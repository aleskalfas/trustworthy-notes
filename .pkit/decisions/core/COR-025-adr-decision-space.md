---
id: COR-025
title: ADR decision space — adopter's architectural decisions as a third namespace alongside COR and PRJ
status: accepted
date: 2026-05-27
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

The methodology today defines three decision-record contexts:

| Existing | Scope | Lives at | Owner |
|---|---|---|---|
| **COR** | Universal methodology principles | `.pkit/decisions/core/` | Methodology maintainers |
| **PRJ** | Project-specific decisions (workflow, tooling, distribution conventions) | `.pkit/decisions/project/` | Adopter maintainers |
| **DEC** (capability-scoped) | Per-capability principles | `.pkit/capabilities/<cap>/decisions/` | Capability maintainers |

Adopters running this methodology rapidly accumulate **architectural decisions** that don't fit cleanly into PRJ:

- "We use a microservices boundary between the auth service and the API gateway."
- "Postgres is the system-of-record; Redis is cache-only."
- "The recorder subsystem owns session state; the gateway is stateless."
- "We deploy via Kubernetes with one namespace per environment."

These are *architectural* — they pin the project's shape, abstractions, integration patterns, technology choices. They're project-specific (don't propagate; aren't methodology principles) but they're a different *kind* of project decision from PRJ records (which capture how-we-work conventions like versioning policy or branch-naming).

Two failure modes today:

1. **Architecture decisions land informally** — in code comments, in PR descriptions, in README files, in tribal knowledge — without a stable artifact that captures the *why* and the *alternatives considered*. New contributors and future-maintainers cannot reconstruct the reasoning.
2. **PRJ records become a mixed bag.** Some PRJ records pin workflow (PRJ-002 hybrid bump policy); others pin architecture (PRJ-003 implementation-language Python). Reading the PRJ corpus, the architectural decisions are hidden among workflow conventions. The two are coherent but mixed; an architect surveying "the project's architecture" cannot filter for just that.

