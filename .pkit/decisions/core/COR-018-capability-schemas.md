---
id: COR-018
title: Capabilities adopt the schemas mechanism as their engine-data layer
status: accepted
date: 2026-05-20
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

A capability bundles a discipline: decisions that explain principles, skills and agents that operationalise them, templates the discipline shapes, scripts the discipline runs. Some of the discipline's content is *qualitative* — principles, rationale, when-to-apply judgement. That content belongs in decisions, where prose is the right carrier.

Other content is *quantitative* or *structural*: regexes a validator runs, state names a transition walker enumerates, field lists a body checker iterates, mapping tables a classifier indexes. This content has to be consumed by code — skills, agents, and scripts that execute the discipline mechanically. Three places it can live:

1. **Hardcoded in the engine** — the skill body, the agent prompt, the script source contain the literal rules. Every methodology change requires editing the engine; engine becomes specific to one version of one methodology.
2. **Parsed from decisions at runtime** — the engine reads `DEC-NNN-*.md` and extracts the rule from prose. Brittle (natural-language parsing), expensive, no clean separation between rationale and data.
3. **Structured data files** — the engine reads a file in a known format, in a known location, with a known shape. Engine stays methodology-agnostic; methodology changes become data edits.

COR-017 named `schemas/` as a standard subdirectory of every capability — establishing option 3 as the intent — but defined nothing about what those files are. The `.pkit/schemas/` area now defines the **schemas mechanism** generally: YAML data files paired with JSON Schema companions, with conventions for shape, naming, cross-schema references, and consuming-code expectations. This record settles whether capabilities adopt that mechanism and how the adoption integrates with the rest of a capability's artifacts.

## Decision

**Capabilities adopt the schemas mechanism (defined in the `.pkit/schemas/` area) as their engine-data layer.** A capability with mechanically-consumable rules encodes them as schemas under `<capability_root>/schemas/`; consuming skills, agents, and scripts read those schemas at runtime. The mechanism's conventions (YAML shape, JSON Schema companion, file naming, patterns) are inherited from the area; this record adds the *capability-specific* rules about how schemas fit alongside the capability's other artifacts.

### How schemas fit alongside other capability artifacts

Within a capability, schemas sit alongside decisions, skills, agents, scripts, and templates. Each artifact carries a distinct slice of the discipline:

| Artifact | Carries | Audience | Changes when |
|---|---|---|---|
| **Decision** (`decisions/DEC-NNN-*.md`) | The *why* — principle, rationale, alternatives | Humans deciding whether the discipline fits | The principle changes |
| **Schema** (`schemas/<name>.yaml` + `.schema.json`) | The *what* — enumerations, regexes, transition graphs, field lists | Engine code at runtime | The concrete rule changes |
| **Template** (`templates/*.md`) | The user-facing artifact shape (issue body, PR template, etc.) | Humans + runtime filling it in | The shape of produced artifacts changes |
| **Skill** (`skills/<name>.md`) | A procedure walkthrough | Runtime invoking the skill | The procedure changes |
| **Agent** (`agents/<name>.md`) | Orchestration logic across skills | Runtime | Orchestration changes |
| **Script** (`scripts/<name>.{py,sh}`) | Deterministic operation (validator, walker, generator) | Skills/agents invoking it | The operation changes |

The decision explains why a rule exists; the schema enumerates the rule's content; the skill or script consumes the schema and acts on it; the agent orchestrates. Each artifact has one job and one change cadence.

### How schemas connect to consumers

Schemas exist to be consumed. The kit tracks consumption through the reference graph established by COR-013:

- **Skills and agents declare the schemas they rely on** via `reads.paths` in frontmatter, and cite them in body prose. The bidirectional rule (per COR-013) keeps declaration and prose in sync.

- **Scripts don't carry their own declarative frontmatter.** When a script reads a schema, the *orchestrating skill or agent* — the artifact that invokes the script — is responsible for declaring both the script and the schemas the script depends on. The orchestrator is the source of truth for what's involved in its operation.

- **A schema is non-orphan if any consumer is reachable to it through the reference graph** (direct or transitive — agent → skill → schema counts the same as skill → schema). Schemas slot in as a new node type in the existing COR-013 graph.

- **Orphan schemas surface as validator issues.** A schema that no consumer references is a smell — either the consumer was lost, the schema was meant to be consumed but isn't yet wired up, or it's dead weight. The kit's validator flags this, the same way it flags an unreferenced storyboard or a body-cited record without a frontmatter declaration.

