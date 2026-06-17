---
variant: specialized
---

# Schemas

> A **schema** is a structured data file plus a companion shape declaration. The kit defines the convention; capabilities, adopter projects, and future kit features adopt it.

The schemas mechanism gives the kit a uniform way to encode machine-consumable rules and data — state machines, enumerations, regexes, mapping tables, structured records, cross-referenced datasets — separately from the code that consumes them. Engine code stays methodology-agnostic; methodology (or domain data) becomes editable without touching code.

This area is the **mechanism reference**. It defines what schemas are, how they're shaped, how they cross-reference each other, and what tooling expects from them. Decisions that *adopt* the schemas mechanism for a particular context (capability engine data, adopter project data, future kit features) live as their own records and reference this area.

## When to reach for schemas

Use a schema when a methodology has *quantitative or structural* content that some piece of code needs to consume mechanically — enumerations of allowed values, regexes for shape checks, transition graphs, field lists, ordered taxonomies, lists of records. The schema is the single source of truth; consumers read it at runtime.

Don't use a schema for purely qualitative content — principles, rationale, when-to-apply judgement. That belongs in prose (decisions, READMEs). The schema's *value* is machine-consumability; if no code consumes it, it's just data noise.

## The schema is a pair

A schema is two files paired one-to-one:

| File | Carries | Audience |
|---|---|---|
| `<name>.yaml` | Instance data — the actual rules, enums, records | Engine code reading the data at runtime; humans editing the data |
| `<name>.schema.json` | Formal shape declaration — what the YAML must look like | JSON Schema validators (CI gates, IDEs); humans verifying the shape |

Neither half alone is the schema. The YAML carries the facts; the companion declares what counts as valid facts. Together they enable autocomplete in editors, machine validation in CI, and a stable contract for anyone authoring or consuming the data.

## YAML conventions

Every schema YAML follows the same envelope:

```yaml
schema_version: 1   # required, first key
source:             # optional — only when the schema distills from an external spec
  upstream: <project-name>
  commit: <40-char SHA>
  decisions: [<external-decision-id>, ...]
  captured_at: YYYY-MM-DD
# …domain-specific fields…
```

Rules:

- **`schema_version: <int>` is the first key**, always. The integer is the schema's own version; consuming code switches on it when the shape evolves.
- **`source:` is an optional structured block** carrying lineage to an external spec when applicable (e.g., a methodology being distilled from an upstream repo). Omit when the schema is its own source of truth.
- **Field names use `snake_case`**, matching the kit's other YAML conventions (`schema_version`, `requires_backbone`, `backend_state`).
- **Identifier values use `kebab-case`**, matching kit-wide slug conventions (`github-sub-issues`, `claude-code`).
- **Multi-line prose uses block scalars** (`|`), matching the evidence-record convention.
- **Leading comments document the schema's purpose and source** in plain prose; inline comments only where a field's purpose isn't obvious from its name.

## JSON Schema companion convention

Every YAML schema ships a companion JSON Schema declaring its formal shape:

- **File naming.** The companion is `<schema-name>.schema.json` in the same directory as the YAML. For `<root>/issue-types.yaml` the companion is `<root>/issue-types.schema.json`. Side-by-side; no sub-directory split.
- **JSON Schema draft: `2020-12`.** Every companion declares it via the top-level `$schema` keyword:
  ```json
  { "$schema": "https://json-schema.org/draft/2020-12/schema", ... }
  ```
- **Validates the envelope.** The companion's `properties` block constrains `schema_version` (typically `"const": <integer>`), declares `source` as an optional object when applicable, and validates each domain-specific field's type and value constraints.
- **Companion is required, not optional.** A YAML schema without a companion is incomplete. Consumers and tools can rely on the companion always existing.

