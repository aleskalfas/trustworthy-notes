---
id: COR-011
title: Areas as a first-class organizing concept
status: accepted
date: 2026-05-07
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

Core content is organised into top-level directories under `.pkit/`: `decisions/`, `cli/`, `skills/`, `adapters/`, `lifecycle/`. COR-003 established the universal `core/` + `project/` pattern within an area; COR-005 established the adapter-umbrella variant for areas with cross-cutting harness content. (COR-005's bundle-based variant was retired in [COR-027](COR-027-alternative-impls-as-capability-data.md).)

What's not yet captured anywhere is the **area itself** as a unit. Today areas exist as a convention — top-level directories with READMEs — without a record that names the concept, fixes its contract, or governs how new ones are added.

This becomes a problem the moment authoring tooling enters the picture. Commands like `pkit new adapter <name>` need a target they can dispatch on, and the scaffold needs a layout to stamp. Without an area concept, each command call has to embed area-specific knowledge; cross-area uniformity is by accident, not by rule. Adopters who want a new domain area (e.g., a "research" area for an academic-methodology project, a "deployment" area for ops content) have no sanctioned mechanism to add one — they would stamp from prose.

## Decision

An **area** is a first-class concept in the methodology: a named top-level slice of `.pkit/` with its own README, its own content layout, and a declared **variant** that determines its internal shape.

The variants are those established in COR-005 — universal (per COR-003), adapter-umbrella — plus *specialized* areas with no parallel-alternatives shape (e.g., `cli/`, `lifecycle/`). New variants are possible and arrive via their own COR record. (COR-005's original *bundle-based* variant was retired by COR-027.)

Each area's README declares the area's variant and its layout — what subdirectories exist, what content type lives there. Authoring tooling and cross-area inspection commands read the declaration; they do not re-derive shape from filesystem heuristics.

Adopters can create their own areas. An adopter-created area lives at `.pkit/<name>/` and is project-owned: never touched by sync, never part of the propagation manifest. The no-shared-files invariant rules out collisions with core-shipped areas because adopters cannot reuse a name the core layer already ships.

Core ships an authoring command for the area level itself: `pkit new area <name>` scaffolds an adopter-owned area with the README skeleton and the variant's expected layout. (The command is part of the broader authoring surface specified in the COR-005 amendment.)

### Capabilities as a sibling concept (refinement per COR-017)

Capabilities (introduced by COR-017) are top-level subtrees at `.pkit/capabilities/<name>/` that sit alongside areas. They are not areas: areas are mandatory and have no install lifecycle; capabilities are opt-in with explicit install / sync / uninstall. The area variant taxonomy (universal, adapter-umbrella, specialized — see COR-027 for the retirement of bundle-based) is unchanged by COR-017; capabilities are a sibling concept, not an area variant. An adopter's `.pkit/` therefore has two classes of top-level subtree: areas (every adopter has every one) and installed capabilities (per-project opt-in).

## Rationale

**Why formalise areas now.** With per-area conventions accreting (decisions has its `core/project` split; adapters has its harness umbrella; lifecycle ships a spec next to templates), the implicit-area regime is drifting. Naming the concept and fixing what each area must declare prevents future areas from re-inventing shape, and gives authoring tools a target to dispatch on.

**Why each area declares its own layout.** A single rigid layout (every area has `core/`) would force areas into needless nesting and would not fit the adapter umbrella at all. A rigid type tag (with a closed taxonomy) would multiply categorisation work without buying clarity — the variants reflect genuine content-shape differences. Letting each area's README declare its variant + layout keeps the rules where they apply, and lets new variants enter the system through their own records rather than through schema upgrades.

**Why adopters can add areas.** Extension is a first-class operation throughout the methodology: PRJ records sit alongside CORs, project-side bundles sit alongside core-side ones, adopter customisations sit alongside core baselines. Areas are the next level up. An adopter who needs a domain core does not ship (research, deployment, compliance, etc.) should not have to fork the methodology or stamp from prose to get it.

**Why a scaffold command rather than a doc.** Per COR-007, mechanical work earns tooling. Creating an area is a fixed sequence — make a directory, drop a README skeleton, slot the variant's expected sub-layout. A command makes the result uniform; a doc would require every adopter to read it and reproduce the steps by hand.

### Alternatives considered

- **Leave areas implicit; document conventions in `CONTRIBUTING.md` only.** Rejected — same rationale that motivated COR-005. Without a record, conventions drift, and authoring tools have no sanctioned target to dispatch on.
- **Enforce a single uniform layout across all areas.** Rejected — would force universal areas into needless nesting and does not fit the adapter umbrella at all.
- **Closed area taxonomy fixed in this record (only the four current variants are ever allowed).** Rejected — a closed taxonomy forces every future shape into one of the existing slots regardless of fit. New variants arriving via new CORs is the same evolution mechanism the rest of the methodology uses.
- **Only core declares areas; adopters extend within existing areas.** Rejected — constrains adopters who legitimately need new domain areas, and fights the methodology's broader pattern of first-class adopter extension.
- **Adopter-created areas live in a separate `project/` umbrella (e.g., `.pkit/project/<area>/`).** Rejected — introduces a structural distinction the no-shared-files invariant already enforces (an area's name is its identity; core and adopter areas can't collide). Putting adopter areas in a parallel tree would also make cross-area references awkward.

## Implications

- **Each area's README declares its variant and layout.** Authoring tooling and cross-area commands consume the declaration; they do not infer it from directory structure.
- **The CLI's component-authoring commands** (`pkit new adapter <name>`, `pkit new capability <name>`, etc.) take a target name; for area-bound scaffolding the area's declared variant determines the scaffold shape.
- **`pkit new area <name>`** is a public CLI command — adopters use it. The variant is selected at scaffold time (`--variant universal | adapter-umbrella | specialized`); the command stamps the variant's expected layout.
- **Adopter-created areas live at `.pkit/<name>/`** alongside core-shipped areas; the no-shared-files invariant prevents collision (an adopter cannot create an area with a name core already ships).
- **New variants** beyond those established in COR-005 (as refined by COR-027) require a new COR; this record does not pre-authorise variant additions.
- **Cross-area authoring** (a future skill or command that operates across areas) reads each area's README to discover layout, enabling area-agnostic operations without per-area special cases.
