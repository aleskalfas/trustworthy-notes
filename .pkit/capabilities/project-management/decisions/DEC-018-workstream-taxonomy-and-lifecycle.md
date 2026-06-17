---
id: DEC-018
title: Workstream taxonomy and lifecycle — semantics, attributes, storage, naming, active-use rules, lifecycle operations
status: accepted
date: 2026-05-24
author: Ales Kalfas
---

## Context

[project-management:DEC-012-classification-axes] establishes Workstream as one of three classification axes (Type, Priority, Workstream), with values declared by the adopter and substrate varying by board presence (Projects v2 single-select field with a board; `workstream:*` label without). DEC-012 stops at that statement. Real adoption immediately surfaces gaps:

1. **Semantic ambiguity.** "Workstream" is project-specific in DEC-012, but how project-specific? A team using portfolio-scale workstreams (`Agent Platform`, `Storage`) faces different choices than a single-product team using sub-area workstreams (`capabilities`, `schemas`, `cli`). DEC-012 doesn't resolve which.
2. **No attribute model.** A workstream is more than a slug. Lifecycle requires status (active / deprecated), human-readable name, description, and an audit trail for deprecations. DEC-012 says nothing about these.
3. **No storage shape.** Where do workstreams live? In `config.yaml` as a bare list? In a separate file? With what naming + validation rules? DEC-012 leaves this open.
4. **No lifecycle operations.** Workstreams are introduced, renamed, merged, split, retired over a project's life. Without a kit-shipped contract for these operations, every adopter improvises — and the resulting state drifts.
5. **No cross-repo coordination story.** Multi-repo teams need workstream consistency across repos. DEC-012 mentions board-level cross-repo alignment but stops there.

Real-world prior art exists: **ai-platform-incubation** manages workstreams as a `ProjectV2SingleSelectField` on its org-level Team Planning board with five values (`Spyre`, `llm-d`, `Agent Platform`, `Storage`, `Kagenti`); the `portfolio` repo mirrors the taxonomy as top-level directories. The naming is currently inconsistent — `Agent Platform` (title-case, space) vs `llm-d` (lowercase, hyphen) — which is exactly the kind of drift a kit-shipped contract prevents.

This DEC pins the v1 workstream-management contract: semantics, attributes, storage shape, naming rules, active-use rules, lifecycle operations, authority. Cross-repo coordination is delegated to [project-management:DEC-022-methodology-mesh].

## Decision

A workstream is a long-lived domain area; the capability ships a five-attribute model + a dedicated storage file + naming rules + eight lifecycle commands + a membership-gated authority model. Cross-repo workstream coordination is the methodology-mesh's job, not workstream-specific.

### Semantic definition

**A workstream is a long-lived domain area the project (or portfolio) invests in over multiple outcomes.** Stable in time; coarse-grained; distinct from EPIC. An EPIC scopes a single outcome inside a workstream; a workstream is the durable container the EPIC sits in.

Granularity depends on scale:

- **Portfolio-scale projects** — workstream = product / project area (`Agent Platform`, `Storage`).
- **Single-product projects** — workstream = sub-area within the product (`capabilities`, `schemas`, `cli`).

Both are valid; the v1 contract doesn't enforce a granularity. The conventional pairing of `slug` and `name` (per the naming rules below) makes the granularity choice visible.

### Per-workstream attributes

Five attributes per workstream:

| Attribute | Required? | Purpose |
|---|---|---|
| `slug` | Yes (mapping key) | Kebab-case stable ID; cross-references key off this. |
| `name` | Yes | Human-readable; may carry spaces / mixed case. Defaults to `slug` if omitted. |
| `description` | Recommended | One-line prose. May be empty. |
| `status` | Yes (default `active`) | `active` or `deprecated`. |
| `deprecated_reason` | Optional (encouraged when status=deprecated) | Audit prose; cites successor workstream or migration manifest entry. |

