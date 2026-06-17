#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — show-workstream (verb-subject per DEC-020 + DEC-018).

Read-only view of one workstream entry. Resolves from
project/workstreams.yaml (canonical) or falls back to
project/config.yaml's `workstreams:` list during the v0.5.0
transition.

Membership gate per DEC-021 runs at startup.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/show-workstream.py cli

Or via the dispatcher (per COR-021):
  pkit project-management show-workstream cli

Exit codes:
  0  shown
  1  membership refusal
  2  usage error (slug not found)
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
    parse_workstreams,
    workstreams_path,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Show one workstream entry.",
    )
    parser.add_argument(
        "slug",
        help="Workstream slug to look up.",
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

    match = next((w for w in parsed.entries if w.slug == args.slug), None)
    if match is None:
        print(
            f"error: workstream {args.slug!r} not found. "
            f"Known slugs: {', '.join(sorted(w.slug for w in parsed.entries)) or '<none>'}",
            file=sys.stderr,
        )
        return 2

    if args.json:
        out = {
            "slug": match.slug,
            "name": match.name,
            "description": match.description,
            "status": match.status,
            "deprecated_reason": match.deprecated_reason,
        }
        print(json.dumps(out, indent=2))
    else:
        print(f"workstream: {match.slug}")
        print(f"  name:        {match.name}")
        if match.description:
            print(f"  description: {match.description}")
        print(f"  status:      {match.status}")
        if match.deprecated_reason:
            print(f"  reason:      {match.deprecated_reason}")
        print(f"  source file: {workstreams_path(capability_root)}")
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
