#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — create-issue (verb-subject per DEC-020).

Files a new issue against the methodology's body shape: validates the
type, stamps the title against `titles.yaml`'s per-type regex,
composes the body from the matching `templates/<Type>.md`, applies the
classification axes (type:*, priority:*, workstream:* per
`classification.yaml`), and posts the issue via `gh issue create`.

For board-substrate adopters (per DEC-019 +
`schemas/mandatory-issue-state.yaml`), the new issue is also added to
the configured Projects v2 board as the final step of filing. The
default assignee is the resolved invoker identity per DEC-019's
default_at_filing: filer.

Membership predicate per DEC-021 runs at startup; closed mode refuses
non-members with the standard structured refusal.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/create-issue.py

Or, via the dispatcher (per COR-021):
  pkit project-management create-issue --type task --title "..."

Exit codes:
  0  issue created
  1  membership refusal
  2  usage error / validation refusal
  3  gh failure (auth, network, repo not found, ...)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
from _lib.gh import gh_run, load_adopter_config  # noqa: E402
from _lib.hooks import fire_hooks  # noqa: E402
from _lib.membership import (  # noqa: E402
    CAPABILITY_NAME,
    check_membership,
    resolve_capability_root,
    resolve_invoker_identity,
)
from _lib.milestone import resolve_milestone  # noqa: E402
from _lib.placeholder_detection import (  # noqa: E402
    PHASE_CREATE,
    detect_placeholder_residuals,
)


