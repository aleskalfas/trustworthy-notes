---
id: COR-023
title: Adopter data files bind to schemas via a `pkit_schema:` top-level field; capabilities declare per-schema fallbacks via a `binds_to:` field inside each schema YAML
status: accepted
date: 2026-05-25
author: Ales Kalfas <kalfas.ales@gmail.com>
supersedes: COR-022
---

## Context

[COR-022] established the adopter-data binding mechanism: a top-level `pkit_schema:` field declares the schema explicitly, with a capability-declared fallback for files that omit the field. The decision specified the fallback as a sibling `schemas/bindings.yaml` — a separate file that lists `{schema, matches}` pairs for the capability.

That sub-decision (the *location* of the fallback) introduced an unnecessary layer of indirection. A capability authoring a new schema has to edit two files — the schema's own YAML *and* the central `bindings.yaml`. The bindings file is a registry that duplicates information already addressable from the schema itself: a schema knows what data it applies to; expressing the binding alongside the schema's other metadata is the natural shape.

The first review of the implementation surfaced this immediately: why does the binding live in a separate file when each schema could declare its own `binds_to:` patterns alongside its content? The shipped `bindings.yaml` shape is defensible but it's the wrong default — it groups what should be per-schema, and it adds a meta-schema + sub-procedure for an artefact that didn't need to exist.

This record supersedes [COR-022] and re-establishes the binding convention with the fallback expressed inline on each schema. The field-first convention, the resolution order, the schema-version-mismatch handling, the IDE-directive stamping, and the `pkit data validate` CLI command surface stay unchanged — only the *shape* of the fallback changes.

## Decision

**Adopter data files declare their schema via a top-level `pkit_schema: <capability>:<schema-name>` field; capabilities declare fallback bindings via a `binds_to:` field inside each schema's YAML; resolution refuses cleanly when neither matches.** The `pkit data validate <path>` command consumes the binding and runs JSON Schema validation. Authoring stamps an IDE directive alongside the field so editors with no `pkit` integration still light up.

### The `pkit_schema:` field

An adopter data YAML carries `pkit_schema:` as its **first key** (or first key after a leading IDE-directive comment line — see below). The value is the bare two-part token `<capability>:<schema-name>`:

```yaml
# yaml-language-server: $schema=.pkit/capabilities/trip-planning/schemas/trip.schema.json
pkit_schema: trip-planning:trip
schema_version: 1
slug: japan-2026
title: Japan (Tokyo)
# …
```

- `<capability>` is an installed capability name (matching the directory under `.pkit/capabilities/`).
- `<schema-name>` is a schema stem in that capability (matching `<name>.yaml` + `<name>.schema.json` under `<capability>/schemas/`).

The reference shape is the bare two-part form (no brackets), distinct from the bracketed typed-token form in COR-019. The brackets in COR-019 delimit references *embedded in prose or other field values*; in field position where the entire value is the reference, the brackets add noise.

The field is optional but recommended. When present, it is authoritative — the resolver uses the field directly without consulting capability fallbacks.

### Capability `binds_to:` per-schema fallback

A capability schema's YAML may declare path-pattern fallbacks via a top-level `binds_to:` field — a list of repo-relative glob patterns the schema matches:

```yaml
# .pkit/capabilities/trip-planning/schemas/trip.yaml
schema_version: 1
binds_to:
  - "trips/*/trip.yaml"
# … rest is the schema's namespace content (entries, types, document fields, …)
```

The field is optional. A schema without `binds_to:` declares no fallback bindings — adopter data files referencing it must use the explicit `pkit_schema:` field. Most schemas in the kit are namespace owners or capability-internal — `binds_to:` matters only for schemas that describe adopter-data files.

When an adopter data file omits `pkit_schema:`, the resolver walks every installed capability's `schemas/*.yaml`, in capability-name order, and uses the first matching `binds_to:` glob. Multiple matches across capabilities surface as an ambiguous-binding refusal pointing the adopter at the `pkit_schema:` field as the escape hatch.

The `binds_to:` field is governed by the schemas-mechanism envelope (the same shape `schema_version:` + `source:` already share). Its presence neither requires nor implies any meta-schema beyond what the schema's own companion already declares — `binds_to:` becomes a recognised top-level field in any schema YAML the kit consumes.

