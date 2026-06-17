---
id: COR-016
title: Design scripted scenarios via storyboard
status: accepted
date: 2026-05-17
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

The methodology accumulates places where a tool runs a **scripted interaction** with a human user — a designed sequence of turns, gates, prompts, and mutations. Today the most concrete instance is an agent driving a workflow (a review agent walking a human through methodology acceptance). Tomorrow the same shape can show up in a CLI command with a non-trivial flow, an interactive migration script, a bundle setup wizard, or a tutorial that walks a contributor through their first task. The actor differs; the *shape of the design problem* does not.

Without a named convention, every author of such an interaction re-invents the format — different prose, different rigor, different verifiability. Some authors compress the interaction into terse procedural text that elides critical dialogue; others embed so much dialogue inside the implementing artifact (agent body, CLI prompt code, migration script) that the role description gets buried. Either way, the design ambiguities surface at implementation time when they're more expensive to address.

A **storyboard** — a document that walks each scenario with Trigger, Preconditions, an example Walkthrough, and Behind-the-scenes mutations — addresses this directly. Writing dialogue forces ambiguities to surface; treating each scenario as a unit makes edge cases first-class; separating *what the actor says* from *what really happens* keeps the spec verifiable before any implementation is written. The pattern is general — any scripted human-facing interaction benefits from being designed this way.

This record **names the principle in its general form** and **scopes the tooling and location convention to its first concrete application class: agent-driven scripted scenarios.** Other application classes (CLI flows, interactive migrations, setup wizards, tutorials) can adopt the storyboard template under analogous sibling conventions as they emerge; a future sibling record can extend the tooling to those cases when there's real evidence to ground them.

## Decision

### The general principle

A **scripted interaction scenario** is a sequence of turns between an implementing artifact and a human user where the methodology designs the dialogue: specific prompts the artifact issues, specific gates it enforces, specific mutations behind each user input. Scripted scenarios are distinct from *judgment-driven* interactions, where the actor improvises its dialogue from context — even if those interactions are also turn-based.

The signal is concrete: *do I find myself writing scripted dialogue for a specific workflow?* If yes, the workflow is a scripted scenario worth storyboarding. The record does not enumerate sub-criteria (gates, state transitions, confirmation patterns) — those are properties many scripted scenarios share but are not themselves gates on the recommendation.

When authoring a scripted scenario, the author is **recommended** to write a storyboard before the scenario is implemented in any artifact body. The storyboard is the long-form behavioral source; the implementing artifact declares its storyboards in frontmatter and loads them at task time via its `Read` tool. The artifact body is the compact runtime entry point — it states the role, declares which storyboards it drives, and instructs the runtime to load and follow them. The methodology surfaces the recommendation at authoring time without enforcing it — authors choose whether to apply the discipline.

### First application class: agent-driven scenarios

The concrete tooling and location convention this record commits to is the case where the implementing artifact is an **agent** (per COR-013). Agent-driven scripted scenarios are the only application class with a working example today; the tooling, location, and authoring flow ship for this class.

Examples within the agent class:

- **Scripted scenarios.** A review agent walking a human through methodology acceptance; an onboarding flow for new contributors; a code reviewer driving a security-PR-review walkthrough; an interactive coordinator confirming scope before delegating.
- **Not scripted scenarios.** A code reviewer responding to general diffs with judgment; a research assistant exploring a topic; a troubleshooting helper diagnosing context-dependent errors. These may have turns, but the dialogue is improvised, not designed.
- **Borderline / mixed.** The same agent can run both. A code reviewer doing free-form review most of the time, plus a scripted scenario when a security-sensitive PR shows up — storyboard the scenario, leave the rest to judgment.

### Other application classes

Other artifacts that could host scripted scenarios (CLI commands with non-trivial flows, interactive migration scripts, bundle install wizards, tutorial walkthroughs) are recognized as candidates but not tooled here. When such a case arises in practice, the storyboard template applies analogously — sibling to the implementing artifact, source-only lifecycle, same three-layer structure — and a sibling record can extend the kit's tooling to that class.

### Storyboard structure

A storyboard file may carry one or many scenarios. The structure is general — it applies to any application class. Every storyboard has three layers:

