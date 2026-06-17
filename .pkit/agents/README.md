---
variant: universal
---

# Agents

This directory holds the project's **agents** — persistent roles (per COR-006) that AI tooling can be delegated to. Each agent is a named role with its own files-owned scope, reading list, tools, and behaviour.

The principles — the unified frontmatter shape, the reference graph with bidirectional consistency, the hook contract for cross-area execution, the adopter overlay for adopter-specific paths, the core / project split — are recorded in [`.pkit/decisions/core/COR-013-agent-architecture.md`](../decisions/core/COR-013-agent-architecture.md). This README is the spec adopters and authors consult day-to-day.

## Layout

Per COR-015, an agent takes one of two forms:

```
.pkit/agents/
├── README.md                       # this file (core-owned; propagated by sync)
├── core/                           # core-shipped agents (propagated)
│   ├── <name>.md                   # flat form: atomic agent, no helpers
│   └── <name>/                     # folder form: agent with sibling helpers
│       ├── <name>.md               #   canonical file (name matches the folder)
│       └── (supporting files)
└── project/                        # project-owned agents (never propagated)
    ├── overlay.yaml                # adopter-specific path categories (see "Adopter overlay")
    ├── <name>.md
    └── <name>/
        ├── <name>.md
        └── (supporting files)
```

The flat form is the default for new agents; promote to folder form only when a sibling helper materialises. Both `core/` and `project/` follow COR-003's universal pattern. An adopter's `overlay.yaml` lives at the top of `project/`; per-agent overrides for that overlay live inside it under the `overrides:` key.

## Frontmatter schema

Agents and skills share the same frontmatter shape for fields that participate in the reference graph. Fields that don't apply to one kind are omitted.

```yaml
---
name: backend-implementer
description: Illustrative only — a project's own domain agent (implementation, debugging, review).
tools: [Read, Edit, Bash, Glob, Grep, WebFetch, WebSearch]
reads:
  paths:                              # filesystem paths
    - .pkit/decisions/README.md
    - CLAUDE.md
  records:                            # decision-record IDs (resolve by ID, not slug)
    - COR-005
    - COR-008
  patterns:                           # adopter-overlay placeholders; resolved at deploy time
    - <code-paths>
owns:                                 # paths the agent has write authority over (agents only)
  - <code-paths>
  - <test-paths>
needs:                                # hook names the agent invokes (see "Hooks")
  - project-management.create-issue
  - project-management.move-issue
---

# Software Engineer

You are the **software engineer** for this project. …
```

**Field semantics:**

