---
id: COR-010
title: Lifecycle of installed resources
status: accepted
date: 2026-05-07
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

The core layer installs more than just files. Some resources live in the project tree (the core content directory, fixed-path config files, deployed symlinks); others live outside it (issues-tracker labels, project boards, eventual webhooks / branch-protection rules / etc., per the platform an adopter targets). All of these are *installed by the core layer* — created by it, expected to evolve as core content evolves, and possibly removed on uninstall.

Existing records cover parts of this:

- COR-001 covers in-tree content lifecycle (propagation, extension, suspension, install-time seeding).
- COR-002 covers fixed-path config-file updates (merge delivery operation).
- COR-004 names the upgrade command with "version-aware migrations" but doesn't specify what migrations are or how they're authored.
- COR-005 establishes bundles and adapters as pluggable components with their own contracts.

What's missing is a unified principle: **what does it mean for a resource to be installed by the core layer**, what lifecycle operations apply across all such resources, how does the methodology version itself, and how do component versions relate to the methodology's version? Without this, each new resource type and each component re-derives tracking, update, and removal semantics from scratch, and version transitions remain ad hoc.

This record fixes the rules. The architecture (manifest schema, upgrade procedure, migration directory layout, register/unregister mechanics, worked examples) is specified in `.pkit/lifecycle/README.md`.

## Decision

