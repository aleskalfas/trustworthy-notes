#!/usr/bin/env bash
#
# Ensure the adopter's root CLAUDE.md includes @.pkit/rules/core.md (and
# @.pkit/rules/project.md) so the kit-shipped hard rules and tool-hygiene
# conventions are loaded into the agent at session start.
#
# Per the COR-002 merge contract (insert-if-absent / create-if-none):
#   - If CLAUDE.md doesn't exist: creates a minimal one with the @-includes.
#   - If CLAUDE.md exists without the @-include: inserts the @-include block
#     after the first H1, or prepends a minimal header + @-includes if there
#     is no H1. The existing content is NEVER clobbered.
#   - If CLAUDE.md already contains @.pkit/rules/core.md: no-op (idempotent).
#
# Per core.md rule 13 (the @-include authoring convention): the included
# sections start at H2, so the @-include line must come after the host's
# H1, not at line 1, so the sections nest naturally under the host.
#
# Idempotent: re-running on a current file reports "exists".
# Output uses tagged status lines: created, insert, prepend, exists.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

CLAUDE_MD="$ROOT/CLAUDE.md"
CORE_INCLUDE="@.pkit/rules/core.md"
PROJECT_INCLUDE="@.pkit/rules/project.md"

status() { printf "  %-10s %s\n" "$1" "$2"; }

# ── Already contains the core.md include? ─────────────────────────────────
if [ -f "$CLAUDE_MD" ] && grep -qF "$CORE_INCLUDE" "$CLAUDE_MD"; then
    status "exists" "CLAUDE.md (already includes $CORE_INCLUDE)"
    exit 0
fi

# ── CLAUDE.md doesn't exist — create a minimal one ────────────────────────
if [ ! -f "$CLAUDE_MD" ]; then
    cat > "$CLAUDE_MD" <<'HEREDOC'
# Claude Code instructions

This file is loaded by Claude Code at session start. The kit-shipped rules
and tool-hygiene conventions are included below; add project-specific
instructions after the includes.

@.pkit/rules/core.md
@.pkit/rules/project.md
HEREDOC
    status "created" "CLAUDE.md (minimal host with @-includes)"
    exit 0
fi

# ── CLAUDE.md exists but lacks the include — insert after the first H1 ────
# Strategy:
#   1. Find the line number of the first `# ` heading (Markdown H1).
#   2. If found, insert the @-include block after that line (with a blank
#      line separator so the includes don't run into the H1 inline).
#   3. If no H1, prepend a minimal header + @-includes above the existing
#      content (never clobbers; prepend is the safe posture when we can't
#      determine where the includes belong).
#
# Both @-includes are written together: core.md (always) then project.md
# (always — the file may not exist yet, but Claude Code silently ignores
# missing @-includes, so wiring it is harmless and future-proof).

H1_LINE=$(grep -n "^# " "$CLAUDE_MD" | head -1 | cut -d: -f1 || true)

TMP=$(mktemp)
INCLUDE_TMP=$(mktemp)

# Write the include block to a temp file to avoid newline-in-variable issues
# with awk's -v flag. The block has a leading blank line so the @-include
# lines are visually separated from the H1.
printf '\n%s\n%s\n' "$CORE_INCLUDE" "$PROJECT_INCLUDE" > "$INCLUDE_TMP"

if [ -n "$H1_LINE" ]; then
    # Insert the include block immediately after the H1 line.
    awk -v h1="$H1_LINE" -v inc="$INCLUDE_TMP" '
        NR == h1 { print; while ((getline line < inc) > 0) print line; next }
        { print }
    ' "$CLAUDE_MD" > "$TMP"
    rm -f "$INCLUDE_TMP"
    mv "$TMP" "$CLAUDE_MD"
    status "insert" "CLAUDE.md (@-includes added after line $H1_LINE)"
else
    rm -f "$INCLUDE_TMP"
    {
        printf '# Claude Code instructions\n'
        printf '\n'
        printf '%s\n' "$CORE_INCLUDE"
        printf '%s\n' "$PROJECT_INCLUDE"
        printf '\n'
        cat "$CLAUDE_MD"
    } > "$TMP"
    mv "$TMP" "$CLAUDE_MD"
    status "prepend" "CLAUDE.md (@-includes prepended; no H1 found)"
fi
