#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — create-milestone (verb-subject per DEC-020).

Files a new GitHub Milestone in a declared category from
`project/config.yaml`'s `milestone_categories:` block. Reads the
category's `title_format` (with `{n}` + `{name}` placeholders),
queries existing milestones in the category to compute the next
number (max declared + 1), composes the body with the `Close trigger:`
first line per DEC-016, posts to GitHub via `gh api`.

Per [project-management:DEC-016-time-bound-containers]:
  - Category declaration is mandatory before any Milestone is filed.
  - Filing outside declared categories is a hard-reject.
  - The category's title_format must include `{n}` + `{name}` placeholders.
  - Each instance carries an explicit `Close trigger:` first body line.

Membership gate per DEC-021 runs at startup.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/create-milestone.py <category> --name "..."

Or via the dispatcher:
  pkit project-management create-milestone <category> --name "..."

Exit codes:
  0  milestone created (or dry-run)
  1  membership refusal
  2  usage error (no categories declared / category not declared / invalid format)
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
from _lib.gh import gh_run, load_adopter_config  # noqa: E402
from _lib.membership import (  # noqa: E402
    CAPABILITY_NAME,
    check_membership,
    resolve_capability_root,
    resolve_invoker_identity,
)


VALID_CLOSE_TRIGGERS = ("date-based", "content-based", "either")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "File a new GitHub Milestone in a declared category from "
            "project/config.yaml's milestone_categories: block. Computes "
            "the next number for the category, composes the title from "
            "the category's title_format, and posts to GitHub."
        ),
    )
    parser.add_argument(
        "category",
        help=(
            "Name of a milestone category declared in "
            "project/config.yaml's milestone_categories: block."
        ),
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Semantic name; substituted into the category's title_format {name} placeholder.",
    )
    parser.add_argument(
        "--number",
        type=int,
        default=None,
        help=(
            "Override the auto-computed number. Default: max declared "
            "in this category + 1."
        ),
    )
    parser.add_argument(
        "--close-trigger",
        choices=VALID_CLOSE_TRIGGERS,
        default=None,
        help=(
            "Override the category's default close-trigger for this "
            "instance. Valid: date-based, content-based, either."
        ),
    )
    parser.add_argument(
        "--due-on",
        default=None,
        help="ISO 8601 date for date-based / either close triggers (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--description",
        default="",
        help="Optional body text after the `Close trigger:` first line.",
    )
    parser.add_argument(
        "--capability-root",
        type=Path,
        default=None,
        help=f"Path to the installed capability's directory (default: <repo-root>/.pkit/capabilities/{CAPABILITY_NAME}/).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the plan; don't invoke gh.")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
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

    # Read milestone_categories from adopter config.
    config = _read_yaml(capability_root / "project" / "config.yaml", yaml_loader)
    categories = config.get("milestone_categories")
    if not isinstance(categories, dict) or not categories:
        print(
            "error: no milestone categories declared in "
            f".pkit/capabilities/{CAPABILITY_NAME}/project/config.yaml. "
            "Per [project-management:DEC-016-time-bound-containers], "
            "at least one milestone_categories: entry is required "
            "before any Milestone is filed. Declare a category first, "
            "then re-run.",
            file=sys.stderr,
        )
        return 2

    if args.category not in categories:
        declared = ", ".join(sorted(categories.keys()))
        print(
            f"error: category {args.category!r} is not declared in "
            f"milestone_categories:. Declared categories: {declared}.",
            file=sys.stderr,
        )
        return 2

    cat = categories[args.category]
    if not isinstance(cat, dict):
        print(
            f"error: milestone_categories.{args.category} is malformed "
            "(must be a mapping with title_format + close_trigger_default).",
            file=sys.stderr,
        )
        return 2

    title_format = cat.get("title_format")
    if not isinstance(title_format, str) or not title_format:
        print(
            f"error: milestone_categories.{args.category}.title_format is "
            "missing or not a string. Expected a Python format-string with "
            "{n} and {name} placeholders.",
            file=sys.stderr,
        )
        return 2

    if "{n}" not in title_format or "{name}" not in title_format:
        print(
            f"error: title_format {title_format!r} must contain both "
            "{n} (number) and {name} (semantic) placeholders.",
            file=sys.stderr,
        )
        return 2

    close_trigger = args.close_trigger or cat.get("close_trigger_default")
    if close_trigger not in VALID_CLOSE_TRIGGERS:
        print(
            f"error: close_trigger {close_trigger!r} is not valid. "
            f"Must be one of: {', '.join(VALID_CLOSE_TRIGGERS)}.",
            file=sys.stderr,
        )
        return 2

    # Compute the next number for this category.
    if args.number is not None:
        n = args.number
    else:
        n = _next_number_for_category(title_format, config)
        if n is None:
            return 3  # gh failure already printed

    # Compose the title + body.
    try:
        title = title_format.format(n=n, name=args.name)
    except KeyError as exc:
        print(
            f"error: title_format references undeclared placeholder {exc}. "
            "Only {n} and {name} are supported.",
            file=sys.stderr,
        )
        return 2

    body_lines = [f"Close trigger: {close_trigger}"]
    if args.description:
        body_lines.append("")
        body_lines.append(args.description)
    body = "\n".join(body_lines)

    # Preview.
    print("about to create milestone:")
    print(f"  category:      {args.category}")
    print(f"  title:         {title}")
    print(f"  close_trigger: {close_trigger}")
    if args.due_on:
        print(f"  due_on:        {args.due_on}")
    print(f"  body:")
    for line in body.splitlines():
        print(f"    {line}")

    if args.dry_run:
        print("\n[dry-run] gh would be invoked; nothing written.")
        return 0

    if not args.yes and sys.stdin.isatty():
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    # Detect dupe.
    if _existing_milestone_with_title(title, config) is not None:
        print(
            f"error: a milestone titled {title!r} already exists on the repo. "
            f"Pass --number explicitly to choose a different number, or "
            f"rename the existing milestone first.",
            file=sys.stderr,
        )
        return 2

    url = _gh_create_milestone(title=title, body=body, due_on=args.due_on, config=config)
    if url is None:
        return 3
    print(f"\n[ok] created: {url}")
    return 0


