#!/usr/bin/env bash
# project-management 0.5.0 — structural: config.workstreams → workstreams.yaml.
#
# DEC-018 introduces a dedicated `project/workstreams.yaml` file as the
# source of truth for the workstream taxonomy. This migration bridges
# adopters who carry the legacy `workstreams:` list inside their
# `project/config.yaml` to the new file shape.
#
# The migration:
#   1. Checks for an existing `project/workstreams.yaml`. If present,
#      assume already-migrated; exit 0 (idempotent).
#   2. Reads `project/config.yaml`. If it has a `workstreams:` field
#      with a non-empty list, writes a starter `workstreams.yaml`
#      using the list-shorthand form. Otherwise exit 0 — nothing to
#      migrate.
#   3. Leaves the legacy `workstreams:` field in config.yaml in place
#      (deliberate: the next minor handles removal once readers
#      consistently prefer the new file).
#
# Idempotent: re-runs on already-migrated state are no-ops.
#
# Run via the upgrade runtime with ROOT=<adopter root>.

set -euo pipefail

: "${ROOT:?ROOT must be set by the upgrade runtime}"

CAP_DIR="$ROOT/.pkit/capabilities/project-management"
PROJECT_DIR="$CAP_DIR/project"
WORKSTREAMS_FILE="$PROJECT_DIR/workstreams.yaml"
CONFIG_FILE="$PROJECT_DIR/config.yaml"

if [ ! -d "$CAP_DIR" ]; then
    echo "  [skip] project-management capability not installed at $CAP_DIR"
    exit 0
fi

if [ -f "$WORKSTREAMS_FILE" ]; then
    echo "  [skip] $WORKSTREAMS_FILE already exists; already migrated"
    exit 0
fi

if [ ! -f "$CONFIG_FILE" ]; then
    echo "  [skip] no adopter config at $CONFIG_FILE; nothing to migrate"
    exit 0
fi

# Extract a flat `workstreams:` list from config.yaml using Python (no
# external YAML tool dependency). The runtime ships Python ≥ 3.10 via
# the wider methodology requirements.
mkdir -p "$PROJECT_DIR"

python3 - <<PYEOF
import sys
import re
from pathlib import Path

config_path = Path("$CONFIG_FILE")
ws_path = Path("$WORKSTREAMS_FILE")

text = config_path.read_text(encoding="utf-8")

# Crude but robust: look for a top-level `workstreams:` block followed
# by `- <slug>` lines. Avoids pulling in ruamel during migration (which
# would mean adopting a runtime dep at migration time).
lines = text.splitlines()
slugs = []
in_block = False
for line in lines:
    stripped = line.rstrip()
    if not in_block:
        if re.match(r"^workstreams\s*:\s*$", stripped):
            in_block = True
        continue
    # End of block: any non-indented non-blank line.
    if stripped and not (line.startswith("  ") or line.startswith("\t")):
        break
    m = re.match(r"^\s*-\s+(\S+)\s*$", line)
    if m:
        slugs.append(m.group(1).strip("'\""))

if not slugs:
    print("  [skip] no workstreams: list found in config.yaml")
    sys.exit(0)

ws_path.write_text(
    "# Workstreams — per project-management:DEC-018.\n"
    "# Auto-migrated from project/config.yaml's `workstreams:` list by\n"
    "# .pkit/capabilities/project-management/migrations/0.5.0/001-config-workstreams-to-file.sh\n"
    "# at upgrade time. Edit freely; switch to the mapping form when you\n"
    "# need per-workstream attributes (name/description/status).\n"
    "schema_version: 1\n"
    "workstreams:\n"
    + "".join(f"  - {s}\n" for s in slugs),
    encoding="utf-8",
)
print(f"  [migrated] wrote {len(slugs)} workstream(s) to {ws_path}")
PYEOF
