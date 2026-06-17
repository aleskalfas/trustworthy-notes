#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — edit-pr (verb-subject per DEC-020).

Edits a PR's body or title. Validates the new state against
titles.yaml's `pr` pattern + git-conventions.yaml's `pr-body` rules
before writing. Membership gate per DEC-021 runs at startup.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/edit-pr.py 99 --append "Additional notes..."

Or via the dispatcher (per COR-021):
  pkit project-management edit-pr 99 --title "..."

Exit codes:
  0  edited (or dry-run reported)
  1  membership refusal / validation refusal
  2  usage error
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
from _lib.gh import gh_run, load_adopter_config  # noqa: E402
from _lib.membership import (  # noqa: E402
    CAPABILITY_NAME,
    check_membership,
    resolve_capability_root,
    resolve_invoker_identity,
)


SEVERITY_HARD_REJECT = "hard-reject"
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
        description="Edit a GitHub PR's body or title with methodology validation.",
    )
    parser.add_argument(
        "pr_number",
        type=int,
        help="GitHub PR number.",
    )
    g = parser.add_mutually_exclusive_group()
    g.add_argument(
        "--body",
        default=None,
        help="Replace the body with the supplied text. `-` reads from stdin.",
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
        help="Append the supplied text to the existing body.",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Replace the PR title.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Accept hard-reject validation findings (audit-comment recorded).",
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

    titles = _read_yaml(capability_root / "schemas" / "titles.yaml", yaml_loader)

    pr = _gh_get_pr(args.pr_number, config)
    if pr is None:
        return 2

    current_title = str(pr.get("title", ""))
    current_body = str(pr.get("body") or "")

    new_title = args.title if args.title is not None else current_title
    new_body = _compute_new_body(current_body, args)
    if new_body is None:
        return 2

    print(f"edit-pr: #{args.pr_number}")
    print(f"  current title: {current_title}")
    if args.title is not None:
        print(f"  new title:     {new_title}")
    print(f"  body change:   {len(current_body)} → {len(new_body)} chars")

    findings = _validate(
        title=new_title,
        body=new_body,
        titles=titles,
    )
    _print_findings(findings)

    has_hard_reject = any(f.severity == SEVERITY_HARD_REJECT for f in findings)

    if has_hard_reject and not args.force:
        print(
            "\n[refused] validation surfaced hard-reject findings. "
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

    if has_hard_reject and args.force:
        audit_lines = ["[audit] edit applied despite hard-reject findings (--force):"]
        for f in findings:
            if f.severity == SEVERITY_HARD_REJECT:
                audit_lines.append(f"  - {f.label}: {f.detail}")
        if not _gh_pr_comment(args.pr_number, "\n".join(audit_lines)):
            return 3

    if not _gh_apply_edit(
        args.pr_number,
        title=new_title,
        body=new_body,
        current_title=current_title,
        config=config,
    ):
        return 3
    print(f"\n[ok] edited PR #{args.pr_number}.")
    return 0


def _compute_new_body(current_body: str, args: argparse.Namespace) -> str | None:
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
            print(f"error: failed to read {args.body_file}: {exc}", file=sys.stderr)
            return None
    if args.append is not None:
        sep = "\n\n" if current_body and not current_body.endswith("\n\n") else ""
        return current_body + sep + args.append
    return current_body


def _validate(*, title: str, body: str, titles: dict) -> list[Finding]:
    findings: list[Finding] = []
    pattern = _pr_title_pattern(titles)
    if pattern and not re.match(pattern, title):
        findings.append(
            Finding(
                SEVERITY_HARD_REJECT,
                "title.pattern",
                f"PR title does not match Conventional Commits pattern: {pattern!r}",
            )
        )
    if not CLOSING_KEYWORD_RE.search(body):
        findings.append(
            Finding(
                SEVERITY_HARD_REJECT,
                "body.closes",
                "PR body has no `Closes #N` / `Fixes #N` / `Resolves #N` reference.",
            )
        )
    if "## Doc impact" not in body:
        findings.append(
            Finding(
                SEVERITY_HARD_REJECT,
                "body.doc-impact",
                "PR body is missing the `## Doc impact` section.",
            )
        )
    return findings


def _pr_title_pattern(titles: dict) -> str | None:
    formats = titles.get("formats") or {}
    entry = formats.get("pr")
    if isinstance(entry, dict):
        p = entry.get("pattern")
        if isinstance(p, str):
            return p
    return None


def _print_findings(findings: list[Finding]) -> None:
    if not findings:
        print("\nvalidation: clean (no findings).")
        return
    print("\nvalidation findings:")
    for f in findings:
        print(f"  [{f.severity}] {f.label}: {f.detail}")


def _gh_get_pr(pr_number: int, config: dict) -> dict | None:
    try:
        proc = gh_run(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--json",
                "title,body,state",
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


def _gh_apply_edit(
    pr_number: int, *, title: str, body: str, current_title: str
, config: dict) -> bool:
    cmd = ["gh", "pr", "edit", str(pr_number)]
    if title != current_title:
        cmd.extend(["--title", title])
    with tempfile.NamedTemporaryFile(
        "w", suffix=".md", encoding="utf-8", delete=False
    ) as f:
        f.write(body)
        body_path = f.name
    cmd.extend(["--body-file", body_path])
    try:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return False
        if proc.returncode != 0:
            print(
                f"error: gh pr edit failed (exit {proc.returncode}).\n"
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


def _gh_pr_comment(pr_number: int, body: str, config: dict) -> bool:
    try:
        proc = gh_run(
            ["gh", "pr", "comment", str(pr_number), "--body", body],
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
