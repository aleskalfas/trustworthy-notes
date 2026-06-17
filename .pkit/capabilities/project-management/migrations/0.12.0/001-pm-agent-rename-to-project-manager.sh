#!/usr/bin/env bash
# project-management 0.12.0 — structural: pm-agent.md → project-manager/project-manager.md.
#
# DEC-029 (operationalising COR-026's placement rule for this capability)
# renames the capability's primary agent from `pm-agent` to `project-manager`
# and converts the flat agent file to folder form (per COR-015's first-helper
# rule, the storyboard sibling triggers the conversion).
#
# Pre-migration state in an installed adopter:
#   .pkit/capabilities/project-management/agents/pm-agent.md
#   .claude/agents/pm-agent.md  (symlink deployed by deploy-agents.sh)
#
# Post-sync + post-migration state:
#   .pkit/capabilities/project-management/agents/project-manager/project-manager.md  (synced from kit)
#   .pkit/capabilities/project-management/agents/project-manager/storyboard.md       (synced from kit)
#   .claude/agents/project-manager.md  (re-deployed by deploy-agents.sh on next sync)
#
# The kit-shipped content under .pkit/ is handled by sync (not this migration).
# What this migration handles: cleanup of the stale `pm-agent.md` symlink in
# .claude/agents/ that deploy-agents.sh deposited from the prior version.
# Without the cleanup, the adopter has both the old (dangling) symlink and the
# new (deployed) one — the old one points to a kit-shipped file that no longer
# exists.
#
# Idempotent: re-runs on already-migrated state are no-ops.
#
# Run via the upgrade runtime with ROOT=<adopter root>.

set -euo pipefail

: "${ROOT:?ROOT must be set by the upgrade runtime}"

CAP_DIR="$ROOT/.pkit/capabilities/project-management"
CLAUDE_AGENTS_DIR="$ROOT/.claude/agents"
STALE_SYMLINK="$CLAUDE_AGENTS_DIR/pm-agent.md"

if [ ! -d "$CAP_DIR" ]; then
    echo "  [skip] project-management capability not installed at $CAP_DIR"
    exit 0
fi

if [ ! -d "$CLAUDE_AGENTS_DIR" ]; then
    echo "  [skip] no .claude/agents/ dir; no claude-code adapter state to migrate"
    exit 0
fi

if [ ! -L "$STALE_SYMLINK" ] && [ ! -e "$STALE_SYMLINK" ]; then
    echo "  [skip] $STALE_SYMLINK does not exist; already migrated or never deployed"
    exit 0
fi

# The stale symlink may be dangling (kit content already removed by sync) or
# still valid (sync hasn't run yet). Either way, removing it is safe — the
# next sync will deploy project-manager.md and (re)establish the new symlink.
echo "  [remove] $STALE_SYMLINK (replaced by project-manager.md on next sync)"
rm -f "$STALE_SYMLINK"

echo "  [ok] pm-agent → project-manager rename: deployed adapter state cleaned"
