---
variant: specialized
---

# Scratchpad notes

Exploratory working drafts for architectural questions that are too large to crystallise into a record on first pass. A scratchpad note is the carrier for the design-mapping work that precedes a decision: listing forces, drawing relations between artifacts, abandoning lines of thought, picking promising ones, and progressively narrowing toward what eventually becomes a COR, PRJ, doc, skill, or agent.

The principles — that scratchpad notes are a fifth content shape (orthogonal to COR-006's four), that the folder is the state, that the area is of the specialized variant — are recorded in [`.pkit/decisions/core/COR-012-scratchpad-notes.md`](../decisions/core/COR-012-scratchpad-notes.md). This README is the spec.

## Layout

```
.pkit/scratchpad/
├── README.md                 # this file (kit-owned, propagated by sync)
├── active/                   # notes currently being filled or referenced
│   └── <YYYY-MM-DD>-<slug>.md
├── done/                     # notes whose content was incorporated into other artifacts
│   └── <YYYY-MM-DD>-<slug>.md
└── dropped/                  # notes whose line of thought did not pan out
    └── <YYYY-MM-DD>-<slug>.md
```

The notes themselves are project-owned and never touched by sync; only this README (and any future kit-shipped templates) is in the propagation manifest. The same convention applies in adopting projects: their scratchpad notes live in their own `.pkit/scratchpad/{active,done,dropped}/` tree.

## Lifecycle

A note moves through three states. The folder it lives in *is* its state — there is no `status:` field in frontmatter.

| State (folder) | Meaning |
|---|---|
| **`active/`** | The note is being filled or actively referenced. The question it explores is still open. |
| **`done/`** | The note's content has been incorporated into other artifacts (records, docs, skills, agents). The question is resolved; the note is kept as the archaeology of how the resolution was reached. |
| **`dropped/`** | The line of thought did not pan out. The note is kept as a record of what was explored and why it was abandoned, so future authors do not re-tread the path silently. |

A state transition is a `git mv` from one folder to another, performed (or wrapped) by the CLI commands below. Transitions are intentionally simple — no validation, no machinery beyond moving the file and updating frontmatter.

## Filename

`<YYYY-MM-DD>-<slug>.md`, where:

- **`<YYYY-MM-DD>`** is the note's start date — the day it first entered `active/`. The date is fixed at creation and does not change when the note transitions between states. It exists in the filename so a filesystem-chronological listing (`ls`, `find`, IDE file tree) matches the order of exploration.
- **`<slug>`** is kebab-case shorthand of the topic, 2–4 words — short enough to keep listings self-documenting, long enough to identify the note without opening it.

Examples: `2026-05-12-agent-architecture.md`, `2026-04-08-inventory.md`.

## Body

A scratchpad note's body opens with a level-1 heading carrying the note's title:

```markdown
# Agent architecture — meta-agents vs role-shaped specialists

…body content…
```

The H1 is the canonical readable title — markdown preview, the host platform's UI, and `head` all surface it without parsing frontmatter. The frontmatter does **not** carry a `title:` field; the H1 is authoritative.

Beyond the H1, the body's shape is up to the author. Scratchpad notes are exploratory, not structured records.

## Frontmatter

Frontmatter exists for machine-readable lifecycle and authorship metadata. The set of fields depends on the current state.

### `active/`

```yaml
---
authors:
  - Name <email>
started: 2026-05-12
---
```

- **`authors:`** — list of contributors as git-style `Name <email>` entries. At creation, just the creator; further contributors append.
- **`started:`** — the note's start date. Mirrors the filename date for machine-readable consumption (same duplication as a decision record's `id:` appearing in both filename and frontmatter).

### `done/`

```yaml
---
authors:
  - Name <email>
started: 2026-05-12
retired: 2026-05-15
produced:
  - COR-013
  - .pkit/agents/README.md
---
```

- **`retired:`** — the date the note left `active/`. Added by the `pkit scratchpad done` command at transition time.
- **`produced:`** — list of artifacts (record IDs, file paths, or URLs) the note's content fed into. Added by the `pkit scratchpad done --produced <ref>...` flags, and editable by hand for later additions.

### `dropped/`

```yaml
---
authors:
  - Name <email>
started: 2026-05-12
retired: 2026-05-15
---
```

- **`retired:`** — the date the note was dropped. Added by the `pkit scratchpad drop` command.
- No `produced:` field — the line of thought did not produce anything.

The note's body, when dropped, should explain *why* the line of thought was abandoned — typically as a closing paragraph or section appended before the move. Future readers benefit from knowing what was tried and why it failed.

## CLI commands

The kit's authoring and management surface (per COR-004 and COR-005) includes:

| Command | Effect |
|---|---|
| `pkit new scratchpad <slug>` | Stamp a new note at `active/<YYYY-MM-DD>-<slug>.md` with today's date. Frontmatter is seeded with `authors:` (from git config) and `started:`; body is seeded with a `# <slug>` placeholder H1. Paired with the `scratchpad-author` skill per COR-005's skill / command pairing. |
| `pkit scratchpad done <slug> [--produced <ref>...]` | Move the file from `active/<slug>.md` to `done/<same-filename>.md`. Append `retired:` (today's date) and `produced:` (from `--produced` arguments) to frontmatter. The `<slug>` argument may match the slug portion of the filename or the full filename. |
| `pkit scratchpad drop <slug>` | Move the file from `active/<slug>.md` to `dropped/<same-filename>.md`. Append `retired:` (today's date) to frontmatter. |

State-transition commands (`done`, `drop`) are mechanical — they wrap `git mv` plus frontmatter updates. Per COR-006's discriminator they need no paired skill.

Deferred (per COR-007 — extract after recurrence is visible):

- **`pkit scratchpad reopen <slug>`** — move from `done/` or `dropped/` back to `active/`. Hand-`git mv` works while this is rare.
- **`pkit scratchpad list [--state <state>]`** — listing helper. `ls .pkit/scratchpad/<state>/` covers the obvious case.

## Authoring workflow

To start a new scratchpad note, invoke the `scratchpad-author` skill (or call `pkit new scratchpad <slug>` directly if you are sure you have the slug, the topic boundary, and the disciplines in mind). The skill carries:

- Slug-choice judgement — picking a name that survives later reading without being so long it clutters listings.
- Topic boundary — what belongs in this one note vs what should be split into a separate one.
- The opening prompt — what kinds of content scratchpad notes typically open with (forces, questions, options, candidate decisions).

To retire a note:

- If the note's content has been incorporated into other artifacts: `pkit scratchpad done <slug> --produced <ref>...`. The `--produced` references can be records, file paths, or URLs.
- If the line of thought is being abandoned: append a closing paragraph to the note explaining why, then `pkit scratchpad drop <slug>`.

## Why scratchpad and not "draft" or "notes"

A *draft* implies a future final form of the same artifact (a draft record will become a record). A scratchpad note is not a draft of anything in particular — it might produce a record, several docs, or nothing at all. *Notes* is too generic and collides with everything else humans call notes. *Scratchpad* matches the actual mode: a surface to scribble on while thinking, that gets cleared or framed when thinking concludes.

## Adopter relevance

Any project doing methodology-level work hits the same exploratory-draft need. Adopters get this README and the CLI commands; their notes live in their own `.pkit/scratchpad/{active,done,dropped}/` tree, project-owned, never touched by sync. Project-kit self-hosts and follows the same convention for its own kit-maintainer notes.
