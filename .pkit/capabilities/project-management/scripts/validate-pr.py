#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — validate-pr (verb-subject per DEC-020).

Validates an existing GitHub PR against the methodology's PR-side
rules:

  * Title matches `titles.yaml`'s `pr` regex (Conventional Commits).
  * Title's `<type>` matches the closing issue's `type:*` label per
    classification.yaml's `pr_type_mapping`.
  * Body contains at least one `Closes #N` / `Fixes #N` / `Resolves #N`
    keyword reference (git-conventions.yaml `pr-body` rule).
  * Body contains a `## Doc impact` section (git-conventions.yaml
    `pr-body` rule).
  * Body has been authored — residual-placeholder detection per DEC-031:
    - `## Test plan` with no authored checkbox items → warning at open,
      hard-reject at the merge gate (PHASE_TRANSITION).
    - Surviving PR.md placeholder prose → always a warning.

Findings tagged by severity per validation-severity.yaml.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/validate-pr.py 99

Or via the dispatcher (per COR-021):
  pkit project-management validate-pr 99

Exit codes:
  0  every check passed or only warning-level findings
  1  one or more hard-reject / bypassable findings
  2  usage error (PR not found)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
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
from _lib.placeholder_detection import (  # noqa: E402
    PHASE_CREATE,
    PHASE_TRANSITION,
    detect_placeholder_residuals,
)


SEVERITY_HARD_REJECT = "hard-reject"
SEVERITY_BYPASSABLE = "bypassable-with-audit"
SEVERITY_WARNING = "warning"

CLOSING_KEYWORD_RE = re.compile(
    r"\b(?:closes|fixes|resolves)\s+#(\d+)", re.IGNORECASE
)


