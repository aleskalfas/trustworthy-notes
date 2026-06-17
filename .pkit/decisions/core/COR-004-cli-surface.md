---
id: COR-004
title: CLI command surface
status: accepted
date: 2026-05-05
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

COR-001 settled the three steady-state mechanisms (propagation, extension, suspension) and the seed delivery operation. COR-002 added merge as a second delivery operation. COR-003 captured the principles by which a new artifact is assigned a mechanism + delivery.

What none of those say is *how a project actually invokes* these operations, and which design rules govern the CLI that exposes them. The current command list is reference material — it grows as bundles surface new gestures and new areas earn their own commands. That list lives in `.pkit/cli/README.md`. The design rules behind it are this record.

This record settles those rules. It does not settle:

- The CLI's binary name (a PRJ-side decision in the implementing project).
- Implementation language, framework, or distribution channel (PRJ).
- The current set of commands, their flags, or output formatting — those live in `.pkit/cli/README.md` as that area's specification.

## Decision

The CLI's shape is governed by the principles below. They constrain how the command list grows and what guarantees each command must provide.

### Each command anchors to one mechanism or operation

A command performs one of: propagation, seed, merge, suspension management, validation, or read-only introspection. It does not compound two of these into one verb. Compound verbs (e.g., an "update" that does sync + merge + migrations) hide which contract is being invoked, conflate consent profiles, and resist the manifest-level reasoning the install/sync runtime needs. New commands earn inclusion by representing one operation cleanly.

### `sync` and `merge` stay separate

Both are mutating operations a project may want to invoke independently. They have *different consent profiles*: sync silently overwrites core-owned paths (the project consented to the overwrite contract by adopting the methodology); merge prompts and appends on project-owned paths (project content is at stake on every run, per COR-002). Folding them into one verb either leaks the silent-overwrite contract onto project-owned files or makes routine refresh interactive. They are different verbs because they encode different consent.

### `init` is one-shot, not idempotent

The first-install command runs propagation, then seed, then merge, in that order. Once a project is initialised, that command refuses to run again. Recovery from partial or broken state flows through `validate` plus targeted `sync` / `merge` instead. Re-running first-install would either resurface seeded content (violating COR-001's seed contract) or silently skip already-seeded paths (confusing). Keeping the contract sharp is worth the small upfront refusal.

### `--dry-run` is universal on every mutating command

Any operation a project might want to preview before committing should be previewable through one consistent flag. A single convention reduces surprise about which commands support it and what the flag means.

### Failure mode is forward-only

A failed run leaves the project at a known partial state, with `validate` as the recovery entry point. There is no transactional rollback across the manifest. At this scale, transactional semantics would require a journal or filesystem snapshots — heavy infrastructure for a small set of file mutations. Forward-only with a reliable diagnostic is sufficient.

## Rationale

**Why principles, not the command list.** The list of commands evolves as bundles surface new verbs and new areas earn their own gestures. Pinning the list inside a decision record forces an amendment per change and conflates "what we decided about CLI design" with "what the CLI currently exposes." The principles are durable; the spec changes; they belong in different places. (Same separation as COR-003 vs the per-area manifest.)

**Why anchor each command to one operation.** The mechanism vocabulary of COR-001 / COR-002 already names the operations a project cares about. A CLI that mirrors them gives the project a shape it can reason about — sync is propagation, merge is merge, etc. Compound verbs would create a parallel vocabulary that drifts from the mechanism vocabulary and re-encodes consent contracts in opaque names.

**Why the sync/merge separation matters more than "they're different operations."** The deeper reason is consent. The no-shared-files invariant (in `.pkit/decisions/README.md`), COR-001, and COR-002 between them encode different consent contracts for different file ownership classes. A CLI verb represents an *adopter-visible* contract; conflating verbs across consent classes is the same shape of error as conflating the underlying mechanisms.

**Why first-install is sharp rather than smart.** The temptation is to make first-install "smart" — re-runnable, recovery-aware, repair-mode-on-broken-state. The cost is conceptual: it then has to know which paths it can resurface (none, per the seed contract) and which it cannot. Pushing recovery into `validate` plus targeted commands keeps the first-install contract one sentence long.

### Alternatives considered

- **Spec the command list inside this record.** Rejected — inventory pinned in a decision forces amendments per addition. The reference doc owns the list.
- **Skip the CLI COR entirely; let the spec doc carry both spec and rationale.** Rejected — design rationale tends to get lost inside spec docs. Decision records are where "why we did it this way" stays visible.
- **One smart `update` verb that picks sync / merge / migration as needed.** Rejected — see anchoring rationale; conflates consent profiles.
- **Transactional rollback on failure.** Rejected — heavy infrastructure for small mutations; forward-only with diagnostic is enough at this scale.

## Implications

- The current command list lives in `.pkit/cli/README.md` (propagation; synced). Each command's documentation references back to whichever principle here justifies its shape, where the link is non-obvious.
- Adding a new command means identifying the operation it represents (anchored to one mechanism / delivery / read-only gesture), naming it accordingly, and documenting it in `.pkit/cli/README.md`. No COR amendment unless a principle itself changes.
- New mechanisms or delivery operations introduced by future CORs may surface as new top-level commands; the principles here govern that surfacing.
- Subcommand groupings are a spec-doc concern unless a grouping touches a principle (e.g., a sub-verb that combined sync + merge would hit the anchoring rule).
- The CLI's binary name is the natural follow-on PRJ decision in the implementing project's corpus.