Deferred to future refinements per COR-007: `owner`, `parent` (hierarchy), `portfolio_doc`, `color`, `aliases`, `created_at` / `deprecated_at` timestamps.

### Storage shape and location

Workstreams live at **`.pkit/capabilities/project-management/project/workstreams.yaml`** — a dedicated project-side file, not mixed into `project/config.yaml`. Separate file means distinct lifecycle, clean diffs, and a clear place to point cross-repo coordination at.

The file accepts two forms — a mapping form for entries with attributes, and a list-form shorthand when every entry would be slug-only:

```yaml
# Mapping form — canonical for entries with attributes
schema_version: 1
workstreams:
  capabilities:
    name: capabilities
    description: Capability authoring + lifecycle.
    status: active
  agent-platform:
    name: Agent Platform
    description: The Kagenti agent platform product area.
    status: active

# Shorthand — when every entry is slug-only with default status
schema_version: 1
workstreams:
  - capabilities
  - schemas
  - cli
```

**Source of truth — file-canonical; board projection.** For board-substrate adopters per DEC-012, the `add-workstream.py` / `rename-workstream.py` / `merge-workstream.py` scripts sync the file to the board's Workstream single-select field. The file is authoritative; the board reflects it.

A kit-shipped **`schemas/workstreams.schema.json`** validates the file against the attribute and naming rules. The schema ships as a same-PR-as-surface-change discipline per [project-management:DEC-017-prerequisites-bootstrap-migrate-discipline].

### Naming and value-space rules

| Field | Rule |
|---|---|
| `slug` (map key) | Matches `^[a-z][a-z0-9-]*[a-z0-9]$`; 2–40 chars; no consecutive hyphens. |
| `name` | Non-empty; ≤ 64 chars; no newlines. |
| `description` | Optional; ≤ 200 chars; no newlines. |
| `status` | `active` (default) or `deprecated`. |
| `deprecated_reason` | Optional; ≤ 200 chars; no newlines. |

Uniqueness: slug uniqueness is enforced by the mapping key. The validator emits a warning on duplicate `name` across active workstreams (legitimate per-entry overlap is rare; surfacing it forces an explicit decision).

Not allowed at v1: hierarchy (no slashes in slugs); per-entry aliases (use migration manifest history); a reserved-slug list.

Style conventions — informational, not enforced by the schema:

- **Single-product projects**: `slug == name` (kebab-case throughout).
- **Portfolio-scale projects**: `name` is title-case with spaces; `slug` is the kebab-case derivation.

### Active-use rules on issues

| Sub-question | Decision |
|---|---|
| Cardinality | Mutually exclusive — one workstream per issue. |
| Required at filing? | Warning at filing; hard-reject at close. |
| Inheritance from parent | Inherit-with-override; closest-ancestor wins on conflict. |
| Cross-cutting work | No methodology-special handling. An adopter that genuinely has cross-cutting work declares a `cross-cutting` workstream value. |

The cardinality + close-time hard-reject mirrors DEC-012's existing `[validation-severity:hard-reject]` for missing classification at close, while keeping the filing experience permissive (a warning lets the filer move on; the closer fixes it before completion).

### Lifecycle operations — eight verb-subject scripts

Per [project-management:DEC-020-methodology-as-executable-commands], every lifecycle operation ships as a verb-subject script under `scripts/`. All eight inherit the script discipline from DEC-017 + DEC-020 (PEP 723, schema-driven, deterministic, exit codes are the contract, context header at startup, membership predicate at startup).

