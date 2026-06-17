---
id: DEC-025
title: Parallelization primitive — `lane:<slug>` labels and typed Blocked-by lines; design proposed pending lived evidence
status: proposed
date: 2026-05-27
author: Ales Kalfas
---

> **Status note (acceptance gate per `.pkit/rules/core.md` rule 2).**
> This DEC lands as `proposed`. The design is documented for cross-DEC coherence with [DEC-023] and [DEC-024], but the acceptance gate forbids implementation work (capability code, schemas, lifecycle scripts citing this DEC) until the open-questions section is resolved from lived evidence (the manual-discipline phase below). Promotion to `accepted` is a separate gesture — a one-line status flip + commit, with the open questions answered by then.

## Context

Real adoption — this project plus IGW plus other near-term targets — runs **multiple issues concurrently** across worktree branches. Without a methodology primitive, every adopter improvises the discipline and the answers drift. The capability today gives adopters no systematic way to answer the two questions a parallel-execution model has to answer:

1. **Can issues A and B be in flight at the same time?** A primitive for *code-surface conflicts* (overlapping files; merge collisions).
2. **Given the in-flight set, what is the unblocked frontier — what is safe to pick up next?** A primitive for *sequence conflicts* (B depends on A's outcome).

The two conflicts are unrelated — code-surface is static and geography-based; sequence is dynamic and outcome-based — and require different mechanisms.

Today, the capability handles only **adjacent** primitives:

- [project-management:DEC-018-workstream-taxonomy-and-lifecycle] — workstreams are *long-lived domain areas* (categorisation, reporting). Overloading them as parallel-lane locks muddies the semantic; renames break the lock partition.
- [project-management:DEC-005-linking-and-containment] — dependencies between issues are **textual prose** in an optional `## Dependencies` body section. The substrate is unparsed; the graph cannot be queried, validated, or reported on. Native sub-issues handle parent↔child *containment* only.

Real adopters need a primitive that disambiguates code-surface conflicts from sequence conflicts and surfaces the ready frontier programmatically. Agent-driven workflows make this acute — an orchestrator computing "what is safe to start now" cannot rely on prose parsing.

### Why this DEC lands as `proposed`

The scratchpad's own recommended path is **manual discipline first → crystallise the primitive later**: adopters run an informal convention while authoring the primitive — capturing the discipline that works in practice, watching where the prose substrate breaks — then promote the crystallised primitive from lived evidence.

That follows [COR-007]'s pattern-extraction discipline: invest in tooling when recurrence forces it, not before. Several open questions below are **evidence-shaped** — they cannot be settled from first principles alone:

- In-flight state mechanism — issue state machine, draft PR linkage, assignee, explicit label?
- Cardinality — one lane per issue, or multi-lane?
- Axis placement — lane joins the classification axes from [project-management:DEC-012-classification-axes] as a fourth axis, or lives outside as a lifecycle marker?
- `Blocked by:` validation shape — `#N` only, `owner/repo#N`, both?

These need lived experience to settle. The DEC documents the design landscape now, so [DEC-023] and [DEC-024] can reference the same terminology, but the implementation gate is the acceptance gate.

## Decision

> **Provisional pending acceptance gate resolution.** The following is the design the capability commits to *if* the open questions resolve as the scratchpad anticipates. Promotion to `accepted` requires the open questions section to be resolved (each question answered, the answer captured here or in a follow-on DEC).

### Design at a glance

| Component | Substrate |
|---|---|
| Code-surface conflict | `lane:<slug>` label series; one in-flight issue per lane |
| Sequence conflict | Typed `Blocked by: #<N>` line inside `## Dependencies` body section |
| Lane catalog | `project/lanes.yaml` — adopter-declared lane definitions |
| Ready-frontier reporter | New verb-subject script (name TBD) that surfaces "what is safe to start now" |

### Lanes — additive to DEC-018, not a re-cut

The `workstream:<slug>` taxonomy from [project-management:DEC-018-workstream-taxonomy-and-lifecycle] stays exactly as written — long-lived domain areas; portfolio-scale; categorisation. **Lanes are a separate primitive** with a separate substrate (`lane:<slug>` label series) and separate semantic (ephemeral; code-area scope; operational lock, not categorisation).

The etymological re-cut (renaming workstreams to lanes) was rejected at the scratchpad stage because shared-board topologies (IGW + AUJ + future peers feeding the same Team Planning board) carry the workstream field at the board level; renaming would require multi-team, multi-repo, multi-environment coordination for what is fundamentally a linguistic cleanup. The substrate vetoes the rename. See the scratchpad for the full analysis.

### `lane:<slug>` label series

A new label series, parallel to but distinct from `workstream:<slug>`. Each label names an ephemeral lock domain (file area, deployment target, fixture set — adopter's call). **At most one in-flight issue per lane** is the lock rule.

### `project/lanes.yaml` — lane catalog

Adopter declares lane definitions in a separate file, paralleling `project/workstreams.yaml`:

```yaml
schema_version: 1

lanes:
  - slug: workbench
    description: Sandbox harness code (workbench/, harness libs).
  - slug: gateway
    description: Gateway routing + auth code.
  - slug: recorder
    description: Session recording subsystem.
```

The lane attribute model is **lighter** than the workstream's 5-attribute shape: slug + description only at v1. Lanes are ephemeral by intent; the workstream attribute model (`status`, `deprecated_reason`) doesn't earn its keep for short-lived lock domains.

### Typed `Blocked by:` — DEC-005 refinement

The `## Dependencies` body section from [project-management:DEC-005-linking-and-containment] gains a **typed line** the validator can parse:

```markdown
## Dependencies

Blocked by: #142
Blocked by: ai-platform-incubation/agentic-user-journey#27
```

Prose narrative may follow the typed lines. The validator extracts the typed lines into a parseable graph; the prose stays for human context.

### Ready-frontier reporter

A new verb-subject script reads:
- The open-issue set + their lane labels (code-surface state)
- The typed `Blocked by:` graph (sequence state)

…and surfaces the **ready frontier** — the set of open issues whose lane is free AND whose blockers have all closed. Output: table, JSON, both (TBD).

### Lane lifecycle — leaner than DEC-018

Workstreams ship eight lifecycle scripts (add / rename / merge / split / edit / remove / show / list). Lanes ship a leaner set at v1:

| Verb | Purpose |
|---|---|
| `add-lane` | Add a lane to `lanes.yaml` + create the `lane:<slug>` label |
| `remove-lane` | Remove a lane; refuse if any issue still uses the label unless `--force` |
| `list-lanes` | List declared lanes; surface occupancy from open-issue scan |
| `show-lane` | Read-only view of one lane entry |

`rename-lane`, `merge-lane`, `split-lane`, `edit-lane` are deferred — lanes are ephemeral by intent; the rename/merge/split operations on a workstream taxonomy don't translate. Recurrence (COR-007) promotes the deferred verbs if needed.

## Open questions — evidence sought

Promotion to `accepted` requires answering each of these from lived experience during the manual-discipline phase. Field notes accumulate in the source scratchpad (`.pkit/scratchpad/active/2026-05-26-parallelization-primitive.md`) until the DEC flips.

1. **In-flight state mechanism.** Computed from what? Candidates:
   - Issue state machine (`in_progress` from [project-management:DEC-006-state-machine-and-cascade])
   - Presence of a linked draft PR
   - Non-null assignee
   - Explicit `in-flight: true` label
   - Some combination
2. **Cardinality.** One lane per issue (mirrors workstream's mutual-exclusion), or multi-lane (an issue touching two code areas locks both)? Multi-lane gives accurate locking but explodes the "is anything ready?" query.
3. **Axis placement.** Does `lane` join [project-management:DEC-012-classification-axes]'s three axes as a fourth axis (type, priority, workstream, lane), or live outside the classification model as a lifecycle marker (similar in spirit to milestone — orthogonal to the axes)?
4. **`Blocked by:` validation shape.** Patterns the validator accepts: `#N` only, `owner/repo#N` for cross-repo, both? How does it interact with native sub-issues (a child of an unclosed parent is implicitly blocked; should we even need to type it)?
5. **Lane attribute model.** Stick with slug + description, or grow toward DEC-018's 5-attribute shape if lanes prove less ephemeral than expected?
6. **Ready-frontier command name + output.** `pkit project-management parallel-status` / `next` / `frontier`? Table / JSON / markdown? What columns?
7. **Interaction with milestones / time-containers.** Does the active milestone gate the parallel frontier (issues outside the current milestone excluded from the ready set)?
8. **Cross-repo dependencies (DEC-022 mesh).** Does the Blocked-by graph cross repo boundaries? If yes, how does the ready-frontier reporter resolve cross-repo state?
9. **Lane lifecycle scope.** Do `rename-lane` / `merge-lane` / `split-lane` / `edit-lane` ship at v1, or stay deferred per COR-007?
10. **Promotion success criterion.** How many parallel-issue weeks of manual-discipline operation count as enough lived data to flip the DEC? What signals close the question?
11. **In-flight detection in board mode.** Label-substrate adopters detect lane occupancy from `lane:*` labels on open issues. Board-substrate adopters might use a board-state field instead. Does the primitive support both, or require label substrate? (Working assumption: label-substrate-only since lanes are ephemeral — but evidence might force otherwise.)

## Rationale (provisional)

The two-conflict shape — code-surface (static, geography) vs sequence (dynamic, outcome) — comes from how parallel work actually fails in practice: either two PRs touch the same files and merge-conflict, or one PR depends on another's outcome and starts too early. Adopters don't conflate these in conversation ("we can't run those at the same time because they touch the same surface" vs "B can't start until A lands"); the primitive shouldn't conflate them either.

The additive choice (separate `lane:*` series rather than re-cutting `workstream:*`) was forced by shared-board substrate. The full analysis lives in the source scratchpad. The decision here is: lanes are operationally distinct from workstreams; the methodology gives each its own substrate and lifecycle.

The leaner lane lifecycle (4 verbs vs workstream's 8) reflects the ephemeral-by-intent design. Rename / merge / split are taxonomy operations; ephemeral lock domains don't typically need them. COR-007 promotes when recurrence forces.

The "DEC-005 typed-line extension" preserves the existing prose substrate (no breaking change for adopters who use `## Dependencies` informally) and adds a parseable layer on top. Two adoption modes — informal-prose + typed-line — coexist until typed-line is ubiquitous.

### Alternatives considered

- **Overload `workstream:` as code-area lanes.** Rejected — breaks DEC-018's semantic; workstream renames break the lane partition; monorepos with cross-cutting libraries have nowhere to land.
- **Lanes only (no Blocked-by extension).** Rejected — covers code-surface but not sequence conflict; the ready-frontier query is half-blind.
- **Typed Blocked-by only (no lanes).** Rejected — covers sequence but not code-surface conflict; same half-blindness in the opposite direction.
- **Full primitive — lanes + typed Blocked-by + ready-frontier reporter.** Recommended at v1 endpoint (this DEC's design).
- **Manual discipline only — diligent prose convention + manual coordination, no methodology surface.** The bridge. Adopters run the manual discipline now while authoring this DEC; the field notes are the empirical input that promotes the full primitive.

## Implications (provisional)

- **Acceptance gate.** Per [.pkit/rules/core.md] rule 2, implementation work citing this DEC is forbidden until the DEC flips to `accepted`. The IGW and project-kit adopters run the manual discipline in the interim.
- **DEC-005 refinement** — when this DEC flips to accepted, DEC-005 grows a "Typed Blocked-by lines" subsection cross-referencing this DEC. Schema bumps for `body-format.yaml`.
- **DEC-012 axis-model decision** — open question 3 will either add a fourth axis or place lanes outside the axis model. Either path updates DEC-012.
- **New schema: `project/lanes.yaml`**. Optional file; absence equals no lanes; pre-check.py validates when present.
- **New scripts.** `add-lane`, `remove-lane`, `list-lanes`, `show-lane`, plus the ready-frontier reporter. Each lifecycle script uses the `_lib/gh.py` helper from [project-management:DEC-023-gh-host-and-owner].
- **No interaction with hooks at v1.** DEC-024's hook events do not include lane lifecycle events. If lane lifecycle hooks become useful, recurrence (COR-007) adds them later.
- **Mesh interaction.** Lanes are repo-local by design — ephemeral, code-area-bound. [project-management:DEC-022-methodology-mesh]'s `check-mesh.py` ignores `lanes.yaml`. The Blocked-by graph crossing repo boundaries is open question 8.
- **Versioning.** Lane primitive + Blocked-by typed extension are surface changes; the implementation PR (when DEC flips to accepted) bumps the capability's version per PRJ-002 + the pm capability's bump policy.

## Source scratchpad

`.pkit/scratchpad/active/2026-05-26-parallelization-primitive.md` — captures the etymological analysis (workstream vs lane), the field notes section (currently empty), the substrate-veto argument against re-cutting DEC-018, and the manual-discipline → crystallised-primitive promotion plan. The scratchpad retires per [COR-012] when this DEC flips to `accepted`.
