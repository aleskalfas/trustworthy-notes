---
id: COR-024
title: Critic and architect agents — universal pre-proposal critique role and architectural custodianship with escalation
status: accepted
date: 2026-05-27
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

AI-mediated authoring is now the dominant mode of work on the methodology core and on adopting projects. The pattern that emerges: a primary agent (Claude in the Claude Code harness, or whatever an adopter uses) drafts proposals, designs, plans, decisions; the human reviews them. Two structural failures recur:

1. **Cheap-to-fix mistakes survive into the human's review loop.** The primary agent is willing to surface a half-formed idea because doing so is its default mode. The human's review time is precious and the cycle's expensive seam. Mistakes that a moment's adversarial second-opinion would catch — internal contradictions, gaps, weak reasoning, undeclared assumptions, missed alternatives — burn human review cycles.
2. **Architecturally drifting decisions look locally sensible.** A change that satisfies its immediate task can quietly violate a previously-recorded architectural promise, introduce abstractions at the wrong layer, or alter foundational shape without re-examining the doc that says how things hang together. The primary agent isn't oriented toward the big picture; nobody is, by default.

The two reviewer agents already shipped — `methodology-reviewer` and `convention-compliance-reviewer` — fire at different stages and address different scopes. `methodology-reviewer` audits *artifacts* against disciplines (axiom / project-neutrality / principles-not-inventory / universal applicability / artifact-role placement). `convention-compliance-reviewer` audits *diffs* against conventions (conventional commits / no-shared-files / branch naming / surface-change discipline). Neither catches the cheap-pre-proposal failure mode (the artifact / diff doesn't exist yet) nor the architectural-coherence failure mode (architectural fit is broader than per-artifact discipline). A separate methodological seam is needed.

This record names two universal agent roles that fill the gap. They sit alongside the existing reviewers, with explicit ordering and complementary scopes. The implementation (agent files, adopter wiring) is the operational layer the architecture roles in [COR-013](COR-013-agent-architecture.md) and [COR-015](COR-015-artifact-file-layout.md) already model.

## Decision

### Two universal agent roles

| Agent | Stage | Mode | Tools | Scope |
|---|---|---|---|---|
| **critic** | Pre-proposal (before the human sees a substantive draft) and on-demand | Adversarial second opinion | Read-only — Read, Glob, Grep, WebFetch | Universal — applies to any proposal, design, plan, draft, decision |
| **architect** | Per-proposal when the change touches the big picture; on-demand; optional periodic | Architectural review + doc custodianship | Read + Edit constrained to overlay-resolved architecture roots and ADR records (see [COR-025](COR-025-adr-decision-space.md)) | Universal — every project has *some* architectural surface; the agent operates on whatever the overlay points at |

Both agents are **core-shipped** (under `.pkit/agents/core/`) and apply to every adopter. The principle they enforce is universal; the adopter-specific wiring lives in the adopter's CLAUDE.md (or equivalent) and the adopter's overlay.

### Critic — adversarial opposition on demand

The critic's role is **structured adversarial review of unbaked work**. Three legitimate invocation patterns:

1. **Pre-proposal review** — the primary agent calls the critic before showing a substantive draft to the user. The critic returns a structured critique; the primary agent revises (or pushes back) and then shows the user the revised draft plus any unresolved critiques flagged. Substance threshold: a draft DEC/COR/PRJ, a multi-component plan, a command-palette design, an architectural rework. Trivia (Q&A, single-file edits, one-line decisions) is exempt — discipline shouldn't become bureaucracy.
2. **On-demand opposition** — the user explicitly asks for a contrary view: "critic, oppose this design." Useful when the user senses agreement is too easy or wants a sanity check on a settled-feeling answer.
3. **Periodic adversarial sweep** — the critic is invoked on an open question, in-progress plan, or recently-accepted decision to surface weaknesses that didn't appear at filing time.

The critic's contract is the same in all three: read the proposal and its context, return structured critique organised as red flags / gaps / weak reasoning / overlooked alternatives / agreements-worth-stating. The critic does not write code, does not edit artifacts, does not run commands. Read-only is the discipline; it preserves the role's independence.

### Architect — architectural custodian and escalation point

The architect's role is **architectural coherence custody**. Two responsibilities:

1. **Review proposals that touch the big picture.** Triggers: a change introduces a new abstraction or component; touches more than one capability or area; modifies a foundational decision (a previously-accepted COR/DEC); renames or relocates a kit-owned tree; adds a cross-cutting concern (failure semantics, config-block growth, lifecycle event taxonomy). The architect returns architectural review: boundaries, abstractions, layer placement, cross-cutting concerns, escalation-needed flags.
2. **Own architecture documentation.** The architect has constrained write authority over overlay-resolved architecture-doc roots (see "Adopter overlay" below) and ADR records ([COR-025](COR-025-adr-decision-space.md)). When an architectural decision is settled, the architect drafts or updates the relevant document. When a change implies a doc update that hasn't happened, the architect flags or makes it.

The architect operates **advisory** at v1. The primary agent (or human) remains responsible for the final shape of any proposal. The architect's feedback is structured advice with an explicit escalation flag when authorisation from the architectural perspective is required. Promotion to *gate* — the architect can refuse and the primary agent must comply — is deferred until recurrence demonstrates the advisory mode is insufficient (per [COR-007](COR-007-pattern-extraction.md)).

### Adopter overlay — customisable architecture roots

The architect must reach the adopter's architecture documents. Per [COR-013](COR-013-agent-architecture.md), agents declare reads/owns via either explicit paths or overlay-resolved placeholders. The architect uses placeholders for its architecture-related references so adopters with different documentation layouts can wire the agent without modifying the kit-shipped file:

```yaml
# .pkit/agents/core/architect.md (frontmatter excerpt)
reads:
  patterns:
    - <architecture-docs>
    - <adr-records>
owns:
  patterns:
    - <architecture-docs>
    - <adr-records>
```

The adopter resolves the placeholders by populating `.pkit/agents/project/overlay.yaml`. That file is project-owned per the no-shared-files invariant ([`.pkit/decisions/README.md`](../README.md)) — the methodology cannot ship default values inside it. Instead, the methodology documents the **conventional resolution** here; adopters opt in by populating their overlay accordingly:

```yaml
# .pkit/agents/project/overlay.yaml — adopter populates with the conventional values
architecture-docs:
  - docs/architecture/
adr-records:
  - docs/architecture/decisions/
```

The conventional resolution matches the well-known ADR-community layout. Adopters whose architecture lives under `engineering/architecture/`, `docs/system/`, or anywhere else populate their own values. Adopters without architectural documentation today resolve to absent paths — the agent operates read-only on whatever it can reach (potentially nothing) until the adopter authors their first architecture doc.

The convention does not bind the adopter; only their populated overlay does. `pkit init` (or future bootstrap tooling) may offer to populate the conventional values into a fresh `overlay.yaml` to lower the adoption-friction tax, but the placeholder-resolution machinery itself remains adopter-controlled.

### Invocation discipline

| Question | Answer |
|---|---|
| When does critic fire? | Pre-proposal on substantive drafts (every substantive draft); on-demand when the user requests it; periodic sweep is optional per adopter. Trivia and Q&A are exempt. |
| When does architect fire? | When a proposal touches multiple components, introduces a new abstraction, modifies a foundational decision, renames or relocates a kit-owned tree, or adds a cross-cutting concern. On-demand on request. Periodic is optional. |
| Ordering when both apply | Critic first (catches dumb mistakes cheap), architect second (architectural review on a critique-clean proposal). Sequential, not parallel. |
| Mode | Both advisory at v1. Promotion to gate per [COR-007]. |
| Coexistence with `methodology-reviewer` and `convention-compliance-reviewer` | Different stages and scopes. Critic fires *pre-proposal* on unbaked work; methodology-reviewer fires *on an authored artifact*; convention-compliance-reviewer fires *on a diff*. Architect fires on a proposal that touches the big picture; the others don't audit architecture. The four agents compose without overlap. |

### What both agents do not do

- **Neither writes code.** The primary agent (or human) authors. Critic and architect review and (architect only) edit overlay-resolved architecture docs.
- **Neither auto-rejects.** Both return structured advice. The primary agent decides what to do with it.
- **Neither replaces the existing reviewers.** `methodology-reviewer` and `convention-compliance-reviewer` continue to operate on their respective scopes (artifacts, diffs). The four agents form the project's structural-checks layer.

## Rationale

Authoring AI workflows that funnel every proposal through a human reviewer make the human the bottleneck and pay no premium for the AI's structural-checks capacity. The two failure modes the critic and architect address are exactly the ones where adding an AI-cycle is cheap and adding a human-cycle is expensive: "did I think this through?" (critic's domain) and "does this fit the bigger picture?" (architect's domain).

Splitting the role into two specialised agents — rather than one super-reviewer — matches the methodology's own role-decomposition discipline ([COR-006](COR-006-artifact-roles.md)): the critic has a narrow, universally applicable contract (adversarial second opinion); the architect has a different, narrower contract (architectural custodianship). Each is reusable and orthogonally invocable.

The advisory-not-gate posture at v1 follows [COR-007](COR-007-pattern-extraction.md). Gating is a strong intervention; advisory establishes the discipline and lets recurrence (proposals that ignore the agents' feedback to bad outcomes) demonstrate whether gating is needed. A gate-too-early agent slows the workflow without proportional value; an agent that never gates but is consulted reliably preserves human authority while paying the AI premium.

The overlay-resolved doc roots come from [COR-013](COR-013-agent-architecture.md)'s adopter-overlay pattern. Fixing a single path (`ARCHITECTURE.md` at the repo root, say) overfits the kit to the project-kit-source-tree shape and breaks any adopter whose documentation conventions differ. The placeholder + overlay shape is the universal contract; the adopter resolves locally.

### Alternatives considered

- **One reviewer agent covering both roles.** Rejected — different stages, different tools, different invocation patterns. The critic operates on unbaked proposals; the architect operates on the project's structural surface. Conflating them produces a reviewer with confused authority and ambiguous tools (read-only or write-on-architecture-docs?). Splitting matches the role-decomposition discipline.
- **Make architect a gate at v1.** Rejected — gating is a strong intervention. Advisory is the conservative starting point; recurrence promotes to gate per [COR-007].
- **Critic as a hook, not an agent.** Rejected — the critic's value is in *substantive review* (reading the proposal, the surrounding context, prior decisions, and producing structured critique). That is agent-shaped work, not a deterministic hook.
- **Architect operates kit-internally only.** Rejected — every adopter benefits from architectural custodianship of their own project. The methodology is universal; the agent shape is universal; the documentation layout is adopter-configurable via overlay.
- **Fixed `ARCHITECTURE.md` path at repo root.** Rejected — overfits to project-kit-source-tree-specific conventions. Different adopters keep architecture in different places (docs/architecture/, engineering/architecture/, docs/system/, a Notion mirror). Placeholder + overlay is universal.
- **No critic role at all; trust primary agent self-review.** Rejected — primary agents in current AI-mediated workflows demonstrably benefit from a structurally-independent second opinion. Self-review can't catch the issues self-review missed; that's the failure mode being addressed.

## Implications

- **Two new core-shipped agents** at `.pkit/agents/core/critic.md` and `.pkit/agents/core/architect.md`. Both follow the unified frontmatter schema from [COR-013](COR-013-agent-architecture.md); both pass the bidirectional reference-graph check.
- **Adopter overlay schema gains two placeholders**: `<architecture-docs>` and `<adr-records>`. Default values live in the kit-shipped overlay; adopters override in their project-side `.pkit/agents/project/overlay.yaml`.
- **CLAUDE.md (or adopter-equivalent) gains invocation wiring**. For project-kit specifically, the kit's own CLAUDE.md declares when the primary agent calls the critic and architect; for adopting projects, the adopter authors their own wiring. The methodology mandates the agents; adopters wire them to their workflow.
- **The four reviewer agents form a coherent stack**: `critic` (pre-proposal, on unbaked work), `architect` (architectural fit, on proposals touching the big picture), `methodology-reviewer` (per-artifact disciplines), `convention-compliance-reviewer` (per-diff conventions). Ordering when multiple apply on the same proposal: critic → architect → methodology-reviewer (on the authored artifact) → convention-compliance-reviewer (on the diff). Each catches a distinct failure mode.
- **The ADR decision space ([COR-025](COR-025-adr-decision-space.md))** lands alongside this record. The architect is the ADR custodian; the two records are coupled and ship together.
- **Existing `agent-author` skill applies**. New agents stamp via `pkit new agent core critic` and `pkit new agent core architect`; the skill walks the disciplines.
- **No breaking change for existing adopters.** The two agents are additive. Adopters who don't wire them keep working as before; agents the kit ships but the adopter doesn't invoke are quiescent.
- **Promotion to gate is a separate decision.** Recurrence (proposals that ignore the agents' feedback to consistently bad outcomes) is the signal that justifies promotion. Until then, advisory is the contract; primary agent (or human) authority is preserved.
- **The principle is methodology-level, not capability-level.** Both agents apply to any adopter doing AI-mediated authoring, regardless of which capabilities they've installed. They are core-shipped accordingly.
