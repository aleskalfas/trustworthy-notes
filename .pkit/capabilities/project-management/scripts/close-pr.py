#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — close-pr (verb-subject per DEC-020).

Closes a PR without merging (`gh pr close`). Optional `--reason`
records why; the script posts a comment with the reason before
closing. Membership gate per DEC-021 runs at startup.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/close-pr.py 99 --reason "superseded by #142"

Or via the dispatcher (per COR-021):
  pkit project-management close-pr 99 --reason "..."

Exit codes:
  0  closed (or dry-run reported)
  1  membership refusal
  2  usage error (PR not found)
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
        description="Close a PR without merging.",
    )
    parser.add_argument(
        "pr_number",
        type=int,
        help="GitHub PR number.",
    )
    parser.add_argument(
        "--reason",
        default=None,
        help="Free-text reason recorded in the closing comment.",
    )
    parser.add_argument(
        "--delete-branch",
        action="store_true",
        help="Pass --delete-branch to gh pr close (deletes the source branch).",
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

    pr = _gh_get_pr(args.pr_number, config)
    if pr is None:
        return 2

    title = str(pr.get("title", ""))
    state = str(pr.get("state", "")).lower()

    print(f"close-pr: #{args.pr_number}")
    print(f"  title: {title}")
    print(f"  state: {state}")
    if args.reason:
        print(f"  reason: {args.reason}")
    if args.delete_branch:
        print("  delete branch: yes")

    if state != "open":
        print(f"\n[noop] PR already in state {state!r}.")
        return 0

    if args.dry_run:
        print("\n[dry-run] gh would be invoked; nothing written.")
        return 0
    if not args.yes and sys.stdin.isatty():
        reply = input("Close the PR? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    if args.reason:
        comment_body = (
            f"[close-pr] {args.reason}\n\n"
            "Closed via `pkit project-management close-pr`."
        )
        if not _gh_pr_comment(args.pr_number, comment_body, config):
            return 3

    if not _gh_pr_close(args.pr_number, delete_branch=args.delete_branch, config=config):
        return 3

    print(f"\n[ok] closed PR #{args.pr_number}.")
    return 0


def _gh_get_pr(pr_number: int, config: dict) -> dict | None:
    try:
        proc = gh_run(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--json",
                "title,state,url",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        print("error: `gh` not on PATH.", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(
            f"error: gh pr view {pr_number} failed.\n"
            f"stderr: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def _gh_pr_comment(pr_number: int, body: str, config: dict) -> bool:
    try:
        proc = gh_run(
            ["gh", "pr", "comment", str(pr_number), "--body", body],
            config,
            check=False,
        )
    except FileNotFoundError:
        return False
    return proc.returncode == 0


def _gh_pr_close(pr_number: int, *, delete_branch: bool, config: dict) -> bool:
    cmd = ["gh", "pr", "close", str(pr_number)]
    if delete_branch:
        cmd.append("--delete-branch")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False
    if proc.returncode != 0:
        print(
            f"error: gh pr close failed (exit {proc.returncode}).\n"
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
