#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — add-member.

Stamps a new entry into `members.yaml`. The script writes to the file
on the working branch — committing + PR review by an existing member
(when in closed mode) is the actual landing step. In open mode (no
prior members), the first add is self-authored without prior review;
the moment it lands, closed mode applies.

Per DEC-021. Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/add-member.py

Exit codes:
  0  entry added
  1  membership refusal (closed mode, invoker not a member)
  2  usage error (bad args; capability not installed)
  3  duplicate entry (github_login already present)
"""

from __future__ import annotations

import argparse
import datetime as _dt
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
            "Add a new member to the project-management team roster "
            "(per DEC-021). Writes to members.yaml on the working "
            "branch; commit + PR review by an existing member is the "
            "actual landing step."
        ),
    )
    parser.add_argument("--github-login", help="GitHub login of the new member.")
    parser.add_argument("--name", default="", help="Human-readable name.")
    parser.add_argument("--email", default="", help="Email address.")
    parser.add_argument(
        "--role",
        choices=["PM", "Implementer"],
        default=None,
        help="Optional role (informational per DEC-021).",
    )
    parser.add_argument(
        "--me",
        action="store_true",
        help=(
            "Self-add — uses the resolved invoker identity for "
            "github_login + email. Valid in open mode (bootstrap) or "
            "for an existing member re-adding themselves."
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
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt before writing.",
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

    # Resolve invoker identity first — used for both membership gate
    # and for `--me` and `added_by`.
    config = load_adopter_config(capability_root)

    invoker = resolve_invoker_identity(config=config)

    # Membership gate: open mode allows anyone; closed mode requires
    # the invoker to already be a member.
    result = check_membership(members, invoker)
    if not result.allowed:
        print(result.refusal_message, file=sys.stderr)
        return 1

    # Resolve the new entry's identity fields.
    if args.me:
        github_login = invoker.github_login or args.github_login
        email = invoker.email or args.email
    else:
        github_login = args.github_login
        email = args.email
    name = args.name or ""

    if not github_login:
        if sys.stdin.isatty():
            github_login = input("github_login: ").strip()
        if not github_login:
            print(
                "error: --github-login is required (or pass --me to self-add).",
                file=sys.stderr,
            )
            return 2

    # Duplicate check.
    for entry in members:
        if isinstance(entry, dict) and entry.get("github_login") == github_login:
            print(
                f"error: an entry for github_login={github_login!r} "
                f"already exists in {file_path}.",
                file=sys.stderr,
            )
            return 3

    # added_by: bootstrap when no prior members, else the invoker.
    added_by = "bootstrap" if not members else (invoker.github_login or "unknown")
    new_entry: dict = {
        "github_login": github_login,
        "added_at": _dt.date.today().isoformat(),
        "added_by": added_by,
    }
    if name:
        new_entry["name"] = name
    if email:
        new_entry["email"] = email
    if args.role:
        new_entry["role"] = args.role

    # Confirmation.
    print(f"about to add to {file_path}:")
    for k, v in new_entry.items():
        print(f"  {k}: {v}")
    if not args.yes and sys.stdin.isatty():
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    # Write.
    _write_members(file_path, members + [new_entry], yaml_loader)
    print(f"\n[ok] Added {github_login!r} to {file_path.relative_to(capability_root.parents[2])}.")
    if not members:
        print(
            "\nThis is the first member — the repository transitions to "
            "closed mode once this change lands on main. Commit it and "
            "open a PR; from this point forward, member additions need "
            "review by an existing member."
        )
    else:
        print(
            "\nCommit this change and open a PR. Per DEC-021, member "
            "additions require review by ≥1 existing member who is not "
            "the author of the PR."
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
