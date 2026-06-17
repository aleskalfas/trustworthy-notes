---
name: capability-author
description: Author a new capability — an opt-in installable methodology discipline at .pkit/capabilities/<name>/ — with proper layout, package metadata, and the COR-017 contract. Use when packaging a coherent body of decisions, skills, agents, and scripts that some adopters need and others don't.
metadata:
  wraps_command: pkit new capability
gates:
  - COR-005
  - COR-006
  - COR-007
  - COR-008
  - COR-017
reads:
  records:
    - COR-011
    - PRJ-002
  paths:
    - .pkit/cli/README.md
    - .pkit/decisions/README.md
    - .pkit/decisions/core/COR-017-capability-pattern.md
    - .pkit/decisions/core/COR-005-bundle-pattern.md
    - .pkit/decisions/core/COR-007-pattern-extraction.md
    - CONTRIBUTING.md
---

# Authoring a capability

This skill walks through adding a new **capability** at `.pkit/capabilities/<name>/` (per COR-017). A capability is an opt-in installable discipline — a coherent bundle of decisions, skills, agents, scripts, and schemas that some adopters install per project and others don't. Capabilities slot in alongside areas, bundles, and adapters as a sibling concept, not a fourth area variant.

## When this skill applies

Reach for a capability when:

- The discipline is **useful but not universal** — most adopters won't need it, but those who do need the whole bundle (decisions + skills + maybe an agent + maybe a script).
- A clean opt-in/opt-out boundary exists. If you can describe "install this and it appears, uninstall and it disappears, no shared files" you have a capability.
- The pattern has earned its keep per COR-007 — at minimum, a concrete adopter motivated it; ideally, two or more adopters or use cases would benefit. Inventing capabilities speculatively is the failure mode this skill is designed to prevent.

Do **not** use this skill for:

- Universal disciplines every adopter must follow — those belong in `core/` (areas) and ship via propagation, not opt-in install.
- Single-adopter customisation — that belongs in the adopter's `project/` namespaces (per COR-011's universal variant).
- Harness translations — those are adapters (per COR-005).
- Alternative implementations of the same area's contract — those are bundles (per COR-005).

## Acceptance gate (run first)

Per `.pkit/decisions/README.md`'s acceptance gate: verify every record in `gates:` is `accepted` before authoring. Halt if any is `proposed` or `superseded`.

The current dependencies:

- **COR-005** — the bundle/adapter pattern; capabilities share their package-yaml shape and skill/command-pairing discipline.
- **COR-006** — artifact roles; what belongs in a decision vs a skill vs an agent vs a script.
- **COR-007** — pattern extraction; capabilities should formalise a recurring discipline, not anticipate one.
- **COR-008** — git workflow conventions; the commit step.
- **COR-017** — the capability pattern; the canonical record fixing layout, lifecycle, citation form, and install/sync/uninstall semantics.

## Procedure

### 1. Pick the capability name

Use a kebab-case noun that names the *discipline*, not the implementation. Examples:

- `evidence` — citation discipline (not `citations` or `evidence-yaml`)
- `product-management` — product-management discipline (not `pm-agent` or `scrum`)
- `storyboard-authoring` — storyboard discipline (not `storyboards`, which would conflict with the universal area)

The name becomes the directory name, the value of `component.name` in `package.yaml`, and the prefix in citations: `[<capability-name>:DEC-NNN-<slug>]`.

### 2. Read the contract

Read `.pkit/decisions/core/COR-017-capability-pattern.md`. Every capability ships:

- `package.yaml` — component metadata (`kind: capability`, `name`, `version`, `requires_backbone`).
- `README.md` — adopter-facing intro: the discipline, the commands, the conventions.
- Some non-empty subset of `decisions/`, `skills/`, `agents/`, `scripts/`, `schemas/`. A capability with no decisions and no skills is suspicious — at minimum, you'd expect one decision establishing the discipline's invariant plus one skill or script operationalising it.

### 3. Stamp the scaffold

Use the authoring command (per `.pkit/cli/README.md`):

```
pkit new capability <name>
```

The command:

- Creates `.pkit/capabilities/<name>/`.
- Stamps `package.yaml` with `kind: capability`, `version: 0.1.0`, and `requires_backbone` pinned to a range matching the project's current backbone.
- Stamps `README.md` with placeholder prose explaining the discipline, install command, and citation form.
- Creates empty `decisions/`, `skills/`, `agents/`, `scripts/`, and `schemas/` subdirectories with `.gitkeep`.

Unlike bundles and adapters, the capability is **not** registered in the backbone manifest by the scaffolding step. Capabilities are kit-shipped from the source-of-edit's perspective; adopters register them per-project via `pkit capabilities install <name>`.

