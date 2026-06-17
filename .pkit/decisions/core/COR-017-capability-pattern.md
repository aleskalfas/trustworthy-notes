---
id: COR-017
title: Capability pattern — opt-in installable disciplines
status: accepted
date: 2026-05-18
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

Pkit today ships three packaging primitives:

- **Areas** (COR-011) — top-level slices of `.pkit/` (`decisions`, `agents`, `skills`, `scratchpad`, `workflow`, etc.). Areas are mandatory: every adopter has every area.
- **Bundles** (COR-005) — alternative implementations within a single bundle-based area (e.g., `github-issues` as one of several possible workflow bundles). Adopters pick at most one bundle per bundle-based area.
- **Adapters** (COR-005, COR-013) — translation layers to external systems. Today scoped to harnesses (`adapters/claude-code/`); adopters install one or more.

What's missing is a packaging primitive for **discipline-level opt-in**. Many methodology concepts — evidence-management citation discipline, product-management coordinator agents, observability conventions, audit-logging patterns — apply to *some* projects but not all. Without an opt-in primitive, the methodology either forces every adopter to inherit a discipline they don't need (wrong by COR-014's universal-applicability principle), or scatters discipline-specific content across adopters' project namespaces (loses reusability, leaks methodology work into adopter-owned files).

This gap was first articulated in a `example-adopter` scratchpad note proposing evidence-management as an opt-in discipline. The same shape recurs in pkit-itself: the `product-manager` and `orchestrator` agents shipped under COR-013 as universal core agents are not actually universal — they imply a particular product-management workflow many adopters lack. The `storyboard-author` skill from COR-016 is similar — useful only for projects building scripted-scenario agents. Three concrete cases is enough to extract the pattern.

This record introduces the **capability** as the missing packaging primitive.

## Decision

A **capability** is a self-contained installable unit of methodology — decisions, skills, agents, scripts, schemas — that adopters opt into per project. Capabilities slot alongside areas, bundles, and adapters as the kit's fourth packaging primitive.

### Structural shape

Each capability lives at `.pkit/capabilities/<name>/` as a self-contained subtree:

```
.pkit/capabilities/
├── <capability-name>/
│   ├── package.yaml                # manifest
│   ├── README.md                   # entry-point doc
│   ├── decisions/                  # capability-scoped decisions
│   │   └── DEC-NNN-<slug>.md
│   ├── skills/                     # skills the adopter invokes
│   │   └── <skill-slug>.md
│   ├── agents/                     # agents (optional)
│   │   └── <agent-slug>.md
│   ├── scripts/                    # runtime tools
│   │   └── <script>.py
│   └── schemas/                    # data-shape declarations
│       └── <schema>.json
```

The capability owns its subtree. Decisions, skills, agents are self-contained — no projection into the kit's main `.pkit/decisions/`, `.pkit/agents/`, `.pkit/skills/` directories. The kit's tooling (deploy primitives, validator, sync) extends to walk capability subtrees in addition to the existing area paths.

### Manifest schema

Each capability ships a `package.yaml` modeled on the kit's existing bundle/adapter manifests:

```yaml
schema_version: 1
component:
  kind: capability
  name: evidence
  version: 0.1.0
description: One-line summary surfaced in `pkit capabilities list`.
requires_backbone: ">=1.19.0,<2.0.0"
```

Required fields: `schema_version`, `component.kind`, `component.name`, `component.version`, `description`, `requires_backbone`. The `component.name` matches the directory name (`.pkit/capabilities/<name>/`). `component.version` is semver, independent of the kit's backbone version. `requires_backbone` mirrors the bundle/adapter convention.

Capability content is not enumerated in the manifest — the directory layout convention defines what files exist (mirrors how bundles and adapters work). Adding a new skill to a capability does not require manifest churn.

### Naming convention for capability artifacts

Filenames inside a capability follow the kit's existing per-type conventions:

- **Decisions** use `DEC-NNN-<slug>.md` filenames. The capability's directory is the namespace; no per-capability prefix is encoded in the filename (the path provides it).
- **Skills, agents, scripts, schemas** use slug-only filenames (`add-evidence.md`, `validate.py`), mirroring how core skills and agents are named in the kit today.

The asymmetry between numbered decisions and slug-only skills mirrors the kit's existing convention (CORs are numbered; core skills are not).

### Citation convention

Body prose cites capability decisions with a namespaced token:

```
Per [<capability-name>:<filename-stem>], every factual claim cites a record.
```

For example: `[evidence:DEC-001-citation-discipline]`. The capability name disambiguates from other capabilities and from the kit's core / project decisions; the filename-stem identifies the specific record.

Adopter content (PRJ records, project-side skill bodies, prose anywhere in the adopter's tree) can cite capability decisions using this form. The reference graph spans CORs, PRJs, and installed capability decisions.

### Lifecycle: install, sync, uninstall

Capabilities have an explicit install / sync / uninstall lifecycle, in contrast to areas (which are mandatory and have no install).

**Install** (`pkit capabilities install <name>`) copies the capability subtree from kit source into the adopter's `.pkit/capabilities/<name>/`, registers it in `.pkit/manifest.yaml`'s `components` list, and re-runs deploy primitives so the harness picks up the capability's skills and agents. Three pre-flight checks must pass before any files are touched: the capability exists in kit source; the kit version satisfies the capability's `requires_backbone`; no naming collisions exist with already-installed content. On collision, the install flow is interactive — for each colliding artifact the adopter chooses to override (replace; the prior content recovers via git), skip (the colliding artifact is omitted; the rest of the capability installs partially with the decision recorded in the manifest), or inspect (show a unified diff inline, then re-prompt with the same three choices).

**Sync** (`pkit sync`) auto-upgrades installed capabilities along with the rest of kit content. When the kit no longer ships a capability the adopter has installed, sync warns but does not auto-uninstall (adopter must explicitly remove). When sync would introduce a new collision (e.g., the upgraded capability now ships a skill that matches one the adopter authored project-side after install), sync refuses to upgrade that specific capability and instructs the adopter to run `pkit capabilities upgrade X --interactive` to resolve.

**Uninstall** (`pkit capabilities uninstall <name>`) refuses by default if references to the capability's content (citations of `[<name>:...]`, path references to the capability's scripts/schemas) exist in the adopter's tree. The adopter cleans references first, then re-runs uninstall. A `--force` flag overrides the safety check for adopters who explicitly accept dangling references (typical use cases: scripted migrations, replacing one capability with another).

### Collision prevention

Naming collisions between capabilities are prevented by **install-time validation**, not by reserving global namespaces in advance. Capability authors are advised to give their artifacts (skills, agents) names distinctive enough to avoid common conflicts; if two capabilities ship artifacts with colliding names, the second installation surfaces the collision via the install flow, and the adopter resolves explicitly.

Decision citations use the capability's directory name as the namespace token (`[evidence:DEC-001]`), so decision collisions across capabilities are structurally impossible — each capability's directory is unique.

### Relationship to existing primitives

| Primitive | Mandatory? | Lives at | Choice per project |
|---|---|---|---|
| Area | Yes | `.pkit/<area>/` | None — all areas exist |
| Bundle | The area is mandatory; bundle choice is optional | `.pkit/<area>/bundles/<name>/` | One per bundle-based area |
| Adapter | Optional | `.pkit/adapters/<name>/` | One or more per harness |
| Capability | Optional | `.pkit/capabilities/<name>/` | Zero or more per discipline |

Capabilities collaborate with other primitives via the kit's existing hook + reference-graph machinery: a capability's agent can declare `needs:` for hooks provided by installed bundles; a capability's skills deploy to harness-specific locations via installed adapters; a capability's decisions cite COR / PRJ records and vice versa.

## Rationale

**Why a new top-level concept rather than a fourth area variant.** Areas under COR-011 are mandatory and have three internal-layout variants (universal, specialized, bundle-based). Capabilities are *not* mandatory and have a different lifecycle (install / sync / uninstall) that areas don't have. Forcing capabilities into the area taxonomy would require either making some areas optional (breaks COR-011's "every area ships" rule) or inventing an `optional` variant that behaves nothing like the other three. A new sibling concept keeps the taxonomy honest: areas are the kit's mandatory backbone; capabilities are the kit's opt-in disciplines.

