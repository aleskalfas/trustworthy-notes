#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — enable-default-agent (DEC-030).

Activates the project-manager default-agent overlay for the claude-code
harness. Copies the capability-shipped template at
`adapters/claude-code/overlay.template.json` to the adopter-owned live
overlay at `project/adapter-overlays/claude-code.json`, then runs
`pkit sync` to re-materialise `.claude/settings.json`.

Per DEC-030's `enable` semantics: always overwrites the live overlay
with the current template (no diff prompts, no in-place customisation
in v1). Idempotent — re-running converges on "live matches current
template".

Refuses with exit code 2 if the claude-code adapter is not installed in
the adopter project; the overlay would otherwise be dead weight.

Exit codes:
  0  overlay activated (or already active and template-equivalent)
  1  membership refusal (closed-mode, invoker not a member)
  2  usage error / claude-code adapter not installed / pkit sync failure
"""

from __future__ import annotations

import argparse
import shutil
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
TEMPLATE_RELATIVE = Path("adapters") / HARNESS / "overlay.template.json"
LIVE_RELATIVE = Path("project") / "adapter-overlays" / f"{HARNESS}.json"


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


def _adapter_installed(project_root: Path, name: str) -> bool:
    """Check the backbone manifest for a kind: adapter, name: <name> entry."""
    manifest = project_root / ".pkit" / "manifest.yaml"
    if not manifest.is_file():
        return False
    try:
        data = YAML(typ="safe").load(manifest.read_text(encoding="utf-8")) or {}
    except (OSError, YAMLError):
        return False
    components = data.get("components", [])
    if not isinstance(components, list):
        return False
    for entry in components:
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") == "adapter" and entry.get("name") == name:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Activate the project-manager default-agent overlay (per "
            "DEC-030). Copies the capability-shipped template to the "
            "adopter-owned live overlay and re-runs pkit sync."
        ),
    )
    parser.add_argument(
        "--capability-root", type=Path, default=None,
        help=f"Default: <repo-root>/.pkit/capabilities/{CAPABILITY_NAME}/.",
    )
    parser.add_argument(
        "--skip-sync", action="store_true",
        help="Update the live overlay file but skip the pkit sync step. Mostly for tests.",
    )
    args = parser.parse_args()

    capability_root = resolve_capability_root(args.capability_root)
    if capability_root is None:
        print(f"error: {CAPABILITY_NAME} capability not found.", file=sys.stderr)
        return 2

    # capability_root is .../<repo>/.pkit/capabilities/<CAPABILITY_NAME>/
    project_root = capability_root.parent.parent.parent

    yaml_loader = YAML(typ="safe")
    config = load_adopter_config(capability_root)
    members = _read_members(capability_root, yaml_loader)
    invoker = resolve_invoker_identity(config=config)
    membership = check_membership(members, invoker)
    if not membership.allowed:
        print(membership.refusal_message, file=sys.stderr)
        return 1

    if not _adapter_installed(project_root, HARNESS):
        print(
            f"error: {HARNESS} adapter is not installed in this project.\n"
            f"  Install it before enabling the default-agent overlay; the overlay\n"
            f"  is harness-specific and writing it without the adapter would be a no-op.",
            file=sys.stderr,
        )
        return 2

    template = capability_root / TEMPLATE_RELATIVE
    if not template.is_file():
        print(
            f"error: overlay template missing at {template}.\n"
            f"  This is a capability-source bug — the template should ship with "
            f"the capability. Re-run `pkit sync` to refresh capability content.",
            file=sys.stderr,
        )
        return 2

    live = capability_root / LIVE_RELATIVE
    live.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, live)
    print(f"  activated  {LIVE_RELATIVE}", flush=True)

    if args.skip_sync:
        return 0

    # Re-run merge-settings.sh directly so `.claude/settings.json` picks up the
    # new overlay. We invoke the adapter's merge primitive narrowly rather
    # than the broader `pkit sync` because (a) it's the only operation we
    # need here, and (b) `pkit sync` refuses in the project-kit self-host
    # case (it would clobber the source tree).
    merge_script = project_root / ".pkit" / "adapters" / HARNESS / "merge-settings.sh"
    if not merge_script.is_file():
        print(
            f"warning: {merge_script.relative_to(project_root)} not found; "
            "overlay is in place but `.claude/settings.json` will not reflect it "
            "until merge-settings.sh runs.",
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
            "warning: merge-settings.sh exited non-zero; the overlay file is in place "
            f"but `.claude/settings.json` may not reflect it. Re-run the script "
            f"manually: bash {merge_script.relative_to(project_root)}",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
