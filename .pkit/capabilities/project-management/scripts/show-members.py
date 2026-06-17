#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — show-members.

Read-only diagnostic: prints the current `members.yaml` roster, the
membership mode (open / closed), and the invoker's resolved identity.
No mutations. Useful for inspecting authority state before invoking
mutating pm operations.

Per DEC-021. Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/show-members.py

Exit codes:
  0  ran cleanly (regardless of mode)
  2  capability not installed at the expected path
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

# Path manipulation for shared library import (PEP 723 keeps each
# script's deps inline; shared helpers live at scripts/_lib/).
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
from _lib.gh import gh_run, load_adopter_config  # noqa: E402
from _lib.membership import (  # noqa: E402
    CAPABILITY_NAME,
    MEMBERS_RELATIVE,
    check_membership,
    members_path,
    resolve_capability_root,
    resolve_invoker_identity,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Show the current project-management team membership "
            "(per DEC-021). Read-only."
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
    args = parser.parse_args()

    capability_root = resolve_capability_root(args.capability_root)
    if capability_root is None:
        print(
            f"error: {CAPABILITY_NAME} capability not found. "
            "Run this script from within an adopter project that has the "
            f"capability installed at .pkit/capabilities/{CAPABILITY_NAME}/.",
            file=sys.stderr,
        )
        return 2

    file_path = members_path(capability_root)
    members = _read_members(file_path)
    config = load_adopter_config(capability_root)

    invoker = resolve_invoker_identity(config=config)
    result = check_membership(members, invoker)

    print(f"members file: {file_path}")
    print(f"mode:         {result.mode}")
    print(f"invoker:      {invoker.label()}")
    if invoker.github_login:
        print(f"  github_login: {invoker.github_login}")
    if invoker.email:
        print(f"  email:        {invoker.email}")
    print(f"allowed:      {'yes' if result.allowed else 'no'}")

    print()
    if not members:
        print(f"({MEMBERS_RELATIVE} is absent or has an empty members list — open mode applies.)")
        print("Anyone with repo access may invoke mutating pm operations.")
    else:
        print(f"{len(members)} member(s) registered:")
        for entry in members:
            github_login = entry.get("github_login", "<missing>") if isinstance(entry, dict) else "<malformed>"
            name = entry.get("name", "") if isinstance(entry, dict) else ""
            role = entry.get("role", "") if isinstance(entry, dict) else ""
            email = entry.get("email", "") if isinstance(entry, dict) else ""
            line = f"  - {github_login}"
            if name:
                line += f" ({name})"
            if role:
                line += f" [{role}]"
            if email:
                line += f"  <{email}>"
            print(line)

    return 0


def _read_members(file_path: Path) -> list[dict]:
    if not file_path.is_file():
        return []
    try:
        data = YAML(typ="safe").load(file_path.read_text(encoding="utf-8"))
    except (OSError, YAMLError):
        return []
    if not isinstance(data, dict):
        return []
    members = data.get("members") or []
    if not isinstance(members, list):
        return []
    return members


if __name__ == "__main__":
    sys.exit(main())
