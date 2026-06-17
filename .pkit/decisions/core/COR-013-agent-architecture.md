---
id: COR-013
title: Agent architecture
status: accepted
date: 2026-05-14
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

COR-006 establishes *agents* as one of five content shapes — the *who*, a persistent role with boundaries. The shape is named but its internal structure has not been settled. Adopters that already operate agent layers (the methodology framework's near-term validation targets) prove the value of the shape and surface a working pattern: a path-ownership matrix, coordinator and specialist roles, declared tool access, declared reading lists.

What remains to settle, and what this record fixes, is the *structural* layer that lets the methodology ship an agent backbone every adopter inherits — and lets adopters specialise on top of it — without either side hand-coding agent infrastructure each time. Five concerns interlock:

- How agents declare their references (paths, records, operations) so that the references survive area refactors, slug refinements, and adopter-specific paths.
- How agents *execute* operations whose implementations live in different sources (core, bundles, adapters, project).
- How agents reach adopter-specific paths that the methodology cannot enumerate.
- How the core / project split (per COR-001's content mechanisms) applies to agents specifically.
- How the agent matrix (the cross-cutting view of who owns what and who handles what task domain) is stored and kept consistent.

Each concern admits multiple viable shapes. Settling them piecemeal would force forward references between records; this record fixes them as one interlocking architecture.

## Decision

The methodology's agent layer is structured by six interlocking rules. The agents area is materialised as a first-class area per COR-011; agents declare references and operations in a unified frontmatter shape; a reference graph spans agents and skills with bidirectional consistency; a hook pattern decouples agents from concrete implementations; an overlay mechanism lets adopter-specific paths populate core-shipped agent templates at deploy time; and a small set of universal agents ships in core under the universal-applicability test.

### 1. The agents area

Agents live in a first-class area at `.pkit/agents/`, in the universal variant of COR-003 (`core/` for core-shipped content, `project/` for adopter additions). The area's README is the spec. Each agent is a self-contained directory carrying a single canonical file describing the role; the file's frontmatter holds machine-readable metadata, and the body is the role description and instructions.

Agent file content is harness-neutral per COR-006. Translation to a specific harness's expected deployment paths is the responsibility of that harness's adapter (per COR-005).

### 2. Unified frontmatter shape (agents and skills)

Agents and skills share a single frontmatter schema for the fields that participate in the reference graph. The shape:

```yaml
reads:
  paths:                        # filesystem paths (area docs, READMEs, project-root files)
  records:                      # decision-record IDs (resolved by ID, not slug)
  patterns:                     # adopter-overlay placeholders (see rule 5)
owns:                           # paths the artifact has write authority over (agents only)
needs:                          # hook names the artifact invokes (see rule 4)
answers:                        # hook names the artifact provides (skills only)
gates:                          # records whose accepted-status is load-bearing (skills only)
```

- `reads` lists the references the artifact consults at task time.
- `owns` lists paths whose modification is the agent's responsibility; every managed path has exactly one owning agent.
- `needs` and `answers` express the hook contract from rule 4.
- `gates` carries the acceptance-gate semantic from `.pkit/decisions/README.md` for skills; an entry there asserts the skill refuses to run unless the named records are `accepted`.

Fields that don't apply to a particular artifact are omitted. The body of the artifact is the role description (for agents) or the procedure (for skills); it cites the same references with a strict convention so the graph walker can extract them.

### 3. Reference graph and bidirectional consistency

Every reference an agent or skill carries is *declared in frontmatter* and *cited in the body*. The validator enforces both directions:

- **Forward**: every entry in `reads`, `owns`, `needs`, `answers` must appear in the body.
- **Backward**: every path / record-ID / hook name extracted from the body must be declared in frontmatter.
- **Closure**: every `needs:` entry has at least one matching `answers:` (skill) or `provides:` (per rule 4) in the installation.

The body's citation convention makes extraction unambiguous:

- Paths inside backticks: `` `.pkit/decisions/README.md` ``.
- Markdown link targets: `[text](.pkit/foo.md)`.
- Record IDs as literal tokens: `COR-005`, `PRJ-002` (matching `^(COR|PRJ)-\d+\b`).
- Anything inside fenced code blocks, HTML comments, or strikethrough does not count.

The CLI exposes graph operations through a `pkit refs` family: show outgoing references for an artifact, reverse lookup of who references a target, forward validation, bulk rename of frontmatter values across artifacts, detection of references to superseded or deleted targets, ID-to-path resolution. Validation runs at install / sync / on demand / in CI.

### 4. The hook pattern (agents executing in other areas)

Agents execute operations through *hooks* — named entry points that decouple the consumer (the agent) from the provider (a skill, command, or script). Agents declare `needs: [hook-name]`; providers declare `answers: [hook-name]` (skill frontmatter) or `provides: {hook-name: implementation}` (bundle / adapter `package.yaml`).

#### Provider value syntax

The implementation string in a `provides:` entry is parsed by prefix:

- `/<skill-name>` invokes the named skill through the harness's skill mechanism.
- Anything else is executed as a shell command.

#### Hook signature

A hook invocation takes positional string arguments and produces text on standard output. The implementation's exit code signals success (0) or failure. The per-hook contract — what arguments it expects, what its output looks like — is documented in the body / README of its provider; no typing system is imposed.

#### Hook naming

Two segments — `<topic>.<operation>` — for *contract* hooks that multiple providers in the same topic are expected to implement (bundle-agnostic). Three segments — `<topic>.<provider>.<operation>` — for *provider-specific* extensions that only one provider implements (the dependency is visible in the name). Lowercase kebab-case segments; dot separators. Regex: `^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*){1,2}$`.

Adopter-defined hooks use the reserved `project.*` topic.

#### Provider precedence

```
project > bundle > adapter > core
```

Same-tier collisions (two installed bundles providing the same contract hook) refuse rather than silently picking; the adopter must disambiguate by uninstalling one or adding a project-side override.

#### Unsatisfied needs

All `needs:` are required by default. Validation fires at install / sync / CI; runtime is the safety net. Optional-hook semantics are deferred to a future refinement once concrete cases for graceful degradation surface (per COR-007).

### 5. Adopter overlay for paths outside `.pkit/`

Agent references to adopter-specific paths (source code, project docs, project-root files) are expressed as *placeholder tokens* in agent templates, resolved at deploy time against a single overlay file shipped by the adopter.

#### Template form

Agent templates contain `<category-name>` placeholders wherever a reference would otherwise be a hardcoded adopter path:

```yaml
owns:
  - <code-paths>
reads:
  paths:
    - <project-root-docs>
```

#### Overlay form

A single file at `.pkit/agents/project/overlay.yaml` defines categories. Top-level keys are *default* categories applying to every agent unless overridden; a reserved `overrides:` key holds per-agent specialisations.

```yaml
code-paths: [src/...]
project-root-docs: [README.md, CLAUDE.md]
overrides:
  <agent-name>:
    code-paths: [tests/...]
```

#### Resolution

A deploy primitive — `deploy-agents.sh` for the Claude-Code adapter, with sibling primitives for future adapters — substitutes placeholders with the overlay's resolved values and writes the resulting agent file to the harness's expected location. The resolved file is what every downstream tool reads (the harness, the validator, the matrix renderer); the bidirectional consistency check operates on resolved paths, not placeholders.

Per-agent overrides *replace* the default value for that category (no merge); copying base entries into the override is the explicit way to extend rather than replace. Merge semantics are deferred per COR-007.

### 6. Backbone — what ships in core vs project

The core / project split for agents follows the universal-applicability principle (the same test that distinguishes COR records from PRJ records in `.pkit/decisions/README.md`; see the project's tracking work for lifting this test into a cross-artifact principle).

#### Core ships (the infrastructure floor)

- The agents area itself, with its README spec.
- The deploy primitive per harness adapter.
- The authoring command `pkit new agent <name>` paired with the `agent-author` skill (per COR-005).
- The `pkit hooks` and extended `pkit refs` CLI families for matrix, validation, and graph queries.

#### Core ships (the universal agents)

A small set of agents that pass the universal-applicability test ships in `core/`. Specific roles are inventory and belong in the area README, not this record; but the test is uniform: an agent ships in core iff its role makes sense in any adopting project.

#### Adopter authors (the project layer)

Agents tied to the adopter's domain — implementers, domain reviewers, customised coordinators — live in `.pkit/agents/project/`. Core ships the scaffold (`pkit new agent`); adopters fill it in with concrete paths and per-project judgement.

## Rationale

**Why a first-class area for agents.** Agents satisfy COR-011's criteria for an area: a named slice of the namespace with its own contract, README, and content layout. Without the area, agents would have to share storage with skills or docs, conflating the artifact shapes COR-006 explicitly distinguishes.

**Why the unified frontmatter shape spans agents and skills.** Both kinds participate in the reference graph; both make declarations about what they reference and what they answer. Splitting the schema across two shapes would force the graph walker to handle two normalisations and create asymmetric authoring ergonomics for what is structurally the same data. The fields that only apply to one kind (`owns` for agents; `answers` and `gates` for skills) are omitted from the other.

**Why references in frontmatter, not prose.** Bulk rename across hardcoded text references is sed-and-pray; bulk rename across structured frontmatter is YAML-aware and zero false positives. The frontmatter is queryable for reverse lookup and impact analysis. The body's job is the role / procedure description; the frontmatter's is the machine-readable declaration. The bidirectional consistency check keeps them in sync — neither can drift from the other.

**Why the body's citation convention is strict.** A loose convention forces the validator to parse arbitrary prose, with high false-positive risk for things that look like paths but aren't (sentences containing dot-separated tokens, version strings, etc.). Backticks-for-paths plus `(COR|PRJ)-\d+` for record IDs are unambiguous, parser-friendly, and authoring-natural — authors already write paths in backticks for rendering.

**Why hooks instead of bundle-embedded agents or universal-contract agents.** Bundle-embedded agents (one agent file per bundle) fragment the role layer; universal-contract agents (agents that call `<workflow>.promote` directly with no contract resolution) require a heavyweight contract definition upfront. Hooks split the difference: agents are universal (one file per role), bundles provide implementations through declarative bindings, contract definition emerges incrementally as bundles converge on shared hook names. Per COR-007, the formal contract document arrives when concrete recurrence justifies it; before then, hook names are the contract.

**Why string args and stdout output rather than typed JSON.** Agents reading text natively (the role's whole purpose) are more robust against stdout text than against potentially-malformed structured I/O. Per-hook typed signatures are an option for the future on a case-by-case basis; imposing JSON on every hook would force every shell-callable implementation through a marshalling layer that doesn't pay for itself when the consumer is an LLM agent.

**Why two- and three-segment hook names.** Two segments express *contract* hooks that multiple providers in a topic implement (the bundle-agnostic case); three segments make provider-specific extensions visible in the name itself, so an agent invoking a three-segment hook is *knowingly* bundle-locked. Forcing one form would either lose the abstraction (everything three-segment) or hide bundle dependencies (everything two-segment).

**Why `project > bundle > adapter > core` precedence.** This is the same precedence skills already follow when the deploy step picks `.pkit/skills/project/<name>` over `.pkit/skills/core/<name>`. Generalising the rule to hooks keeps the mental model consistent. Same-tier collisions refuse rather than picking silently because silent picking is the worse failure mode — an agent calling the wrong provider produces wrong outcomes without warning.

**Why required-by-default needs, with optional deferred.** Most agents really do require their declared hooks; making required the default forces honest declarations. Optional semantics add a flag and a runtime fallback path that pays for itself only when concrete graceful-degradation cases pile up — defer per COR-007.

**Why placeholders + deploy-time resolution rather than read-time substitution or no-overlay-at-all.** Read-time substitution forces every reader (the harness, validators, matrix renderer) to know about resolution and produces inconsistent views when readers differ in their handling. Deploy-time substitution produces a single resolved file that all readers see uniformly. No-overlay would force the core layer to ship adopter-path-free templates and leave every core-shipped agent unable to reference adopter content — making them less useful than competitive alternatives.

**Why a single overlay file with per-agent overrides, not per-agent overlay files.** Adopter categories are mostly shared across agents (project-root docs appear in every agent's reading list, etc.). Per-agent overlay files would duplicate the shared categories N times and produce drift. A single file with `overrides:` for per-agent specialisation handles the common case (shared categories) cleanly while supporting the rare case (one agent needs different paths).

**Why whole-category replacement on override rather than merge.** Merge semantics need a rule (append? prepend? deduplicate?) and produce surprises when an adopter expects "replace" and gets "extend". Replacement is the simpler primitive; an adopter who genuinely wants to extend writes the extended list inline. Per COR-007, merge can land later if real cases for "override should add to default" recur.

**Why the methodology is opinionated about core agents.** The methodology already ships opinion in decisions, rules, and skills — the no-shared-files invariant, the acceptance gate, the artifact-role discriminator, the bundle pattern. The agent layer is no different. Shipping zero universal agents would deliver only infrastructure; shipping carefully-chosen universal ones — those that pass the universal-applicability test — delivers methodology value out of the box. The specific roster of universal agents is inventory belonging in the area README; the rule that core ships *some* is a principle belonging here.

**Why no abstract bundle contract upfront.** A contract that pre-specifies the full vocabulary of workflow operations risks over-fitting to the first bundle and under-fitting to the second. Hook names converge organically as bundles ship; the formal contract document arrives when convergence is visible. This is the same evolutionary mechanism COR-007 names: pattern extraction after recurrence, not before.

### Alternatives considered

- **Per-area or per-bundle agent files** (one `pm` agent per workflow bundle). Rejected — fragments the role layer; an adopter switching bundles cannot reuse their agent definitions; core cannot ship a universal coordinator.
- **Prose-only references (no frontmatter declaration)** with parsing extracting references from body text. Rejected — bulk rename becomes sed-and-pray; the parser has to disambiguate genuine references from prose that resembles them; validation has high false-positive rates.
- **Centralised matrix document hand-maintained alongside per-agent files** (the working-but-drifty pattern in one adopter target today). Rejected — two sources of truth that drift in opposite directions; the auto-generated view from frontmatter is strictly better.
- **Per-agent overlay files** instead of one overlay file with per-agent overrides. Rejected — shared categories duplicate across files; drift across overlays produces inconsistent agents.
- **Typed (JSON) hook signatures from the start.** Rejected — adds marshalling overhead and brittleness for LLM consumers; per-hook typed contracts can opt in case-by-case when concrete needs surface.
- **Universal bundle contract defining all workflow primitives upfront.** Rejected — risks over-fitting to the first bundle; defer formalisation per COR-007 until convergence is observed.
- **Zero universal agents in core; core ships only infrastructure.** Rejected — gives up the opinionated stance the rest of the methodology already takes; adopters lose immediate value; the framework becomes a thin frame rather than a methodology.

## Implications

- **`.pkit/agents/` is materialised** as a universal-variant area per COR-011 with `{README.md, core/, project/}`. The README is the area's spec — frontmatter schema, body conventions, matrix shape, overlay format, deploy semantics.
- **`deploy-agents.sh` ships per harness adapter** — symmetric to `deploy-skills.sh`. Walks `.pkit/agents/{core,project}/`, applies the overlay, writes resolved files into the harness's expected location.
- **`new agent <name>` authoring command** ships paired with the `agent-author` skill per COR-005's pairing rule. The skill carries the slug-choice judgement, the body-drafting conventions, the citation discipline.
- **CLI extensions**: `<refs>` family (show, who-references, validate, rename, rot, graph, lookup) and `<hooks>` family (list, resolve, who-needs, who-provides). Folds into `<validate>` for PR-time CI integration.
- **Existing skills migrate** to the unified frontmatter shape. Their current `metadata.depends_on.{decisions,docs}` translates to `reads.{records,paths}` plus `gates:` for the records currently treated as gate-bearing. The migration surfaces existing drift (declarations not cited in the body) which the bidirectional check catches.
- **`package.yaml` schema for bundles and adapters gains an optional `provides:` block** for non-skill hook implementations.
- **Skill frontmatter schema gains `answers:`** for skills that ship as hook implementations.
- **CLAUDE.md surfaces the agent layer** so future sessions invoke the matrix conventions and reference-graph commands rather than reinventing per-author placements.
- **The universal-applicability principle**, which underwrites the core / project split for agents, is named explicitly across all artifact kinds in a separate refinement (tracking work in the methodology repo's audit of the existing core rules). This record applies the principle to agents; the explicit cross-artifact framing lives where the principle does.
- **No abstract bundle-contract record is needed yet**. Bundles converge on hook names through use; the formal contract document lands when concrete recurrence justifies it (per COR-007).
- **Composition / multi-agent workflow primitives are deferred per COR-007**. Orchestration logic lives in coordinator agents' bodies; a first-class composition artifact lands only when concrete multi-agent chains recur across enough adopters to make the primitive shape observable rather than speculative.
