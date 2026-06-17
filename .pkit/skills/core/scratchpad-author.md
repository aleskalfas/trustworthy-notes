---
name: scratchpad-author
description: Start a new scratchpad note for an exploratory architectural question too large to crystallise into an immediate record. Use when the design space needs mapping before a decision can be made.
metadata:
  wraps_command: pkit new scratchpad
gates:
  - COR-005
  - COR-006
  - COR-007
  - COR-012
reads:
  records:
    - COR-013
  paths:
    - .pkit/scratchpad/README.md
    - .pkit/decisions/README.md
    - .pkit/agents/README.md
---

# Starting a scratchpad note

A scratchpad note (per COR-012) is the carrier for exploratory work that precedes a decision: mapping the design space, listing forces, sketching alternatives, abandoning unworkable lines, and progressively narrowing toward the artifacts (records, docs, skills, agents) that will eventually crystallise from the work.

This skill walks through stamping a new active-state note and the disciplines that make it useful.

## When to invoke this skill

Use a scratchpad note when:

- The design space for an architectural question is too large to crystallise into a record on first pass.
- Multiple alternatives need enumerating and weighing before one becomes the decision.
- The work is genuinely *exploratory* — you are mapping territory, not implementing a known plan.

If the answer is already clear and you are just writing it down, skip this skill and author the artifact directly (e.g. `decision-author` for a COR/PRJ).

## Acceptance gate

Per `.pkit/decisions/README.md`'s acceptance gate, every record in `gates:` must be `accepted` before the skill can run:

- **COR-005** — skill / command pairing. Establishes the rule that authoring commands ship paired with their skill; this skill is the pairing for `pkit new scratchpad`.
- **COR-006** — artifact roles. The discriminator that places scratchpads as a fifth content shape orthogonal to decisions, docs, skills, and agents.
- **COR-007** — pattern extraction. Used in step 6 below to decide when an evolving exploration is ready to retire.
- **COR-012** — scratchpad notes. The convention itself.

If any is `proposed` or `superseded`, halt and report.

## Procedure

### 1. Pick a slug

Kebab-case, 2–4 words, naming the *question* the note explores. Examples: `agent-architecture`, `versioning-policy`, `bundle-overrides`.

The slug is the file's identity — it survives across state transitions and is referenced from records that crystallise. Pick one that will still read sensibly six months from now.

### 2. Confirm topic boundary

A scratchpad note explores **one question**. If you find yourself wanting to explore two related-but-distinct questions, start two notes. Cross-reference them from each other's body.

The test: would the eventual retirement (`done/` or `dropped/`) produce **one** crystallisation event, or two? If two, split.

### 3. Stamp the note

```
pkit new scratchpad <slug>
```

The command creates `.pkit/scratchpad/active/<YYYY-MM-DD>-<slug>.md` with seeded frontmatter (`authors` from git config, `started` today) and an H1 derived from the slug — edit the H1 on first pass to whatever reads best as the note's title.

### 4. Draft the opening

A scratchpad note's opening typically captures:

- **The question** — one sentence, plainly stated. What needs to be decided?
- **Forces** — what is pulling the answer in different directions? Adopter relevance, existing decisions, recurring constraints, future-proofing concerns.
- **What is already known** — facts about the codebase, prior records, accepted patterns. Cite COR/PRJ records by ID rather than restating their content.
- **Candidate alternatives** — even a rough enumeration; the list sharpens as you write.
- **Open questions** — what would you need to know to choose.

You do not need to use these exact headings. The note is non-normative; structure it however the exploration wants to flow.

### 5. Evolve the note

Add content as the exploration progresses. Other authors may contribute — append entries to `authors:` when they do.

The note is *non-normative*: it can restate, paraphrase, contradict, and explore freely. The single-source-of-truth discipline (COR-006) applies to the four persisting shapes, not to scratchpads.

### 6. Retire the note when the question resolves

When the note's content has produced records / docs / skills / agents:

```
pkit scratchpad done <slug> --produced <ref> [--produced <ref> ...]
```

`--produced` takes record IDs (`COR-013`), file paths (`.pkit/agents/README.md`), or URLs. The command moves the file to `done/` and appends `retired` (today) and `produced` (your refs) to frontmatter.

When the line of thought did not pan out:

```
pkit scratchpad drop <slug>
```

Before dropping, append a closing paragraph to the body explaining *why* the line was abandoned — what was tried, what did not work, what the alternative was. Future readers benefit from knowing the path so they do not re-tread it. The command moves the file to `dropped/` and appends `retired` (today) to frontmatter.

Per COR-007, the retirement event is itself the trigger for noticing whether a *pattern* across notes has emerged that should earn its own tooling (a recurring shape across multiple scratchpads is the kind of recurrence COR-007 names).

## Variations

- **Resuming an abandoned line.** If the dropped reason no longer applies, hand-`git mv` from `dropped/` back to `active/` and edit out the closing "abandoned" paragraph. The reopen command is deferred (per COR-007's recurrence trigger) until this becomes a common operation.
- **Listing notes by state.** `ls .pkit/scratchpad/<state>/` is the simplest listing; a future `pkit scratchpad list` will gain filtering when listing across many states is itself patterned.
- **Multiple notes for one umbrella question.** If a question is large enough to span several notes (e.g. agent architecture has both "role taxonomy" and "deployment pipeline" sub-questions), use sibling notes with related slugs (`agent-architecture-roles`, `agent-architecture-deployment`) and cross-reference each other's bodies.