| Op | Script | Migration manifest? | Hard gates |
|---|---|---|---|
| Add | `scripts/add-workstream.py` | No | Validates slug + schema; runs `bootstrap.py` + `pre-check.py` inline. |
| Rename (slug) | `scripts/rename-workstream.py` | Yes (`kind: label-rename`) | Validates new slug; verifies old + new label state; per-change confirmation in interactive shell. |
| Edit (name / description / status / deprecated_reason) | `scripts/edit-workstream.py` | No | Validates; confirmation only on status flips. |
| Merge | `scripts/merge-workstream.py` | Yes (`kind: label-merge` — new primitive) | Explicit survivor must exist; per-loser issue count surfaced; per-change confirmation. |
| Split | `scripts/split-workstream.py` | Yes (`kind: workstream-split` — new primitive) | 2–5 new slugs; interactive per-issue triage loop; reference rewriting opt-in (filesystem + GitHub bodies via `--include-github-bodies`). |
| Remove | `scripts/remove-workstream.py` | Yes (`kind: label-delete`, `refuse_if_used: true`) | Zero-issues precondition; type-the-slug confirmation prompt. |
| Show | `scripts/show-workstream.py` | No | Read-only. |
| List | `scripts/list-workstreams.py` | No | Read-only. |

Two new migration primitives ship in the same surface-change PR that lands the lifecycle commands, per DEC-017's same-PR-as-surface-change discipline (which means `schemas/migrations.yaml` bumps its `schema_version`):

- **`label-merge`** — re-tag issues from loser to survivor; delete loser label. The semantic counterpart of `label-rename` for the merge case.
- **`workstream-split`** — captures the structural split event; per-issue retag is the script's interactive responsibility, not the manifest's. The manifest records that the split happened; the migration's user-facing flow is the interactive triage loop.

**Reference rewriting on rename / merge / split:**

