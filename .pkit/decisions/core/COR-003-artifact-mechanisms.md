---
id: COR-003
title: Mechanism assignment for artifact types
status: accepted
date: 2026-05-05
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

COR-001 set the three steady-state mechanisms (propagation, extension, suspension) and the install-time seeding delivery operation. COR-002 added merge as a second delivery operation.

What neither says is *how* a maintainer chooses a mechanism for any given artifact, or which cross-cutting principles govern the choice. Maintainer-side exploration settled per-artifact mappings during inventory work, but those mappings are operational state — they change every time content is added or relocated. The durable content is the *rules* by which any artifact gets mapped.

This record captures those rules. The actual list of paths and their current mappings lives outside the decision record — in each area's own documentation as content lands, and in the manifest the install/sync runtime reads.

## Decision

Any artifact under core governance is assigned exactly one steady-state mechanism (COR-001) and at most one delivery operation (seed per COR-001, merge per COR-002), by applying the principles below in order.

### Normativity governs suspendability

**Normative** content — decisions, hard rules, the methodology spec — is **propagation, not suspendable**. A project that overrides normative content is no longer practising the methodology; the override semantics defeat the purpose.

**Runtime instructions** — agent prompts, skills, workflow scripts — are **propagation, suspendable**. Projects legitimately need to override these (a project-specific code-reviewer prompt; a tighter docs-engineer scope). Each suspendable artifact type declares its precedence rule and disable semantics in its own documentation.

### Two-namespace pattern for areas with both core and project content

Already established in `.pkit/decisions/README.md`. Where an area carries both core-shipped content and project-owned additions of the same kind (more decisions, more agents, more workflows), the convention is parallel `core/` and `project/` directories with independent contents and numbering or naming. Core is propagation; project is extension; collisions resolve via the suspendability rule above (suspension when allowed; otherwise project content takes new names).

### Fixed-path project files = extension + delivery

Files that tooling expects at fixed paths (root `CLAUDE.md`, `.claude/settings.json`, `.mise.toml`, `.gitignore`, `CONTRIBUTING.md`) cannot be core-owned without violating the no-shared-files invariant. They are **extension** — project-owned — with a delivery operation handling the core layer's contribution:

- **Seed** (one-shot at install) when core's contribution is initial scaffolding the project takes over. Once stamped, the file is project-owned and the core layer never revisits.
- **Merge** (re-runnable) when core's contribution is a baseline that evolves with the methodology and must keep landing in the project's file across upgrades, append-only with respect to project additions.

The choice between seed and merge is determined by whether core's contribution ever needs to grow after install. One-shot fits seed; an evolving baseline needs merge.

### Runtime-deployment paths are not mechanism rows

Some project-side paths host content **regenerated** at sync/install time from source paths under the steady-state mechanisms (e.g., a runtime location assembled from a `core/` directory plus a `project/` directory under one source area). These deployment paths are gitignored, owned by neither party, and assigned no steady-state mechanism. The mechanism applies to the source paths; the deployment is a runtime concern documented in the source area's own runtime contract.

### Out of scope

The core layer ships, syncs, and seeds the methodology surface only — decisions, hard rules, agents, workflow bundles, and the project-side config baselines those bundles plug into. The core layer does **not** touch:

- **Project content** — architecture docs, domain methodology, use-cases, project-specific scripts, project-specific tooling.
- **Per-machine state files** — e.g., personal-overrides files, runtime worktree directories. The core layer may ensure these are listed in the project's `.gitignore`; nothing more.
- **Environment-tooling setups** the project chooses — direnv configuration, language toolchains, IDE-specific configuration.

These principles cover everything observed during inventory. New artifact types are assigned by working through them in order; no COR amendment is required unless a principle itself changes.

## Rationale

**Why principles, not a path-by-path map.** A decision record captures durable choices. A list of "which paths exist today and how each is treated" is operational state — it changes every time content is added or relocated. Pinning that state inside a COR forces an amendment per change and conflates the decision (the rule) with its application (the inventory). The principles are durable; the manifest changes; they belong in different places.

**Why the normativity-suspendability principle.** Suspension is structurally identical to extension — a project file at a colliding name. The contractual difference is whether the override is *permitted*. Decisions, rules, and methodology are the system's terms of practice; allowing override would let a project keep the label "uses the methodology" while having silently swapped out the methodology. Agents and scripts, by contrast, are how an automated participant *applies* the methodology; projects have legitimate reasons to vary them. The principle names the line that separates the two.

**Why seed and merge are distinguished.** Both are delivery operations on extension files. The difference is whether the core layer ever revisits the file after install. Seed is one-shot; merge is re-runnable. Picking the wrong one is recoverable but wasteful — a merge target whose baseline never evolves is just a complicated seed; a seed target whose baseline grows leaves projects without later updates.

**Why runtime deployment is kept off the mechanism list.** Deployment paths conflate "where the consumer reads" with "where ownership lives." Treating them as mechanism-bearing rows would force a fourth mechanism class (regenerated content) that adds nothing — the source-path mechanism already governs ownership; deployment is just where the runtime puts the result.

**Why an explicit out-of-scope boundary.** Without one, scope creeps into anywhere a maintainer thinks "we could ship a default for that." Declaring the methodology surface as the limit makes drift visible. Future expansions (e.g., language profiles) extend the surface only via dedicated records, not by accretion.

## Implications

- **No master mapping table inside this record.** Specific path-to-mechanism assignments live with their content as it lands — in each area's README, and in the manifest the install/sync runtime reads.
- **Each artifact area's README documents** its mechanism choice (with a reference back to whichever principle settles it), and — for suspendable types — its precedence rule and disable semantics; — for merge targets — its tier classification (auto-add vs prompt-once) and safety-enforce entries per COR-002.
- **The install/sync runtime manifest** partitions paths into three disjoint sets (synced, seed, merge) per COR-001/COR-002. The principles here govern *how* paths get assigned to a partition; the partition listing itself is operational data.
- **Adding a new artifact type** means working through these principles in order, picking a mechanism + delivery, and documenting the choice in the area's README. No COR amendment unless a principle itself changes.
- **Focused records spin off** when a single area's specifics outgrow its README — workflow bundles is the most likely first split (primitive contract, composite layer, default-workflow stamping, mise-tasks merge integration). Such a record references these principles without restating them.
