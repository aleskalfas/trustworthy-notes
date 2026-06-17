---
name: storyboard-author
description: Author a storyboard for a scripted interaction scenario per COR-016. Walks the author through framing, tone, and per-scenario Trigger / Preconditions / Walkthrough / Behind-the-scenes drafting before the implementing artifact is written.
metadata:
  wraps_command: pkit new storyboard
gates:
  - COR-005
  - COR-006
  - COR-013
  - COR-015
  - COR-016
reads:
  records:
    - COR-008
  paths:
    - .pkit/agents/README.md
    - .pkit/decisions/README.md
---

# Authoring a storyboard

A storyboard (per COR-016) is the design source for a **scripted interaction scenario** — a sequence of turns between an implementing artifact and a human user where the methodology designs the dialogue: specific prompts, specific gates, specific mutations behind each user input.

This skill walks the author through stamping a storyboard and drafting its content before any implementing artifact body is written. Today the implementing artifact is always an agent; future application classes (CLI flows, interactive migrations, tutorials) slot into the same command with new handlers.

## Acceptance gate (run first)

Per `.pkit/decisions/README.md`'s acceptance gate, verify every record in this skill's `gates:` is `accepted` before authoring:

- **COR-005** — skill / command pairing. Establishes the rule that this skill pairs with `pkit new storyboard`.
- **COR-006** — artifact roles. The discriminator that places "storyboard" as a typed sibling helper, distinct from the five top-level shapes.
- **COR-013** — agent architecture. Defines the agent file the storyboard sits alongside.
- **COR-015** — artifact file layout. An agent gaining its first sibling helper migrates from flat to folder form; the storyboard is that first helper.
- **COR-016** — scripted-scenario storyboards. The convention itself.

If any is `proposed` or `superseded`, halt and report.

## Procedure

### 1. Confirm "storyboard" is the right artifact

Per COR-016, write a storyboard when you find yourself drafting scripted dialogue for a specific workflow. The signal is concrete: *do I find myself writing dialogue inside the implementing artifact's body?* If yes, the workflow is a scripted scenario worth designing first.

Don't use a storyboard for:

- *Judgment-driven work.* A code reviewer responding to general diffs with judgment doesn't need a script — the agent improvises from context. Scripting would make it worse.
- *Trivial single-turn interactions.* One question, one action. The dialogue writes itself.

Do use a storyboard for:

- A scripted workflow with multiple turns where each step needs designing (a review agent walking a human through acceptance, an onboarding flow, a security-PR-review walkthrough).
- A workflow where the dialogue is part of the design, not improvised.

### 2. Pick the implementing artifact

Today the only supported artifact-kind is **agent**. The named agent must already exist — stamp it first with `pkit new agent <namespace> <name>` if it doesn't.

The storyboard binds to the agent that drives the scripted scenario. If the agent is currently in flat form (`<ns>/<name>.md`), stamping the storyboard migrates it to folder form (`<ns>/<name>/<name>.md` + `<ns>/<name>/storyboard.md`) per COR-015's first-helper rule.

### 3. Decide single-file or per-scenario layout

Two shapes are valid:

