---
id: COR-012
title: Scratchpad notes for exploratory drafts
status: accepted
date: 2026-05-12
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

Some architectural questions are large enough that crystallising them into a record on first pass is premature — the design space is not yet mapped, the alternatives are not yet enumerated, the load-bearing tensions are not yet visible. The work needed before such a record can be written is *exploratory*: scribbling, listing forces, drawing arrows between artifacts, abandoning lines of thought, picking promising ones, and progressively narrowing toward a decision.

Today this exploratory work has no recognised home. The only existing instance — `INVENTORY.md` at repo root — is an unformalised one-off: it sits outside the methodology's content shape system, it has no lifecycle states, and it has no formal relation to the records it eventually fed into. Future explorations will either scatter (every author invents a placement) or get skipped entirely (jumping to records before the design space is mapped). Per COR-007's recurrence trigger, the right response is to formalise the pattern rather than reinvent its placement each time.

The work needed is neither a *decision* (no decided choice yet), nor a *doc* (docs are normative state; exploratory drafts are non-normative and retire), nor a *skill* (not procedural), nor an *agent* (not a role). Exploratory drafts have their own lifecycle: they begin open-ended, accumulate content, and either *successfully retire* into other artifacts or *get abandoned* when the line of thought doesn't pan out. The four artifact shapes defined in COR-006 do not capture this.

## Decision

A **scratchpad note** is a recognised artifact shape: a non-normative working draft that explores an open question and retires by either producing other artifacts or being abandoned. Scratchpad notes are a fifth content shape, orthogonal to the four established by COR-006.

### Where scratchpad notes live

Scratchpad notes live in a new first-class area at `.pkit/scratchpad/`, of the **specialized** variant per COR-011. The area has no `core/` / `project/` split — there is no core-side canonical scratchpad content to propagate; the core layer ships only the convention (the README) and the tooling. Notes themselves are project-owned and never synced.

### The lifecycle is the directory

A scratchpad note's lifecycle has three states: an **active** state (the note is being filled or referenced), a **successfully-retired** state (the note's content has been incorporated into other artifacts), and an **abandoned** state (the line of thought did not pan out, but the note is kept as a record of what was explored). The folder a note lives in *is* its state; there is no parallel `status:` field in the note's frontmatter. State transitions are filesystem moves.

The specific state labels and folder names live in `.pkit/scratchpad/README.md`. Per COR-006's docs-as-state-and-reference role, the labels are reference content that can be refined without amending this record; only the three-state principle and the folder-as-state mechanic are locked here.

### Frontmatter tracks lifecycle and authorship

A scratchpad note's body opens with a level-1 heading carrying its title — markdown previews, the host platform's rendering, and `head` all surface the title without needing to parse frontmatter. The frontmatter does not carry the title; it carries lifecycle and authorship metadata that benefits from being machine-readable and visible at file-open without a separate `git log` query.

Active-state notes track who is working on them and when the work began. Retired notes additionally track when the retirement happened and — when applicable to the retired-state semantics — which artifacts the note's content fed into. The full field set and field names live in `.pkit/scratchpad/README.md`; only the principle (frontmatter carries lifecycle and authorship; not the title) is locked here.

### Filename carries the date

A note's filename is `<YYYY-MM-DD>-<slug>.md`. The date is the note's start date and makes filesystem-chronological sort line up with creation order. The slug is kebab-case shorthand of the topic, 2–4 words.

### CLI surface

The methodology's authoring and management surface (per COR-004 and COR-005) gains scratchpad-specific commands:

- An authoring command (`pkit new scratchpad <slug>`) stamps a new note in the active-state folder with today's date, paired with an authoring skill per COR-005's skill / command pairing rule.
- State-transition commands (one per retired state) move a note's file from the active-state folder to the retired-state folder, applying whatever frontmatter changes the transition produces. State-transition commands are mechanical; per COR-006's discriminator they need no paired skill.

The full per-command surface (flag set, exact verb shapes) is specified in `.pkit/cli/README.md`'s "Authoring commands" section, not enumerated here. Implementation of these commands and the paired skill lands alongside this record or in immediate follow-up PRs; the convention is what this record fixes.

### Extending COR-006

COR-006's discriminator gains a fifth row for scratchpad notes (carries: exploratory working drafts; loaded / read when: the design space for an open question needs to be mapped before a decision crystallises). This extends the four-shape rule without invalidating it; the refinement edit to COR-006 lands alongside this record.

## Rationale

**Why a fifth content shape rather than a sub-kind of doc.** Docs are normative state — they describe what *is*, and they are intended to live. Scratchpad notes are non-normative exploration — they describe what *might be*, and they are intended to retire. Treating scratchpads as a sub-kind of doc would hide the fundamentally different lifecycle (retiring vs persisting) and would force the lifecycle machinery into a content shape that does not otherwise have one.

**Why the folder is the state, not a frontmatter field.** Two reasons. First, single source of truth: a frontmatter `status:` and a folder location can drift; one of them has to win, and the file's actual location is the more authoritative signal (an author or reader sees the folder immediately; the frontmatter requires opening the file). Second, the retirement event is meaningful and observable: a state transition becomes a `git mv` operation visible in diffs and `git log`. Folder-as-state collapses the lifecycle's machinery into something the filesystem already does well.

