---
id: DEC-029
title: project-manager agent shape — rename, mode surface, sub-procedure boundary, reviewer-invocation discipline
status: accepted
date: 2026-05-27
author: Ales Kalfas
---

## Context

[COR-026](../../../decisions/core/COR-026-agent-placement-by-discipline.md) establishes the universal rule: discipline-implying agents live in the capability that ships the discipline. project-kit's project-management capability is the first realisation. The rule says *where* the agent lives; it does not say *what shape* the agent takes once consolidated.

This capability today ships `pm-agent` — a mechanical executor scoped to file / validate / transition issues per the eight schemas. The core agents `product-manager` (interactive coordinator) and `orchestrator` (autonomous coordinator) shipped at `.pkit/agents/core/` covered the judgment-layer and autonomous-coordination roles for the pm discipline. Per COR-026's rule and [COR-017](../../../decisions/core/COR-017-capability-pattern.md)'s Retroactive reclassification implication, those roles consolidate into this capability.

Three concrete questions remain to be pinned:

1. **The rename and the agent's name.** `pm-agent.md` has a redundant `-agent` suffix that the kit's other agent-name convention (`architect`, `critic`, `orchestrator`) does not carry. The rename is mandated by COR-026's placement realisation; the new name is the local decision.
2. **The mode surface.** [DEC-008](DEC-008-pm-and-implementer-roles.md) commits the capability's primary agent to mode-switching between PM-direction and Implementer-direction, with deployment-shape ("one mode-switching agent or several specialised") explicitly punted. The autonomous-coordination role (intent → filed work with one approval gate) is *new* responsibility this capability gains via COR-026. Whether this is a third user-facing mode, an invisible variation, or something else needs to be pinned.
3. **The procedure carrier.** [COR-006](../../../decisions/core/COR-006-artifact-roles.md) places procedures in skills, not agent bodies. The autonomous flow is multi-step (read intent → propose slicing → produce plan → approval gate → file via primitives). Where the procedure lives — composite-skill sub-procedure, standalone skill, or agent body — needs to be pinned.

The walkthrough captured in `.pkit/scratchpad/active/2026-05-27-project-manager-agent-shape.md` resolved each of these. This DEC pins the resolutions.

## Decision

### Rename: `pm-agent.md` → `project-manager.md`

The capability's primary agent renames to `project-manager`. The `-agent` suffix is dropped to align with the kit's other agent-name convention. All references to `pm-agent` in capability documentation and decisions update to `project-manager` in the same change-set as the rename.

The file move uses `git mv` to preserve history. The capability-tier migration script per [COR-010](../../../decisions/core/COR-010-resource-lifecycle.md) handles the rename idempotently for installed adopters.

### Mode surface: two visible modes, one invisible variation

The agent has **two user-facing modes** per [DEC-008](DEC-008-pm-and-implementer-roles.md): PM-direction and Implementer-direction. These remain user-facing because the methodology's role taxonomy is what distinguishes the modes.

The autonomous-coordination behaviour (intent → filed work with one approval gate) is an **invisible variation within PM-direction**. The agent infers from the user's request shape whether to operate in single-issue mode (file this one ticket; ask along the way) or batch-planning mode (read fuzzy intent + reference material; propose slicing; show single plan; file on approval). The user does not learn a third mode name or set a flag; the agent dispatches on request shape, same pattern DEC-008 already commits to for PM-vs-Implementer inference.

The rationale for invisible-not-visible is captured in the source scratchpad's Q1 resolution: today's `pm-agent` already infers PM vs Implementer from request shape with no explicit signal — extending the same pattern to "batch vs single" within PM-direction is consistent with existing behaviour and minimises the user-facing surface.

### Procedure carrier: new sub-procedure in the existing pm composite skill

The autonomous flow's steps live in **`batch-plan.md`**, a new sub-procedure of the pm composite skill, sibling to today's `create-issue.md` / `validate-body.md` / `transition-state.md`. The agent body stays thin and dispatches to it when batch-planning is inferred.

The sub-procedure carries:

1. **Read intent and reference material** — fuzzy intent + any handoff doc, scratchpad, or related issue the user supplies.
2. **Propose slicing** — Umbrella / EPIC / Feature / Task hierarchy per [project-management:DEC-004-six-level-hierarchy], with workstream / milestone / priority / parent-ref classifications per [project-management:DEC-012-classification-axes].
3. **Adversarial review** — invoke `critic` and (when work crosses ≥3 components or the slicing introduces a new abstraction) `architect` per the reviewer-invocation discipline below.
4. **Single approval gate** — present the (possibly revised) plan to the user; pause until approval, revision, or refusal.
5. **File via primitives** — call `create-issue` / `edit-issue` / `move-issue` per the plan. Handle validation failures per the storyboard's mid-execution-validation-failure scenario.

The sub-procedure file is authored as part of F3's implementation; this DEC commits its name and boundary.

### Reviewer-invocation discipline

`project-manager` invokes the kit's reviewer agents (`critic`, `architect` per [COR-024](../../../decisions/core/COR-024-reviewer-agents.md)) during batch-planning when the work crosses an empirical threshold:

- **Multi-issue arcs (≥3 issues to file)** invoke `critic` adversarially against the proposed slicing before the user sees it.
- **Cross-component work (≥3 components touched, or any work introducing a new abstraction)** additionally invokes `architect` for big-picture review.
- **Narrow single-issue work** (one ticket, no slicing decision) skips reviewer invocation. The threshold language mirrors today's CLAUDE.md reviewer-invocation table ("trivia and Q&A are exempt").

