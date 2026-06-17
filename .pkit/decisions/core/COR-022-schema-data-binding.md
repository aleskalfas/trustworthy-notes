---
id: COR-022
title: Adopter data files bind to schemas via a `pkit_schema:` top-level field with capability-declared fallback bindings
status: superseded
date: 2026-05-25
author: Ales Kalfas <kalfas.ales@gmail.com>
---

*Superseded by [COR-023]. The field convention, resolution order, schema-version handling, IDE-directive stamping, and `pkit data validate` CLI all stand; only the fallback location changes — capabilities declare bindings via a `binds_to:` field inside each schema YAML, not a separate `schemas/bindings.yaml` registry. The original `bindings.yaml` shape introduced an unnecessary layer of indirection (separate file, separate meta-schema, separate skill sub-procedure for one rule per schema); the inline form puts the rule alongside the schema's content where it belongs. See COR-023's Context for the supersession rationale.*

## Context

The schemas mechanism (COR-018 + the `.pkit/schemas/` area) defines schemas as YAML data + JSON Schema companion pairs living inside capabilities at `<capability>/schemas/`. The mechanism handles two layers cleanly: each schema's own shape (companion validates the YAML), and cross-schema data references (typed-token form `[<namespace>:<id>]` per COR-019). What the mechanism *doesn't* yet handle is the **adopter data layer** — files in an adopting project that follow a capability's schema but live in the adopter's own tree, not under `<capability>/schemas/`.

Concretely: an adopter applying the `trip-planning` capability writes `trips/<slug>/trip.yaml`. That YAML is structurally shaped by `<capability>/schemas/trip.schema.json`, but nothing in the file *says* so. Filename matches, by convention; no tool today reads the adopter file and decides "this is schema X." Three things break against that gap:

1. **Discovery** — tooling walking adopter files cannot answer "what schema applies here?" without out-of-band knowledge (filename heuristic, parent-capability inference, hard-coded mapping).
2. **Editor integration** — JSON-Schema-aware editors (VS Code, JetBrains family) cannot surface the schema without a binding directive; the YAML Language Server's `# yaml-language-server: $schema=...` is tool-specific and stores absolute paths that don't survive `pkit sync`.
3. **Validate-against-schema** — `pkit schemas validate` validates capability-side schema pairs (the spec). It does not validate adopter data against a referenced schema. Adopters who want validation today run the `jsonschema` library directly with the right file pair, which they probably will not.

The first adopter that hit this gap (`example-adopter` applying the `trip-planning` capability) surfaced it within hours of installing the capability. The pattern is general — every future capability shipping adopter-data schemas will land in the same gap. COR-007's threshold is met; the binding mechanism extracts now.

## Decision

**Adopter data files declare their schema via a top-level `pkit_schema: <capability>:<schema-name>` field; capabilities may ship a `schemas/bindings.yaml` declaring path-pattern fallbacks for files that omit the field; resolution refuses cleanly when neither matches.** A new CLI command `pkit data validate <path>` consumes the binding and runs JSON Schema validation. Authoring stamps an IDE directive alongside the field so editors with no `pkit` integration still light up.

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

The field is optional but recommended. When present, it is authoritative — the resolver uses the field directly without consulting capability bindings.

### Capability `schemas/bindings.yaml` fallback

A capability that ships adopter-data schemas may declare path-pattern fallbacks in a sibling `schemas/bindings.yaml`:

```yaml
schema_version: 1
bindings:
  - schema: trip
    matches: "trips/*/trip.yaml"
  - schema: transport
    matches: "trips/*/transport.yaml"
```