The combination of YAML + companion JSON Schema means a schemas-aware editor (VSCode's YAML extension, JetBrains, etc.) gives autocomplete and inline validation on every YAML schema with zero per-file configuration. CI validators, language-level libraries (`jsonschema` in Python, `ajv` in JavaScript, etc.) all consume the companion the same way.

## Common shape patterns

A handful of structural shapes recur across schemas. JSON Schema expresses each cleanly; reuse the idiom rather than reinventing per schema.

### Envelope (every schema)

`schema_version` + optional `source` + domain fields. Defined once as a `$defs` fragment and referenced from every companion via `$ref` so all schemas share one envelope shape.

### Entry collections with stable ids

Many schemas hold a list of structured entries where each entry carries an `id` field used both for human reference and as a target for cross-schema references. The companion validates:

- Each entry conforms to a per-entry sub-shape.
- `id` is required.
- `id` values are unique across the collection.

The *shape* "list of objects with required `id`" is identical across schemas; the *collection name* (`transitions`, `records`, `types`, `entries`) is domain-specific. The reusable shape lives in `$defs` parameterised on the per-entry sub-shape.

### References between schemas

A field whose value names an entry defined in **another** schema — a workflow state declaring which issue types it applies to, a validation rule declaring its severity class, an aggregator pointing at entries in sibling files — uses the namespace-bearing token form:

```yaml
applies_to: ["[issue-types:task]", "[issue-types:feature]"]
severity: "[validation-severity:hard-reject]"
```

The token shape is `[<namespace>:<id>]`:

- `<namespace>` is the target schema's stem (filename without `.yaml` and without `.schema.json`).
- `<id>` is the target entry's id within that schema's collection.

Intra-schema references — a field naming an entry defined in the **same file** (e.g., a transition's `from` pointing at a state defined elsewhere in the same workflow schema) — stay bare:

```yaml
transitions:
  - id: open-to-review
    from: open       # bare — same file
    to: review
```

**Mapping keys stay bare, always** — whether they declare their own namespace or reference a foreign one. Definition sites should read cleanly:

```yaml
issues:
  epic:           # bare — not "[issue-types:epic]"
    required_sections: [...]
  feature:
    required_sections: [...]
```

When a mapping's keys reference a foreign namespace, the source namespace lives on the **JSON Schema companion**, not on each key. The parent field carries an `x-pkit-keys-from-namespace: "<namespace>"` annotation:

```json
"issues": {
  "type": "object",
  "x-pkit-keys-from-namespace": "issue-types",
  "patternProperties": {
    "^[a-z][a-z0-9-]*$": { "$ref": "#/$defs/issue_body_shape" }
  }
}
```

The resolver walks every field tagged with this annotation, iterates the mapping's keys, and confirms each key exists in the named namespace. Same cross-file validation as typed-token values; cleaner authoring at the definition site.

The split — typed tokens in values, bare ids + annotation in keys — reflects that key-position has a natural schema-side place to declare the namespace, while value-position doesn't.

(See COR-019 for the rule and rationale.)

### Validating the token shape

The JSON Schema companion validates a token's *shape* via a `pattern` constraint. The general form, defined once as a `$defs` fragment:

```json
{
  "$defs": {
    "reference_token": {
      "type": "string",
      "pattern": "^\\[[a-z][a-z0-9-]*:[a-z][a-z0-9-]*\\]$"
    }
  }
}
```

When a field accepts only one target namespace, narrow the pattern's namespace half:

```json
{
  "$defs": {
    "issue_type_ref": {
      "type": "string",
      "pattern": "^\\[issue-types:[a-z][a-z0-9-]*\\]$"
    }
  }
}
```

The narrowed form catches namespace typos at shape-validation time without waiting for the cross-file resolver. Both forms `$ref` from the field constraint via `#/$defs/<name>`.

JSON Schema does not look across files. Confirming that the token's target id **actually exists** in the named namespace is the consuming code's or a dedicated cross-file validator's responsibility. The kit ships that resolver as `pkit schemas validate`'s default pass; see below.

### Declaring where ids live: `x-pkit-id-collection`

To resolve a token like `[issue-types:task]`, the cross-file validator needs to know *where in `issue-types.yaml`* the ids live. Every schema that owns a namespace declares this via a top-level JSON Schema annotation:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "issue-types.schema.json",
  "title": "Issue type taxonomy",
  "x-pkit-id-collection": "/types",
  "type": "object",
  ...
}
```

The value is a **JSON Pointer** (RFC 6901) into the data YAML — `/types` points at the top-level `types` mapping; `/items` points at a top-level `items` list; nested pointers like `/groups/0/entries` work too.

The resolver supports two collection shapes:

- **Mapping** — keys are the ids (`types: { task: {...}, feature: {...} }` → ids are `task`, `feature`). This is the dominant shape across the kit's current schemas.
- **List of objects with `id` field** — each list item carries an `id` field whose value is the id (`items: [{ id: alpha, ... }, { id: beta, ... }]` → ids are `alpha`, `beta`). Use this shape when the collection's entries need a stable ordering or when other per-entry metadata makes the mapping form awkward.

A schema that doesn't own a namespace (an aggregator pointing at others' ids; a config-style schema with no entries of its own) omits the annotation. Tokens pointing *at* a schema without the annotation surface as resolver errors.

### What the resolver pass checks

`pkit schemas validate` runs two passes by default:

1. **Shape** — JSON Schema validates the YAML's structure.
2. **References** — two complementary walks:
   - **Value-position tokens.** For every value-position string matching `[<namespace>:<id>]`, the resolver looks up the target namespace's companion in the same directory, reads its `x-pkit-id-collection` pointer, walks to that collection in the data YAML, and confirms the id is present.
   - **Annotated key positions.** For every JSON Schema field carrying `x-pkit-keys-from-namespace: "<namespace>"`, the resolver walks to that data field, iterates its mapping keys, and confirms each key exists in the named namespace's id collection.

Resolver errors surface as hard-rejects (validator exits non-zero). Authors mid-refactor can opt out via `--shape-only`. Cross-directory resolution is not supported in v1 — sibling-file scope only.

### Aggregator schemas

A schema that collects references to entries spread across sibling files declares one referencing field per aggregated namespace. Each field's `$defs` constraint narrows to its target namespace:

```json
{
  "properties": {
    "transport": {
      "type": "array",
      "items": { "$ref": "#/$defs/transport_ref" }
    },
    "lodging": {
      "type": "array",
      "items": { "$ref": "#/$defs/lodging_ref" }
    }
  },
  "$defs": {
    "transport_ref": { "type": "string", "pattern": "^\\[transport:[a-z][a-z0-9-]*\\]$" },
    "lodging_ref":   { "type": "string", "pattern": "^\\[lodging:[a-z][a-z0-9-]*\\]$" }
  }
}
```

The aggregator schema carries no entries of its own — it points at them. This lets a root data file act as a single point of contact for a domain (a trip spec aggregating transport / lodging / activities; a project spec aggregating phases / deliverables / risks) without becoming unscannable. Detail moves to sibling files; the root references it.

### Reusable fragments via `$defs`

When the same sub-shape appears in multiple schemas — the envelope, entry-id constraint, token pattern, semver-shaped strings — define it once and `$ref` from each consumer. Drift reduces; one fix updates every dependent schema.

The kit settles two ownership rules for where the canonical definition lives:

- **Kit-wide patterns** (recur across capabilities — the generic `reference_token`, the structured `source` envelope) live in `.pkit/schemas/_defs/refs.schema.json`. Consumers `$ref` `refs.schema.json#/$defs/<name>`.

- **Namespace-narrowed patterns** (a typed token narrowed to one namespace — e.g., `issue_type_ref` for the issue-types namespace) live in the **namespace owner's own companion** as a published `$defs` entry. Consumers cross-file `$ref` the owner: `issue-types.schema.json#/$defs/issue_type_ref`. The owner is the source of truth for its own narrowed reference pattern.

Both forms use JSON Schema's standard cross-file `$ref`. The kit's `pkit schemas validate` builds a Registry covering every companion in the same directory plus the kit-wide `_defs/` library, so all relative `$id`-keyed `$ref`s resolve.

## Adopter data → schema binding (COR-023)

A schema is consumed two ways: by the engine of the capability that ships it (reading its own canonical YAML at runtime) and by *adopter-side data files* that follow the schema (e.g., `trips/<slug>/trip.yaml` follows `trip-planning:trip`). The first form's binding is implicit — the file lives at `<capability>/schemas/<schema>.yaml` and the engine knows what to read. The second form needs a declarative binding so the resolver, the IDE, and `pkit data validate` can answer "which schema applies to this file?"

Per COR-023 (superseding COR-022), the binding mechanism is two-layered:

### 1. The `pkit_schema:` field (recommended, authoritative)

An adopter data YAML carries a top-level `pkit_schema:` field whose value is the bare two-part form `<capability>:<schema-name>`:

```yaml
# yaml-language-server: $schema=.pkit/capabilities/trip-planning/schemas/trip.schema.json
pkit_schema: trip-planning:trip
schema_version: 1
slug: japan-2026
title: Japan (Tokyo)
# …
```

- The field's value is the bare reference (no brackets). Brackets in COR-019 delimit references *embedded in prose or other values* — needed when the surrounding context is text. In field position where the entire value is the reference, the brackets add noise.
- The field is optional but recommended. When present, it is authoritative — the resolver uses the field directly without consulting capability fallbacks.
- The YAML Language Server directive comment (`# yaml-language-server: $schema=...`) is the IDE-side counterpart: editors with no `pkit` integration still light up with autocomplete + inline validation. Two sources of truth, each serving a different tool surface; drift is bounded because the authoring step writes both atomically.

### 2. Per-schema `binds_to:` fallback

A capability schema declares path-pattern fallbacks via a top-level `binds_to:` field on the schema's YAML — a list of repo-relative globs the schema validates:

```yaml
# .pkit/capabilities/trip-planning/schemas/trip.yaml
schema_version: 1
binds_to:
  - "trips/*/trip.yaml"
# … rest is the schema's namespace content
```

- The field lives **on the schema itself**, not in a separate bindings registry. One source of truth per schema; bindings die with the schema when it's removed; no cross-file registry to keep in sync.
- The pattern is a glob (Python's `fnmatch` semantics) matched against the adopter file's repo-relative path. One segment per `*`; no `**`.
- The field is optional. Most schemas in the kit are namespace owners or capability-internal — `binds_to:` matters only for schemas that describe adopter-data files.
- When an adopter file omits `pkit_schema:`, the resolver walks every installed capability's `schemas/*.yaml`, collects `binds_to:` patterns, and uses the first matching glob. Multiple matches across capabilities surface as ambiguous (the adopter resolves it by adding the explicit field).

### Resolution order

For a given adopter data file:

1. **Field-first.** If the file carries `pkit_schema: <capability>:<schema>`, resolve it. The field is authoritative.
2. **Capability fallback.** Otherwise, walk installed capabilities (in backbone-manifest order); for each capability's `schemas/*.yaml`, match the file's repo-relative path against each schema's `binds_to:` glob entries.
3. **Refuse.** No field, no matching binding → the resolver reports a structured "no schema binding" error pointing the adopter at the two ways to declare one.

### Schema-version cross-check

The data file's `schema_version` field declares which schema version the data was authored against. The schema (the capability's `<schema>.yaml`) declares its current `schema_version`. When the two disagree, validation refuses with a structured migration hint naming both versions and pointing at the capability's migration tier. Auto-migration is out of scope in v1 — adopter data is often hand-edited, and silent transformation is the wrong default.

### `pkit data validate <path>`

The CLI surface for the binding mechanism. Resolves the binding for one adopter data file (or every YAML in a directory, recursively), runs JSON Schema validation against the resolved schema, and reports findings. Exits non-zero on any unresolved binding or validation failure.

This command is **distinct from `pkit schemas validate`** — the latter validates capability-side schema pairs (the spec); the former validates adopter-side data files against those schemas. Two artefacts, two surfaces.

### Cross-file references in adopter data: `x-pkit-reference-namespace` (COR-029)

Adopter data files reference each other: a `[<namespace>:<id>]` token in one bound file names an entry defined in another bound file (e.g. a trip's aggregator file citing `[transport:asiana-fux5mv]`, defined in that trip's transport file). `pkit data validate` resolves these in a second pass after shape validation (default-on; `--shape-only` skips it).

Two things make adopter-data references different from the capability-side resolution `pkit schemas validate` runs:

- **Resolution is *through the binding*, to the bound instance.** A capability schema that *describes* adopter data keeps its own id collection empty by design — the entries live in the adopter tree. So a reference does not resolve into the namespace schema's own (empty) collection; it resolves into the files *bound* to that namespace, read via the schema companion's `x-pkit-id-collection` pointer.
- **References are *position-gated*.** Adopter data carries bracketed tokens that are not references (prose, free-text). The resolver inspects **only** fields the citing schema's companion marks with `x-pkit-reference-namespace: "<namespace>"` — the value-position counterpart to the key-position `x-pkit-keys-from-namespace`. The annotation declares "this position holds references in this namespace"; the namespace is still carried by the token itself. Mark a scalar field, an array's `items`, or a shared `$defs` definition that other fields `$ref`:

  ```json
  "$defs": {
    "transport_ref": {
      "type": "string",
      "x-pkit-reference-namespace": "transport"
    }
  }
  ```

**Scope is the validated subtree.** A namespace's id pool is the union of every in-scope file bound to it — where "in scope" means under the directory `pkit data validate` was pointed at. Isolation is by *what you validate*: validate one instance's subtree and only its data is in scope; validate a parent and a shared file under it serves every instance below. Resolution is not positional (moving a file within the scope changes nothing) and there is no shadowing (the pool is a union).

**Failure surface:** a dangling id (the namespace has a pool in scope, the id is absent) is an **error**; a **duplicate** id across in-scope files of one namespace is an **error** (the pool is ambiguous); a reference whose namespace has **no bound file anywhere in scope** is a **warning** — incremental authoring routinely references a not-yet-created sibling, so this does not fail the run.

Deferred to successor decisions (each pending a real consumer, per COR-029): cross-scope shared reference roots (a shared catalog serving instances without unioning them into one scope) and foreign-keyed mapping keys.

### Authoring

The `schema` skill (composite per COR-020) covers adopter-data schemas through its `author.md` and `extend.md` sub-procedures. Stamping a schema that describes adopter-data files includes adding the `binds_to:` field to that schema's YAML alongside the namespace content; adopter files themselves carry `pkit_schema:` + the IDE directive as recommended.

## Tooling expectations

A schema's value depends on tooling actually consuming the companion. Three tooling layers a schemas-using project can expect:

1. **IDE integration (zero configuration).** JSON-Schema-aware editors detect `<name>.schema.json` next to `<name>.yaml` and apply validation + autocomplete during authoring. Works out of the box; no project-specific setup.

2. **Language-level validators (consumer-driven).** Code consuming a schema may load its companion at runtime and validate the YAML before acting on it (`jsonschema` in Python, `ajv` in JavaScript, etc.). Whether a given consumer does this is a per-consumer choice — runtime validation adds latency but catches malformed data with clearer errors than a downstream crash.

3. **Cross-file resolution (kit-level validator).** `pkit schemas validate` ships the resolver: it walks every typed token across every YAML, looks up each namespace's companion in the same directory, follows the companion's `x-pkit-id-collection` JSON Pointer to the id-bearing collection in the data YAML, and confirms each token's id exists. Sibling-file scope (cross-directory not supported in v1). Unresolved references are hard-rejects (validator exits non-zero); `--shape-only` skips this pass for mid-refactor authoring.

4. **Adopter-data validation (`pkit data validate <path>`).** The consumer surface for the COR-023 binding mechanism. Resolves each data file's binding (field-first; per-schema `binds_to:` as fallback), refuses on schema-version mismatch, runs JSON Schema validation against the resolved schema, and then — unless `--shape-only` — resolves cross-file typed references through the binding, scoped to the validated subtree (per COR-029). See "Adopter data → schema binding" above.

## Layout

```
.pkit/schemas/
├── README.md                  # this file — mechanism overview, conventions, patterns
└── _defs/                     # kit-wide shared $defs library (cross-file $ref target)
    └── refs.schema.json       # canonical reference_token + source patterns
```

The `_defs/` directory holds JSON Schema fragments that every capability (and adopter project) `$ref` into. New shared patterns land as additional `$defs` in `refs.schema.json`, or as additional sibling files when a coherent group of patterns earns its own file.

## What's *not* in this area

This area defines the schemas mechanism. It does **not** decide:

- *Which contexts adopt the schemas mechanism.* That's per-adopter decisions (a COR for capabilities, a PRJ for an adopter project, etc.).
- *Overlay or customisation semantics for adopters.* When schemas are shipped by one party and customised by another, the override mechanism is a separate concern handled in a future record.

## Adopting the schemas mechanism

A context wanting to use schemas — a capability, an adopter project, a future kit feature — declares its adoption in its own record (COR for kit-shipped, PRJ for adopter-shipped). The adoption record states *why this context uses schemas* and what data it'll encode. Mechanical details (YAML format, companion convention, patterns) reference this area instead of restating them.
