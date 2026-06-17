---
name: adapter-author
description: Author a new adapter (harness translation layer at .pkit/adapters/<name>/) with proper layout, package metadata, and the COR-005 contract. Use when supporting a new AI harness (Claude Code, Codex, Cursor, etc.).
metadata:
  wraps_command: pkit new adapter
gates:
  - COR-005
  - COR-006
  - COR-008
  - COR-010
reads:
  records:
    - COR-002
  paths:
    - .pkit/cli/README.md
    - .pkit/lifecycle/README.md
    - .pkit/adapters/README.md
    - .pkit/decisions/README.md
    - .pkit/decisions/core/COR-005-bundle-pattern.md
    - .pkit/adapters/claude-code/README.md
---

# Authoring an adapter

This skill walks through adding a new **adapter** at `.pkit/adapters/<name>/` (per COR-005). An adapter is a harness translation layer — it ports core-shipped content (skills, agents, settings, hooks) into whatever the target harness (Claude Code, Codex, Cursor, …) expects. Adapters sit at the methodology's top level, not inside an area, because they cut across multiple areas' content.

## Acceptance gate (run first)

Per `.pkit/decisions/README.md`'s acceptance gate: verify every record in `gates:` is `accepted` before authoring. Halt if any is `proposed` or `superseded`.

The current dependencies:

- **COR-005** — the bundle/adapter pattern; fixes the directory shape, universal elements, and install model.
- **COR-006** — artifact roles; harness-agnostic vs. harness-flavoured content split.
- **COR-008** — git workflow conventions; the commit step.
- **COR-010** — resource lifecycle; fixes the `package.yaml` schema, `requires_backbone` semantics, and migration directory layout.

## Procedure

### 1. Pick the adapter name

Use the harness's canonical kebab-case name: `claude-code`, `codex`, `cursor`, etc. The name becomes the directory name and the value of the `component.name` field in `package.yaml`.

### 2. Read the contract

Read `.pkit/decisions/core/COR-005-bundle-pattern.md` ("Adapter structure" and "Universal elements"). Every adapter must ship:

- `package.yaml` — component metadata per COR-010 (`kind: adapter`, `name`, `version`, `requires_backbone`).
- `README.md` — what the adapter handles, what content it ships, how to deploy it.

Beyond these, an adapter's content is heterogeneous — settings files in the harness's expected format, deploy scripts that produce symlinks, runtime artifacts. Read `.pkit/adapters/claude-code/` as a reference shape; your harness may need a different mix.

### 3. Stamp the scaffold

Use the authoring command (per `.pkit/cli/README.md`):

```
pkit new adapter <name>
```

The command:

- Creates `.pkit/adapters/<name>/`.
- Stamps `package.yaml` with `kind: adapter`, `version: 0.1.0`, and `requires_backbone` pinned to a range matching the project's current backbone.
- Stamps `README.md` with a placeholder body.
- Creates an empty `migrations/` directory.
- Registers the adapter in the backbone manifest's `components` registry (so `pkit status` sees it immediately).

The command refuses if an adapter with that name already exists or if the slug isn't kebab-case.

### 4. Fill in the README

Open `.pkit/adapters/<name>/README.md` and replace the placeholders with:

- A one-paragraph summary of which harness the adapter translates for and what core content it carries across.
- A "What this adapter ships" section listing the artifacts the adapter provides — settings file(s), deploy scripts, runtime artifacts.
- A "How adopters use this adapter" section walking through deployment: what happens at `pkit init` (or sync), what the adopter does once, what runs automatically.

Look at `.pkit/adapters/claude-code/README.md` as a reference.

### 5. Author the harness-specific content

Add the artifacts the harness needs. Common shapes:

- **Settings file(s)** — typically a `core/` + `project/` split inside a `settings/` directory (universal area pattern applied internally), with a `merge-settings.sh` primitive that combines them into the harness's expected fixed-path file (per COR-002).
- **Deploy script(s)** — typically `deploy-skills.sh` (and later `deploy-agents.sh`) that symlinks `.pkit/skills/<…>/` into the harness's expected location.
- **Hook configuration** — if the harness supports hooks.

Skills, agents, and decisions live in their own harness-agnostic areas (per COR-006); the adapter only translates them at deploy time.

### 6. Self-check

Walk the adapter against the COR-005 universal-element checklist:

- *Does the adapter have a `README.md` and a `package.yaml`?*
- *Does the `README.md` cover what the adapter handles, what's shipped, and how to deploy it?*
- *Are the harness-specific deploy steps idempotent? Re-running them should be a no-op.*
- *Does the adapter respect COR-006's harness-agnostic discipline — core content lives at canonical paths, and the adapter only translates at deploy time?*

If any check fails, revise.

### 7. Commit

Per COR-008, conventional-commits format. Type is `feat`; scope is `adapters` (or the adapter name if more specific):

```
feat(adapters): add <name> adapter

<body — 1–3 paragraphs naming the harness, what content the adapter
translates for, and any harness-specific deployment notes>
```

The adapter lands at `version: 0.1.0`. Subsequent bumps follow the same surface-change rule the methodology uses for its own backbone.

## Variations

- **Adopters authoring their own adapter** — same procedure, same command. An adopter using an in-house AI harness creates the adapter under their own copy of the methodology and contributes it back upstream if generally useful.
- **Adding an adapter for a harness already shipped** — refuses by design. To extend an existing adapter, edit its files (core-side if you're a methodology maintainer; via the methodology's extension mechanisms otherwise).