The command refuses if a capability with that name already exists or if the slug isn't kebab-case.

### 4. Fill in the README

Open `.pkit/capabilities/<name>/README.md` and replace the placeholders with:

- **One-paragraph summary** — what discipline the capability formalises, when an adopter would install it.
- **What this capability ships** — the kit-shipped artifacts an adopter receives.
- **Adopter setup** — the install command and any per-project configuration the adopter must fill in.
- **Citing this capability's decisions** — keep the stamped paragraph; it documents the `[<capability-name>:DEC-NNN-<slug>]` citation form.
- **Dependencies** — what the adopter needs in place: external tooling, other capabilities, accounts.

### 5. Author the decisions

Capability decisions live in `decisions/` with filenames `DEC-NNN-<slug>.md`. The numbering is scoped to *this* capability — every capability has its own `DEC-001`. Author by hand for now: there is no `pkit new decision` extension for capability namespaces yet (per COR-007, that pattern lands when capability authoring recurs enough to justify the tooling).

Each decision has the same shape as a PRJ decision (axiom + principles-not-inventory disciplines apply; project-neutrality does not — capabilities are explicitly discipline-specific):

```markdown
---
id: DEC-001
title: <imperative short title>
status: accepted
date: YYYY-MM-DD
author: <name>
---

## Context

## Decision

## Rationale

## Implications
```

Cite other capability decisions in the same capability using the form `[<this-capability>:DEC-NNN-<slug>]`. Cite COR / PRJ records as `COR-NNN` / `PRJ-NNN` (the kit's existing forms).

### 6. Author the skills, agents, scripts, and schemas

Skills, agents, scripts, and schemas in a capability follow the same shapes as their area-shipped counterparts (per COR-006). Two notes specific to capabilities:

- Skills and agents may cite *this capability's* decisions in body prose via the `[<name>:DEC-NNN-slug]` form. The validator (`pkit refs validate`) walks capability subtrees and resolves these citations.
- Scripts can be Python with PEP 723 inline metadata (so adopters can run them via `uv run` without a host project) or shell. If a script needs Python dependencies, declare them inline so the script is self-installing.

### 7. Self-check

Walk the capability against COR-017's universal-element checklist:

- *Is the capability genuinely opt-in?* If every adopter would install it, it's not a capability — it belongs in core areas.
- *Does the capability stand on its own?* Could an adopter install it and use it without inheriting hidden expectations from the rest of the kit?
- *Are the decisions principle-shaped?* No inventory dressed up as decisions. The COR-017 disciplines apply to capability decisions too.
- *Is there a citation form that an author can use?* `[<name>:DEC-NNN-<slug>]` should round-trip through `pkit refs validate`.
- *Is the README adopter-facing?* It explains the discipline, not the implementation; an adopter reading it cold should understand what they're opting into.

If any check fails, revise.

### 8. Smoke install + uninstall

Before committing, validate the capability mechanically:

```
pkit refs validate                              # capability subtree is parsed cleanly
```

Then in a scratch adopter:

```
cd /tmp/scratch-adopter && pkit init
pkit capabilities install <name>               # subtree copies in, manifest registers
pkit status                                     # capability appears under installed
pkit capabilities uninstall <name>             # tree removed, manifest unregisters
```

Catch any layout or schema mistakes here, not at adopter time.

### 9. Commit

Per COR-008, conventional-commits format. Type is `feat`; scope is `capabilities` or the capability name:

```
feat(capabilities): add <name> capability

<body — 1–3 paragraphs naming the discipline this capability
formalises, what it ships, and what motivated bundling it as an opt-in
capability rather than core content>
```

The capability lands at `version: 0.1.0`. Subsequent bumps follow the same surface-change rule the methodology uses for its own backbone (per PRJ-002 in project-kit's own repo; adopter-shipped capabilities use whatever bump policy that project adopts).

## Variations

- **Adding decisions/skills/agents to an existing capability** — edit the capability's subtree directly. Refusing to use the scaffolding command for follow-up work is fine; the scaffold is just for the first instance.
- **Adopters authoring their own capability** — same procedure, same command. An adopter who develops a discipline worth sharing creates it under their own copy of the methodology and contributes upstream if generally useful.
- **Bumping a capability's version** — bump `version:` in `package.yaml` whenever the capability lands a surface change visible to adopters: new decision, new skill, new agent, new script, removed file, schema change. Adopters pick up the new version on the next `pkit sync` or `pkit capabilities upgrade <name>`.
- **Swappable implementations of the same capability** — defer until two implementations exist. COR-017's variants note (Implications section) captures this: if the same discipline ships in multiple flavours (e.g., evidence-yaml-python vs evidence-sqlite), pattern-extract a sub-structure when the second flavour lands per COR-007.
