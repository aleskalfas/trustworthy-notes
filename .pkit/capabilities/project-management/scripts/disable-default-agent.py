#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — disable-default-agent (DEC-030).

Deactivates the project-manager default-agent overlay for the
claude-code harness. Three steps per DEC-030:

  1. Read the live overlay file's top-level keys to know what to clean.
  2. Strip those keys from `.claude/settings.json` (skipping `permissions`
     — overlays never legitimately contributed permissions per the
     reserved-key rule).
  3. Remove the live overlay file at
     `project/adapter-overlays/claude-code.json`.

Then runs `pkit sync` to re-execute the merge against the updated state.

The explicit strip is necessary because the merge primitive treats
existing target entries as last-write-wins survivors (per #190's
broadening) — without it, the agent key would persist in
`.claude/settings.json` after the overlay is removed.

Exit codes:
  0  overlay deactivated (or already inactive)
  1  membership refusal (closed-mode, invoker not a member)
  2  usage error / pkit sync failure
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
from _lib.gh import load_adopter_config  # noqa: E402
from _lib.membership import (  # noqa: E402
    CAPABILITY_NAME,
    check_membership,
    resolve_capability_root,
    resolve_invoker_identity,
)


HARNESS = "claude-code"
LIVE_RELATIVE = Path("project") / "adapter-overlays" / f"{HARNESS}.json"
TARGET_RELATIVE = Path(".claude") / "settings.json"


def _read_members(capability_root: Path, yaml_loader: YAML) -> list:
    """Load the members list from `project/members.yaml`. Empty if missing."""
    path = capability_root / "project" / "members.yaml"
    if not path.is_file():
        return []
    try:
        data = yaml_loader.load(path.read_text(encoding="utf-8")) or {}
    except (OSError, YAMLError):
        return []
    members = data.get("members") if isinstance(data, dict) else None
    return members if isinstance(members, list) else []


def _strip_overlay_keys_from_target(target_path: Path, overlay_keys: set[str]) -> bool:
    """Remove `overlay_keys` (minus `permissions`) from `target_path` JSON.

    Returns True if the target was rewritten, False if it was untouched
    (file missing, no overlap with overlay_keys, etc.).
    """
    if not target_path.is_file():
        return False
    try:
        data = json.loads(target_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False

    # The reserved-key rule means overlays should never have set permissions,
    # but the strip is defensive — never let disable touch permissions.
    keys_to_strip = (overlay_keys - {"permissions"}) & set(data.keys())
    if not keys_to_strip:
        return False
    for key in keys_to_strip:
        del data[key]
    target_path.write_text(
        json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Deactivate the project-manager default-agent overlay (per "
            "DEC-030). Strips the overlay's keys from .claude/settings.json, "
            "removes the live overlay file, and re-runs pkit sync."
        ),
    )
    parser.add_argument(
        "--capability-root", type=Path, default=None,
        help=f"Default: <repo-root>/.pkit/capabilities/{CAPABILITY_NAME}/.",
    )
    parser.add_argument(
        "--skip-sync", action="store_true",
        help="Strip + remove the live overlay but skip pkit sync. Mostly for tests.",
    )
    args = parser.parse_args()

    capability_root = resolve_capability_root(args.capability_root)
    if capability_root is None:
        print(f"error: {CAPABILITY_NAME} capability not found.", file=sys.stderr)
        return 2

    project_root = capability_root.parent.parent.parent

    yaml_loader = YAML(typ="safe")
    config = load_adopter_config(capability_root)
    members = _read_members(capability_root, yaml_loader)
    invoker = resolve_invoker_identity(config=config)
    membership = check_membership(members, invoker)
    if not membership.allowed:
        print(membership.refusal_message, file=sys.stderr)
        return 1

    live = capability_root / LIVE_RELATIVE
    if not live.is_file():
        print(f"  inactive   {LIVE_RELATIVE} (already absent; nothing to do)")
        # Re-run merge to confirm clean state. Same narrow-primitive choice
        # as enable: skip the broader `pkit sync`, which would refuse in
        # the project-kit self-host case.
        if not args.skip_sync:
            merge_script = project_root / ".pkit" / "adapters" / HARNESS / "merge-settings.sh"
            if merge_script.is_file():
                subprocess.run(["bash", str(merge_script)], cwd=project_root, check=False)
        return 0

    # Step 1: read the overlay's top-level keys.
    try:
        overlay_data = json.loads(live.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: live overlay at {live} is unreadable: {exc}", file=sys.stderr)
        return 2
    if not isinstance(overlay_data, dict):
        print(
            f"error: live overlay at {live} is not a JSON object; "
            "removing the file but cannot enumerate keys to strip.",
            file=sys.stderr,
        )
        live.unlink()
        return 2

    overlay_keys = set(overlay_data.keys())

    # Step 2: strip those keys from .claude/settings.json.
    target_path = project_root / TARGET_RELATIVE
    target_rewritten = _strip_overlay_keys_from_target(target_path, overlay_keys)
    if target_rewritten:
        print(
            f"  stripped   {TARGET_RELATIVE} "
            f"(keys: {', '.join(sorted(overlay_keys - {'permissions'}))})",
            flush=True,
        )

    # Step 3: remove the live overlay file.
    live.unlink()
    print(f"  deactivated {LIVE_RELATIVE}", flush=True)

    if args.skip_sync:
        return 0

    # Re-run merge-settings.sh narrowly (see enable-default-agent for the
    # rationale on choosing the adapter primitive over `pkit sync`).
    merge_script = project_root / ".pkit" / "adapters" / HARNESS / "merge-settings.sh"
    if not merge_script.is_file():
        print(
            f"warning: {merge_script.relative_to(project_root)} not found; "
            "overlay removed and target stripped, but the next merge needs "
            "the adapter installed to converge.",
            file=sys.stderr,
        )
        return 0
    result = subprocess.run(
        ["bash", str(merge_script)],
        cwd=project_root,
        check=False,
    )
    if result.returncode != 0:
        print(
            "warning: merge-settings.sh exited non-zero; the overlay is removed "
            f"but `.claude/settings.json` may not be in a clean state. "
            f"Re-run the script manually: bash {merge_script.relative_to(project_root)}",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
