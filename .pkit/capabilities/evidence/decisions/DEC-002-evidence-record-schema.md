---
id: DEC-002
title: Evidence records live in per-directory `evidence.yaml` files with a fixed schema
status: accepted
date: 2026-05-18
author: Ales Kalfas
---

## Context

[evidence:DEC-001-citation-discipline] requires every `[ev:slug]` token to resolve to a record. That record needs a storage format, a location convention, and a schema. Three constraints shape the choice:

- **Excerpts are typically multi-line.** A web page paragraph, an API response body, or a quoted regulation runs across line breaks. The format has to keep them readable in source.
- **Records evolve over time.** Fields will be added; existing records must keep parsing.
- **Scope is per-content-area.** Facts about one area of the project should not pollute another area's namespace in the same repo. The storage location has to express scope.

## Decision

### File location

Records live in **`evidence.yaml`** files placed at the root of each scope. A scope is "the directory containing this file, plus its sub-tree." Files are discovered by walking the project tree; no central registry.

The placement *is* the scope declaration. An `evidence.yaml` at any directory validates everything under it; a second `evidence.yaml` deeper in the tree or in a sibling directory establishes its own scope. The two sets do not collide — each scope is checked independently.

### File format

YAML, with a wrapped (mapping) top-level shape carrying `schema_version` and a `records:` list:

```yaml
schema_version: 1
records:
  - id: api-rate-limit
    source_url: https://docs.example.com/api/limits
    fetched_at: 2026-05-17
    excerpt: |
      Each authenticated client may issue up to 1,000 requests per hour.
      Exceeding this returns HTTP 429 with a Retry-After header indicating
      the seconds until the next request will be accepted.
    title: Example API rate limit (authenticated)
    note: Anchors retry-loop and backoff design.
```

### Required fields

- `id` (string) — the slug, matching the citation token's `[ev:slug]` form.
- `source_url` (string) — pointer to where the excerpt came from. URL is the common case; non-URL identifiers (filesystem paths, API endpoint descriptions) are accepted in v1.
- `fetched_at` (date or datetime) — ISO 8601 date (`YYYY-MM-DD`) or full timestamp. Records when the excerpt was captured, not when the underlying fact was true.
- `excerpt` (string) — the verbatim text from the source that grounds the claim. Multi-line via YAML's `|` block scalar. The validator does NOT re-fetch or re-verify excerpts; they are accepted as captured.

### Optional fields

- `title` (string) — human-readable label.
- `note` (string) — what the fact is about, free-form.

### Schema versioning

The top-level `schema_version: 1` field carries forward. A future schema change (renamed field, new required field) bumps the version. Records pre-dating the bump remain readable; the validator migrates or rejects per the new version's rules.

## Rationale

**YAML over JSON.** Excerpts are multi-line. YAML's `|` block scalar preserves newlines and indentation without escape sequences. JSON would force `\n`-escaped strings that are unreadable in diffs.

**Wrapped over bare-list.** A bare `records:` list at top level loses the schema version. Three lines of overhead (`schema_version`, `records`, indented entries) buys explicit evolution.

**Per-directory placement over central registry.** A central `.pkit/evidence/records.yaml` scales poorly: a single file accumulating every project's records, with every area / thread / topic fighting for slug uniqueness. Per-directory placement scopes uniqueness naturally — the same slug used in two unrelated scopes does not collide, and the placement is self-documenting about which area the fact belongs to.

**No required `excerpt` length.** A single-line URL response or a multi-paragraph regulation are both legitimate. The discipline is "the verbatim text grounding the claim," not "≥N words."

### Alternatives considered

- **SQLite database.** Considered. Rejected for v1: not human-readable in diffs; requires a tool to inspect; adds a runtime dependency. May become an alternative adapter implementation later (per COR-017's variants note in `[evidence:DEC-003-validation-model]`'s Implications).
- **BibTeX format.** Considered. BibTeX targets academic citations; its fields (author, journal, year, volume) are awkward for web pages, API responses, or filesystem paths. Reuses none of the kit's existing conventions either.
- **Per-fact files (`evidence/<slug>.yaml`).** Considered. Rejected: more files to maintain, more git churn per addition, more cognitive overhead for the author. A single per-scope file with multiple records is a better fit at this granularity.

## Implications

- The validator's parser is fixed by this schema. Changes to field names or required-vs-optional bump `schema_version`.
- A scope can shadow a parent scope by introducing its own `evidence.yaml`. The validator runs per-scope; cross-scope citation is not supported in v1 (a citation in scope A whose record lives in scope B would fail validation). If cross-scope sharing becomes a need, a future record-level `imports:` clause is the migration path.
- The `excerpt` field's faithfulness is the author's discipline, not the validator's check. The validator confirms the citation chain; the human confirms the excerpt matches the source.