### Resolution order

For a given adopter data file path:

1. **Field-first.** Parse the YAML; if it carries a top-level `pkit_schema:` field, resolve `<capability>:<schema-name>` to the capability's schema and validate against the companion.
2. **Capability fallback.** Walk installed capabilities (via the backbone manifest); for each capability, walk its `schemas/*.yaml`; match the adopter file's repo-relative path against each schema's `binds_to:` glob entries. First match wins; multiple matches across capabilities are ambiguous (refuse).
3. **Refuse.** No field, no matching binding: the resolver reports a structured "no schema binding" error naming the file and pointing the adopter at the two ways to declare one.

### Schema-version mismatch handling

The data file's `schema_version` field declares which version of the schema the data was authored against. The schema (the capability's `<schema>.yaml`) declares its current `schema_version`. When the two disagree, the validator refuses with a structured migration hint naming both versions and pointing at the capability's migration tier. Auto-migration is **out of scope for v1** — adopter data is often hand-edited, and silent transformation is the wrong default.

### IDE-directive stamping

The schemas mechanism's adopter-data authoring stamps the YAML Language Server directive alongside the `pkit_schema:` field:

```yaml
# yaml-language-server: $schema=.pkit/capabilities/<capability>/schemas/<schema>.schema.json
pkit_schema: <capability>:<schema-name>
schema_version: 1
# …
```

The two carry the same binding, but each serves a different tool surface — the comment for any editor running the YAML Language Server, the field for the kit's own tooling. Drift is bounded: the authoring step writes both atomically; a future validator pass can confirm the two agree.

### The `pkit data validate <path>` command

The CLI command consuming the binding mechanism:

- `pkit data validate <path>` — resolves the binding for one adopter data file, runs JSON Schema validation against the resolved schema, and reports findings.
- The command accepts a file or a directory; directories walk for `*.yaml` recursively.
- Returns a non-zero exit code on any validation failure or unresolved binding.

The command is distinct from `pkit schemas validate`: the latter validates capability-side schema pairs (the spec); the former validates adopter-side data files against those schemas. Two validators, two artefacts, two surfaces — keeping them separate avoids overloading a single command with two distinct semantics.

## Rationale

**Why `binds_to:` inside the schema YAML rather than a separate `bindings.yaml`.** A capability's schema knows what data it applies to; that knowledge is more naturally expressed *on* the schema than abstracted into a registry that names schemas by string. The inline form has one source of truth per schema, dies with the schema when it's removed, and removes one layer of indirection from the resolver. The original `bindings.yaml` design introduced a separate file, a separate meta-schema, and a separate skill sub-procedure for an artefact that captures one rule per schema — the rule belongs alongside the schema's content, not in a sibling registry.

The trade-off the registry shape would offer is a single grep target: "show me every binding in this capability." A directory of schemas with `binds_to:` fields requires walking all schema YAMLs to answer the same question. The cost is small — `grep -l binds_to: schemas/` works — and the benefit of co-located ownership outweighs the marginal scan cost.

**Why a field-first convention over filename-only inference** (unchanged from [COR-022]). Filename heuristics are implicit; the binding is not visible from the file. A reader opening `transport.yaml` cannot answer "what schema is this?" without tracing dir structure to a capability's declared conventions. The field makes the binding self-evident at the top of the file — the same discipline already established for `schema_version` (first key, machine-consumable, human-readable). Adopters who don't want to stamp the field still get fallback resolution, but the recommended path is the explicit one.

**Why the bare two-part reference (`<capability>:<schema>`) over bracketed (`[<capability>:<schema>]`)** (unchanged). COR-019's brackets delimit tokens *embedded in prose or other field values* — needed when the surrounding context is text. In a YAML field where the entire value is the reference, the brackets add visual noise without disambiguating anything.

**Why `pkit_schema:` over `$schema:` or `schema:`** (unchanged). JSON Schema's `$schema` keyword is reserved by the spec to declare the *meta-schema* a document is written in. Reusing it to mean "the validating schema" would confuse any tool that expects the standard JSON-Schema semantic. Bare `schema:` collides with field names in capability YAMLs that already use `schema_version` and reads ambiguously.

