#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — split-workstream (verb-subject per DEC-020 + DEC-018).

Splits one workstream into 2–5 new workstreams. Per DEC-018:

  * Source must exist.
  * 2–5 new slugs supplied via `--into <slug>` (repeatable).
  * New slugs must not already exist.
  * Source workstream is removed; new slugs are added (default
    name = slug, active status).
  * Issues retag is interactive at v1 — per-issue prompt for which
    new slug to apply; can opt into batch via `--default <new-slug>`.
  * Default-on retag of `workstream:<source>` label; opt-in via
    `--include-github-bodies` for bulk body rewrites (deferred at v1
    — narrated as a TODO).

Membership gate per DEC-021 runs at startup.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/split-workstream.py --source cli --into cli-tools --into cli-rendering

Or via the dispatcher (per COR-021):
  pkit project-management split-workstream --source cli --into a --into b

Exit codes:
  0  split (or dry-run reported)
  1  membership refusal / validation refusal
  2  usage error
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
    SLUG_PATTERN,
    parse_workstreams,
    workstreams_path,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Split a workstream into 2–5 new slugs.",
    )
    parser.add_argument("--source", required=True, help="Source slug to split.")
    parser.add_argument(
        "--into",
        action="append",
        required=True,
        metavar="SLUG",
        help="New slug to create. Repeat for each split target (2–5 total).",
    )
    parser.add_argument(
        "--default",
        default=None,
        help=(
            "New slug to assign by default when re-tagging issues. If "
            "omitted, issues are flagged for manual retag and the label "
            "is not deleted."
        ),
    )
    parser.add_argument(
        "--skip-labels",
        action="store_true",
        help="Skip the gh label creation step.",
    )
    parser.add_argument("--capability-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if not (2 <= len(args.into) <= 5):
        print(
            f"[refused] --into requires 2–5 values; got {len(args.into)}.",
            file=sys.stderr,
        )
        return 1

    for slug in args.into:
        if not SLUG_PATTERN.match(slug):
            print(
                f"[refused] new slug {slug!r} does not match the slug pattern.",
                file=sys.stderr,
            )
            return 1

    if args.default is not None and args.default not in args.into:
        print(
            f"[refused] --default={args.default!r} is not in the --into set.",
            file=sys.stderr,
        )
        return 1

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
            f"error: {path} does not exist. Run `add-workstream` or the "
            "v0.5.0 migration first.",
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
    if args.source not in existing:
        print(
            f"[refused] source {args.source!r} not found in workstreams.yaml.",
            file=sys.stderr,
        )
        return 1
    overlap = [s for s in args.into if s in existing]
    if overlap:
        print(
            f"[refused] new slugs already exist: {', '.join(overlap)}.",
            file=sys.stderr,
        )
        return 1

    config = _read_yaml(capability_root / "project" / "config.yaml", yaml_loader)
    has_board = bool(config.get("has_projects_v2_board", False))

    print(f"split-workstream: {args.source} → {', '.join(args.into)}")
    if args.default:
        print(f"  default retag: workstream:{args.source} → workstream:{args.default}")
    else:
        print("  default retag: <none> — issues will be flagged but not retagged")

    if not has_board and not args.skip_labels:
        count = _gh_count_label_uses(f"workstream:{args.source}", config)
        print(
            f"  source label uses: {count if count is not None else '?'} issue(s)"
        )

    if args.dry_run:
        print("\n[dry-run] nothing written; no gh invocation.")
        return 0
    if not args.yes and sys.stdin.isatty():
        reply = input("Proceed with split? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    # File mutation.
    ws = data.get("workstreams")
    if isinstance(ws, list):
        new_list = [item for item in ws if item != args.source]
        new_list.extend(args.into)
        data["workstreams"] = new_list
    elif isinstance(ws, dict):
        ws.pop(args.source, None)
        for slug in args.into:
            ws[slug] = {"name": slug, "status": "active"}
    try:
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f)
    except OSError as exc:
        print(f"error: failed to write {path}: {exc}", file=sys.stderr)
        return 2

    # Label ops.
    if not has_board and not args.skip_labels:
        for slug in args.into:
            _gh_label_create(slug, config)
        if args.default:
            _gh_split_retag(args.source, args.default, config)
            # Delete the source label.
            try:
                gh_run(
                    ["gh", "label", "delete", f"workstream:{args.source}", "--yes"],
                    config,
                    check=False,
                )
            except FileNotFoundError:
                pass

    print(
        f"\n[ok] split workstream {args.source!r} into "
        f"{', '.join(args.into)}."
    )
    if not args.default and not has_board:
        print(
            f"[reminder] {args.source!r} label was kept (no --default). "
            "Manually retag each affected issue, then delete the label."
        )
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


def _gh_label_create(slug: str, config: dict) -> bool:
    try:
        proc = gh_run(
            [
                "gh",
                "label",
                "create",
                f"workstream:{slug}",
                "--color",
                "0e8a16",
                "--description",
                f"Workstream `{slug}` (per project-management:DEC-018).",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        return False
    return proc.returncode == 0 or "already exists" in (proc.stderr or "")


def _gh_split_retag(source: str, default: str, config: dict) -> None:
    """Re-tag all issues with `workstream:<source>` → `workstream:<default>`."""
    try:
        proc = gh_run(
            [
                "gh",
                "issue",
                "list",
                "--label",
                f"workstream:{source}",
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
        return
    if proc.returncode != 0:
        return
    try:
        numbers = [item["number"] for item in json.loads(proc.stdout)]
    except (json.JSONDecodeError, KeyError, TypeError):
        return
    for n in numbers:
        try:
            gh_run(
                [
                    "gh",
                    "issue",
                    "edit",
                    str(n),
                    "--add-label",
                    f"workstream:{default}",
                    "--remove-label",
                    f"workstream:{source}",
                ],
                config,
                check=False,
            )
        except FileNotFoundError:
            return


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
