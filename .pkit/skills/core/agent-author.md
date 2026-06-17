---
name: agent-author
description: Author a new agent (persistent role at .pkit/agents/<namespace>/<name>.md) with proper frontmatter shape, citation discipline, and body conventions per COR-013. Use when adding a role for an AI tooling integration to delegate against.
metadata:
  wraps_command: pkit new agent
gates:
  - COR-005
  - COR-006
  - COR-013
  - COR-015
  - COR-016
reads:
  records:
    - COR-008
    - COR-014
  paths:
    - .pkit/agents/README.md
    - .pkit/decisions/README.md
    - .pkit/agents/project/overlay.yaml
---

# Authoring an agent

This skill walks through adding a new **agent** under `.pkit/agents/{core,project}/`. Agents are the persistent-role artifact kind (per COR-006); each names a scope of authority and judgement, declares the references it consults and the paths it owns, and gives the AI tooling a stable identity to delegate against.

## Acceptance gate (run first)

Per `.pkit/decisions/README.md`'s acceptance gate: before procedural work, verify every record listed in this skill's frontmatter `gates:` is `accepted`. The current dependencies:

- **COR-005** — skill / command pairing. Establishes the rule that this skill pairs with `pkit new agent`.
- **COR-006** — artifact roles. The discriminator that places "agent" as one of five content shapes and rules out putting role-content in a skill or decision.
- **COR-013** — agent architecture. The unified frontmatter shape, hook contract, overlay mechanism, and reference-graph discipline this skill enforces.
- **COR-015** — artifact file layout. Atomic agents stamp flat as `<name>.md`; only promote to folder form when sibling helpers appear.

If any is `proposed` or `superseded`, halt and report.

## Procedure

### 1. Confirm "agent" is the right artifact

Per COR-006's discriminator, agents are *role-bearing* artifacts: a persistent identity an AI tooling integration can be delegated against, with its own scope of authority. Use a different artifact if:

- The work is a *recipe* (how to do X), not a role → that's a **skill**.
- The work is a *decision* (the rule among alternatives) → that's a COR / PRJ record.
- The work is a *reference doc* (explanation, navigation) → that's an area README or `<artifact>/README.md`.
- The work is *exploratory* (mapping a design space) → that's a **scratchpad note**.

An agent has *judgement*, *write authority over paths*, and *staying power across sessions*. A one-off task or a procedure you walk through once doesn't need an agent — a skill carries it more cheaply.

### 2. Pick a namespace (core vs project)

Per COR-014's universal-applicability test:

- **`core`** — the agent's role is useful to *any* adopting project. Methodology disciplines, code review against universal conventions, coordinator templates adopters specialise via overlay. Ships with the methodology; refreshes on every sync.
- **`project`** — the agent is tied to this adopter's stack, language, or product. Implementer agents (`software-engineer`, `qa-engineer`), domain reviewers, customised coordinators. Authored per project; never propagated.

If you're not sure, the question to ask: *would `example-brownfield` and `example-greenfield` both benefit from this agent in identical form?* Yes → core. Otherwise → project.

### 3. Pick a name

Kebab-case, 1–3 words, naming the *role* (not the verb). Examples: `methodology-reviewer`, `software-engineer`, `convention-compliance-reviewer`. Bad: `do-the-thing`, `review-stuff`.

Test: the name should fit naturally in the sentence *"You are the **<name>** for this project."* If the name doesn't read as an identity, sharpen it.

### 4. Decide if this agent drives a scripted scenario

Per COR-016, ask: *will this agent drive a scripted interaction scenario* — a sequence of designed turns with specific prompts, gates, and mutations the methodology authors in advance? Or is the agent's value purely in *judgment applied to context* (improvising findings from a diff, exploring a topic, answering ad-hoc questions)?

If **yes** to scripted scenarios, the storyboard-first path applies:

- Stamp the agent in folder form with a sibling storyboard scaffold (`--with-storyboard`, step 5).
- Draft the storyboard *first*, then write the agent body from it (call `storyboard-author` after this skill, before drafting the body in step 6).

If **no**, stamp flat as the default — the agent's body is the source of truth, no storyboard needed.

You can answer "no" today and revisit later: stamping a storyboard sibling onto an existing flat agent is supported (`pkit new storyboard agent <name>` auto-migrates flat to folder).

### 5. Stamp the stub

For a judgment-driven agent (flat layout):

```
pkit new agent core <name>            # for a universal role
pkit new agent project <name>         # for an adopter-specific role
```

For an agent that drives one or more scripted scenarios (folder layout + sibling storyboard):

```
pkit new agent core <name> --with-storyboard
pkit new agent project <name> --with-storyboard
```

The flat stamp produces `.pkit/agents/<namespace>/<name>.md`. The `--with-storyboard` stamp produces `.pkit/agents/<namespace>/<name>/<name>.md` plus a sibling `.pkit/agents/<namespace>/<name>/storyboard.md` scaffold. Both contain:

