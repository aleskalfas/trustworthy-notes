#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — show-tree (verb-subject per DEC-020).

PM-operational diagnostic. Walks the hierarchy:

  Milestones → EPICs → Features / Umbrellas → Tasks → sub-tasks + PRs

Surfaces orphans:
  * Open issues without a parent that aren't EPICs.
  * Tasks not under Feature / Umbrella / EPIC.
  * Open PRs not linked to any Task via Closes #N.
  * For board-substrate adopters: open issues not on the configured
    Projects v2 board (best-effort; checked when --board-check is on).

Output formats: text tree (default), JSON, markdown.

Read-only. Membership gate per DEC-021 runs at startup (read mode).

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/show-tree.py

Or via the dispatcher (per COR-021):
  pkit project-management show-tree --json

Exit codes:
  0  rendered cleanly
  1  membership refusal
  2  usage error / gh failure
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
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


CLOSING_KEYWORD_RE = re.compile(
    r"\b(?:closes|fixes|resolves)\s+#(\d+)", re.IGNORECASE
)


@dataclass
class Issue:
    number: int
    title: str
    state: str
    body: str
    labels: list[str]
    milestone: str | None
    structural_type: str | None  # epic / feature / umbrella / task / None
    parent_number: int | None = None
    children: list[int] = field(default_factory=list)


