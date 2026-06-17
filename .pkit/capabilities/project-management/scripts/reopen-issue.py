#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — reopen-issue (verb-subject per DEC-020).

Reopens a closed GitHub issue. Optional `--reason` records why; the
script posts an audit comment + invokes `gh issue reopen`. Membership
gate per DEC-021 runs at startup.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/reopen-issue.py 42

Or via the dispatcher (per COR-021):
  pkit project-management reopen-issue 42 --reason "regressed"

Exit codes:
  0  reopened (or dry-run reported)
  1  membership refusal
  2  usage error (issue not found; already open)
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
from _lib.gh import gh_get_issue, gh_run, load_adopter_config  # noqa: E402
from _lib.membership import (  # noqa: E402
    CAPABILITY_NAME,
    check_membership,
    resolve_capability_root,
    resolve_invoker_identity,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reopen a closed GitHub issue.",
    )
    parser.add_argument(
        "issue_number",
        type=int,
        help="GitHub issue number to reopen.",
    )
    parser.add_argument(
        "--reason",
        default=None,
        help="Free-text reason recorded in the audit comment.",
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
        help="Print the plan; do not invoke gh.",
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

    issue = _gh_get_issue(args.issue_number, config)
    if issue is None:
        return 2

    state = str(issue.get("state", "")).lower()
    title = str(issue.get("title", ""))

    print(f"reopen-issue: #{args.issue_number}")
    print(f"  title:         {title}")
    print(f"  current state: {state}")
    if args.reason:
        print(f"  reason:        {args.reason}")

    if state != "closed":
        print("\n[noop] issue is already open.")
        return 0

    if args.dry_run:
        print("\n[dry-run] gh would be invoked; nothing written.")
        return 0
    if not args.yes and sys.stdin.isatty():
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    if args.reason:
        comment_body = (
            f"[reopen] {args.reason}\n\n"
            "Reopened via `pkit project-management reopen-issue`."
        )
        if not _gh_comment(args.issue_number, comment_body, config):
            return 3

    if not _gh_reopen(args.issue_number, config):
        return 3

    print(f"\n[ok] reopened #{args.issue_number}.")
    return 0


def _gh_get_issue(issue_number: int, config: dict) -> dict | None:
    return gh_get_issue(issue_number, config, fields="title,state")


def _gh_comment(issue_number: int, body: str, config: dict) -> bool:
    try:
        proc = gh_run(
            ["gh", "issue", "comment", str(issue_number), "--body", body],
            config,
            check=False,
        )
    except FileNotFoundError:
        return False
    return proc.returncode == 0


def _gh_reopen(issue_number: int, config: dict) -> bool:
    try:
        proc = gh_run(
            ["gh", "issue", "reopen", str(issue_number)],
            config,
            check=False,
        )
    except FileNotFoundError:
        return False
    if proc.returncode != 0:
        print(
            f"error: gh issue reopen failed (exit {proc.returncode}).\n"
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