The well-known Architecture Decision Record (ADR) pattern (Michael Nygard's *Documenting Architecture Decisions*, 2011) directly addresses this gap. ADRs are short, contextual records of architecturally-significant decisions, stored in version control alongside the code they describe. Adopting ADRs as a third decision space — alongside COR and PRJ — gives the methodology a dedicated home for architectural decisions, distinct from both universal methodology principles (COR) and project workflow conventions (PRJ).

The `architect` agent introduced in [COR-024](COR-024-critic-and-architect-agents.md) is the ADR custodian by design. The two records are coupled: COR-024 defines the agent; this record defines the decision space the agent operates on.

## Decision

ADR records are a third decision-record namespace at the adopter level, parallel to PRJ but architecture-specific. The methodology ships the convention; adopters author ADRs as their architecture evolves.

### Scope test — pick the namespace before the discriminator

Before applying the PRJ-vs-ADR table below, decide whether the record is adopter-scoped at all. The methodology defines four decision-record contexts; the choice between them is layered:

1. **First test — scope.** Does the rule apply to *any adopter of this methodology* (a universal principle about the methodology corpus, the agent/skill/decision contract, or any artifact the methodology ships)? Or does it apply only to *this one project*?
   - **Universal** → **COR** (`.pkit/decisions/core/`).
   - **Project-specific** → continue to the second test.

2. **Second test — capability-scoped.** Is the rule specific to one installed capability's discipline (e.g., a project-management classification, an evidence-management retention rule)?
   - **Capability-internal** → **DEC** in that capability's `decisions/` folder.
   - **Project-wide** → continue to the third test.

3. **Third test — project-side discriminator (the PRJ-vs-ADR table below).** Apply the question-shape test (workflow / process / tooling = PRJ; architecture / boundary / technology = ADR).

The concrete test that resolves the first level: *"If another adopter of this methodology authored a similar artifact (a new capability, a new agent, a new skill, a new project), would they need to know this rule?"* If yes → COR. If no → adopter-scoped (DEC or PRJ or ADR per the lower tests).

Worked examples:

| Rule | First test | Second test | Third test | Carrier |
|---|---|---|---|---|
| "Discipline-implying agents live in the capability that ships the discipline" | Universal (applies to any adopter authoring a capability) | — | — | COR |
| "Project root resolves implicitly from cwd via `git rev-parse`" | Project-specific (about project-kit's CLI runtime) | Not capability-scoped | Architecture (system shape, contract) | ADR |
| "Pre-1.0 hybrid version-bump policy" | Project-specific | Not capability-scoped | Workflow (versioning process) | PRJ |
| "Issue body must carry a Closes-line linking to the parent" | Project-specific *and* discipline-specific (project-management capability) | Capability-internal | — | DEC (capability) |

A rule that *feels* architectural but applies to any adopter authoring an artifact is universal — it lands as a COR, not an ADR. The "architectural" flavour is about the shape of the rule (boundaries, integration patterns); scope decides the carrier.

### Distinct from PRJ

| Aspect | PRJ | ADR |
|---|---|---|
| Scope | Project-specific decisions of any kind (workflow, tooling, distribution, conventions, architecture-flavoured choices that touch tooling) | Project's architectural decisions specifically — system boundaries, technology choices, integration patterns, key abstractions, deployment topology |
| Typical questions answered | "How do we work?" "What tooling do we use?" "What's our versioning policy?" | "What did we build?" "Why these boundaries?" "Why this technology over alternatives?" |
| Examples | Hybrid bump policy; branch-naming format; CLI binary path; package-manager choice | "Auth service is separate from API gateway"; "Postgres is the system-of-record"; "Stateless gateway pattern"; "One Kubernetes namespace per environment" |
| Owner | Adopter maintainers | Adopter maintainers; architect agent is the custodian |

A decision may legitimately fit either space; the discriminator is the *question being answered*. "What technology do we use for X" is architectural (ADR). "What versioning convention do we follow for our releases" is workflow (PRJ). When both flavours apply, the methodology preference is: pin the architecturally-significant aspect as an ADR; pin the workflow-mechanical aspect as a PRJ; cross-reference both.

### Location — overlay-resolved, conventional default `docs/architecture/decisions/`

ADR records live where the adopter declares their architecture documents live. Per [COR-024](COR-024-critic-and-architect-agents.md)'s `<adr-records>` placeholder, the location is overlay-resolved. The methodology documents the **conventional resolution** in COR-024; adopters populate their `.pkit/agents/project/overlay.yaml` to opt in:

```yaml
# .pkit/agents/project/overlay.yaml — adopter populates with the conventional value
adr-records:
  - docs/architecture/decisions/
```

The conventional resolution `docs/architecture/decisions/` matches the well-known ADR-community layout. Adopters who store architecture docs elsewhere populate their own value.

Rationale for the project-side location (rather than `.pkit/decisions/adr/`): ADRs describe the *adopter's project*, not the methodology that the kit installs. The methodology's namespace (`.pkit/`) is methodology-shaped state; the adopter's architecture lives in the adopter's own documentation tree. Pinning ADRs under `docs/` keeps them with the rest of the project's documentation.

### Propagation isolation — kit ADRs never leak to adopters

The location choice (outside `.pkit/`) automatically secures a critical property: **ADRs authored in project-kit's own source tree never propagate to adopters who install the methodology**.

The mechanism:

1. `pkit sync` operates only on the kit-shipped surface under `.pkit/`. Files outside that tree are never read or written by sync (per [`.pkit/decisions/README.md`](../README.md) "The no-shared-files invariant").
2. ADR records live at the adopter's `docs/architecture/decisions/` (or wherever the overlay resolves), which is **outside `.pkit/`** by design.
3. Therefore: project-kit-the-project's own ADRs (if it authors any, in its own `docs/architecture/decisions/`) are project-kit-the-project's state — never in the sync propagation surface; never copied to an adopter; never overwritten when an adopter re-syncs.

This is the same isolation property PRJ records enjoy (they live under `.pkit/decisions/project/`, which sync treats as project-owned), realised through a different mechanism: PRJ is inside `.pkit/` but in a project-owned subtree; ADRs are entirely outside `.pkit/`. Both paths get the no-leakage guarantee.

The corollary: project-kit's own architectural decisions stay in project-kit. Each adopter authors their own ADRs from scratch — no cross-contamination, no "this ADR doesn't make sense for our project" cruft inherited from the kit source.

### Schema — uniform with COR/PRJ/DEC

ADRs use the same four-section schema as COR, PRJ, and DEC records (per [`.pkit/decisions/README.md`](../README.md)):

```markdown
---
id: ADR-NNN
title: <short imperative title>
status: proposed | accepted | superseded
date: YYYY-MM-DD
author: <author>
supersedes: ADR-NNN     # when superseding a prior ADR
superseded_by: ADR-NNN  # when superseded
---

## Context
## Decision
## Rationale
## Implications
```

**Why not Nygard's classic three-section shape (Context / Decision / Consequences)?** Uniformity with the existing decision spaces. Adopters already learn the kit's four-section shape for COR/PRJ/DEC; introducing a fifth file shape for ADR creates cognitive overhead without proportional value. The four-section schema covers Nygard's content (Rationale + Implications subsume Consequences with more discipline).

### Numbering — `ADR-NNN`, per-adopter

ADR records use a three-digit zero-padded prefix `ADR-NNN`, independent sequence per adopter. The first ADR an adopter authors is `ADR-001`, regardless of which COR/PRJ/DEC numbers exist. Like PRJ, ADRs do not propagate between repositories.

### Acceptance gate

Same acceptance gate as COR/PRJ/DEC ([`.pkit/decisions/README.md`](../README.md) "The acceptance gate"): ADRs land as `proposed`; promotion to `accepted` is a separate gesture. Implementation work citing a `proposed` ADR is forbidden until acceptance.

### Authoring — `pkit new decision` extension required

The existing `pkit new decision <namespace> <slug>` command supports `core` and `project` namespaces. ADR support requires extending the command to accept the ADR namespace. Two implementation paths:

1. Add `adr` as a third explicit namespace: `pkit new decision adr <slug>`. The command stamps the next ADR-NNN at the overlay-resolved location.
2. Extend the command to read the overlay and resolve ADR path: `pkit new decision adr <slug>` uses `overlay.adr-records[0]` as the target directory.

Path 2 is the universal one (works for adopters with non-default overlay). The command extension lands as part of the implementation work of this decision.

### Custodianship — architect agent

The `architect` agent from [COR-024](COR-024-critic-and-architect-agents.md) is the ADR's primary custodian:

- **Authors** new ADRs when an architectural decision is made (or reviews adopter-authored ADRs for completeness and architectural fit).
- **Audits** the ADR set periodically against the running state of the project; flags drift (a decision recorded as accepted that no longer matches reality; an architectural pattern in the code with no corresponding ADR).
- **Owns** the `<adr-records>` overlay-resolved directory per its frontmatter `owns:` clause.

Adopters may also author ADRs directly — the architect's custodianship doesn't preclude humans. The agent's role is to ensure the discipline doesn't drift, not to monopolise authorship.

### No retroactive backfill

When an adopter installs the architect agent and adopts ADRs, the methodology does **not** require backfilling existing architectural decisions into ADR form. Going forward, new architectural decisions land as ADRs; historical decisions live where they live (in PRJ records that were really architectural, in code comments, in `README.md`, in tribal knowledge). An adopter who wants to backfill may; the methodology doesn't demand it.

### Coexistence with capability DECs

Capability DECs (e.g., the pm capability's `DEC-NNN` series at `.pkit/capabilities/project-management/decisions/`) remain capability-scoped: principles the capability ships and adopters consume. ADRs are adopter-scoped: decisions the adopter makes about *their project*. The two don't overlap — a capability's decisions are part of the capability's contract; an adopter's ADRs are part of the adopter's project surface.

## Rationale

The PRJ namespace as it stands is a *catch-all* for project-side decisions, which is fine while the project is small but begins mixing concerns as the project's architectural surface grows. Architecture has its own audience (the architect, future maintainers, on-call engineers), its own typical questions (boundaries, technology, patterns), and its own typical reviewers (the architect agent introduced in [COR-024], external technical reviewers). Giving architecture its own namespace surfaces those decisions for that audience without diluting PRJ's role as the workflow-conventions home.

The Nygard ADR pattern is mature and well-understood; adopters who recognise it carry transferable knowledge from prior projects. The methodology's gain is that the *discipline* (one decision per record, structured Context / Decision / Rationale / Implications, versioned alongside code) was already proven before ADRs entered the methodology's surface. The methodology adds the integration: ADRs participate in the reference graph, the acceptance gate applies, the architect agent is the custodian.

Putting ADRs under the adopter's `docs/` tree (not `.pkit/`) keeps the methodology surface and the adopter's project surface cleanly separated. The methodology's job is to *enable* architectural-decision discipline; it doesn't own the resulting records. The same separation already applies to PRJ (which lives under `.pkit/decisions/project/` because it captures adopter-decisions about how the kit is used — but those are *kit-aware* decisions). ADRs are not kit-aware; they're project-architectural and belong with the rest of the project's docs.

### Alternatives considered

- **No new namespace; use PRJ for everything.** Rejected — PRJ becomes a catch-all that hides architectural decisions among workflow conventions. The audience for architecture decisions is different from the audience for workflow decisions; merging them serves neither well.
- **Architecture as a fourth `kind` field within PRJ records.** Rejected — adds metadata complexity without solving the audience-separation problem. A reader looking at "architectural decisions for this project" still has to filter the PRJ corpus by a soft field.
- **Use Nygard's three-section schema (Context / Decision / Consequences).** Rejected — uniformity with COR/PRJ/DEC's four-section schema is worth more than alignment with the external ADR community's exact format. Nygard's "Consequences" maps cleanly to Rationale + Implications.
- **ADRs under `.pkit/decisions/adr/` (kit-namespace).** Rejected — ADRs are about the adopter's *project*, not about the methodology installed in the project. Putting them under `.pkit/` blurs the kit-vs-project separation. `docs/architecture/decisions/` is the standard convention.
- **Numbering shared with PRJ.** Rejected — different prefix, different audience, different lifecycle. An ADR may be superseded by an architectural rework that doesn't reach PRJ; a PRJ record's revision is independent of architectural state.
- **No custodian agent; just discipline.** Rejected — discipline without a custodian drifts. The architect agent introduced in [COR-024](COR-024-critic-and-architect-agents.md) is the right custodian; coupling the two records expresses the relationship explicitly.
- **Defer the ADR space to adopter discretion (no methodology surface).** Rejected — every adopter doing non-trivial software has architectural decisions; the methodology should provide the convention so adopters don't reinvent it (poorly, inconsistently, per-adopter).

## Implications

- **New decision namespace at adopter project level**. Default location `docs/architecture/decisions/`; adopter overlay resolves `<adr-records>` (placeholder defined in [COR-024](COR-024-critic-and-architect-agents.md)).
- **`pkit new decision` command extension**. The command accepts a new namespace argument (`adr`) and resolves the target directory via the agent overlay. Implementation ships in the same PR or follow-on PR alongside this record's acceptance.
- **Schema and acceptance gate are inherited**. ADRs follow the same four-section schema, same acceptance gate, same superseding model as COR/PRJ/DEC. The reference graph and `pkit refs validate` operate over the ADR space uniformly.
- **Architect agent's custodianship is the operational layer**. Per [COR-024](COR-024-critic-and-architect-agents.md), the architect's frontmatter `owns:` resolves to the ADR location; the agent has write authority over ADR records.
- **No migration**. The ADR namespace is additive; existing PRJ records stay where they are. Adopters who want to migrate architecturally-flavoured PRJs to ADRs may do so (one at a time, as the records come up for revision) but the methodology doesn't require it.
- **Adopter doc impact**. The methodology's adopter-facing docs (`.pkit/decisions/README.md`) gain a brief section on ADRs as the third namespace, the agent's role as custodian, and the overlay-resolution mechanism for the location.
- **Coexistence with project-kit-the-project itself**. project-kit may or may not author ADRs for its own architectural choices — many project-kit decisions are already captured as PRJ records (project-kit is the methodology framework's source tree, so its decisions about *itself* tend to be workflow-shaped). The methodology ships the ADR namespace for adopters; whether project-kit's own architecture warrants ADRs is a separate question for a PRJ record to settle.
- **The principle is universal**. Every adopter of this methodology benefits from a dedicated architecture-decision namespace, regardless of capability composition. ADRs are core-methodology-shaped.