Each binding maps a glob pattern (matched against the adopter file's repo-relative path) to a schema in the same capability. The file's own shape is governed by a meta-schema shipped by the schemas mechanism — the same authoring discipline as any other schema in the kit.

When an adopter data file omits `pkit_schema:`, the resolver walks every installed capability's bindings file, in capability-name order, and uses the first matching binding. Multiple matches across capabilities surface as a resolution error (ambiguous binding); the adopter resolves it by adding the explicit field.

### Resolution order

For a given adopter data file path:

1. **Field-first.** Parse the YAML; if it carries a top-level `pkit_schema:` field, resolve `<capability>:<schema-name>` to the capability's schema and validate against the companion.
2. **Capability fallback.** Walk installed capabilities (via the backbone manifest); for each capability with `schemas/bindings.yaml`, match the file's repo-relative path against each binding's `matches:` glob. First match wins; multiple matches across capabilities are ambiguous (refuse).
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

A new top-level CLI command consumes the binding mechanism. Surface:

- `pkit data validate <path>` — resolves the binding for one adopter data file, runs JSON Schema validation against the resolved schema, and reports findings.
- The command accepts a file or a directory; directories walk for `*.yaml` recursively.
- Returns a non-zero exit code on any validation failure or unresolved binding.

The command is distinct from `pkit schemas validate`: the latter validates capability-side schema pairs (the spec); the former validates adopter-side data files against those schemas. Two validators, two artefacts, two surfaces — keeping them separate avoids overloading a single command with two distinct semantics.

## Rationale

**Why a field-first convention over filename-only inference.** Filename heuristics (`trips/*/transport.yaml` → `trip-planning:transport`) are implicit; the binding is not visible from the file. A reader opening `transport.yaml` cannot answer "what schema is this?" without tracing dir structure to a capability's declared conventions. The field makes the binding self-evident at the top of the file — the same discipline already established for `schema_version` (first key, machine-consumable, human-readable). Adopters who don't want to stamp the field still get fallback resolution, but the recommended path is the explicit one.

**Why the bare two-part reference (`<capability>:<schema>`) over bracketed (`[<capability>:<schema>]`).** COR-019's brackets delimit tokens *embedded in prose or other field values* — needed when the surrounding context is text. In a YAML field where the entire value is the reference, the brackets add visual noise without disambiguating anything. The bare form mirrors `apiVersion`/`kind` in Kubernetes and `schema_version` in the kit's own schemas — scalar identifier in field position, no delimiter ceremony.

**Why `pkit_schema:` over `$schema:` or `schema:`.** JSON Schema's `$schema` keyword is reserved by the spec to declare the *meta-schema* a document is written in (`https://json-schema.org/draft/2020-12/schema`). Reusing it to mean "the validating schema" would confuse any tool that expects the standard JSON-Schema semantic. Bare `schema:` is too generic — it collides with field names in capability YAMLs that already use `schema_version`, and reads ambiguously (is this *defining* a schema or *referencing* one?). The `pkit_` prefix scopes the field unambiguously to the kit's binding mechanism; the prefix is a few extra characters in exchange for zero spec-collision risk.

**Why refuse-on-version-mismatch over auto-migrate in v1.** Auto-migration of adopter data is risky: data is often hand-edited, fields may carry adopter-specific meaning the migration script doesn't know about, and a silent transformation breaks the adopter's mental model of what's in the file. The refuse-with-hint stance forces the adopter to read the migration plan before applying it, preserving the human-in-the-loop discipline the kit applies elsewhere (collision prompts on install, acceptance gate on decisions). Auto-migration is a future refinement when usage patterns make the trade-off clearer.

**Why two sources of truth (field + IDE directive) over one.** A single pkit-aware Language Server would eliminate the duplication, but it's a substantial build (and a per-editor build, since LSP integration varies). The YAML Language Server directive is already supported by every JSON-Schema-aware editor; using it costs zero new infrastructure. The cost — two locations carrying the same binding — is bounded: authoring writes both atomically, a validator can confirm they agree, and the duplication serves a real purpose (the comment unblocks editors, the field unblocks kit tooling). When a pkit LSP becomes worth building, the field stays as the canonical source and the directive becomes vestigial; until then, both pull weight.

**Why `pkit data validate` rather than overloading `pkit schemas validate`.** Two semantically distinct operations — validating the spec (capability YAML + companion) vs. validating instance data (adopter file + schema) — deserve two commands. Overloading one command with both semantics, branching on whether the path is under a capability or in the adopter tree, makes the command's behaviour invisible to the reader of a CI workflow or an error message. The verb-subject form `data validate` matches the dispatcher pattern (COR-021) and reads cleanly: "validate the data," as distinct from "validate the schemas."

**Why capability-declared bindings live in `schemas/bindings.yaml` and not in `package.yaml`.** A capability's `package.yaml` carries component metadata (version, requires_backbone, declared commands per COR-021); the bindings file carries data-resolution conventions. Different change cadence, different audience (the bindings file is consumed by the resolver; `package.yaml` is consumed by the installer and the CLI dispatcher), different shape. Folding the bindings into `package.yaml` would bloat that file without consolidating its concerns. The dedicated file follows the same discipline as the rest of the schemas mechanism — each shape lives in its own file with its own companion.

### Alternatives considered

- **Sidecar binding file** (`<filename>.schema-binding` next to each data file). Rejected — file proliferation (one extra file per data file) and drift risk (the sidecar references a schema the data no longer matches). The field-in-file approach binds atomically with the data.
- **Filename / path convention only.** Rejected — implicit, not visible from file content, and breaks when two capabilities ship overlapping conventions. Pure capability-declared bindings (3.5 in the scratchpad) is this convention generalised, and it survives as the *fallback* in this decision but not as the primary mechanism.
- **YAML Language Server directive as the canonical form.** Rejected — ties the kit's data-binding convention to one editor's convention; the directive stores absolute paths that don't survive `pkit sync`; and pkit's own tooling would have to parse a comment to do its job, which is ad hoc. The directive is *adjunct* to the field, not the source of truth.
- **Pure capability-declared bindings (no per-file field).** Rejected — the file's schema becomes invisible to a reader; debugging "why is this validation failing?" requires walking the capability's binding rules. The hybrid (field-first, bindings as fallback) gives self-describing data files for the common case and a clean escape hatch for adopters who don't want to annotate every file.
- **`$schema:` field reusing the JSON Schema convention.** Rejected — `$schema` is reserved for declaring the *meta-schema*, not the validating schema. Reusing it would confuse JSON-Schema-aware tooling.
- **Auto-migrate on schema-version mismatch.** Rejected for v1 — silent transformation of hand-edited adopter data is the wrong default. The refuse-with-hint stance keeps the human in the loop; auto-migration can come back as a follow-up when usage patterns justify it.
- **Overload `pkit schemas validate` to also validate adopter data when given an external path.** Rejected — overloading one command with two semantically distinct operations (spec validation vs. instance validation) makes the command's behaviour invisible at the call site. Two artefacts, two commands.

## Implications

- **The schemas area README documents the binding mechanism.** The adopter-data layer joins the spec layer (schema YAML + companion) as a first-class concept the area covers. The `pkit_schema:` field convention, the bindings file shape, the resolution order, and the `pkit data validate` command surface in the area's reference documentation.
- **The `schema` skill (composite per COR-020) gains a bindings sub-procedure.** Authoring a capability's `schemas/bindings.yaml` becomes a recognised operation under the same skill that covers schema authoring; the dispatcher (`schema.md`) points at the sub-procedure for "stamp bindings." The schema-author sub-procedure also documents the adopter-data field convention so adopters writing their own data files have a single authoring reference.
- **A meta-schema for `bindings.yaml` ships under `.pkit/schemas/_defs/`** (or a sibling location the schemas mechanism owns). The shape — `schema_version: 1`, `bindings: [{ schema: <name>, matches: <glob> }]` — is mechanically validated like any other schema in the kit. Capabilities adopting the bindings mechanism ship a `bindings.yaml` that passes the meta-schema; `pkit schemas validate` extends its coverage to include bindings files alongside capability schema pairs.
- **A new top-level CLI command `pkit data validate <path>` lands** alongside the existing `pkit schemas validate`. The two coexist with non-overlapping scopes (spec vs. instance). The command is additive — adopters who don't use the binding mechanism see no change in behaviour.
- **Capability migrations may bump schema versions independently of the data.** When a capability bumps a schema's `schema_version`, adopter data files referencing that schema continue to declare the old version until the adopter migrates them; the validator surfaces the mismatch as a hard refuse with a migration hint. The capability's migration tier (per COR-017) carries the migration script; adopters apply it explicitly.
- **The first showcase adopter (`example-adopter`) migrates its `trips/<slug>/*.yaml` files** to carry the `pkit_schema:` field and the IDE directive; the `trip-planning` capability ships `schemas/bindings.yaml` covering the per-trip file shapes. The migration is per-adopter — the kit ships the mechanism; adopters opt in by stamping their files and (if shipping a capability) declaring bindings.
- **Surface change is a new convention adopters can break against**; this PR bumps the backbone version per the per-component bump policy from PRJ-002 and rule 7 of the operational core. No migration script is required at the backbone tier — the change is purely additive (new field convention, new CLI command, new bindings file shape); existing adopter data without the field continues to work (subject to the resolver's refuse-when-no-binding behaviour).
