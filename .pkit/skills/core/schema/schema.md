---
name: schema
description: Work with YAML schemas + their JSON Schema companions — author a new schema, extend an existing one with a new entry, rename an entry with cascading reference updates, or distill schemas from an upstream methodology. Composite skill per COR-020; dispatches to per-operation sub-procedures.
metadata:
  wraps_commands:
    - pkit new schema
    - pkit schemas add
    - pkit schemas rename
    - pkit data validate
composes:
  - author.md
  - extend.md
  - rename.md
  - distill.md
gates:
  - COR-008
  - COR-017
  - COR-018
  - COR-019
  - COR-020
  - COR-023
reads:
  paths:
    - CONTRIBUTING.md
    - .pkit/schemas/README.md
    - .pkit/schemas/_defs/refs.schema.json
    - .pkit/lifecycle/README.md
    - .pkit/decisions/core/COR-018-capability-schemas.md
    - .pkit/decisions/core/COR-019-schema-reference-form.md
    - .pkit/decisions/core/COR-020-skill-folder-form.md
    - .pkit/decisions/core/COR-023-schema-binds-inline.md
  records:
    - COR-010
---

# Working with schemas

This is the **schemas-mechanism authoring** skill. It composes four operations that share the same domain (the schemas mechanism: YAML data files + their JSON Schema companions, with typed-token cross-references), the same disciplines, and the same body of records and conventions.

Pick the operation that fits the work:

| Operation | When to use it | Sub-procedure |
|---|---|---|
| **Author a new schema** | A new namespace (an engine needs to read a new kind of mechanically-consumable data — issue types, severity vocabulary, transition graph, ...). Stamps YAML + JSON Schema companion. | `author.md` |
| **Extend an existing schema** | Adding one more entry to a namespace that already exists (a new severity in `validation-severity`, a new state in `workflow`, a new issue type in `issue-types`). | `extend.md` |
| **Rename an entry** | Refining a methodology's naming after the initial draft — cascading the change across the namespace owner, value-position typed tokens, and annotation-based mapping keys. | `rename.md` |
| **Distill from upstream** | A capability's engine-data layer is being built from a pre-existing methodology body (decision corpus, standards document, domain spec). Walks through identifying engine-consumable rules, deciding schema boundaries, capturing upstream lineage. | `distill.md` |

Per COR-023, adopter-data binding lives on the schema itself via an optional top-level `binds_to:` field — no separate sub-procedure. The `author.md` and `extend.md` sub-procedures cover stamping it when a schema describes adopter-side data files.

If the user's request doesn't fit any of these, the skill doesn't apply — look elsewhere. (For purely consuming a schema at runtime, the `project_kit.schemas` Python API is the right surface, not a skill.)

## Shared framing (applies to every operation)

These hold for every sub-procedure; the per-operation files build on them.

### Acceptance gate

Verify the records in this skill's `gates:` frontmatter list are `accepted`:

- **COR-008** — git workflow conventions. For commit messages.
- **COR-017** — capability pattern. Schemas live inside capabilities.
- **COR-018** — capabilities adopt the schemas mechanism. Defines the YAML + companion pairing.
- **COR-019** — schema reference form. Settles typed tokens for cross-schema references.
- **COR-020** — skill family folder form. The convention this composite skill itself follows.
- **COR-023** — adopter data → schema binding. The `pkit_schema:` field convention + per-schema `binds_to:` fallback; supersedes COR-022.

Halt if any is `proposed` or `superseded`.

### Disciplines

The kit's authoring disciplines (per `CONTRIBUTING.md`) apply when the operation involves authorial judgment:

- **Axiom** — use only previously-defined terms (kit-defined, generic English, named external tools). No reaching for not-yet-decided framework-internal names.
- **Project-neutrality** (for core-shipped schemas) — the rule expressed must make sense in any adopting project.
- **Principles-not-inventory** — schemas encode rules; prose-only rationale lives in DECs, not schemas.

### Conventions every operation respects

- **Companion required.** Every YAML schema ships a JSON Schema companion at `<name>.schema.json` (COR-018).
- **Typed cross-schema references.** Cross-schema data references use `[<namespace>:<id>]` per COR-019. Intra-schema references stay bare. Mapping keys obey the same rule via `x-pkit-keys-from-namespace` annotation when the keys belong to another namespace.
- **Single source of truth for shared `$defs`.** Generic patterns live in `.pkit/schemas/_defs/refs.schema.json`; namespace-narrowed reference patterns live in the namespace owner's own companion (cross-file `$ref` from consumers).
- **`x-pkit-id-collection` annotation.** Namespace owners declare where their ids live via a top-level JSON Pointer annotation in the companion.

### Validation after every change

Every operation that mutates a schema re-runs the validator before reporting success:

```
pkit schemas validate
```

The validator's two passes (shape + cross-file resolver) catch the most common mistakes. The authoring commands (`pkit new schema`, `pkit schemas add`, `pkit schemas rename`) integrate this automatically; manual edits should run it explicitly.

## Routing to the sub-procedure

After confirming the gates + identifying which operation fits, read the matching sub-procedure file (one of `author.md`, `extend.md`, `rename.md`, `distill.md`) and follow its walkthrough. The shared framing above applies; the sub-procedure adds the operation-specific steps.

Each sub-procedure ends with a commit step using the conventional-commits format per COR-008.