**Why refuse-on-version-mismatch over auto-migrate in v1** (unchanged). Auto-migration of adopter data is risky: data is often hand-edited, fields may carry adopter-specific meaning the migration script doesn't know about, and a silent transformation breaks the adopter's mental model of what's in the file. The refuse-with-hint stance forces the adopter to read the migration plan before applying it.

**Why two sources of truth (field + IDE directive) over one** (unchanged). A single pkit-aware Language Server would eliminate the duplication, but it's a substantial build (and a per-editor build). The YAML Language Server directive is already supported by every JSON-Schema-aware editor; using it costs zero new infrastructure.

**Why `pkit data validate` rather than overloading `pkit schemas validate`** (unchanged). Two semantically distinct operations — validating the spec vs. validating instance data — deserve two commands. Overloading one command with both semantics, branching on whether the path is under a capability or in the adopter tree, makes the command's behaviour invisible to the reader of a CI workflow or an error message.

### Alternatives considered

- **Separate `schemas/bindings.yaml` registry** (the original [COR-022] shape). Rejected per the `binds_to:` rationale above — adds a registry file, a meta-schema, and a skill sub-procedure for one rule per schema; the rule belongs with the schema's content.
- **Sidecar binding file** (`<filename>.schema-binding` next to each adopter data file). Rejected — file proliferation (one extra file per data file) and drift risk (the sidecar references a schema the data no longer matches). The field-in-file approach binds atomically with the data.
- **Filename / path convention only.** Rejected — implicit, not visible from file content, and breaks when two capabilities ship overlapping conventions. `binds_to:` survives as the *fallback* but not as the primary mechanism.
- **YAML Language Server directive as the canonical form.** Rejected — ties the kit's data-binding convention to one editor's convention; the directive stores absolute paths that don't survive `pkit sync`; and pkit's own tooling would have to parse a comment to do its job.
- **Pure capability-declared bindings (no per-file field).** Rejected — the file's schema becomes invisible to a reader; debugging "why is this validation failing?" requires walking the capability's binding rules.
- **`$schema:` field reusing the JSON Schema convention.** Rejected — `$schema` is reserved for declaring the *meta-schema*, not the validating schema.
- **Auto-migrate on schema-version mismatch.** Rejected for v1 — silent transformation of hand-edited adopter data is the wrong default.

## Implications

- **`schemas/bindings.yaml` is removed from the mechanism.** Capabilities that adopted the [COR-022] shape (none in the kit, only the design landed) drop the file and move bindings inline. The meta-schema (`bindings.schema.json`) shipped with [COR-022] is removed. No adopter has yet migrated, so blast radius is zero.
- **The `schema` skill's `bindings` sub-procedure is removed.** Authoring shifts to "add `binds_to:` to the schema YAML you're already editing." The `schema-author` sub-procedure picks up the field as a recognised top-level shape.
- **The schemas area README's "Capability bindings" section** rewrites for the inline form. The adopter-data layer remains a first-class concept the area covers.
- **The `pkit data validate <path>` command** keeps its surface and exit-code contract; only the resolver's fallback branch changes (walks `<capability>/schemas/*.yaml` for `binds_to:` instead of reading one bindings.yaml per capability).
- **The schemas-mechanism envelope recognises `binds_to:`** as an optional top-level field on any schema YAML. Schemas without the field declare no fallback bindings — the common case. Adopter-data schemas opt in by adding the field.
- **The first showcase adopter (`example-adopter`) migrates its `trips/<slug>/*.yaml` files** to carry the `pkit_schema:` field and the IDE directive; the `trip-planning` capability adds `binds_to:` entries to its `trip.yaml` and `transport.yaml` schemas. The migration is per-adopter — the kit ships the mechanism; adopters opt in.
- **Surface change is a new convention adopters can break against**; this PR bumps the backbone version. The change supersedes a recent record (COR-022) shipped in v1.28.0; no adopter migration script is needed since no adopter has yet adopted the v1.28.0 bindings.yaml shape.
