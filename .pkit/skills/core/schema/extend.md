
# Extending a schema with a new entry

This skill walks through adding **one new entry** to a schema's id collection — a new severity in `validation-severity.yaml`, a new state in `workflow.yaml`, a new issue type in `issue-types.yaml`, etc.

For authoring an entirely new schema (a new namespace), see `schema-author`. This skill is for extending one that already exists.

## Acceptance gate (run first)

Per the schemas area's conventions, verify each record in `gates:` is `accepted`:

- **COR-008** — git workflow conventions. Used for the commit step.
- **COR-018** — capabilities adopt the schemas mechanism. Used to confirm the schema is one this skill should be modifying (schemas under `.pkit/capabilities/*/schemas/`).
- **COR-019** — schema reference form. Used to know whether the new entry's fields involve cross-schema references (typed tokens vs bare ids).

Halt if any is `proposed` or `superseded`.

## Procedure

### 1. Identify the target namespace

Confirm which namespace gains the entry. Useful checks:

```
pkit schemas list                       # see all installed namespaces
pkit schemas show <namespace>           # inspect the namespace's existing entries
```

If the namespace doesn't exist among installed capabilities, the user is asking for a new schema, not an extension — switch to `schema-author`.

### 2. Pick an id

Kebab-case, starts with a lowercase letter, unique within the namespace. The naming pattern usually mirrors the existing entries' style (semantic id, not number suffix). Examples:

- adding to `validation-severity`: `info`, `notice`, `deprecation`
- adding to `workflow`'s states: `triage`, `paused`, `archived`
- adding to `issue-types`: `outage`, `experiment`

### 3. Inspect the entry shape

Read the namespace's JSON Schema companion to learn the required + optional fields for each entry. The companion lives at `.pkit/capabilities/<cap>/schemas/<namespace>.schema.json`. Look at the per-entry sub-shape (typically referenced from `patternProperties` for mapping-form collections, or `items` for list-form).

Key questions:

- *Which fields are required?* The companion's `required` array on the per-entry sub-shape.
- *What types?* (string / boolean / array / object)
- *Any enum or pattern constraints?* (e.g., a `severity` field's value must be `[validation-severity:<id>]` — that's a cross-schema typed token; the field's `pattern` declares the shape).
- *Are any fields conditional?* (e.g., `validation-severity.schema.json` requires `override` iff `overridable: true`).

### 4. Decide cross-schema references (per COR-019)

If the new entry's fields reference ids from another namespace, write them as typed tokens `[<namespace>:<id>]`. Common cases:

- A new `validation` rule whose `severity` references a severity in `validation-severity.yaml`: `severity: "[validation-severity:hard-reject]"`.
- A new state whose `applies_to` references issue-type ids: `applies_to: ["[issue-types:task]", "[issue-types:feature]"]`.

Intra-schema references (e.g., a new transition's `from` / `to` referencing states defined in the same `workflow.yaml`) stay bare.

### 5. Draft the entry data

Compose the fields as a YAML mapping. Example for a new severity:

```yaml
description: |
  Informational note; non-fatal; no audit comment. Used to surface
  context without blocking the operation.
blocks: false
overridable: false
```

If the entry has many fields or includes multi-line prose, save it to a temp file (any path your shell can read; e.g., a scratch file in the system temp directory). The CLI accepts both `--from <path>` and stdin.

### 6. Apply via the CLI

Use the authoring command:

```
pkit schemas add <namespace> <id> --from <path-or-dash>
```

The command:

- Locates the namespace owner via `find_namespace_owner`.
- Reads the YAML with round-trip preservation (existing comments + formatting + key order survive).
- Appends the entry to the collection (mapping-form: as a new key; list-form: as a new item with `id:` first).
- Re-validates the resulting file via the same shape + resolver passes `pkit schemas validate` runs.
- On validation failure, restores the prior file and reports the issues.

Refuses if the id is already in use (use a different id, or edit the existing entry directly).

### 7. Confirm

After the command succeeds, run `pkit schemas validate` to verify the whole schema set is still clean (the command already ran it, but a separate confirmation catches any unexpected interactions with sibling schemas — e.g., the new entry's id now resolves cross-file references that previously failed).

### 8. Commit

Per COR-008, conventional-commits format. Type and scope reflect the artifact:

```
feat(<capability>): add <namespace> entry <id>

<body — 1–3 paragraphs naming what the new entry is for, what the
fields express, and (when applicable) which other schemas the entry's
fields reference via tokens>
```

For example:

```
feat(project-management): add validation-severity entry 'info'

Adds an informational severity class: non-blocking, non-overridable,
no audit-comment posted. Used for surface-level guidance the agent
can emit without forcing a user decision.
```

## Variations

- **Editing an existing entry rather than adding a new one** — edit the YAML in place; this skill is for new entries only. The shape + resolver passes still run on the edited result via `pkit schemas validate`.
- **Adding multiple entries at once** — run the command once per entry. Each invocation re-validates the whole file, catching invariants violated by intermediate combinations.
- **Adding an entry to a schema you also intend to evolve structurally** (new required field across all entries) — first author a `schema_version` bump in the companion + migrate existing entries, then add the new one. Out of scope for this skill; see the migration framework (COR-010 / `.pkit/lifecycle/README.md`).