### Support scripts as a natural pattern

A data-driven engine often wants supporting tooling: a validator that checks a schema's content makes sense at the methodology level (e.g., "the state machine has no orphan states", "every title regex compiles"), a tester that exercises behaviour, a migration that bridges schema versions. These live in the capability's `scripts/` directory like any other capability-shipped script. The kit doesn't mandate them; the pattern emerges naturally from the engine/data split and capability authors ship as much or as little supporting tooling as the discipline needs. Consuming skills/agents declare the scripts they invoke just like any other reference.

(Note: the schema's *shape* validation — does the YAML match its companion JSON Schema — is the schemas mechanism's concern, not the capability's. The capability's support scripts handle *content* validation that goes beyond shape.)

## Rationale

**Why capabilities adopt the schemas mechanism.** A capability without schemas hardcodes its rules in skill/agent prose (Option 1 above) and pays the drift tax every time the methodology evolves: edits to multiple files, no single source of truth, no machine-checkable shape. Schemas resolve this by carrying the rules as data the engine reads at runtime — the rule a decade of similar tools converged on (linters configured by `.eslintrc`, build tools by `Makefile`, package managers by lockfiles, etc.). The cost of authoring a schema is small; the structural payoff is large.

**Why path-reference + transitive reachability for the consumption model.** The kit already tracks references this way for every other artifact (per COR-013). Reusing the same graph means schemas slot in as a new node type with no new mechanism. The alternative — schemas declaring their consumers, or no declarative tracking at all — would either fragment the reference model or lose the ability to detect dead schemas. Transitive reachability (agent → skill → schema) is necessary because orchestration layers genuinely don't read schemas directly; their skills do. Direct-only would force every agent to redundantly declare schemas its skills already declare, with no information gain.

### Alternatives considered

- **Hardcode rules in engine code.** Rejected — drift across multiple files; no single source of truth; methodology changes require engine edits.
- **Parse rules from decisions at runtime.** Rejected — natural-language interpretation is brittle for deterministic code paths and expensive when the consumer pays per invocation.
- **Schemas declare their consumers** (instead of consumers declaring schemas). Rejected — inverts COR-013's reference model for no information gain; would fragment the validator's graph.
- **No declarative tracking at all** (schemas just exist; consumers find them ad hoc). Rejected — orphan schemas become invisible; engine/data coupling can't be verified.
- **Define schemas inline within decisions.** Considered. Rejected as a separate failure mode of "parse from decisions": couples prose rationale to machine-readable data; format conventions can't apply cleanly to embedded fragments.

## Implications

- **Capability architecture splits cleanly into engine + data.** Skills, agents, and scripts implement *how*; schemas describe *what*. A capability shipping a data-driven engine has a clear contract on both sides; schemas are the contract.

- **Methodology evolution becomes data evolution.** Adding a state, changing a regex, introducing a new issue type — all become schema edits. The engine code stays put. The capability's version bumps when adopter-visible behaviour changes; the bump's surface is schemas (and DECs that explain new principles), not skill bodies.

- **Consumers handle their own parse.** A skill that reads a schema opens the file, branches on `schema_version`, keys into the mapping, validates locally against its needs, and surfaces errors via its own error path. The schemas mechanism standardises the *shape* and provides the JSON Schema companion for validation; per-consumer parse remains the consumer's responsibility.

- **The validator's reference graph extends to schemas.** Per COR-013's bidirectional pattern, every schema in a capability must be reachable from at least one consuming artifact (skill, agent, or — transitively — script invoked by a skill/agent). Orphans surface as issues the same way unreferenced storyboards do today. The validator extension is a follow-on PR but the rule is fixed by this record.

- **Schema evolution within a capability uses the `schema_version` lever.** When a schema's shape changes incompatibly, bump the integer in both the YAML and its JSON Schema companion; consuming code adds a case for the new version. Adopter-side state migration across schema versions remains a separate concern handled by the kit's migration framework (COR-010 + COR-017's capability migrations tier).

- **The mechanism is reusable beyond capabilities.** Adopter projects (or future kit features) that want to use the schemas mechanism for their own data do so by following the area's conventions; the tooling (IDE integration, language-level validators) works identically. This record only commits *capabilities* to the mechanism; other adopters declare their own adoption in their own records when they choose to use it.
