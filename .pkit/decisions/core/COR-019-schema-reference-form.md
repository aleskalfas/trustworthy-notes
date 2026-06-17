---
id: COR-019
title: Cross-schema references use namespace-bearing tokens
status: accepted
date: 2026-05-21
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

The schemas mechanism (defined in `.pkit/schemas/`) lets one schema's data reference an entry defined in another schema's data — a workflow state declaring which issue types it applies to, a validation rule declaring its severity class, an aggregator schema pointing at entries spread across sibling files. The reference is a *data* construct: a value in one YAML file that names an id defined elsewhere.

Two forms of cross-schema reference work mechanically:

1. **Bare id with field-name convention.** The value is a kebab-case id (`task`, `hard-reject`); the consumer infers the target schema from the field name (and its leading comment). Example: `applies_to: [task]` in a `workflow.yaml` field whose comment says "issue-type ids."
2. **Namespace-bearing token.** The value carries its target namespace explicitly, shaped `[<namespace>:<id>]`. Example: `applies_to: ["[issue-types:task]"]`.

The area README sanctioned both forms as the mechanism was being established. Practice across the first two adopters surfaced the trade-off: when a schema references one or two well-known targets, bare ids read cleanly; when a schema aggregates references across many sibling files (one root pointing at five sibling namespaces), the field-name-signals-target convention breaks down and bare ids become ambiguous.

This record settles which form is the convention going forward.

## Decision

**Cross-schema data references use the namespace-bearing token form `[<namespace>:<id>]`.** The `<namespace>` is the source schema's stem (e.g., `issue-types`, `validation-severity`); the `<id>` is the entry id within that schema's collection. Intra-schema references — a value in one YAML file naming an id defined elsewhere *in the same file* — remain bare ids, because no namespace ambiguity exists.

**Value-position** ids and **key-position** ids follow different rules, because key-position carries different ergonomic constraints:

- **Value-position** ids that reference *another* namespace use the typed-token form. The value is a leaf; the JSON Schema has no convenient place to declare the source namespace, so the token's namespace half carries it.

- **Key-position** ids stay bare, always — whether the keys declare their own namespace or reference a foreign one. Mapping keys appear at definition sites (`issues.epic: {...}` reads naturally; `issues."[issue-types:epic]": {...}` is noise) and the parent field's schema is the right place to declare the source namespace, not the data. When a mapping's keys reference a foreign namespace, the parent field's JSON Schema companion carries an `x-pkit-keys-from-namespace: "<namespace>"` annotation; the resolver walks the annotation to validate each key against the named namespace.

Intra-schema references in *value* position (a transition's `from`/`to` naming a state defined in the same workflow schema) stay bare — no namespace ambiguity.

The JSON Schema companion validates token *shape* via a `pattern` constraint shared across companions (`$defs.reference_token` parameterised on namespace where applicable). Resolution of a token to its target entry across files is the consuming code's or a dedicated cross-file validator's responsibility — JSON Schema does not look across files.

## Rationale

**Why namespace-bearing tokens.** A bare id is meaningful only when one obvious target exists for the field that carries it. The field's name and comment encode that target. The convention works for simple cases (one-to-one cross-schema references with well-named fields) and breaks for aggregator and multi-target cases (one root file pointing at many sibling namespaces; a field referencing entries from one of several namespaces). Namespace-bearing tokens make the target explicit, surviving aggregator patterns and removing the need for the reader to trace the field-name convention back to the target schema.

**Why settle now rather than supporting both.** Two forms in active use forces every tool (resolver, IDE plugin, validator) to handle both. It also forces every consumer of the mechanism (capability, adopter project) to pick one, with no shared expectation across the ecosystem. Settling on one form means one resolver, one pattern, one expectation. The cost — a few additional characters per reference — is bounded; the clarity compounds.

**Why intra-schema references stay bare.** Inside one YAML file, no namespace ambiguity exists: every id reference targets an id defined in the same file. Adding a namespace prefix would be redundant noise. Mapping keys stay bare for the same reason — the file declares the namespace by holding the keys; only references *from elsewhere* need to name the namespace.

### Alternatives considered

- **Bare ids with field-name convention (status quo permissive option).** Rejected — breaks down in aggregator patterns and forces readers to trace the field-name convention back to the target schema; mixed adoption across the ecosystem makes tooling write twice.
- **Allow both forms; adopters pick per schema.** Rejected — fragments tooling; loses shared expectations; passes the choice to every author with no guidance.
- **Use a typed-token form with a different shape** (e.g., `<namespace>/<id>` or `<namespace>::<id>`). Considered. The bracketed form `[<namespace>:<id>]` was chosen because the brackets visually delimit the reference from surrounding text and the form is greppable without escaping for shell/regex consumers.
- **Use absolute file paths instead of namespace stems.** Rejected — couples the reference shape to filesystem layout; a schema rename would require rewriting every reference.

## Implications

- **Existing schemas use the typed-token form in value positions only.** Value-position cross-schema references in the project-management capability (workflow → issue-types, classification → issue-types, git-conventions → issue-types and validation-severity, body-format → validation-severity, time-containers → validation-severity) carry `[<namespace>:<id>]`. Intra-schema value-position references (workflow's `transitions.from/to` referencing states defined in the same file) stay bare. All mapping keys stay bare; key-position cross-namespace membership is declared via the `x-pkit-keys-from-namespace` annotation on the parent field's JSON Schema (`body-format.yaml`'s `issues` and `titles.yaml`'s `issues` each have their companion's `issues` field annotated with `x-pkit-keys-from-namespace: "issue-types"`).

- **JSON Schema companions add a shared `reference_token` `$defs` fragment.** A common regex (`^\[[a-z][a-z0-9-]*:[a-z][a-z0-9-]*\]$`) validates the token shape; per-namespace specialisations narrow the namespace half (`^\[issue-types:[a-z][a-z0-9-]*\]$`) where the field accepts only one target schema. The fragment lives in each companion's `$defs` until the schemas area earns a shared `$defs` file (deferred per COR-007).

- **The schemas area README narrows.** The "either bare or typed-token" wording in the cross-schema reference section is replaced with the typed-token convention; the bare-id form documents as the *intra-schema* form only.

- **Cross-file resolution becomes a uniform validator concern.** A future extension to `pkit schemas validate` parses every `[<namespace>:<id>]` token, locates the target schema, and confirms the id exists. The same resolver handles every cross-schema reference across every adopter — no per-field logic for "what schema does this field reference."

- **Adopter projects (e.g., example-adopter) and future capabilities inherit the convention.** A capability author writing a new schema, or an adopter authoring schemas for project-specific data, follows the same form. The ecosystem has one expected reference shape.

- **No migration framework entry needed.** The change is a one-time edit of the existing schemas in this repo; adopter projects pulling the schemas mechanism for the first time start on the typed-token form directly. The schemas area's documentation update is the only kit-shipped change downstream of this record.