VALID_STRUCTURAL_TYPES = ("epic", "feature", "umbrella", "task")
VALID_KINDS = ("feature", "bug", "docs", "test", "refactor", "maintenance")
VALID_PRIORITIES = ("High", "Medium", "Low")
DEFAULT_KIND = "feature"
DEFAULT_PRIORITY = "Medium"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "File a new issue against the project-management methodology's "
            "body shape. Composes title + body from the type's template + "
            "titles regex, applies classification labels, optionally adds "
            "to the configured Projects v2 board (per DEC-019)."
        ),
    )
    parser.add_argument(
        "--type",
        required=True,
        choices=VALID_STRUCTURAL_TYPES,
        help="Structural issue type per issue-types.yaml.",
    )
    parser.add_argument(
        "--title",
        required=True,
        help="Title text (without the [Type] prefix — that's prepended automatically).",
    )
    parser.add_argument(
        "--kind",
        choices=VALID_KINDS,
        default=DEFAULT_KIND,
        help=(
            "Classification axis `type:*` value per classification.yaml. "
            f"Default: {DEFAULT_KIND}. Drives PR-title alignment when the "
            "issue closes."
        ),
    )
    parser.add_argument(
        "--priority",
        choices=VALID_PRIORITIES,
        default=DEFAULT_PRIORITY,
        help=f"Priority axis per classification.yaml. Default: {DEFAULT_PRIORITY}.",
    )
    parser.add_argument(
        "--workstream",
        default=None,
        help=(
            "Workstream slug per the adopter's workstreams list. Required "
            "in label-fallback mode (no Projects v2 board)."
        ),
    )
    parser.add_argument(
        "--parent",
        type=int,
        default=None,
        help=(
            "Parent issue number. Substituted into the body template's "
            "first parent-ref line. Validated against issue-types.yaml's "
            "containment graph."
        ),
    )
    parser.add_argument(
        "--assignee",
        default=None,
        help="Assignee GitHub login. Defaults to the resolved invoker identity.",
    )
    parser.add_argument(
        "--milestone",
        default=None,
        help=(
            "Milestone to attach. Accepts the milestone number "
            "(e.g. `6`) or its exact title (e.g. "
            "`Milestone 1: Self-host project-kit pm capability cleanly`). "
            "Matches `gh issue create --milestone`'s permissive behaviour."
        ),
    )
    parser.add_argument(
        "--body-file",
        type=Path,
        default=None,
        help=(
            "Path to a file whose content becomes the issue body, "
            "bypassing the template-based composition. The file's "
            "first line must be the parent-ref per the issue type's "
            "`parent_ref_form` (the same first-line check the "
            "template-composition path enforces). Useful when the "
            "caller has the full body already prepared (e.g. agent "
            "filing). See #218."
        ),
    )
    parser.add_argument(
        "--board",
        type=int,
        default=None,
        help=(
            "Projects v2 board ID. Overrides the adopter's "
            "`projects_v2_board_id` config for this invocation."
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
        help="Print what would be done; do not invoke gh.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt before invoking gh.",
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

    # Membership gate first.
    config = load_adopter_config(capability_root)
    members = _read_members(capability_root, yaml_loader)
    invoker = resolve_invoker_identity(config=config)
    membership = check_membership(members, invoker)
    if not membership.allowed:
        print(membership.refusal_message, file=sys.stderr)
        return 1

    # Read schemas + adopter config.
    issue_types = _read_yaml(
        capability_root / "schemas" / "issue-types.yaml", yaml_loader
    )
    titles = _read_yaml(
        capability_root / "schemas" / "titles.yaml", yaml_loader
    )
    body_format = _read_yaml(
        capability_root / "schemas" / "body-format.yaml", yaml_loader
    )
    config = _read_yaml(
        capability_root / "project" / "config.yaml", yaml_loader
    )

    type_entry = (issue_types.get("types") or {}).get(args.type)
    if not isinstance(type_entry, dict):
        print(
            f"error: issue-types.yaml has no entry for type {args.type!r}.",
            file=sys.stderr,
        )
        return 2

    # Compose the full title with the type's title_prefix.
    title_prefix = type_entry.get("title_prefix", args.type.capitalize())
    title_case = type_entry.get("title_case", "title")
    if title_case == "upper":
        title_prefix = str(title_prefix).upper()
    full_title = f"[{title_prefix}] {args.title.strip()}"

    # Validate against titles.yaml's pattern for this surface.
    title_pattern = _title_pattern_for(titles, args.type)
    if title_pattern and not re.match(title_pattern, full_title):
        print(
            f"error: composed title {full_title!r} does not match "
            f"titles.yaml pattern for {args.type!r}: {title_pattern!r}",
            file=sys.stderr,
        )
        return 2

    # Validate parent type (if --parent given).
    parent_issue_types = type_entry.get("parent_issue_types") or []
    parent_ref_optional = bool(type_entry.get("parent_ref_optional", False))
    milestone_is_valid_parent = "milestone" in parent_issue_types
    if (
        args.parent is None
        and not parent_ref_optional
        and not (args.milestone is not None and milestone_is_valid_parent)
    ):
        print(
            f"error: --parent is required for issue type {args.type!r}. "
            f"Permitted parent types: {', '.join(parent_issue_types) or '<none>'}. "
            f"You may pass --milestone instead when milestone is a permitted parent.",
            file=sys.stderr,
        )
        return 2

    # Resolve --milestone (accepts number OR title; per #217).
    # Normalises `args.milestone` to the int form so downstream code
    # (parent-ref URL composition, display) sees a single shape. The
    # TITLE is kept separately because `gh issue create --milestone`
    # matches by NAME only (`gh issue create --help`: "Add the issue to
    # a milestone by name") — passing the number fails with
    # "could not add to milestone '<N>': '<N>' not found" (#223).
    milestone_title: str | None = None
    if args.milestone is not None:
        resolved = resolve_milestone(str(args.milestone), config)
        if resolved is None:
            print(
                f"error: --milestone {args.milestone!r} did not match any "
                "OPEN milestone (tried as number, then as title). "
                "List with `gh api repos/<owner>/<repo>/milestones?state=open`.",
                file=sys.stderr,
            )
            return 2
        args.milestone = resolved.number
        milestone_title = resolved.title

    # Workstream requirement when in label-fallback mode.
    has_board = bool(config.get("has_projects_v2_board", False))
    if not has_board and args.workstream is None:
        print(
            "error: --workstream is required in label-fallback mode "
            "(no Projects v2 board configured in project/config.yaml).",
            file=sys.stderr,
        )
        return 2

    # Workstream value validation against adopter config.
    if args.workstream is not None:
        adopter_workstreams = _adopter_workstreams(config)
        if adopter_workstreams and args.workstream not in adopter_workstreams:
            print(
                f"error: workstream {args.workstream!r} is not in the "
                "adopter's declared workstreams list "
                f"({', '.join(sorted(adopter_workstreams))}).",
                file=sys.stderr,
            )
            return 2

    # Compose the body. Two paths per #218:
    #   1. --body-file: read the file's content verbatim. The first
    #      line must match the parent-ref form (same check the
    #      validator + edit-issue apply); errors out otherwise.
    #   2. Default: stamp from the type's template + parent-ref line.
    expected_parent_ref = _parent_ref_line(
        type_entry,
        parent_num=args.parent,
        milestone_num=args.milestone,
    )
    if args.body_file is not None:
        if not args.body_file.is_file():
            print(
                f"error: --body-file path {str(args.body_file)!r} is not a file.",
                file=sys.stderr,
            )
            return 2
        try:
            body = args.body_file.read_text(encoding="utf-8")
        except OSError as exc:
            print(
                f"error: failed to read --body-file {str(args.body_file)!r}: {exc}",
                file=sys.stderr,
            )
            return 2
        first_line = body.lstrip().split("\n", 1)[0]
        if expected_parent_ref and first_line.strip() != expected_parent_ref.strip():
            print(
                f"error: --body-file's first line must be the parent-ref "
                f"line for this issue type. Expected:\n  {expected_parent_ref}\n"
                f"Got:\n  {first_line}",
                file=sys.stderr,
            )
            return 2
    else:
        template_path = capability_root / "templates" / f"{title_prefix}.md"
        if not template_path.is_file():
            # Fall back to title-case for the file (e.g., Feature.md).
            template_path = (
                capability_root / "templates" / f"{type_entry.get('title_prefix', '')}.md"
            )
        body = _compose_body(template_path, parent_ref=expected_parent_ref)

    # Residual-placeholder check at create-phase (DEC-031).
    # Emits warnings when the composed body is still the raw skeleton so
    # the author sees the unfinished state from the first moment.  Does
    # NOT block filing — the hard-reject gate fires at the first
    # lifecycle transition via validate-issue --phase transition.
    _warn_placeholder_residuals(body, args.type, body_format, capability_root)

    # Resolve assignee.
    assignee = args.assignee or invoker.github_login
    if not assignee:
        print(
            "error: could not resolve assignee. Pass --assignee explicitly "
            "or ensure `gh api user` works (sets the default).",
            file=sys.stderr,
        )
        return 2

    # Labels.
    labels = [f"type:{args.kind}"]
    if not has_board:
        labels.append(f"priority:{args.priority}")
        labels.append(f"workstream:{args.workstream}")

    # Pre-flight summary.
    print("about to create issue:")
    print(f"  title:      {full_title}")
    print(f"  type:       {args.type}  (structural)")
    print(f"  kind:       type:{args.kind}  (classification label)")
    print(f"  priority:   {args.priority}")
    if args.workstream:
        print(f"  workstream: {args.workstream}")
    if args.parent:
        print(f"  parent:     #{args.parent}")
    if args.milestone:
        print(f"  milestone:  #{args.milestone}")
    print(f"  assignee:   {assignee}")
    print(f"  labels:     {', '.join(labels)}")
    board_id = args.board if args.board is not None else config.get("projects_v2_board_id")
    if has_board:
        print(f"  board:      v2/{board_id}  (auto-add per DEC-019)")

    if args.dry_run:
        print("\n[dry-run] gh would be invoked; nothing written.")
        return 0

    if not args.yes and sys.stdin.isatty():
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    # Invoke gh issue create.
    issue_url = _gh_create_issue(
        title=full_title,
        body=body,
        labels=labels,
        assignee=assignee,
        milestone_title=milestone_title,
        config=config,
    )
    if issue_url is None:
        return 3

    print(f"\n[ok] created: {issue_url}")

    # Auto-add to board for board-substrate adopters (per DEC-019).
    if has_board and board_id:
        if not _gh_add_to_board(board_id, issue_url, config):
            print(
                f"[warn] issue created but failed to add to board v2/{board_id}.",
                file=sys.stderr,
            )

    # Fire lifecycle hooks per DEC-024. Report-and-continue contract:
    # hook failures don't propagate to this script's exit code.
    issue_number = _extract_issue_number_from_url(issue_url)
    fire_hooks(
        "after_create_issue",
        context={
            "issue": {"number": issue_number, "title": full_title},
            "repo": _resolve_repo_name_with_owner_safe(),
        },
        config=config,
        capability_root=capability_root,
    )

    return 0


def _warn_placeholder_residuals(
    body: str,
    structural_type: str,
    body_format: dict,
    capability_root: Path,
) -> None:
    """Emit stderr warnings when *body* still contains template-skeleton content.

    Runs at create-phase (DEC-031): the hard-reject gate lives in
    validate-issue --phase transition.  Filing is not blocked; the warnings
    make the unfinished body visible from the first moment.
    """
    findings = detect_placeholder_residuals(
        body=body,
        structural_type=structural_type,
        body_format=body_format,
        capability_root=capability_root,
        phase=PHASE_CREATE,
    )
    for _sev, label, detail in findings:
        print(f"[warning] {label}: {detail}", file=sys.stderr)


def _extract_issue_number_from_url(url: str) -> int | None:
    """Parse the trailing issue number from `gh issue create`'s URL output."""
    m = re.search(r"/issues/(\d+)(?:[/?#].*)?$", url.strip())
    return int(m.group(1)) if m else None


def _resolve_repo_name_with_owner_safe() -> str:
    """Best-effort `owner/name` resolution for hook context. Empty on failure."""
    try:
        proc = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


# ---- schema helpers --------------------------------------------------


def _read_yaml(path: Path, yaml_loader: YAML) -> dict:
    if not path.is_file():
        return {}
    try:
        data = yaml_loader.load(path.read_text(encoding="utf-8"))
    except (OSError, YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_members(capability_root: Path, yaml_loader: YAML) -> list[dict]:
    path = capability_root / "project" / "members.yaml"
    data = _read_yaml(path, yaml_loader)
    members = data.get("members") or []
    return members if isinstance(members, list) else []


def _title_pattern_for(titles: dict, structural_type: str) -> str | None:
    """Look up the titles.yaml regex for the given structural type."""
    formats = titles.get("formats") or {}
    key = f"issue-{structural_type}"
    entry = formats.get(key)
    if isinstance(entry, dict):
        pattern = entry.get("pattern")
        if isinstance(pattern, str):
            return pattern
    return None


def _adopter_workstreams(config: dict) -> set[str]:
    """Extract the adopter's declared workstream slugs.

    Supports both the v0.2.0 shape (`workstreams:` as a bare list in
    config.yaml) and the v0.5.0 shape (mapping form per DEC-018) as a
    forward-compatible read.
    """
    ws = config.get("workstreams")
    if isinstance(ws, list):
        out: set[str] = set()
        for entry in ws:
            if isinstance(entry, str):
                out.add(entry)
        return out
    if isinstance(ws, dict):
        return set(ws.keys())
    return set()


def _parent_ref_line(
    type_entry: dict,
    parent_num: int | None,
    milestone_num: int | None = None,
) -> str:
    """Build the parent-ref line that goes at the top of the body.

    When ``milestone_num`` is given (and the type permits milestone as a
    parent), emits the markdown-link form so the rendered link points to
    the actual milestone rather than auto-linking to an issue:
        ``Milestone: [#<N>](../milestone/<N>)``

    When ``parent_num`` is given, emits the plain ``<Label>: #<N>`` form
    (issue auto-links are correct for issue parents).
    """
    if milestone_num is not None and "milestone" in (
        type_entry.get("parent_issue_types") or []
    ):
        return f"Milestone: [#{milestone_num}](../milestone/{milestone_num})"
    if parent_num is None:
        return ""
    form = type_entry.get("parent_ref_form", "Parent: #<N>")
    # form is like "Feature: #<N>" or "EPIC: #<N> or Umbrella: #<N>" — pick
    # the first label fragment before the `:` and use it.
    head = str(form).split(":", 1)[0].strip()
    if " or " in head:
        head = head.split(" or ", 1)[0].strip()
    return f"{head}: #{parent_num}"


def _compose_body(template_path: Path, parent_ref: str) -> str:
    """Read the template, strip GitHub-issue-template frontmatter, substitute parent ref."""
    if not template_path.is_file():
        # Minimal fallback body.
        return parent_ref + ("\n\n" if parent_ref else "")
    raw = template_path.read_text(encoding="utf-8")
    body = _strip_issue_template_frontmatter(raw)
    if parent_ref:
        # Replace the first `<Label>: #` placeholder line (e.g., `Feature: #`)
        # with the actual parent ref.
        body = re.sub(
            r"^([A-Za-z]+)(:\s*)#\s*$",
            parent_ref,
            body,
            count=1,
            flags=re.MULTILINE,
        )
    return body


def _strip_issue_template_frontmatter(raw: str) -> str:
    """Remove a leading `---\\n...---\\n` block if present."""
    if not raw.startswith("---\n"):
        return raw
    end = raw.find("\n---\n", 4)
    if end < 0:
        return raw
    return raw[end + len("\n---\n"):]


# ---- gh helpers ------------------------------------------------------


def _gh_create_issue(
    *,
    title: str,
    body: str,
    labels: list[str],
    assignee: str,
    milestone_title: str | None,
    config: dict,
) -> str | None:
    """Invoke `gh issue create` and return the issue URL on success.

    ``milestone_title`` is the milestone's NAME, not its number:
    `gh issue create --milestone` matches by name only (#223).
    """
    cmd = [
        "gh",
        "issue",
        "create",
        "--title",
        title,
        "--body",
        body,
        "--assignee",
        assignee,
    ]
    for label in labels:
        cmd.extend(["--label", label])
    if milestone_title is not None:
        cmd.extend(["--milestone", milestone_title])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        print("error: `gh` not on PATH. Install GitHub CLI.", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(
            f"error: gh issue create failed (exit {proc.returncode}).\n"
            f"stderr: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return None
    # gh prints the URL on stdout.
    return proc.stdout.strip() or None


def _gh_add_to_board(board_id: int, issue_url: str, config: dict) -> bool:
    """Add an issue to a Projects v2 board via gh project item-add.

    The owner is derived from the issue URL (github.com/<owner>/<repo>/...).
    """
    # Extract owner from issue URL.
    m = re.match(r"https?://[^/]+/([^/]+)/", issue_url)
    if not m:
        return False
    owner = m.group(1)
    cmd = [
        "gh",
        "project",
        "item-add",
        str(board_id),
        "--owner",
        owner,
        "--url",
        issue_url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False
    return proc.returncode == 0


if __name__ == "__main__":
    sys.exit(main())
