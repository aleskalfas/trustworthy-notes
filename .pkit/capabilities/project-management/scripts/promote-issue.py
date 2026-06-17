#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — promote-issue (DEC-026 workflow wrapper).

Promotes an issue from Todo → Backlog, recording the authorisation source
as an audit comment. Per DEC-026 (as amended for issue #61):

    promote-issue <N> [--milestone "<M>"] --reason "<R>"

Two paths:
  - `--milestone` given → resolves <M> to an OPEN milestone (by number or
    exact title), attaches it via `gh issue edit --milestone`, posts the
    audit comment, then calls `move-issue --to backlog`.
  - `--milestone` omitted → promotes on `--reason` alone: posts the same
    audit comment (already milestone-free), skips `_attach_milestone`, then
    calls `move-issue --to backlog`. No milestone resolution is attempted.

Gates per DEC-026:
  - `--reason` non-empty (the authorisation source — typically the
    user's verbal in-session request; required in both paths).
  - When `--milestone` is given, `<M>` must match the exact title of an
    OPEN milestone in the repo (given-but-unresolvable is still an error;
    it is never silently downgraded to milestone-free).
  - Current Status = Todo (delegated to `move-issue`'s state machine).

Composes over `move-issue.py`: this wrapper writes the audit comment
first, then invokes `move-issue --to backlog`. The audit comment is
idempotent via DEC-024's template-stamp discipline.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/promote-issue.py 42 --reason "PM approved"
  uv run --script .pkit/capabilities/project-management/scripts/promote-issue.py 42 --milestone "v1" --reason "PM approved"

Or via the dispatcher (per COR-021):
  pkit project-management promote-issue 42 --reason "PM approved"
  pkit project-management promote-issue 42 --milestone "v1" --reason "PM approved"

Exit codes:
  0  promoted
  1  membership refusal
  2  usage error / gate failure / gh failure
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ruamel.yaml import YAML

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
from _lib.gh import gh_run, load_adopter_config  # noqa: E402
from _lib.milestone import resolve_milestone  # noqa: E402
from _lib.membership import (  # noqa: E402
    CAPABILITY_NAME,
    check_membership,
    resolve_capability_root,
    resolve_invoker_identity,
)


AUDIT_STAMP = "<!-- pkit-hook: promote-issue -->"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Promote an issue Todo → Backlog by attaching a Milestone "
            "and posting an audit comment with the authorisation source. "
            "Composes over move-issue (per DEC-026 / DEC-020)."
        ),
    )
    parser.add_argument(
        "issue_number",
        type=int,
        help="GitHub issue number to promote.",
    )
    parser.add_argument(
        "--milestone",
        default=None,
        help=(
            "OPEN milestone to attach. Accepts the milestone number "
            "(e.g. `6`) or its exact title (e.g. `Milestone 1: ...`). "
            "Optional — omit to promote on --reason alone (no milestone "
            "attached). When given, must match an OPEN milestone exactly; "
            "an unresolvable value is always an error."
        ),
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Authorisation source — typically the user's in-session request.",
    )
    parser.add_argument(
        "--capability-root",
        type=Path,
        default=None,
        help=f"Path to the installed capability's directory (default: <repo-root>/.pkit/capabilities/{CAPABILITY_NAME}/).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan; do not invoke gh or move-issue.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    args = parser.parse_args()

    capability_root = resolve_capability_root(args.capability_root)
    if capability_root is None:
        print(f"error: {CAPABILITY_NAME} capability not found.", file=sys.stderr)
        return 2

    yaml_loader = YAML(typ="safe")
    config = load_adopter_config(capability_root)
    members = _read_members(capability_root, yaml_loader)
    invoker = resolve_invoker_identity(config=config)
    membership = check_membership(members, invoker)
    if not membership.allowed:
        print(membership.refusal_message, file=sys.stderr)
        return 1

    # Gate: --reason non-empty (argparse `required` covers empty
    # presence, but the value may still be whitespace-only).
    reason = args.reason.strip()
    if not reason:
        print(
            "error: --reason must be non-empty (per DEC-026 audit-trail discipline).",
            file=sys.stderr,
        )
        return 2

    # Resolve --milestone when given (accepts number OR title; per #217).
    # The title is what downstream `gh issue edit --milestone` wants, so
    # normalise to the title form regardless of input shape.
    # When --milestone is omitted, skip resolution entirely — promoting on
    # --reason alone is a valid path per the DEC-026 #61 amendment.
    milestone_title: str | None = None
    if args.milestone is not None:
        resolved = resolve_milestone(str(args.milestone), config)
        if resolved is None:
            print(
                f"error: milestone {args.milestone!r} did not match any OPEN "
                "milestone (tried as number, then as title). "
                "List with `gh api repos/<owner>/<repo>/milestones?state=open`.",
                file=sys.stderr,
            )
            return 2
        milestone_title = resolved.title

    print(f"promote-issue: #{args.issue_number}")
    if milestone_title is not None:
        print(f"  milestone: {milestone_title}")
    else:
        print("  milestone: (none — promoting on --reason alone)")
    print(f"  reason:    {reason}")

    if args.dry_run:
        if milestone_title is not None:
            print(
                "(dry-run: would post audit comment, attach milestone "
                f"{milestone_title!r}, and call move-issue --to backlog.)"
            )
        else:
            print(
                "(dry-run: would post audit comment and call move-issue --to backlog "
                "(no milestone — --reason-only path).)"
            )
        return 0

    if not args.yes and sys.stdin.isatty():
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    # Audit comment (idempotent via stamp marker). The text is milestone-free
    # by design — it works for both the milestone-given and milestone-omitted
    # paths without a template fork.
    audit_body = (
        f"{AUDIT_STAMP}\n\nPromoted Todo → Backlog by PM on user's "
        f"in-session request: {reason}"
    )
    if not _post_audit_comment_idempotent(args.issue_number, audit_body, config):
        return 2

    # Attach the milestone via gh issue edit — only when one was given.
    if milestone_title is not None:
        if not _attach_milestone(args.issue_number, milestone_title, config):
            return 2

    # Detect the issue's current state before calling move-issue. If
    # the issue is already at Backlog or further (cascade may have
    # walked it past Todo), the transition is a no-op — skip the
    # move-issue invocation and exit 0 with an idempotent-skip note.
    # Per #219: previously this path errored with "no transition
    # backlog → backlog declared" and exited 2, forcing callers to
    # special-case the already-promoted state.
    current_state = _detect_state_from_labels(args.issue_number, config)
    if current_state in ("backlog", "in-progress", "review", "done"):
        if milestone_title is not None:
            idempotent_detail = "milestone reattached, audit recorded"
        else:
            idempotent_detail = "audit recorded"
        print(
            f"\n[ok] #{args.issue_number} already at state:{current_state} "
            f"({idempotent_detail}; no state transition needed)."
        )
        return 0

    # Compose over move-issue for the actual state transition.
    rc = _invoke_move_issue(args.issue_number, "backlog", args.capability_root)
    if rc != 0:
        applied = "audit comment + milestone" if milestone_title is not None else "audit comment"
        print(
            f"[warn] {applied} applied; move-issue exited {rc}. "
            "Re-run this wrapper or run `move-issue --to backlog` to complete the transition.",
            file=sys.stderr,
        )
        return rc

    if milestone_title is not None:
        print(f"\n[ok] promoted #{args.issue_number} Todo → Backlog (milestone: {milestone_title})")
    else:
        print(f"\n[ok] promoted #{args.issue_number} Todo → Backlog (no milestone)")
    return 0


def _detect_state_from_labels(issue_number: int, config: dict) -> str | None:
    """Read the issue's `state:*` label and return the bare state name.

    Returns one of "todo", "backlog", "in-progress", "review", "done",
    or None if no recognised state label is present (or the gh call
    fails). Used by `promote-issue` for the idempotent-skip path on
    already-promoted issues (per #219).
    """
    try:
        proc = gh_run(
            ["gh", "issue", "view", str(issue_number), "--json", "labels"],
            config,
            check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except (ValueError, KeyError, TypeError):
        return None
    labels = data.get("labels") or []
    for label in labels:
        name = label.get("name", "") if isinstance(label, dict) else ""
        if name.startswith("state:"):
            return name.removeprefix("state:")
    return None


# ---- gates --------------------------------------------------------------
#
# `_milestone_exists_open` + `_parse_concatenated_json_arrays` were
# removed in #217 — both moved to `_lib/milestone.py` along with the
# `resolve_milestone(arg, config)` helper that handles either number
# or title input. Call sites switched to the lib resolver.


# ---- side-effects ------------------------------------------------------


def _post_audit_comment_idempotent(
    issue_number: int, body: str, config: dict
) -> bool:
    """Post an audit comment if a comment with the same stamp doesn't already exist."""
    # Check existing comments for the stamp marker.
    proc = gh_run(
        ["gh", "issue", "view", str(issue_number), "--json", "comments"],
        config,
        check=False,
    )
    if proc.returncode == 0:
        try:
            data = json.loads(proc.stdout)
            for c in data.get("comments", []):
                if AUDIT_STAMP in (c.get("body") or ""):
                    print(f"  audit comment with stamp already exists; idempotent skip")
                    return True
        except (ValueError, KeyError, TypeError):
            pass

    proc = gh_run(
        ["gh", "issue", "comment", str(issue_number), "--body", body],
        config,
        check=False,
    )
    if proc.returncode != 0:
        print(
            f"error: gh issue comment failed: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def _attach_milestone(issue_number: int, title: str, config: dict) -> bool:
    proc = gh_run(
        ["gh", "issue", "edit", str(issue_number), "--milestone", title],
        config,
        check=False,
    )
    if proc.returncode != 0:
        print(
            f"error: gh issue edit --milestone failed: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def _invoke_move_issue(
    issue_number: int, target: str, capability_root_arg: Path | None
) -> int:
    """Shell out to `move-issue.py --to <target>` as the substrate transition."""
    cmd = [
        sys.executable,
        str(_HERE / "move-issue.py"),
        str(issue_number),
        "--to", target,
        "--bypass",  # Todo → Backlog is bypassable-with-audit per workflow.yaml
        "--bypass-reason", "promoted via promote-issue wrapper (audit comment already posted)",
        "--yes",
    ]
    if capability_root_arg is not None:
        cmd += ["--capability-root", str(capability_root_arg)]
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


# ---- helpers -----------------------------------------------------------


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
