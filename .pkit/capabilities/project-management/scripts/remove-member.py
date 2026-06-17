#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — remove-member.

Removes an entry from `members.yaml`. Like add-member, the script
writes to the file on the working branch — the actual landing is via
PR. Per DEC-021, removal PRs cannot be approved solely by the author
when removing another member; self-removal is reviewable by any
other member.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/remove-member.py

Exit codes:
  0  entry removed (or abort acknowledged)
  1  membership refusal (closed mode, invoker not a member)
  2  usage error
  3  not found (no entry matches the given github_login)
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
    members_path,
    resolve_capability_root,
    resolve_invoker_identity,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Remove a member from the project-management team roster "
            "(per DEC-021). Writes to members.yaml on the working "
            "branch; commit + PR review is the actual landing step."
        ),
    )
    parser.add_argument(
        "github_login",
        nargs="?",
        help="GitHub login of the member to remove.",
    )
    parser.add_argument(
        "--me",
        action="store_true",
        help="Self-removal — uses the resolved invoker identity.",
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

    file_path = members_path(capability_root)
    yaml_loader = YAML(typ="safe")
    members = _read_members(file_path, yaml_loader)

    config = load_adopter_config(capability_root)


    invoker = resolve_invoker_identity(config=config)
    result = check_membership(members, invoker)
    if not result.allowed:
        print(result.refusal_message, file=sys.stderr)
        return 1

    target = invoker.github_login if args.me else args.github_login
    if not target:
        print(
            "error: github_login is required (or pass --me to self-remove).",
            file=sys.stderr,
        )
        return 2

    # Find the matching entry.
    matching_index = None
    for i, entry in enumerate(members):
        if isinstance(entry, dict) and entry.get("github_login") == target:
            matching_index = i
            break
    if matching_index is None:
        print(
            f"error: no member with github_login={target!r} in {file_path}.",
            file=sys.stderr,
        )
        return 3

    entry = members[matching_index]
    print(f"about to remove from {file_path}:")
    for k, v in entry.items():
        print(f"  {k}: {v}")
    if not args.yes and sys.stdin.isatty():
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    new_members = [m for i, m in enumerate(members) if i != matching_index]
    _write_members(file_path, new_members, yaml_loader)

    print(f"\n[ok] Removed {target!r} from {file_path.relative_to(capability_root.parents[2])}.")
    if not new_members:
        print(
            "\nThe roster is now empty — the repository transitions back "
            "to open mode once this change lands on main. Anyone with "
            "repo access can re-claim membership via `add-member --me`."
        )
    else:
        print(
            "\nCommit this change and open a PR. Per DEC-021, removal PRs "
            "cannot be approved solely by the author when removing another "
            "member; self-removal is reviewable by any other member."
        )
    return 0


def _read_members(file_path: Path, yaml_loader: YAML) -> list[dict]:
    if not file_path.is_file():
        return []
    try:
        data = yaml_loader.load(file_path.read_text(encoding="utf-8"))
    except (OSError, YAMLError):
        return []
    if not isinstance(data, dict):
        return []
    members = data.get("members") or []
    if not isinstance(members, list):
        return []
    return members


def _write_members(
    file_path: Path, members: list[dict], yaml_loader: YAML
) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "members": members}
    with file_path.open("w", encoding="utf-8") as fh:
        yaml_loader.dump(payload, fh)


if __name__ == "__main__":
    sys.exit(main())
