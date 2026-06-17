#!/usr/bin/env bash
#
# Deploy .pkit/skills/{core,project}/ skills as symlinks under
# .claude/skills/<name>/SKILL.md so Claude Code can load them.
#
# Part of the Claude Code adapter (.pkit/adapters/claude-code/) per
# COR-005's adapter pattern. Sibling scripts for other harnesses (Codex,
# Cursor) would live alongside under their own .pkit/adapters/<harness>/
# directory.
#
# Source layout (per COR-015 + COR-020):
# - Flat (atomic skill): .pkit/skills/<ns>/<name>.md
# - Folder (composite skill): .pkit/skills/<ns>/<name>/<name>.md
#   plus sibling supporting files (sub-procedure walkthroughs per
#   COR-020, scripts, templates, reference docs per COR-015).
#
# Destination layout (Claude Code's expectation):
# - .claude/skills/<name>/SKILL.md   (symlink to the source's canonical file)
# - .claude/skills/<name>/<sibling>  (symlink to each supporting sibling, for
#                                    composite skills per COR-020)
#
# The destination is always the per-name directory + SKILL.md file
# symlink for the canonical; composite skills additionally get one
# symlink per sibling file so the harness can read the sub-procedure
# walkthroughs the dispatcher delegates to.
#
# Behavior:
# - Project namespace wins on collision (per COR-005).
# - Idempotent: correct symlinks report "exists"; mismatched kit-managed
#   symlinks are updated; stale kit-managed symlinks (target no longer
#   present in .pkit/skills/) are removed.
# - Legacy `.claude/skills/<name>` directory-symlinks (the pre-COR-015
#   form pointing to the source folder) are detected and replaced with
#   the new structure.
# - Adopter content (non-symlink files/dirs, or symlinks pointing
#   outside .pkit/skills/) is left untouched and reported "skipped".
# - Output uses tagged status lines: created, updated, exists, removed,
#   skipped, error.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
KIT_SKILLS="$ROOT/.pkit/skills"
KIT_CAPABILITIES="$ROOT/.pkit/capabilities"
CLAUDE_SKILLS="$ROOT/.claude/skills"

mkdir -p "$CLAUDE_SKILLS"

status() { printf "  %-10s %s\n" "$1" "$2"; }