@dataclass
class PR:
    number: int
    title: str
    state: str
    closes: list[int]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Walk the methodology hierarchy (Milestones → EPICs → Features/"
            "Umbrellas → Tasks → sub-tasks + PRs) and report orphans."
        ),
    )
    parser.add_argument(
        "--state",
        choices=["open", "closed", "all"],
        default="open",
        help="Issue/PR state filter (default: open).",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output format (default: text tree).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help=(
            "Max issues to fetch from gh (default: 500). Increase for "
            "large repos."
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

    issue_types = _read_yaml(
        capability_root / "schemas" / "issue-types.yaml", yaml_loader
    )

    issues_raw = _gh_list_issues(state=args.state, limit=args.limit, config=config)
    if issues_raw is None:
        return 2
    prs_raw = _gh_list_prs(state=args.state, limit=args.limit, config=config)
    if prs_raw is None:
        return 2

    issues = _parse_issues(issues_raw, issue_types)
    prs = _parse_prs(prs_raw)

    # Build parent relationships.
    _link_parents(issues)

    orphans = _detect_orphans(issues, prs)
    tree = _build_tree(issues)

    if args.format == "json":
        out = {
            "issues": {
                str(num): _issue_to_dict(issues[num]) for num in issues
            },
            "prs": [
                {"number": p.number, "title": p.title, "state": p.state, "closes": p.closes}
                for p in prs.values()
            ],
            "orphans": orphans,
            "tree_roots": [n for n in tree if issues[n].parent_number is None],
        }
        print(json.dumps(out, indent=2))
    elif args.format == "markdown":
        _print_markdown(issues, prs, orphans, tree)
    else:
        _print_text(issues, prs, orphans, tree)

    return 0


# ---- parsing --------------------------------------------------------


def _parse_issues(raw: list, issue_types: dict) -> dict[int, Issue]:
    out: dict[int, Issue] = {}
    for r in raw:
        if not isinstance(r, dict):
            continue
        number = r.get("number")
        if not isinstance(number, int):
            continue
        title = str(r.get("title", ""))
        labels = [
            lbl.get("name", "") if isinstance(lbl, dict) else str(lbl)
            for lbl in (r.get("labels") or [])
        ]
        milestone = r.get("milestone") or {}
        ms_title = milestone.get("title") if isinstance(milestone, dict) else None
        out[number] = Issue(
            number=number,
            title=title,
            state=str(r.get("state", "")).lower(),
            body=str(r.get("body") or ""),
            labels=labels,
            milestone=ms_title,
            structural_type=_infer_structural_type(title, issue_types),
        )
    return out


def _parse_prs(raw: list) -> dict[int, PR]:
    out: dict[int, PR] = {}
    for r in raw:
        if not isinstance(r, dict):
            continue
        number = r.get("number")
        if not isinstance(number, int):
            continue
        body = str(r.get("body") or "")
        closes = sorted(
            {int(m.group(1)) for m in CLOSING_KEYWORD_RE.finditer(body)}
        )
        out[number] = PR(
            number=number,
            title=str(r.get("title", "")),
            state=str(r.get("state", "")).lower(),
            closes=closes,
        )
    return out


def _infer_structural_type(title: str, issue_types: dict) -> str | None:
    types = issue_types.get("types") or {}
    for type_name, entry in types.items():
        if not isinstance(entry, dict):
            continue
        prefix = entry.get("title_prefix", "")
        case = entry.get("title_case", "title")
        rendered = str(prefix)
        if case == "upper":
            rendered = rendered.upper()
        if title.startswith(f"[{rendered}] "):
            return str(type_name)
    return None


def _link_parents(issues: dict[int, Issue]) -> None:
    """Populate parent_number + children based on body parent-ref lines."""
    for num, issue in issues.items():
        parent = _extract_parent_ref(issue.body)
        if parent is not None and parent in issues:
            issue.parent_number = parent
            issues[parent].children.append(num)


def _extract_parent_ref(body: str) -> int | None:
    if not body:
        return None
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^([A-Za-z]+):\s+#(\d+)", s)
        if not m:
            return None
        return int(m.group(2))
    return None


# ---- orphan detection -----------------------------------------------


def _detect_orphans(issues: dict[int, Issue], prs: dict[int, PR]) -> dict:
    """Return dict with several orphan categories."""
    orphan_open_no_parent: list[int] = []
    task_not_under_container: list[int] = []
    pr_no_closing_issue: list[int] = []

    for num, issue in issues.items():
        if issue.state != "open":
            continue
        if issue.structural_type == "epic":
            # EPICs are tops; no parent expected (parent_ref_optional: true).
            continue
        if issue.parent_number is None:
            orphan_open_no_parent.append(num)
        elif issue.structural_type == "task":
            parent = issues.get(issue.parent_number)
            if parent is not None and parent.structural_type not in (
                "feature",
                "umbrella",
                "epic",
            ):
                task_not_under_container.append(num)

    for pr_num, pr in prs.items():
        if pr.state != "open":
            continue
        # Any closes-target should be an issue we know about.
        if not pr.closes or not any(n in issues for n in pr.closes):
            pr_no_closing_issue.append(pr_num)

    return {
        "open_issues_with_no_parent_ref": sorted(orphan_open_no_parent),
        "tasks_not_under_container": sorted(task_not_under_container),
        "prs_without_closing_issue_in_repo": sorted(pr_no_closing_issue),
    }


# ---- tree construction ----------------------------------------------


def _build_tree(issues: dict[int, Issue]) -> dict[int, Issue]:
    """Identity passthrough for now; the dict order is the iteration order.

    The tree shape is encoded by `parent_number` + `children` on each
    Issue. The renderers walk roots (parent_number is None) and recurse.
    """
    return issues


def _issue_to_dict(issue: Issue) -> dict:
    return {
        "number": issue.number,
        "title": issue.title,
        "state": issue.state,
        "structural_type": issue.structural_type,
        "milestone": issue.milestone,
        "parent_number": issue.parent_number,
        "children": sorted(issue.children),
    }


# ---- text renderer --------------------------------------------------


def _print_text(
    issues: dict[int, Issue],
    prs: dict[int, PR],
    orphans: dict,
    _tree: dict[int, Issue],
) -> None:
    roots = sorted(n for n, i in issues.items() if i.parent_number is None)
    print("# Issue hierarchy")
    print()
    if not roots:
        print("  (no roots found)")
    else:
        for root in roots:
            _print_branch(issues, prs, root, depth=0)

    print()
    print("# Orphans / drift")
    print()
    if not any(orphans.values()):
        print("  (none)")
        return
    for category, nums in orphans.items():
        if not nums:
            continue
        print(f"  [{category}]")
        for n in nums:
            target = issues.get(n) or prs.get(n)
            label = (
                f"#{n} — {target.title}"
                if target is not None and getattr(target, "title", None)
                else f"#{n}"
            )
            print(f"    - {label}")
        print()


def _print_branch(
    issues: dict[int, Issue],
    prs: dict[int, PR],
    num: int,
    depth: int,
) -> None:
    issue = issues[num]
    prefix = "  " * depth + ("- " if depth else "")
    type_marker = f"[{issue.structural_type or '?'}]"
    state_marker = f"({issue.state})"
    ms = f" — milestone: {issue.milestone}" if issue.milestone else ""
    print(f"{prefix}{type_marker} #{num} {state_marker} {issue.title}{ms}")
    # Linked PRs.
    linked = [p for p in prs.values() if num in p.closes]
    for p in linked:
        sub = "  " * (depth + 1) + "↪ "
        print(f"{sub}PR #{p.number} ({p.state}) — {p.title}")
    for child in sorted(issue.children):
        _print_branch(issues, prs, child, depth + 1)


# ---- markdown renderer ----------------------------------------------


def _print_markdown(
    issues: dict[int, Issue],
    prs: dict[int, PR],
    orphans: dict,
    _tree: dict[int, Issue],
) -> None:
    print("# Issue hierarchy")
    print()
    roots = sorted(n for n, i in issues.items() if i.parent_number is None)
    for root in roots:
        _md_branch(issues, prs, root, depth=0)
    print()
    print("# Orphans / drift")
    print()
    for category, nums in orphans.items():
        if not nums:
            continue
        print(f"## {category}")
        for n in nums:
            print(f"- #{n}")
        print()


def _md_branch(
    issues: dict[int, Issue],
    prs: dict[int, PR],
    num: int,
    depth: int,
) -> None:
    issue = issues[num]
    indent = "  " * depth
    state = f" *(closed)*" if issue.state == "closed" else ""
    print(f"{indent}- **[{issue.structural_type or '?'}] #{num}**{state} {issue.title}")
    linked = [p for p in prs.values() if num in p.closes]
    for p in linked:
        print(f"{indent}  - PR #{p.number} ({p.state}) {p.title}")
    for child in sorted(issue.children):
        _md_branch(issues, prs, child, depth + 1)


# ---- gh wrappers ----------------------------------------------------


def _gh_list_issues(*, state: str, limit: int, config: dict) -> list | None:
    try:
        proc = gh_run(
            [
                "gh",
                "issue",
                "list",
                "--state",
                state,
                "--limit",
                str(limit),
                "--json",
                "number,title,body,state,labels,milestone",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        print("error: `gh` not on PATH.", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(
            f"error: gh issue list failed.\nstderr: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def _gh_list_prs(*, state: str, limit: int, config: dict) -> list | None:
    try:
        proc = gh_run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                state,
                "--limit",
                str(limit),
                "--json",
                "number,title,body,state",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        print(
            f"error: gh pr list failed.\nstderr: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


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
