---
id: DEC-022
title: Methodology mesh — cross-repo state coordination via per-repo peer lists with optional governance-repo centralisation
status: accepted
date: 2026-05-24
author: Ales Kalfas
---

## Context

When a team's methodology adoption spans multiple repos (e.g., an org running both `agentic-user-journey` and `interaction-gateway` under the same workstreams and team membership), the methodology state on each repo should be consistent: identical `type:*` / `priority:*` / `workstream:*` label vocabularies, identical `members.yaml`, identical capability version, identical milestone naming conventions. Today nothing detects or coordinates this — each repo is autonomous and can drift silently. Drift surfaces as confusion at filing time (a label that exists in repo A doesn't exist in repo B), at planning time (workstream assignment doesn't aggregate cleanly across repos), and at audit time (membership differs across repos that should share a team).

Two adoption shapes exist in the wild:

1. **Decentralised teams** — each repo owns its methodology state autonomously. Coordination happens informally through PR review across repos.
2. **Governance-repo teams** — a designated repo holds the canonical methodology state; other repos pull from it (manually today; automatically with the right tooling).

Both shapes need a way to detect drift between repos and surface it. Neither needs the methodology to *enforce* consistency — enforcement would block legitimate transient states (e.g., mid-rename across repos). The right shape is **decentralised mesh with drift detection** — peers declare each other, a script compares state, findings surface as warnings; the operator decides what to do.

This DEC is **capability-local** at v1. The pattern (cross-repo state coordination among a team's repos, with drift detection but no enforcement) is plausibly generalisable to a future `deployment` or `compliance` capability, but COR-007's pattern-extraction discipline says wait for the second instance before promoting to a kit-level COR. Phase E settled this scoping choice deliberately.

## Decision

The capability ships a **decentralised mesh model with drift detection**. Each adopter declares its peers in adopter config (first-class) and may optionally point at a governance-repo central registry (optimisation for teams that have one). A read-only `scripts/check-mesh.py` script compares state across the mesh and surfaces drift as warnings. A kit-shipped GitHub Action template runs the check on a schedule.

### Topology — per-repo peer list, first-class; governance registry, optional

Each adopter's `.pkit/capabilities/project-management/project/config.yaml` may declare its mesh peers:

```yaml
mesh_peers:
  - github://ai-platform-incubation/interaction-gateway
  - github://ai-platform-incubation/agentic-user-journey
```

For teams with a governance repo, an alternative single pointer:

```yaml
mesh_source: github://ai-platform-incubation/governance-repo/path/to/mesh.yaml
```

The governance-repo file (`mesh.yaml`) lists the team's repos in the same shape as `mesh_peers:`; the consuming repo dereferences `mesh_source:` at check time. **Either configuration works; whichever the adopter sets wins**; neither requires governance-repo authority — the per-repo list is the natural default, the governance pointer is an optimisation.

**Single-repo adopters** — neither field set. The mesh feature is inactive. The script reports "no peers configured; mesh check skipped" and exits zero.

The same per-repo-vs-central pattern applies symmetrically to `members.yaml` (per [project-management:DEC-021-team-membership-gate]'s deferred multi-repo question) and to `workstreams.yaml` (per [project-management:DEC-018-workstream-taxonomy-and-lifecycle]). A future enhancement may add `members_source:` and `workstreams_source:` analogues; v1 ships the mesh-level pointer only.

### Trigger and severity

**Trigger.** Three invocation paths:

- **Manual** — adopter runs `scripts/check-mesh.py` directly.
- **Scheduled workflow** — kit-shipped `templates/.github/workflows/pm-mesh-check.yml`. Default schedule: daily. Surfaces findings as a GitHub issue (tagged `mesh-drift`) or a status check.
- **Not per pm-operation** — drift detection is not an inline check for issue creation or any other verb-subject script. It's a periodic / on-demand health check. Per-op drift checking is too expensive (every command would hit `gh api` for every peer); the three-layer defence model from [project-management:DEC-020-methodology-as-executable-commands] keeps inline checks confined to local state.

**Severity.** All drift is **`[validation-severity:warning]`** at v1. Surface findings; do not block pm operations. Drift is often transient (mid-rename across repos; a planned add not yet propagated); the operator decides what to do. Tag-based severity per drift kind (e.g., "member-list divergence is hard-reject; label drift is warning") is deferred per COR-007.

### Scope — what state gets compared

**In scope at v1:**

| State | Source | Comparison |
|---|---|---|
| `type:*` labels | Repo labels via `gh label list` | Methodology-fixed; should be identical across team repos. |
| `priority:*` labels | Repo labels (label-fallback adopters only) | Should be identical across team repos that use label substrate. |
| `workstream:*` labels | Repo labels (label-fallback adopters only) | Team-shared values; should be identical. |
| Capability version | `.pkit/capabilities/project-management/package.yaml` `version:` | Drift means peers run different methodology versions; flagged for upgrade coordination. |
| `members.yaml` contents | Project file | If both peers have it in closed mode, members should match. |
| Milestone titles + close-trigger markers | `gh api repos/.../milestones` | Shared milestone names with mismatched close-trigger markers; cross-repo gaps in expected milestones. |

**Out of scope at v1:**

- **Adopter config values** (`default_branch`, `projects_v2_board_id`, `pre_close_triage_lead_days`, …) — legitimate per-repo variation.
- **Custom (non-methodology) labels** — adopter's own concerns.
- **Per-milestone close-trigger checks** — handled per-repo by `pre-check.py`.
- **Workstream-substrate-specific board comparisons** — when both peers use board substrate, the board IS the shared substrate and per-repo comparison is meaningless. The mesh check only compares label substrate.

The compared state is **the methodology-mandated state that should be uniform across the team's repos**. Per-repo legitimate variation is excluded by construction.

### Authority

`check-mesh.py` is read-only and invokes no mutating `gh` calls. The script gates on the [project-management:DEC-021-team-membership-gate] membership predicate like every other verb-subject script — open mode passes; closed mode refuses non-members. Beyond that, no methodology authority gate applies (there's no destructive operation to authorise).

The scheduled workflow runs as the configured GitHub Action identity; that identity must be added to `members.yaml` (or `PM_INVOKER_LOGIN` must be set from a CI secret) in closed-mode repos.

### Reporting shape

The script's output is structured and re-readable:

```
[check-mesh] target: ai-platform-incubation/interaction-gateway
             peers:  ai-platform-incubation/agentic-user-journey

[drift] type:* labels diverge
  in target only:   type:incident
  in peer only:     —
  → Required by classification.yaml#axes.type.values (per [project-management:DEC-012-classification-axes])

[drift] capability version
  target: 0.6.0
  peer:   0.5.0
  → Peers run different methodology versions; upgrade coordination needed.

[ok] members.yaml — identical across peers
[ok] workstream:* labels — identical
[ok] priority:* labels — identical (both adopters in label-fallback mode)

[summary] 2 drift findings, 3 ok. Severity: warning.
```

Exit code 0 on every drift severity ≤ warning at v1. The output format makes findings actionable; the scheduled workflow's GitHub issue picks the format up verbatim and links back to the `check-mesh.py` invocation that produced it.

### Sequencing

The mesh lands at **v0.7.0+** per the [project-management:DEC-020-methodology-as-executable-commands] rollout — lowest priority among the four design refinements settled in Phase D. Predecessors:

- v0.5.0 — workstream lifecycle must exist so workstream-axis drift is detectable.
- v0.6.0 — mandatory-issue-state must exist so the schema reference for severity tokens is stable.

The v0.7.0 PR ships:

- `scripts/check-mesh.py` — the verb-subject diagnostic.
- `templates/.github/workflows/pm-mesh-check.yml` — the scheduled workflow template.
- Adopter config schema updates — recognising `mesh_peers:` (list) and `mesh_source:` (single URI).
- Capability `package.yaml` `version:` bump.

## Rationale

**Why decentralised mesh rather than a central authoritative repo.** Forcing every adopter through a governance repo would over-engineer the single-repo case (most adopters), introduce a hard dependency on a designated repo's availability, and impose a topology many teams don't have. The per-repo peer list is the natural shape for the common case; the governance-repo pointer is the optimisation for teams that already have central state.

**Why drift detection is warning-only at v1.** Hard-rejecting on drift would break legitimate transient states. The classic example: renaming a workstream across three repos takes three PRs; the second PR fails mid-flight if drift is hard-reject. Surfacing the drift as a warning, letting the operator finish the third PR, and the warning clearing on the next mesh check is the right shape. Promoting specific drift kinds to higher severity (e.g., member-list divergence) lands when there's evidence the warning is being ignored on cases where it shouldn't be — COR-007 again.

**Why scope is methodology-mandated state only.** Comparing adopter-specific config values (`default_branch`, `pre_close_triage_lead_days`) would force teams to standardise things they have legitimate reasons to vary. The mesh's purpose is to ensure team-shared methodology surface is uniform, not to homogenise adopters.

**Why no per-pm-operation mesh check.** Per-operation drift detection would either be expensive (hit `gh api` for every peer on every command — slow + rate-limit-prone) or stale (cache aggressively → false-negatives). A periodic external check at warning severity is the right shape for state that drifts on a multi-day cadence, not a per-second cadence.

**Why capability-local at v1 rather than a kit-level COR.** Promoting the pattern to a kit-level COR now is speculative — exactly one capability (this one) consumes mesh today. COR-007 mandates waiting for a second instance before generalising. The cost of waiting is roughly zero: a future `deployment` capability that wants mesh consumes this DEC's shape; a kit-level COR that both consume is one PR of rework with concrete generalisation signals.

**Why the scheduled workflow is template-only rather than auto-deployed.** Same reasoning as [project-management:DEC-019-mandatory-issue-state]'s post-check workflow — `.github/workflows/` is a fixed adopter path the no-shared-files invariant forbids the kit from writing to. Template-and-copy is the adopter-installable pattern.

### Alternatives considered

- **Central governance-repo as mandatory.** Rejected — over-engineers the single-repo case; introduces a hard dependency.
- **Per-op mesh check inline.** Rejected — too expensive; rate-limit-prone; conflates inline correctness with periodic health.
- **Hard-reject on drift at v1.** Rejected — breaks legitimate transient states (mid-rename across repos).
- **Promote to a kit-level COR now.** Rejected — speculative; violates COR-007's pattern-extraction discipline. Promote when a second capability consumes mesh.
- **Auto-remediate drift (e.g., auto-rename labels to match peer).** Rejected — too aggressive at v1; cross-repo writes carry real blast radius and need per-change human gates.
- **Compare adopter config too.** Rejected — adopter config has legitimate per-repo variation; the mesh's scope is methodology-shared state.

## Implications

- **A new script `scripts/check-mesh.py`** ships at v0.7.0.
- **A new template `templates/.github/workflows/pm-mesh-check.yml`** ships at v0.7.0 — adopters install it into their own `.github/workflows/`.
- **Adopter config schema** gains `mesh_peers:` (list of `github://owner/repo` URIs) and `mesh_source:` (single `github://owner/repo/path` URI) as optional fields, mutually compatible (whichever the adopter sets wins).
- **The capability `version:`** bumps to v0.7.0 on the implementing PR.
- **Membership gate (DEC-021)** applies to `check-mesh.py` like every other verb-subject script — open mode bypasses; closed mode requires the invoker (or service identity / `PM_INVOKER_LOGIN`) to be in `members.yaml`.
- **Single-repo adopters are unaffected** — without `mesh_peers:` / `mesh_source:`, the script reports "skipped" and exits zero. The scheduled workflow template is opt-in.
- **The scheduled workflow's output channel** (GitHub issue with `mesh-drift` label vs status check) is adopter-configurable in the template's `env:` block.
- **Future kit-level COR may generalise this pattern** to other capabilities that mutate cross-repo state. Promotion follows COR-007 when a second capability needs the same shape. Until then, DEC-022 is the only mesh DEC in the kit corpus.
- **Workstream-specific cross-repo logic** stays out of [project-management:DEC-018-workstream-taxonomy-and-lifecycle] — DEC-018's cross-repo coordination section explicitly delegates the cross-repo workstream story here. There is no `workstream_peers:`; the mesh's general `mesh_peers:` covers it.
- **`members.yaml` cross-repo coordination** is covered by the mesh check's comparison of file contents. The deferred design question from DEC-021's identity resolution section (single source-of-truth across multi-repo teams) lands as a v0.8.0+ refinement (`members_source:` analogue), not at v0.7.0.
