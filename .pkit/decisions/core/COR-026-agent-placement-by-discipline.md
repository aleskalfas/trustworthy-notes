---
id: COR-026
title: Discipline-implying agents live in the capability that ships the discipline
status: accepted
date: 2026-05-27
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

The methodology ships agents in two locations: core (`.pkit/agents/core/`) for agents any adopting project can use, and per-capability (`.pkit/capabilities/<name>/agents/`) for agents tied to an installed capability. [COR-013](COR-013-agent-architecture.md) defines the agent contract; [COR-014](COR-014-universal-applicability.md) requires that core artifacts pass a universal-applicability bar; [COR-017](COR-017-capability-pattern.md) introduced the capability as the packaging primitive for opt-in discipline.

The placement rule for *where* an agent goes was never explicit. The default in practice has been: ship at core unless a specific capability home exists. That default fails when the agent's body implies a particular discipline — issues / PRs / lifecycle states for a workflow tracker, evidence-citation semantics for an evidence-management discipline, scripted-scenario walkthroughs for a storyboard-authoring discipline. Such agents are not universally applicable: adopters who don't install the capability still inherit them, implying disciplines those adopters lack.

[COR-017](COR-017-capability-pattern.md) already flagged this gap in its *Retroactive reclassification* implication, naming three concrete artifacts (`product-manager` and `orchestrator` agents from COR-013; `storyboard-author` skill from COR-016) as candidates for relocation. The reclassification commitment was made but the placement *rule* — the universal principle that prevents future recurrence — was never authored.

The same shape now recurs every time a new capability ships agents that span both judgment and execution surfaces. Without an explicit rule, each capability author re-decides whether the judgment-layer agent goes at core or in the capability, and the corpus accumulates inconsistency. The recurrence triggers [COR-007](COR-007-pattern-extraction.md)'s extraction threshold — the rule is worth pinning.

## Decision

**Agents that imply a particular discipline live in the capability that ships that discipline, not in core.**

The placement rule:

- **Core agents** at `.pkit/agents/core/` must pass [COR-014](COR-014-universal-applicability.md)'s universal-applicability bar. They must be useful to an adopter regardless of which capabilities (if any) are installed. Agents whose bodies cite capability-specific schemas, workflow-tracker primitives, or other discipline-specific concepts fail this bar.

- **Capability agents** at `.pkit/capabilities/<name>/agents/` own the *full agent surface* for that capability's discipline. A capability is free to ship one agent that switches modes, multiple agents per role, or any other shape that fits the discipline — the architectural commitment is that the locus is the capability's agent folder.

- **No-capability-yet case.** When a new discipline-implying agent is proposed and no capability exists to host it, the answer is *not* to default to core. Either author the capability first (per [COR-017](COR-017-capability-pattern.md)'s capability-authoring procedure) and place the agent there, or defer the agent until the discipline is concrete enough to motivate a capability. Discipline-implying agents do not float at core "temporarily".

The test an agent author runs: *would an adopter who installed none of this methodology's capabilities find this agent useful?* If yes, the agent is core-eligible. If no, it belongs in the capability whose discipline the agent presupposes.

## Rationale

**[COR-014](COR-014-universal-applicability.md) universal-applicability.** Core artifacts must be useful in any adopting project. An agent that talks about issues, PRs, evidence records, or storyboards is meaningful only in projects that have installed the corresponding capability. Placing such an agent at core breaks the universal contract.

**[COR-017](COR-017-capability-pattern.md) capability pattern.** Capabilities are opt-in installable disciplines. Agents that imply a discipline belong inside that capability's boundary, not at a level above it. Putting them at core inverts the opt-in shape: every adopter inherits the discipline-implying agent regardless of whether they want the discipline.

**[COR-006](COR-006-artifact-roles.md) artifact roles.** Agents are role surfaces — one named entity the user invokes. The role is bound to the discipline when the discipline shapes what the agent does. Decoupling them (a generic role at core, a specific discipline in the capability) introduces indirection without clarity: the user still has to know which discipline backs the role.

**Composition over decomposition.** When a discipline has both judgment and execution surfaces, placing them in different locations decomposes the discipline across the locations and forces composition at invocation time. Co-locating them in the capability composes the discipline back together — one place to read the agent surface, one place to extend it.

### Alternatives considered

- **No rule; trust each agent author's judgment.** Rejected per [COR-007](COR-007-pattern-extraction.md) — when the same shape recurs, document the rule. Three concrete cases (project-management coordinators, evidence-management scratchpad, storyboard-authoring skill) is enough recurrence to extract the principle.
- **Inverse rule — promote capability execution agents to core; coordinators stay at core.** Symmetric rejection: capability-execution agents read capability-specific schemas and dispatch against discipline-specific sub-procedures. They fail COR-014 even more sharply than judgment-layer coordinators. Listed for symmetry.
- **Hybrid — thin core interface agent + capability-shipped implementation.** A core agent that resolves at runtime to the installed capability's implementation. Rejected because the core shell still ships the surface; adopters who never install the capability still see a discipline-implying agent at core. Adds runtime indirection without clearing COR-014.
- **Coordinator-as-skill, no agent.** [COR-006](COR-006-artifact-roles.md)'s discriminator says procedures live in skills, but the *role* aspect (one named entity to invoke) belongs to an agent. The clean answer is both: the agent is the role surface, the skill carries the procedure. Skills nest under the agent's capability; this COR's rule governs the agent's placement.

## Implications

- **Authors of new discipline-implying agents.** Author the corresponding capability first (or extend an existing one); place the agent inside it. Do not stage a "temporary" core placement with intent to relocate.
- **Core agents promoted in future.** Each promotion must clear COR-014's universal bar explicitly. The test from the Decision applies: would an adopter with no capabilities installed find this agent useful?
- **[COR-017](COR-017-capability-pattern.md)'s *Retroactive reclassification* implication.** This COR is the rule the implication anticipated. The implication's agent cases (`product-manager`, `orchestrator`) are now governed by this rule and may be relocated under it. The implication's *skill* case (`storyboard-author`) is **not** governed by this COR — that artifact is a skill, not an agent; its disposition follows COR-006's separate logic and requires its own record.
- **Agent-name collision precedence between capability and core.** When a capability ships an agent with the same name as a core agent (rare but possible — e.g., a capability that supersedes a core agent), the resolution rule must exist. `.pkit/agents/README.md` documents project-vs-core precedence today; capability-vs-core is unspecified. This COR creates the structural need for the rule; the README is extended to carry it.
- **Migration on relocation.** Moving a discipline-implying agent from core into a capability is a file rename in a kit-owned tree. Per [COR-010](COR-010-resource-lifecycle.md), the move ships a migration script at the affected tier in the same change-set.
- **Capability authoring guidance.** The `capability-author` skill and the `agent-author` skill should surface this rule at authoring time: when stamping an agent, the skill prompts the author to check whether the agent implies a discipline, and if so, refuses placement at core.
