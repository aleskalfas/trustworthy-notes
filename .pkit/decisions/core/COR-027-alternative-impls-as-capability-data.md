---
id: COR-027
title: Alternative implementations live as capability-internal data, not as bundles
status: accepted
date: 2026-05-27
author: Ales Kalfas <kalfas.ales@gmail.com>
---

> **Note on COR-005 relationship.** This record retires the **bundle half** of [COR-005](COR-005-bundle-pattern.md). The adapter pattern + skill/command pairing rules in COR-005 stand; COR-005 stays `accepted` for that reason (see its top-of-file refinement note). The `supersedes:` frontmatter field is intentionally omitted — the schema's `supersedes:` semantics are whole-record, and this is a partial refinement.

## Context

[COR-005](COR-005-bundle-pattern.md) (dated 2026-05-05) introduced **bundles** as a pluggable pattern alongside adapters: *"area-internal alternative backends. They sit inside an area: `.pkit/<area>/bundles/<bundle-name>/`. Alternative implementations selected from a set."* The motivating use case was work-tracking-backend implementations — `github-issues` today, `linear` or `jira` tomorrow — behind a common area-level contract.

Thirteen days later, [COR-017](COR-017-capability-pattern.md) (dated 2026-05-18) introduced **capabilities** as the packaging primitive for opt-in installable disciplines. Capabilities ship the full surface (decisions, skills, agents, scripts, schemas, migrations) for one discipline; multiple capabilities coexist additively in a single project.

In the time since, the kit has lived with both patterns. The lived evidence:

- **Bundles produced exactly one concrete instance** — `github-issues` at `.pkit/workflow/bundles/github-issues/`. It ships templates + label schema; the "primitives" the bundle was supposed to provide (`work-start`, `work-promote`, etc.) were never built.
- **The pm capability bypasses the bundle** — its ~30 scripts call `gh` directly per its own [DEC-003-github-bound-substrate](../../capabilities/project-management/decisions/DEC-003-github-bound-substrate.md). The capability never used the bundle's anticipated primitive layer.
- **DEC-003 explicitly rejects the use case bundles were designed for** — tracker-agnosticism (Linear/Jira/etc. as alternative work-tracking backends). DEC-003's stated escape hatch for non-GitHub adopters is a *separate capability* (`project-management-linear`), not a swapped bundle behind the same capability.
- **Every other "modular methodology unit" use case became a capability** — `release-management`, `evidence`. None became a bundle within an area.
- **No second bundle in any area materialised** in the kit's lifetime.

The two patterns overlap structurally: both are filesystem-level packages with `package.yaml`, install/uninstall flow, version pinning, `requires_backbone` compatibility, project-side state. Their conceptual difference (bundle = area-internal alternative; capability = standalone discipline) hasn't manifested in any concrete way. The bundle layer is an empty abstraction.

This record retires the bundle pattern and pins the principle for handling future alternative-implementation needs within capabilities.

## Decision

**Alternative implementations of a capability's internals live as capability-internal *data*, not as filesystem-level bundles.**

When a capability has multiple variants of some internal aspect (storage backend, ecosystem integration, format implementation, etc.), the variants are expressed as data the capability's scripts consume — typically a `schemas/<aspect>/<variant>.yaml` directory the adopter's config selects from. No separate filesystem-level package, no separate install/uninstall flow, no parallel hierarchy.

Concrete shape:

```
.pkit/capabilities/<name>/
├── schemas/
│   └── <aspect>/
│       ├── variant-a.yaml
│       ├── variant-b.yaml
│       └── README.md       # how to add a new variant
├── scripts/
│   └── <op>.py             # reads the configured variant; dispatches behaviour
└── project/
    └── config.yaml         # adopter selects the variant for this aspect
```

The capability's scripts and agent read the configured variant's schema at runtime (per [COR-018](COR-018-capability-schemas.md)) and dispatch behaviour accordingly. Adding a new variant is a new YAML file in `schemas/<aspect>/`; no CLI ceremony, no new component install.

### What this retires

- **The bundle pattern as a methodology mechanism.** The CLI commands (`pkit bundle install`, `pkit bundle list`, `pkit bundle remove`, `pkit new bundle`) and the `bundle-author` skill ship out with this record's acceptance.
- **The bundle-based area variant.** [COR-011](COR-011-areas-first-class.md)'s area-variant taxonomy drops `bundle-based`. The remaining variants (universal, adapter-umbrella, specialized) continue.
- **The `workflow.*` hook namespace.** Was designed as the bundle-provider hook mechanism; with no bundles, no providers, no consumers.

### What this preserves

- **Adapters at `.pkit/adapters/<name>/` continue.** The structural similarity to bundles that COR-005 noted is real, but adapters carry harness-specific knowledge that genuinely doesn't fit inside any capability (claude-code's deploy mechanics aren't a discipline's content — they bridge the discipline to a specific harness). The adapter pattern stays.
- **[COR-017](COR-017-capability-pattern.md) (capability pattern) continues unchanged.** This record narrows COR-005's scope but doesn't touch COR-017.
- **[COR-018](COR-018-capability-schemas.md) (capability schemas)** is the substrate for this record's principle. The schema mechanism is how variants are expressed.

