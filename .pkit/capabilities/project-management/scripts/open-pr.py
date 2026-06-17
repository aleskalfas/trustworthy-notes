#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — open-pr (verb-subject per DEC-020).

Opens a PR per the methodology's branch + PR conventions
(git-conventions.yaml + titles.yaml + classification.yaml).

Inputs:
  * Current branch must match `git-conventions.yaml`'s branch-name
    pattern (refused if not).
  * Closing issue number — derived from the branch name's `<N>`
    segment unless overridden by `--closes`.
  * PR Conventional-Commits `<type>` — derived from the closing
    issue's `type:*` label via classification.yaml's pr_type_mapping;
    overridden by `--type`.
  * PR title scope — extracted from caller via `--scope` or omitted.
  * PR body — `templates/PR.md` skeleton with the `Closes #N`
    placeholder filled in; user-supplied `--body-file` overrides.

Membership gate per DEC-021 runs at startup.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/open-pr.py --scope cli --summary "add new dispatcher"

Or via the dispatcher (per COR-021):
  pkit project-management open-pr --summary "..."

Exit codes:
  0  PR opened (or dry-run reported)
  1  membership refusal / validation refusal
  2  usage error (not on a feature branch; closing issue not found)
  3  gh failure
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Open a GitHub PR per the methodology's branch + PR + title "
            "conventions. Derives the closing issue from the current branch "
            "name; derives the Conventional Commits <type> from the issue's "
            "type:* label."
        ),
    )
    parser.add_argument(
        "--closes",
        type=int,
        default=None,
        help=(
            "Closing issue number. Default: derived from the current "
            "branch's `<conv-type>/<N>-<slug>` form."
        ),
    )
    parser.add_argument(
        "--type",
        default=None,
        help=(
            "Conventional Commits <type> to use (overrides the value "
            "derived from the closing issue's type:* label)."
        ),
    )
    parser.add_argument(
        "--scope",
        default=None,
        help="Conventional Commits <scope> (optional).",
    )
    parser.add_argument(
        "--summary",
        default=None,
        help=(
            "Conventional Commits <summary> — short, imperative, lowercase, "
            "no trailing period. Default: derived from the issue title (drop "
            "the [Type] prefix and lowercase)."
        ),
    )
    parser.add_argument(
        "--body-file",
        type=Path,
        default=None,
        help=(
            "Path to a file containing the PR body. Default: use the "
            "capability's templates/PR.md skeleton with `Closes #N` filled in."
        ),
    )
    parser.add_argument(
        "--base",
        default=None,
        help=(
            "Base branch (default: the adopter's `default_branch` in "
            "project/config.yaml, falling back to `main`)."
        ),
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        help="Open the PR as a draft (passed through as gh pr create --draft).",
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

    git_conventions = _read_yaml(
        capability_root / "schemas" / "git-conventions.yaml", yaml_loader
    )
    classification = _read_yaml(
        capability_root / "schemas" / "classification.yaml", yaml_loader
    )
    config = _read_yaml(capability_root / "project" / "config.yaml", yaml_loader)

    branch = _current_branch()
    if branch is None:
        return 2

    # Validate the branch name.
    branch_pattern = _branch_pattern(git_conventions)
    if branch_pattern and not re.match(branch_pattern, branch):
        print(
            f"[refused] current branch {branch!r} does not match "
            f"git-conventions.yaml's branch-name pattern "
            f"({branch_pattern!r}).\n"
            "  → rename the branch via `git branch -m <new-name>` and retry.",
            file=sys.stderr,
        )
        return 1

    # Derive the closing issue number.
    issue_number = args.closes if args.closes is not None else _extract_issue_number(branch)
    if issue_number is None:
        print(
            f"error: could not derive closing issue from branch {branch!r}; "
            "pass --closes <N>.",
            file=sys.stderr,
        )
        return 2

    # Fetch the closing issue to derive title / type label.
    issue = _gh_get_issue(issue_number, config)
    if issue is None:
        return 2

    issue_title = str(issue.get("title", ""))
    issue_labels = [
        lbl.get("name", "") if isinstance(lbl, dict) else str(lbl)
        for lbl in (issue.get("labels") or [])
    ]

    # Determine the PR's Conventional Commits <type>.
    conv_type = args.type or _conv_type_from_issue_labels(issue_labels, classification)
    if conv_type is None:
        print(
            f"error: could not determine Conventional Commits <type> for "
            f"PR. Issue #{issue_number} has no `type:*` label; pass --type.",
            file=sys.stderr,
        )
        return 2

    # Derive the PR title.
    summary = args.summary or _summary_from_issue_title(issue_title)
    if args.scope:
        pr_title = f"{conv_type}({args.scope}): {summary}"
    else:
        pr_title = f"{conv_type}: {summary}"

    # Build the PR body.
    body = _build_pr_body(
        capability_root=capability_root,
        issue_number=issue_number,
        body_file=args.body_file,
    )
    if body is None:
        return 2

    # Determine base branch.
    base = args.base or str(config.get("default_branch") or "main")

    print("open-pr: plan")
    print(f"  branch:  {branch}")
    print(f"  base:    {base}")
    print(f"  closes:  #{issue_number}")
    print(f"  type:    {conv_type}")
    if args.scope:
        print(f"  scope:   {args.scope}")
    print(f"  title:   {pr_title}")
    print(f"  body:    {len(body)} chars")
    if args.draft:
        print("  draft:   yes")

    if args.dry_run:
        print("\n[dry-run] gh would be invoked; nothing written.")
        return 0
    if not args.yes and sys.stdin.isatty():
        reply = input("Open the PR? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    url = _gh_pr_create(
        title=pr_title,
        body=body,
        base=base,
        draft=args.draft,
        config=config,
    )
    if url is None:
        return 3
    print(f"\n[ok] opened: {url}")

    # Fire after_open_pr hooks per DEC-024.
    import re as _re
    pr_number_match = _re.search(r"/pull/(\d+)", url)
    pr_number = int(pr_number_match.group(1)) if pr_number_match else None
    fire_hooks(
        "after_open_pr",
        context={"pr": {"number": pr_number, "title": pr_title}},
        config=config,
        capability_root=capability_root,
    )

    return 0


# ---- conventions helpers -------------------------------------------


def _branch_pattern(git_conventions: dict) -> str | None:
    conv = (git_conventions.get("conventions") or {}).get("branch-name")
    if isinstance(conv, dict):
        p = conv.get("pattern")
        if isinstance(p, str):
            return p
    return None


def _extract_issue_number(branch: str) -> int | None:
    m = re.match(r"^[a-z]+/(\d+)-", branch)
    if not m:
        return None
    return int(m.group(1))


def _conv_type_from_issue_labels(labels: list[str], classification: dict) -> str | None:
    """Map the issue's type:* label to the PR's Conventional Commits <type>."""
    mapping = classification.get("pr_type_mapping") or []
    type_labels = [lbl for lbl in labels if lbl.startswith("type:")]
    if not type_labels:
        return None
    issue_label_value = type_labels[0].removeprefix("type:")
    for entry in mapping:
        if not isinstance(entry, dict):
            continue
        if entry.get("issue_label_value") == issue_label_value:
            return str(entry.get("pr_conv_type", ""))
    return None


def _summary_from_issue_title(title: str) -> str:
    """Drop the [Type] prefix and lowercase the remainder.

    Strips trailing period if any. Result still needs the user's
    judgment (~50 chars, imperative); we make a best-effort default.
    """
    m = re.match(r"^\[[A-Za-z]+\]\s+(.*?)\.?\s*$", title)
    rest = m.group(1) if m else title
    return rest.lower()


def _build_pr_body(
    *,
    capability_root: Path,
    issue_number: int,
    body_file: Path | None,
) -> str | None:
    if body_file is not None:
        try:
            return body_file.read_text(encoding="utf-8")
        except OSError as exc:
            print(
                f"error: failed to read {body_file}: {exc}",
                file=sys.stderr,
            )
            return None
    template_path = capability_root / "templates" / "PR.md"
    if not template_path.is_file():
        return f"Closes #{issue_number}\n"
    raw = template_path.read_text(encoding="utf-8")
    # Drop the HTML comment scaffolding lines so the PR body stays clean.
    stripped = _strip_html_comments(raw)
    # Replace the `Closes #` placeholder with the actual issue number.
    out = re.sub(r"^Closes #\s*$", f"Closes #{issue_number}", stripped, flags=re.MULTILINE)
    if out == stripped:
        # Template lacked the placeholder; prepend a Closes line.
        out = f"Closes #{issue_number}\n\n{stripped}"
    return out


def _strip_html_comments(text: str) -> str:
    """Remove <!-- ... --> blocks (including multi-line ones)."""
    return re.sub(r"<!--.*?-->\s*", "", text, flags=re.DOTALL)


# ---- gh + git wrappers ---------------------------------------------


def _current_branch() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print("error: `git` not on PATH.", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(
            f"error: could not determine current branch.\n"
            f"stderr: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return None
    return proc.stdout.strip() or None


def _gh_get_issue(issue_number: int, config: dict) -> dict | None:
    return gh_get_issue(issue_number, config, fields="title,labels,state")


def _gh_pr_create(
    *, title: str, body: str, base: str, draft: bool
, config: dict) -> str | None:
    with tempfile.NamedTemporaryFile(
        "w", suffix=".md", encoding="utf-8", delete=False
    ) as f:
        f.write(body)
        body_path = f.name
    cmd = [
        "gh",
        "pr",
        "create",
        "--title",
        title,
        "--body-file",
        body_path,
        "--base",
        base,
    ]
    if draft:
        cmd.append("--draft")
    try:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return None
        if proc.returncode != 0:
            print(
                f"error: gh pr create failed (exit {proc.returncode}).\n"
                f"stderr: {proc.stderr.strip()}",
                file=sys.stderr,
            )
            return None
        return proc.stdout.strip() or None
    finally:
        try:
            Path(body_path).unlink(missing_ok=True)
        except OSError:
            pass


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