@dataclass(frozen=True)
class Finding:
    severity: str
    label: str
    detail: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a GitHub PR against the methodology's title + body "
            "rules. Findings by severity; exit code is the contract."
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
        "--phase",
        choices=(PHASE_CREATE, PHASE_TRANSITION),
        default=PHASE_CREATE,
        help=(
            "Validation phase. 'create' (default) — PR body was just opened; "
            "empty-checkbox-section in ## Test plan is a warning. "
            "'transition' — merge gate; empty-checkbox-section is a hard-reject "
            "per DEC-031."
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

    titles = _read_yaml(capability_root / "schemas" / "titles.yaml", yaml_loader)
    classification = _read_yaml(
        capability_root / "schemas" / "classification.yaml", yaml_loader
    )
    git_conv = _read_yaml(
        capability_root / "schemas" / "git-conventions.yaml", yaml_loader
    )

    pr = _gh_get_pr(args.pr_number, config)
    if pr is None:
        return 2

    pr_title = str(pr.get("title", ""))
    pr_body = str(pr.get("body") or "")

    # Fetch closing-issue type labels (best-effort) for cross-check.
    closing_issues = _extract_closing_issues(pr_body)
    closing_type_labels = _gather_closing_type_labels(closing_issues)

    findings = _validate_pr(
        pr_title=pr_title,
        pr_body=pr_body,
        titles=titles,
        classification=classification,
        git_conv=git_conv,
        closing_type_labels=closing_type_labels,
        capability_root=capability_root,
        phase=args.phase,
    )

    if args.json:
        out = {
            "pr_number": args.pr_number,
            "pr_title": pr_title,
            "findings": [
                {"severity": f.severity, "label": f.label, "detail": f.detail}
                for f in findings
            ],
        }
        print(json.dumps(out, indent=2))
    else:
        _print_findings(args.pr_number, pr_title, findings)

    has_blocking = any(
        f.severity in (SEVERITY_HARD_REJECT, SEVERITY_BYPASSABLE)
        for f in findings
    )
    return 1 if has_blocking else 0


# ---- validation -----------------------------------------------------


def _validate_pr(
    *,
    pr_title: str,
    pr_body: str,
    titles: dict,
    classification: dict,
    git_conv: dict,
    closing_type_labels: list[str],
    capability_root: Path | None = None,
    phase: str = PHASE_CREATE,
) -> list[Finding]:
    findings: list[Finding] = []

    # Title regex.
    pattern = _pr_title_pattern(titles)
    if pattern:
        m = re.match(pattern, pr_title)
        if not m:
            findings.append(
                Finding(
                    SEVERITY_HARD_REJECT,
                    "title.pattern",
                    f"PR title does not match Conventional Commits "
                    f"pattern: {pattern!r}",
                )
            )
        else:
            # Cross-check the type with closing-issue labels.
            conv_type = m.group(1)
            expected_types = _expected_conv_types(closing_type_labels, classification)
            if expected_types and conv_type not in expected_types:
                if len(closing_type_labels) > 1:
                    # Multi-issue PR with mismatched types is a warning.
                    findings.append(
                        Finding(
                            SEVERITY_WARNING,
                            "title.type-mismatch",
                            f"PR <type>={conv_type!r} differs from "
                            "closing-issue type labels' mapping "
                            f"{expected_types!r}; multi-issue PR with mixed "
                            "types — warning per git-conventions.yaml.",
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            SEVERITY_HARD_REJECT,
                            "title.type-mismatch",
                            f"PR <type>={conv_type!r} does not match the "
                            f"closing issue's type:* label mapping "
                            f"{expected_types!r}.",
                        )
                    )

    # Body: closing keyword required.
    if not CLOSING_KEYWORD_RE.search(pr_body):
        findings.append(
            Finding(
                SEVERITY_HARD_REJECT,
                "body.closes",
                "PR body has no `Closes #N` / `Fixes #N` / `Resolves #N` "
                "reference (required by git-conventions.yaml).",
            )
        )

    # Body: Doc impact required.
    if "## Doc impact" not in pr_body:
        findings.append(
            Finding(
                SEVERITY_HARD_REJECT,
                "body.doc-impact",
                "PR body is missing the `## Doc impact` section "
                "(required by git-conventions.yaml).",
            )
        )

    # Residual-placeholder detection per DEC-031.
    # The PR template has a `## Test plan` checkbox section.  We build the
    # body_format structure the helper expects so no schema file is needed
    # on the PR side — the structure is derived from the live PR.md template
    # at runtime via the helper's `extract_placeholder_phrases` signal.
    if capability_root is not None:
        pr_body_format = _pr_body_format()
        for sev, label, detail in detect_placeholder_residuals(
            body=pr_body,
            structural_type="pr",
            body_format=pr_body_format,
            capability_root=capability_root,
            phase=phase,
        ):
            findings.append(Finding(sev, label, detail))

    return findings


# PR-body format descriptor for the placeholder-detection helper.
# Mirrors the body-format.yaml structure used by the issue side.
# The `## Test plan` section is the only required checkbox section
# in the PR template (PR.md).  `## Doc impact` and `## Summary` are
# prose sections; the helper's prose-fingerprint signal covers them.
_PR_BODY_FORMAT: dict = {
    "bodies": {
        "pr": {
            "required_sections": [
                {
                    "heading": "## Test plan",
                    "has_checkboxes": True,
                    "severity": "[validation-severity:hard-reject]",
                    "purpose": (
                        "Checkboxes describing the testing strategy. "
                        "Omit the section entirely for trivial changes; "
                        "when present, at least one authored item is required."
                    ),
                },
            ],
        },
    },
}


def _pr_body_format() -> dict:
    """Return the body-format descriptor for the PR placeholder check."""
    return _PR_BODY_FORMAT


def _pr_title_pattern(titles: dict) -> str | None:
    formats = titles.get("formats") or {}
    entry = formats.get("pr")
    if isinstance(entry, dict):
        p = entry.get("pattern")
        if isinstance(p, str):
            return p
    return None


def _extract_closing_issues(pr_body: str) -> list[int]:
    out: list[int] = []
    for m in CLOSING_KEYWORD_RE.finditer(pr_body or ""):
        n = int(m.group(1))
        if n not in out:
            out.append(n)
    return out


def _gather_closing_type_labels(closing_issues: list[int]) -> list[str]:
    out: list[str] = []
    for n in closing_issues:
        issue = _gh_get_issue(n, config)
        if issue is None:
            continue
        for lbl in issue.get("labels") or []:
            name = lbl.get("name") if isinstance(lbl, dict) else str(lbl)
            if isinstance(name, str) and name.startswith("type:"):
                out.append(name)
    return out


def _expected_conv_types(type_labels: list[str], classification: dict) -> list[str]:
    """Map each `type:*` label to its expected pr_conv_type."""
    mapping = classification.get("pr_type_mapping") or []
    out: list[str] = []
    for label in type_labels:
        value = label.removeprefix("type:")
        for entry in mapping:
            if not isinstance(entry, dict):
                continue
            if entry.get("issue_label_value") == value:
                t = entry.get("pr_conv_type")
                if isinstance(t, str) and t not in out:
                    out.append(t)
                alternates = entry.get("alternates") or []
                for alt in alternates:
                    if isinstance(alt, str) and alt not in out:
                        out.append(alt)
                break
    return out


def _print_findings(pr_number: int, pr_title: str, findings: list[Finding]) -> None:
    print(f"validating PR #{pr_number}: {pr_title}")
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
    n_block = len(by_severity.get(SEVERITY_HARD_REJECT, [])) + len(
        by_severity.get(SEVERITY_BYPASSABLE, [])
    )
    n_warn = len(by_severity.get(SEVERITY_WARNING, []))
    print(f"summary: {n_block} blocking, {n_warn} warning(s).")


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
                "title,body,state,url",
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
    return gh_get_issue(issue_number, config, fields="labels")


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