# ---- numbering ------------------------------------------------------


def _title_format_to_regex(title_format: str) -> re.Pattern:
    """Convert a Python-style title_format to a regex with named `n` group.

    Input: "Milestone {n}: {name}"
    Output: regex compiled from "^Milestone (?P<n>\\d+): (?P<name>.+)$"
    """
    # re.escape() escapes literal braces too — un-escape them so we can
    # substitute placeholders.
    escaped = re.escape(title_format)
    escaped = escaped.replace(r"\{n\}", r"(?P<n>\d+)")
    escaped = escaped.replace(r"\{name\}", r"(?P<name>.+)")
    return re.compile(f"^{escaped}$")


def _next_number_for_category(title_format: str, config: dict | None = None) -> int | None:
    """Find max existing `n` for milestones matching the category's title format; return n+1.

    Queries the repo's milestones (open + closed) via `gh api --paginate`,
    matches each title against the category's regex, takes the highest
    number, returns max+1. Returns 1 when no existing milestones match.
    Returns None on `gh` failure (caller surfaces).
    """
    regex = _title_format_to_regex(title_format)
    milestones = _gh_list_milestones(config)
    if milestones is None:
        return None
    max_n = 0
    for m in milestones:
        title = m.get("title", "")
        match = regex.match(title)
        if match is None:
            continue
        try:
            n = int(match.group("n"))
        except (ValueError, IndexError):
            continue
        if n > max_n:
            max_n = n
    return max_n + 1


def _existing_milestone_with_title(title: str, config: dict | None = None) -> dict | None:
    """Return the milestone dict if one with this exact title already exists, else None."""
    milestones = _gh_list_milestones(config) or []
    for m in milestones:
        if m.get("title") == title:
            return m
    return None


# ---- gh helpers -----------------------------------------------------


def _detect_repo(config: dict) -> tuple[str, str] | None:
    """Detect (hostname, nameWithOwner) from gh's view of the current repo.

    `gh api` defaults to host `github.com` even when the cwd's git remote
    points elsewhere. To support enterprise instances (github.com,
    self-hosted, …), the script extracts both the hostname (from the
    repo's HTTPS URL) and the nameWithOwner string explicitly, then
    passes them to subsequent gh api calls.
    """
    try:
        proc = gh_run(
            ["gh", "repo", "view", "--json", "url,nameWithOwner"],
            config,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    url = data.get("url") or ""
    name_with_owner = data.get("nameWithOwner") or ""
    if not name_with_owner:
        return None
    m = re.match(r"https?://([^/]+)/", url)
    hostname = m.group(1) if m else "github.com"
    return hostname, name_with_owner


def _gh_list_milestones(config: dict | None = None) -> list[dict] | None:
    """List all milestones (open + closed) on the current repo via `gh api`."""
    repo = _detect_repo(config or {})
    if repo is None:
        print(
            "error: could not detect the current repo via `gh repo view`. "
            "Run this from within a git checkout where `gh` is authenticated "
            "to the appropriate host.",
            file=sys.stderr,
        )
        return None
    hostname, name_with_owner = repo
    try:
        proc = gh_run(
            [
                "gh",
                "api",
                "--hostname",
                hostname,
                "--paginate",
                f"repos/{name_with_owner}/milestones?state=all",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        print("error: `gh` not on PATH.", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(
            f"error: gh failed listing milestones (exit {proc.returncode}).\n"
            f"stderr: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return None
    # --paginate concatenates JSON arrays with no separator; parse defensively.
    out = proc.stdout.strip()
    if not out:
        return []
    try:
        # If single page: clean JSON array.
        return json.loads(out)
    except json.JSONDecodeError:
        # Multi-page: gh emits multiple JSON arrays back-to-back; split.
        results: list[dict] = []
        depth = 0
        start = 0
        for i, ch in enumerate(out):
            if ch == "[":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    chunk = out[start : i + 1]
                    try:
                        results.extend(json.loads(chunk))
                    except json.JSONDecodeError:
                        pass
        return results


def _gh_create_milestone(*, title: str, body: str, due_on: str | None, config: dict) -> str | None:
    """POST a new milestone via `gh api`; return the html_url on success."""
    repo = _detect_repo(config or {})
    if repo is None:
        print(
            "error: could not detect the current repo via `gh repo view`.",
            file=sys.stderr,
        )
        return None
    hostname, name_with_owner = repo
    args = [
        "gh",
        "api",
        "--hostname",
        hostname,
        "-X",
        "POST",
        f"repos/{name_with_owner}/milestones",
        "-f",
        f"title={title}",
        "-f",
        f"description={body}",
    ]
    if due_on:
        # GitHub API expects ISO 8601 with Z; accept date-only and pad.
        if len(due_on) == 10 and due_on.count("-") == 2:
            due_iso = f"{due_on}T23:59:59Z"
        else:
            due_iso = due_on
        args.extend(["-f", f"due_on={due_iso}"])
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        print("error: `gh` not on PATH.", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(
            f"error: gh failed creating milestone (exit {proc.returncode}).\n"
            f"stderr: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print("error: gh returned non-JSON.", file=sys.stderr)
        return None
    return data.get("html_url") or data.get("url")


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


if __name__ == "__main__":
    sys.exit(main())
