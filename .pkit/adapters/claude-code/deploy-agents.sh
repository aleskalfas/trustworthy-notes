#!/usr/bin/env bash
#
# Deploy .pkit/agents/{core,project}/<name>/<name>.md as resolved copies
# under .claude/agents/<name>.md so Claude Code can load them.
#
# Part of the Claude Code adapter (.pkit/adapters/claude-code/) per
# COR-005's adapter pattern. Sibling to deploy-skills.sh; differs in
# two ways:
#
#   1. Copies (not symlinks) — agent templates contain `<category-name>`
#      placeholders resolved at deploy time against
#      `.pkit/agents/project/overlay.yaml`. The resolved file is what
#      Claude Code loads; the source template is what authors edit.
#
#   2. Flat destination layout — Claude Code expects one `.md` file per
#      agent at `.claude/agents/<name>.md`, not a per-agent directory.
#
# Behavior:
# - Project namespace wins on collision (per COR-005).
# - Overlay placeholders (`<category-name>`) are resolved from
#   `overlay.yaml`'s top-level categories, with per-agent values in
#   `overrides.<name>` taking precedence per COR-013.
# - Idempotent: if the resolved content matches the destination,
#   reports "exists"; otherwise overwrites.
# - Unresolved placeholder (category referenced by an agent but not
#   defined in the overlay) → "error" status + non-zero exit code.
# - Tagged status lines: created, updated, exists, error.
#
# Stale-removal pass (now that the marker convention exists): after the
# deploy pass, a `.claude/agents/<name>.md` that carries our marker but whose
# source no longer ships is stale kit output — removed. Adopter-authored
# agents (no marker) and currently-shipped agents are never touched. To KEEP a
# no-longer-shipped agent, strip its marker line: it then reads as adopter
# content and is preserved (the same guard that protects authored agents).
#
# Deferred:
# - Disable mechanism (adopter wants a kit agent not deployed) — same
#   deferral rationale as deploy-skills.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
KIT_AGENTS="$ROOT/.pkit/agents"
KIT_CAPABILITIES="$ROOT/.pkit/capabilities"
CLAUDE_AGENTS="$ROOT/.claude/agents"
OVERLAY="$KIT_AGENTS/project/overlay.yaml"

# Marker inserted as a YAML comment inside each resolved agent's
# frontmatter. The kit uses it to tell its own deployed copies from
# adopter-authored agents that happen to share a name (see deploy_one's
# user-content guard). YAML comments are ignored by every frontmatter
# parser, including Claude Code's, so the marker is invisible at load
# time but trivial to grep for here.
MARKER="# managed-by: project-kit (deploy-agents.sh) — do not edit; regenerated on sync"

mkdir -p "$CLAUDE_AGENTS"

status() { printf "  %-10s %s\n" "$1" "$2"; }

