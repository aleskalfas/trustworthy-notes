
# Distilling schemas from an upstream methodology

This skill walks through producing **schemas from a pre-existing methodology specification**. The classic case: a separate decision corpus (METs, RFCs, design docs, standards) defines an engine-supportable discipline; a capability needs that discipline as runtime data; the schemas are the bridge.

For authoring schemas from scratch (no upstream source), use `schema-author` directly. For adding entries to an existing schema, use `schema-extend`.

## Acceptance gate (run first)

- **COR-008** — git workflow conventions.
- **COR-017** — capability pattern. The schemas being distilled land inside a capability.
- **COR-018** — capabilities adopt the schemas mechanism. The mechanism this skill produces output for.
- **COR-019** — schema reference form. Cross-schema references in distilled output use the token form.

Halt if any is `proposed` or `superseded`.

## What distillation is (and isn't)

**Distillation** = identifying the engine-consumable subset of a methodology spec and encoding it as schemas. The upstream spec carries both **principles** (qualitative — when to apply, why, alternatives) and **data** (quantitative / structural — enumerations, regexes, transitions, mappings). Distillation separates the two:

- Principles stay as prose, often as decision records (DECs) that cite the upstream source.
- Data becomes schemas, with the upstream lineage captured in each YAML's `source:` block.

Distillation is **not** wholesale import. Not every line of the upstream spec belongs in a schema. Lines that name a single concrete rule (an enumeration, a state transition, a regex) distill cleanly; lines that describe rationale, edge-case judgment, or how-to-apply do not.

## Procedure

### 1. Identify the upstream source

Pin the source by:

- **Project / corpus name** (e.g., `pm-workflow`).
- **Exact commit SHA** of the version you're distilling from. This gets captured in every schema's `source.commit` field so future readers can diff the upstream to see what changed.
- **Decision / spec identifiers** within the corpus (e.g., `MET-003`, `MET-004`, ...). Each schema's `source.decisions` list names the upstream records it distills.

Confirm the upstream is in a known-good state — typically the main branch or a tagged release. Avoid distilling from work-in-progress branches; the upstream might change underneath you.

### 2. Read the upstream end-to-end

Before drafting any schemas, read the entire upstream corpus once. Aim to internalise:

- The methodology's overall shape — what concepts it names, what relationships hold among them.
- Which records carry **principles** (qualitative) vs **data** (engine-consumable rules).
- How records reference each other — the corpus's internal graph.

This first-pass reading is the most important step. Distilling without it produces schemas that fragment the methodology along the wrong seams.

### 3. Identify the engine-consumable rules

For each upstream record, mark which content is engine-consumable. Useful patterns:

- **Enumerations.** "Each issue is one of {epic, feature, umbrella, task}." → an `issue-types` schema.
- **State machines.** "Issues move todo → backlog → in-progress → review → done." → a `workflow` schema.
- **Regexes.** "Branch names match `<type>/<issue-number>-<slug>`." → a `git-conventions` schema with the pattern.
- **Mapping tables.** "Type label `type:feature` ↔ Conventional Commits prefix `feat`." → a `classification` schema.
- **Field shapes.** "Every Task body has `## What` and `## Acceptance criteria` sections." → a `body-format` schema.
- **Tagged rules.** "Title regex mismatch is hard-reject; section absence is warning." → severity tags in each rule + a `validation-severity` schema with severity definitions.

Content that's prose-only (rationale, when-to-apply judgment, edge cases): leaves no schema footprint. Keep it in DECs.

### 4. Decide schema boundaries

Group engine-consumable rules into schemas. The boundaries follow the methodology's natural grain — not the upstream record numbering.

Each schema should:

- **Own one namespace** with a coherent set of entries. `issue-types` owns the issue-type vocabulary; `validation-severity` owns the severity vocabulary; etc.
- **Be small enough to read end-to-end** (~50–200 lines of YAML is comfortable; larger means probably two schemas).
- **Cross-reference rather than duplicate.** A rule that needs to name a severity references `[validation-severity:<id>]` rather than restating the severity behavior.

Decide which schemas the methodology needs before stamping any. Sketch the list:

```
- issue-types        (the issue-type vocabulary)
- workflow           (state machine + transitions)
- titles             (title regex per surface)
- classification     (axes: type, priority, workstream)
- body-format        (per-issue-type body shape)
- git-conventions    (branch, PR body, merge, force-push policy)
- time-containers    (Milestone, Iteration; close triggers)
- validation-severity (the severity vocabulary the others tag against)
```

