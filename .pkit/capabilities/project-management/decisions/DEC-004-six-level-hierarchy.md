---
id: DEC-004
title: Six-level work-item hierarchy — Milestone, EPIC, Feature, Umbrella, Task, sub-task
status: accepted
date: 2026-05-21
author: Ales Kalfas
source:
  upstream: pm-workflow
  upstream_id: MET-003
  commit: 9d1f0237f5d5778ed9811c72f22ae8268e5faff3
  captured_at: 2026-05-21
---

## Context

The methodology needs a hierarchy that gives mid-level grouping between long-term outcomes and PR-sized changes. Too flat (everything under one EPIC) and the board becomes a wall of undifferentiated tasks; too deep and filing becomes a structural debate. The hierarchy choice fixes the issue types the engine recognises, the containment rules the validator enforces, and the body shapes the create-issue skill scaffolds.

## Decision

The capability recognises a **six-level hierarchy**:

| Level | Substrate | Role |
|---|---|---|
| **Milestone** | Native GitHub Milestone (separate primitive) | Time-bound delivery container; semantics project-defined (see [project-management:DEC-016-time-bound-containers]). |
| **EPIC** | GitHub Issue, type `epic` | Multi-quarter thesis or outcome. The unit that justifies a workstream. |
| **Feature** | GitHub Issue, type `feature` | Coherent cluster of Tasks delivering one capability. Has acceptance criteria. Atomic — does not nest. |
| **Umbrella** | GitHub Issue, type `umbrella` | Bucket of related Tasks that share a theme. No acceptance criteria. Nests freely. |
| **Task** | GitHub Issue, type `task` | One PR-sized unit of implementation work. |
| **sub-task** | Markdown checkbox inside a Task body | Coordination affordance; not a GitHub issue. |

The four issue types (epic, feature, umbrella, task) are encoded in [`schemas/issue-types.yaml`](../schemas/issue-types.yaml) with their title prefix, casing, structural role, allowed children (`can_contain`), allowed parents (`parent_issue_types`), parent-ref form, and whether the type gets a branch and PR. Milestone — a separate GitHub primitive scoping issues via the Milestone field — lives in [`schemas/time-containers.yaml`](../schemas/time-containers.yaml). Sub-task semantics (markdown checkbox conventions, promotion to standalone Task) live in [`schemas/body-format.yaml`](../schemas/body-format.yaml).

The **Feature / Umbrella split** is load-bearing: a Feature claims a capability and has acceptance criteria; an Umbrella is a flexible bucket that doesn't claim anything. Conflating them loses the planning signal ("which features ship in this milestone?"). The two-binary-test at filing — *does this group ship a capability?* — drives the choice.

### Small-adopter shortcut — skip the EPIC layer when work isn't multi-quarter

The default hierarchy assumes a Milestone → EPIC → Feature/Umbrella → Task shape. The EPIC layer earns its keep when work spans multiple quarters or bundles outcomes that justify a workstream-level thesis. Small adopters (early-stage projects, scoped tooling work) often have Milestones full of PR-sized fixes — a Milestone of three Tasks where forcing an EPIC wrapper adds ceremony without planning signal.

Adopters may **skip the EPIC layer** and parent Features / Umbrellas / Tasks directly under a Milestone via the `Milestone: #<N>` ancestry ref. The intermediate type stays optional — when work grows to warrant an EPIC, it's filed retroactively and existing children re-parent under it. The hierarchy reads:

| Default | Shortcut |
|---|---|
| Milestone → EPIC → Feature/Umbrella → Task | Milestone → Feature/Umbrella/Task |

The shortcut applies **per Milestone**, not project-wide — one Milestone can use the shortcut while another uses the full layering. The choice is the filer's judgement: *is there a multi-quarter outcome thesis here?* If no, skip EPIC. If yes, file the EPIC.

This expands `parent_issue_types` for Feature / Umbrella / Task in `issue-types.yaml` to include `milestone` as an allowed alternative parent. EPIC's parent stays Milestone only (EPICs always sit directly under a Milestone, never deeper).

## Rationale

Three structural levels are the minimum the original problem requires — long-term outcome (EPIC), mid-level grouping (Feature/Umbrella), and unit of work (Task). The Feature/Umbrella distinction adds friction at filing time (a "does this ship something?" judgement), but the friction is bounded and the planning payoff is real. The agent-mediated context makes the friction smaller still — the agent does the classification under user direction.

Going deeper (e.g., adding Initiative between EPIC and Feature) is over-engineering without observed need. Going shallower (collapsing Feature/Umbrella into a single grouping concept) loses the capability-claim signal. The six-level shape is the smallest hierarchy that holds.

### Alternatives considered

- **Mid five-level (single grouping type collapsing Feature and Umbrella).** Rejected — loses the "this ships a capability" signal Features carry.
- **Lean three-level (Milestone, Umbrella, Task).** Rejected — no EPIC concept; long-term outcomes have no home in the tracker.
- **Deeper hierarchy (EPIC → Initiative → Feature → Umbrella → Task).** Rejected as over-engineered; no observed need for an extra level above Feature.
- **Strict layering (no skip-EPIC shortcut).** Rejected — forces small adopters into thin EPIC wrappers around PR-sized work; the wrapper adds ceremony without planning signal. The shortcut preserves the full hierarchy as the default while accommodating small-project reality.

## Implications

- The issue-types schema is the source of truth for which types exist and how each behaves; the create-issue skill dispatches on it at filing.
- The containment graph (which type can contain which) is encoded in the schema's per-entry `can_contain` lists plus the schema-level `containment_invariants` block. The validator refuses filings that violate the graph (Feature-in-Feature, EPIC-in-EPIC, Task containing issues rather than markdown).
- Body shape per type is fixed by [project-management:DEC-010-issue-body-minimum-structure] and encoded in [`schemas/body-format.yaml`](../schemas/body-format.yaml).
- Filing authority per type is set by [project-management:DEC-008-pm-and-implementer-roles]; PMs file EPICs and Features, Implementers file Tasks and Umbrellas.
- Sub-tasks live as markdown checkboxes per [project-management:DEC-007-checkbox-validation]; promotion mechanics are in [`schemas/body-format.yaml`](../schemas/body-format.yaml)'s `sub_task_promotion` block.