- Frontmatter scaffolding (`name`, placeholder `description`, default `tools`, empty `reads` / `owns` / `needs`).
- Body headers: `## When to invoke this agent`, `## Files you own`, `## Key documents to read`, `## How you work`.

Refuses if the name already exists in either namespace (project > core resolution means a colliding name would silently mask the core version).

### 6. Draft the body

For each section:

- **Description (frontmatter)** — single sentence; what the agent does and when to invoke it. This surfaces in the harness's agent picker; the first 1,500 chars compete with every other agent's description for the model's attention. Lead with the load-bearing keywords.
- **`## When to invoke this agent`** — bullet list of trigger conditions. Concrete; an author scanning the list should know whether their situation matches.
- **`## Files you own`** — the paths this agent has write authority over. Per the bidirectional reference-graph rule (COR-013), every path here must also appear in frontmatter `owns:`. Use `<category-name>` placeholders for adopter-specific paths; declare each in `reads.patterns` so the deploy-time substitution covers them.
- **`## Key documents to read`** — paths, record IDs (`COR-NNN`, `PRJ-NNN`), and hook contracts the agent consults at task time. Every entry here must also appear in `reads.{paths,records}` in frontmatter; the validator walks both directions. For scripted-scenario agents (per COR-016), the agent's storyboards belong here too — declared in frontmatter `storyboards:` and load-bearing on the body.
- **`## How you work`** — the agent's procedure or principles. For *judgment-driven* agents (no storyboards), numbered steps if the role follows a fixed sequence; principles + examples if the role is more judgement-bearing. For *scripted-scenario* agents (with `storyboards:` declared), the body is much thinner: it states that the agent's scripted behavior is documented in its declared storyboards, instructs the runtime to load them at session start via the `Read` tool, and may summarize at a high level what scenarios the agent drives — but does **not** restate or sketch the scenarios. The storyboard is the source; the agent body's job is to point at it. Cite authority by record ID rather than restating it (`per COR-005` not "per the skill/command pairing rule").

### 7. Declare hooks (if any)

If the agent invokes external operations (settings changes, work-tracker writes, deploys), declare each as a hook in frontmatter `needs:` rather than hard-coding a shell command in the body. See `.pkit/agents/README.md` → "Hooks" for the naming and signature contract.

Two-segment hooks (`<topic>.<operation>`) are portable across bundles. Three-segment hooks (`<topic>.<provider>.<operation>`) lock the agent to a specific provider; only use these when the operation genuinely has no portable equivalent.

### 8. Self-check against disciplines

Before showing the draft, walk it against:

- **Bidirectional reference-graph consistency.** Every frontmatter `reads.{paths,records,patterns}` / `owns` / `needs` entry must appear in the body. Every path / record-ID / hook-name in the body must be declared in frontmatter. The validator runs the same check; running it mentally first saves a rejection.
- **Universal applicability** (core namespace only). Would the agent read naturally for `example-greenfield` and `example-brownfield` in identical form? If it leaks framework-source vocabulary (`pkit` specifics, project-kit decision IDs that don't apply to adopters), demote to project namespace or generalise.
- **Role-not-procedure.** The body should read as "what you are and how you think", not as "step 1 do this, step 2 do that". Procedures live in skills the agent invokes.
- **Description quality.** Read the description aloud. Does it tell the harness's auto-loader exactly when this agent applies? Sharpen until yes.
- **Lead with meaning.** The agent opens by saying plainly what it is and when to reach for it, before the detail; sentences cite what they need (roughly one reference per point), not pile five-deep. An agent definition a reader can't grasp on a first pass has the same failure mode as a cryptic record. See CONTRIBUTING.md's "Lead with meaning".

If any check fails, revise.

### 9. Show the draft for review

Surface the draft to the user. Do not commit until approved.

### 10. Commit (after approval)

Per COR-008, conventional-commits format. Type is `feat` for a new agent; scope reflects the area:

```
feat(agents): add <name> agent

<body — 1–3 paragraphs on role, why it exists, what it owns>

Co-Authored-By: <as appropriate>
```

The agent lands and is deployed by the next `pkit sync` or via running the adapter's deploy primitive (`bash .pkit/adapters/<harness>/deploy-agents.sh`). For Claude Code, the resolved file lands at `.claude/agents/<name>.md`.

## Variations

- **Promoting from flat to folder form.** When the agent gains its first sibling helper (a reference matrix, a generated template, a script), migrate from `<name>.md` to `<name>/<name>.md` with helpers as siblings. Update any links in the body that referenced the old path. This is a structural change worth its own commit.
- **Refining an existing agent.** Edit in place. Git history is the change log. Skip this skill — it stamps new agents only.
- **Adopter overrides for a core agent.** Do not edit `.pkit/agents/core/<name>.md` — that's core-owned and silently overwritten by sync. Instead, add per-agent overrides to `.pkit/agents/project/overlay.yaml` under `overrides.<name>:` to customise paths the agent references via `<category-name>` placeholders.
