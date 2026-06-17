
# Authoring a new schema

This skill walks through adding a new schema under `.pkit/capabilities/<capability>/schemas/`. Each schema is a YAML data file + JSON Schema companion, paired one-to-one per COR-018. Two shapes are supported:

- **Namespace-owning schema** (the dominant form). The file declares a top-level id collection (`x-pkit-id-collection`) and consumers reference its entries as typed tokens per COR-019.
- **Document schema** (one resource per file). The file IS the resource — no top-level collection, no namespace. Pick when the capability's spec is "one X per file" rather than "a registry of Xs."

For adding **one more entry** to an existing namespace, use `schema-extend` instead.

## Acceptance gate (run first)

Verify each record in `gates:` is `accepted`:

- **COR-008** — git workflow conventions. Used for the commit step.
- **COR-017** — capability pattern. Used so the new schema lands inside an existing capability per the kit's layout.
- **COR-018** — capabilities adopt the schemas mechanism. Used for the YAML + companion pairing convention.
- **COR-019** — schema reference form. Used when the new schema's entries carry cross-schema references (typed tokens) or when it'll be referenced from elsewhere.

Halt if any is `proposed` or `superseded`.

## Procedure

### 1. Confirm the target

A schema is stamped into one of two homes:

- **A capability** — `.pkit/capabilities/<capability>/schemas/`. The dominant case. If no fitting capability exists, the user is asking for new capability work — switch to `capability-author` first.
- **The core schemas area** — `.pkit/schemas/`, for schemas a core subsystem owns (not tied to any one capability). Pass the reserved target `core` to the stamp command.

Useful check:
```
pkit capabilities list
```

### 2. Pick the namespace name

Kebab-case, starts with a lowercase letter. The name should be:

- *Domain-precise.* `issue-types`, `validation-severity`, `time-containers` — each names what the namespace encodes, not its location.
- *Singular or domain-natural.* Some namespaces are plural by convention (`issue-types` for issue types collectively); others use the natural domain term (`workflow` for the workflow definition).
- *Distinguishable.* Doesn't collide with existing namespace names across all installed capabilities (run `pkit schemas list` to confirm).

The name becomes the filename stem AND the namespace identifier consumers reference: `[<name>:<id>]` from elsewhere.

### 3. Choose the collection form

Three shapes the schemas mechanism supports:

- **Mapping form** (the dominant choice for namespace owners). Keys ARE the ids; entry data is the mapping value. Example:
  ```yaml
  types:
    epic: { role: ..., can_contain: [...] }
    feature: { role: ..., can_contain: [...] }
  ```
  Pick when entries have no inherent order, when fields are heterogeneous, and when most consumers will look up by id.

- **List-of-objects form**. Each list item has `id:` as the first field; entry data is the rest of the object. Example:
  ```yaml
  items:
    - id: alpha
      label: Alpha
    - id: beta
      label: Beta
  ```
  Pick when entries need stable ordering, when iteration order matters for consumers, or when per-entry metadata makes the mapping form awkward (rare).

- **Document form** (one resource per file — no collection). The YAML carries the resource's top-level fields directly; no `x-pkit-id-collection`. Example:
  ```yaml
  schema_version: 1
  slug: japan-2026
  title: Japan, autumn 2026
  status: planning
  ```
  Pick when the capability's spec is "one X per file" (one trip, one report, one campaign) — the file IS the resource, not a registry of resources. Stamps via `--no-namespace`. Document schemas are not referenceable by typed token (`[<name>:<id>]`); references make sense only against namespace-owning schemas.

The default is `mapping` (namespace owner). Override with `--collection-form list`, or switch entirely to the document path with `--no-namespace`.

### 4. Choose the collection name

*(Skip this step if you're stamping a document schema — there's no collection to name.)*

The top-level YAML key that holds the id collection. Conventions across the kit:

- Schemas tend to use **domain-natural plural names** for their collections: `issue-types.yaml` → `types:`, `workflow.yaml` → `states:`, `validation-severity.yaml` → `severities:`, `time-containers.yaml` → `containers:`.
- The collection name is *content-relative*, not filename-mechanical: `issue-types` (the namespace) → `types` (the collection key).
- When no obvious domain-natural plural exists, fall back to `entries`.

