---
name: decision-author
description: Author a new decision record (COR, PRJ, or ADR) with proper schema, disciplines, and citations. Use when adding a methodology, project-side, or project-architectural decision.
metadata:
  wraps_command: pkit new decision
gates:
  - COR-006
  - COR-008
  - COR-025
reads:
  records:
    - COR-024
  paths:
    - CONTRIBUTING.md
    - .pkit/decisions/README.md
    - .pkit/cli/README.md
---

# Authoring a decision record

This skill walks through adding a new **COR** (core methodology) record under `.pkit/decisions/core/`. **PRJ** records (project-side, under `.pkit/decisions/project/`) follow the same shape with two differences: they skip the project-neutrality discipline, and they use the `PRJ` prefix and a separate numbering sequence. **ADR** records (project-architectural, at the overlay-resolved `<adr-records>` path per [COR-025](../../decisions/core/COR-025-adr-decision-space.md)) follow the same shape with a different discipline emphasis (architectural-fit, see below) and use the `ADR` prefix at the adopter's `docs/architecture/decisions/` (or wherever the overlay resolves).

## Acceptance gate (run first)

Per `.pkit/decisions/README.md`'s acceptance gate: before doing any procedural work, verify that every record listed in this skill's frontmatter `gates:` field is `accepted`. If any is `proposed` or `superseded`, halt and report — this skill cannot run on a draft hypothesis.

The current declared dependencies:

- **COR-006** — artifact roles. Used so this skill cites authoritative docs/decisions rather than restating them.
- **COR-008** — git workflow conventions. Used for the commit-message format in the final step.

## Procedure

### 1. Read the disciplines

Read `CONTRIBUTING.md`'s **Adding a core record (COR)** section. Three disciplines apply when authoring a COR:

- **Axiom discipline** — use only previously-defined terms in the corpus, generic English, or named external tools (e.g. Claude Code, Yeoman). Do not reach for framework-internal command names that haven't been decided yet.
- **Project-neutrality** — the record must make sense in any adopting project. Framework-source-specific decisions (CLI binary name, self-hosting, distribution channel) belong in PRJ records, not COR.
- **Principles, not inventory** — capture durable rules-among-alternatives, not path lists, command lists, or current-state inventories. Inventory belongs in reference docs that the COR points at.

A fourth discipline applies to **every** record type (COR, PRJ, ADR):

- **Lead with meaning** — the record opens with a short declarative title and a plain-language summary a reader grasps in under a minute, *before* the rigor; cross-references serve the sentence (roughly one per point), not pile five-deep. Keep the depth, but put a readable on-ramp in front of it. See CONTRIBUTING.md's "Lead with meaning". This guards against the wall-of-jargon record whose decision is unrecoverable on a first read.

For **PRJ records**, project-neutrality does not apply (PRJ records are explicitly project-specific). The other disciplines still apply.

For **ADR records** (per COR-025), project-neutrality does not apply either, and the *audience* is the project's architects + future maintainers + on-call engineers (not the methodology corpus). One additional discipline replaces project-neutrality:

- **Architectural fit** — the record captures *what the project built and why*: a system boundary, technology choice, integration pattern, key abstraction, or deployment topology. Workflow conventions, tooling choices unconnected to architecture, and how-we-work practices belong in PRJ, not ADR. The discriminator: an ADR answers "what did we build / why these boundaries / why this technology over alternatives?"; a PRJ answers "how do we work / what tooling / what's our process?". When a decision touches both, prefer pinning the architecturally-significant aspect as ADR and cross-referencing a PRJ for the workflow-mechanical aspect.

### 2. Read the schema

Read `.pkit/decisions/README.md`'s **Schema** and **Statuses** sections. Every record has the same frontmatter and four required sections.

### 3. Pick a slug

Kebab-case, 2–4 words, describing what's decided. Examples: `content-mechanisms`, `merge-delivery`, `pr-workflow`, `git-conventions`, `pattern-extraction`.

### 4. Stamp the stub

Use the methodology's authoring command to scaffold the file (per `.pkit/cli/README.md` → "Authoring commands" → `new decision`):

```
pkit new decision core <slug>            # for COR
pkit new decision project <slug>         # for PRJ
pkit new decision adr <slug>             # for ADR (per COR-025)
```

The command picks the next number in the namespace, stamps the frontmatter (`id`, `title` placeholder, `status: proposed`, today's `date`, `author` from git config), and writes the four required section headers (`## Context`, `## Decision`, `## Rationale`, `## Implications`) with empty bodies.

For the `adr` namespace, the target directory is resolved from `.pkit/agents/project/overlay.yaml`'s top-level `adr-records:` key (first entry). The directory must exist before stamping — if not, the command refuses with a `mkdir -p` hint. If the overlay key is missing or the path points inside `.pkit/`, the command refuses with a pointer to COR-024/COR-025.

This is the deterministic half of authoring. The conversational half — drafting the body — happens in the next steps.

### 5. Draft the body

Open the stamped file and fill in:

- **Title** — replace the placeholder with the actual short imperative title.
- **`## Context`** — what situation prompted this decision?
- **`## Decision`** — what was decided. Single crisp sentence ideally; complex decisions may use sub-sections.
- **`## Rationale`** — why this choice over alternatives. May include an `### Alternatives considered` sub-section.
- **`## Implications`** — what does this mean for code, tests, workflow, downstream decisions?

### 6. Self-check against disciplines

Before showing the draft, walk it against each applicable discipline:

- *Axiom*: every term used has a prior definition, is generic English/Markdown/filesystem vocabulary, or names a known external tool.
- *Project-neutrality* (COR only): would this record fit naturally in `example-brownfield` or `example-greenfield` adopting the methodology?
- *Architectural fit* (ADR only): does the record answer "what did we build / why these boundaries / why this technology"? If it answers "how do we work / what's our process", it belongs in PRJ.
- *Principles-not-inventory*: does the body capture rules-among-alternatives, or has it slipped into enumerating state? Tag candidate content as *rule* or *inventory*; inventory gets a one-line cross-reference, not enumeration.
- *Lead with meaning* (every record type): is the title short and declarative? Does a plain-language summary open the record so a reader grasps the decision in under a minute before the rigor? Do any sentences pile up cross-references and bury their own meaning? If the decision isn't recoverable on a first read, revise the on-ramp before showing it.

If any check fails, revise.

### 7. Show the draft for review

Surface the draft to the user. Do **not** commit until approved. The acceptance gate forbids using the new record as a basis for downstream work until it's accepted; the same caution applies to committing — uncommitted drafts can still be revised cheaply.

### 8. Commit (after approval)

Per COR-008, use conventional-commits format. Type is `decision`; scope reflects the area:

```
decision(<scope>): add COR-NNN <short title>

<body — 1–3 paragraphs summarising context and decision>

Status: proposed.

Co-Authored-By: <as appropriate>
```

The record lands as `proposed`. Acceptance is a separate gesture (status flip + a follow-up commit, per the acceptance gate). Do **not** mark the new record `accepted` in the same commit unless the user explicitly approves both the addition and the acceptance together.

## Variations

- **Refining an existing accepted record** — edit the record in place. Git history is the change log; the spec does not duplicate it inside the record. Don't use this skill for refinements that don't introduce a new decision.
- **Superseding an existing record** — set `supersedes: COR-NNN` in the new record's frontmatter; the superseded record gets a *Superseded by …* line at the top of its body. This skill handles the superseding record's authoring; the in-place edit on the superseded record is a separate step.