- `name`, `description` — agent identity; `description` is the one-line summary surfaced by tooling.
- `tools` — the harness-recognised tool names this agent is granted (e.g. for Claude Code: `Read`, `Edit`, `Bash`, `Agent`, …). The adapter translates this to the harness's expected format at deploy time.
- `reads` — references the agent consults at task time. Split into `paths` (filesystem locations), `records` (decision-record IDs like `COR-NNN` or `PRJ-NNN`), and `patterns` (overlay-resolved placeholders).
- `owns` — paths the agent has write authority over. Every kit-relevant path has exactly one owning agent; the bidirectional check flags overlaps. Agents-only (skills don't own paths).
- `needs` — hook names this agent invokes. See the "Hooks" section.
- `answers` — hook names a skill provides. Skills only.
- `gates` — record IDs whose `accepted` status is load-bearing for a skill to run. Skills only; entries here automatically count as `reads.records`.

## Body conventions

Body prose cites the same references the frontmatter declares. The validator extracts mentions from the body using these rules:

- **Paths** inside backticks count: `` `.pkit/decisions/README.md` ``.
- **Markdown link targets** count: `[link text](.pkit/foo.md)`.
- **Record IDs** as bare tokens count: `COR-005`, `PRJ-002` (regex `^(COR|PRJ)-\d+\b`).
- **Hook names** count when they appear: `project-management.create-issue` (regex `^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*){1,2}$`).
- **Not counted**: anything inside fenced code blocks, HTML comments, or strikethrough.

The discipline: cite paths in backticks, cite records by ID, mention hooks by name. The validator can extract unambiguously without ad-hoc prose parsing.

## Reference graph and bidirectional consistency

`pkit refs validate` walks every agent's and skill's frontmatter and body, building the reference graph. Two consistency checks:

- **Forward** — every entry in frontmatter (`reads`, `owns`, `needs`, `answers`) must appear in the body. Unused declarations are flagged.
- **Backward** — every path/ID/hook extracted from the body must be declared in frontmatter. Untracked usages are flagged.

Both directions must hold. CI runs the same check at PR time.

Additional graph operations live in the `pkit refs` CLI family — show, who-references, rename, rot, graph, lookup. See `.pkit/cli/README.md` for the full surface once it ships.

## Hooks

Agents execute external operations through **hooks** — named entry points that decouple consumers (agents) from providers (skills, shell commands, scripts).

### Declaration

- **Consumer** (agent frontmatter): `needs: [hook-name]`.
- **Provider** (skill frontmatter): `answers: [hook-name]`.
- **Provider** (capability / adapter `package.yaml`): `provides: { hook-name: <implementation> }`.

### Provider value syntax

The implementation string is parsed by prefix:

- `/<skill-name>` → invoke the named skill via the harness's skill mechanism.
- Anything else → execute as a shell command via bash.

```yaml
# capability's package.yaml
provides:
  project-management.create-issue: /pm-create-issue      # skill
  project-management.move-issue:   scripts/move-issue.py # shell script
```

### Hook signature

Hooks take positional string arguments and produce text on standard output. Exit code 0 indicates success; stderr carries errors/warnings. Each hook's per-hook contract (args, expected output format) lives in the body/README of its provider.

### Naming

- **Two segments — `<topic>.<operation>`** — for *contract* hooks that multiple providers in the same topic are expected to implement. Topic is typically a capability name; agents using only two-segment hooks stay portable across capability variants.
- **Three segments — `<topic>.<provider>.<operation>`** — for *provider-specific* extensions only one provider implements. Agents using these are knowingly tied to a specific provider.

Format: lowercase kebab-case segments separated by dots. Adopter-defined hooks use the reserved `project.*` topic.

### Provider precedence

```
project > capability > adapter > core
```

Mirrors the skill-deploy precedence. Same-tier collisions (e.g. two installed capabilities providing the same hook) refuse rather than silently picking; the adopter must disambiguate.

### Unsatisfied needs

All `needs:` entries are required by default. `pkit refs validate` (and install / sync) flag any unsatisfied need at install time; the runtime returns "no provider" cleanly if a hook is invoked with no provider.

## Adopter overlay

Agent templates reference adopter-specific paths via `<category-name>` placeholders. The adopter populates each category in a single overlay file:

```yaml
# .pkit/agents/project/overlay.yaml

# Default categories — apply to every agent unless overridden.
code-paths:
  - src/myproject/
test-paths:
  - tests/
project-root-docs:
  - CLAUDE.md
  - README.md

# Adopter-defined categories — used by project-authored agents.
acme-deploy-configs:
  - deploy/staging/

# Per-agent overrides — replace the default for the named agent only.
overrides:
  qa-engineer:
    code-paths:
      - tests/integration/
      - tests/unit/
```

The deploy primitive (see "Deploy mechanics" below) substitutes each `<category-name>` placeholder with the resolved value at deploy time. The resolved agent file is what every downstream tool reads.

**Resolution semantics:**

1. Start with the top-level (default) categories.
2. Apply each entry in `overrides.<agent-name>:` as a **full replacement** (not merge) for that category.
3. Substitute placeholders in the agent template; write the resolved file to the harness's expected location.

Per-agent overrides replace; copying base entries into the override is the explicit way to extend. (Merge semantics are deferred per COR-007 until concrete needs surface.)

**Validation:**

- Every category referenced by an agent template must be defined in the overlay — either at the top level or in `overrides.<agent>:`. An agent that references an undefined category is **skipped at deploy time** (loud, non-fatal — the rest still deploy).
- Override entries for non-existent default categories produce a warning (likely typo / dead config).
- Override entries for non-existent agents produce a warning.

**Diagnosing + repairing the overlay (per COR-013):**

- `pkit agents` reports, per kit-shipped agent, whether it is *deployable* or *SKIPPED* and which categories are undefined — the discoverable surface for "why didn't my agent show up?" (deployment happens in `sync`; this is the read-only diagnostic).
- `pkit agents adopt <agent>` is the **one-command path** for agents whose categories reference well-known conventional directories. For each undefined category the agent references, it:
  1. Creates the conventional default directory if absent (with a seed README explaining the directory's purpose).
  2. Writes the category into the overlay *uncommented* with the conventional path — never clobbering an adopter-set value.
  3. Runs the adapter's deploy step so the agent lands in `.claude/agents/` immediately.

  Idempotent: re-running on an already-adopted agent makes no changes and re-deploys. Errors clearly when the agent is unknown, references no overlay categories, or references a category with no registered conventional default (use `reconcile` for those).
- `pkit agents reconcile [--write]` surfaces every referenced-but-undefined category into `overlay.yaml`. The command uses **detect-then-fill** logic — four states per missing category:
  1. **Missing + conventional default directory exists**: the category is written *uncommented* with the conventional path, ready for `pkit sync` to deploy the agent immediately with no manual step. Example: `architecture-docs` is auto-filled with `docs/architecture/` when that directory is present; `adr-records` with `docs/architecture/decisions/`.
  2. **Missing + no conventional default directory**: a commented stub is appended (e.g. `# architecture-docs:`) with `<path/relative/to/project/root>` guidance; the adopter fills in a real path before running `pkit sync`. Or run `pkit agents adopt <agent>` to create the conventional layout and deploy it.
  3. **Commented stub already present**: reconcile reports "uncomment + set real paths" guidance and does not append a duplicate. Or run `pkit agents adopt <agent>` to create the conventional layout and deploy it.
  4. **Defined** (uncommented entry with paths): nothing is written; an adopter-set value is never overwritten.

  This is the path for an adopter whose overlay predates a newly-shipped agent's categories — the repair is an explicit, idempotent gesture rather than an automatic sync mutation. Dry-run by default.

  Conventional defaults are declared in `src/project_kit/agents_overlay.py` (`CONVENTIONAL_CATEGORY_DEFAULTS`), one entry per overlay category. Adding a default for a new category is the authoring step that enables auto-fill for adopters who follow the conventional layout and `adopt` for those who prefer the one-command path.

## Deploy mechanics

Each adapter (per COR-005) handles its own deploy. For Claude Code today, `.pkit/adapters/claude-code/deploy-agents.sh` walks `.pkit/agents/{core,project}/` and any installed capability's `agents/` folder (per [COR-026](../decisions/core/COR-026-agent-placement-by-discipline.md)), applies the overlay, and writes resolved agent files into `.claude/agents/`. The deploy primitive is invoked by `pkit init` and `pkit sync`; the resolved files are what the harness loads.

### Name-collision precedence

Three locations can ship agents (core, project, installed capability). On name collision, precedence is:

1. **Project** (`.pkit/agents/project/`) wins over everything. Adopters retain final authority over their agent set.
2. **Capability** (`.pkit/capabilities/<name>/agents/`) wins over **core** (`.pkit/agents/core/`). A capability that ships an agent with the same name as a core agent is opting to override the core surface for adopters who install the capability — the capability's agent is the discipline-specific specialisation; the core's is the universal default. The capability author signals this by shipping the colliding name deliberately.
3. **Core** (`.pkit/agents/core/`) is the fallback. Used when no project or capability ships the name.

The precedence applies symmetrically across capabilities: if two installed capabilities ship an agent with the same name, the deploy refuses rather than silently picking — same shape as the bundle-collision rule. Adopters disambiguate by uninstalling one capability or by shipping a project-side overlay.

Per [COR-026](../decisions/core/COR-026-agent-placement-by-discipline.md), discipline-implying agents belong in their capability, not at core. Capability-vs-core name collisions are therefore not the common case — they exist for explicit override scenarios.

### Why copies, not symlinks

Agent files at `.claude/agents/<name>.md` are **resolved copies** of the source, not symlinks back to it. Skills under `.claude/skills/` deploy as symlinks; agents cannot. The difference is the overlay step: agent templates carry `<category-name>` placeholders that the deploy substitutes using `overlay.yaml`. The resolved content differs from the source, so a symlink would expose the unresolved template (the harness would load `<code-paths>` as literal text). Skills have no placeholders today, so a symlink works there and gives authors live-edit during development.

The trade-off: editing an agent source file in `.pkit/agents/` does **not** propagate to the harness until you re-run the deploy primitive. This is symmetric with the substitution requirement — there is no way to keep the resolved view in sync with the source automatically without re-running the deploy. If a skill ever grows placeholders, it would switch to the same copy-based mechanism at that point.

Future adapters for other harnesses ship their own deploy primitives.

## Core / project split

Per COR-014, the universal-applicability test governs what ships where:

- **Core agents** (in `core/`) — universal roles useful to any adopter. Methodology disciplines (record-review, citation-audit), convention-compliance review, coordinator templates that adopters specialise via overlay. Ships with the methodology; refreshed on every sync.
- **Project agents** (in `project/`) — domain-specific roles tied to the adopter's stack. Implementer agents (`ui-ux-designer`, `qa-engineer`), domain reviewers, customised coordinators. Authored per project; never touched by sync. (The code-authoring `software-engineer` is **not** here — it ships, opt-in, via the `software-engineering` capability per [COR-026](../decisions/core/COR-026-agent-placement-by-discipline.md); capabilities are the home for a discipline-implying agent that isn't universal.)

## Authoring an agent

The methodology ships an authoring command paired with a skill (per COR-005):

```
pkit new agent <name>
```

The paired `agent-author` skill carries the slug-choice judgement, the body-drafting walkthrough, and the citation discipline. Ships in a future PR; until then, hand-stamp using this README as the spec and the existing agents in `core/` as reference shape.

## The matrix

The cross-cutting view of "who owns what" and "who handles which task" is auto-generated from agent frontmatter by `pkit agents matrix` (future CLI command). The generated doc is a denormalised view; the canonical source is each agent's `owns:`, `reads:`, `needs:`, and `description:` fields. Drift between the auto-generated view and the source is structurally impossible because the view is regenerated on demand.

## Storyboards

Per COR-016, agents that drive **scripted interaction scenarios** — sequences of designed turns with specific prompts, gates, and mutations the methodology authors in advance — pair with a sibling **storyboard** that captures the scenario design before the agent body is written.

### When storyboards apply

The signal is concrete: *do I find myself writing scripted dialogue inside the agent body?* If yes, the workflow is a scripted scenario worth designing first.

- **Storyboard fits.** A review agent walking a human through methodology acceptance; an onboarding flow; a coordinator confirming scope before delegating.
- **Storyboard doesn't fit.** Judgment-driven work — a code reviewer responding to general diffs from context, a research assistant exploring a topic, a domain expert improvising findings. Scripting the dialogue would make these worse, not better.
- **Borderline / mixed.** The same agent can do both. A code reviewer doing free-form review most of the time, plus one scripted scenario for security-sensitive PRs — storyboard the scenario, leave the rest to judgment.

### Storyboard structure

Three layers (per COR-016):

1. **Framing** — what set of scenarios the storyboard covers, what global state the scenarios operate on, what the user-facing entry points are.
2. **Tone rules** — behavioral norms applied across every scenario in the file (cadence, turn length, confirmation style).
3. **Scenarios** — each with `Trigger` / `Preconditions` / `Walkthrough` (example dialogue) / `Behind the scenes` (mutations and side effects). Edge cases are first-class scenarios, not afterthoughts.

A single `storyboard.md` may carry multiple scenarios when they share framing and tone. When scenarios diverge, split into per-scenario `<scenario-slug>.storyboard.md` files alongside the agent.

### Location and lifecycle

Storyboards live as **sibling helper files** of the agent in folder-form per COR-015:

```
.pkit/agents/<namespace>/<owning-agent>/
├── <owning-agent>.md          # the agent: declares storyboards, loads them at session start
├── storyboard.md              # one storyboard file (covers one or more scenarios)
└── <scenario-slug>.storyboard.md   # per-scenario file (when scenarios diverge)
```

**Source-only, runtime-readable via source path.** Storyboards are not propagated by the adapter — they stay at their source location. At runtime the agent reads them directly from the source path via its `Read` tool: the harness's working directory is the project root, and `.pkit/` is committed alongside the project tree, so the path resolves cleanly. The agent body's reference to its storyboard is therefore **load-bearing** — the body declares the storyboard in frontmatter and instructs the runtime to load and follow it.

This keeps the storyboard as a single source of truth (no deploy-side copy that can drift) while letting the agent execute scripted scenarios from a long-form spec rather than a compressed sketch.

### Frontmatter declaration

The consumer/storyboard relationship is **two-sided** in frontmatter per COR-016. Both the agent and the storyboard declare it.

**Agent side:**

```yaml
---
name: review-agent
description: ...
tools: [Read, Edit, ...]      # Read is required when storyboards are declared
storyboards:
  - .pkit/agents/project/review-agent/storyboard.md
---
```

`storyboards:` is a list of project-root-relative paths. Each entry must resolve to a file on disk; the agent body must cite the path.

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

`consumers:` is a non-empty list. Each entry identifies one artifact that drives the storyboard's scenarios — today always an agent (`kind: agent`); future application classes (CLI flows, migrations) will add their own kinds.

The list form rather than a single `agent:` scalar is intentional: today every storyboard has exactly one consumer, but the shape supports future shared cases without schema change. `pkit new storyboard` fills the frontmatter automatically.

`pkit refs validate` enforces the two-sided relationship: each agent's declared storyboards exist and are cited in the body; each storyboard's declared consumers exist and back-reference; orphan storyboards (files in an agent folder that no agent declares) are flagged.

### Authoring

Stamp via:

```
pkit new storyboard agent <agent-name>                 # single storyboard for the agent
pkit new storyboard agent <agent-name> --scenario <slug>   # per-scenario file
```

The paired `storyboard-author` skill walks the author through framing, tone, and scenario drafting.

For new agents that will drive a scripted scenario from the start, `pkit new agent <ns> <name> --with-storyboard` stamps folder layout with a sibling storyboard scaffold in one gesture.

## Where this content came from

- COR-013 (agent architecture) — the load-bearing decisions this README implements.
- COR-005 (skill / command pairing) — the authoring pattern.
- COR-006 (artifact roles) — the skill-vs-agent layering.
- COR-014 (universal applicability) — the core / project split test.
- COR-011 (areas as first-class) — this area's structural place.
- COR-016 (storyboards) — the scripted-scenario design convention.