The agent surfaces reviewer findings to the user as part of the single approval gate. The user retains final authority; the reviewer pass is opposition, not veto.

**Invocation pattern: parent-mode only.** The dispatch language above applies when `project-manager` is the **parent session** — booted via `claude --agent project-manager` or via the default-agent toggle the project-management capability ships (per [DEC-030](DEC-030-capability-contributed-adapter-overlays.md)). Per Claude Code's documented subagent constraint ([sub-agents.md](https://code.claude.com/docs/en/sub-agents.md), lines 62, 306–313, 770), **subagents cannot spawn other subagents**: the `Agent` tool is on the "not available to subagents, even when listed in the `tools:` field" list. When `project-manager` is invoked as a subagent of another session (e.g. via `Agent({subagent_type: "project-manager"})` from a different parent), the dispatch capability is platform-gated regardless of frontmatter — in that case, dispatch is the outer parent session's responsibility, and `project-manager` operates in a degraded mode (filing / validating / transitioning via Write+Edit+Bash, but unable to invoke reviewers itself). The intended invocation pattern for adopters is the parent-mode toggle; subagent-mode is a fallback used only by the kit itself when the outer session is the general assistant rather than PM.

## Rationale

**Rename.** The `-agent` suffix is convention-inconsistent (other kit agents drop it) and creates surface ambiguity (is `pm-agent` an agent or a pm-related artifact?). `project-manager` is the discipline-fitting name; the role is project-management.

**Two visible modes + invisible variation.** Adding a third visible mode would force the user to learn a new mode name and decide when to invoke it. The user's actual ask is "do this for me" — a role-shaped invocation, not a mode-picking decision. Inference from request shape matches today's PM-vs-Implementer pattern and stays inside DEC-008's frame. (DEC-008's Implications line 82 explicitly punts deployment-shape; extending the agent's mode-switching to cover this variation is the natural continuation.)

**Sub-procedure in the existing composite skill.** Per [COR-006](../../../decisions/core/COR-006-artifact-roles.md), procedures live in skills. The pm composite skill already exists as the agent's procedure home; adding `batch-plan.md` as a sibling sub-procedure keeps the agent body thin (it dispatches; the skill steps) and avoids a separate top-level skill that the user has to discover. The agent is the single role surface; the skill carries the multi-step procedure underneath.

**Reviewer-invocation threshold.** Universal reviewer invocation on every batch-plan call would be heavyweight (most autonomous flows would carry a critic pass the user did not need). No reviewer invocation would leave non-trivial slicing decisions un-adversarial — the user's "I trust the agent to plan this" framing implies they want adversarial review built in. The threshold (multi-issue + multi-component) catches the cases where independent opposition meaningfully reduces the risk of bad slicing while avoiding ceremony on simple tasks.

### Alternatives considered

- **Three visible modes** (PM, Implementer, product-owner). Rejected — adds user-facing surface without proportional value; the autonomous behaviour is a variation within PM direction, not a peer role.
- **Standalone `pm-batch-plan` skill** (no sub-procedure of the composite). Rejected — fragments the procedure surface; the user has to know to invoke the standalone skill. Keeping the autonomous flow as a composite sub-procedure means the agent is the only entry point users learn.
- **Procedure steps inline in the agent body.** Rejected per COR-006 — procedures are skill-shaped, not agent-body-shaped. An agent body of >100 lines describing every batch-planning step would also defeat the agent's "thin dispatcher" framing today.
- **Mandatory reviewer invocation on every batch-plan.** Rejected — heavyweight for trivial cases; the empirical threshold catches what matters and skips what doesn't.

## Implications

### Immediate (operationalised in F3-F5)

- The `pm-agent.md` → `project-manager.md` rename ships with the new body shape in F3 (#185).
- The `batch-plan.md` sub-procedure is authored in F3 alongside the agent body rewrite.
- The capability-tier migration for the rename ships per COR-010 (F3 or F4 — change-set decision deferred to implementation).
- The storyboard at `.pkit/capabilities/project-management/agents/project-manager/storyboard.md` (F2 #184) covers the scripted scenarios for the autonomous flow per [COR-016](../../../decisions/core/COR-016-scripted-scenario-storyboards.md). The agent body declares the storyboard in frontmatter per COR-016's two-sided declaration.

### Forward implications

- Future capability features that touch the agent's mode surface should refine this DEC in place rather than supersede it (the load-bearing claim — the rename + two-mode-with-invisible-variation shape — is stable; sub-procedure boundary changes are refinement).
- The reviewer-invocation threshold may prove too coarse or too fine with lived experience. Adjustments to the threshold land as in-place refinements to this DEC; a fundamental rework (e.g., per-issue reviewer choice) warrants a successor DEC.
- [DEC-008](DEC-008-pm-and-implementer-roles.md) is refined in the same change-set with a forward-pointer to this DEC — DEC-008's Implications line 82 ("deployment shape is the adopter's choice") is now answered for this capability by this DEC.

### What this DEC does NOT cover

- The implementation of any pm capability lifecycle work (Phases A-E from the impl-phase handoff — DEC-023/024/026/027/028). Those are independent of agent shape; the new `project-manager` will eventually serve as the substrate for those flows but DEC-029 does not specify their content.
- The disposition of the `storyboard-author` skill case from COR-017's Retroactive reclassification (skill, not agent — outside COR-026's rule and this DEC's scope).
