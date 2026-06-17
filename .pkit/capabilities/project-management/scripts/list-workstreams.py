#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — list-workstreams (verb-subject per DEC-020 + DEC-018).

Read-only enumeration of every workstream entry. Resolves from
project/workstreams.yaml (canonical) or config.yaml legacy fallback.

Membership gate per DEC-021 runs at startup.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/list-workstreams.py

Or via the dispatcher (per COR-021):
  pkit project-management list-workstreams

Exit codes:
  0  listed
  1  membership refusal
  2  usage error
"""

from __future__ import annotations

import argparse
import json
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
    duplicate_names,
    parse_workstreams,
    workstreams_path,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List every workstream in the project's workstreams.yaml.",
    )
    parser.add_argument(
        "--status",
        choices=["active", "deprecated", "all"],
        default="active",
        help="Filter by status (default: active).",
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
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
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

    raw = _read_workstreams_file_or_legacy(capability_root, yaml_loader)
    parsed = parse_workstreams(raw if raw else None)

    if args.status == "all":
        entries = parsed.entries
    else:
        entries = tuple(w for w in parsed.entries if w.status == args.status)

    dupes = duplicate_names(parsed)

    if args.json:
        out = {
            "form": parsed.form,
            "errors": list(parsed.errors),
            "duplicate_names": dupes,
            "entries": [
                {
                    "slug": w.slug,
                    "name": w.name,
                    "description": w.description,
                    "status": w.status,
                    "deprecated_reason": w.deprecated_reason,
                }
                for w in entries
            ],
        }
        print(json.dumps(out, indent=2))
        return 0

    src = workstreams_path(capability_root)
    print(f"workstreams (source: {src}, form: {parsed.form})")
    if parsed.errors:
        print(f"  parse errors: {len(parsed.errors)}")
        for e in parsed.errors:
            print(f"    ! {e}")
    if not entries:
        print(f"  (no entries{f' with status={args.status}' if args.status != 'all' else ''})")
        return 0
    print()
    for w in entries:
        flag = " [deprecated]" if w.status == "deprecated" else ""
        descr = f" — {w.description}" if w.description else ""
        print(f"  {w.slug}: {w.name}{flag}{descr}")
        if w.deprecated_reason:
            print(f"      reason: {w.deprecated_reason}")
    if dupes:
        print()
        print(
            "[warn] duplicate active workstream names: "
            + ", ".join(repr(n) for n in dupes)
        )
    return 0


def _read_workstreams_file_or_legacy(
    capability_root: Path, yaml_loader: YAML
) -> dict | list | None:
    path = workstreams_path(capability_root)
    if path.is_file():
        return _read_yaml(path, yaml_loader)
    config = _read_yaml(capability_root / "project" / "config.yaml", yaml_loader)
    return config.get("workstreams")


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
