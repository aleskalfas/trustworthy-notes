---
id: COR-005
title: Bundle and adapter pattern
status: accepted
date: 2026-05-05
author: Ales Kalfas <kalfas.ales@gmail.com>
---

> **Refined by [COR-027](COR-027-alternative-impls-as-capability-data.md)** (2026-05-27). This record originally established three rules; one is retired and two stand:
>
> - **Bundle pattern** — *retired*. Capabilities ([COR-017](COR-017-capability-pattern.md)) subsumed the alternative-implementations use case; alternative variants now live as capability-internal data per COR-027. Do not author new bundles. Bundle-pattern content below is preserved as historical context.
> - **Adapter pattern** — *operative*. Adapters remain the harness-translation mechanism at `.pkit/adapters/<name>/`.
> - **Skill / command pairing** — *operative*. Every authoring command in the methodology's CLI ships with a paired skill; the script does the stamp, the skill does the disciplines.
>
> Status stayed at `accepted` (rather than `superseded`) because two of the three rules continue to govern current authoring — the binary supersession status would have falsely refused gates from skills that depend on the still-operative halves (`adapter-author`, `agent-author`, `area-author`, `capability-author`, `migration-author`, `storyboard-author`, `scratchpad-author`, `methodology-reviewer` all cite COR-005 in their `gates:` field). When the entire record's content retires, the status flips to `superseded`; until then, this header is the carrier of the partial-refinement semantics.

## Context

COR-003 established the two-namespace pattern for areas with both core and project content: parallel `core/` and `project/` directories, with the core directory holding canonical content (propagation) and the project directory holding adopter additions (extension).

That pattern fits **universal** areas — decisions, rules, agents — where there is one canonical version of each content type and projects extend by adding their own. It does not fit two other shapes that show up in the methodology:

- **Bundle-based areas** — where the core layer ships multiple alternative implementations of one contract, picked at install time. Workflow is the canonical example: GitHub Issues, Jira, and Linear are alternatives implementing an issue-tracking contract.
- **Harness-flavoured content** — where some content's format and deployment depend on a specific AI tool (Claude Code, Codex, Cursor, etc.). Settings files, deploy scripts, and runtime config don't fit harness-agnostic areas.

Both shapes need a namespace where multiple alternatives coexist, the adopter picks one (or more), and each alternative is self-contained. Without a structural rule, each instance would invent its own conventions and the methodology surface would become inconsistent.

## Decision

Two structurally-similar pluggable patterns, each under a clearly-named umbrella:

- **Bundles** sit *inside* an area: `.pkit/<area>/bundles/<bundle-name>/`. They are area-internal alternative backends.
- **Adapters** sit *at the methodology's top level*: `.pkit/adapters/<adapter-name>/`. They hold harness-flavoured content, one adapter per harness.

### The shared structural pattern

Both bundles and adapters:

