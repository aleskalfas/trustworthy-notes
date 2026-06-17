---
name: migration-author
description: Author a new migration script (backbone, bundle, or adapter tier) per the COR-010 contract. Use when a version bump needs to bridge installed projects' state to the new version.
metadata:
  wraps_command: pkit new migration
gates:
  - COR-005
  - COR-008
  - COR-010
reads:
  records:
    - PRJ-002
  paths:
    - .pkit/cli/README.md
    - .pkit/lifecycle/README.md
    - .pkit/decisions/README.md
    - .pkit/VERSION
---

# Authoring a migration

This skill walks through adding a new **migration script** per COR-010's lifecycle contract. A migration bridges installed projects' state across a version transition — adding labels, renaming files, restructuring manifests, etc. Migrations are versioned (tied to a `<major>.<minor>.0/` directory), idempotent (safe to re-run), and scoped to one tier (backbone, bundle, or adapter).

## Acceptance gate (run first)

Per `.pkit/decisions/README.md`'s acceptance gate: verify every record in `gates:` is `accepted` before authoring. Halt if any is `proposed` or `superseded`.

The current dependencies:

- **COR-005** — the bundle/adapter pattern; identifies the tier scopes that own migration trees.
- **COR-008** — git workflow conventions; the commit step.
- **COR-010** — resource lifecycle; fixes the migration framework (tiers, scopes, directory layout, idempotence contract).

## Procedure

### 1. Pick the tier

The migration lives in one of three trees, picked by the resource it affects:

- **`backbone`** — the migration affects backbone-level state (decision records, rules, the CLI surface, backbone-wide directory shapes). Lives under `.pkit/migrations/backbone/<X.Y.0>/`.
- **`bundle`** — the migration affects one specific bundle's state (labels, templates, primitives for that bundle). Lives under `.pkit/<area>/bundles/<name>/migrations/<X.Y.0>/`.
- **`adapter`** — the migration affects one specific adapter's state (settings, deployed paths, hooks for that harness). Lives under `.pkit/adapters/<name>/migrations/<X.Y.0>/`.

Pick the most specific tier that covers the change. A bundle's internal change → bundle tier (not backbone), even if the change is conceptually "across the methodology's bundles".

### 2. Pick the scope

Each tier has three scopes that determine the script's role and execution order within a version's directory (per COR-010 / `.pkit/lifecycle/README.md`'s "Three scopes per tier"):

- **`manifest-schema`** — bridges a manifest format change. Runs **first** in any upgrade flow that needs it, before any structural or resource-scoped migration of the same target version.
- **`structural`** — affects the tier's directory shape (a backbone-wide rename; a bundle's internal restructure within the bundle). Runs **before** resource-scoped migrations of the same target version.
- **`resource`** — affects one specific resource (a label, a setting key, a template). The most common scope.

### 3. Pick the target version

The target version is the `<major>.<minor>.0` the migration applies *up to*. Per COR-010, patches have no migrations — the patch segment is always `.0`, and one minor-version directory covers all patches within that line.

- For a backbone migration: read `.pkit/VERSION` for the current backbone version (after the bump that the migration is for).
- For a component migration: read the component's `package.yaml`'s `version` field (after the bump).

### 4. Pick the slug

Kebab-case, 2–4 words, describing what the migration does. Examples: `add-status-labels`, `rename-chore-to-maintenance`, `manifest-schema-v2`, `decisions-frontmatter-author`.

### 5. Stamp the scaffold

Use the authoring command (per `.pkit/cli/README.md`):

```
pkit new migration --tier <tier> [--component <name>] [--version <X.Y.0>] --name <slug> [--scope <scope>]
```

- `--tier` is required.
- `--component` is required when `--tier` is `bundle` or `adapter`.
- `--version` defaults to the tier's current recorded version (read from `.pkit/VERSION` for backbone; from `package.yaml` for components). Pass explicitly to override.
- `--name` is the slug, required.
- `--scope` defaults to `resource`. Set to `manifest-schema` or `structural` per step 2.

The command stamps `<NNN>-<slug>.sh` in the right `<X.Y.0>/` directory, where `NNN` is the next zero-padded index in that directory. The script is made executable and includes the COR-010 contract boilerplate (`set -euo pipefail`, `ROOT` env consumption, idempotence pattern).

### 6. Implement the migration

Open the stamped script and replace the TODO body with the actual change. Two requirements (per COR-010 / lifecycle spec's "Script contract"):

- **Idempotent** — detect already-applied state and exit cleanly. The stamped boilerplate shows the pattern:

  ```bash
  if <state is already correct>; then
      echo "  exists  <description>"
      exit 0
  fi
  # ... apply ...
  ```

- **Updates the affected resource.** For derivable resources (files in the core content directory, labels on a tracker), the migration mutates the resource directly — no manifest update. For non-derivable resources (opaque backend IDs in `backend_state`), the migration updates the manifest entry.

Use only the dependencies the project ships with — `bash`, standard UNIX tools, `git`, `gh`, `yq` if YAML manipulation is needed.

### 7. Self-check

Walk the script against the contract:

- *Does it `set -euo pipefail`?*
- *Does it consume `ROOT` from the environment, not hardcode paths?*
- *Is it idempotent — would re-running on already-migrated state be a no-op?*
- *Does it update the affected resource (or the relevant manifest entry, for non-derivable state)?*
- *Did you place it in the right tier × version × scope ordering?*

Test the script locally on a fresh checkout if practical.

### 8. Commit

Per COR-008, conventional-commits format. Type is typically `feat` (a new migration is new behaviour at the target version); scope is the tier (or component name for bundle/adapter migrations):

```
feat(<scope>): add migration <X.Y.0>/<slug>

<body — 1–3 paragraphs explaining what state the migration bridges, what
the new version expects, and any caveats for adopters>
```

The migration is part of the version-bump commit's surface change (per PRJ-002 for backbone, or the component's analogue bump rule).

## Variations

- **A migration that fully reconciles is unnecessary** — if the upgrade flow's reconciliation step regenerates the resource from the new spec, no migration is needed. Migrations only exist for state the reconciliation cannot derive (renames, removals, opaque backend IDs).
- **Multiple migrations at one version** — the next-index numbering supports this. Place manifest-schema migrations first (lowest NNN), then structural, then resource-scoped. The runtime walks them in that order.