1. **Framing** (file head) — what set of scenarios the storyboard covers, what global state the scenarios operate on, what the user-facing entry points are.
2. **Tone rules** — behavioral norms applied across every scenario in the file: cadence (one thought per turn), turn length (1–3 sentences), confirmation style, when to pause for input.
3. **Scenarios** — each scenario carries:
   - **Trigger** — what activates the scenario.
   - **Preconditions** — state that must hold for the scenario to apply.
   - **Walkthrough** — example dialogue interleaving the actor's turns and user turns; italics for behind-the-scenes narration to the user.
   - **Behind the scenes** — file mutations, state checks, and side effects the implementation must perform.

Edge cases (the actor refusing to act, the user trying to bypass a gate, returning users with prior state) are first-class scenarios, not afterthoughts in prose.

### Location and lifecycle

The convention is **sibling-to-the-implementing-artifact**. A storyboard lives next to the file the scenario will be implemented in, in folder-form per COR-015.

For the first application class — agent-driven scenarios — the concrete shape is:

```
<agents-area>/<namespace>/<owning-agent>/
├── <owning-agent>.md         # the agent: frontmatter declares storyboards; body loads + follows them
├── storyboard.md             # one storyboard file (covers one or more scenarios)
└── <other-helpers>           # other folder-form siblings, if any
```

When an agent owns multiple distinct scripted scenarios that don't share framing, the storyboard splits — `<scenario-slug>.storyboard.md` per scenario, each a sibling of the agent file. A single storyboard covering several closely-related scenarios is also fine; the author decides what fits in one file by whether the scenarios share framing and tone.

Other application classes (when they materialise) follow the analogous shape: a CLI command's storyboard sibling under `.pkit/cli/`, an interactive migration's storyboard sibling in the migration's directory, etc. The naming convention (`storyboard.md` or `<scenario-slug>.storyboard.md`) and source-only-with-runtime-read lifecycle stay the same.

**Source-only, runtime-readable via source path.** Storyboards are not propagated by the adapter — they stay at their source location (`.pkit/agents/<ns>/<name>/storyboard.md` for agent storyboards). At runtime, the implementing artifact reads them directly from the source path; the harness's working directory is the project root, and `.pkit/` is committed alongside the rest of the project tree, so the path resolves cleanly via the artifact's `Read` tool. The agent body's reference to its storyboard is therefore **load-bearing** — the agent expects the storyboard at the declared path and instructs the runtime to load it at session start.

