#!/usr/bin/env bash
#
# Merge the Claude Code adapter's settings/{core,project}/settings.json
# into the project's .claude/settings.json. Per COR-002's merge contract.
#
# Behavior (v1, simplified — proper merge runtime per COR-004 supersedes):
# - Allows are the union of core + project + any pre-existing adopter
#   entries in .claude/settings.json (deduped).
# - Denies similarly unioned (baseline-enforce: kit denies are re-added if
#   the adopter has removed them).
# - Per-skill grants: emits `Skill(<name>)` for every kit-shipped skill
#   under `.pkit/skills/{core,project}/` and every capability-shipped
#   skill under `.pkit/capabilities/*/skills/`. The deploy is the trust
#   signal — adopters don't maintain per-skill allowlists by hand.
#   Replaces an earlier wildcard approach that widened the trust
#   boundary to "anything in `.claude/skills/`."
# - Tier-1 only at this stage (auto-add). Tier-2 prompt-once requires
#   classification metadata on the kit baseline; deferred to the proper
#   runtime.
# - Top-level keys outside `permissions` (e.g. `agent`, `model`) are
#   preserved from the source chain with last-write-wins precedence —
#   project overrides core; capability overlays override project;
#   existing target entries override overlays.
# - Capability-contributed overlays per [project-management:DEC-030]:
#   for each manifest-registered capability, if `.pkit/capabilities/<cap>/
#   project/adapter-overlays/claude-code.json` exists, that file is
#   included in the merge chain. The walker is manifest-scoped (orphan
#   capability directories not in the manifest do not contribute) — a
#   deliberate asymmetry vs. collect_skill_grants's directory-presence
#   walk; settings keys are higher-stakes than skill allows.
#   A top-level `permissions` key inside an overlay is silently stripped
#   by step 2 below (the existing del(.permissions) on every source),
#   so capability overlays cannot influence permissions; the reserved-key
#   contract per DEC-030 is enforced mechanically.
# - Idempotent: re-running on a current file reports "exists".
# - Output uses tagged status lines.
#
# Dependencies: jq.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

CORE="$ROOT/.pkit/adapters/claude-code/settings/core/settings.json"
PROJECT_FILE="$ROOT/.pkit/adapters/claude-code/settings/project/settings.json"
TARGET="$ROOT/.claude/settings.json"
KIT_SKILLS="$ROOT/.pkit/skills"
KIT_CAPABILITIES="$ROOT/.pkit/capabilities"

status() { printf "  %-10s %s\n" "$1" "$2"; }

if ! command -v jq >/dev/null 2>&1; then
    echo "Error: jq is required for merge-settings.sh" >&2
    exit 1
fi

mkdir -p "$(dirname "$TARGET")"

# Walk a skills directory and emit Skill(<name>) lines for each artifact.
# Handles both COR-015 layout forms: flat (<name>.md) and folder
# (<name>/<name>.md). Outputs one Skill(<name>) per line.
emit_skill_grants_from_dir() {
    local dir="$1"
    [ -d "$dir" ] || return 0
    local entry name
    for entry in "$dir"/*; do
        [ -e "$entry" ] || continue
        name="$(basename "$entry")"
        if [ -f "$entry" ] && [[ "$name" == *.md ]]; then
            echo "Skill(${name%.md})"
        elif [ -d "$entry" ] && [ -f "$entry/$name.md" ]; then
            echo "Skill($name)"
        fi
    done
}

# Collect Skill grants from every kit-shipped skill source.
# Area skills: .pkit/skills/{core,project}/.
# Capability skills: .pkit/capabilities/<cap>/skills/ for each installed
# capability (per COR-017). Sorted-unique to dedupe across sources.
collect_skill_grants() {
    {
        emit_skill_grants_from_dir "$KIT_SKILLS/core"
        emit_skill_grants_from_dir "$KIT_SKILLS/project"
        if [ -d "$KIT_CAPABILITIES" ]; then
            local cap
            for cap in "$KIT_CAPABILITIES"/*; do
                [ -d "$cap/skills" ] || continue
                emit_skill_grants_from_dir "$cap/skills"
            done
        fi
    } | sort -u
}

# List installed capability names from the backbone manifest at
# .pkit/manifest.yaml. Emits one capability name per line, in the
# order they appear in the manifest. Empty output if the manifest is
# missing or has no capability components.
#
# Per DEC-030, the overlay walker is manifest-scoped (not directory-
# presence-scoped) so orphan capability directories — left behind by
# botched uninstall, stash, or rebase — do not silently contribute
# settings keys. The parser depends on the manifest's documented field
# ordering (kind: before name:), which is core-generated and stable.
list_installed_capabilities() {
    local manifest="$ROOT/.pkit/manifest.yaml"
    [ -f "$manifest" ] || return 0
    awk '
        /^[[:space:]]*-[[:space:]]*kind:[[:space:]]*capability[[:space:]]*$/ {
            in_capability = 1
            next
        }
        /^[[:space:]]*-[[:space:]]*kind:/ {
            in_capability = 0
            next
        }
        in_capability && match($0, /^[[:space:]]+name:[[:space:]]*[^[:space:]]+/) {
            sub(/^[[:space:]]+name:[[:space:]]*/, "")
            print
            in_capability = 0
        }
    ' "$manifest"
}

