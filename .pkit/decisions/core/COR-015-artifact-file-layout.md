---
id: COR-015
title: Flat file vs folder layout for atomic vs composite artifacts
status: accepted
date: 2026-05-15
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

Skills and agents are both file-bearing artifact kinds. Skills shipped today live under `.pkit/skills/{core,project}/<name>/SKILL.md` — each skill is a directory containing a fixed-name file plus any optional supporting files. Agents per COR-013 inherited the same convention as `.pkit/agents/{core,project}/<name>/<name>.md`.

In practice, every skill shipped to date is a single file. None has supporting templates, sub-prompts, or auxiliary scripts. The per-name directory wrapper is overhead without payoff: it adds one level of nesting that carries no information beyond what a flat file `.pkit/skills/core/<name>.md` would already carry.

Folders are useful when an artifact has helpers — a skill with a generated template the body references, an agent with a sibling reference matrix, etc. They are not useful when the artifact is atomic. The current convention forces folders unconditionally, accepting the overhead to avoid the conditional rule.

This record settles the rule: artifacts are flat when atomic, folder when composite. The rule applies symmetrically to skills and agents (and any future file-bearing artifact kind that fits the same shape).

## Decision

A core-shipped artifact (skill or agent) takes one of two layouts on the source side:

- **Flat layout** — `<area>/<namespace>/<name>.md`, when the artifact is a single file with no supporting siblings.
- **Folder layout** — `<area>/<namespace>/<name>/<name>.md`, with supporting files as siblings of the canonical file, when the artifact has helpers.

The rule is *conditional*: when an atomic artifact gains its first helper file, it migrates from flat to folder. When a composite artifact loses its last helper, it migrates back to flat. Migration is a structural change visible in git; not a frequent operation.

### Filename inside a folder

When folder-form, the canonical file is named `<name>.md` (matching the directory). Existing folder-form skills used the fixed name `SKILL.md`; that convention is dropped — `<name>/<name>.md` is uniform across kinds. The legacy SKILL.md name was a Claude Code-influenced choice; the source has no need for harness-specific filenames.

### Adapter deploy

The adapter's deploy primitive accepts both layouts on the source side. The harness's expected deploy layout is the adapter's concern (per COR-005). For example, Claude Code expects skills at `.claude/skills/<name>/SKILL.md` regardless of source layout — the Claude Code adapter's `deploy-skills.sh` translates from either flat or folder source into the harness's expected directory + `SKILL.md`-named symlink. Agents in Claude Code expect `.claude/agents/<name>.md` (flat); `deploy-agents.sh` resolves from either source form.

Future adapters (Codex, Cursor, others) translate to their own harness conventions; the source layout is harness-neutral per COR-006.

## Rationale

**Why conditional and not unconditional.** An unconditional rule ("always folders" or "always flat") trades one cost for another. Always-folders pays the wrapper-overhead cost for atomic artifacts. Always-flat blocks future helper-bearing artifacts from carrying their helpers cleanly. A conditional rule keeps the layout fitted to actual structure: ceremony only when content justifies it.

**Why the rule is symmetric across skills and agents.** Both are file-bearing artifact kinds with the same composite-vs-atomic distinction. A different rule per kind would be asymmetric for no methodology reason; the harness-driven layout differences (Claude Code's `SKILL.md` filename, agents-as-flat-files-in-`.claude/agents/`) belong in the adapter, not the source.

**Why drop the `SKILL.md` filename.** The fixed name was useful when every skill was in a folder — it gave Claude Code one path to look for. With the conditional layout, flat skills are at `<name>.md` and folder skills are at `<name>/<name>.md`. Uniform with agents; no special name to remember. The Claude Code adapter still produces `SKILL.md` symlinks at the harness side; that translation lives in the adapter, not the source convention.

**Why migrate now rather than after the next composite skill ships.** The current corpus has six atomic skills, all using folder layout unnecessarily. Migrating them while the count is small is far cheaper than later. The rule is also worth recording before the agent-area accretes more agents (the first one, methodology-reviewer, was authored before this rule landed and used folder layout by inertia).

### Alternatives considered

- **Always-folders (status quo).** Rejected — overhead without payoff for atomic artifacts; the inertia of "every skill has a folder" obscures the question of whether the folder earns its keep.
- **Always-flat.** Rejected — closes the door on composite artifacts with sibling helpers (which is a legitimate need even if no current artifact uses it).
- **Conditional, but skills and agents stay asymmetric (skills always folders, agents flat-or-folder).** Rejected — the harness-driven argument for skills' folder convention belongs in the adapter, not the source. The structural rules don't need to encode harness-specific quirks.
- **Keep `SKILL.md` naming for folder-form skills.** Rejected — uniform `<name>.md` across kinds is easier to teach and matches what flat-form already uses.

## Implications

- **Existing skills migrate.** `decision-author`, `adapter-author`, `area-author`, `bundle-author`, `migration-author`, `scratchpad-author` — all currently `<name>/SKILL.md` — flatten to `<name>.md`.
- **Existing agent migrates.** `methodology-reviewer` flattens from `methodology-reviewer/methodology-reviewer.md` to `methodology-reviewer.md`.
- **Adapter deploy scripts accept both layouts.** `deploy-skills.sh` and `deploy-agents.sh` each resolve a name to either the flat or folder form on the source side and translate to the harness's expected layout.
- **Skills area README updated.** `.pkit/skills/README.md` documents the new rule, including how the SKILL.md naming convention drops in favour of `<name>.md`.
- **Agents area README updated.** `.pkit/agents/README.md` documents the layout rule.
- **Future authoring commands stamp flat by default.** `pkit new skill <name>` (when it ships) and `pkit new agent <name>` (per COR-013) stamp a flat file; the author migrates to folder form only when helpers materialise.
- **`.claude/skills/*` symlinks updated.** Project-kit's own self-host tree currently tracks directory symlinks at `.claude/skills/<name>`; after migration the tracked entries become `.claude/skills/<name>/SKILL.md` file symlinks (the adapter's translated form).
