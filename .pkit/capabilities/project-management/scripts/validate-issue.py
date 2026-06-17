#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — validate-issue (verb-subject per DEC-020).

Validates an existing GitHub issue against the methodology's body
shape: title regex per type, per-type required sections, classification
axes presence + uniqueness, parent-ref first line. Emits findings
tagged by the severity tokens from validation-severity.yaml (hard-
reject / bypassable-with-audit / warning).

Membership predicate per DEC-021 runs at startup; closed mode refuses
non-members (the gate applies to all mutating + read commands in the
v0.3.0 stub).

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/validate-issue.py 42

Or via the dispatcher:
  pkit project-management validate-issue 42

Exit codes:
  0  every check passed or only warning-level findings
  1  one or more hard-reject (or unbypassed bypassable-with-audit) findings
  2  usage error (issue not found; gh failure)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from _lib.placeholder_detection import (  # noqa: E402
    PHASE_CREATE,
    PHASE_TRANSITION,
    detect_placeholder_residuals,
)


SEVERITY_HARD_REJECT = "hard-reject"
SEVERITY_BYPASSABLE = "bypassable-with-audit"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    """One validation finding."""

    severity: str
    label: str
    detail: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate an existing GitHub issue against the project-management "
            "methodology's body + classification rules. Reports findings by "
            "severity; exit code is the contract for CI gating."
        ),
    )
    parser.add_argument(
        "issue_number",
        type=int,
        help="GitHub issue number to validate.",
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
        "--phase",
        choices=(PHASE_CREATE, PHASE_TRANSITION),
        default=PHASE_TRANSITION,
        help=(
            "Validation phase. 'create' — body was just stamped from the "
            "template (empty-checkbox-section is a warning, not a hard-reject). "
            "'transition' (default) — body is being validated at a lifecycle "
            "transition; empty-checkbox-section is a hard-reject per DEC-031."
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

    # Read schemas + adopter config.
    issue_types = _read_yaml(capability_root / "schemas" / "issue-types.yaml", yaml_loader)
    titles = _read_yaml(capability_root / "schemas" / "titles.yaml", yaml_loader)
    body_format = _read_yaml(capability_root / "schemas" / "body-format.yaml", yaml_loader)
    config = _read_yaml(capability_root / "project" / "config.yaml", yaml_loader)
    mandatory_state = _read_yaml(
        capability_root / "schemas" / "mandatory-issue-state.yaml", yaml_loader
    )

    issue = _gh_get_issue(args.issue_number, config)
    if issue is None:
        return 2

    findings = _validate_issue(
        issue=issue,
        issue_types=issue_types,
        titles=titles,
        body_format=body_format,
        config=config,
        mandatory_state=mandatory_state,
        capability_root=capability_root,
        phase=args.phase,
    )

    if args.json:
        out = {
            "issue_number": args.issue_number,
            "issue_title": issue.get("title", ""),
            "findings": [
                {"severity": f.severity, "label": f.label, "detail": f.detail}
                for f in findings
            ],
        }
        print(json.dumps(out, indent=2))
    else:
        _print_findings(args.issue_number, issue, findings)

    # Exit code: non-zero on any hard-reject or bypassable.
    has_blocking = any(
        f.severity in (SEVERITY_HARD_REJECT, SEVERITY_BYPASSABLE)
        for f in findings
    )
    return 1 if has_blocking else 0


# ---- validation -----------------------------------------------------


def _validate_issue(
    *,
    issue: dict,
    issue_types: dict,
    titles: dict,
    body_format: dict,
    config: dict,
    mandatory_state: dict | None = None,
    capability_root: Path | None = None,
    phase: str = PHASE_TRANSITION,
) -> list[Finding]:
    findings: list[Finding] = []
    title = str(issue.get("title", ""))
    body = str(issue.get("body") or "")
    labels = [
        lbl.get("name", "") if isinstance(lbl, dict) else str(lbl)
        for lbl in (issue.get("labels") or [])
    ]
    assignees = issue.get("assignees") or []

    # Infer structural type from title prefix.
    structural_type = _infer_structural_type(title, issue_types)

    # Title format.
    if structural_type is None:
        findings.append(
            Finding(
                SEVERITY_HARD_REJECT,
                "title.format",
                f"title {title!r} does not match any known [Type] prefix "
                f"(expected one of [EPIC], [Feature], [Umbrella], [Task]).",
            )
        )
    else:
        pattern = _title_pattern_for(titles, structural_type)
        if pattern and not re.match(pattern, title):
            findings.append(
                Finding(
                    SEVERITY_HARD_REJECT,
                    "title.pattern",
                    f"title does not match titles.yaml pattern for "
                    f"{structural_type!r}: {pattern!r}",
                )
            )

    # Classification axes (per DEC-012).
    type_labels = [lbl for lbl in labels if lbl.startswith("type:")]
    if len(type_labels) == 0:
        findings.append(
            Finding(
                SEVERITY_HARD_REJECT,
                "classification.type.missing",
                "no `type:*` label present (required by classification.yaml).",
            )
        )
    elif len(type_labels) > 1:
        findings.append(
            Finding(
                SEVERITY_HARD_REJECT,
                "classification.type.multiple",
                f"multiple `type:*` labels — must be mutually exclusive: "
                f"{', '.join(type_labels)}",
            )
        )

    has_board = bool(config.get("has_projects_v2_board", False))
    if not has_board:
        priority_labels = [lbl for lbl in labels if lbl.startswith("priority:")]
        workstream_labels = [lbl for lbl in labels if lbl.startswith("workstream:")]
        if len(priority_labels) == 0:
            findings.append(
                Finding(
                    SEVERITY_HARD_REJECT,
                    "classification.priority.missing",
                    "no `priority:*` label present (required in label-fallback "
                    "mode per classification.yaml).",
                )
            )
        elif len(priority_labels) > 1:
            findings.append(
                Finding(
                    SEVERITY_HARD_REJECT,
                    "classification.priority.multiple",
                    f"multiple `priority:*` labels: {', '.join(priority_labels)}",
                )
            )
        if len(workstream_labels) == 0:
            findings.append(
                Finding(
                    SEVERITY_HARD_REJECT,
                    "classification.workstream.missing",
                    "no `workstream:*` label present (required in label-"
                    "fallback mode per classification.yaml).",
                )
            )
        elif len(workstream_labels) > 1:
            findings.append(
                Finding(
                    SEVERITY_HARD_REJECT,
                    "classification.workstream.multiple",
                    f"multiple `workstream:*` labels: {', '.join(workstream_labels)}",
                )
            )

    # Mandatory assignment (per DEC-019 / mandatory-issue-state.yaml).
    state_fields = (mandatory_state or {}).get("required_fields") or {}
    if not assignees:
        assignee_field = state_fields.get("assignee") or {}
        sev = _severity_from_token(assignee_field.get("drift_severity")) if assignee_field else SEVERITY_WARNING
        findings.append(
            Finding(
                sev,
                "assignment.missing",
                "no assignee. Mandatory per DEC-019 (mandatory-issue-state.yaml).",
            )
        )

    # Board membership drift (per DEC-019 / mandatory-issue-state.yaml).
    # Only fires for board-substrate adopters. We surface a finding when
    # the issue is open + board configured + the issue's `projectItems`
    # is empty (best-effort; the gh JSON surface for project membership
    # is limited at v1 so this is gated to data we have).
    if has_board and state_fields.get("board_membership"):
        project_items = issue.get("projectItems")
        if project_items is not None and isinstance(project_items, list) and len(project_items) == 0:
            board_field = state_fields["board_membership"]
            sev = _severity_from_token(board_field.get("drift_severity"))
            findings.append(
                Finding(
                    sev,
                    "board_membership.missing",
                    "issue is not on the configured Projects v2 board. "
                    "Mandatory per DEC-019.",
                )
            )

    # Per-type required body sections.
    if structural_type is not None:
        bodies = body_format.get("bodies") or {}
        type_body = bodies.get(structural_type)
        if isinstance(type_body, dict):
            required = type_body.get("required_sections") or []
            for section in required:
                if not isinstance(section, dict):
                    continue
                heading = str(section.get("heading", ""))
                if heading and heading not in body:
                    severity = _severity_from_token(section.get("severity"))
                    findings.append(
                        Finding(
                            severity,
                            "body.required-section",
                            f"missing required section {heading!r} "
                            f"({structural_type} body).",
                        )
                    )

        # Parent-ref first line.
        type_entry = (issue_types.get("types") or {}).get(structural_type)
        if isinstance(type_entry, dict):
            parent_ref_optional = bool(type_entry.get("parent_ref_optional", False))
            parent_ref_form = str(type_entry.get("parent_ref_form", ""))
            if parent_ref_form and not parent_ref_optional:
                first_line = body.lstrip().split("\n", 1)[0]
                # New canonical form: `Milestone: [#<N>](../milestone/<N>)`
                _NEW_MILESTONE_RE = re.compile(
                    r"^Milestone:\s+\[#(\d+)\]\(\.\./milestone/\1\)\s*$"
                )
                # Old (deprecated) form: `Milestone: #<N>` — accepted with
                # a warning during the grace period; suggests upgrading.
                _OLD_MILESTONE_RE = re.compile(r"^Milestone:\s+#\d+\s*$")
                # Plain issue-parent form: `<Label>: #<N>` (EPIC, Feature, etc.)
                _ISSUE_PARENT_RE = re.compile(r"^[A-Za-z]+:\s+#\d+\s*$")

                if _NEW_MILESTONE_RE.match(first_line):
                    # New form — clean pass.
                    pass
                elif _OLD_MILESTONE_RE.match(first_line):
                    # Old plain form — accepted with a deprecation warning.
                    findings.append(
                        Finding(
                            SEVERITY_WARNING,
                            "body.parent-ref.milestone-old-form",
                            "milestone parent-ref uses the old `Milestone: #<N>` "
                            "form; update to "
                            "`Milestone: [#<N>](../milestone/<N>)` so the link "
                            "points to the milestone rather than an issue.",
                        )
                    )
                elif not _ISSUE_PARENT_RE.match(first_line):
                    # Neither milestone form nor a valid issue-parent ref.
                    findings.append(
                        Finding(
                            SEVERITY_HARD_REJECT,
                            "body.parent-ref",
                            f"first body line does not match the parent-ref "
                            f"form {parent_ref_form!r}; got {first_line!r}.",
                        )
                    )

        # Residual-placeholder detection per DEC-031.
        if capability_root is not None:
            for sev, label, detail in detect_placeholder_residuals(
                body=body,
                structural_type=structural_type,
                body_format=body_format,
                capability_root=capability_root,
                phase=phase,
            ):
                findings.append(Finding(sev, label, detail))

    # Universal body rules — minimal subset.
    if re.search(r"^# [^#]", body, flags=re.MULTILINE):
        findings.append(
            Finding(
                SEVERITY_HARD_REJECT,
                "body.h1",
                "body contains an h1 (`# ...`) heading; the issue title "
                "is the h1. Use `## Title` for sections.",
            )
        )
    if re.search(r"[A-Za-z0-9_/\.\-]+\.[a-z]+:\d+\b", body):
        findings.append(
            Finding(
                SEVERITY_WARNING,
                "body.file-line-refs",
                "body contains file:line references; line numbers go stale.",
            )
        )

    return findings


def _infer_structural_type(title: str, issue_types: dict) -> str | None:
    """Map the title prefix to the structural type name."""
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


def _title_pattern_for(titles: dict, structural_type: str) -> str | None:
    formats = titles.get("formats") or {}
    key = f"issue-{structural_type}"
    entry = formats.get(key)
    if isinstance(entry, dict):
        pattern = entry.get("pattern")
        if isinstance(pattern, str):
            return pattern
    return None


def _severity_from_token(token: Any) -> str:
    """Parse a `[validation-severity:<sev>]` token to a string severity."""
    if not isinstance(token, str):
        return SEVERITY_WARNING
    m = re.match(r"\[validation-severity:([a-z-]+)\]", token)
    if not m:
        return SEVERITY_WARNING
    return m.group(1)


# ---- I/O helpers ----------------------------------------------------


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
    """Fetch issue title/body/labels/assignees via `gh issue view`."""
    return gh_get_issue(
        issue_number, config,
        fields="title,body,labels,assignees,projectItems",
    )


def _print_findings(issue_number: int, issue: dict, findings: list[Finding]) -> None:
    title = issue.get("title", "")
    print(f"validating issue #{issue_number}: {title}")
    print()
    if not findings:
        print("[ok] no findings.")
        return
    by_severity: dict[str, list[Finding]] = {}
    for f in findings:
        by_severity.setdefault(f.severity, []).append(f)
    for sev in (SEVERITY_HARD_REJECT, SEVERITY_BYPASSABLE, SEVERITY_WARNING):
        group = by_severity.get(sev, [])
        if not group:
            continue
        print(f"[{sev}]")
        for f in group:
            print(f"  - {f.label}: {f.detail}")
        print()
    n_blocking = len(by_severity.get(SEVERITY_HARD_REJECT, [])) + len(
        by_severity.get(SEVERITY_BYPASSABLE, [])
    )
    n_warn = len(by_severity.get(SEVERITY_WARNING, []))
    print(f"summary: {n_blocking} blocking, {n_warn} warning(s).")


if __name__ == "__main__":
    sys.exit(main())