**Why self-contained subtrees rather than projection into existing areas.** An alternative considered: capabilities install their content *into* existing area folders (e.g., evidence's decisions land at `.pkit/decisions/core/` alongside CORs), with a manifest tracking ownership. Rejected because the projection model has compounding costs as capabilities multiply: file ownership becomes metadata rather than structural (have to consult the manifest to know which capability owns a record); core directories become variable namespaces (different content across different adopters); uninstall requires walking a manifest to find scattered files. The self-contained subtree makes ownership structural — the path tells you the owner. Uninstall is `rm -rf`. The trade-off is tooling extension (validator, deploy primitives must walk capability subtrees), which is finite one-time work.

**Why install-time collision detection rather than reserved namespaces.** The original proposal sketched per-capability prefixes (`EVR-NNN` for evidence-management's decisions). Rejected because 3-letter prefixes don't scale beyond a few capabilities and require a coordination registry. Using the capability's full directory name as the citation namespace (`[evidence:DEC-001]`) gives unlimited namespace depth, makes citations self-describing in body prose, and matches what authors already have to do (pick a directory name). Naming collisions for skills / agents (which don't have a global identifier) are caught at install time by the interactive flow, not by a registry.

**Why DEC-NNN-slug filenames for capability decisions, asymmetric with slug-only skills.** Decisions have natural ordering (chronological authoring) and benefit from being numbered for terse citations. Skills and agents are referenced by their `name` frontmatter (in deploy / harness loading), so prefixing their filenames adds ceremony without payoff. The asymmetry mirrors what the kit already does — CORs are `COR-NNN-slug.md`; core skills are `agent-author.md`.

**Why citations carry the full filename-stem rather than just the number.** A citation of `[evidence:DEC-001]` (number only) is terse but opaque — a reader has to look up the slug to know what the rule is. The full form `[evidence:DEC-001-citation-discipline]` is self-describing in prose. Adopters reading capability-heavy documents benefit from the longer form; the cost is verbosity, which is acceptable in body prose where readability matters most.

**Why interactive collision resolution rather than refusal.** Capability install could simply refuse on any collision (adopter must rename project content before retrying). Rejected because adopters legitimately have project-side content with names that overlap a capability's content, and the right resolution is per-collision: sometimes the adopter wants the capability's version, sometimes their own. Per-artifact interactive choice gives that agency. The skipped-artifact records persist in the manifest so sync respects them without re-prompting on each subsequent sync.

**Why uninstall refuses with references rather than auto-cleaning.** Cleaning references is adopter content work — the kit's general disposition is "never edit adopter prose." Refusing forces the adopter to do the cleanup themselves, which preserves their authorship. A `--force` escape hatch handles legitimate cases (migrations, replacing one capability with another) without making the destructive path the default.

### Alternatives considered

- **Capability as a fourth area variant in COR-011 (`optional` / `installable`).** Rejected — areas are mandatory by definition; making some optional inverts the principle. Capabilities are a sibling concept, not an area variant.

- **Capability as projection into existing areas (manifest declares which files belong to it).** Rejected — file ownership becomes metadata, namespace pollution in core directories grows linearly with capability count, uninstall complexity compounds. Self-contained subtrees are cheaper to reason about at scale.

- **Per-capability 3-letter prefix (EVR-NNN, PMG-NNN) for citations.** Rejected — doesn't scale beyond a handful of capabilities, requires a coordination registry. Directory-name namespace (`[evidence:...]`) is unlimited and self-describing.

- **Refuse install entirely on any collision rather than offering interactive resolution.** Rejected — too heavy-handed. Per-artifact choice respects adopter agency without forcing pre-install cleanup.

- **Auto-uninstall capabilities removed from kit source.** Rejected — silently removing files the adopter chose to install is a surprise. Sync warns; explicit uninstall removes.

- **Strip references automatically on uninstall.** Rejected — editing adopter prose violates the kit's "never touch adopter content" disposition. Adopter cleans references at their own pace.

- **Defer the concept entirely until a second example forces it.** Rejected this time — three concrete grounded cases exist already (evidence-management designed in example-adopter; product-manager + orchestrator agents shipped as core but mis-classified; storyboard-authoring skill similarly mis-classified). COR-007's recurrence threshold is met.

## Implications

### New kit content

- **`.pkit/capabilities/`** — new top-level directory. Empty by default in adopter trees; populates as capabilities are installed.
- **New CLI commands**: a noun-first `pkit capabilities` group — `pkit capabilities install <name>`, `pkit capabilities uninstall <name> [--force]`, `pkit capabilities upgrade <name> [--interactive]`, `pkit capabilities list`. All support `--dry-run`. (The grouping is harmonized with the other resource-domain groups; per COR-004 the exact spelling is a sub-principle spec choice.)
- **`pkit refs validate`** extension — walks `.pkit/capabilities/*/decisions/`, `.../skills/`, `.../agents/`; new citation regex for `[<capability>:<filename-stem>]`.
- **Deploy primitives extension** — `deploy-skills.sh` and `deploy-agents.sh` walk capability subtrees in addition to area-core and area-project.
- **Sync extension** — refreshes installed capabilities; surfaces no-longer-shipped capabilities; refuses upgrade on new collisions.

### Refinements to existing records

- **COR-011 (areas first-class)** gains a refinement noting capabilities exist as a sibling top-level concept; the area variant taxonomy is unchanged.
- **COR-010 (resource lifecycle)** may gain a refinement noting capabilities slot into the existing install / upgrade / uninstall framework as another component class.
- **COR-005 (bundle pattern)** is unchanged. The adapter-generalization-beyond-harnesses idea (sketched in the original handoff note) is deferred until a concrete capability surfaces that needs swappable backends.

### Variants within a capability

A capability that needs swappable implementations (e.g., a `project-management` capability with scrum-software vs kanban-flow variants) can use COR-005's bundle pattern internally — `.pkit/capabilities/<name>/bundles/<variant>/`. The exact convention for nested namespaces, citation forms, and install-time bundle selection is deferred until the first variant-needing capability surfaces. Separate top-level capabilities for each variant is an equally valid alternative; the choice depends on how much content the variants share.

### Retroactive reclassification

Two existing kit-shipped artifacts are candidates for reclassification as capabilities:

- ~~`product-manager` and `orchestrator` agents (shipped in COR-013 as universal core)~~ **Fulfilled 2026-05-27.** The placement rule was generalised in [COR-026](COR-026-agent-placement-by-discipline.md); the agents were retired from core and their role absorbed by the project-management capability's renamed `project-manager` agent per [project-management:DEC-029-project-manager-agent-shape]. Backbone migration `1.31.0/001-retire-pm-core-agents.sh` handles the adopter-state cleanup.
- `storyboard-author` skill plus the `pkit new storyboard` command (shipped in COR-016) — useful only for projects building scripted-scenario agents. A `scripted-scenario-authoring` capability would be the right home. **Still open** — COR-026's rule covers agents, not skills; the skill case requires its own disposition record per COR-006's discriminator.

Reclassification is a follow-on activity, not part of this record's initial implementation. Each move is a structural change (touches the agent / skill location) worth its own PR.

### Authoring tooling

A future `pkit new capability <name>` command, paired (per COR-005) with a `capability-author` skill, scaffolds a new capability with the canonical layout. Not part of this record's initial implementation; tracked as a follow-on once the first hand-stamped capabilities have shipped and the canonical layout has stabilised.

### Migration

No migration is needed for existing adopters. Capabilities are a new opt-in concept; existing kit-shipped content (CORs, area skills / agents) is unaffected unless and until reclassification work moves specific artifacts. When reclassification happens, each affected artifact gets a migration script per COR-010's framework.
