
# Adding an evidence record

This skill walks through capturing a new fact into the **evidence** capability's per-scope `evidence.yaml`, so prose can cite it via the `[ev:<slug>]` token (per COR-017's capability-author skill / pairing rule).

## When this skill applies

Use it before — or while — writing prose that asserts an external fact:

- A rate limit, license term, version policy, SLA, regulatory threshold, or vendor commitment that depends on a source outside the model's training.
- A claim copied from a web page, API response, or PDF where the author would otherwise paraphrase from memory.

Skip it for:

- Pure framing prose ("this section explains X") that doesn't assert external facts.
- Claims about the project's own internals (file paths, function signatures, decisions inside this repo — those are checked by `pkit refs validate`, not by evidence).

## Procedure

### 1. Identify the scope

The record lands in the **nearest `evidence.yaml` walking up the directory tree from the file you're writing.** If no `evidence.yaml` exists in any ancestor, create one at the right level — the level that scopes the work the record belongs to.

For any directory containing prose that makes external-fact claims, the file lives at `<scope-dir>/evidence.yaml`. Each scope is independent; sibling directories with their own `evidence.yaml` files are validated separately. The placement *is* the scope declaration (per [evidence:DEC-002-evidence-record-schema]).

If the file doesn't exist:

```sh
mkdir -p <scope-dir>
cat > <scope-dir>/evidence.yaml <<'EOF'
# yaml-language-server: $schema=.pkit/capabilities/evidence/schemas/evidence-record.schema.json
pkit_schema: evidence:evidence-record
schema_version: 1
records: []
EOF
```

The first line is the IDE directive that YAML Language Server consumes for autocomplete + inline diagnostics. The `pkit_schema:` field binds the file to the `evidence-record` schema for `pkit data validate` (per [project-kit:COR-023]) — though the schema also declares a `binds_to:` fallback covering `evidence.yaml` at the repo root or one level deep, so the field is optional in those layouts and strictly required only for deeper-nested files outside the fallback's reach.

### 2. Pick a slug

Kebab-case, matching `^[a-z0-9][a-z0-9-]*$` (per [evidence:DEC-001-citation-discipline]). Describe the fact, not the source:

- Good: `api-rate-limit`, `vendor-sla-window`, `library-license-mit`.
- Bad: `wikipedia-1`, `source-3`, `note-from-friday`.

Slugs are scope-local — the same slug used in two unrelated scopes does not collide.

### 3. Capture the excerpt

Fetch the source. Copy the **verbatim** text that grounds the claim into the `excerpt:` field. Keep it minimal: enough to support the claim, not the entire page. Multi-line excerpts use YAML's block scalar (`|`):

```yaml
- id: api-rate-limit
  source_url: https://docs.example.com/api/limits
  fetched_at: 2026-05-18
  excerpt: |
    Each authenticated client may issue up to 1,000 requests per hour.
    Exceeding this returns HTTP 429 with a Retry-After header indicating
    the seconds until the next request will be accepted.
  title: Example API rate limit (authenticated)
  note: Anchors retry-loop and backoff design.
```

Required: `id`, `source_url`, `fetched_at`, `excerpt`. Optional: `title`, `note`. See [evidence:DEC-002-evidence-record-schema] for the full schema.

### 4. Append to `evidence.yaml`

Append the new record to the `records:` list. Keep records in chronological order of capture (newest at the bottom) — diffs stay clean and reviewers can read the file as an audit log.

### 5. Cite in prose

Write the claim with the inline token:

```
The API accepts up to 1,000 requests per hour per authenticated client [ev:api-rate-limit].
```

Repeat the token for multi-citation in one sentence:

```
The vendor guarantees 99.9% monthly uptime [ev:vendor-sla-window] with credits for excess downtime [ev:vendor-sla-credits].
```

#### Citing in non-prose files

The validator scans only `.md` and `.yaml` / `.yml` files (per [evidence:DEC-001-citation-discipline]'s placement rules). Put the token where the validator can see it:

- **YAML comment** — at the end of the line carrying the claim:
  ```yaml
  start: 2026-07-11  # Saturday [ev:trip-dates]
  ```
- **YAML human-prose field** — inside a `notes:` / `description:` block scalar, appended to the line (here `#` is literal text, not a comment):
  ```yaml
  notes: |
    Flights booked through the partner fare; refundable up to 24h before departure [ev:fare-rules].
  ```
- **Never in a machine-consumed value.** `region: us-east-1 [ev:region]` corrupts the value — every consumer now reads `us-east-1 [ev:region]`. Use a comment on that line instead.
- **Any other file type** (`.toml`, `.py`, `.json`, `.html`, …) is **not scanned** — a token there is silently unverified. Cite the claim in an adjacent `.md` or in the scope's YAML prose, and point at the data file from there. Strict JSON has no in-file convention; cite in sibling prose. (A dedicated mechanism is deferred per [project-kit:COR-007].)

### 6. Validate before committing

Run the validator against the scope:

```sh
.pkit/capabilities/evidence/scripts/validate.py <scope-dir>
```

A clean exit (`0`) means every citation in the scope resolves. A failure lists each cited-but-missing slug. Fix by either adding the record, fixing the slug typo, or removing the citation.

## Common shapes

- **The same fact serves multiple sentences.** One record, multiple citations of the same slug. The validator doesn't care how many times a slug is cited; it cares that every cite resolves.
- **Two sources for the same fact.** Two records (`api-rate-limit-docs` and `api-rate-limit-blog`), cited side-by-side in the sentence.
- **The fact came from an API, not a web page.** Same shape; `source_url` carries the endpoint, `excerpt:` carries the relevant JSON snippet verbatim.

## Variations

- **Backfilling citations on existing prose.** Run the validator first; it lists every cited-but-missing slug already in the file. Work through them — most of the slugs you'd choose are already implied by the existing prose's claims.
- **Removing a record.** Delete the entry from `evidence.yaml`. The next validator run flags any prose still citing the slug — fix the prose, then commit.
- **A claim that no public source supports.** That's not an evidence-capability fact. Either rephrase the claim as the project's own conclusion (no citation needed), or write a private working note and link to it as the source (with `source_url:` pointing at the in-repo file).
