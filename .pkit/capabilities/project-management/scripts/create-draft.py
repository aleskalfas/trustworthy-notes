#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — create-draft (DEC-026 workflow wrapper).

Opens a *draft* PR for an issue's feature branch without moving the
issue's lifecycle state (the issue stays in In Progress). Used when CI
should run on the work-in-progress branch before the work is ready for
review. Per DEC-026:

    create-draft <N>

Gates per DEC-026:
  - Membership check (open-mode degrades to no-op).
  - A branch exists per `<type>/<N>-<slug>` (created by start-work).
  - At least one commit on the branch not on `main`.

Side-effects:
  - `gh pr create --draft`.

No issue-state transition; no reviewer assignment; no audit comment
(the PR creation itself is the audit trail).

Exit codes:
  0  draft PR opened (or already exists)
  1  membership refusal
  2  usage error / gate failure / gh failure
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Open a draft PR for an issue's feature branch. Issue stays "
            "in In Progress; no reviewer assignment. Per DEC-026."
        ),
    )
    parser.add_argument("issue_number", type=int)
    parser.add_argument(
        "--title", default=None,
        help="PR title (default: derived from issue title with conventional-commit prefix).",
    )
    parser.add_argument(
        "--body", default=None,
        help="PR body (default: `Closes #<N>` + auto-derived content).",
    )
    parser.add_argument("--base", default="main")
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

    yaml_loader = YAML(typ="safe")
    config = load_adopter_config(capability_root)
    members = _read_members(capability_root, yaml_loader)
    invoker = resolve_invoker_identity(config=config)
    membership = check_membership(members, invoker)
    if not membership.allowed:
        print(membership.refusal_message, file=sys.stderr)
        return 1

    # Gate: branch matching `<type>/<N>-<slug>` exists locally.
    branch = _find_issue_branch(args.issue_number)
    if branch is None:
        print(
            f"error: no local branch matching `*/{args.issue_number}-*` found. "
            f"Run `start-work {args.issue_number}` first to create one.",
            file=sys.stderr,
        )
        return 2

    # Gate: at least one commit not on main.
    if not _branch_has_commits_beyond(branch, args.base):
        print(
            f"error: branch {branch!r} has no commits beyond {args.base!r}. "
            "Commit your work-in-progress before opening a draft PR.",
            file=sys.stderr,
        )
        return 2

    # Idempotence: if a PR already exists for this branch, no-op.
    existing_pr = _find_pr_for_branch(branch, config)
    if existing_pr is not None:
        if existing_pr.get("isDraft"):
            print(
                f"  draft PR #{existing_pr['number']} already exists for {branch!r}; "
                "idempotent skip"
            )
        else:
            print(
                f"  PR #{existing_pr['number']} already exists for {branch!r} "
                f"(state: {existing_pr.get('state')}, draft: {existing_pr.get('isDraft')}). "
                f"No-op."
            )
        return 0

    # Fetch issue for title derivation.
    issue = _gh_get_issue(args.issue_number, config)
    if issue is None:
        return 2
    title = args.title or _derive_pr_title(issue, branch)
    body = args.body or f"Closes #{args.issue_number}\n\nDraft PR for work-in-progress."

    print(f"create-draft: #{args.issue_number}")
    print(f"  branch: {branch}")
    print(f"  base:   {args.base}")
    print(f"  title:  {title}")

    if args.dry_run:
        print("(dry-run: would invoke `gh pr create --draft`.)")
        return 0

    if not args.yes and sys.stdin.isatty():
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    url = _gh_pr_create_draft(branch, args.base, title, body, config)
    if url is None:
        return 3

    print(f"\n[ok] opened draft PR: {url}")
    return 0


# ---- gates / inference -----------------------------------------------


def _find_issue_branch(issue_number: int) -> str | None:
    """Locate a local branch matching `<type>/<N>-<slug>`."""
    try:
        proc = subprocess.run(
            ["git", "branch", "--list", "--format=%(refname:short)"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    pattern = re.compile(rf"^[a-z]+/{issue_number}-[a-z0-9-]+$")
    for line in proc.stdout.splitlines():
        line = line.strip()
        if pattern.match(line):
            return line
    return None


def _branch_has_commits_beyond(branch: str, base: str) -> bool:
    """True if `branch` has commits not in `base`."""
    proc = subprocess.run(
        ["git", "rev-list", "--count", f"{base}..{branch}"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return False
    try:
        return int(proc.stdout.strip()) > 0
    except ValueError:
        return False


def _find_pr_for_branch(branch: str, config: dict) -> dict | None:
    """Return the PR for the head branch, or None."""
    proc = gh_run(
        ["gh", "pr", "list", "--head", branch, "--state", "all",
         "--json", "number,state,isDraft,headRefName"],
        config, check=False,
    )
    if proc.returncode != 0:
        return None
    try:
        prs = json.loads(proc.stdout)
        for pr in prs:
            if pr.get("headRefName") == branch:
                return pr
    except (ValueError, KeyError):
        pass
    return None


def _gh_get_issue(issue_number: int, config: dict) -> dict | None:
    return gh_get_issue(issue_number, config, fields="title")


def _derive_pr_title(issue: dict, branch: str) -> str:
    """Derive a conventional-commits PR title from issue title + branch prefix."""
    title = re.sub(r"^\[[^\]]+\]\s*", "", str(issue.get("title", "")))
    prefix_match = re.match(r"^([a-z]+)/", branch)
    prefix = prefix_match.group(1) if prefix_match else "feat"
    return f"{prefix}: {title}".strip()


# ---- side-effects ----------------------------------------------------


def _gh_pr_create_draft(
    branch: str, base: str, title: str, body: str, config: dict
) -> str | None:
    proc = gh_run(
        ["gh", "pr", "create",
         "--draft",
         "--head", branch,
         "--base", base,
         "--title", title,
         "--body", body],
        config, check=False,
    )
    if proc.returncode != 0:
        print(
            f"error: gh pr create --draft failed: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return None
    return proc.stdout.strip()


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