- Are alternative implementations selected from a set.
- Live in a structured umbrella (`bundles/` within an area; `adapters/` at the methodology's top level).
- Are self-contained directories: one folder holds everything for one alternative.
- Adopters pick one or more to install.
- Project-side state, where applicable, mirrors the core-side namespace.

### The three variants of core-side content layout

| Variant | Where | Examples | Kit-side namespace | Project-side |
|---|---|---|---|---|
| **Universal** (per COR-003) | within an area | decisions, rules, agents | `core/` | `project/` |
| **Bundle-based area** | within an area | workflow today; future ci, release, language profiles | `bundles/<name>/` | `project/<name>/` |
| **Adapter** | at methodology top-level | claude-code today; future codex, cursor | `.pkit/adapters/<name>/` | (per-adapter; adapter docs its own) |

Universal areas have one canonical version of each content type, so the core-side is flat. Bundle-based areas have multiple parallel implementations of one contract, so the core-side is partitioned by bundle name. Adapters partition the methodology's harness-translation work by harness name at the top level.

### Bundle-based area structure

```
.pkit/<area>/
├── README.md                          # area README: contract + bundle index
├── bundles/                           # core-owned (propagation): all available bundles
│   └── <bundle-name>/
│       ├── README.md                  # this bundle's contract + adopter setup
│       ├── (optional) config.template.yaml   # schema the adopter must fill
│       └── (area-specific internals)  # templates, primitives, composites — per the area's contract
└── project/                           # project-owned (extension)
    └── <bundle-name>/                 # bundle is "installed" iff this directory exists
        ├── config.yaml                # adopter's filled config
        └── (future) overrides/        # project-side overrides of bundle internals
```

### Adapter structure

```
.pkit/adapters/
├── README.md                          # what an adapter is, how to add new harnesses
└── <adapter-name>/                    # one directory per harness
    ├── README.md                      # what this adapter ships
    └── (harness-specific content)     # settings files, deploy scripts, runtime artifacts —
                                       # whatever the harness needs
```

Within an adapter, content is harness-specific. Where the adapter has both core and adopter content of the same kind (e.g. settings.json with core baseline plus adopter additions), it can apply the universal area pattern internally — `<concept>/core/` + `<concept>/project/` — to keep the rule consistent.

### Install signal

A bundle is **installed** when `.pkit/<area>/project/<bundle-name>/` exists. The directory's presence is the signal — same convention as decisions, where a decision is part of the project iff `.pkit/decisions/project/PRJ-NNN-*.md` exists. No separate marker file, no `enabled` flag, no parallel manifest.

For an adapter, "installed" is not a single signal — adapters carry a mix of content (settings to merge, deploy scripts to run, etc.), and "installed" means the relevant deployments have been performed. Each adapter documents its install model in its own README.

### Universal elements

Every **bundle** ships at minimum:

- `README.md` — what the bundle provides, prerequisites, adopter setup.
- (optional) `config.template.yaml` — schema declaring values the adopter must fill.

Every **adapter** ships at minimum:

- `README.md` — what the adapter handles, what content it ships, how to deploy it.

Beyond these, internal structure is determined by the area's or harness's specific concerns.

### Authoring surface

For each component type defined here, core ships an authoring command that scaffolds the contract. Bundles and adapters today; future component types added by future records arrive with their own scaffold command on the same surface.

The commands (specified in `.pkit/cli/README.md`, materialised by the install/sync runtime per the build roadmap):

- **`pkit new bundle <area> <name>`** — scaffolds a bundle within an area declared (per COR-011) as the bundle-based variant. Stamps `package.yaml`, `README.md`, `migrations/`, `config.template.yaml`, and any area-specific internals the area's contract names.
- **`pkit new adapter <name>`** — scaffolds a top-level adapter at `.pkit/adapters/<name>/` with `package.yaml`, `README.md`, baseline-settings template, primitive stubs, and `migrations/`.
- **`pkit new migration --tier <backbone|bundle|adapter> [...]`** — drops a numbered script into the right `<major>.<minor>.0/` directory with the script-contract boilerplate from the lifecycle spec.

Each command produces a directory whose layout matches the contract this record fixes; each wires the new component into the lifecycle spec's manifest layer (per COR-010) at scaffold time. Templates live where their contract lives — `.pkit/lifecycle/templates/` for migration scripts and per-component manifest skeletons; `.pkit/cli/scaffolds/` for bundle/adapter directory shapes — so a backbone upgrade that changes a contract also updates what gets stamped.

### Skill / command pairing

Every authoring command in the methodology's CLI ships with a paired **skill** that is the agent-facing entry point for the corresponding authoring task. The script does the deterministic stamping; the skill does the disciplines, the slug choice, the body drafting, and the gates. Authors who explicitly want only the stamp call the script directly; agents and humans following the intended path invoke the skill.

The pairing in effect today and as future commands ship:

| Authoring command | Paired skill | Status |
|---|---|---|
| `pkit new decision <namespace> <slug>` | `decision-author` | ships today (`.pkit/skills/core/decision-author/`) |
| `pkit new bundle <area> <name>` | `bundle-author` | ships when the command lands |
| `pkit new adapter <name>` | `adapter-author` | ships when the command lands |
| `pkit new migration [...]` | `migration-author` | ships when the command lands |
| `pkit new area <name>` | `area-author` | ships when the command lands |

Each skill's frontmatter declares `metadata.wraps_command` naming the command it pairs with, so a skill registry (today: filesystem walk; future: a `pkit skills list` lookup) can answer "which skill is the entry point for command X?" deterministically.

### Cross-bundle project-side content

Areas may carry project-side content not tied to a single bundle — for example, workflow definitions in `.pkit/workflow/project/<workflow-name>.md` that reference a bundle by name. Such content lives at the top of `project/`, alongside (not inside) the per-bundle directories. Its shape depends on the area; this record does not constrain it.

## Rationale

**Why distinguishing universal, bundle-based, and adapter as three variants.** The trigger for needing alternative-style namespacing is *whether multiple alternatives exist of the same kind of content*. Universal areas have one canonical version per content type; bundle-based areas have many backends implementing one contract; adapters have many harness-specific translations of core content. Treating all three with one mechanism would either flatten useful distinctions or force universal areas into needless nesting.

**Why `bundles/` and `adapters/` rather than reusing `core/`.** Both directory names carry the meaning the prose was trying to: "these are alternatives, pick one." A reader landing on `.pkit/workflow/` or `.pkit/adapters/` understands immediately that there is a menu. Putting these under `core/` would lose that signal and force every reader to learn that "core" sometimes means "one canonical version" and sometimes means "container for alternatives."

**Why bundles are area-internal and adapters are top-level.** A bundle implements an area's specific contract — the github-issues bundle's primitives only mean something within the workflow area. The bundle's home is naturally inside its area. An adapter, by contrast, holds harness-translations for content from across the methodology (skills, agents, settings, hooks). Placing adapters at top-level keeps each adapter able to carry content from any area.

**Why presence-of-`project/<name>/` as install signal for bundles.** The decisions area already establishes the convention: a decision is part of the project iff its file exists in `project/`. Carrying the same rule to bundles — a bundle is installed iff its directory exists in `project/` — keeps the methodology consistent. Introducing a separate `installed/` folder, an `enabled: true` flag, or a parallel manifest would each be a second source of truth that can drift from the actual project state.

**Why adapters need their own install model.** An adapter's content is heterogeneous — config files merged into adopter-side files, deploy scripts that produce symlinks, runtime artifacts. There is no single project-side directory whose presence means "installed." The adapter's README documents what installation means for that adapter.

**Why the shared universal-element minimum (README plus optional config template) is so light.** Beyond these, what each bundle or adapter ships depends entirely on its specific concern. Imposing further universal structure (e.g., "every bundle must have a `primitives/` directory") would be wrong because non-workflow bundles wouldn't have primitives. Per-area and per-harness contracts handle the rest.

**Why authoring belongs on the public surface.** Adopters who write their own bundles (custom workflow backends) or adapters (in-house AI harnesses) are first-class users of the methodology, not maintainers of the framework source. The contract this record fixes is theirs to satisfy; the tooling to satisfy it cleanly should be theirs to use. Hiding scaffolding behind framework-internal scripts would re-create the gap the record already closed for *consumption* — half the methodology surface available to adopters, the other half not.

**Why scaffold commands rather than templates-only.** A doc plus a templates directory ("clone this directory, rename, fill in") would cover most of the work but would force every author to also wire the new component into manifests, registries, and the lifecycle spec by hand — exactly the kind of mechanical sequence that COR-007 says should earn tooling. The command performs the wiring deterministically; the templates are the command's substrate, not a parallel surface.

**Why bundle authoring takes area as an argument.** A bundle is area-internal by this record's structural rule (`.pkit/<area>/bundles/<name>/`). Treating "bundle" as an unqualified token would couple the verb to whichever area happens to host bundles today (workflow), which is exactly the coupling COR-011's areas-first-class principle is meant to break.

**Why every authoring command is paired with a skill.** A bare command does deterministic stamping but cannot enforce process — disciplines (axiom / project-neutrality / principles-not-inventory), the acceptance gate, the bump policy, the slug-choice judgement. A skill carries the process; the script carries the substrate. Splitting the responsibilities along COR-006's discriminator (skills are conversational and judgement-bearing; commands are deterministic and idempotent) means each artifact stays minimal and the methodology's authoring discipline is encoded as runnable agent guidance rather than prose nobody re-reads. Pairing them by convention — every command lands in the same PR as its skill — keeps the surface coherent. Without the pairing rule, agents and humans tend to call the script directly, skip the disciplines, and produce records / components that don't pass review (this was the failure mode of an early hand-authored record that picked the wrong number and bypassed the skill that would have used `pkit new decision` correctly; the pairing principle and CLAUDE.md surfacing are the structural fix).

### Alternatives considered

- **Top-level `installed/` peer to `bundles/` and `project/`.** Rejected — deviates from COR-003's two-level top namespace (core-side + `project/`) without buying clarity that `project/<name>/` doesn't already provide.
- **Separate `installed.yaml` manifest in `project/`.** Rejected — introduces a second source of truth (the manifest vs. the directory listing) that can drift.
- **`enabled: true` flag inside each bundle's config.** Rejected — implicit, doesn't surface in directory listings, adds a hand-edited field easy to forget.
- **Bundles under `core/<bundle-name>/` rather than `bundles/<bundle-name>/`.** Rejected — overloads `core/` and loses the visual signal that the area has alternative implementations.
- **Universal areas use `bundles/<name>/` with always exactly one entry.** Rejected — wrong shape: universal areas don't have alternatives. A "bundles" directory with one fixed entry is just `core/` with extra nesting.
- **Adapters as bundles inside a `.pkit/harness/` area.** Rejected — adapters cut across multiple areas (their content includes skill deploys, agent deploys, settings, etc.), so they don't fit cleanly inside a single area. Top-level placement matches their cross-cutting role.
- **Distribute harness-specific content per area** (e.g. `.pkit/skills/deploy-claude-code.sh`, `.pkit/agents/deploy-claude-code.sh`, `.pkit/runtime/settings.json`). Rejected — scatters harness-flavoured content across the corpus, and each new harness multiplies the scatter. Adapter umbrella consolidates.
- **Authoring as a doc + templates directory only, no command.** Rejected — leaves the manifest wiring to the author and re-introduces the inconsistency removing the consumption gap was meant to fix. Per COR-007, mechanical sequences earn tooling.
- **Bundle authoring command without an area argument.** Rejected — couples the verb to the single bundle-based area that exists today (workflow), contradicting COR-011's areas-first-class principle.
- **Authoring commands as framework-internal-only (not on the public surface).** Rejected — adopters who write their own bundles or adapters need them. Half-public is worse than fully-public.
- **Authoring commands without paired skills (let agents discover them ad-hoc).** Rejected — empirically observed: agents skip the disciplines when there's no skill to invoke; the pairing rule + CLAUDE.md surfacing fixes this structurally.
- **Skills only, no commands (skills do the stamping themselves).** Rejected — skills are conversational; reproducible mechanical stamping (numbering, frontmatter, paths) belongs in a deterministic command per COR-006. Skills calling commands keeps both artifacts minimal.
- **Auto-generate skills from commands via a meta-skill.** Rejected for now — over-engineers a convention that is just "ship the skill in the same PR." If the convention is followed by review, no meta-skill is needed.

## Implications

- **Each area's README declares its shape.** A universal area's README says what's in `core/`. A bundle-based area's README lists what's in `bundles/` and explains the install model. The `.pkit/adapters/` README explains the adapter umbrella; each adapter's own README explains what that adapter ships.
- **The install/sync runtime manifest** treats core-side paths uniformly: every path under `core/`, `bundles/<name>/`, or `.pkit/adapters/<name>/` is propagation; project-side paths are extension. Per-adapter or per-bundle config files are extension targets, seeded from their respective `config.template.yaml` files.
- **CLI bundle commands** (per COR-004's surface) operate on bundle-based areas: `list` reads `bundles/` and `project/<name>/`; `install` creates `project/<name>/` with seeded `config.yaml` and runs the bundle's stamping/setup; `remove` removes `project/<name>/` per COR-004's "leaves project-owned content alone" rule. Adapter-equivalent commands (likely `pkit adapter <verb>` or similar) follow when the CLI ships.
- **Suspension within a bundle** — overriding individual bundle internals (e.g. swapping a workflow primitive) — uses `.pkit/<area>/project/<bundle>/overrides/`. The precise precedence rule is per-area (and per-bundle-type within the area); each area documents its own.
- **Adding a new bundle-based area** (CI, release, language profile) follows this pattern: `.pkit/<new-area>/{README.md, bundles/<name>/, project/<name>/}` with bundle internals shaped to the area's contract.
- **Adding a new harness** (Codex, Cursor, etc.) means creating a new directory at `.pkit/adapters/<harness>/` with a README and the harness-specific content. No new structural decision needed.
- **Authoring CLI commands are public surface.** `pkit new bundle <area> <name>`, `pkit new adapter <name>`, `pkit new migration [...]` are documented in `.pkit/cli/README.md` alongside the consumption commands.
- **Templates location.** `.pkit/lifecycle/templates/` for manifest + migration skeletons; `.pkit/cli/scaffolds/` for bundle/adapter directory shapes.
- **Scaffold output is wired.** A new bundle or adapter created via these commands is registered and discoverable by `pkit status` immediately — no manual manifest edits needed.
- **Implementation is blocked on the install/sync runtime** (the build roadmap); this record fixes the principle and the public command shapes, not the timeline.
- **Skill / command pairing is enforced by review.** Every PR introducing a new authoring command must also ship its paired skill. Skills declare `metadata.wraps_command` so the pairing is queryable from the skill registry, not just prose.
- **CLAUDE.md surfaces the pairing rule** so agents see "for authoring tasks, invoke the paired skill rather than the command directly" early in every session. The rule plus the pairing table is what closes the discipline gap empirically observed in earlier hand-authored records.

