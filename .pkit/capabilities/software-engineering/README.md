# software-engineering capability

Formalises the discipline of **authoring code under a project's own conventions**. It ships a *producer* agent, `software-engineer`, that writes and edits code by reading the project's conventions corpus and conforming to it — so the code an agent produces is clean, stable, and extensible by *this* project's standards, consistently across sessions, without the conventions being re-explained each time. Install it in any project where agents write code; skip it where they don't (it's opt-in for exactly that reason, per [COR-026](../../decisions/core/COR-026-agent-placement-by-discipline.md)).

## What this capability ships

When an adopter runs `pkit capabilities install software-engineering`:

- `agents/software-engineer.md` — the producer agent. Reads the project's conventions corpus (the overlay-resolved `<project-conventions>` category) and conforms to it; carries no coding opinions of its own; self-checks conformance and defers judgment to the reviewer stack (`critic` / `architect` / `convention-compliance-reviewer`). Its project-level definition shadows the harness's generic same-named agent.
- `decisions/DEC-001-producer-agent-and-conventions-seam.md` — the discipline's invariant: the conventions-thin producer, the overlay-resolved seam, the producer/checker boundary, empty-tolerance.

It deliberately ships **no conventions content** — the conventions corpus is adopter-owned and accretes over time (see Adopter setup).

## Adopter setup

Install:

```
pkit capabilities install software-engineering
```

After install:

- **Define where your conventions live.** Add a `project-conventions` category to `.pkit/agents/project/overlay.yaml`, pointing at the path(s) where you keep your code conventions. `pkit agents reconcile` will surface this category as referenced-but-undefined and can stub it for you; the `software-engineer` agent reads whatever it resolves to.
- **An empty corpus is fine to start.** With no conventions defined yet, the agent behaves as a careful generalist and says so. Conventions accrete over time (e.g. via a generate → catch → encode loop); the agent picks them up as the corpus fills — no re-install needed.

## Citing this capability's decisions

Inside this capability's own content, cite decisions by their filename stem: `[software-engineering:DEC-001-producer-agent-and-conventions-seam]`. Other capabilities and adopter content use the same form.

## Dependencies

- The kit's **agents area + overlay mechanism** ([COR-013](../../decisions/core/COR-013-agent-architecture.md)) — the agent is deployed and its `<project-conventions>` placeholder resolved by `deploy-agents.sh`.
- The **reviewer stack** ([COR-024](../../decisions/core/COR-024-critic-and-architect-agents.md)) — `critic` / `architect` / `convention-compliance-reviewer` are how the producer's work gets checked. They ship in core; no separate install.
- No other capability is required. (Convention *content* and any cross-capability composition are out of scope here — see DEC-001's Implications.)