This is "source-only" in the deploy sense (the adapter doesn't copy storyboards to `.claude/`), but "runtime-accessible" in the operational sense (the runtime reads them from source). The combination keeps the storyboard as a single source of truth (no copy to drift from) while letting the agent execute scripted scenarios from a long-form spec rather than a compressed sketch.

### Frontmatter declaration

The relationship between a storyboard and its consumers is **two-sided** in frontmatter — both the consumer and the storyboard declare it. The validator cross-checks both declarations against filesystem position.

**Consumer side (e.g., the agent that drives the scenarios):**

```yaml
---
name: review-agent
description: ...
tools: [Read, Edit, ...]   # Read is required when storyboards are declared
storyboards:
  - .pkit/agents/project/review-agent/storyboard.md
---
```

`storyboards:` is a list of project-root-relative paths. Each entry must resolve to a file on disk. `pkit refs validate` checks both that the file exists and that the body cites the path. Tools must include `Read` so the runtime can load the file.

**Storyboard side:**

```yaml
---
consumers:
  - kind: agent
    name: review-agent
    namespace: project
---

# Storyboard: ...
```

`consumers:` is a non-empty list. Each entry identifies one artifact that drives the storyboard's scenarios. Fields per entry:

- `kind` — the consumer's artifact type. Today the only supported value is `agent`. Future application classes (per the "Other application classes" section above) add their own kinds (`cli`, `migration`, etc.) when they materialise.
- `name` — the consumer's name, matching its frontmatter `name` field.
- `namespace` — the consumer's namespace (`core` or `project` for agents).

The list form (rather than a single `agent:` scalar) is intentional: today every storyboard has exactly one consumer, but the shape is the same for future cases where a storyboard is genuinely shared between multiple consumers. Adding a second consumer is a frontmatter edit, not a schema change.

**Bidirectional consistency.** The validator checks:

- Each declared consumer exists on disk.
- Each declared consumer's frontmatter (`storyboards:` for agents) includes this storyboard's path.
- The storyboard's filesystem location is consistent with one of its declared consumers' folder (the *primary owning* consumer — the one whose folder the storyboard sits in).
- Storyboard files in an agent's folder must declare that agent as a consumer (orphan check).

**Cross-actor scenarios are deferred.** A scenario whose dialogue spans multiple implementing artifacts (e.g., a CLI command that hands off to an agent mid-flow) is conceivable but speculative — no example exists yet. When one surfaces, a future record can introduce a non-sibling location convention (e.g., `.pkit/scenarios/<slug>/`). Until then, every storyboard binds to one primary-owning artifact.

### Strength

The storyboard is:

- **Recommended** for scripted interaction scenarios (the workflow's value is in the designed sequence of turns), regardless of application class.
- **Always permitted** for any implementing artifact (a designer may choose to storyboard a borderline case, or a scenario that's still finding its shape).
- **Not applicable** to judgment-driven work (the actor improvises from context; scripting the dialogue would make the artifact worse, not better).

The authoring tooling surfaces the recommendation at scenario-design time. The question is not "is this an interactive agent" but "am I designing a scripted workflow?" — if yes, a storyboard scaffold is offered (for the agent class, today); if no, the author writes the artifact body directly. The methodology does not refuse to author without one. Adopters who skip the storyboard accept the cost — design ambiguities that the storyboard would have surfaced may show up later.

## Rationale

**Why the principle is named broadly, even though tooling ships narrowly.** The storyboard template — Trigger / Preconditions / Walkthrough / Behind-the-scenes — is general. It works for any scripted interaction with a human user, regardless of whether the implementing artifact is an agent, a CLI command, a migration script, or a tutorial. Scoping the *principle* to agents would force a re-decision the moment another application class wants to use the same template. Scoping the *tooling* to the only class we have a concrete example of (agents) respects COR-007's recurrence discipline — we ship infrastructure for what's grounded in real use, while naming the broader pattern so it doesn't have to be rediscovered.

**Why scenarios, not the implementing artifact.** The natural impulse is to make storyboards an artifact-shaped thing — "interactive agents use storyboards," or "interactive CLI commands use storyboards." But the same artifact can have both judgment-driven default behavior and one or more scripted scenarios (a code reviewer that improvises most of the time and follows a specific walkthrough for security PRs; a CLI tool whose `--help` is freeform but whose `pkit upgrade` flow is scripted). Binding the storyboard to the artifact's identity forces a false dichotomy. The reality is that *scenarios* are scripted; the artifact is just an actor that may execute zero or more of them.

**Why storyboards specifically, and not other design artifacts.** Per COR-006's discriminator, the artifact set is decision / doc / skill / agent / scratchpad. A storyboard isn't any of those: it isn't a rule-among-alternatives (decision), an explanatory doc (it's prescriptive), a procedure for execution (skill), an exploratory note that retires (scratchpad), or a role declaration (agent). It is a **typed sibling helper** for the implementing artifact — a sixth shape that is structurally bound to its owning artifact. Naming it as a typed helper (rather than inventing a sixth top-level artifact kind) keeps the artifact taxonomy stable and the storyboard's relationship to its host visible.

**Why recommended, not required.** Scripted scenarios admit real edge cases — an author whose workflow is well-understood enough that drafting the artifact body first is faster than storyboarding, a single-prompt single-action scenario whose "script" is trivial, a turn sequence so simple that the dialogue writes itself. A required rule would force ceremony in cases where the discipline doesn't pay for itself. A recommendation that names the convention and surfaces it at authoring time lets the kit's tooling guide the choice without making it for the author. Adopters who skip the storyboard accept the cost; the methodology trusts them to make that call.

**Why one signal rather than a multi-part discriminator.** The category "scripted scenario" is recognized today from one concrete instance (the pm-workflow review agent). Inventing a multi-part test from one example would be fitting a discriminator to a data point, not extracting a principle — exactly the over-engineering COR-007 warns against in the other direction. The single signal — *do I find myself writing scripted dialogue for a specific workflow?* — is honest about what we know. As more storyboarded scenarios land (in any application class), the boundary self-discovers; a future record can sharpen the discriminator with evidence.

**Why storyboard-first, not storyboard-alongside or storyboard-derived.** Writing dialogue forces decisions about behavior. The implementing artifact authored first, without a storyboard, tends to elide the decisions ("when the user asks X, respond appropriately" with no specifics). The storyboard exposes the elisions. Reversing the order — artifact first, storyboard back-documented — gives the same elision-hiding behavior the storyboard was supposed to surface. The temporal discipline carries the value.

**Why source-only with runtime read, not deploy-alongside.** Two paths exist for letting the runtime access a storyboard: (a) deploy a copy of the storyboard alongside the agent at the harness side, or (b) leave the storyboard at source and have the agent read it from the source path at runtime. The kit chooses (b). Reason: deploy-alongside creates a second copy that can drift from the source if a maintainer edits one and forgets the other; runtime-read-from-source keeps a single source of truth. The runtime can always reach `.pkit/` because adopters commit it alongside their project tree, so the path resolution isn't fragile. Earlier framings of this principle called for deploy-side propagation; that was reconsidered before any propagation logic shipped — single source of truth wins.

There's a secondary reason: deploying storyboards alongside agents at `.claude/agents/<name>/` would put non-agent `.md` files inside the harness's recursively-scanned agent directory, where their handling by the harness is unspecified (Claude Code might try to load them as agents, error on the missing `name` field, or silently skip). Source-side reading sidesteps the harness behavior entirely.

**Why persistent, not retired.** Unlike scratchpad notes (which crystallize and retire), the storyboard remains the long-form behavioral spec the implementing artifact was written from. Evolving the scenario means editing the storyboard, then updating the artifact to match. Retirement would discard a load-bearing artifact.

**Why borrowed from adjacent disciplines.** UX designers write user-flow scripts. Screenwriters write screenplays. Game designers write narrative beats. The pattern of "design human-facing behavior by writing the interaction down" is well-tested in fields older than software-defined agents. Importing the pattern is cheaper than inventing one — and importing it as a general principle (rather than agent-specific tooling) preserves its generality.

### Alternatives considered

- **Scope the principle to agents only; don't name the broader pattern.** Rejected — the Trigger/Preconditions/Walkthrough/Behind-the-scenes template is genuinely general. Scoping the principle would force a future re-decision the first time a CLI flow or interactive migration wants to use the same shape. Naming the broader principle while shipping narrow tooling preserves future option without ungrounded abstraction.

- **Storyboard coupled to the agent's identity (`interactive agent` framing).** Rejected — forces a false dichotomy. An agent (or any implementing artifact) is not "interactive" or "not"; it may *participate in* scripted scenarios while also doing judgment-driven work. Coupling the artifact to the scenario instead of the actor lets the same artifact host both modes.

- **Generalize the tooling too: ship `pkit new storyboard <where>` for arbitrary artifact types now.** Rejected — we have one application class with a concrete example. Building tooling for hypothetical classes (CLI flows, migrations, tutorials) without examples would fit infrastructure to a data point. Tooling extends incrementally; the principle is named now, the tooling lands as application classes arrive.

- **Storyboard as scratchpad note (typed, retires after the scenario ships).** Rejected — scratchpads map design space *before* a decision crystallizes. The storyboard's role does not end when the scenario ships; it remains the behavioral spec the implementing artifact was written from. Retirement would discard load-bearing content.

- **Storyboard as a new top-level artifact kind alongside the COR-006 set.** Rejected — storyboards are inherently bound to one implementing artifact. Top-level status would fragment whichever area hosts the artifact and obscure the relationship. Folder-form sibling per COR-015 keeps both visible and contained.

- **Storyboard required for all scripted scenarios.** Rejected — a single-prompt single-action scenario has no meaningful script to design. Universal requirement would be ceremony in cases where the discipline doesn't pay for itself.

- **Storyboard as informal practice, not a methodology principle.** Rejected — without a named convention, each author re-invents the format. The Trigger/Preconditions/Walkthrough/Behind-the-scenes template carries the value; codifying it removes the per-author template-design overhead and makes storyboards reviewable on consistent terms.

- **Storyboard-alongside (parallel authoring) rather than storyboard-first.** Rejected — the temporal discipline is where the design-surfacing value lives. Writing dialogue first forces decisions the implementing artifact would otherwise elide.

- **Storyboard propagated to the deploy side alongside the resolved artifact.** Rejected — would create a second copy that can drift from the source, and (for the agent case specifically) places non-agent `.md` files inside the harness's recursively-scanned agents directory where their handling is unspecified. Runtime read from source keeps a single source of truth and avoids the harness-behavior question.

- **Agent body self-contained (storyboard reference informational only).** Rejected on reconsideration. The earlier framing said the agent body must work without loading the storyboard; revisiting that, it forces the body to compress the scenarios into a sketch that drifts from the storyboard whenever either side evolves. Making the body load-bear on the storyboard keeps the agent thin (it just instructs the runtime to read and follow the storyboard) and lets the storyboard's full detail drive behavior. Requires `Read` in the agent's tools and a runtime convention that the agent loads its storyboards at session start.

## Implications

### Scoped to the agent class (shipped with this record)

- **Authoring tooling.** A new command `pkit new storyboard <artifact-kind> <name> [--scenario <slug>]` ships, paired (per COR-005) with a **`storyboard-author`** skill. The first positional identifies the kind of implementing artifact the storyboard belongs to. Today the only supported value is `agent`; future application classes (`cli`, `migration`, etc.) slot in as additional handlers without renaming the command. The command stamps `storyboard.md` (or `<slug>.storyboard.md` with `--scenario`) at the location appropriate for the artifact kind. The skill walks the author through framing, tone, and scenario sections, applying the disciplines.

  Concretely today:
  - `pkit new storyboard agent <name>` → stamps `.pkit/agents/<ns>/<name>/storyboard.md` (resolves namespace by looking up where the named agent lives; errors if ambiguous).
  - `pkit new storyboard agent <name> --scenario <slug>` → stamps `.pkit/agents/<ns>/<name>/<slug>.storyboard.md` alongside.

- **`pkit new agent` updates.** The command surfaces the scripted-scenario question at namespace/name choice: *does this agent drive any scripted workflows?* If yes, it stamps folder-form per COR-015 with a sibling storyboard scaffold. If no, flat form as today. The question is independent of the agent's role — an agent can answer "no" today and gain a storyboard later when a scripted scenario emerges.

- **`agent-author` skill updates.** Adds the scripted-scenario question as an early discriminator step. Routes authors with a scripted scenario into the storyboard-first workflow before agent-body drafting.

- **Agents area README.** Gains a "Storyboards" section covering: what a scripted scenario is, the three-layer storyboard structure, location convention (sibling to the owning agent), source-only lifecycle, and the multiple-scenarios-per-agent shape.

- **Adapter deploy primitives are unchanged.** Storyboards stay at source; deploy operates on the agent file alone. No new exclusion rule needed — siblings other than the canonical `<name>.md` were already ignored. The runtime reads storyboards from their source path (`.pkit/agents/<ns>/<name>/storyboard.md`) using the agent's `Read` tool.

- **Two-sided frontmatter.** Consumers (today: agents) declare their storyboards via `storyboards:` (list of paths). Storyboards declare their consumers via `consumers:` (list of `{kind, name, namespace}` entries). The agent's `tools` must include `Read` when `storyboards:` is non-empty. The `consumers:` list shape supports future multi-consumer sharing without schema change; today every storyboard has exactly one consumer.

- **Reference graph (`pkit refs validate`).** Extended to walk both sides of the storyboard relationship:
  - Each consumer's declared storyboard path exists on disk and is cited in the consumer's body; the consumer's tools include `Read`.
  - Each storyboard's declared consumers exist on disk; each consumer's `storyboards:` includes this storyboard's path.
  - Storyboard files present in a consumer's folder must declare that consumer (orphan check).
  Cross-references between consumers and their storyboards become part of the graph.

- **Authoring tooling stamps both sides.** `pkit new storyboard agent <name>` writes the `consumers:` frontmatter on the storyboard automatically (filling `kind: agent`, `name`, `namespace` from context); `pkit new agent <ns> <name> --with-storyboard` does the same for the storyboard scaffold it stamps. The author doesn't hand-write the cross-references on first stamp.

- **Existing agents are not retroactively migrated.** The discipline applies to new scripted scenario authoring. Existing agents whose authors find the prose-only form sufficient can stay; those who want to formalize a scripted scenario they're already running can adopt the storyboard pattern voluntarily — adding `storyboards:` to their frontmatter, ensuring `Read` is in their tools, and writing a body that loads + follows the declared storyboards.

### Other application classes (not shipped here)

- **CLI flows, interactive migrations, bundle setup wizards, tutorial walkthroughs** are recognized as candidate application classes for the storyboard template. None has a concrete grounding example today, so this record ships no tooling or area-README updates for them.

- **Adopting the convention for a new class** requires three things: a real example to ground the abstraction, a sibling location decision (where the storyboard lives relative to the implementing artifact), and a new handler for the existing `pkit new storyboard` command (i.e., adding the new value to the `<artifact-kind>` positional, with the location-resolution logic for that kind). A sibling record can capture the extension and cite this record as the load-bearing parent. The command name itself is already general enough that no rename is needed.

- **The storyboard template itself is reusable as-is** for any class that adopts it — the three layers (Framing / Tone rules / Scenarios with their four sub-sections) describe a general design problem, not an agent-specific one. New classes inherit the template; only the implementing-artifact part changes.
