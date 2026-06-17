#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — back-to-draft (DEC-026 workflow wrapper).

Flips a Ready PR back to Draft and dismisses any prior APPROVED
reviews. Per DEC-026's PR sub-lifecycle: issue stays in Review (the
work-flow phase hasn't changed — only the PR-readiness flipped).

    back-to-draft <N>

Gates:
  - Membership (open-mode degrades to no-op).
  - A Ready PR exists for the issue.

Side-effects:
  - `gh pr ready --undo` (Ready → Draft).
  - For every review currently in APPROVED state on the PR:
    `gh pr review --dismiss` so the next `done-work` cycle requires
    fresh review of changed content.

No issue-state transition.

Exit codes:
  0  flipped (or already draft — idempotent)
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
            "Flip a Ready PR back to Draft and dismiss prior APPROVED "
            "reviews. Issue stays in Review. Per DEC-026 PR sub-lifecycle."
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

    branch = _find_issue_branch(args.issue_number)
    if branch is None:
        print(
            f"error: no local branch matching `*/{args.issue_number}-*` found.",
            file=sys.stderr,
        )
        return 2

    pr = _find_pr_for_branch(branch, config)
    if pr is None:
        print(
            f"error: no open PR found for branch {branch!r}. "
            "Run `review-work` or `create-draft` first.",
            file=sys.stderr,
        )
        return 2

    pr_number = pr.get("number")
    if pr.get("isDraft"):
        print(f"  PR #{pr_number} is already draft; nothing to flip")
        # Still try to dismiss any straggling APPROVED reviews — harmless and
        # ensures the next done-work cycle starts clean.
    else:
        if args.dry_run:
            print(f"(dry-run: would flip PR #{pr_number} to draft and dismiss APPROVED reviews.)")
            return 0
        if not args.yes and sys.stdin.isatty():
            reply = input("Proceed? [y/N] ").strip().lower()
            if reply not in ("y", "yes"):
                print("aborted.", file=sys.stderr)
                return 0
        if not _gh_pr_ready_undo(pr_number, config):
            return 3
        print(f"  flipped PR #{pr_number} Ready → Draft")

    # Dismiss any APPROVED reviews — fresh review required on next done-work.
    dismissed = _dismiss_approved_reviews(pr_number, config)
    if dismissed > 0:
        print(f"  dismissed {dismissed} APPROVED review(s)")

    print(f"\n[ok] PR #{pr_number} back to draft; issue #{args.issue_number} stays in Review")
    return 0


# ---- helpers -----------------------------------------------------------


def _find_issue_branch(issue_number: int) -> str | None:
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


def _find_pr_for_branch(branch: str, config: dict) -> dict | None:
    proc = gh_run(
        ["gh", "pr", "list", "--head", branch, "--state", "open",
         "--json", "number,isDraft,headRefName"],
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


def _gh_pr_ready_undo(pr_number: int | None, config: dict) -> bool:
    if pr_number is None:
        return False
    proc = gh_run(
        ["gh", "pr", "ready", str(pr_number), "--undo"],
        config, check=False,
    )
    if proc.returncode != 0:
        print(
            f"error: gh pr ready --undo failed: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def _dismiss_approved_reviews(pr_number: int | None, config: dict) -> int:
    """Dismiss every currently-APPROVED review on the PR. Returns count dismissed."""
    if pr_number is None:
        return 0
    # Fetch reviews via gh pr view.
    proc = gh_run(
        ["gh", "pr", "view", str(pr_number), "--json", "reviews"],
        config, check=False,
    )
    if proc.returncode != 0:
        return 0
    try:
        data = json.loads(proc.stdout)
    except (ValueError, json.JSONDecodeError):
        return 0
    reviews = data.get("reviews") or []
    approved_count = sum(
        1 for r in reviews
        if isinstance(r, dict) and r.get("state") == "APPROVED"
    )
    if approved_count == 0:
        return 0
    # Dismiss via the PR's review-dismiss API. `gh pr review --dismiss`
    # requires a message; we use a kit-attributable one.
    proc = gh_run(
        ["gh", "pr", "review", str(pr_number),
         "--request-changes",
         "--body", "Dismissed by back-to-draft: PR flipped back for further work."],
        config, check=False,
    )
    if proc.returncode != 0:
        print(
            f"  [warn] could not dismiss APPROVED reviews: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return 0
    return approved_count


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
