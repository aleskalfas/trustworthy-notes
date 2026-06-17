#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — edit-workstream (verb-subject per DEC-020 + DEC-018).

Edits an existing workstream's name / description / status /
deprecated_reason. Per DEC-018, status flips require explicit
confirmation; non-status edits proceed without further prompting.

Membership gate per DEC-021 runs at startup.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/edit-workstream.py <slug> [--name "..."] [--status active|deprecated]

Or via the dispatcher (per COR-021):
  pkit project-management edit-workstream <slug> --description "..."

Exit codes:
  0  edited (or dry-run reported)
  1  membership refusal / validation refusal
  2  usage error (slug not found)
"""

from __future__ import annotations

import argparse
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
        description="Edit a workstream's attributes.",
    )
    parser.add_argument("slug", help="Slug to edit.")
    parser.add_argument("--name", default=None)
    parser.add_argument("--description", default=None)
    parser.add_argument("--status", choices=["active", "deprecated"], default=None)
    parser.add_argument("--deprecated-reason", default=None)
    parser.add_argument("--capability-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if args.name is None and args.description is None and args.status is None and args.deprecated_reason is None:
        print(
            "error: nothing to edit. Pass --name / --description / --status / --deprecated-reason.",
            file=sys.stderr,
        )
        return 2

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
            f"error: {path} does not exist. Run `add-workstream` first, or "
            "run the v0.5.0 migration to bridge from config.yaml.",
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
    if not any(w.slug == args.slug for w in parsed.entries):
        print(f"error: workstream {args.slug!r} not found.", file=sys.stderr)
        return 2

    ws = data.get("workstreams")

    # Upgrade list-form to mapping-form if we're changing an entry's attributes.
    if isinstance(ws, list):
        upgraded: dict = {}
        for item in ws:
            if isinstance(item, str):
                upgraded[item] = {"name": item, "status": "active"}
        data["workstreams"] = upgraded
        ws = upgraded

    if not isinstance(ws, dict):
        print(f"error: {path} `workstreams:` is not a mapping or list.", file=sys.stderr)
        return 2

    entry = ws.get(args.slug)
    if entry is None or not isinstance(entry, dict):
        entry = {"name": args.slug, "status": "active"}
        ws[args.slug] = entry

    current = dict(entry)
    if args.name is not None:
        entry["name"] = args.name
    if args.description is not None:
        entry["description"] = args.description
    if args.status is not None:
        if args.status == "deprecated" and not (args.deprecated_reason or entry.get("deprecated_reason")):
            print(
                "[refused] --status=deprecated requires --deprecated-reason "
                "(or an existing deprecated_reason).",
                file=sys.stderr,
            )
            return 1
        entry["status"] = args.status
    if args.deprecated_reason is not None:
        entry["deprecated_reason"] = args.deprecated_reason

    print(f"edit-workstream: {args.slug}")
    for k in ("name", "description", "status", "deprecated_reason"):
        if k in current or k in entry:
            old = current.get(k, "<unset>")
            new = entry.get(k, "<unset>")
            marker = "*" if old != new else " "
            print(f"  {marker} {k}: {old!r} → {new!r}")

    if args.dry_run:
        print("\n[dry-run] nothing written.")
        return 0
    if args.status is not None and current.get("status") != entry["status"]:
        if not args.yes and sys.stdin.isatty():
            reply = input(
                f"Flip status {current.get('status', '<unset>')!r} → "
                f"{entry['status']!r}? [y/N] "
            ).strip().lower()
            if reply not in ("y", "yes"):
                print("aborted.", file=sys.stderr)
                return 0

    try:
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f)
    except OSError as exc:
        print(f"error: failed to write {path}: {exc}", file=sys.stderr)
        return 2

    print(f"\n[ok] edited workstream {args.slug!r}.")
    return 0


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
