# evidence capability

A lightweight citation discipline for projects that make factual claims grounded in external sources. Every factual claim in adopter-authored text carries an inline `[ev:slug]` token; every slug resolves to a record in a per-directory `evidence.yaml` carrying the verbatim excerpt and source pointer. A validator script enforces the chain.

Install this capability when:

- The project makes claims about external facts (dates, prices, locations, regulations, vendor terms).
- You want a lightweight grounding discipline rather than a heavyweight evidence-management system (confidence tiers, anchored ratings, second-agent verification).
- You'd benefit from a CI-friendly validator that fails on cited-but-missing slugs.

Skip it for projects whose claims are about their own internals — `pkit refs validate` already covers those.

## What this capability ships

`pkit capabilities install evidence` copies the following into the adopter's `.pkit/capabilities/evidence/`:

- `decisions/DEC-001-citation-discipline.md` — the `[ev:slug]` token convention and slug grammar.
- `decisions/DEC-002-evidence-record-schema.md` — the per-directory `evidence.yaml` shape with `schema_version: 1`.
- `decisions/DEC-003-validation-model.md` — the validator's contract (what's checked, what fails, exit codes).
- `skills/evidence-add.md` — walks an author through capturing a new record and citing it in prose.
- `skills/evidence-validate.md` — walks an author through running the validator and resolving findings.
- `scripts/validate.py` — the validator. PEP 723 self-contained Python script. Surfaces as `pkit evidence validate` per the capability-command-dispatch convention (per COR-021).

## Adopter setup

Install:

```
pkit capabilities install evidence
```

After install, create an `evidence.yaml` at each scope where you'll make external-fact claims:

```yaml
schema_version: 1
records: []
```

Author the first record using the `evidence-add` skill, cite it in prose with `[ev:<slug>]`, and run the validator:

```
pkit evidence validate <scope-dir>
```

The validator also remains invocable by direct path (`.pkit/capabilities/evidence/scripts/validate.py <scope-dir>`) for adopters whose kit predates COR-021's dispatcher; the `pkit evidence validate` form is the canonical invocation from v0.3.0 onward.

Wire the validator into a pre-commit hook or CI job once the discipline lands.

## Citing this capability's decisions

Inside this capability's own content (and from any other kit-shipped or adopter content referencing the discipline), cite decisions by their filename stem:

```
[evidence:DEC-001-citation-discipline]
[evidence:DEC-002-evidence-record-schema]
[evidence:DEC-003-validation-model]
```

This is the COR-017 citation form. `pkit refs validate` walks the capability's subtree and resolves each citation.

## Dependencies

- **Backbone:** `>=1.26.0,<2.0.0`. The capability install/sync/upgrade mechanics depend on COR-017's runtime; the `pkit evidence validate` invocation depends on COR-021's capability-command dispatch landing in backbone v1.26.0.
- **uv** on the adopter's PATH to run the validator's PEP 723 self-contained script. The first invocation installs the script's dependencies transparently.
- No external accounts or services. The discipline is entirely local-file-based in this reference implementation.

## Variants

This capability ships a single reference implementation (`yaml-python` style: per-directory `evidence.yaml` + Python validator). Plausible future variants — covered by COR-017's variants note — include:

- A `sqlite` variant: SQLite-backed store, single file per project.
- A `zotero` variant: integrates with a Zotero library.
- A `bibtex` variant: BibTeX-style records.

These will land when an adopter case forces the second flavour, per COR-007's recurrence rule.