- **Single `storyboard.md`** covering one or more scenarios. Use when the scenarios share framing and tone (the most common case — see pm-workflow's review-agent storyboard for the worked example).
- **Per-scenario `<scenario-slug>.storyboard.md`** files. Use when the scenarios are distinct enough that they don't share framing.

The author decides based on whether a single file's "Framing" and "Tone" sections cover all the scenarios cleanly.

### 4. Stamp the storyboard

```
pkit new storyboard agent <agent-name>
```

Or per-scenario:

```
pkit new storyboard agent <agent-name> --scenario <slug>
```

The command stamps the file with:

- A frontmatter block declaring the consumer(s) — `consumers:` list with `kind`, `name`, `namespace` filled in automatically per COR-016.
- The three-layer scaffold below the frontmatter: `## Framing`, `## Tone`, and a `## Scenario 1` template carrying `Trigger` / `Preconditions` / `Walkthrough` / `Behind-the-scenes` sub-sections.

Do not edit the `consumers:` frontmatter at first stamp — the command fills it correctly. Edit it only when the storyboard genuinely gains a second consumer (rare today; when it happens, add an additional `{kind, name, namespace}` entry, and verify each named consumer's `storyboards:` declares this file back).

### 5. Draft the framing

The Framing section answers three questions:

- **What set of scenarios does this storyboard cover?** Name the workflows. If one storyboard covers many, list them up front.
- **What global state do the scenarios operate on?** What files, what frontmatter fields, what external state matters? Reviewers reading the storyboard need to know the world the agent operates in.
- **What are the user-facing entry points?** How does the user trigger any of these scenarios — by invoking the agent, by a CLI command, by passing arguments?

Be concrete. "The agent walks the user through methodology acceptance" is too vague; "The agent processes the project root README's Quorum table, walks METHODOLOGY.md section by section, and tracks acceptances in the Acceptances table at the bottom of each section" tells reviewers what state matters.

### 6. Define tone rules

Tone rules apply globally across every scenario in the file. Examples:

- One thought per turn. The actor never dumps a whole section if it can be staged.
- Turns are 1–3 sentences. Italics for behind-the-scenes narration.
- Confirmation prompts are short and direct.
- When the actor acts on a user request, it confirms what it did in one sentence and offers the next step.

Borrow from your example storyboard's tone section, or rewrite for your scenario's context. The tone rules set the voice; the scenarios apply it.

### 7. Draft each scenario

Per scenario, four sub-sections:

- **Trigger.** One sentence — what activates the scenario.
- **Preconditions.** Bullet list — state that must hold for the scenario to apply.
- **Walkthrough.** Example dialogue. Use a quoted blockquote with `> **Actor:** ...` and `> **User:** ...` interleaving. Italics for behind-the-scenes narration to the user. Keep each turn short.
- **Behind the scenes.** Bullet list — file mutations, state checks, side effects. This is the spec the implementing artifact must satisfy.

Edge cases are first-class scenarios, not afterthoughts. If the user can refuse to act, try to bypass a gate, return after a prior session, etc. — those each get their own scenario with the same four sub-sections.

### 8. Self-check against the disciplines

Before showing the draft, walk it against:

- **Trigger + Preconditions exclusivity.** Each scenario's Trigger and Preconditions together must uniquely select when the scenario fires. If two scenarios could both apply at once, sharpen one of them.
- **Walkthrough realism.** Read the dialogue aloud. Does the actor's voice match the tone rules? Does the user's response make sense? Implausible dialogue is a design problem, not a writing problem.
- **Behind-the-scenes coverage.** Every state change the dialogue implies should appear as a behind-the-scenes bullet. Reviewers should be able to write tests from the spec.
- **Edge cases present.** What if the user tries to skip a step? What if a precondition fails mid-flow? At least one explicit edge-case scenario.

### 9. Show the draft for review

Surface the storyboard to the user before committing. Per the acceptance-gate analog for storyboards — the implementing artifact (agent body) should be written *from* the storyboard, not before it. Until the storyboard is reviewed, the agent body doesn't need to exist or change.

### 10. Commit

Per COR-008, conventional-commits format. Type is `docs` (the storyboard is a doc, not a runtime artifact); scope reflects the owning agent area:

```
docs(agents): add storyboard for <agent-name>

<body — 1–3 paragraphs on the scenarios and why the storyboard captures them>

Co-Authored-By: <as appropriate>
```

The storyboard lands. The implementing artifact (agent body) is updated *from* the storyboard in a subsequent commit, typically `feat(agents): implement <agent-name> scenarios from storyboard`.

## Variations

- **Adding a scenario to an existing storyboard.** Edit the file in place; add a new `## Scenario N: <name>` block with the four sub-sections. Skip this skill; the discipline is in the four-section template the existing storyboard already follows.
- **Splitting one storyboard into many.** When `storyboard.md` grows too large, split scenarios that don't share framing into `<slug>.storyboard.md` siblings. `pkit new storyboard agent <name> --scenario <slug>` stamps each one with the scaffold.
- **Updating the implementing artifact to match storyboard changes.** If the storyboard's behavior spec changes after the agent body has been written, the agent body needs to be updated too. The storyboard is the source; the agent body is downstream.