**Why a specialized area with a flat layout.** The core layer ships no canonical scratchpad notes — only the convention. Under COR-003's universal pattern (`core/` for propagation, `project/` for extension), `core/` would always be empty in adopters, which is wasteful and signals the wrong shape. The specialized variant per COR-011 fits: the area has a contract (notes live here, in folders by state, with this filename) but no parallel-alternatives axis (per COR-005) and no canonical-content axis (per COR-003's universal variant).

**Why H1-in-body rather than frontmatter-only title.** Markdown preview, the host platform's rendering, and `head` all show the body but not the frontmatter; a frontmatter-only title leaves the rendered note untitled in the contexts where authors actually read it. Decision records do not have this problem because they are typically read on the host platform's UI or as accepted artifacts in known formats; scratchpads are read in markdown preview during active exploration. The H1 also doubles as the title for any tooling that walks markdown directly.

**Why the date in the filename.** Filesystem-chronological listing of a directory is the cheapest "show me what's been explored when" query; a date prefix makes that listing useful without any tooling. The same date also lives in the frontmatter as canonical machine-readable lifecycle metadata — the same duplication a decision record carries with `id:` appearing in both filename and frontmatter.

**Why CLI commands ship with the convention rather than after the second instance.** COR-007 prescribes extracting tooling after recurrence is visible — but two of the operations (stamping a new note; moving a note between state folders) are recurring by construction. Every note created involves the first; every retirement involves the second. The recurrence is structural, not empirical, so the wait-for-recurrence trigger does not apply. The third command (reopening or listing) is genuinely speculative and is deferred until recurrence is visible.

**Why the COR fixes the three-state principle but defers labels to the README.** The principle (active vs successfully-retired vs abandoned) carries the load: it determines lifecycle machinery, the number of state folders, the number of state-transition commands. The labels (the specific words) are reference content that can refine without invalidating the principle. Per COR-006's docs-as-state role, labels belong in the README.

### Alternatives considered

- **Treat scratchpad notes as a sub-kind of doc.** Rejected — conflates normative state with non-normative exploration, hides the retire-or-abandon lifecycle, and forces lifecycle machinery into a shape that has none elsewhere.
- **Universal area variant (`core/` + `project/`).** Rejected — `core/` would always be empty in adopters because the core layer ships no canonical scratchpad notes, only the convention. The universal pattern is meant for areas with core-side canonical content per COR-003.
- **Status in frontmatter, single flat directory.** Rejected — two sources of truth (the field and the file's siblings) that can drift; retirement becomes a frontmatter edit rather than a visible `git mv`; cumulative listings of active-only notes require parsing every file's frontmatter rather than `ls active/`.
- **Bundle-based variant (alternative implementations).** Rejected — there is no parallel-alternatives axis for scratchpad notes. Every adopter wants the same convention.
- **No lifecycle distinction between successfully-retired and abandoned.** Rejected — collapsing the two loses signal that future readers care about: an abandoned line of thought is a record of *what did not work*, valuable for not re-treading; a successfully-retired note is a record of *what produced what*, valuable for archaeology. Two reasons, two states.
- **No CLI commands; hand-stamp and `git mv` directly.** Rejected for stamping (mechanical; the recurrence is structural; same argument as `pkit new decision` per COR-005). Accepted for the third state-transition command (reopen) and for listing — deferred until recurrence is visible.

## Implications

- **A new area is materialised** at `.pkit/scratchpad/{README.md, <active>/, <retired>/, <abandoned>/}`. The state-folder names are chosen in the README. The README specifies: lifecycle states and their meanings, frontmatter shape per state, filename convention, and the retire vs abandon distinction.
- **COR-006 gains a fifth row** describing scratchpad notes' role (exploratory working drafts; loaded when mapping the design space before a decision crystallises). The edit is a refinement, not a supersession, and lands in the same PR as this record.
- **The authoring CLI command `pkit new scratchpad <slug>` ships with this record**, paired with a `scratchpad-author` skill per COR-005's skill / command pairing rule. State-transition commands (one per retired state) ship alongside, with no paired skill (mechanical, per COR-006).
- **`pkit new` and related commands extend the authoring surface** documented in `.pkit/cli/README.md`. Their per-command specifications (flags, output, error shape) follow the CLI conventions adopted by the project.
- **CLAUDE.md surfaces the convention** so future sessions invoke the scratchpad commands rather than re-inventing exploratory-draft placement.
- **Pre-existing unformalised exploratory notes** (those that predate this convention) relocate under it opportunistically. The migration is per-note, not blocking; a project may complete it in one pass or amortise it over time.
- **Adopter relevance.** Any adopter doing methodology-level work hits the same exploratory-draft need. They inherit the area, the convention, and the CLI surface. Adopter scratchpads live in their own `.pkit/scratchpad/` tree under the no-shared-files invariant.
- **No `core/project/` propagation.** Per the area's specialized variant, the sync manifest carries the README (and any core-shipped templates), not the notes. Adopter notes are never read or written by sync.
