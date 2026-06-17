---
id: DEC-006
title: Gated lifecycle state machine with upward-only cascade
status: accepted
date: 2026-05-21
author: Ales Kalfas
source:
  upstream: pm-workflow
  upstream_id: MET-005
  commit: 9d1f0237f5d5778ed9811c72f22ae8268e5faff3
  captured_at: 2026-05-21
---

## Context

Every issue moves through some sequence of states from filing to closure. The capability needs to fix what those states are, who authorises each transition (since the agent runs most state changes but irreversible ones — start of work, end of work — need explicit human gates), and how parent issues respond when their children's states change. Without this, agent behaviour around state changes is non-deterministic and the cascade across the hierarchy in [project-management:DEC-004-six-level-hierarchy] has no defined propagation rule.

## Decision

### State machine

Five states in linear order: **Todo → Backlog → In Progress → Review → Done**. Encoded in [`schemas/workflow.yaml`](../schemas/workflow.yaml). Each state carries a display name, prose meaning, the issue types it `applies_to` (Review is task-only; the other four apply to every type), and the native primitives the canonical state is inferred from (issue open/closed, Milestone assignment, branch existence, PR state).

When a Projects v2 board exists, its Status field is a projection the agent maintains. When the board and native primitives disagree, **native wins**.

### Authorisation gates

The schema's `transitions` list fixes who authorises each transition and what the agent does on violation:

