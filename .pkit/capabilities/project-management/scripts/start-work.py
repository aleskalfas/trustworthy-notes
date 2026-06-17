#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — start-work (DEC-026 workflow wrapper).

Transitions an issue Backlog → In Progress by creating the feature
branch + setting the assignee. Per DEC-026:

    start-work <N>

Gates per DEC-026:
  - Current user is a team member (DEC-021); open-mode degrades to no-op.
  - Issue not assigned to someone else (hard refusal points at handoff-issue).
  - If a branch exists, matches `<type>/<N>-<slug>` (idempotent).

Side-effects:
  - Creates branch `<type>/<N>-<kebab-slug>` (type from issue's type:*
    label; slug from the issue title).
  - Sets assignee to the current invoker.
  - Composes over `move-issue.py --to in-progress`.

Exit codes:
  0  in-progress
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


# Default mapping of `type:*` label to conventional-commit prefix.
TYPE_LABEL_TO_PREFIX = {
    "type:feature": "feat",
    "type:bug": "fix",
    "type:docs": "docs",
    "type:refactor": "refactor",
    "type:test": "test",
    "type:maintenance": "chore",
    "type:chore": "chore",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Start work on an issue: create the feature branch, set "
            "assignee, transition Backlog → In Progress. Composes over "
            "move-issue (per DEC-026)."
        ),
    )
    parser.add_argument("issue_number", type=int)
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

    # Fetch issue.
    issue = _gh_get_issue(args.issue_number, config)
    if issue is None:
        return 2

    # Gate: not assigned to someone else.
    assignees = issue.get("assignees") or []
    other_assignees = [
        a.get("login") for a in assignees
        if isinstance(a, dict)
        and a.get("login")
        and a.get("login") != invoker.github_login
    ]
    if other_assignees:
        print(
            f"error: issue #{args.issue_number} is assigned to "
            f"{', '.join('@' + a for a in other_assignees)}. "
            f"Use `handoff-issue {args.issue_number}` to take ownership.",
            file=sys.stderr,
        )
        return 2

    # Derive branch name from issue title + type:* label.
    title = str(issue.get("title", ""))
    labels = [
        lbl.get("name", "") if isinstance(lbl, dict) else str(lbl)
        for lbl in (issue.get("labels") or [])
    ]
    prefix = _derive_branch_prefix(labels)
    if prefix is None:
        print(
            f"error: issue #{args.issue_number} has no recognised type:* label. "
            f"Expected one of {', '.join(sorted(TYPE_LABEL_TO_PREFIX))}.",
            file=sys.stderr,
        )
        return 2
    slug = _slug_from_title(title)
    branch_name = f"{prefix}/{args.issue_number}-{slug}"

    # Idempotence: if a matching branch already exists locally, no-op.
    existing = _existing_branch_for_issue(args.issue_number)
    if existing is not None:
        if existing == branch_name:
            print(f"  branch {branch_name!r} already exists; idempotent skip")
        elif _branch_matches_shape(existing, args.issue_number):
            print(f"  branch {existing!r} exists with valid shape; using it")
            branch_name = existing
        else:
            print(
                f"error: branch {existing!r} exists for #{args.issue_number} "
                f"but doesn't match the expected shape `<type>/{args.issue_number}-<slug>`. "
                "Rename or delete the branch and re-run.",
                file=sys.stderr,
            )
            return 2

    print(f"start-work: #{args.issue_number}")
    print(f"  branch:    {branch_name}")
    print(f"  assignee:  {invoker.github_login or '(unknown invoker)'}")

    if args.dry_run:
        print("(dry-run: would create branch, set assignee, and call move-issue --to in-progress.)")
        return 0

    if not args.yes and sys.stdin.isatty():
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    # Create branch (idempotent — git checkout -b on existing branch fails;
    # we check existence first).
    if existing is None:
        if not _create_branch(branch_name):
            return 2
    else:
        print(f"  branch {branch_name!r} already in repo; skipping creation")

    # Set assignee.
    if invoker.github_login and not _set_assignee(args.issue_number, invoker.github_login, config):
        print(
            "[warn] branch created but failed to set assignee. "
            "Run `gh issue edit --add-assignee` manually and re-run move-issue.",
            file=sys.stderr,
        )

    # Compose over move-issue.
    rc = _invoke_move_issue(args.issue_number, "in-progress", args.capability_root)
    if rc != 0:
        return rc

    print(f"\n[ok] started work on #{args.issue_number} (branch: {branch_name})")
    return 0


# ---- helpers -----------------------------------------------------------


def _gh_get_issue(issue_number: int, config: dict) -> dict | None:
    return gh_get_issue(issue_number, config, fields="title,labels,assignees,state")


def _derive_branch_prefix(labels: list[str]) -> str | None:
    """Pick the conventional-commit prefix from the issue's type:* label."""
    for label in labels:
        if label in TYPE_LABEL_TO_PREFIX:
            return TYPE_LABEL_TO_PREFIX[label]
    return None


def _slug_from_title(title: str) -> str:
    """Derive a kebab-case slug from an issue title.

    Strips the `[Type]` prefix, removes punctuation, lowercases, joins
    words with hyphens. Trims to 5 words for branch-name readability.
    """
    # Strip [Type] prefix
    title = re.sub(r"^\[[^\]]+\]\s*", "", title)
    # Lowercase + replace non-alphanumeric with spaces, then collapse
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", title).strip().lower()
    words = cleaned.split()[:5]  # cap at 5 words
    return "-".join(words) if words else "untitled"


def _existing_branch_for_issue(issue_number: int) -> str | None:
    """Find a local branch matching `*/<N>-*` for the issue. Returns first match or None."""
    try:
        proc = subprocess.run(
            ["git", "branch", "--list", "--format=%(refname:short)"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    pattern = re.compile(rf"^[a-z]+/{issue_number}(-|$)")
    for line in proc.stdout.splitlines():
        line = line.strip()
        if pattern.match(line):
            return line
    return None


def _branch_matches_shape(name: str, issue_number: int) -> bool:
    return bool(re.match(rf"^[a-z]+/{issue_number}-[a-z0-9-]+$", name))


def _create_branch(name: str) -> bool:
    proc = subprocess.run(
        ["git", "checkout", "-b", name],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        print(
            f"error: git checkout -b {name!r} failed: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    print(f"  created branch: {name}")
    return True


def _set_assignee(issue_number: int, login: str, config: dict) -> bool:
    proc = gh_run(
        ["gh", "issue", "edit", str(issue_number), "--add-assignee", login],
        config, check=False,
    )
    if proc.returncode != 0:
        print(
            f"error: gh issue edit --add-assignee failed: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def _invoke_move_issue(
    issue_number: int, target: str, capability_root_arg: Path | None
) -> int:
    cmd = [
        sys.executable,
        str(_HERE / "move-issue.py"),
        str(issue_number),
        "--to", target,
        "--yes",
    ]
    if capability_root_arg is not None:
        cmd += ["--capability-root", str(capability_root_arg)]
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


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
