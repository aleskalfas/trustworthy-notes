---
name: area-author
description: Author a new area (top-level slice of .pkit/) with the 
  variant-specific layout per COR-011. Use when adding a methodology domain core
  doesn't already ship (research, deployment, compliance, etc.).
metadata:
  wraps_command: pkit new area
gates:
  - COR-003
  - COR-005
  - COR-008
  - COR-011
reads:
  records:
    - COR-027
  paths:
    - .pkit/cli/README.md
    - .pkit/decisions/README.md
    - .pkit/lifecycle/README.md
    - .pkit/adapters/README.md
    - .pkit/decisions/core/COR-003-artifact-mechanisms.md
    - .pkit/decisions/core/COR-027-alternative-impls-as-capability-data.md
---

# Authoring an area

This skill walks through adding a new **area** at `.pkit/<name>/` (per COR-011). An area is a top-level slice of `.pkit/` with its own README, its own content layout, and a declared **variant** that determines its internal shape. Authoring an area is a methodology-level move — you're declaring a new domain the rest of the methodology (and its tooling) can dispatch on.

## Acceptance gate (run first)

Per `.pkit/decisions/README.md`'s acceptance gate: verify every record in `gates:` is `accepted` before authoring. Halt if any is `proposed` or `superseded`.

The current dependencies:

- **COR-003** — the universal `core/` + `project/` pattern; the variant inherited by `universal` areas.
- **COR-008** — git workflow conventions; the commit step.
- **COR-011** — areas as first class; declares the variant rule and the scaffold-command shape this skill wraps.
- **COR-027** — alternative implementations live as capability-internal data; the `bundle-based` area variant from COR-005 was retired here.

## Procedure

### 1. Pick the area name

Kebab-case, single noun or short noun phrase naming the domain. Examples: `research`, `deployment`, `compliance`, `risk-assessment`. The name becomes the directory name (`.pkit/<name>/`).

Refuses on collision with a core-shipped area name (the no-shared-files invariant — adopters cannot reuse `decisions`, `skills`, `cli`, `adapters`, `lifecycle`, `rules`, `migrations`).

### 2. Pick the variant

Per COR-011, the variants determine the area's internal layout:

- **`universal`** — one canonical version of each content type, with adopter extensions in parallel. Layout: `core/` + `project/`. Examples: decisions, skills, rules.
- **`adapter-umbrella`** — top-level harness translations, like `.pkit/adapters/` itself. Layout: one directory per harness, each self-contained. Rare; only one such area today.
- **`specialized`** — minimal layout (just a README); the area's content shape is documented in the README directly. Examples: cli, lifecycle.

Default is `specialized` if the area's shape doesn't fit one of the structured variants. Pick the most specific variant the area's content actually uses. (The `bundle-based` variant was retired per [COR-027](../../decisions/core/COR-027-alternative-impls-as-capability-data.md); alternative implementations now live as capability-internal data.)

### 3. Read the variant's expected layout

Read the COR record that owns the variant:

- *Universal* → `.pkit/decisions/core/COR-003-artifact-mechanisms.md` ("The universal area pattern").
- *Adapter-umbrella* → `.pkit/adapters/README.md` for layout reference.
- *Specialized* → no extra structural rule; the area's README documents its own shape.

### 4. Stamp the scaffold

Use the authoring command (per `.pkit/cli/README.md`):

```
pkit new area <name> [--variant <variant>]
```

The command:

- Creates `.pkit/<name>/`.
- Stamps `README.md` with the variant declaration in frontmatter and a placeholder body shaped to the variant.
- For `universal`: creates empty `core/` + `project/` directories.
- For `adapter-umbrella` and `specialized`: README only — sub-layout is the author's job (or follows when `pkit new adapter` etc. land).

The command refuses if the area already exists.

### 5. Fill in the README

Open `.pkit/<name>/README.md` and replace the placeholders with:

- A one-paragraph summary of what the area is for and what content it carries.
- A *Layout* section showing the area's directory shape (an ASCII tree). For structured variants the template gives you the basic shape; expand it with any area-specific sub-dirs.
- For *universal* areas: explain what `core/` content looks like and what kinds of `project/` extensions adopters typically write.
- For *adapter-umbrella* areas: explain what kinds of adapters live here and how they're added.
- For *specialized* areas: document the area's own content shape directly — there's no fixed layout to reference.

Look at the existing areas' READMEs for shape:

- `.pkit/decisions/README.md` (universal).
- `.pkit/adapters/README.md` (adapter-umbrella).
- `.pkit/cli/README.md` or `.pkit/lifecycle/README.md` (specialized).

### 6. Self-check

Walk the area against COR-011's implications:

- *Does the README's frontmatter declare the variant?*
- *Does the README's layout section match the variant's expected shape?*
- *Is the area's purpose distinguishable from existing areas? (If the content fits inside an existing area, extend that area instead of creating a new one.)*
- *Did you avoid colliding with a core-shipped area name?*

If any check fails, revise.

### 7. Commit

Per COR-008, conventional-commits format. Type is `feat`; scope is `areas` (or the area name):

```
feat(areas): add <name> area (<variant>)

<body — 1–3 paragraphs naming the domain the area covers, why it earns
its own area rather than fitting inside an existing one, and what content
it'll carry>
```

If the area is adopter-owned (not core-shipped), the commit lives in the adopter's own repo — core-side and adopter-side authoring use the same skill and command.

## Variations

- **Adding core-shipped vs. adopter-owned areas** — the command and skill are the same; the difference is who owns the area. Core-shipped areas live in the methodology source repo and propagate to every adopter; adopter-owned areas live in the adopter's repo and are never touched by `pkit sync`.
- **New variants beyond the four established in COR-011** — require a new COR record. Don't stretch an existing variant to cover a new shape; if the four variants don't fit, file a record proposing the new variant first (use `decision-author`).
- **An area that grows to need its own scaffold command** — e.g., a future `pkit new ci-pipeline` if a `ci` area earns one. That command + paired skill ship in a future PR; for now, the area's content is hand-authored under the area's documented layout.
