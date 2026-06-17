---
variant: universal
---

# Decision records

This directory holds your project's architectural-decision record: why each significant choice was made, separately from how it is currently implemented. project-kit installs and maintains the decision-record system here, so you can capture your own decisions in a consistent, reviewable form alongside the methodology decisions project-kit ships.

## Two namespaces, two prefixes

| Directory | Prefix | Owner | Lifecycle |
|---|---|---|---|
| `core/` | **COR** | project-kit | Maintained by project-kit; refreshed on sync; **do not edit** |
| `project/` | **PRJ** | Your project | Yours. project-kit never touches it |

The two namespaces have **independent numbering**. `core/COR-001` and `project/PRJ-001` are separate decisions about separate things; neither blocks the other.

The distinct prefixes mean a reference like `COR-002` or `PRJ-007` is unambiguous on sight — no need to know the surrounding directory to know which side of the .pkit/project line it belongs to.

## The no-shared-files invariant

Every file has exactly one owner — kit or project — and they never share a path.

This invariant is what makes the namespace split above operationally safe. project-kit's sync operation works on a fixed set of kit-owned paths; project-owned paths are never read or written by sync. There is no merge logic, no conflict UI, no marker comments, no include-with-substitution mechanism.

Sync **cannot** produce a conflict. You can run it whenever you like — it cannot break anything you wrote.

The same `core/` / `project/` pattern (and the same invariant) governs other kit areas in your project — `.pkit/agents/`, `.pkit/rules/`, and so on. To extend kit-shipped content, add sibling files in the matching `project/` directory; never edit a kit-owned file.

Some files must live at fixed paths that you will want to extend — root `CLAUDE.md` is the canonical example. The invariant rules out editing such files in place to add kit content; the resolution is to keep the fixed-path file project-owned and ship the kit's canonical content at a separate path that the project's file references. The lifecycle that supports this — when files are first written, when they are updated — is detailed in COR-001.

## File naming

`<PREFIX>-NNN-slug.md`, where:

- `<PREFIX>` is `COR` (in `core/`) or `PRJ` (in `project/`).
- `NNN` is a zero-padded serial within the namespace (`001`, `002`, …, `099`, `100`).
- `slug` is a kebab-case shorthand of the title — short enough to keep file listings self-documenting, long enough to identify the decision without opening the file.

Examples: `COR-001-init-vs-synced-lifecycle.md` (kit-owned, read-only), `PRJ-001-our-architecture.md` (yours).

## Schema

Each record is a Markdown file with YAML frontmatter and four required sections:

```markdown
---
id: PRJ-NNN          # for your own records; COR records you receive use the COR prefix
title: Short imperative title
status: proposed | accepted | superseded
date: YYYY-MM-DD
author: Name <email>  # primary author (git-style)
supersedes: PRJ-NNN  # optional — same-namespace prefix as the superseded record
---

## Context

What situation or question prompted this decision?

## Decision

What was decided. Single sentence ideally; complex decisions may use sub-sections (D1, D2, …) but the top line stays crisp.

## Rationale

Why this choice over the alternatives? What goes wrong with a different choice?

## Implications

What does this mean for the code, the tests, the workflow, downstream decisions?
```

Larger records may add sub-sections (e.g. *Alternatives considered*, *Migration path*). Those four headings are the contract; everything else is optional.

The **`author`** field captures responsibility for the record — git-style `Name <email>` matching the value the author would use as their git commit identity. When multiple users collaborate on a project, this makes per-record authorship explicit at a glance; git history captures the rest (commit author, `Co-Authored-By` trailers). The schema may grow a `co-authors` list if frequent multi-author records earn it.

## Statuses

- **`proposed`** — under discussion. Not binding. **Implementation must not depend on the record's content** — see "The acceptance gate" below.
- **`accepted`** — in effect. Implementation must comply.
- **`superseded`** — replaced by a newer record. The successor sets `supersedes: PRJ-NNN` (or `COR-NNN`) in its frontmatter; the superseded record adds a *Superseded by …* line at the top of its body. The superseded record is preserved as historical material — never deleted.

A record moves only forward through these states: `proposed → accepted → superseded`. There is no `rejected` state — a rejected proposal is deleted before it lands.

Supersession is always within a single namespace.

## The acceptance gate

Implementation work — code, content, tooling, downstream decisions — depends only on **accepted** decisions. Proposed records are draft hypotheses, useful for discussion but not authoritative. Authoring work that would cite a still-proposed record violates the gate; either accept the record first (a one-line status flip and a commit) or pause the implementation.

The gate applies to every kind of dependent work:

- **Decisions** that build on other decisions cite only accepted predecessors.
- **Docs** describing systems built on a decision wait until that decision is accepted.
- **Skills and agents** that automate work depending on a decision verify acceptance before running. The mechanism for declaring and verifying decision dependencies is part of each artifact area's own README (e.g. future `.pkit/skills/README.md`, `.pkit/agents/README.md`).

Acceptance is intentionally cheap — flipping `proposed → accepted` is one line and one commit. The friction is not in the flip; it's in the requirement that everyone look at the record and agree before depending on it.

## Refining an accepted record

For clarifications, scope tweaks, or refinements that do not invalidate the original decision: edit the record in place. Git history is the change log — the spec does not duplicate it inside the record itself. For changes that overturn the original, write a new superseding record instead.

## Adding a record

You add records to `project/` — your own architectural decisions, in your own namespace.

The recommended path is the kit's authoring command (specified in `.pkit/cli/README.md`):

```
pkit new decision project <slug>
```

This stamps `PRJ-NNN-slug.md` with the schema's frontmatter and four section headers; you fill in the body and flip status to `accepted` once agreed.

If you prefer to author by hand, the procedure is:

1. Pick the next available number in `project/`.
2. Create `PRJ-NNN-slug.md` with the frontmatter and the four sections above.
3. Open it as `proposed` if it is still under discussion, `accepted` once agreed.

The directory listing in `project/` serves as the index — file names carry their slugs, and most projects' corpora are small enough that no separate index is needed. If yours grows numerous, a `README.md` index can be added inside `project/` as a convenience.

Records in `core/` are managed by project-kit. **Do not edit them** — they are refreshed on every sync, and your edits would be overwritten. To propose a change to the methodology itself (a new core record, a refinement of an existing one, or a supersession), contribute to project-kit upstream.

## Why this shape

A few choices in the system above are deliberate:

**Markdown, not a structured store.** Records are read by humans and AI agents alike. Both want plain text in a versioned repo.

**Two distinct prefixes (COR/PRJ), not a shared one.** A shared prefix would force you either to coordinate numbering with the kit or to live with collisions. Distinct prefixes make ownership self-evident at every reference and let each side number from 1 independently.

**Four required sections, not more.** Context, Decision, Rationale, Implications cover what every reader needs. Larger records can add sub-sections without those becoming mandatory in small ones.

**Conflicts impossible, not resolvable.** project-kit makes file-conflict scenarios structurally unreachable rather than introducing a UX to resolve them. Sync never asks "what do I do now?".