### 5. Order the stamping

Some schemas reference others (consumers ↔ owners). Stamp owners first so consumers can `$ref` their published narrowed patterns:

- **First:** `validation-severity` (owns the severity vocabulary; many consumers reference it).
- **First:** `issue-types` (owns the type vocabulary; many consumers reference it).
- **After:** consumers (`workflow`, `titles`, `body-format`, `classification`, `git-conventions`, `time-containers`).

Within each schema:

1. Stamp via `pkit new schema <capability> <name>` (or invoke `schema-author`).
2. Fill in the leading comment block — what the schema encodes, when each entry applies, what fields express.
3. Fill the `source:` block with upstream lineage:
   ```yaml
   source:
     upstream: <project-name>
     commit: <40-char SHA>
     decisions: [<upstream-id>, ...]
     captured_at: <YYYY-MM-DD>
   ```
4. Declare the per-entry shape in the companion's `$defs.entry.properties`.
5. (If consumers will reference this namespace) publish a narrowed `<name>_ref` in the companion's `$defs`.
6. Add entries via `pkit schemas add` — one per upstream-defined entry.
7. Validate via `pkit schemas validate`.

### 6. Cite cross-schema references

When an entry's field references an id in another namespace, use the typed-token form per COR-019:

```yaml
validation:
  - id: branch-pattern-mismatch
    severity: "[validation-severity:hard-reject]"  # cross-schema reference
    description: ...
```

When the field is a mapping key whose membership is constrained by another namespace, the companion declares the source via `x-pkit-keys-from-namespace`:

```json
"issues": {
  "type": "object",
  "x-pkit-keys-from-namespace": "issue-types",
  "patternProperties": { "^[a-z][a-z0-9-]*$": ... }
}
```

The resolver pass walks both forms — see the schemas area README's "What the resolver pass checks" section.

### 7. Capture qualitative content as DECs (not schemas)

Each upstream record that carried both data and principles produces:

- **One or more schemas** with the data (this skill's output).
- **One or more DECs** with the principles (cited via `source.decisions` from the schemas).

Author the DECs separately using `decision-author`. The DECs explain *why* the schemas encode what they do; the schemas carry the *what*. Both link back to the upstream record so future readers can follow the lineage in either direction.

### 8. Validate the end-to-end lineage

After every schema is stamped + populated:

```
pkit schemas validate          # shape + resolver passes clean
pkit schemas list              # all expected schemas present, each with the right entry count
```

For each schema, manually verify the `source:` block is accurate:

- The commit SHA matches the upstream commit you distilled from.
- The `decisions:` list names every upstream record that contributed.
- The `captured_at:` date matches when you finished the distillation.

### 9. Commit

Per COR-008, conventional-commits format. Distillation usually lands as one PR with multiple commits — one per schema (or one per logical group):

```
feat(<capability>): distill <namespace> from <upstream>

<body — 1–2 paragraphs naming what the schema encodes, which upstream
records it distills, and any non-obvious choices made during the
distillation (boundary decisions, field-shape choices).>

Source: <upstream-name>@<short-SHA>
Decisions: <list of upstream ids>
```

Order commits so each is independently buildable: owner schemas first, consumers second. Reviewers can step through the distillation incrementally.

## Variations

- **Distilling from an upstream that's still evolving.** Pin to a specific commit; treat that as your immutable input. When the upstream evolves, re-run the distillation against the new commit (`pkit schemas rename` for renames, `schema-extend` for new entries, `schema-author` for new namespaces) and bump each schema's `source.commit` + `captured_at`.

- **Distilling content that doesn't fit any single namespace.** When upstream describes a discipline that spans multiple namespaces (e.g., a single MET defines both a state and the severity tag for its validation), split into one schema per concept. Cite the same upstream record in each schema's `source.decisions`.

- **Distilling without an explicit upstream commit** (the spec lives only in a person's head or in a non-version-controlled medium). The `source:` block is optional; omit it when the schema is the source of truth. Document the methodology origin in the schema's leading comment instead.

- **Distilling and finding the upstream is unclear.** Pause and clarify upstream first. Distilling under-specified rules into schemas freezes the ambiguity; the schemas become the spec. Better to surface ambiguity for upstream resolution than to encode a guess.
