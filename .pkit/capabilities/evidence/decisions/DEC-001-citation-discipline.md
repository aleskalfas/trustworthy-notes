---
id: DEC-001
title: Cite every factual claim with `[ev:slug]`
status: accepted
date: 2026-05-18
author: Ales Kalfas
---

## Context

Project text routinely makes factual claims that depend on facts outside the model's training set: API rate limits, library license terms, regulatory thresholds, vendor SLAs, third-party version policies, hardware specifications. An LLM author confidently restating such facts from training data is the failure mode this capability exists to prevent — claims may be subtly wrong or outdated and the reader has no signal that the source needs checking.

The lightest discipline that prevents this is a citation convention. Every factual claim is tagged in prose with a token that points at a record; a record carries the verbatim excerpt and source pointer. Untagged prose is by-convention free of external facts. A reader (human or tool) seeing untagged text can trust the model's own framing; seeing a tag, they can chase the record.

## Decision

Every factual claim in adopter-authored text must be backed by an inline token:

```
[ev:<slug>]
```

`<slug>` is kebab-case, matching the regex `^[a-z0-9][a-z0-9-]*$`: starts with a letter or digit, lower-case letters / digits / hyphens, no trailing hyphen.

Multiple citations in a single sentence repeat the token: `... per [ev:foo] [ev:bar].` Comma-list syntax (`[ev:foo,bar]`) is rejected; it adds parser complexity without saving keystrokes.

A slug names a single atomic fact — one excerpt, one record. Multiple records may share a `source_url`; citations resolve to records, not URLs.

The token is metadata, not a rendered link. Rendering as a markdown footnote (`[^slug]`) was considered and rejected: it conflicts with actual markdown footnote semantics and would require a paired definition block per file, adding ceremony for no reader benefit.

### Placement across files

The token is plain text the validator finds by regex, so *where* it may sit is governed by one fact: the validator scans only `.md` and `.yaml` / `.yml` files, and strips fenced code blocks and HTML comments before matching (per [evidence:DEC-003-validation-model]). A citation must live where the validator can see it — otherwise the author believes a claim is verified when nothing checks it, the worst failure for an integrity discipline. Placement follows:

- **Markdown** — in the prose, immediately after the claim. Not inside a fenced code block (the validator strips those).
- **YAML** — in a `#` comment at the end of the line carrying the claim (`start: 2026-07-11  # [ev:trip-dates]`), or appended inside a **human-prose** string field — a `notes:` / `description:` block scalar — where `#` is literal text. **Never inside a machine-consumed value:** a token in `region: us-east-1 [ev:region-choice]` becomes part of the value every consumer reads, corrupting the data. Comments and prose fields only.
- **Any other file type** (`.toml`, `.py`, `.json`, `.html`, …) — the validator does not open it, so a token placed there is *silently unvalidated*. Cite the claim in **adjacent prose the validator scans** — a sibling `.md`, or a prose field in the scope's YAML — and reference the data file from there.

Formats with no inert-text region at all (notably strict JSON) get no token-in-file convention, for the same reason: the citation lives in adjacent scanned prose. A dedicated mechanism (a sibling citation file, or a reserved metadata key like `_evidence`) is **deferred** until a concrete need recurs (per [project-kit:COR-007]); one structured-file format having surfaced the question is not recurrence enough to design the mechanism.

## Rationale

A token-only form (no surrounding markup, no companion block) keeps the cost of citing close to zero — the threshold below which authors actually do it.

Kebab-case slugs match the rest of the kit's naming conventions (skill names, capability names, decision filename stems). Reusing the convention saves authors a separate slug-choice rule.

Repeating the token instead of a comma-list is uniform across one and many cases: the parser walks token instances, not token contents. A single regex extracts every citation without a special case for multi-citations.

### Alternatives considered

- **Markdown footnotes (`[^slug]` + `[^slug]: …` definition block)**: rejected. Markdown renderers interpret these; the rendered output disrupts the prose. The companion block also forces authors to maintain two files in lock-step instead of one (the prose + the `evidence.yaml`).
- **Comma-list syntax**: rejected. Saves one keystroke per multi-citation at the cost of a parser special case. Repetition is uniform.
- **Full URLs inline**: rejected. URLs in prose are noisy, hard to update, and don't carry an excerpt to ground the claim.

## Implications

- A validator extracts citation tokens from in-scope files and verifies each slug resolves to a record. See [evidence:DEC-003-validation-model] for the validator's contract.
- The record schema must carry an `id` field matching the slug, plus enough provenance metadata to make the citation auditable. See [evidence:DEC-002-evidence-record-schema] for the record shape.
- The token grammar is intentionally narrow. Future variants of this capability (a `bibtex` adapter, a `zotero` adapter) translate at install time; the prose convention stays uniform.
- Placement is governed by the validator's scan scope — see *Placement across files* above; the `evidence` `add` skill carries the quick-reference. A token-in-file mechanism for JSON-like formats is deferred per [project-kit:COR-007].