## Rationale

**Lived evidence ranks higher than initial design.** COR-005 was a reasonable hypothesis when authored (early in the kit's life, before capability shape was settled). The time since produced exactly one bundle, no second bundle ever, and a deliberate rejection (DEC-003) of the use case bundles were designed for. Per [COR-007](COR-007-pattern-extraction.md), abstractions follow recurrence; an abstraction with no second consumer that contradicts an explicit decision is over-built.

**Capabilities absorbed the structural use case.** Every "modular installable methodology unit" the kit has added since COR-017 became a capability. The bundle namespace is empty; the capability namespace is full. The capabilities-eat-everything pattern is the lived shape; this record names it.

**Data-driven variation is simpler than filesystem-driven.** A capability with multiple variants of some aspect (e.g., a future `release-management` capability supporting python-uv / npm / cargo ecosystem variants) needs the variants to be reachable by the capability's scripts at runtime. Two ways to do this: (a) variants as YAML files in `schemas/<aspect>/` the script reads — one filesystem location, one install flow, one config field selects; (b) variants as separate bundles the adopter installs separately — multiple filesystem locations, separate install flows, no clear selection mechanism. (a) is strictly simpler and matches how COR-018's capability-schema mechanism is already used.

**Pre-1.0 tolerates breaking CLI changes.** Per [PRJ-002](../project/PRJ-002-version-bump-policy.md)'s pre-1.0 policy, breaking surface changes are acceptable in minor bumps. Removing the `pkit bundle` family + `pkit new bundle` + `bundle-author` skill is a breaking change tolerated by the policy.

### Alternatives considered

- **Leave COR-005 as-is; refine in place to note n=0 instances.** Rejected — investigation surfaced that the bundle pattern's conceptual space is fully absorbed by capabilities. Keeping COR-005 as a "pattern that may earn its keep someday" leaves dead CLI commands, dead area-variant handling, dead hook namespace, and dead skill in the kit. The honest move is supersession.

- **Keep `pkit bundle` commands as no-op stubs.** Rejected — stubs with no consumers are kit-debt. If a future need surfaces, the right move is a new CLI command shaped to *that* need, not to preserve commands designed for a use case that didn't materialise.

- **Migrate the github-issues bundle into the pm capability.** Rejected — its templates are GitHub-UI issue forms; the pm capability is agent-driven per [project-management:DEC-008-pm-and-implementer-roles], so the UI templates aren't load-bearing. They can be dropped without replacement.

- **Make bundles a sub-shape of capabilities (every capability optionally has internal bundles).** Rejected — adds filesystem-level layering inside capabilities for a use case (multi-variant within a capability) that COR-018's schema mechanism already serves with strictly less ceremony.

## Implications

### Records

- [COR-005](COR-005-bundle-pattern.md) is **superseded** by this record. Its status flips to `superseded`; its body gains a top-of-file "Superseded by COR-027" line. The bundle pattern as a methodology mechanism is retired.
- [COR-011](COR-011-areas-first-class.md) refines in place: the `bundle-based` area variant is dropped from the taxonomy. The variant had one instance (`.pkit/workflow/`) which is also being removed.

### Code

- **CLI commands removed**: `pkit bundle install`, `pkit bundle list`, `pkit bundle remove`, `pkit new bundle`. Breaking change in the next backbone minor bump.
- **Python module retired**: `src/project_kit/bundles.py` and `stamp_bundle` from `scaffolds.py`.
- **CLI command group `bundle`** removed from `cli.py`.

### Kit content

- **`.pkit/workflow/` directory removed entirely** — was the only bundle-based area, with the only bundle (`github-issues`). The "Git conventions" reference content (conventional commits type table, branch naming) the workflow README carried moves into [COR-008](COR-008-git-conventions.md) (its principle's home).
- **`.pkit/skills/core/bundle-author.md` removed**.
- **`.pkit/skills/core/area-author.md`** is refined to drop bundle-based variant handling.
- **`.pkit/agents/README.md`** drops the `workflow.*` hook namespace documentation (no providers exist post-bundle-removal).
- **Cross-reference sweep**: CLAUDE.md, manifest.yaml, lifecycle README, rules/core.md, convention-compliance-reviewer agent, and the CLI README's bundle section are updated.

### Migration

A backbone-tier migration script ships with this record's acceptance handling:

- Removal of `.pkit/workflow/` from installed adopters (handled by sync; no migration action needed).
- Removal of any adopter-side `.pkit/workflow/project/<bundle-name>/` directory (project-owned; the migration prompts for cleanup since sync doesn't touch project-owned trees).
- Manifest cleanup: any `bundles:` registry entries in `.pkit/manifests/` for the github-issues bundle.

Idempotent per [COR-010](COR-010-resource-lifecycle.md)'s migration script contract.

### Forward implications

- Future capability variants (storage backends, ecosystem implementations, format variants) follow this record's principle. The capability author ships a `schemas/<aspect>/` directory with one YAML per variant and an adopter config field that selects.
- If a future use case genuinely doesn't fit the data-driven shape (some structural need that requires separate filesystem packages within a capability), it can author a successor record arguing for the new mechanism. This record is the current best-known principle; future evidence may refine it.
