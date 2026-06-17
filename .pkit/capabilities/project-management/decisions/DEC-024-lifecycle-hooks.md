---
id: DEC-024
title: Lifecycle hooks — declarative post-action steps in adopter config, fired by the engine after pm lifecycle events
status: accepted
date: 2026-05-27
author: Ales Kalfas
---

## Context

Real adopters perform **repeatable GitHub state changes** after every pm lifecycle event. The IGW trigger case is concrete: every issue filed in the repo should have its board `Workstream` field set to `Spyre`. Every time. No per-issue judgement. Without a methodology primitive, the adopter wraps `pkit project-management create-issue` in personal shell glue that follows up with `gh project item-edit --field-id ... --single-select-option-id ...`. That wrapper is repetitive, adopter-private, brittle, and — most importantly — re-creates the wrapper-shell-glue problem the verb-subject contract ([project-management:DEC-020-methodology-as-executable-commands]) exists to eliminate.

The board-field case is the trigger; the shape generalises. Adopters in the wild already want all of:

- Set a board single-select field to a fixed value after `create-issue`.
- Post a templated comment after `close-issue` (e.g., notify a Slack channel).
- Assign a default milestone based on issue type at `create-issue`.
- Request review from a fixed reviewer set after `open-pr` (when CODEOWNERS doesn't cover the case).
- Update a custom board field after `move-issue` reflects a state change.

The mechanism — *lifecycle event + declarative action* — is the primitive worth shipping; the specific cases are illustrative, not enumerable. [COR-007] (pattern extraction) names the recurrence: the bespoke wrappers are the signal that justifies promotion from project-local convention to capability primitive.

The methodology has already accepted that adopter-portable configuration is the substrate ([project-management:DEC-017-prerequisites-bootstrap-migrate-discipline]). Hooks belong in that substrate: declared in the adopter's `project/` namespace, machine-readable, validatable, and consumed by the engine each time a lifecycle event fires.

## Decision

The capability ships a **declarative lifecycle-hook mechanism**: adopters declare post-action steps in a kit-known file; the engine fires them after the primary operation lands.

### File location — `project/hooks.yaml` (separate from `config.yaml`)

Hooks live in a dedicated `project/hooks.yaml` rather than inside `config.yaml`. Three reasons:

1. **Bounded growth.** Adopters may declare many hooks; a separate file matches the same separation as `project/workstreams.yaml` ([project-management:DEC-018-workstream-taxonomy-and-lifecycle]) and `project/lanes.yaml` (forthcoming).
2. **Lifecycle separation.** Hooks change for different reasons than `gh:` / `default_branch:` / milestone categories; a separate file makes the diff easier to review.
3. **Optional file.** Adopters with no hooks keep working with no `hooks.yaml` at all. Absence equals zero declared hooks.

### Shape

```yaml
schema_version: 1

hooks:
  after_create_issue:
    - kind: set-board-field
      field_id: MDI2OlByb2plY3RWMlNpbmdsZVNlbGVjdEZpZWxkMTA5MzE2NQ==
      single_select_option_id: 2e106694   # Spyre
  after_close_issue:
    - kind: post-comment
      template_path: project/hook-templates/close-comment.md
```

The top-level `hooks:` map keys are lifecycle event names; each value is an ordered list of hook entries. Each entry's required field is `kind:`; the remaining fields are kind-specific and validated by the per-kind schema.

### Lifecycle events at v1

| Event | Fires |
|---|---|
| `after_create_issue` | After the issue exists on GitHub *and* is added to the board (per DEC-019) |
| `after_close_issue` | After the issue is closed in either `wont-do` or `pr-merge` mode |
| `after_open_pr` | After `gh pr create` succeeds |
| `after_merge_pr` | After the merge completes and cascades land |
| `after_move_issue` | After a state transition lands (per DEC-006) |

`before_*` hooks are deferred — they can block the primary operation and introduce a distinct failure mode. Add later if recurrence justifies.

### Hook kinds at v1

The capability ships three declarative kinds plus a custom-script escape hatch. Each kind has a JSON schema at `schemas/hook-kinds/<kind>.schema.json`:

| Kind | Purpose |
|---|---|
| `set-board-field` | Set a Projects v2 single-select or text field on the just-created/moved item |
| `post-comment` | Post a comment from a template file (renders `{{ issue.number }}`, `{{ issue.title }}`, etc.) |
| `assign-milestone` | Set the issue's milestone by title (resolved at fire-time) |
| `custom-script` | Run an adopter-supplied script at a declared path with a fixed env-var envelope |

Additional kinds land per [COR-007] when recurrence forces them.

### Failure semantics — report-and-continue

When a hook fails *after* the primary operation has succeeded, the CLI:

- Reports the hook failure to stderr with the hook's index, kind, and exit reason.
- Exits **0** (the primary operation succeeded; the partial state is logged, not propagated to the exit code).
- Records the failure in a structured log line the agent can read.

Rollback is **not** attempted. Deleting an issue because a follow-up comment template failed produces worse partial states than leaving the issue in place with a logged warning.

This contract applies uniformly to all kinds.

### Idempotency

- Each kind declares `idempotent: true|false` in its schema. Kit-shipped kinds are idempotent (`set-board-field` writes the same value; `post-comment` checks for an existing comment with the same template stamp; `assign-milestone` is a no-op when already set).
- `custom-script` runs with `PKIT_HOOK_REPLAY=true` in its env when re-fired, so the script can detect replay and short-circuit.

### Ordering — serial in declared order

Hooks for a given event fire in the order they appear in `hooks.yaml`. No parallelism at v1. The same kind may appear multiple times in one event's list.

### Validation timing — three checkpoints

1. **Schema validation** (`pre-check.py`): the `hooks.yaml` file is parsed; each entry validates against its kind's schema; unknown kinds warn.
2. **GitHub-state validation** (`bootstrap.py`): for kinds that reference live state (`set-board-field` field IDs, `assign-milestone` titles), bootstrap resolves them against the configured host/owner from [project-management:DEC-023-gh-host-and-owner] and fails-fast if a reference doesn't exist.
3. **Fire-time** (lifecycle scripts): the engine catches resolution failures at fire-time as the safety net — useful when the live state changes between bootstrap and the next CLI invocation.

### Dry-run

When a lifecycle script accepts `--dry-run`, it lists the hooks that would fire — one line per hook, in declared order, with the resolved arguments. No GitHub calls are made.

### Mesh interaction (DEC-022)

Hooks are **adopter-private** by design. `check-mesh.py` ignores `hooks.yaml` entirely. Two peers in the same mesh may declare wildly different hooks without surfacing as drift. Hooks are operational, not methodology-canonical state.

### Distinction from GitHub Actions

Hooks fire **synchronously** within the CLI invocation. GitHub Actions react **asynchronously** to GitHub-side events (`issues:opened`, `pull_request:closed`). Use a hook when the follow-up should appear atomic with the CLI command. Use a GitHub Action when the response is observation-driven (e.g., "label every external-contributor PR"). The capability's adopter-facing doc states this distinction.

## Rationale

The B5 shape (kit-shipped declarative kinds + `custom-script` escape hatch) gives the methodology two adoption paths without forking. Most use cases collapse onto the kit-shipped kinds — greppable, validatable, mesh-explainable. Novel cases that don't fit any kit kind use `custom-script` and the adopter accepts the trade-off (loses kind-level validation and dry-run readability; gains arbitrary flexibility). Recurrence on `custom-script` is the signal that promotes the next kit-shipped kind.

Putting hooks in `hooks.yaml` rather than `config.yaml` matches the existing pattern (`workstreams.yaml` is also separate) and keeps each file's reason-to-change orthogonal. The schema bump applies to `hooks.yaml` independently of `config.yaml`.

Report-and-continue is the only safe failure mode for synchronous post-actions. Rollback is dangerous (the primary state is already on GitHub; deleting it creates worse partial states than logging). Failing the overall command exit code would discourage adopters from declaring hooks at all (one flaky hook makes every issue creation "fail" from the agent's perspective).

Three-stage validation (schema → bootstrap → fire-time) catches the most common drift sources at the earliest possible checkpoint. Fire-time validation is the safety net, not the primary defense.

### Alternatives considered

- **B1 (declarative kinds only, no escape hatch).** Rejected — adopters with novel needs fall back to wrappers, and the methodology has no way to absorb the recurrence. The escape hatch is what makes B5 viable as a v1 endpoint.
- **B2 (adopter-supplied scripts only, no declarative kinds).** Rejected — the entire mechanism becomes imperative glue with kit-supplied envelope. Loses the declarative-validation, dry-run-readability, and greppability benefits. Recurrent kinds never get promoted because every adopter writes their own.
- **B3 (kit-shipped kinds only, no escape hatch).** Rejected — leaves novel cases stranded; adopters write wrappers around `pkit` invocations to do what the hook should have done, which re-creates the very glue this DEC eliminates.
- **B4 (status quo, no methodology surface).** Rejected — fails [COR-007]; the recurrence is real and adopter-experienced.
- **`config.yaml`-inline hooks.** Rejected — for adopters with many hooks the inline form gets unwieldy; mixed reason-to-change with `gh:` / `default_branch:` / milestone categories makes review noisier; doesn't match the existing `workstreams.yaml` separation.
- **`before_*` hooks at v1.** Deferred — blocks the primary operation; introduces a distinct failure mode (the hook *prevents* the op); recurrence isn't there yet. Re-evaluate when v1 lands.
- **Rollback on hook failure.** Rejected — produces worse partial states than report-and-continue. The primary state on GitHub is real and observable; rolling it back can cascade unpredictably.
- **`when:` predicates at v1.** Deferred — per-classification scoping is real demand ("set Severity=high only for type:bug") but adds a predicate-language surface that should be settled separately. v1 hooks fire unconditionally on the lifecycle event; conditional logic uses `custom-script` until recurrence justifies a kit-shipped predicate language.

## Implications

- **New file at adopter side.** `project/hooks.yaml` is optional; absence equals no hooks. Schema validation runs only when the file exists.
- **New schemas.** `schemas/hook-kinds/<kind>.schema.json` for each kit-shipped kind (`set-board-field`, `post-comment`, `assign-milestone`, `custom-script`). The discovery contract — engine reads all schemas in the directory — lets a future PR add a kind without touching the engine code path.
- **Engine extension.** A new `_lib/hooks.py` module provides `fire_hooks(event: str, context: dict, config: dict) -> list[HookResult]`. Each lifecycle script calls it at the end of its happy path. The module imports `_lib/gh.py` from [project-management:DEC-023-gh-host-and-owner] for any `gh` shell-outs.
- **Verb-subject script signature unchanged.** The hook fire is internal; the script's exit-code contract from [project-management:DEC-020-methodology-as-executable-commands] stays the same.
- **`pre-check.py` extension.** Adds `hooks.yaml` schema validation and per-kind shape validation. Surfaces unknown kinds, missing required fields, malformed values. Read-only diagnostic.
- **`bootstrap.py` extension.** Resolves live references (board field IDs, milestone titles) once at install / re-bootstrap time. Fails-fast with remediation hints.
- **Dry-run impact.** Lifecycle scripts that already accept `--dry-run` add a "would fire" listing in their dry-run output. Scripts that don't accept `--dry-run` today don't get it for free; that's tracked separately.
- **Schema addition is additive.** No migration script needed at the capability-tier — pure addition per rule 7. The `hooks.yaml` file is optional; absence preserves all current behaviour.
- **Doc impact.** The capability's adopter-facing README gains a "Hooks" subsection: the file format, the kit-shipped kinds, the GitHub Actions distinction, the failure model. Per [project-management:DEC-015-doc-update-obligations].
- **`custom-script` envelope.** Adopters' scripts receive a fixed set of env vars: `PKIT_HOOK_EVENT`, `PKIT_ISSUE_NUMBER` (or `PKIT_PR_NUMBER`), `PKIT_REPO`, `PKIT_HOOK_REPLAY`, `PKIT_DRY_RUN`. The envelope is part of the capability's contract; changing it is a breaking change.
- **Mesh integration.** `check-mesh.py` ignores `hooks.yaml`. Hooks are not methodology-canonical state, so divergence between peers is by design.
- **Recurrence-driven kind additions.** New kit-shipped kinds land per [COR-007] when adopters' `custom-script` hooks repeatedly implement the same pattern. The capability owner reviews `custom-script` usage across adopters periodically.
- **Versioning.** The hook mechanism is a surface change; the implementation PR bumps the capability's version per PRJ-002 + the pm capability's bump policy.
- **Builds on [DEC-023].** Hook execution that calls `gh` (any kit-shipped kind, plus `custom-script` invocations that the envelope hands a configured-gh context) uses the helper introduced in DEC-023. Hooks ride DEC-023's adopter-portability gain.