Pass via `--collection-name <name>` (defaults to `entries`).

### 5. Decide whether the namespace distills from upstream

If the new schema encodes rules from an external spec (a methodology, a standards document, etc.), the YAML envelope's `source:` block captures the lineage: upstream project name, the exact commit SHA, the upstream decision identifiers being distilled, the date captured. The stamped template leaves this commented out. Uncomment + fill in when applicable.

If the schema is its own source of truth (the kit defines the rules), leave the `source:` block commented out.

### 6. Stamp the scaffold

Use the authoring command:

```
pkit new schema <capability> <name> [--collection-form mapping|list] [--collection-name <name>] [--no-namespace]
pkit new schema core <name> [...]      # the reserved `core` target stamps into .pkit/schemas/
```

For a **namespace owner**, the command:

- Creates `<name>.yaml` with the envelope: `schema_version: 1`, the optional `source` block (commented), the collection (`{}` for mapping, `[]` for list) with leading prose-placeholder comments.
- Creates `<name>.schema.json` with the envelope: `$schema`, `$id`, title + description placeholders, `x-pkit-id-collection: /<collection-name>`, the collection shape (`patternProperties` for mapping or `items: $ref` for list), a `$defs.entry` placeholder with `additionalProperties: false` and empty `properties`.

For a **document schema** (`--no-namespace`), the command:

- Creates `<name>.yaml` with the envelope: `schema_version: 1`, the optional `source` block (commented), and a leading comment block explaining "the file IS the resource — fill in the top-level fields here." No collection wrapper.
- Creates `<name>.schema.json` with the envelope: `$schema`, `$id`, title + description placeholders, top-level `type: object`, `additionalProperties: false`, and a flat `properties: {}` placeholder (author declares the document's fields here). No `x-pkit-id-collection`; no `$defs.entry`.

Both paths re-validate the stamp via `pkit schemas validate`. On failure, both files are rolled back. Refuses if the schema already exists or the capability doesn't.

### 7. Fill in the placeholders

Open the stamped files and replace:

**In `<name>.yaml`:**

- The first comment block — what the schema encodes (one line) plus a paragraph on its purpose.
- For namespace owners: per-entry-field comments — for each field you plan to declare in the companion, add a short description.
- For documents: the actual top-level fields, mirroring what's declared in the companion's `properties`.
- If applicable, uncomment + fill the `source:` block.

**In `<name>.schema.json`:**

- The `title` — short label for what the schema encodes.
- The `description` — one paragraph on the schema's shape. Convention: start with "Formal shape of `<name>.yaml` — ...".
- The schema body:
  - **Namespace owner** — `$defs.entry.properties` declares each per-entry field's type + constraints + description. `$defs.entry.required` lists which fields are required (defaults to none in the stamp). This is the schema's most substantive content.
  - **Document** — top-level `properties` declares each of the document's fields directly. `required` lists which fields the document must carry (defaults to `["schema_version"]` in the stamp; add the document's own required fields).
- For fields that are cross-schema references, use the typed-token pattern (per COR-019). When the field accepts only one target namespace, `$ref` the published narrowed pattern from the namespace owner: `{"$ref": "validation-severity.schema.json#/$defs/severity_ref"}`. When the field accepts any namespace, `$ref` the canonical `reference_token`: `{"$ref": "refs.schema.json#/$defs/reference_token"}`.

### 8. (Optional) Publish a narrowed reference pattern

*(Namespace owners only — document schemas have no namespace, so nothing to reference by token.)*

If consumers will reference this namespace via typed tokens (`[<name>:<id>]`), add a `<name>_ref` entry to the companion's `$defs` so consumers can `$ref` it rather than redeclaring the pattern:

```json
"$defs": {
  "<name>_ref": {
    "type": "string",
    "pattern": "^\\[<name>:[a-z][a-z0-9-]*\\]$",
    "description": "Narrowed cross-schema reference pattern for this namespace (per COR-019)."
  },
  "entry": { ... }
}
```

