#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — handoff-issue (DEC-026 workflow wrapper).

Reassigns an in-flight issue from one team member to another without
changing the issue's lifecycle state. Per DEC-026:

    handoff-issue <N> --to @<new-assignee> --reason "<R>"

Gates per DEC-026:
  - Current user is a team member (DEC-021); open-mode supports the
    operation as self-service ownership transfer.
  - Issue currently in `In Progress` or `Review`.

Side-effects:
  - Posts audit comment: `Handoff: @<from> → @<to> (YYYY-MM-DD, reason: <text>)`
    (idempotent via DEC-024 template-stamp).
  - `gh issue edit --add-assignee <to> --remove-assignee <from>`.
  - No `move-issue` call (no state transition).

Exit codes:
  0  handed off
  1  membership refusal
  2  usage error / gate failure / gh failure
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from ruamel.yaml import YAML

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
from _lib.gh import gh_get_issue, gh_run, load_adopter_config  # noqa: E402
from _lib.membership import (  # noqa: E402
    CAPABILITY_NAME,
    check_membership,
    resolve_capability_root,
    resolve_invoker_identity,
)


AUDIT_STAMP_PREFIX = "<!-- pkit-hook: handoff-issue:"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reassign an in-flight issue from one team member to another. "
            "No state transition; audit comment records the handoff."
        ),
    )
    parser.add_argument("issue_number", type=int)
    parser.add_argument(
        "--to", required=True, dest="new_assignee",
        help="New assignee (`@user` or `user`).",
    )
    parser.add_argument(
        "--reason", required=True,
        help="Reason for the handoff — recorded in the audit comment.",
    )
    parser.add_argument(
        "--capability-root", type=Path, default=None,
        help=f"Default: <repo-root>/.pkit/capabilities/{CAPABILITY_NAME}/.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    capability_root = resolve_capability_root(args.capability_root)
    if capability_root is None:
        print(f"error: {CAPABILITY_NAME} capability not found.", file=sys.stderr)
        return 2

    new_assignee = args.new_assignee.lstrip("@").strip()
    if not new_assignee:
        print("error: --to must name a non-empty assignee.", file=sys.stderr)
        return 2
    reason = args.reason.strip()
    if not reason:
        print(
            "error: --reason must be non-empty (per DEC-026 audit-trail discipline).",
            file=sys.stderr,
        )
        return 2

    yaml_loader = YAML(typ="safe")
    config = load_adopter_config(capability_root)
    members = _read_members(capability_root, yaml_loader)
    invoker = resolve_invoker_identity(config=config)
    membership = check_membership(members, invoker)
    if not membership.allowed:
        # Open-mode falls through; closed-mode refuses.
        print(membership.refusal_message, file=sys.stderr)
        return 1

    issue = _gh_get_issue(args.issue_number, config)
    if issue is None:
        return 2

    # Gate: issue is In Progress or Review (state inferred from milestone/labels
    # in the substrate; here we use a simple heuristic — issue must be open).
    state = str(issue.get("state", "")).lower()
    if state != "open":
        print(
            f"error: issue #{args.issue_number} is in state {state!r}; "
            "handoff only applies to open issues currently in In Progress or Review.",
            file=sys.stderr,
        )
        return 2

    # Determine current assignee (for the audit comment + remove flag).
    assignees = issue.get("assignees") or []
    current_assignees = [
        a.get("login") for a in assignees
        if isinstance(a, dict) and a.get("login")
    ]
    from_assignee = current_assignees[0] if current_assignees else "(unassigned)"

    if from_assignee == new_assignee:
        print(
            f"  #{args.issue_number} is already assigned to @{new_assignee}; "
            "no-op."
        )
        return 0

    print(f"handoff-issue: #{args.issue_number}")
    print(f"  from:   @{from_assignee}")
    print(f"  to:     @{new_assignee}")
    print(f"  reason: {reason}")

    if args.dry_run:
        print("(dry-run: would post audit comment + reassign.)")
        return 0

    if not args.yes and sys.stdin.isatty():
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    # Audit comment (idempotent — stamp includes from/to so re-runs are no-op).
    today = dt.date.today().isoformat()
    audit_stamp = f"{AUDIT_STAMP_PREFIX}{from_assignee}->{new_assignee} -->"
    audit_body = (
        f"{audit_stamp}\n\n"
        f"Handoff: @{from_assignee} → @{new_assignee} ({today}, reason: {reason})"
    )
    if not _post_audit_comment_idempotent(
        args.issue_number, audit_stamp, audit_body, config
    ):
        return 2

    # Reassign.
    if not _reassign(args.issue_number, from_assignee, new_assignee, config):
        return 2

    print(f"\n[ok] handed off #{args.issue_number}: @{from_assignee} → @{new_assignee}")
    return 0


# ---- helpers -----------------------------------------------------------


def _gh_get_issue(issue_number: int, config: dict) -> dict | None:
    return gh_get_issue(
        issue_number, config,
        fields="title,state,assignees,labels,milestone",
    )


def _post_audit_comment_idempotent(
    issue_number: int, stamp_marker: str, body: str, config: dict
) -> bool:
    proc = gh_run(
        ["gh", "issue", "view", str(issue_number), "--json", "comments"],
        config, check=False,
    )
    if proc.returncode == 0:
        try:
            data = json.loads(proc.stdout)
            for c in data.get("comments", []):
                if stamp_marker in (c.get("body") or ""):
                    print("  handoff audit comment already present; idempotent skip")
                    return True
        except (ValueError, KeyError, TypeError):
            pass
    proc = gh_run(
        ["gh", "issue", "comment", str(issue_number), "--body", body],
        config, check=False,
    )
    if proc.returncode != 0:
        print(
            f"error: gh issue comment failed: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def _reassign(
    issue_number: int, from_assignee: str, to_assignee: str, config: dict
) -> bool:
    cmd = ["gh", "issue", "edit", str(issue_number), "--add-assignee", to_assignee]
    if from_assignee and from_assignee != "(unassigned)":
        cmd += ["--remove-assignee", from_assignee]
    proc = gh_run(cmd, config, check=False)
    if proc.returncode != 0:
        print(
            f"error: gh issue edit reassignment failed: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def _read_members(capability_root: Path, yaml_loader: YAML) -> list[dict]:
    path = capability_root / "project" / "members.yaml"
    if not path.is_file():
        return []
    try:
        data = yaml_loader.load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    members = data.get("members") if isinstance(data, dict) else None
    return members if isinstance(members, list) else []


if __name__ == "__main__":
    sys.exit(main())
