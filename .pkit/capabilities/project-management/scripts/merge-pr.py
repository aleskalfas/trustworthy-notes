#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — merge-pr (verb-subject per DEC-020).

Merges a GitHub PR with the methodology's squash-and-delete-branch
policy (git-conventions.yaml's `merge` convention). Before invoking
`gh pr merge --squash --delete-branch`:

  * Membership gate (DEC-021).
  * Checkbox close-gate (DEC-007) on every issue the PR closes —
    every `- [ ]` in any closing issue body must be ticked, else
    refuse. The PR body's own checkboxes also count.
  * PR title must match `titles.yaml`'s `pr` regex (Conventional
    Commits).

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/merge-pr.py 99

Or via the dispatcher (per COR-021):
  pkit project-management merge-pr 99

Exit codes:
  0  merged (or dry-run reported)
  1  membership refusal / checkbox close-gate refusal / title refusal
  2  usage error (PR not found)
  3  gh failure
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
from _lib.gh import gh_get_issue, gh_run, load_adopter_config  # noqa: E402
from _lib.hooks import fire_hooks  # noqa: E402
from _lib.membership import (  # noqa: E402
    CAPABILITY_NAME,
    check_membership,
    resolve_capability_root,
    resolve_invoker_identity,
)


CLOSING_KEYWORD_RE = re.compile(
    r"\b(?:closes|fixes|resolves)\s+#(\d+)", re.IGNORECASE
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Merge a PR per the methodology's squash-and-delete-branch "
            "policy. Enforces the checkbox close-gate on every closing "
            "issue + the PR's own body."
        ),
    )
    parser.add_argument(
        "pr_number",
        type=int,
        help="GitHub PR number to merge.",
    )
    parser.add_argument(
        "--skip-checkbox-gate",
        action="store_true",
        help=(
            "Skip the DEC-007 checkbox close-gate on closing issues. "
            "Discouraged; only when you've manually validated each box."
        ),
    )
    parser.add_argument(
        "--admin",
        action="store_true",
        help=(
            "Pass --admin to gh pr merge (bypasses branch-protection "
            "checks). Use only when authorised."
        ),
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

    titles = _read_yaml(capability_root / "schemas" / "titles.yaml", yaml_loader)

    pr = _gh_get_pr(args.pr_number, config)
    if pr is None:
        return 2

    pr_title = str(pr.get("title", ""))
    pr_body = str(pr.get("body") or "")
    pr_state = str(pr.get("state", "")).lower()
    pr_url = pr.get("url") or ""

    print(f"merge-pr: #{args.pr_number}")
    print(f"  title: {pr_title}")
    print(f"  state: {pr_state}")

    if pr_state != "open":
        print(
            f"\n[refused] PR is not open (state: {pr_state}). "
            "Cannot merge.",
            file=sys.stderr,
        )
        return 1

    # Title validation.
    title_pattern = _pr_title_pattern(titles)
    if title_pattern and not re.match(title_pattern, pr_title):
        print(
            f"\n[refused] PR title does not match Conventional Commits "
            f"pattern: {title_pattern!r}.\n"
            "  → edit the PR title (e.g., `gh pr edit <N> --title "
            "'<type>(<scope>): <summary>'`).",
            file=sys.stderr,
        )
        return 1

    # Closing-issue + PR-body checkbox gate.
    closing_issues = _extract_closing_issues(pr_body)
    print(
        f"  closes: {', '.join(f'#{n}' for n in closing_issues) or '<none>'}"
    )
    if not closing_issues:
        print(
            "\n[refused] PR body has no `Closes #N` / `Fixes #N` / "
            "`Resolves #N` reference (required by git-conventions.yaml).\n"
            "  → add a `Closes #<N>` line to the PR body and retry.",
            file=sys.stderr,
        )
        return 1

    if not args.skip_checkbox_gate:
        unticked_findings = _gather_unticked_findings(args.pr_number, pr_body, closing_issues, config)
        if unticked_findings:
            print("\n[refused] DEC-007 checkbox close-gate:")
            for src, lines in unticked_findings.items():
                print(f"  {src}:")
                for line in lines:
                    print(f"    - {line}")
            print(
                "\n  → tick or remove each unticked checkbox; re-run.",
                file=sys.stderr,
            )
            return 1

    if args.dry_run:
        print(
            f"\n[dry-run] gh pr merge --squash --delete-branch "
            f"--subject {pr_title!r} would be invoked; nothing written."
        )
        return 0
    if not args.yes and sys.stdin.isatty():
        reply = input("Merge with squash + delete-branch? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    if not _gh_merge(args.pr_number, pr_title=pr_title, admin=args.admin, config=config):
        return 3

    print(f"\n[ok] merged: {pr_url}")

    # Fire after_merge_pr hooks per DEC-024.
    fire_hooks(
        "after_merge_pr",
        context={
            "pr": {
                "number": args.pr_number,
                "title": str(pr.get("title", "")) if pr else "",
            },
        },
        config=config,
        capability_root=capability_root,
    )

    return 0


# ---- closing-issue parsing -----------------------------------------


def _extract_closing_issues(pr_body: str) -> list[int]:
    """Find all `Closes #N` / `Fixes #N` / `Resolves #N` numbers."""
    out: list[int] = []
    for m in CLOSING_KEYWORD_RE.finditer(pr_body or ""):
        n = int(m.group(1))
        if n not in out:
            out.append(n)
    return out


def _gather_unticked_findings(
    pr_number: int, pr_body: str, closing_issues: list[int], config: dict
) -> dict[str, list[str]]:
    """Return a mapping of source label → unticked-box lines.

    Sources: 'PR body' for the PR's own body, '#<N>' for each closing
    issue.
    """
    findings: dict[str, list[str]] = {}
    pr_unticked = _unticked_boxes(pr_body)
    if pr_unticked:
        findings["PR body"] = pr_unticked
    for n in closing_issues:
        issue = _gh_get_issue(n, config)
        if issue is None:
            findings[f"#{n}"] = ["(could not fetch issue body)"]
            continue
        body = str(issue.get("body") or "")
        unticked = _unticked_boxes(body)
        if unticked:
            findings[f"#{n}"] = unticked
    return findings


def _unticked_boxes(body: str) -> list[str]:
    out: list[str] = []
    for line in (body or "").splitlines():
        if re.match(r"^\s*[-*]\s+\[\s\]\s+\S", line):
            out.append(line.strip())
    return out


# ---- schema helpers ------------------------------------------------


def _pr_title_pattern(titles: dict) -> str | None:
    formats = titles.get("formats") or {}
    entry = formats.get("pr")
    if isinstance(entry, dict):
        p = entry.get("pattern")
        if isinstance(p, str):
            return p
    return None


# ---- gh wrappers ----------------------------------------------------


def _gh_get_pr(pr_number: int, config: dict) -> dict | None:
    try:
        proc = gh_run(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--json",
                "title,body,state,url,headRefName,baseRefName",
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


def _gh_get_issue(issue_number: int, config: dict) -> dict | None:
    return gh_get_issue(issue_number, config, fields="title,body,state")


def _gh_merge(pr_number: int, *, pr_title: str, admin: bool, config: dict) -> bool:
    # Force --subject to the PR title so the squash-commit subject equals the
    # gate-validated title for both single- and multi-commit PRs.  GitHub's
    # default for a single-commit PR is the commit message, not the title —
    # the --subject flag overrides that (DEC-013; fixes #33).
    cmd = [
        "gh",
        "pr",
        "merge",
        str(pr_number),
        "--squash",
        "--delete-branch",
        "--subject", pr_title,
    ]
    if admin:
        cmd.append("--admin")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False
    if proc.returncode != 0:
        print(
            f"error: gh pr merge failed (exit {proc.returncode}).\n"
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
