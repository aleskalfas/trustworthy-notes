---
id: DEC-001
title: A producer agent authors code by conforming to an overlay-resolved project-conventions corpus
status: accepted
date: 2026-06-13
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

The kit ships reviewer agents that *check* work ([COR-024](../../../decisions/core/COR-024-critic-and-architect-agents.md)) but none that *produces* code. When an adopter's agent writes code today, it makes generic, session-to-session-inconsistent structural choices — scattered constants, duplicated utilities, over-commenting, non-modular layout — functional but not the clean, extensible code the adopter would author by hand. The model does not lack the patterns; it applies them inconsistently and not to *this project's* opinionated standard.

Four facts shape how a producer agent must be built. First, the project's coding conventions are **adopter-owned, project-specific prose** that accretes over time — they are not the agent. Second, they must survive this capability's uninstall (`rm -rf` of the capability subtree, per [COR-017](../../../decisions/core/COR-017-capability-pattern.md)) — so they cannot live inside the capability. Third, the conventions corpus will eventually have more than one consumer (this agent now; reviewers later), so *how an agent discovers conventions* is a seam, not a one-off. Fourth, any attempt to demonstrate that the corpus improves output requires the agent to be the *same* in the with- and without-corpus cases — so the agent must carry no coding opinions of its own.

## Decision

**The `software-engineering` capability ships one producer agent, `software-engineer`, that authors and edits code by reading the project's conventions corpus and conforming to it. The agent discovers the corpus through the overlay-resolved `<project-conventions>` category; its body carries no project-specific coding opinions; it self-checks mechanical conformance and defers judgment to the reviewer stack.**

1. **Producer agent.** `software-engineer` is a producer in the [COR-024](../../../decisions/core/COR-024-critic-and-architect-agents.md) review pipeline — it writes code; the reviewers check it. It is placed in this opt-in capability rather than core because authoring code is not universal to every adopter ([COR-026](../../../decisions/core/COR-026-agent-placement-by-discipline.md)).

2. **Overlay-resolved conventions seam.** The agent reads conventions through the `<project-conventions>` overlay category ([COR-013](../../../decisions/core/COR-013-agent-architecture.md)), **not** a hard-coded capability path. Consequences: the corpus is adopter-owned and lives wherever the adopter's overlay points (so uninstalling this capability never deletes it); and when conventions later come from multiple sources, only what the category resolves to changes — the agent (the consumer) does not. The cross-cutting shape of this seam is recorded in [ADR-013](../../../../docs/architecture/decisions/ADR-013-conventions-discovery-seam.md); this record fixes how *this* capability's agent consumes it.

3. **Conventions-thin body.** Project-specific structural opinions (naming, modularity, DRY, comments, …) live **only** in the corpus, never in the agent body. The body holds role, the read-conventions-first contract, the producer/checker boundary, and the composition with the reviewers — nothing more.

4. **Producer / checker boundary.** The agent **self-checks mechanical conformance** to the corpus (it is the only agent that reads the project corpus, so no other agent can). It **defers judgment** — design quality, abstraction choices, big-picture fit — to `critic` and `architect`. `convention-compliance-reviewer` covers only *universal* conventions and does **not** read the project corpus, so conformance to the corpus is the producer's responsibility, not a downstream catch.

5. **Empty-tolerance.** An absent or empty corpus is a normal early state, not an error. The agent announces "no project conventions found" and proceeds with ordinary good engineering judgment; it never invents project conventions to fill the gap.

## Rationale

**Why conventions-thin.** Two payoffs. It keeps the corpus the single source of truth — opinions in two places drift. And it keeps any with-corpus / without-corpus comparison honest: if the body encoded opinions, the without-corpus case would silently carry them, and one could not attribute improvements to the corpus. The agent is the *applier*; the corpus is the *authority*.

**Why an overlay seam, not a capability path.** A hard-coded `.pkit/capabilities/software-engineering/project/conventions/` would couple the adopter's accumulated conventions to this capability's lifetime — uninstall would destroy them — and would force a migration when conventions later come from many sources. The overlay category ([COR-013](../../../decisions/core/COR-013-agent-architecture.md)) is the mechanism the architect agent already uses for `<architecture-docs>`; reusing it costs no new machinery and avoids both the data-loss footgun and the later migration.

**Why the producer/checker split.** A producer that grades its own *design* loses the independence the reviewer agents exist to provide. But mechanical conformance to a declared corpus is not design judgment — and no other agent reads the project corpus — so that check has to sit with the producer. The split assigns each what only it can do.

## Implications

- **Opt-in.** Adopters who write code install this capability; those who don't, don't. The agent's project-level definition shadows the harness's generic same-named agent (Claude Code subagent precedence).
- **Adopter setup.** The adopter defines a `project-conventions` category in `.pkit/agents/project/overlay.yaml` pointing at where they keep conventions; `pkit agents reconcile` surfaces it when the agent references it and the overlay does not yet define it. No capability-specific category is seeded into the core overlay.
- **Documentation currency.** The agents README's core/project split previously classified `software-engineer` as a project-layer example; it is now shipped by this capability. Reconciled in the same change-set.
- **Deferred** (each pending real evidence, per [COR-007](../../../decisions/core/COR-007-pattern-extraction.md)): the conventions *content* (accretes via an empirical capture loop), cross-capability convention *aggregation* (a consumer reading the union across many installed capabilities), and capability `depends_on`. The seam is designed so these land without changing the consumer.