# Resolve a skill name to its expected source path (relative form used
# in the .claude/skills/<name>/SKILL.md symlink). Project wins on
# collision; flat form preferred over folder form within a namespace
# per COR-015's atomic-is-flat bias. Capability skills are checked
# after core/project per COR-017's collision rules (already-installed
# project skills win over capability skills, surfaced at install time).
# Returns 1 if the name is in no source.
expected_for() {
    local name="$1"
    local ns
    for ns in project core; do
        if [ -f "$KIT_SKILLS/$ns/$name.md" ]; then
            echo "../../../.pkit/skills/$ns/$name.md"
            return 0
        elif [ -f "$KIT_SKILLS/$ns/$name/$name.md" ]; then
            echo "../../../.pkit/skills/$ns/$name/$name.md"
            return 0
        fi
    done
    # Walk installed capabilities for a skill of this name.
    if [ -d "$KIT_CAPABILITIES" ]; then
        local cap
        for cap in "$KIT_CAPABILITIES"/*; do
            [ -d "$cap" ] || continue
            local cap_name
            cap_name="$(basename "$cap")"
            if [ -f "$cap/skills/$name.md" ]; then
                echo "../../../.pkit/capabilities/$cap_name/skills/$name.md"
                return 0
            elif [ -f "$cap/skills/$name/$name.md" ]; then
                echo "../../../.pkit/capabilities/$cap_name/skills/$name/$name.md"
                return 0
            fi
        done
    fi
    return 1
}

# Resolve a skill name to its source folder, if folder-form. Returns
# the absolute folder path (e.g., /repo/.pkit/skills/core/schema) when
# the skill ships as a folder; empty otherwise. Uses the same
# precedence as expected_for: project > core > capability layer.
source_folder_for() {
    local name="$1"
    local ns
    for ns in project core; do
        if [ -d "$KIT_SKILLS/$ns/$name" ] && [ -f "$KIT_SKILLS/$ns/$name/$name.md" ]; then
            echo "$KIT_SKILLS/$ns/$name"
            return 0
        fi
    done
    if [ -d "$KIT_CAPABILITIES" ]; then
        local cap
        for cap in "$KIT_CAPABILITIES"/*; do
            [ -d "$cap" ] || continue
            if [ -d "$cap/skills/$name" ] && [ -f "$cap/skills/$name/$name.md" ]; then
                echo "$cap/skills/$name"
                return 0
            fi
        done
    fi
    return 1
}

# Compute the relative path from .claude/skills/<name>/ to a source
# file inside .pkit/{skills|capabilities}/. The destination directory
# is 3 levels deep (.claude/skills/<name>/), so the prefix is `../../../`.
relative_source_path() {
    local absolute="$1"
    local rel="${absolute#$ROOT/}"
    echo "../../../$rel"
}

# Deduped list of skill names across core, project, and capability
# namespaces, in either flat or folder form.
list_kit_names() {
    {
        local ns entry name
        for ns in core project; do
            [ -d "$KIT_SKILLS/$ns" ] || continue
            for entry in "$KIT_SKILLS/$ns"/*; do
                [ -e "$entry" ] || continue
                name="$(basename "$entry")"
                if [ -f "$entry" ] && [[ "$name" == *.md ]]; then
                    echo "${name%.md}"
                elif [ -d "$entry" ]; then
                    echo "$name"
                fi
            done
        done
        # Installed capabilities: walk each capability's skills/ directory.
        if [ -d "$KIT_CAPABILITIES" ]; then
            local cap
            for cap in "$KIT_CAPABILITIES"/*; do
                [ -d "$cap/skills" ] || continue
                for entry in "$cap/skills"/*; do
                    [ -e "$entry" ] || continue
                    name="$(basename "$entry")"
                    if [ -f "$entry" ] && [[ "$name" == *.md ]]; then
                        echo "${name%.md}"
                    elif [ -d "$entry" ]; then
                        echo "$name"
                    fi
                done
            done
        fi
    } | sort -u
}

# Pass 0: clean up legacy `.claude/skills/<name>` directory-symlinks
# (the pre-COR-015 form pointing at a kit source directory). The new
# structure replaces these with `.claude/skills/<name>/SKILL.md` file
# symlinks.
shopt -s nullglob
for entry in "$CLAUDE_SKILLS"/*; do
    [ -L "$entry" ] || continue
    current="$(readlink "$entry")"
    [[ "$current" == ../../.pkit/skills/* ]] || continue
    # Legacy directory-symlink: remove it so the new structure can be created.
    rm "$entry"
    status "migrated" ".claude/skills/$(basename "$entry") (legacy dir-symlink removed)"
done
shopt -u nullglob

# Pass 1: ensure every kit skill has the right .claude/skills/<name>/SKILL.md symlink,
# plus per-sibling symlinks for composite skills (folder-form with supporting siblings).
while IFS= read -r name; do
    [ -n "$name" ] || continue
    expected="$(expected_for "$name")"
    target_dir="$CLAUDE_SKILLS/$name"
    target="$target_dir/SKILL.md"

    mkdir -p "$target_dir"

    if [ -L "$target" ]; then
        current="$(readlink "$target")"
        if [ "$current" = "$expected" ]; then
            status "exists" ".claude/skills/$name/SKILL.md"
        elif [[ "$current" == ../../../.pkit/skills/* ]] || [[ "$current" == ../../../.pkit/capabilities/* ]]; then
            rm "$target"
            ln -s "$expected" "$target"
            status "updated" ".claude/skills/$name/SKILL.md -> $expected"
        else
            status "skipped" ".claude/skills/$name/SKILL.md (user symlink -> $current)"
        fi
    elif [ -e "$target" ]; then
        status "skipped" ".claude/skills/$name/SKILL.md (user content)"
    else
        ln -s "$expected" "$target"
        status "created" ".claude/skills/$name/SKILL.md -> $expected"
    fi

    # For composite skills (folder-form with supporting siblings per
    # COR-020), symlink each sibling into the destination so the
    # harness can read sub-procedure walkthroughs / scripts / templates
    # the dispatcher delegates to.
    source_folder="$(source_folder_for "$name" 2>/dev/null || true)"
    if [ -n "$source_folder" ]; then
        canonical_name="$name.md"
        shopt -s nullglob
        for entry in "$source_folder"/*; do
            entry_name="$(basename "$entry")"
            # Skip the canonical file — already handled above as SKILL.md.
            [ "$entry_name" = "$canonical_name" ] && continue
            sibling_target="$target_dir/$entry_name"
            sibling_expected="$(relative_source_path "$entry")"

            if [ -L "$sibling_target" ]; then
                current="$(readlink "$sibling_target")"
                if [ "$current" = "$sibling_expected" ]; then
                    status "exists" ".claude/skills/$name/$entry_name"
                elif [[ "$current" == ../../../.pkit/skills/* ]] || [[ "$current" == ../../../.pkit/capabilities/* ]]; then
                    rm "$sibling_target"
                    ln -s "$sibling_expected" "$sibling_target"
                    status "updated" ".claude/skills/$name/$entry_name -> $sibling_expected"
                else
                    status "skipped" ".claude/skills/$name/$entry_name (user symlink -> $current)"
                fi
            elif [ -e "$sibling_target" ]; then
                status "skipped" ".claude/skills/$name/$entry_name (user content)"
            else
                ln -s "$sibling_expected" "$sibling_target"
                status "created" ".claude/skills/$name/$entry_name -> $sibling_expected"
            fi
        done
        shopt -u nullglob
    fi
done < <(list_kit_names)

# Pass 2: remove stale kit-managed deploys.
# - For each .claude/skills/<name>/ directory containing a kit-managed
#   SKILL.md symlink: if the source skill no longer exists, remove the
#   whole deployed skill (SKILL.md + any kit-managed sibling symlinks).
# - For composite skills that still exist: remove any kit-managed
#   sibling symlinks whose source file is gone (e.g., a sub-procedure
#   file removed by a skill refactor).
shopt -s nullglob
for skill_dir in "$CLAUDE_SKILLS"/*; do
    [ -d "$skill_dir" ] || continue
    name="$(basename "$skill_dir")"
    inner="$skill_dir/SKILL.md"
    [ -L "$inner" ] || continue
    current="$(readlink "$inner")"
    [[ "$current" == ../../../.pkit/skills/* ]] || [[ "$current" == ../../../.pkit/capabilities/* ]] || continue

    if ! expected_for "$name" >/dev/null 2>&1; then
        # Source skill is gone — remove every kit-managed symlink in
        # this skill's directory, then drop the directory if empty.
        for entry in "$skill_dir"/*; do
            [ -L "$entry" ] || continue
            entry_link="$(readlink "$entry")"
            if [[ "$entry_link" == ../../../.pkit/skills/* ]] || [[ "$entry_link" == ../../../.pkit/capabilities/* ]]; then
                rm "$entry"
            fi
        done
        rmdir "$skill_dir" 2>/dev/null || true
        status "removed" ".claude/skills/$name (source skill gone)"
    else
        # Source skill still exists. If it's composite, check each
        # kit-managed sibling symlink against the source folder; remove
        # any whose source file has been deleted.
        source_folder="$(source_folder_for "$name" 2>/dev/null || true)"
        if [ -n "$source_folder" ]; then
            for entry in "$skill_dir"/*; do
                [ -L "$entry" ] || continue
                entry_name="$(basename "$entry")"
                [ "$entry_name" = "SKILL.md" ] && continue
                entry_link="$(readlink "$entry")"
                if [[ "$entry_link" == ../../../.pkit/skills/* ]] || [[ "$entry_link" == ../../../.pkit/capabilities/* ]]; then
                    if [ ! -e "$source_folder/$entry_name" ]; then
                        rm "$entry"
                        status "removed" ".claude/skills/$name/$entry_name (source sibling gone)"
                    fi
                fi
            done
        fi
    fi
done
shopt -u nullglob

echo "Done."
