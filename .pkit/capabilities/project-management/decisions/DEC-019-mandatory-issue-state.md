---
id: DEC-019
title: Mandatory issue state — auto-add to board on filing and mandatory assignment, encoded in a new schema
status: accepted
date: 2026-05-24
author: Ales Kalfas
---

## Context

[project-management:DEC-012-classification-axes] mandates three classification axes per issue (Type, Priority, Workstream). Real adoption surfaces two more pieces of mandatory state that DEC-012 doesn't capture, and that don't fit the classification-axis shape:

1. **Auto-add to board.** For board-substrate adopters per DEC-012, an issue's classification (workstream / status / priority) lives on the board-item, not on the issue itself. An issue never added to the board has no classification — *"otherwise the issues are lost in board."* The methodology has to ensure every filed issue ends up on the configured board, and has to detect issues that bypassed the methodology (filed via the GitHub UI or raw `gh issue create`) and reconcile them.

2. **Mandatory assignment.** Every issue has an assignee. Someone is responsible. Today this is enforced informally; the methodology should encode it. The default at filing is the filer themselves; reassignment is open to any team member.

Neither rule is a classification axis — Auto-add-to-board is a substrate fact ("the issue exists on the board"), not a category; Assignment names a person, not a value from a constrained set. Encoding them as DEC-012 axes would distort both axes (one would be a boolean; the other would have unbounded values). They need their own home in the schema corpus.

A separate but adjacent failure mode this DEC also addresses: **per-pm-operation pre-check on every issue's state is too expensive**. Drift detection (an issue exists that isn't on the board; an assignee field is empty on a historical issue) is a periodic / post-event check, not an inline check. The enforcement model needs to distribute itself across the methodology's three-layer defence per [project-management:DEC-020-methodology-as-executable-commands] (commands at filing; post-check workflow on UI-mediated bypass; environment pre-check for drift), not stuff everything into pre-check.

## Decision

The capability ships a new **`schemas/mandatory-issue-state.yaml`** schema (with a JSON Schema companion) encoding required-but-not-classification state per issue. v1 records two entries: `assignee` and `board_membership`. Enforcement distributes across the three-layer defence per DEC-020.

### The new schema

`schemas/mandatory-issue-state.yaml` — v1 shape:

```yaml
schema_version: 1
required_fields:
  assignee:
    substrate: native-assignee-field
    required_on_every_issue: true
    multiplicity: one-or-more       # GitHub allows multiple assignees
    default_at_filing: filer
    values_constrained_to: members  # closed-mode per DEC-021; open in bootstrap
    missing_severity: "[validation-severity:hard-reject]"  # at filing
    drift_severity: "[validation-severity:warning]"        # on existing issues
  board_membership:
    substrate: projects-v2-board-item
    required_on_every_issue: true
    applies_when: "config.has_projects_v2_board == true"
    default_at_filing: auto-add-to-configured-board
    missing_severity: "[validation-severity:hard-reject]"  # at filing
    drift_severity: "[validation-severity:warning]"        # on existing issues
```

The schema is data-driven — new mandatory state lands as new entries under `required_fields:` (due dates, milestone-required, label-of-some-kind-required, etc.) without engine changes. Each entry pins its substrate (where the field lives — native field, board item, label, comment marker), required scope, default at filing, severity at filing vs on existing-issue drift. The validation-severity tokens reference [project-management:DEC-014-validation-severity-model]'s vocabulary per the cross-schema typed-token form (COR-019).

### Auto-add to board: three enforcement layers

For board-substrate adopters (`config.has_projects_v2_board == true`), three layers ensure every issue lands on the configured board:

| Layer | Trigger | Catches |
|---|---|---|
| `create-issue.py` | Methodology-mediated filing per DEC-020 | Issues filed through the methodology — auto-adds as the final step of issue creation. |
| Post-check workflow (kit-shipped GitHub Action template) | `issues.opened` / `issues.edited` events | Issues filed via the GitHub UI or raw `gh issue create` — bypasses the methodology. Posts a comment + status check; may auto-remediate by adding to the configured board. |
| `pre-check.py` | Adopter-invoked or scheduled | Environment health (board id resolves; labels exist; etc.) — **not** per-issue scanning. |