# Collect capability-contributed overlay file paths for this harness.
# For each installed capability, emit a tmp file path containing the
# overlay's content with `.permissions` stripped — the reserved-key
# rule per DEC-030. Stripping at the source step means the permissions
# union in the jq filter never sees overlay permissions (so an overlay
# cannot influence allow/deny), while non-permissions top-level keys
# flow through the reduction step normally.
#
# Per DEC-030, file presence at <cap>/project/adapter-overlays/
# claude-code.json is the activation signal; absence means inactive.
# Capabilities visit in manifest order; jq's `*` operator handles
# last-write-wins precedence in the merge step. Capabilities are
# expected not to contribute to the same top-level key — collision is
# not a supported configuration — but the order is deterministic.
#
# Tmp files are tracked in OVERLAY_TMP_FILES; the trap at the script's
# end cleans them up.
OVERLAY_TMP_FILES=()
collect_capability_overlay_sources() {
    local cap_name overlay tmp
    while IFS= read -r cap_name; do
        [ -n "$cap_name" ] || continue
        overlay="$KIT_CAPABILITIES/$cap_name/project/adapter-overlays/claude-code.json"
        [ -f "$overlay" ] || continue
        tmp=$(mktemp)
        OVERLAY_TMP_FILES+=("$tmp")
        jq 'del(.permissions)' "$overlay" > "$tmp"
        echo "$tmp"
    done < <(list_installed_capabilities)
}

cleanup_overlay_tmp_files() {
    local f
    for f in "${OVERLAY_TMP_FILES[@]:-}"; do
        [ -n "$f" ] && [ -f "$f" ] && rm -f "$f"
    done
    return 0  # never let trap return non-zero ($? becomes the script's exit code).
}
trap cleanup_overlay_tmp_files EXIT

# Compose the source list. The project-side settings file is optional —
# adopters who haven't added project-specific allows yet won't have it.
# .claude/settings.json may also not exist yet on first run.
#
# Order: core → project → capability overlays → existing target. The
# jq `*` operator merges last-write-wins, so capability overlays
# override core/project defaults, and existing manual entries in
# .claude/settings.json override capability overlays. Per DEC-030.
sources=("$CORE")
[ -f "$PROJECT_FILE" ] && sources+=("$PROJECT_FILE")
while IFS= read -r overlay; do
    [ -n "$overlay" ] && sources+=("$overlay")
done < <(collect_capability_overlay_sources)
[ -f "$TARGET" ] && sources+=("$TARGET")

# JSON array of Skill(<name>) grants computed from the source tree.
skill_grants_json=$(collect_skill_grants | jq -R . | jq -s .)

