#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — review-work (DEC-026 workflow wrapper).

Transitions an issue In Progress → Review by opening a ready PR (or
flipping a draft PR to ready) and assigning reviewers. Per DEC-026:

    review-work <N> [--reviewer @<user>] [--require-human]

Gates per DEC-026:
  - Membership (open-mode degrades to no-op).
  - Current branch matches `<type>/<N>-<slug>` AND `<type>` matches
    issue's `type:*` label per DEC-013.
  - PR title is Conventional Commits.

Side-effects:
  - Opens a ready PR via `gh pr create` if none exists for the branch.
  - Flips an existing draft PR to ready via `gh pr ready` if present.
  - Reviewer assignment (v1 ships with simple --reviewer override path;
    full DEC-027 mode resolution lands in Phase D).
  - Composes over `move-issue.py --to review`.

Exit codes:
  0  PR ready + issue in Review
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
from _lib.review_mode import (  # noqa: E402
    resolve_mode,
    reviewer_role_from_config,
    role_based_reviewers,
)


# Same mapping start-work uses.
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
            "Open or flip-ready a PR for an issue; transition issue "
            "In Progress → Review. Composes over move-issue per DEC-026."
        ),
    )
    parser.add_argument("issue_number", type=int)
    parser.add_argument(
        "--reviewer", action="append", default=[],
        help="Reviewer to assign (repeatable). May be a @user, user, or team.",
    )
    parser.add_argument(
        "--require-human", action="store_true",
        help=(
            "Force human-mode review even when project config defaults to "
            "agent mode. (Phase D — DEC-027 — wires the full mode-resolution "
            "algorithm; this flag is a v1 forward-compat placeholder.)"
        ),
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

    # Find local branch for issue + validate shape.
    branch = _find_issue_branch(args.issue_number)
    if branch is None:
        print(
            f"error: no local branch matching `*/{args.issue_number}-*` found.",
            file=sys.stderr,
        )
        return 2

    # Fetch issue for type-label cross-check + title derivation.
    issue = _gh_get_issue(args.issue_number, config)
    if issue is None:
        return 2
    labels = [
        lbl.get("name", "") if isinstance(lbl, dict) else str(lbl)
        for lbl in (issue.get("labels") or [])
    ]
    expected_prefix = _derive_branch_prefix(labels)
    branch_prefix_match = re.match(r"^([a-z]+)/", branch)
    branch_prefix = branch_prefix_match.group(1) if branch_prefix_match else None
    if expected_prefix and branch_prefix and expected_prefix != branch_prefix:
        print(
            f"error: branch prefix {branch_prefix!r} doesn't match the issue's "
            f"type:* label (expected `{expected_prefix}` per DEC-013).",
            file=sys.stderr,
        )
        return 2

    print(f"review-work: #{args.issue_number}")
    print(f"  branch: {branch}")

    if args.dry_run:
        print("(dry-run: would open/flip-ready PR, assign reviewers, call move-issue.)")
        return 0

    if not args.yes and sys.stdin.isatty():
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    # PR handling: open ready, or flip draft → ready.
    existing_pr = _find_pr_for_branch(branch, config)
    pr_number: int | None = None
    if existing_pr is None:
        # Open a ready PR (non-draft).
        title = _derive_pr_title(issue, branch)
        body = f"Closes #{args.issue_number}"
        url = _gh_pr_create_ready(branch, args.base, title, body, config)
        if url is None:
            return 3
        m = re.search(r"/pull/(\d+)", url)
        pr_number = int(m.group(1)) if m else None
        print(f"  opened ready PR: {url}")
    elif existing_pr.get("isDraft"):
        # Flip draft → ready.
        pr_number = existing_pr.get("number")
        if not _gh_pr_ready(pr_number, config):
            return 3
        print(f"  flipped PR #{pr_number} draft → ready")
    else:
        pr_number = existing_pr.get("number")
        print(f"  PR #{pr_number} already ready; idempotent skip")

    # Reviewer assignment per DEC-027 mode resolution.
    mode_resolution = resolve_mode(
        config, issue_labels=labels, require_human=args.require_human,
    )
    print(f"  mode:   {mode_resolution.mode} ({mode_resolution.source})")

    reviewers_to_add = list(args.reviewer)  # explicit --reviewer overrides
    if mode_resolution.mode == "human" and not reviewers_to_add:
        members = _read_members(capability_root, yaml_loader)
        role = reviewer_role_from_config(config)
        if role:
            candidates = role_based_reviewers(
                members, role, exclude_login=invoker.github_login,
            )
            if candidates:
                reviewers_to_add = candidates
                print(f"  human-mode reviewers (role={role}): {', '.join('@' + r for r in candidates)}")
            else:
                print(
                    f"  [warn] human mode but no eligible reviewers for role={role!r}.",
                    file=sys.stderr,
                )
        else:
            print(
                "  [warn] human mode but `review.human_review.reviewer_role:` not set.",
                file=sys.stderr,
            )

    if pr_number is not None and reviewers_to_add:
        if not _gh_pr_add_reviewers(pr_number, reviewers_to_add, config):
            print(
                "[warn] PR ready but reviewer assignment failed; assign manually.",
                file=sys.stderr,
            )

    # Compose over move-issue for the state transition.
    rc = _invoke_move_issue(args.issue_number, "review", args.capability_root)
    if rc != 0:
        return rc

    print(f"\n[ok] PR ready + #{args.issue_number} In Progress → Review")
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


def _derive_branch_prefix(labels: list[str]) -> str | None:
    for label in labels:
        if label in TYPE_LABEL_TO_PREFIX:
            return TYPE_LABEL_TO_PREFIX[label]
    return None


def _derive_pr_title(issue: dict, branch: str) -> str:
    title = re.sub(r"^\[[^\]]+\]\s*", "", str(issue.get("title", "")))
    prefix_match = re.match(r"^([a-z]+)/", branch)
    prefix = prefix_match.group(1) if prefix_match else "feat"
    return f"{prefix}: {title}".strip()


def _gh_get_issue(issue_number: int, config: dict) -> dict | None:
    return gh_get_issue(issue_number, config, fields="title,labels")


def _find_pr_for_branch(branch: str, config: dict) -> dict | None:
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
            if pr.get("headRefName") == branch and pr.get("state") == "OPEN":
                return pr
    except (ValueError, KeyError):
        pass
    return None


def _gh_pr_create_ready(
    branch: str, base: str, title: str, body: str, config: dict
) -> str | None:
    proc = gh_run(
        ["gh", "pr", "create",
         "--head", branch, "--base", base,
         "--title", title, "--body", body],
        config, check=False,
    )
    if proc.returncode != 0:
        print(f"error: gh pr create failed: {proc.stderr.strip()}", file=sys.stderr)
        return None
    return proc.stdout.strip()


def _gh_pr_ready(pr_number: int | None, config: dict) -> bool:
    if pr_number is None:
        print("error: cannot flip PR to ready — no PR number resolved.", file=sys.stderr)
        return False
    proc = gh_run(
        ["gh", "pr", "ready", str(pr_number)],
        config, check=False,
    )
    if proc.returncode != 0:
        print(f"error: gh pr ready failed: {proc.stderr.strip()}", file=sys.stderr)
        return False
    return True


def _gh_pr_add_reviewers(pr_number: int, reviewers: list[str], config: dict) -> bool:
    cmd = ["gh", "pr", "edit", str(pr_number)]
    for r in reviewers:
        # Strip leading @ if present
        cmd += ["--add-reviewer", r.lstrip("@")]
    proc = gh_run(cmd, config, check=False)
    if proc.returncode != 0:
        print(
            f"error: gh pr edit --add-reviewer failed: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def _invoke_move_issue(
    issue_number: int, target: str, capability_root_arg: Path | None
) -> int:
    cmd = [
        sys.executable, str(_HERE / "move-issue.py"),
        str(issue_number), "--to", target, "--yes",
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
