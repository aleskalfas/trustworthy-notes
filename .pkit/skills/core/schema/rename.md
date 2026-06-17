
# Renaming an entry id

Rename one id within a namespace (e.g., the `feature` id in `issue-types` → `capability`). The CLI cascades the rename to every reference site: the namespace owner's collection, every value-position `[<namespace>:<old_id>]` typed token, every mapping-key reference in fields whose companion declares `x-pkit-keys-from-namespace: <namespace>`.

For renaming a whole **namespace** (the schema file itself), today's CLI doesn't support it directly — see Variations below.

## Acceptance gate (run first)

- **COR-008** — git workflow conventions. Used for the commit step.
- **COR-018** — capabilities adopt the schemas mechanism. Used to confirm the schema is one this skill should be modifying.
- **COR-019** — schema reference form. Used to know what kinds of references will be cascaded.

Halt if any is `proposed` or `superseded`.

## Procedure

### 1. Confirm the rename is what you want

A rename is a **non-trivial refactor**: every consumer of the namespace sees the new id; downstream prose, comments, and external docs may need follow-up. Before running, confirm:

- The new id is *better* than the old one (not just a synonym — communicates the concept more clearly).
- The namespace's downstream consumers can absorb the change (skills, agents, scripts that load the schema will see the new id at next runtime — but their *cached* references in prose may still reference the old name).
- The methodology spec, if any, has been (or will be) updated.

If unsure, pause and discuss with whoever owns the methodology.

### 2. Confirm the old id exists

```
pkit schemas show <namespace>
```

The old id must appear in the entry list. If it doesn't, you may be targeting the wrong namespace (run `pkit schemas list` to find which namespace owns the id) — or the id has already been renamed.

### 3. Pick the new id

Kebab-case (`^[a-z][a-z0-9-]*$`). Doesn't collide with another existing id in the same namespace. Communicates the entry's role precisely — that's the point of the rename.

### 4. Preview what will change

Two quick scans help understand the rename's scope:

```
grep -r "\[<namespace>:<old_id>\]" .pkit/capabilities/*/schemas/   # token sites
pkit schemas show <namespace>                                       # owner before
```

For annotation-key references, scan companions for `"x-pkit-keys-from-namespace": "<namespace>"` and check the corresponding YAML's mapping keys at those paths.

### 5. Run the rename

```
pkit schemas rename <namespace> <old_id> <new_id>
```

The command:

- Updates the namespace owner's collection (mapping form: rename the key; list form: update the `id:` field of the matching item).
- Walks every YAML under `.pkit/capabilities/*/schemas/` and replaces `[<namespace>:<old_id>]` with `[<namespace>:<new_id>]`.
- Walks every companion for `x-pkit-keys-from-namespace: <namespace>`; for each, renames the matching key in the corresponding YAML's mapping.
- Re-validates every affected file via the same shape + resolver passes `pkit schemas validate` runs.
- On any failure, restores every touched file to its prior state and reports the issue.

Reports a breakdown of changes:

```
Renamed 'feature' → 'capability' in namespace 'issue-types' (3 change(s)):
  [owner-key] .pkit/.../issue-types.yaml
    renamed 'feature' → 'capability' in namespace owner
  [annotation-key] .pkit/.../body-format.yaml
    renamed bare key 'feature' → 'capability' at /issues ...
  [annotation-key] .pkit/.../titles.yaml
    renamed bare key 'feature' → 'capability' at /issues ...
```

Refuses when the namespace doesn't exist, the old id isn't present, the new id collides, or the new id isn't kebab-case.

### 6. Confirm the result

```
pkit schemas validate
pkit schemas show <namespace>
```

Validate is clean; show lists the new id where the old one was.

### 7. Fix unrelated prose

The CLI catches *schema-mechanism* references (tokens + annotation-keys). Other places may still mention the old id:

- Skill / agent body prose (cite the new id; check via `grep` across `.pkit/`).
- Decision records (COR / DEC / MET / PRJ) that name the id.
- README files, comments inline in YAMLs, the methodology spec.

Walk these manually or via `git grep <old_id> -- .pkit/` and update each match. Most are prose-level — judgement call on which need updating (a historical reference in a closed decision may legitimately keep the old name).

### 8. Commit

Per COR-008, conventional-commits format:

```
refactor(<capability>): rename <namespace>/<old_id> to <new_id>

<body — 1–3 paragraphs naming why the rename clarifies the
methodology, what changed across the schemas mechanism, and what
prose / decision references were updated separately.>
```

For example:

```
refactor(project-management): rename issue-types/feature to capability

`feature` was overloaded with the Conventional-Commits `feat:` PR type
(see classification.yaml). Renaming the issue type to `capability`
disambiguates the two — issue types describe *what's delivered*, PR
types describe *what changed*.

Cascaded to body-format.yaml, titles.yaml (annotation-based keys),
plus prose references in: <list of touched files>.
```

## Variations

- **Renaming the namespace itself** (the schema file). Today's CLI doesn't support this in one step. Manually:
  1. `git mv <old_name>.yaml <new_name>.yaml`
  2. `git mv <old_name>.schema.json <new_name>.schema.json`
  3. Update `$id` in the companion: `<new_name>.schema.json`.
  4. Walk every YAML under capabilities; replace `[<old_name>:` with `[<new_name>:` (use `grep` + `sed`).
  5. Walk every companion; replace `x-pkit-keys-from-namespace: <old>` with `<new>`; replace cross-file `$ref` paths like `<old>.schema.json#/...` with `<new>.schema.json#/...`.
  6. `pkit schemas validate` to confirm.

  A future `pkit schemas rename-namespace` could automate this; not in v1.

- **Renaming an id where the change is just cosmetic** (e.g., `feature` → `Feature` for casing). Refuse — kebab-case is the convention; case changes that violate it surface as errors. Pick a kebab-case alternative or reconsider.

- **Renaming during a methodology distillation** (the upstream spec uses different naming than what landed in the schema). See `schema-distill` — the distillation skill establishes initial naming; this skill handles post-distillation refinements.