# --- Authoritative-region tier (COR-002 §80-84 / ADR-002) ------------------
# In managed ownership mode the realizer owns the `permissions` region and
# regenerates it WHOLESALE from its model projection, instead of unioning it
# from the source chain (the additive default below). The owned region is a
# fixed realizer constant — `.permissions` (ADR-002 §26/§30) — not an
# adopter-configurable list.
#
# Gate: `ownership_mode: managed` in the project's permission config. The gate
# is the config flag, NOT file-presence — a stray region file must never
# silently reactivate managed behaviour (cf. the DEC-030 orphan-contribution
# footgun). Fail-safe to `additive` on a missing/unparseable config.
#
# The region content is supplied per-run by the realizer's `apply`, via a JSON
# file at $PKIT_MANAGED_REGION_FILE holding the permissions object
# `{"allow":[...],"deny":[...]}`. Plain `sync` without it leaves the additive
# default untouched. No strip-logic and no in-file markers are needed: because
# `permissions` is already stripped from every source and recomputed each run
# (the jq below), managed mode only swaps the *source* of that recomputed
# region (the projection) for the additive union — a removed grant simply isn't
# in the next projection, so it vanishes. Drift heals to whatever the model
# currently projects, down to empty.
PERM_CONFIG="$ROOT/.pkit/permissions/project/config.yaml"
ownership_mode="additive"
if [ -f "$PERM_CONFIG" ]; then
    # Exact-value match (not a substring) so a value like `unmanaged-x` can't
    # trip managed mode; mirrors decide.py's exact-string read of the key.
    mode_value="$(sed -nE 's/^[[:space:]]*ownership_mode:[[:space:]]*"?([a-z][a-z-]*)"?[[:space:]]*$/\1/p' "$PERM_CONFIG" | head -1 || true)"
    if [ "$mode_value" = "managed" ]; then
        ownership_mode="managed"
    fi
fi
managed_region="null"
if [ "$ownership_mode" = "managed" ] \
   && [ -n "${PKIT_MANAGED_REGION_FILE:-}" ] && [ -f "$PKIT_MANAGED_REGION_FILE" ]; then
    managed_region="$(cat "$PKIT_MANAGED_REGION_FILE")"
fi

# Two-layer merge:
#   1. Compute `permissions` with the existing union-deduped semantics
#      for `allow` / `deny` (byte-for-byte unchanged vs. earlier
#      versions of this script for any input that only used those
#      sub-keys).
#   2. Reduce all sources (with `permissions` stripped) with jq's `*`
#      operator — recursive merge, last-write-wins for scalars and
#      arrays, deep-merge for nested objects. Source order is core →
#      project → target, so project overrides core and an existing
#      target entry wins over both (baseline behaviour for whatever
#      the adopter has already set).
#   3. Layer `permissions` on top of the reduction so it is always
#      shaped by step 1 (additive), never by step 2. When a managed
#      region is supplied, it REPLACES the computed additive permissions
#      wholesale (the authoritative-region tier above). When absent
#      ($managed_region == null) the layered value is byte-for-byte the
#      additive `$perms`, so the default path is unchanged.
merged=$(jq -s --argjson grants "$skill_grants_json" --argjson managed_region "$managed_region" '
    . as $sources
    | {
          permissions: {
              allow: ([$sources[].permissions.allow // []] | add | . + $grants | unique),
              deny:  ([$sources[].permissions.deny  // []] | add | unique)
          }
      } as $perms
    | (reduce $sources[] as $s ({}; . * ($s | del(.permissions))))
      * { permissions: (if $managed_region == null then $perms.permissions else $managed_region end) }
' "${sources[@]}")

# Compare canonicalised JSON to detect a real change vs cosmetic diff.
if [ -f "$TARGET" ]; then
    current_canonical=$(jq -S . "$TARGET")
    proposed_canonical=$(echo "$merged" | jq -S .)
    if [ "$current_canonical" = "$proposed_canonical" ]; then
        status "exists" ".claude/settings.json"
        exit 0
    fi
    echo "$merged" > "$TARGET"
    status "merged" ".claude/settings.json"
else
    echo "$merged" > "$TARGET"
    status "created" ".claude/settings.json"
fi
