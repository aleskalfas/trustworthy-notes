#!/usr/bin/env bash
# evidence 0.2.0 — structural: consolidate-skills.
#
# Migrates the two flat evidence-* skills (evidence-add.md +
# evidence-validate.md) into the composite skill folder layout
# introduced by COR-020:
#
#   Before (0.1.0):
#     .pkit/capabilities/evidence/skills/
#     ├── evidence-add.md
#     └── evidence-validate.md
#
#   After (0.2.0):
#     .pkit/capabilities/evidence/skills/
#     └── evidence/
#         ├── evidence.md   ← dispatcher
#         ├── add.md        ← was evidence-add.md
#         └── validate.md   ← was evidence-validate.md
#
# This script only removes the OLD flat files. The new composite layout
# arrives via the upgrade runtime's source-copy step after the migration
# runs. Removing the stale flat files first prevents them from lingering
# alongside the new layout.
#
# Idempotent: if the old flat files don't exist, the migration is a
# no-op (already-migrated state).

set -euo pipefail

: "${ROOT:?ROOT must be set by the upgrade runtime}"

SKILLS_DIR="$ROOT/.pkit/capabilities/evidence/skills"

OLD_ADD="$SKILLS_DIR/evidence-add.md"
OLD_VALIDATE="$SKILLS_DIR/evidence-validate.md"

removed=0

if [ -f "$OLD_ADD" ]; then
    rm "$OLD_ADD"
    echo "  removed  .pkit/capabilities/evidence/skills/evidence-add.md (consolidated into evidence/)"
    removed=$((removed + 1))
fi

if [ -f "$OLD_VALIDATE" ]; then
    rm "$OLD_VALIDATE"
    echo "  removed  .pkit/capabilities/evidence/skills/evidence-validate.md (consolidated into evidence/)"
    removed=$((removed + 1))
fi

if [ "$removed" -eq 0 ]; then
    echo "  exists   evidence skills already consolidated into composite layout"
fi
