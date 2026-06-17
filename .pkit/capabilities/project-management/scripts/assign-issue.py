#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — assign-issue (verb-subject per DEC-020).

Reassigns an existing GitHub issue. Default semantics per
DEC-019:
  * Membership-gated (DEC-021).
  * `--me` shorthand assigns to the resolved invoker identity.
  * `--assignee <login>` assigns to a specific user (or multiple via
    comma-separated list, matching `gh`'s native multiplicity).
  * `--unassign <login>` removes a specific assignee.
  * `--replace` (default) replaces the assignee set entirely; without
    it, the script adds without removing existing assignees.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/assign-issue.py 42 --me

Or via the dispatcher:
  pkit project-management assign-issue 42 --me

Exit codes:
  0  reassigned (or dry-run reported)
  1  membership refusal
  2  usage error
  3  gh failure
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
from _lib.gh import gh_run, load_adopter_config  # noqa: E402
from _lib.membership import (  # noqa: E402
    CAPABILITY_NAME,
    check_membership,
    resolve_capability_root,
    resolve_invoker_identity,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reassign a GitHub issue. Per DEC-019, every issue has an "
            "assignee — this script changes who it is."
        ),
    )
    parser.add_argument(
        "issue_number",
        type=int,
        help="GitHub issue number.",
    )
    parser.add_argument(
        "--me",
        action="store_true",
        help="Assign to the resolved invoker identity (sugar for --assignee=<my-login>).",
    )
    parser.add_argument(
        "--assignee",
        default=None,
        help="Login to assign. Multiple via comma-separated list.",
    )
    parser.add_argument(
        "--unassign",
        default=None,
        help=(
            "Login to unassign. Multiple via comma-separated list. "
            "Can combine with --assignee for swap-in-one-call."
        ),
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        default=True,
        help=(
            "Replace the assignee set with the new value(s); default. "
            "Pass --no-replace to add-without-removing."
        ),
    )
    parser.add_argument(
        "--no-replace",
        dest="replace",
        action="store_false",
        help="Add new assignees without removing existing ones.",
    )
    parser.add_argument(
        "--capability-root",
        type=Path,
        default=None,
        help=(
            "Path to the installed capability's directory "
            f"(default: <repo-root>/.pkit/capabilities/{CAPABILITY_NAME}/)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done; do not invoke gh.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    args = parser.parse_args()

    capability_root = resolve_capability_root(args.capability_root)
    if capability_root is None:
        print(
            f"error: {CAPABILITY_NAME} capability not found.",
            file=sys.stderr,
        )
        return 2

    yaml_loader = YAML(typ="safe")
    config = load_adopter_config(capability_root)
    members = _read_members(capability_root, yaml_loader)
    invoker = resolve_invoker_identity(config=config)
    membership = check_membership(members, invoker)
    if not membership.allowed:
        print(membership.refusal_message, file=sys.stderr)
        return 1

    # Resolve the assignee/unassign sets.
    add_set: list[str] = []
    if args.me:
        if not invoker.github_login:
            print(
                "error: --me requested but the invoker's github_login could "
                "not be resolved (gh auth not configured?).",
                file=sys.stderr,
            )
            return 2
        add_set.append(invoker.github_login)
    if args.assignee:
        add_set.extend(s.strip() for s in args.assignee.split(",") if s.strip())

    remove_set: list[str] = []
    if args.unassign:
        remove_set.extend(s.strip() for s in args.unassign.split(",") if s.strip())

    if not add_set and not remove_set:
        print(
            "error: nothing to do. Pass --me, --assignee, or --unassign.",
            file=sys.stderr,
        )
        return 2

    # Fetch current assignees so we can preview.
    issue = _gh_get_issue_assignees(args.issue_number, config)
    if issue is None:
        return 3
    current = [
        a.get("login", "") if isinstance(a, dict) else str(a)
        for a in (issue.get("assignees") or [])
    ]

    # Compute target set.
    if args.replace and add_set:
        target = list(dict.fromkeys(add_set))  # dedupe, preserve order
    else:
        target = list(dict.fromkeys(current + add_set))
    # Apply removals.
    target = [a for a in target if a not in remove_set]

    print(f"issue #{args.issue_number}:")
    print(f"  current assignees: {', '.join(current) or '<none>'}")
    print(f"  target assignees:  {', '.join(target) or '<none>'}")

    if target == current:
        print("\n[noop] target matches current; nothing to change.")
        return 0

    if args.dry_run:
        print("\n[dry-run] gh would be invoked; nothing written.")
        return 0

    if not args.yes and sys.stdin.isatty():
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    # Compute deltas.
    to_add = [a for a in target if a not in current]
    to_remove = [a for a in current if a not in target]

    ok = _gh_edit_assignees(args.issue_number, add=to_add, remove=to_remove, config=config)
    if not ok:
        return 3

    print(f"\n[ok] reassigned #{args.issue_number}: {', '.join(target) or '<none>'}")
    return 0


def _gh_get_issue_assignees(issue_number: int, config: dict) -> dict | None:
    try:
        proc = gh_run(
            [
                "gh",
                "issue",
                "view",
                str(issue_number),
                "--json",
                "assignees",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        print("error: `gh` not on PATH.", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(
            f"error: gh issue view {issue_number} failed.\n"
            f"stderr: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def _gh_edit_assignees(
    issue_number: int, *, add: list[str], remove: list[str]
, config: dict) -> bool:
    """Apply assignee deltas via `gh issue edit`."""
    if not add and not remove:
        return True
    cmd = ["gh", "issue", "edit", str(issue_number)]
    for login in add:
        cmd.extend(["--add-assignee", login])
    for login in remove:
        cmd.extend(["--remove-assignee", login])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False
    if proc.returncode != 0:
        print(
            f"error: gh issue edit failed (exit {proc.returncode}).\n"
            f"stderr: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def _read_yaml(path: Path, yaml_loader: YAML) -> dict:
    if not path.is_file():
        return {}
    try:
        data = yaml_loader.load(path.read_text(encoding="utf-8"))
    except (OSError, YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_members(capability_root: Path, yaml_loader: YAML) -> list[dict]:
    data = _read_yaml(capability_root / "project" / "members.yaml", yaml_loader)
    members = data.get("members") or []
    return members if isinstance(members, list) else []


if __name__ == "__main__":
    sys.exit(main())