- Default-on for merge (the survivor's slug is unambiguous).
- Opt-in for split (`--include-github-bodies`); the primary focus is per-issue triage, and bulk body rewrites without per-object confirmation are risky.
- Filesystem search looks for the typed forms `workstream:<slug>` and `[workstream:<slug>]`. Bare slugs are not rewritten — too many false positives.
- GitHub-bodies search covers issues + PRs + comments. Without admin permissions on the repo, the script skips others' comments and warns. There is no rollback for GitHub edits — re-run the operation to amend.
- Per-file and per-object confirmation by default. `--yes` flag opts into batch confirmation per the safety convention.

### Authority

Per [project-management:DEC-021-team-membership-gate], every workstream script invokes the membership predicate at startup. Open mode (no `members.yaml`) bypasses; closed mode refuses non-members with DEC-021's closed-mode refusal template.

Within the membership, all workstream ops are **PM-authority** per the DEC-008 role distinction — workstream taxonomy changes are coarse-grained, durable, and project-shaping decisions. The script trusts the invoker: no enforcement of "you must be PM" at the script layer (the role distinction is informational at v1 per DEC-021). The team's review process is the actual gate.

### Cross-repo coordination

Workstream-specific cross-repo logic is **deferred to [project-management:DEC-022-methodology-mesh]**. Two cases collapse cleanly:

- **Board substrate** — the board IS the shared substrate; no per-repo coordination is needed at the workstream layer.
- **Label substrate** — drift detection across team repos falls under the general mesh feature (mesh-check compares `workstream:*` labels across configured peers per DEC-022's scope section).

There is no workstream-specific `workstream_peers:` mechanism. Workstreams are a methodology axis like Type and Priority; cross-repo consistency for all of them is the mesh's job.

### Sequencing

The workstream lifecycle lands at **v0.5.0** per [project-management:DEC-020-methodology-as-executable-commands]'s rollout table. Predecessors:

- v0.3.0 — verb-subject convention + membership gate must exist for the workstream scripts to inherit from.
- v0.4.0 — broader issue + PR command surface so workstream filings have somewhere to land.

The PR landing v0.5.0 bumps `schemas/migrations.yaml`'s `schema_version` and ships the two new migration primitives in the same change-set (DEC-017 discipline).

## Rationale

**Why a single workstream definition rather than per-mode definitions.** Adopters fall into two modes (board / label-fallback) per DEC-012, and the temptation is to define workstreams differently for each. The semantic definition is mode-agnostic — both modes have the same kind of thing (long-lived domain area), with substrate differences hidden behind the file-canonical principle from the storage shape. The single definition keeps the methodology coherent; the substrate-specific projection is mechanical.

**Why mapping with shorthand fallback.** Most adopters start with slug-only workstreams and grow attributes over time. Demanding the mapping form up front imposes ceremony on the simple case; allowing only the list form denies the attribute model. The dual-form file with a clear "shorthand when applicable" rule serves both ends.

**Why eight scripts rather than a polymorphic `workstream.py`.** Each script has a different safety profile — `show` is read-only, `add` is additive, `rename` and `merge` are destructive on confirmation, `remove` is destructive with strict preconditions. The DEC-017 separation-by-file rationale applies: separate filenames carry separate disciplines unambiguously; flag-driven polymorphism conflates them.

**Why two new migration primitives now rather than wait.** Real workstream operations recur during normal team life (a workstream renames; two workstreams merge after a re-org). The `label-rename` + `label-delete` primitives from DEC-017 cover only the trivial cases. Authoring the workstream lifecycle without the merge / split primitives forces ad-hoc adopter procedures — exactly what DEC-017's "kit ships the primitives; adopters use them" intent rules out.

**Why cross-cutting work is *not* methodology-special.** Building methodology-special handling for "this issue spans workstreams" adds complexity for a case adopters can already express by declaring a `cross-cutting` workstream value. The mutual-exclusion cardinality stays clean; adopters who need this declare it.

**Why hierarchy is excluded at v1.** Hierarchy is the single most common feature request for taxonomies that don't have it, and it's also the single most common source of structural debt when added prematurely. The five attributes cover the common cases; hierarchy lands when a real adopter case forces it.

### Alternatives considered

- **Workstreams in `config.yaml` as a bare list.** Rejected — loses the attribute model; mixes lifecycles; no place for a `schema_version`.
- **Workstreams in a flat `workstreams.txt` (one slug per line).** Rejected — even simpler, but loses every attribute extension path.
- **Per-mode workstream definitions (one shape for board, another for labels).** Rejected — bifurcates the methodology over a substrate detail.
- **Polymorphic `workstream.py` with mode flags.** Rejected — conflates safety profiles per DEC-017's reasoning.
- **Hierarchy at v1.** Rejected per COR-007 — speculative; lands when a real adopter case forces it.
- **`alias:` field per entry for old-name support.** Rejected at v1 — the migration manifest is the audit trail; per-entry aliases duplicate that.

## Implications

- **A new file `schemas/workstreams.schema.json`** ships at v0.5.0 with the attribute + naming rules above.
- **`schemas/migrations.yaml`** bumps `schema_version` at v0.5.0 to introduce `label-merge` and `workstream-split` primitives. Migration script (per DEC-017's same-PR-as-surface-change discipline + COR-010) bridges installed adopters.
- **Eight verb-subject scripts** under `scripts/` (per the lifecycle operations table) ship at v0.5.0.
- **The capability `version:`** bumps to v0.5.0 on the implementing PR.
- **`pre-check.py`** gains a check for `workstreams.yaml` parsing + schema validity in the same PR.
- **`bootstrap.py`** in label-fallback mode reads `workstreams.yaml` (the file is the source of truth) and creates the `workstream:<slug>` labels from it. The DEC-012 behaviour of reading workstreams from `config.yaml` continues working in the interim (file absent → fall back to `config.yaml`); the same-PR migration completes the cutover.
- **The project-manager** invokes the workstream lifecycle commands; the user-facing intent ("add a new workstream for the Storage product area") routes to `add-workstream.py`.
- **Cross-repo workstream drift** lives in [project-management:DEC-022-methodology-mesh]'s scope; nothing workstream-specific ships for it.
- **Membership-gating** (DEC-021) applies to every mutating workstream script.
- **The `cross-cutting` workstream value** is an adopter convention, not a kit primitive. Adopters who declare it can use it like any other slug.
