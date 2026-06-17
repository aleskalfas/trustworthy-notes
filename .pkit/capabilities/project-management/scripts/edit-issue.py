#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — edit-issue (verb-subject per DEC-020).

Methodology-aware body edit. Fetches the current issue body via
`gh issue view --json body`, applies the requested change (--body /
--body-file / --append / --title), validates the new state against
`body-format.yaml` + `titles.yaml` + `issue-types.yaml`, and writes
back via `gh issue edit --body-file`.

Refuses on hard-reject validation findings; warns on warning-level
findings. The `--force` flag accepts hard-rejects with an audit
comment (DEC-014 bypassable-with-audit pattern).

Membership gate per DEC-021 runs at startup.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/edit-issue.py 42 --body-file new-body.md

Or via the dispatcher (per COR-021):
  pkit project-management edit-issue 42 --append "Additional context..."

Exit codes:
  0  edited (or dry-run reported)
  1  membership refusal / validation refusal
  2  usage error (issue not found; no mode specified)
  3  gh failure
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
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


SEVERITY_HARD_REJECT = "hard-reject"
SEVERITY_BYPASSABLE = "bypassable-with-audit"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    severity: str
    label: str
    detail: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Edit a GitHub issue's body or title. Validates the new state "
            "against the methodology's body + title rules before writing."
        ),
    )
    parser.add_argument(
        "issue_number",
        type=int,
        help="GitHub issue number.",
    )
    g = parser.add_mutually_exclusive_group()
    g.add_argument(
        "--body",
        default=None,
        help=(
            "Replace the body with the supplied text. Pass `-` to read "
            "from stdin."
        ),
    )
    g.add_argument(
        "--body-file",
        type=Path,
        default=None,
        help="Replace the body with the contents of this file.",
    )
    g.add_argument(
        "--append",
        default=None,
        help="Append the supplied text to the existing body (with a blank line separator).",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Replace the title (passed to `gh issue edit --title`).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Accept hard-reject validation findings with an audit comment "
            "(DEC-014 bypassable-with-audit pattern). Default: refuse on "
            "hard-reject."
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
        help="Print the plan + findings; do not invoke gh.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    args = parser.parse_args()

    if args.body is None and args.body_file is None and args.append is None and args.title is None:
        print(
            "error: nothing to edit. Pass --body, --body-file, --append, "
            "or --title.",
            file=sys.stderr,
        )
        return 2

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
    titles = _read_yaml(capability_root / "schemas" / "titles.yaml", yaml_loader)
    body_format = _read_yaml(
        capability_root / "schemas" / "body-format.yaml", yaml_loader
    )
    classification = _read_yaml(
        capability_root / "schemas" / "classification.yaml", yaml_loader
    )

    issue = _gh_get_issue(args.issue_number, config)
    if issue is None:
        return 2

    current_title = str(issue.get("title", ""))
    current_body = str(issue.get("body") or "")

    # Compute the new title + body.
    new_title = args.title if args.title is not None else current_title
    new_body = _compute_new_body(current_body, args)
    if new_body is None:
        return 2  # error already printed

    print(f"edit-issue: #{args.issue_number}")
    print(f"  current title: {current_title}")
    if args.title is not None:
        print(f"  new title:     {new_title}")
    print(
        f"  body change:   {len(current_body)} → {len(new_body)} chars"
    )

    # Validate the new state.
    findings = _validate(
        title=new_title,
        body=new_body,
        issue_types=issue_types,
        titles=titles,
        body_format=body_format,
        classification=classification,
    )
    _print_findings(findings)

    has_hard_reject = any(f.severity == SEVERITY_HARD_REJECT for f in findings)
    has_bypassable = any(f.severity == SEVERITY_BYPASSABLE for f in findings)

    if (has_hard_reject or has_bypassable) and not args.force:
        sev = "hard-reject" if has_hard_reject else "bypassable-with-audit"
        print(
            f"\n[refused] validation surfaced {sev} findings. "
            "Pass --force to write anyway (records an audit comment).",
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        print("\n[dry-run] gh would be invoked; nothing written.")
        return 0
    if not args.yes and sys.stdin.isatty():
        reply = input("Write the edit? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    # Audit comment on --force.
    if (has_hard_reject or has_bypassable) and args.force:
        audit_lines = [
            "[audit] edit applied despite validation findings (--force):",
        ]
        for f in findings:
            if f.severity in (SEVERITY_HARD_REJECT, SEVERITY_BYPASSABLE):
                audit_lines.append(f"  - [{f.severity}] {f.label}: {f.detail}")
        if not _gh_comment(args.issue_number, "\n".join(audit_lines)):
            return 3

    if not _gh_apply_edit(args.issue_number, title=new_title, body=new_body, current_title=current_title, config=config):
        return 3

    print(f"\n[ok] edited #{args.issue_number}.")
    return 0


# ---- body computation -----------------------------------------------


def _compute_new_body(current_body: str, args: argparse.Namespace) -> str | None:
    """Resolve the new-body content from the mutually-exclusive flags."""
    if args.body is not None:
        if args.body == "-":
            try:
                return sys.stdin.read()
            except OSError as exc:
                print(f"error: failed to read stdin: {exc}", file=sys.stderr)
                return None
        return args.body
    if args.body_file is not None:
        try:
            return args.body_file.read_text(encoding="utf-8")
        except OSError as exc:
            print(
                f"error: failed to read {args.body_file}: {exc}",
                file=sys.stderr,
            )
            return None
    if args.append is not None:
        sep = "\n\n" if current_body and not current_body.endswith("\n\n") else ""
        return current_body + sep + args.append
    return current_body


# ---- validation -----------------------------------------------------


def _validate(
    *,
    title: str,
    body: str,
    issue_types: dict,
    titles: dict,
    body_format: dict,
    classification: dict | None = None,
) -> list[Finding]:
    """Apply the body + title validators used by validate-issue.py."""
    findings: list[Finding] = []

    structural_type = _infer_structural_type(title, issue_types, classification or {})
    if structural_type is None:
        findings.append(
            Finding(
                SEVERITY_HARD_REJECT,
                "title.format",
                f"title {title!r} does not match any known [Type] prefix.",
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

    # Per-type required body sections.
    if structural_type is not None:
        bodies = body_format.get("bodies") or {}
        type_body = bodies.get(structural_type) or {}
        for section in type_body.get("required_sections") or []:
            if not isinstance(section, dict):
                continue
            heading = str(section.get("heading", ""))
            if heading and heading not in body:
                severity = _severity_from_token(section.get("severity"))
                findings.append(
                    Finding(
                        severity,
                        "body.required-section",
                        f"missing required section {heading!r}.",
                    )
                )

        # Parent-ref first line. Accepts three forms (parity with
        # validate-issue per #210):
        #   1. New canonical milestone link: `Milestone: [#<N>](../milestone/<N>)`
        #   2. Old plain milestone form: `Milestone: #<N>` (accepted with
        #      a deprecation warning during the grace period).
        #   3. Issue-parent form: `<Label>: #<N>` (EPIC, Feature, Umbrella,
        #      Task — anything that resolves through issue-types.yaml's
        #      `parent_ref_form`).
        type_entry = (issue_types.get("types") or {}).get(structural_type)
        if isinstance(type_entry, dict):
            parent_ref_optional = bool(type_entry.get("parent_ref_optional", False))
            parent_ref_form = str(type_entry.get("parent_ref_form", ""))
            if parent_ref_form and not parent_ref_optional:
                first_line = body.lstrip().split("\n", 1)[0]
                _NEW_MILESTONE_RE = re.compile(
                    r"^Milestone:\s+\[#(\d+)\]\(\.\./milestone/\1\)\s*$"
                )
                _OLD_MILESTONE_RE = re.compile(r"^Milestone:\s+#\d+\s*$")
                _ISSUE_PARENT_RE = re.compile(r"^[A-Za-z]+:\s+#\d+\s*$")

                if _NEW_MILESTONE_RE.match(first_line):
                    # New form — clean pass.
                    pass
                elif _OLD_MILESTONE_RE.match(first_line):
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
                    findings.append(
                        Finding(
                            SEVERITY_HARD_REJECT,
                            "body.parent-ref",
                            f"first body line does not match the parent-ref "
                            f"form {parent_ref_form!r}; got {first_line!r}.",
                        )
                    )

    # Universal body rules.
    if re.search(r"^# [^#]", body, flags=re.MULTILINE):
        findings.append(
            Finding(
                SEVERITY_HARD_REJECT,
                "body.h1",
                "body contains an h1 (`# ...`) heading; use `## Title`.",
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


def _infer_structural_type(
    title: str,
    issue_types: dict,
    classification: dict | None = None,
) -> str | None:
    """Infer the structural type from the title prefix.

    Checks two sources in order:
    1. issue-types.yaml `types[*].title_prefix` — the structural-type
       prefixes ([EPIC], [Feature], [Umbrella], [Task]).
    2. classification.yaml `axes.type.title_prefix_by_value` — the
       kind-driven prefixes ([Bug], [Docs], [Test], [Refactor], [Chore]).
       Kind-prefixes are restricted to the `task` structural type per the
       schema's `structural_restriction` rule.

    Returns the structural type string, or None when no prefix matches.
    """
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

    # Check kind-driven prefixes from classification.yaml.
    # These only appear on Task-shape issues (structural_restriction in schema).
    if classification:
        prefix_by_value = (
            classification.get("axes", {})
            .get("type", {})
            .get("title_prefix_by_value", {})
        )
        for _kind_value, kind_prefix in prefix_by_value.items():
            if isinstance(kind_prefix, str) and title.startswith(f"[{kind_prefix}] "):
                return "task"

    return None


def _title_pattern_for(titles: dict, structural_type: str) -> str | None:
    formats = titles.get("formats") or {}
    entry = formats.get(f"issue-{structural_type}")
    if isinstance(entry, dict):
        pattern = entry.get("pattern")
        if isinstance(pattern, str):
            return pattern
    return None


def _severity_from_token(token) -> str:
    if not isinstance(token, str):
        return SEVERITY_WARNING
    m = re.match(r"\[validation-severity:([a-z-]+)\]", token)
    if not m:
        return SEVERITY_WARNING
    return m.group(1)


def _print_findings(findings: list[Finding]) -> None:
    if not findings:
        print("\nvalidation: clean (no findings).")
        return
    print("\nvalidation findings:")
    for f in findings:
        print(f"  [{f.severity}] {f.label}: {f.detail}")


# ---- gh wrappers ----------------------------------------------------


def _gh_get_issue(issue_number: int, config: dict) -> dict | None:
    return gh_get_issue(issue_number, config, fields="title,body,state")


def _gh_apply_edit(
    issue_number: int,
    *,
    title: str,
    body: str,
    current_title: str,
    config: dict,
) -> bool:
    """Apply the edit via `gh issue edit --body-file`."""
    cmd = ["gh", "issue", "edit", str(issue_number)]
    if title != current_title:
        cmd.extend(["--title", title])
    # Always write body via a temp file — avoids shell length limits.
    with tempfile.NamedTemporaryFile(
        "w", suffix=".md", encoding="utf-8", delete=False
    ) as f:
        f.write(body)
        body_path = f.name
    try:
        cmd.extend(["--body-file", body_path])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return False
        if proc.returncode != 0:
            print(
                f"error: gh issue edit failed (exit {proc.returncode}).\n"
                f"stderr: {proc.stderr.strip()}",
                file=sys.stderr,
            )
            return False
    finally:
        try:
            Path(body_path).unlink(missing_ok=True)
        except OSError:
            pass
    return True


def _gh_comment(issue_number: int, body: str, config: dict) -> bool:
    try:
        proc = gh_run(
            ["gh", "issue", "comment", str(issue_number), "--body", body],
            config,
            check=False,
        )
    except FileNotFoundError:
        return False
    return proc.returncode == 0


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
