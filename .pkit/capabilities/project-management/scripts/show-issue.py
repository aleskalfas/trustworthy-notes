#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — show-issue (verb-subject per DEC-020).

Read-only diagnostic for an existing GitHub issue. Surfaces the
methodology-relevant view: title, type (inferred from prefix),
classification labels, assignees, state, parent-ref (first body line),
required-section presence summary, milestone.

Membership gate per DEC-021.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/show-issue.py 42

Or via the dispatcher (per COR-021):
  pkit project-management show-issue 42

Exit codes:
  0  shown
  1  membership refusal
  2  usage error (issue not found; gh failure)
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
from _lib.membership import (  # noqa: E402
    CAPABILITY_NAME,
    check_membership,
    resolve_capability_root,
    resolve_invoker_identity,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Show the methodology-relevant view of a GitHub issue: type, "
            "classification, assignees, state, parent-ref, milestone, "
            "and required-section presence summary."
        ),
    )
    parser.add_argument(
        "issue_number",
        type=int,
        help="GitHub issue number to inspect.",
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

    issue_types = _read_yaml(capability_root / "schemas" / "issue-types.yaml", yaml_loader)
    body_format = _read_yaml(capability_root / "schemas" / "body-format.yaml", yaml_loader)

    issue = _gh_get_issue(args.issue_number, config)
    if issue is None:
        return 2

    summary = _summarise(issue, issue_types, body_format)

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        _print_summary(args.issue_number, summary)
    return 0


def _summarise(issue: dict, issue_types: dict, body_format: dict) -> dict:
    title = str(issue.get("title", ""))
    body = str(issue.get("body") or "")
    labels = [
        lbl.get("name", "") if isinstance(lbl, dict) else str(lbl)
        for lbl in (issue.get("labels") or [])
    ]
    assignees = [
        a.get("login", "") if isinstance(a, dict) else str(a)
        for a in (issue.get("assignees") or [])
    ]
    state = str(issue.get("state", "")).lower()
    milestone = issue.get("milestone") or {}
    milestone_title = (
        milestone.get("title") if isinstance(milestone, dict) else None
    )

    structural_type = _infer_structural_type(title, issue_types)
    parent_ref = _first_body_line(body)
    required_sections = _required_section_status(structural_type, body, body_format)

    type_labels = [lbl for lbl in labels if lbl.startswith("type:")]
    priority_labels = [lbl for lbl in labels if lbl.startswith("priority:")]
    workstream_labels = [lbl for lbl in labels if lbl.startswith("workstream:")]
    other_labels = [
        lbl
        for lbl in labels
        if not any(lbl.startswith(p) for p in ("type:", "priority:", "workstream:"))
    ]

    return {
        "title": title,
        "structural_type": structural_type,
        "state": state,
        "assignees": assignees,
        "milestone": milestone_title,
        "parent_ref": parent_ref,
        "classification": {
            "type": type_labels,
            "priority": priority_labels,
            "workstream": workstream_labels,
        },
        "other_labels": other_labels,
        "required_sections": required_sections,
        "url": issue.get("url"),
    }


def _print_summary(issue_number: int, s: dict) -> None:
    title = s.get("title") or ""
    print(f"issue #{issue_number}: {title}")
    print(f"  type:         {s.get('structural_type') or '<unrecognised prefix>'}")
    print(f"  state:        {s.get('state') or '<unknown>'}")
    print(f"  assignees:    {', '.join(s.get('assignees') or []) or '<none>'}")
    if s.get("milestone"):
        print(f"  milestone:    {s['milestone']}")
    parent_ref = s.get("parent_ref") or ""
    if parent_ref:
        print(f"  parent ref:   {parent_ref}")
    classification = s.get("classification") or {}
    type_lbls = classification.get("type") or []
    pri_lbls = classification.get("priority") or []
    ws_lbls = classification.get("workstream") or []
    print(f"  type label:   {', '.join(type_lbls) or '<missing>'}")
    print(f"  priority:     {', '.join(pri_lbls) or '<unset / on board>'}")
    print(f"  workstream:   {', '.join(ws_lbls) or '<unset / on board>'}")
    other = s.get("other_labels") or []
    if other:
        print(f"  other labels: {', '.join(other)}")
    sections = s.get("required_sections") or []
    if sections:
        present = sum(1 for sec in sections if sec.get("present"))
        print(f"  body sections: {present}/{len(sections)} required present")
        for sec in sections:
            marker = "✓" if sec.get("present") else "✗"
            print(f"    {marker} {sec.get('heading')}")
    url = s.get("url")
    if url:
        print(f"  url:          {url}")


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


def _first_body_line(body: str) -> str:
    return body.lstrip().split("\n", 1)[0] if body.strip() else ""


def _required_section_status(
    structural_type: str | None, body: str, body_format: dict
) -> list[dict]:
    if not structural_type:
        return []
    bodies = body_format.get("bodies") or {}
    type_body = bodies.get(structural_type) or {}
    sections = type_body.get("required_sections") or []
    out: list[dict] = []
    for s in sections:
        if not isinstance(s, dict):
            continue
        heading = str(s.get("heading", ""))
        if not heading:
            continue
        out.append({"heading": heading, "present": heading in body})
    return out


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


def _gh_get_issue(issue_number: int, config: dict) -> dict | None:
    return gh_get_issue(
        issue_number, config,
        fields="title,body,labels,assignees,state,milestone,url",
    )


if __name__ == "__main__":
    sys.exit(main())
