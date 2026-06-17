#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — show-pr (verb-subject per DEC-020).

Read-only diagnostic for a GitHub PR. Surfaces the methodology-relevant
view: title, Conventional Commits parse, state, base/head branches,
closing issues, reviewers, doc-impact section presence.

Membership gate per DEC-021 runs at startup.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/show-pr.py 99

Or via the dispatcher (per COR-021):
  pkit project-management show-pr 99

Exit codes:
  0  shown
  1  membership refusal
  2  usage error (PR not found)
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Show the methodology-relevant view of a GitHub PR: title, "
            "Conventional Commits parse, state, branches, closing issues, "
            "reviewers, doc-impact presence."
        ),
    )
    parser.add_argument(
        "pr_number",
        type=int,
        help="GitHub PR number.",
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
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable text.",
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

    summary = _summarise(pr)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        _print_summary(args.pr_number, summary)
    return 0


def _summarise(pr: dict) -> dict:
    title = str(pr.get("title", ""))
    body = str(pr.get("body") or "")
    state = str(pr.get("state", "")).lower()
    head = pr.get("headRefName") or ""
    base = pr.get("baseRefName") or ""
    merged_at = pr.get("mergedAt")
    is_draft = bool(pr.get("isDraft"))
    url = pr.get("url")
    reviewers = [
        r.get("login") if isinstance(r, dict) else str(r)
        for r in (pr.get("reviewRequests") or [])
    ]

    conv = _parse_conventional_commits(title)
    closing_issues = _extract_closing_issues(body)
    has_doc_impact = "## Doc impact" in body

    return {
        "title": title,
        "state": state,
        "is_draft": is_draft,
        "head": head,
        "base": base,
        "merged_at": merged_at,
        "url": url,
        "conventional_commits": conv,
        "closes": closing_issues,
        "reviewers": reviewers,
        "has_doc_impact_section": has_doc_impact,
    }


def _print_summary(pr_number: int, s: dict) -> None:
    print(f"PR #{pr_number}: {s.get('title') or ''}")
    print(f"  state:        {s.get('state') or '<unknown>'}"
          + ("  (draft)" if s.get("is_draft") else ""))
    print(f"  base:         {s.get('base') or '<unknown>'}")
    print(f"  head:         {s.get('head') or '<unknown>'}")
    conv = s.get("conventional_commits") or {}
    if conv.get("matched"):
        type_part = f"{conv.get('type', '')}"
        if conv.get("scope"):
            type_part += f"({conv['scope']})"
        print(f"  cc type:      {type_part}")
        print(f"  cc summary:   {conv.get('summary') or ''}")
    else:
        print("  cc type:      <does not match Conventional Commits pattern>")
    closes = s.get("closes") or []
    print(
        f"  closes:       "
        f"{', '.join(f'#{n}' for n in closes) if closes else '<none>'}"
    )
    reviewers = s.get("reviewers") or []
    print(f"  reviewers:    {', '.join(reviewers) or '<none>'}")
    print(
        f"  doc impact:   {'present' if s.get('has_doc_impact_section') else 'missing'}"
    )
    if s.get("merged_at"):
        print(f"  merged at:    {s['merged_at']}")
    if s.get("url"):
        print(f"  url:          {s['url']}")


def _parse_conventional_commits(title: str) -> dict:
    """Decompose `<type>(<scope>): <summary>` into parts.

    Returns a dict with `matched`, `type`, `scope`, `summary`.
    """
    m = re.match(
        r"^(?P<type>[a-z]+)(\((?P<scope>[^)]+)\))?:\s+(?P<summary>.+)$",
        title,
    )
    if not m:
        return {"matched": False}
    return {
        "matched": True,
        "type": m.group("type"),
        "scope": m.group("scope"),
        "summary": m.group("summary"),
    }


def _extract_closing_issues(pr_body: str) -> list[int]:
    out: list[int] = []
    for m in CLOSING_KEYWORD_RE.finditer(pr_body or ""):
        n = int(m.group(1))
        if n not in out:
            out.append(n)
    return out


def _gh_get_pr(pr_number: int, config: dict) -> dict | None:
    try:
        proc = gh_run(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--json",
                "title,body,state,headRefName,baseRefName,mergedAt,"
                "isDraft,url,reviewRequests",
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