# Resolve which agent source file to use. Project wins on collision;
# flat form preferred over folder form within a namespace per COR-015's
# atomic-is-flat bias.
source_for() {
    local name="$1"
    local ns
    for ns in project core; do
        if [ -f "$KIT_AGENTS/$ns/$name.md" ]; then
            echo "$KIT_AGENTS/$ns/$name.md"
            return 0
        elif [ -f "$KIT_AGENTS/$ns/$name/$name.md" ]; then
            echo "$KIT_AGENTS/$ns/$name/$name.md"
            return 0
        fi
    done
    # Walk installed capabilities for an agent of this name.
    if [ -d "$KIT_CAPABILITIES" ]; then
        local cap
        for cap in "$KIT_CAPABILITIES"/*; do
            [ -d "$cap" ] || continue
            if [ -f "$cap/agents/$name.md" ]; then
                echo "$cap/agents/$name.md"
                return 0
            elif [ -f "$cap/agents/$name/$name.md" ]; then
                echo "$cap/agents/$name/$name.md"
                return 0
            fi
        done
    fi
    return 1
}

# Deduped list of agent names across core, project, and capability
# namespaces, in either flat or folder form (per COR-015 / COR-017).
list_kit_names() {
    {
        local ns entry name
        for ns in core project; do
            [ -d "$KIT_AGENTS/$ns" ] || continue
            for entry in "$KIT_AGENTS/$ns"/*; do
                [ -e "$entry" ] || continue
                name="$(basename "$entry")"
                if [ -f "$entry" ] && [[ "$name" == *.md ]]; then
                    echo "${name%.md}"
                elif [ -d "$entry" ]; then
                    echo "$name"
                fi
            done
        done
        # Installed capabilities: walk each capability's agents/ directory.
        if [ -d "$KIT_CAPABILITIES" ]; then
            local cap
            for cap in "$KIT_CAPABILITIES"/*; do
                [ -d "$cap/agents" ] || continue
                for entry in "$cap/agents"/*; do
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

# Resolve placeholders in the source file using the overlay, write to stdout.
# Delegates to the sibling Python helper (self-contained via PEP 723 inline
# metadata; uv installs `ruamel.yaml` transparently on first invocation,
# regardless of whether the adopter's tree has a host pyproject.toml).
resolve_agent() {
    local source_file="$1"
    local agent_name="$2"
    local overlay_file="$3"
    "$SCRIPT_DIR/_resolve_agent.py" "$source_file" "$agent_name" "$overlay_file"
}

deploy_one() {
    local name="$1"
    local source_file
    source_file="$(source_for "$name")"
    local dest="$CLAUDE_AGENTS/$name.md"

    local tmpfile tmperr
    tmpfile="$(mktemp)"
    tmperr="$(mktemp)"
    if ! resolve_agent "$source_file" "$name" "$OVERLAY" >"$tmpfile" 2>"$tmperr"; then
        # An unresolved overlay category is an adopter-config gap (a category
        # this agent references but the project's overlay.yaml doesn't define
        # — common when a kit agent like `architect` is newer than the
        # adopter's overlay). It is NON-FATAL: skip this one agent loudly with
        # remediation, deploy the rest, and don't abort the whole sync/upgrade
        # over an unrelated capability. The deploy is idempotent — once the
        # overlay defines the category, the next sync deploys the agent.
        local skip_reason
        skip_reason="$(cat "$tmperr")"
        status "skipped" "$name — $skip_reason."
        printf "  %s\n"    "         Deploy it:  pkit agents adopt $name"
        printf "  %s\n"    "         (custom doc layout? run \`pkit agents reconcile --write\`, set the"
        printf "  %s\n"    "          paths in overlay.yaml, then \`pkit sync\`)"
        rm -f "$tmpfile" "$tmperr"
        unresolved=$((unresolved + 1))
        return 0
    fi
    rm -f "$tmperr"

    # Insert the marker as line 2, right after the opening `---`. Frontmatter
    # parsers tolerate YAML comments here; the kit reads the marker to
    # tell its own files apart from adopter-authored agents that happen
    # to share a name.
    awk -v marker="$MARKER" 'NR==1 {print; print marker; next} {print}' "$tmpfile" > "$tmpfile.marked"
    mv "$tmpfile.marked" "$tmpfile"

    # Adopter-content guard: if the destination exists and DOESN'T carry
    # the marker, treat it as adopter-authored OR as a pre-marker kit
    # deploy. Either way, skip without writing — silently overwriting
    # user agents that share a name with a kit agent was a real bug.
    # The two recovery paths are: (a) rename your agent to keep both,
    # (b) delete this file to let the kit re-deploy its marked version.
    if [ -e "$dest" ] && ! head -n 5 "$dest" | grep -qF "$MARKER"; then
        status "skipped" ".claude/agents/$name.md (no kit marker — adopter content or pre-marker deploy)"
        rm -f "$tmpfile"
        return 0
    fi

    if [ -e "$dest" ]; then
        if cmp -s "$tmpfile" "$dest"; then
            status "exists" ".claude/agents/$name.md"
        else
            cp "$tmpfile" "$dest"
            chmod 644 "$dest"
            status "updated" ".claude/agents/$name.md"
        fi
    else
        cp "$tmpfile" "$dest"
        chmod 644 "$dest"
        status "created" ".claude/agents/$name.md"
    fi
    rm -f "$tmpfile"
}

# Pass: deploy every kit agent. An agent with an unresolved overlay category
# is skipped (counted in `unresolved`) rather than aborting the run — see
# deploy_one. `exit_code` is reserved for genuinely catastrophic failures.
exit_code=0
unresolved=0
while IFS= read -r name; do
    [ -n "$name" ] || continue
    deploy_one "$name" || exit_code=$?
done < <(list_kit_names)

# Stale-removal pass: drop deployed agents that carry our marker but are no
# longer in the shipped set. Marker-less files (adopter content) are left
# untouched — strip the marker to keep a no-longer-shipped agent.
pruned=0
shipped="$(list_kit_names)"
if [ -d "$CLAUDE_AGENTS" ]; then
    for dep in "$CLAUDE_AGENTS"/*.md; do
        [ -e "$dep" ] || continue
        dep_name="$(basename "$dep" .md)"
        head -n 5 "$dep" | grep -qF "$MARKER" || continue        # not ours → leave
        if ! grep -qxF "$dep_name" <<<"$shipped"; then
            rm -f "$dep"
            status "removed" ".claude/agents/$dep_name.md (stale — no longer shipped)"
            pruned=$((pruned + 1))
        fi
    done
fi

echo "Done."
if [ "$unresolved" -gt 0 ]; then
    echo "  note: $unresolved agent(s) skipped — overlay category not set; the rest deployed."
    echo "        → Deploy the skipped agent(s):  pkit agents adopt <agent>"
    echo "        → Custom doc layout:            pkit agents reconcile --write → set paths → pkit sync"
fi
exit $exit_code
