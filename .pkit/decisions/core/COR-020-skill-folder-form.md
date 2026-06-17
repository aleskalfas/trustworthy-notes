---
id: COR-020
title: Skill families ship as one composite skill with sub-procedure files
status: accepted
date: 2026-05-21
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

COR-015 settled the flat-vs-folder layout for skills and agents: atomic artifacts ship as a flat `<name>.md` file; composite artifacts (those with sibling helpers — templates, sub-prompts, auxiliary scripts) ship as a folder `<name>/<name>.md` plus siblings. The choice is content-driven.

A new shape has emerged in practice: **families of related skill-operations** that share a domain, a body of disciplines, and a vocabulary, but differ in the operation they perform. The schemas mechanism currently ships four such operations as four separate flat skills: `schema-author`, `schema-extend`, `schema-rename`, `schema-distill`. Each is its own entry in the skills list. Future families (e.g., a body of `decision-*` operations beyond authoring, or `bundle-*` operations) face the same shape.

Two questions COR-015 doesn't directly settle for the family case:

1. **Granularity.** Should each operation in a family be its own skill (sibling flat files with a prefix), or should the family be one skill whose canonical file dispatches to per-operation siblings?
2. **Supporting content.** The "siblings" COR-015 sanctioned for composite skills (templates, scripts) extend naturally to sub-procedure markdown files — but the record didn't take a position on dispatcher-style routing as an explicit pattern.

This record extends COR-015's composite-folder pattern with a rule for the family case.

## Decision

A **family of related skill-operations** ships as **one composite skill** under COR-015's folder form:

```
.pkit/skills/<namespace>/<family>/
├── <family>.md          # canonical dispatcher — describes the family, routes to operations
├── <operation>.md       # per-operation walkthroughs (one per file)
├── ...
└── (other supporting files — scripts, reference docs, templates, etc.)
```

The canonical file (`<family>.md`) acts as a **dispatcher**: its body describes the family's domain (shared framing, disciplines, terminology) and delegates to per-operation siblings via progressive disclosure ("for authoring a new schema, see `author.md`; for adding an entry, see `extend.md`; ..."). Each operation sibling is a focused walkthrough; the canonical file is short and routing-oriented.

A skill is part of a family when:

- Multiple related operations share a domain (same artifact kind, same area, same body of disciplines).
- Each operation has its own procedure but they share framing — gates, terminology, when-to-use judgement.
- Discovering them as siblings under a domain name reads more naturally than discovering them via prefix-tagged flat skills.

A single-operation skill — one procedure, no family — stays flat per COR-015. Folder form is also still available for a single-operation skill that needs sibling helpers (a template, an architecture note, a script) — also per COR-015.

### Supporting content alongside the dispatcher

The composite folder accepts arbitrary supporting siblings — extending what COR-015 already sanctioned:

- **Per-operation walkthroughs** — the family case described above.
- **Reference docs** — architecture notes, longer examples, diagrams, the family's design rationale beyond what fits in the dispatcher.
- **Scripts** — helpers the skill invokes (when the operation's deterministic part lives in a script rather than a `pkit new <kind>` command).
- **Templates** — boilerplate the skill stamps into the project.

Each sibling is referenced from the dispatcher via progressive disclosure: the canonical file points readers (or the harness) at the right file based on the requested operation or content.

### Frontmatter conventions for composite skills

A composite skill carries **one set of frontmatter** at the dispatcher level. Sub-procedure files (and other supporting files inside the folder) are markdown content with no frontmatter — they are sections of one logical document, not separate skills.

The dispatcher's frontmatter covers the whole composite skill:

- `name` — the family's identity (e.g., `schema`).
- `description` — family-level description. Names the domain + when to invoke the skill; the dispatcher's body handles per-operation routing.
- `gates` — the **union** of every sub-procedure's acceptance gates. A composite skill's reader needs every record in this list accepted before invoking any operation; declaring less would let an operation depending on an un-accepted gate slip through.
- `reads.paths` — the **union** of every sub-procedure's read-paths. The reader prepares context once for the family.
- `composes` — the list of every supporting file the composite carries, as paths relative to the skill folder. Captures sub-procedure markdown files, scripts the skill invokes, templates it stamps, and any other reference content alongside the dispatcher. The validator checks each listed path exists on disk; missing entries surface as `composes` issues the same way missing reads.paths do. The canonical dispatcher file is implicit — it's the file `composes` lives in — and need not be self-referenced.
- `metadata` — family-level metadata. The composite skill rarely wraps a single command (different operations wrap different commands); per-operation command references live in the dispatcher's body, not in a single `wraps_command` field. When useful, `metadata.wraps_commands` (plural) lists them.

Sub-procedure files (`<operation>.md`) start with their `# Title` and body — no `---` frontmatter block. Body references (record IDs, paths) follow the same conventions skills already use; the kit's reference-graph walker treats them as part of the skill's body.

This convention keeps composite skills behaving like one skill to the harness, the kit's reference graph, and the validator — while letting authors read the per-operation walkthrough they need without scrolling through the others. The `composes` field gives a machine-readable inventory of every file inside the composite so the kit's mechanisms can track them uniformly, without distinguishing between sub-procedure prose, scripts, and templates.

## Rationale

**Why one composite skill per family rather than N flat skills.** The flat-per-operation form scales linearly with the number of operations: the skills list grows by N per family, even when the family is one conceptual domain. A composite skill with per-operation siblings keeps the skills list shaped by domain (one entry per family) while preserving the per-operation walkthrough granularity inside the folder. Discoverability scales with families, not operations.

**Why dispatch via the canonical file rather than a separate "router" file.** COR-015 already names `<name>/<name>.md` as the entrypoint for folder-form skills. Reusing that file as the dispatcher avoids inventing a second entrypoint convention (no `index.md`, no `router.md`). The canonical file's body is just routing prose; the per-operation files are the substantive walkthroughs.

**Why this fits inside COR-015 rather than supplanting it.** COR-015's rule — flat when atomic, folder when composite — still holds. This record adds a sub-case: when "composite" means "family of operations," the operations are sibling sub-procedure files and the canonical file dispatches. The base rule is unchanged.

**Why include the non-family supporting-content cases.** Scripts, templates, and reference docs are already sanctioned by COR-015 ("helpers"); naming them explicitly here makes the folder form's full vocabulary visible alongside the new family case. A skill author surveying COR-020 sees the complete picture of what a composite skill can carry.

### Alternatives considered

- **Keep flat-per-operation with naming convention only** (status quo). Rejected — skills list scales linearly with operations; family relationship lives only in prefixes; shared framing repeats across N skills. Doesn't scale as families proliferate.
- **N composite skills per family** (each operation is its own folder with its own helpers). Rejected — duplicates the family framing across N folders; the operations don't actually have their own distinct helpers, just shared family vocabulary.
- **A flat "umbrella" skill that mentions the family operations without folder structure** (e.g., a `schemas` skill that lists the four operations in prose but they remain separate skills). Rejected — faux parent-skill; doesn't capture the family at the skill level, and the operations are still separate entries in the skills list.
- **Per-author choice without a convention** (some families use composite, others stay flat). Rejected — drift across the corpus; readers can't predict whether a family is composite or flat without inspecting each.

## Implications

- **The schemas family migrates first.** `schema-author.md`, `schema-extend.md`, `schema-rename.md`, `schema-distill.md` consolidate into `.pkit/skills/core/schema/` with files `schema.md` (the dispatcher), `author.md`, `extend.md`, `rename.md`, `distill.md`. The dispatcher's frontmatter carries the family-level description; per-operation files use the canonical file's framing as their context.

- **The adapter's deploy primitive handles folder-form skills already (per COR-015), but may need to symlink sibling files in addition to the canonical one.** A composite skill's harness-side layout exposes both the dispatcher and the per-operation siblings to Claude Code. The Claude Code adapter's `deploy-skills.sh` extends to symlink the whole folder when the source is composite (rather than just the canonical file). Other adapters resolve the layout per their own harness conventions.

- **The kit's reference-graph walker treats sub-procedure file bodies as part of the composite skill's body.** Per COR-013's bidirectional rule, body-cited references reconcile against the dispatcher's frontmatter declarations. The walker recurses into composite folders to collect cited record IDs / paths from every sibling file before reconciling. The dispatcher's `gates` and `reads.paths` therefore carry the union of every sub-procedure's references; orphan citations (cited in a sub-procedure but missing from the dispatcher's declarations) surface as validation issues the same way they do for flat skills.

- **The `composes` field is a structural inventory.** The validator confirms every path it lists exists on disk relative to the skill folder. Files referenced by `composes` aren't validated against body citation (a composite may carry a script that's only invoked at runtime, never named in prose) — `composes` answers "what files make up this skill" while `reads.paths` answers "what external content does this skill read." Both are declared in the dispatcher's frontmatter; their semantics differ.

- **CLAUDE.md's authoring-tasks table simplifies for families.** One row per family naming the composite skill; the per-operation choice lives in the dispatcher's body, not the table. Single-operation skills keep their existing one-row-per-skill representation.

- **Future skill families adopt the composite form from creation.** When a second operation joins an existing single-operation skill (e.g., a future `decision-validate` joining `decision-author`), the author migrates the single-operation skill from flat to composite, moving its current procedure into a `decision/<operation>.md` file and stamping a dispatcher.

- **The schemas area README's "Schemas authoring skills" section** (if/when it lands) describes the family at composite-skill altitude — one skill `schema`, with sub-procedures listed below.

- **Naming conventions for families** — the family name is the domain name (singular noun: `schema`, not `schemas`, even when the matching area uses the plural). Operation file names are the role (`author.md`, `extend.md`) without restating the family. Together they read naturally: invoking `schema` → "Working with schemas: pick an operation" → operation file.
