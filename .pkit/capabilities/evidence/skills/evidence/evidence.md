---
name: evidence
description: Work with the evidence capability — capture new external facts as evidence records (so prose can cite them via `[ev:<slug>]`), or validate that every citation in a scope resolves to a record. Composite skill per COR-020; dispatches to per-operation sub-procedures.
composes:
  - add.md
  - validate.md
gates:
  - COR-017
  - COR-020
reads:
  paths:
    - .pkit/capabilities/evidence/README.md
    - .pkit/capabilities/evidence/decisions/DEC-001-citation-discipline.md
    - .pkit/capabilities/evidence/decisions/DEC-002-evidence-record-schema.md
    - .pkit/capabilities/evidence/decisions/DEC-003-validation-model.md
    - .pkit/capabilities/evidence/scripts/validate.py
  records:
    - COR-008
---

# Working with evidence

This is the **evidence capability** authoring skill. It composes the two operations that share the evidence-record substrate — both work with the `evidence.yaml` records the capability defines, both use the `[ev:<slug>]` token convention, both gate on the evidence capability's installed state.

Pick the operation that fits the work:

| Operation | When to use it | Sub-procedure |
|---|---|---|
| **Add an evidence record** | A factual claim is about to land in adopter-authored prose and needs grounding in a source. Stamps a new entry in the relevant scope's `evidence.yaml`. | `add.md` |
| **Validate citations in a scope** | Before committing prose that asserts external facts, or as a CI gate. Confirms every `[ev:<slug>]` token resolves to a record. | `validate.md` |

If the user's request doesn't fit either operation, the skill doesn't apply — look elsewhere.

## Shared framing (applies to both operations)

### Acceptance gate

Verify the records in `gates:` are `accepted`:

- **COR-017** — capability pattern. Evidence is a capability per the kit's pattern; its installed state is the substrate the skill operates on.
- **COR-020** — skill family folder form. The convention this composite skill itself follows.

Halt if any is `proposed` or `superseded`.

### Conventions both operations respect

- **Citation token form.** Every cite is `[ev:<slug>]` where `<slug>` matches a record in the nearest enclosing `evidence.yaml` (per [evidence:DEC-001-citation-discipline]).
- **Per-scope `evidence.yaml`.** Each directory's evidence records live in its own `evidence.yaml`; nested scopes inherit + override per [evidence:DEC-002-evidence-record-schema].
- **Validator's contract.** `.pkit/capabilities/evidence/scripts/validate.py` is the source of truth for what counts as a valid citation; per [evidence:DEC-003-validation-model] the validator scans a scope, parses every token, resolves against the scope's `evidence.yaml`, and reports unresolved tokens.

### Routing to the sub-procedure

After confirming the gates + identifying which operation fits, read the matching sub-procedure file (one of `add.md`, `validate.md`) and follow its walkthrough. The shared framing above applies; the sub-procedure adds the operation-specific steps.

Each sub-procedure ends with a commit step using the conventional-commits format per COR-008.