This makes the namespace a participating member of the single-source-of-truth pattern — see the schemas area README.

### 9. Validate

Run the validator to confirm the schema is clean:

```
pkit schemas validate
```

If issues surface, the messages name what's wrong + where. Fix and re-run.

### 10. Add initial entries

*(Namespace owners only — document schemas have no collection to extend; fill the document body directly in step 7.)*

If you have entries ready, add them via `pkit schemas add` (one at a time, each validated independently):

```
pkit schemas add <name> <id> --from <path-or-dash>
```

For richer entries, write to a YAML file and pass via `--from`. For simple ones, pipe via stdin (`--from -`). Either way, the resulting file re-validates after each add.

### 11. Self-check against the disciplines

Walk the new schema against the kit's authoring disciplines (per `CONTRIBUTING.md`):

- *Axiom*: every term used in the schema's prose has a prior definition, is generic English / YAML / JSON Schema vocabulary, or names a known external tool.
- *Project-neutrality* (when the schema ships kit-side): would this fit naturally in `example-brownfield` or `example-greenfield` adopting the methodology?
- *Principles-not-inventory*: the schema captures rules-among-alternatives, not state inventories. (The *entries* may be a closed set when the methodology defines it — e.g., the three severity classes; but the schema's *shape* expresses the rule.)

### 12. Commit

Per COR-008, conventional-commits format:

```
feat(<capability>): add <name> schema

<body — 1–3 paragraphs naming what the schema encodes, what each
entry expresses, which (if any) external spec it distills from,
and how engine code consumes it.>
```

For example:

```
feat(project-management): add release-trains schema

Encodes the named release trains a project ships against. Each entry
carries name + cadence + current iteration + responsible team. Engine
reads at scheduling time to decide which release a new milestone
joins.
```

## Variations

- **Stamping a CONSUMER or document schema** (one that doesn't own a namespace). Pass `--no-namespace` — the stamp omits `x-pkit-id-collection`, the `$defs.entry` placeholder, and the collection wrapper; you fill flat top-level `properties` in the companion and the resource's own fields in the YAML body.
- **Stamping into a non-default capability layout** — if the capability ships its own `_defs/` for narrowed reference patterns, declare them there. For v1, narrowed patterns live alongside their namespace owner; see the schemas area README's "References between schemas" subsection.
- **Stamping a schema before its capability exists** — refuses. Run `pkit new capability <name>` first.

## Adopter-data schemas — the `pkit_schema:` field + `binds_to:` fallback

When the new schema describes **adopter-side data** (files an adopting project creates that follow this schema, rather than internal capability data the engine reads), the adopter-data layer needs a binding so the resolver knows which schema applies. Per [COR-023] (superseding [COR-022]):

- **Adopter data files SHOULD carry a top-level `pkit_schema: <capability>:<schema>` field.** This is the recommended discipline; the field is self-describing and survives `pkit sync`.
- **The schema YAML SHOULD declare a top-level `binds_to:` field** listing repo-relative glob patterns that match the adopter-data files this schema validates:

  ```yaml
  # .pkit/capabilities/trip-planning/schemas/trip.yaml
  schema_version: 1
  binds_to:
    - "trips/*/trip.yaml"
  # … rest is the schema's namespace content
  ```

  The `binds_to:` field is the fallback that catches adopter files which omit the explicit `pkit_schema:` field. The resolver walks installed capabilities' `schemas/*.yaml` files looking for `binds_to:` matches when a data file is unannotated.

- **Adopters validate via `pkit data validate <path>`**, not `pkit schemas validate` (which validates capability-side schema pairs, not adopter data).

When designing the companion's shape, allow the `pkit_schema:` field at the top level on adopter data (e.g., `"pkit_schema": {"type": "string"}` in `properties`) as a non-required field — the binding mechanism owns the field's semantics, not the schema's content. The schema YAML's own envelope already permits `binds_to:` as a recognised top-level field.

If the schema is purely an internal namespace owner (engine data, methodology mesh, no adopter-side data files), no binding mechanism applies — skip this section. `binds_to:` is optional; schemas without it declare no fallback bindings.
