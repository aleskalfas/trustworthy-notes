#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — remove-workstream (verb-subject per DEC-020 + DEC-018).

Removes a workstream. Per DEC-018:

  * Zero-issues precondition: refuses if any issue (open or closed)
    still carries the `workstream:<slug>` label.
  * Type-the-slug confirmation prompt to prevent accidents.
  * Removes the entry from workstreams.yaml; deletes the GitHub label.

Membership gate per DEC-021 runs at startup.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/remove-workstream.py <slug>

Or via the dispatcher (per COR-021):
  pkit project-management remove-workstream <slug>

Exit codes:
  0  removed
  1  membership refusal / validation refusal / non-zero issue count
  2  usage error (slug not found)
  3  gh failure
"""

from __future__ import annotations

import argparse
import json
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
from _lib.workstreams import (  # noqa: E402
    parse_workstreams,
    workstreams_path,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove a workstream (refuses if any issue still uses it).",
    )
    parser.add_argument("slug", help="Slug to remove.")
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Bypass the zero-issues precondition. Discouraged — leaves "
            "orphaned `workstream:<slug>` labels on issues."
        ),
    )
    parser.add_argument(
        "--skip-label",
        action="store_true",
        help="Skip the gh label delete step.",
    )
    parser.add_argument("--capability-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the type-the-slug confirmation (use with extreme care).",
    )
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

    path = workstreams_path(capability_root)
    if not path.is_file():
        print(
            f"error: {path} does not exist. Nothing to remove.",
            file=sys.stderr,
        )
        return 2

    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.load(f) or {}
    except (OSError, YAMLError) as exc:
        print(f"error: failed to parse {path}: {exc}", file=sys.stderr)
        return 2

    parsed = parse_workstreams(data)
    existing = {w.slug for w in parsed.entries}
    if args.slug not in existing:
        print(f"error: workstream {args.slug!r} not found.", file=sys.stderr)
        return 2

    config = _read_yaml(capability_root / "project" / "config.yaml", yaml_loader)
    has_board = bool(config.get("has_projects_v2_board", False))

    # Issue-count precondition.
    n = None
    if not has_board and not args.skip_label:
        n = _gh_count_label_uses(f"workstream:{args.slug}", config)
        if n is not None and n > 0 and not args.force:
            print(
                f"[refused] {n} issue(s) still tagged `workstream:{args.slug}`. "
                "Re-tag them (or use `merge-workstream` to consolidate into "
                "another slug) first.\n"
                "  → Pass --force to remove anyway (will leave orphan labels).",
                file=sys.stderr,
            )
            return 1

    print(f"remove-workstream: {args.slug}")
    print(f"  file:           {path}")
    if n is not None:
        print(f"  affected issues: {n}")
    if not has_board and not args.skip_label:
        print(f"  label:          delete `workstream:{args.slug}`")

    if args.dry_run:
        print("\n[dry-run] nothing written; no gh invocation.")
        return 0

    if not args.yes and sys.stdin.isatty():
        typed = input(f"Type the slug {args.slug!r} to confirm: ").strip()
        if typed != args.slug:
            print("[refused] slug did not match; aborted.", file=sys.stderr)
            return 0

    # File mutation.
    ws = data.get("workstreams")
    if isinstance(ws, list):
        data["workstreams"] = [item for item in ws if item != args.slug]
    elif isinstance(ws, dict):
        ws.pop(args.slug, None)
    try:
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f)
    except OSError as exc:
        print(f"error: failed to write {path}: {exc}", file=sys.stderr)
        return 2

    # Label deletion.
    if not has_board and not args.skip_label:
        if not _gh_label_delete(args.slug, config):
            print(
                f"[warn] gh label delete `workstream:{args.slug}` failed.",
                file=sys.stderr,
            )

    print(f"\n[ok] removed workstream {args.slug!r}.")
    return 0


def _gh_count_label_uses(label: str, config: dict) -> int | None:
    try:
        proc = gh_run(
            [
                "gh",
                "issue",
                "list",
                "--label",
                label,
                "--state",
                "all",
                "--limit",
                "1000",
                "--json",
                "number",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    try:
        return len(json.loads(proc.stdout))
    except json.JSONDecodeError:
        return None


def _gh_label_delete(slug: str, config: dict) -> bool:
    try:
        proc = gh_run(
            ["gh", "label", "delete", f"workstream:{slug}", "--yes"],
            config,
            check=False,
        )
    except FileNotFoundError:
        return False
    if proc.returncode == 0:
        return True
    if "not found" in (proc.stderr or ""):
        return True
    return False


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