Core content is organized in two tiers — a **backbone** that ships together, and **components** that depend on backbone versions but evolve independently. Project-side state is tracked through a backbone manifest (registry of installed components) plus per-component manifests (each component's state). Lifecycle operations apply uniformly across resources; whole-methodology upgrade orchestrates per-tier and per-component updates under explicit compatibility resolution.

### Two tiers: backbone + components

The backbone is the cohesive core: decisions, rules, the workflow-framework contract, the CLI / runtime. It ships as a single coordinated release with one version number. Components — bundles and adapters — are installable, independently-versioned pieces that depend on a backbone version range.

Both tiers use semantic versioning (`major.minor.patch`). Components express compatibility via `requires_backbone: ">=X.Y.Z, <W.0.0"` recorded in their per-component manifest. Patch-level releases (the third segment) are backward-compatible bug fixes by semver convention and do not have migrations — migration directories are named with the full three-segment target version, with patch always `0` (e.g., `2.1.0/`), and cover all patches within that minor line.

A backbone change affects every adopter (the methodology itself moved); a component change might only affect adopters who installed that component. Independent versioning lets bundle / adapter authors release without bumping the whole methodology, and lets adopters upgrade selectively, with the semver range catching incompatibilities at upgrade time.

### Per-component manifests + backbone registry

Project-side state is split per component, with the backbone manifest acting as registry. The backbone manifest carries the recorded backbone version + a list of installed components, each pointing at its per-component manifest file. Each component owns its own manifest at the component's own project-side path.

Install adds a registry entry and creates the component manifest; remove deletes both. Status / validate / upgrade walk the registry to find component manifests, then operate per component. The backbone manifest does not duplicate per-component data — it is an index, not a god-file.

### Manifest content: non-derivable state only

Each manifest carries only what cannot be re-derived from the core spec at the recorded version + the adopter's config:

- The recorded version of its tier (backbone or component).
- Opaque backend identifiers (project-board UUIDs, webhook IDs, etc.) the methodology cannot rederive.
- For the backbone manifest: the component registry.

State that *is* derivable — files under the core content directory, deployed symlinks, issues-tracker labels, merged-config permission entries, propagated templates — does not appear in any manifest. The setup primitive at the recorded version regenerates it on demand from the spec + adopter's config.

### Lifecycle operations apply uniformly

Four operations apply to every resource the core layer installs, regardless of resource type or tier:

1. **Install** — the relevant tier's setup primitive creates the resource and (for non-derivable state) records it in the appropriate manifest.
2. **Inspect** — `status` walks the registry, reads each component manifest, surfaces aggregated state. `validate` computes expected state for derivable resources from the spec at the recorded version + adopter's config and compares to reality; manifest-tracked resources are compared directly.
3. **Update** — re-running the setup primitive reconciles installed state with the current version's spec. Derivable resources are regenerated; non-derivable resources are updated via their recorded opaque ID. Idempotent.
4. **Remove** — the bundle / adapter remove command tears down the component's resources, deletes its per-component manifest, and removes its registry entry. Adopter content is never touched (per COR-005 + the no-shared-files invariant).

### Three migration scopes per tier

Migrations come in three categories by scope. Each tier (backbone, component) has its own migration tree.

- **Manifest-schema** — bridge a manifest-format change. Each manifest has its own schema; bumping either may need its schema migrated. They run *first* in any upgrade flow that touches them — the runtime needs to read the manifest correctly before tracking subsequent migrations.
- **Structural** — affect the directory shape of the tier (a backbone-wide rename; a bundle's internal restructure within the bundle). They run *before* resource-scoped migrations of the same target version.
- **Resource-scoped** — affect a single resource type (a label is renamed, a setting key changes shape, a primitive moves).

Migrations are versioned (tied to a specific tier-and-version transition), idempotent, and update the affected resource. For manifest-tracked resources, the migration also updates the relevant manifest entry. For derivable resources, no manifest update is needed — the upgrade flow's reconciliation step regenerates the state from the new spec.

### Cross-tier upgrade requires explicit compatibility resolution

A whole-methodology upgrade cannot proceed past a component's `requires_backbone` range. Before applying any migrations, the upgrade command resolves compatibility across all installed components and either succeeds (every component is compatible with the target backbone, possibly after upgrading some components) or refuses with a surfaced conflict for the adopter to address.

The reconciliation order — compatibility resolution → propagation → backbone migrations → component migrations → derivable-state reconciliation → recorded-version updates — is set by the lifecycle spec and applies symmetrically to per-component upgrades (which gate on the same compatibility check).

### Migrations are mandatory on adopter-breaking surface changes

A change that **alters an installed adopter's state observably and breaks against it** must ship a migration script in the same change-set (commit or PR) at the tier whose state it perturbs. Examples of triggers:

- File or directory **renames** in kit-owned trees (a skill moves from flat to composite folder; a record's slug changes; a bundle's internal layout shifts).
- File or directory **removals** in kit-owned trees (a skill is deprecated; a capability is split).
- `schema_version` bumps in any YAML schema whose shape changes incompatibly.
- Breaking signature changes in `pkit` CLI commands (a flag's meaning inverts; a subcommand renames).
- **Capability subtree restructures** (a capability's `skills/`, `agents/`, `decisions/` layout changes).

Pure additions don't trigger migration: a new skill, a new schema, a new decision, a new bundle are observed only by adopters who sync to receive them, and their absence doesn't break against existing installed state. Documentation refinements, internal source refactors, and behavior-preserving fixes also don't trigger.

The rule applies symmetrically across tiers: backbone surface changes ship backbone migrations; bundle surface changes ship bundle migrations; adapter and capability surface changes ship their tier's migrations. The migration is idempotent (already-applied state is a no-op) so adopters can re-run safely.

This couples surface changes to migration coverage: the version bump (per the project's version-bump policy) and the migration land together, not in separate PRs. The lifecycle's reconciliation order assumes every adopter-breaking change has a migration to run; merging surface changes without one leaves adopters with state the upgrade flow can't bridge.

## Rationale

**Why two tiers (backbone + components).** The methodology has parts that move together (decisions, rules, the workflow framework, the CLI) and parts that move independently (specific bundles and adapters). Forcing a single global version means every component bumps with every backbone change — high-noise releases, no surgical updates. Forcing fully independent versions everywhere ignores that the backbone is genuinely a coherent release. Two tiers, with components declaring backbone compatibility ranges, captures the reality.

**Why semantic versioning.** Adopters need predictable compatibility signals: a backbone minor bump shouldn't break component compatibility; a major bump might. Components express the contract via `requires_backbone` ranges, and upgrade enforces them. This is the model package managers (npm, Cargo, pip) use; the methodology benefits from the same precedent.

**Why a backbone manifest plus per-component manifests.** A single combined manifest would mix backbone and component state in one file — a corrupted edit affects everything; adding/removing a component touches a shared file. Per-component manifests give each component clean ownership of its state and make install/remove surgical (one file, one registry entry). The backbone manifest carries the versioned-glue layer (the overall version + the registry of components).

**Why the manifest is intentionally small at each tier.** Listing every core-managed resource (every file, every label, every symlink) bloats the manifest with state already determined by the core spec at the recorded version + adopter's config. Adopter manifests would churn on every core content release — high-noise diffs in version control with no information gain. Keeping each manifest scoped to recorded-version + opaque IDs (and the registry, for the backbone) makes its diffs meaningful (a bundle was installed; a board UUID was recorded) without duplicating derivable state.

**Why migrations don't always update the manifest.** If a migration affects a derivable resource, the new state is implied by the new core spec + adopter's config; reconciliation regenerates it. If a migration affects a non-derivable resource, the migration updates the relevant manifest entry directly. The migration only writes manifest entries when the entry is the source of truth.

**Why three migration scopes per tier.** Resource-scoped migrations have clear locality. Structural migrations don't fit any single resource's locality but still need a place to live and an ordering relative to resource-scoped ones (structural first, so the tree is in the new shape). Manifest-schema migrations bootstrap the very mechanism the runtime uses to track progress; they have to run first.

**Why compatibility resolution is a separate step.** Mixing it into the migration loop hides cross-tier conflicts until partway through an upgrade. Resolving up front lets the adopter see and address conflicts before any state changes — same precedent as package managers' resolver phase preceding the install phase.

**Why this record is principles-only.** Per the principles-not-inventory rule, it captures the two-tier model, the manifest framing, the registry mechanism, the migration scopes, and the compatibility precondition as durable rules. Specifics (manifest paths, entry formats, migration directory layouts, the upgrade command's exact output) are operational details that live in `.pkit/lifecycle/README.md` and evolve with the install/sync runtime.

### Alternatives considered

- **Single global version for everything.** Rejected — couples components to the backbone's release cadence. Bundle hotfix requires bumping backbone; adopters who only use one bundle still get backbone churn.
- **Fully independent versioning with no backbone tier.** Rejected — the methodology has cohesive content (decisions, rules, framework) that should ship together. Treating each piece as fully independent is over-decoupling.
- **Manifest enumerates every core-managed resource.** Rejected — bloats with derivable state that's already in the core spec + adopter config. High-noise PR diffs every time core content evolves.
- **One unified manifest for backbone + all components.** Rejected — mixes ownership, makes adding/removing a component a shared-file edit. Per-component manifests + backbone registry give cleaner separation.
- **No project-side manifests at all (everything implicit by convention).** Rejected — opaque identifiers (project boards, webhook IDs) and recorded versions need persistent storage.
- **No formal lifecycle; each resource type re-derives semantics.** Rejected — fractures the methodology. New resource types invent inconsistent behaviour and adopters can't reason uniformly.
- **All migrations in one global directory.** Rejected for component migrations — divorces them from the bundle or area that gives them context. Backbone-wide and manifest-schema migrations (which have no single component context) appropriately live in a backbone-wide location.
- **Migrations as one-shot scripts that don't track version state.** Rejected — re-running a migration on an already-migrated adopter would do harm. Recording the version plus idempotent re-runs prevents this.
- **Compatibility checked migration-by-migration instead of resolved up front.** Rejected — failures surface mid-upgrade after partial state changes. Resolver-then-applier (the package-manager pattern) is the safer order.

## Implications

- **The backbone manifest is part of the project's git tree** (extension content per COR-001), tracked, visible, diffable.
- **Per-component manifests live with their component's project-side directory.** Each component's adopter-side path gains a `manifest.yaml` alongside its config.
- **The component registry in the backbone manifest is the canonical install record** — install adds an entry, remove deletes one. Status walks it.
- **The status / validate / upgrade commands** all operate per component by walking the registry.
- **Backbone migrations live in a backbone-wide / runtime location**; **component migrations live within the component**. Specifics in `.pkit/lifecycle/README.md`.
- **Adopter customisations** — additions on top of the core baseline, project-side records, hand-written extensions — are never core-managed by definition. The manifests track only what the core layer creates, and only the parts that need explicit tracking.
- **Future formalisation.** As specific resource types and migration patterns accumulate, this record may spawn focused records (a manifest schema record, a structural-migration directory contract, a compatibility-resolution algorithm). For now, principles-only with the spec carried by `.pkit/lifecycle/README.md`.

- **Migration coverage is a release gate.** The kit ships a `pkit migrations check-diff` command that walks a diff for trigger changes (renames + removals in kit-owned trees, schema_version bumps, etc.) and verifies a corresponding migration landed. CI runs it on every PR; PRs with uncovered triggers fail until migrations land. The agent's pre-commit responsibility (per `.pkit/rules/core.md`) is to check the diff first; the CI gate is the durable safety net.
