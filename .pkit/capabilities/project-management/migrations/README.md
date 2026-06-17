# Capability migrations — project-management

This directory holds **versioned adopter-state migration manifests** per [project-management:DEC-017-prerequisites-bootstrap-migrate-discipline]. Each file declares the changes a specific capability version introduced to externally-observable state (labels, marker formats, body shapes) — the changes an adopter's GitHub state needs to reconcile with on upgrade.

The migrate script (`../scripts/migrate.py`) reads every file here, compares against the adopter's per-capability applied-migrations state, and walks the operator through the pending plan with **per-change confirmation gates**.

## When a manifest entry is required

A capability version bump that changes adopter-observable state — renames a label vocabulary value, deletes a value, changes a marker format, alters a body-shape required section — ships a manifest entry in this directory **in the same PR** as the methodology change. Mirrors COR-010's same-PR-as-surface-change discipline at the file level; this is the adopter-state analog.

A bump that **only** adds new state (a new `type:*` value introduced for the first time, a new optional body section) does **not** require a manifest entry. Bootstrap is the additive path; migrate is for renames and removals.

## File naming

```
migrations/<target-version>.yaml
```

The `<target-version>` is the capability `version:` this migration brings the adopter state up to. The script applies pending migrations in version order.

Empty for v0.2.0 (this version introduces the framework; no prior version exists to migrate from).

## Manifest shape

```yaml
schema_version: 1
target_version: 0.3.0     # the capability version this migration lands with
description: |
  Brief prose explaining the methodology change driving this migration
  and (when relevant) the upstream pm-workflow MET + commit SHA.
changes:
  - kind: label-rename
    from: type:maintenance
    to: type:chore
    re_tag_issues: true   # re-label issues currently using the old name
  - kind: label-delete
    label: workstream:legacy-bucket
    refuse_if_used: true  # if any issue uses it, refuse the delete; require manual cleanup first
  - kind: label-create
    name: type:security
    color: d93f0b
    description: Security-related work.
```

## Recognised `kind:` values (v0.2.0)

| `kind` | Effect | Confirmation |
|---|---|---|
| `label-rename` | Rename a label; optionally re-tag issues using the old name. | Per-rename (count of affected issues surfaced before confirming). |
| `label-delete` | Delete a label. If `refuse_if_used: true`, refuses when any issue references the label and instructs manual cleanup. If `refuse_if_used: false`, prompts with the issue count. | Per-delete; per-affected-issue when applicable. |
| `label-create` | Create a new label (used when a methodology evolution adds a value). Overlaps with bootstrap's additive path but is recorded here when the *introduction* is the migration. | Single confirm. |

More primitives land as actual migrations need them — per COR-007's pattern-extraction discipline. Candidates surfaced by future evolutions:

- `marker-format-rename` — rename the `Close trigger:` marker line shape or similar.
- `body-section-rename` — rename a required section heading across existing issues.
- `board-field-rename` — Projects v2 single-select field value rename.

## Adopter-side state file

The migrate script tracks which migrations have been applied via:

```
<adopter-root>/.pkit/capabilities/project-management/project/migrations-applied.yaml
```

Shape:

```yaml
schema_version: 1
applied:
  - version: 0.3.0
    applied_at: 2026-07-12T14:30:00Z
    by: <name> <<email>>
```

The script auto-creates the file on first run. Adopters do not author it by hand. The file is project-side (adopter-owned) and survives capability upgrades.

## Process discipline

Per [project-management:DEC-017-prerequisites-bootstrap-migrate-discipline]:

- Manifest entries are part of the capability's surface — the same PR that lands a methodology evolution requiring migration ships the corresponding manifest entry.
- The migrate script refuses to run when pre-check would fail — drift in basic prerequisites breaks migration plan computation.
- Per-change confirmation is the default; no batch `--yes` flag. CI-friendly via `--config <adopter-authored-pre-approval-file>`.
- Idempotent: re-running on already-applied migrations is a no-op.
- Never auto-chained from `pkit capabilities upgrade project-management` — explicit invocation only, so the adopter reads the plan before authorising.