| Transition | Authorisation | Severity (on violation) |
|---|---|---|
| Todo → Backlog | User (assigns Milestone) | bypassable-with-audit |
| Backlog → In Progress | Agent autonomous | warning |
| In Progress → Review | Agent autonomous (Task only) | warning |
| Review → Done | User (per-PR approval) | hard-reject |
| Backlog/Todo → Done (won't-do) | User | hard-reject |
| In Progress → Done (parent cascade-eligibility close) | User | hard-reject |

User holds both ends of the gate (start and end of work); the agent owns the middle. Authorisations are per-issue and in-session — no standing "go ahead with everything" applies in a later turn. The agent records the bypass with an audit-trail comment per [project-management:DEC-014-validation-severity-model] when a bypassable transition is overridden.

> **Amendment (#61/#62, under EPIC #59) — the Todo → Backlog authorisation has two substrates; the milestone is one of them, not the gate's meaning.** The table's "User (assigns Milestone)" names the *typical* authorisation gesture, not a hard precondition. The gate's meaning is the **user-held scheduling commitment** ("this is real work we intend to do"); a project that runs no Milestone *instances* (e.g. a feature-driven project that has declared a Milestone category but created no Milestones yet) still needs to make that commitment. The authorisation is therefore satisfied by **either** a Milestone assignment **or** an audited verbal `--reason` — the latter is exactly the bypassable-with-audit verbal-authorisation path [project-management:DEC-014-validation-severity-model] already enumerates. The wrapper that carries this is `promote-issue`, whose `--milestone` is optional per the amendment to [project-management:DEC-026-work-ownership-lifecycle].
>
> **The severity is unchanged (decline of #62).** The Todo → Backlog severity stays **bypassable-with-audit** in every project, milestone-bearing or not. Lowering it to `warning` for milestone-less projects was rejected: (1) it would hand the agent one of the two ends the user holds — Todo → Backlog is the *start* commitment, not the agent-owned middle; (2) bypassable-with-audit *is* the verbal-authorisation path, so the milestone-less case is already served at the right severity (the fix is the command's optional `--milestone`, not the severity); (3) a severity that varies with project config would break [project-management:DEC-014-validation-severity-model]'s invariant that the agent dispatches on the severity token without per-rule logic. The substrate broadens; the gate and its audit trail do not.

### Cascade rule

Three behaviours, encoded in the schema's `cascade` block:

- **Forward cascade (Todo → Backlog → In Progress).** Direction `upward`. Automatic. When a child moves forward, the agent checks each ancestor and bumps any that's behind to match. Idempotent — repeated firings on already-cascaded ancestors are no-ops.
- **Closure cascade (→ Done).** Direction `upward`. Semi-automatic. When the *last open* child of a parent closes, the parent becomes **eligible to close** but never auto-closes. The agent validates the parent's close criteria (Feature acceptance criteria ticked, EPIC success criteria met, Umbrella purpose served) and prompts the user to authorise closure at each level.
- **Downward cascade.** Direction `none`. Disallowed. Parent state changes do not change children. The wrong direction of causation.

> **Amendment (#38, under EPIC #6) — Review is a leaf/Task state; containers do not forward-cascade into Review.** The forward cascade above is scoped to **Todo → Backlog → In Progress** (Review is deliberately excluded). A child entering **Review** therefore does **not** promote its container — a container's forward-cascade target tops out at **In Progress** while any child is unfinished. A container reaches Done only via the **closure cascade** (In Progress → Done, cascade-eligibility per the authorisation table) once all children are done and its close criteria are met.
>
> Rationale: Review models "a PR is open for this leaf"; a container has no PR of its own, so a container sitting in Review is meaningless — and it produced a **stuck state**, because Review's only forward exit is Done, leaving a container with more children still to build unable to return to In Progress (finding 4.2 of the done-work handoff note). This is a **clarification** of the forward cascade's existing scope, not a new rule: the implementation was over-cascading containers to *match* a child's Review state, beyond what this section specifies. No `Review → In Progress` back-edge is needed once containers never enter Review.

### Closure triggers

Four paths reach Done, encoded as schema entries:

- **`pr-merge-into-main`** — Task's normal path. PR opens → user authorises merge → agent squash-merges with `--delete-branch` → GitHub's `Closes #N` auto-closes the Task → cascade runs.
- **`pr-merge-into-integration`** — same mechanics but PR base is `integration/<slug>` (per [project-management:DEC-013-branch-and-pr-conventions]).
- **`manual-wont-do`** — user authorises with a reason; agent verifies all checkboxes are ticked or removed per [project-management:DEC-007-checkbox-validation], records the reason in a close comment.
- **`cascade-eligibility-close`** — triggered by closure cascade; agent validates parent's close criteria and prompts user per-level.

## Rationale

Gated state machines work well for agent-mediated workflows because the gates — the places where humans must explicitly authorise — can be enforced as tool refusals encoded in schema severities. The agent literally cannot flip a user-gated transition without an authorisation signal. This converts the methodology's authority discipline into mechanical enforcement.

Upward-only cascade matches the natural direction of causation in planning: a parent's progress is a function of its children's progress, not the other way around. Allowing downward cascade would force the agent to override individual children's states based on parent moves, the wrong direction.

The "eligible to close but never auto-close" asymmetry makes the cascade safe. Closing a Feature is a commitment ("this capability shipped"); closing an EPIC is a bigger one. Auto-closing on the last child closing would produce a chain reaction with no human pause point. Stopping at each parent for explicit authorisation preserves the deliberate quality of those commitments.

### Alternatives considered

- **Open/closed only (no intermediate states).** Rejected — loses planning visibility from Backlog/In Progress/Review.
- **Auto-close parents when last child closes.** Rejected — removes the deliberate-act quality of closure.
- **Bidirectional cascade.** Rejected — wrong direction of causation.
- **No cascade.** Rejected — parents drift out of sync with their children's reality.

## Implications

- The transition-state skill walks the schema's `transitions` list to dispatch every requested state change — refuses the move (per the listed severity) if the requested transition isn't in the schema or if the user-gated transition lacks authorisation.
- The project-manager runs the cascade check after every state-changing operation: forward cascade walks ancestors and bumps any behind; closure cascade surfaces a parent-close prompt when eligibility is reached.
- PR-merge of a Task requires the checkbox-completeness check from [project-management:DEC-007-checkbox-validation] to pass before the agent authorises the merge — GitHub's auto-close on PR merge would otherwise bypass the close-gate.
- Won't-do closures trigger the same cascade as PR-merge closures.
- Date-based Milestone close interacts with this cascade via the rollforward rule in [project-management:DEC-016-time-bound-containers]; open children roll forward rather than closing, and the closure cascade only counts actually-closed children for eligibility.
- Integration-scope closures run the same cascade — the change is only the PR base branch (integration vs `main`) plus the final integration → main PR closing the owning root. See [project-management:DEC-013-branch-and-pr-conventions].