The three layers do not overlap. Per-pm-operation scanning of every issue's board state is explicitly out of scope.

**Multi-board adopters at v1.** A single default board declared in adopter config (`projects_v2_board_id: <N>`); per-invocation override at filing time via `create-issue.py --board=<N>`. Multi-board enumeration (multiple boards, board-per-workstream, etc.) is deferred per COR-007.

**Substrate scope.** The rule applies only to board-substrate adopters. Label-substrate adopters have no board to add to; the `applies_when` field gates the rule.

### Mandatory assignment

**Required at filing**, default-but-overridable. `create-issue.py` defaults the assignee to the filer (resolved per DEC-021's identity resolution); `--assignee=<github-login>` overrides; `--assignee=<login>,<login2>` allows multiple per GitHub's native multiplicity.

**Reassignment authority**: any current team member per the DEC-021 membership gate. In open mode (no `members.yaml`), anyone with repo access. No additional role check at v1.

**`validate-issue.py` checks**:

- Hard-reject at filing if assignee is missing (shouldn't happen given default-to-filer; the rule is the safety net).
- Warning on existing issues with no assignee (rare drift; legitimate when an issue predates the methodology).

**Methodologically NOT a classification axis.** Assignment names a person, not a category from a constrained set. The schema entry above captures this — `substrate: native-assignee-field`, `values_constrained_to: members`.

**Self-assignment shorthand.** `assign-issue.py 42 --me` is sugar for `--assignee=<my-resolved-github-login>`. `create-issue.py` defaults to filer = "me" implicitly when `--assignee` is omitted.

**Cascade interaction.** Assignment is stable across state transitions. A PR-merge close (per [project-management:DEC-006-state-machine-and-cascade]) does not auto-update the assignee to the PR author. The original filer stays on the hook unless explicitly reassigned.

### The post-check workflow template

A kit-shipped GitHub Action template at `templates/.github/workflows/pm-issue-check.yml` ships alongside the v0.6.0 enforcement. The template runs on `issues.opened` and `issues.edited` and:

- Reads `mandatory-issue-state.yaml` to know what to check.
- For each `required_field` entry, validates the issue against the rule.
- On `hard-reject` severity at filing, posts a comment + a status check failure; in `auto-remediate` mode (adopter-configured), invokes the analogous mutation (`gh project item-add`, etc.) to fix the issue.
- On `warning` severity for drift, posts a comment but lets the issue through.

The template is **adopter-installed**, not auto-deployed — adopters who want the post-check enforcement copy it from `templates/.github/workflows/` into their own `.github/workflows/`. The kit-shipped path is canonical; the adopter's copy is operational.

This three-layer model is the same shape pinned in DEC-020's three-layer defence; the post-check workflow template above is its concrete realisation for the mandatory-issue-state rules.

### Sequencing

The rules land at **v0.6.0** per the DEC-020 rollout table. Predecessors:

- v0.3.0 — `create-issue.py` + `validate-issue.py` + membership gate must exist.
- v0.4.0 — broader issue + PR commands (so `assign-issue.py` exists; so the validate / show / move surface is complete).
- v0.5.0 — workstream lifecycle (so the classification axes are fully encoded before adding more required state).

The v0.6.0 PR introduces:

- `schemas/mandatory-issue-state.yaml` + JSON Schema companion.
- `create-issue.py` updates (auto-add-to-board step; default-to-filer assignee).
- `assign-issue.py` (the verb-subject script for reassignment + the `--me` shorthand).
- `validate-issue.py` updates (assignee + board-membership checks).
- `templates/.github/workflows/pm-issue-check.yml` template.
- Capability `package.yaml` `version:` bump.

## Rationale

**Why a new schema rather than extending classification.yaml.** Classification axes are mutually-exclusive value sets — Type / Priority / Workstream pick a value from a fixed list. Assignment is unbounded over people; board membership is a substrate fact. Forcing these into the classification axis shape (e.g., a synthetic `assignee:<login>` label, or a `board:on` flag) distorts both axes (the assignee axis would have unbounded values; the board-membership axis would be a boolean) and bloats the classification model. A separate schema makes "this is mandatory state but not categorical" explicit and gives future mandatory-but-not-categorical state (due dates, milestone-required) a natural home.

**Why three enforcement layers rather than one universal pre-check.** Per-pm-operation pre-check that scans every issue is too expensive (a repo with thousands of issues makes every command slow) and conflates inline correctness with periodic health. The three-layer split from DEC-020 — commands at filing, post-check workflow on UI bypass, environment pre-check for drift — keeps each layer focused on a single concern. This DEC just realises that model concretely for the two v1 rules.

**Why default-to-filer for assignment.** It's the right default in the common case (the person filing has context to drive the work, or at least until reassigned). Making the assignee a hard-reject at filing without a sensible default would force every `create-issue.py` call to carry `--assignee`, which is needless ceremony for the 90% case.

**Why the post-check workflow is adopter-installed rather than kit-deployed.** GitHub Actions workflows live at `.github/workflows/` — a fixed adopter path that the no-shared-files invariant forbids the kit from writing to. The kit-shipped template lives at `templates/.github/workflows/`; the adopter copies it, optionally customises (auto-remediation toggle, comment template wording), and installs. This is the same pattern used for other adopter-installed workflow files in workflow bundles.

**Why warning severity for drift on existing issues.** Existing issues without an assignee, or never on a board, are usually historical — they predate the methodology adoption. Hard-rejecting them mid-flight would block transitions of legitimate issues for accidental reasons. The warning surfaces the drift; the operator fixes it deliberately.

**Why not auto-update assignee on PR merge.** The filer being responsible until explicitly reassigned matches normal team dynamics — work doesn't transfer to whoever happens to write the PR; transfer is a deliberate gesture (`assign-issue.py 42 --assignee=<login>`). Auto-changing the assignee silently would lose the original responsibility signal.

### Alternatives considered

- **Extend `classification.yaml` with assignee + board-membership entries.** Rejected — distorts both axes; classification = constrained value sets, these are not.
- **Single universal `mandatory-state.yaml` covering classification + new rules.** Rejected — would force a `classification.yaml` rewrite for no methodological benefit; the existing classification surface is already settled.
- **Per-pm-operation pre-check on every issue's state.** Rejected — too expensive; conflates inline correctness with periodic health.
- **Hard-reject on drift severity for existing issues.** Rejected — too disruptive; existing issues predate the methodology.
- **Auto-deploy the post-check workflow via the adapter.** Rejected — violates the no-shared-files invariant for fixed adopter paths. The template-and-copy pattern is the right shape.
- **Encode the schema in `validation-severity.yaml`.** Rejected — that schema's job is the severity vocabulary, not the data the severity tokens apply to.

## Implications

- **A new schema** `schemas/mandatory-issue-state.yaml` + JSON Schema companion ships at v0.6.0.
- **`create-issue.py`** updates: auto-add-to-board step for board-substrate adopters; default-to-filer assignee.
- **`assign-issue.py`** ships (the verb-subject reassignment script, with `--me` shorthand).
- **`validate-issue.py`** updates: adds the assignee + board-membership checks against the new schema.
- **`templates/.github/workflows/pm-issue-check.yml`** ships as a kit-shipped template adopters install.
- **The capability `version:`** bumps to v0.6.0 on the implementing PR.
- **`pre-check.py`** keeps its environment-scope focus — it adds checks for board-id resolution (already present per DEC-017) and for `mandatory-issue-state.yaml` parsing. It does not scan per-issue state.
- **The project-manager** invokes `create-issue.py` for filing and `assign-issue.py` for reassignment; the agent does not need to know the rules' details — the scripts enforce.
- **Adopters opt into auto-remediation by toggle** in the post-check workflow template. Default: comment-and-status-check. With `AUTO_REMEDIATE: true`, the template also invokes the relevant `gh` mutation.
- **The schema's `required_fields:` map is open over time.** Future mandatory state (due dates, milestone-on-EPIC, …) lands as new entries via the same-PR-as-surface-change discipline.
- **Cross-repo coordination of `mandatory-issue-state.yaml`** lives in the methodology-mesh's scope (per [project-management:DEC-022-methodology-mesh]); nothing repo-coupling-specific ships here.
- **Membership gate (DEC-021)** applies to `create-issue.py` and `assign-issue.py` like every other mutating script.
