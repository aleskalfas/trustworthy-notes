---
id: DEC-003
title: Validation rules — what the validator checks and when it fails
status: accepted
date: 2026-05-18
author: Ales Kalfas
---

## Context

[evidence:DEC-001-citation-discipline] established the citation convention; [evidence:DEC-002-evidence-record-schema] established the record format. A validator is what makes the chain auditable — without one, the convention rots silently as text drifts and records age out.

The validator runs against one scope at a time (per [evidence:DEC-002-evidence-record-schema]'s scope rule). Its contract has to settle three questions: what counts as a citation worth checking, what counts as a violation worth blocking, and what shape of failure to surface.

## Decision

### What the validator extracts

- **In-scope files:** `.md` and `.yaml` / `.yml` files anywhere under the scope's directory, **except** the scope's `evidence.yaml` itself (skipped wholesale).
- **Citation regex:** `\[ev:([a-z0-9][a-z0-9-]*)\]` — the exact form [evidence:DEC-001-citation-discipline] fixes.
- **Skip regions before regex — markdown files only:** fenced code blocks (` ``` … ``` ` and `~~~ … ~~~`) and HTML comments (`<!-- … -->`) are stripped from `.md` files before matching, so example tokens shown in documentation aren't counted as live citations. These are *markdown* constructs; **YAML files are scanned as raw text** — in YAML those characters are literal (e.g. inside a `notes: |` block scalar), so stripping them would silently drop real citations sitting inside or after such content.

Skipping `evidence.yaml` itself is load-bearing: excerpts in `evidence.yaml` may quote text containing `[ev:foo]`-shaped tokens (a regulation, a markdown snippet from a fetched page). Treating those as citations would force every excerpt's tokens to be authored as separate records — a false positive trap. The validator side-steps it by skipping the file entirely; citations are intended for adopter-authored prose, not for fields inside the evidence file. If an adopter needs to cite from a note about a record, the citation goes in sibling prose, not in `evidence.yaml`.

### What counts as a failure

| Finding | Severity | Exit |
|---|---|---|
| Cited slug has no record in scope's `evidence.yaml` | **error** | non-zero |
| Cited slug appears in scope's `evidence.yaml` | pass | — |
| Record exists in `evidence.yaml` but no citation references it (orphan) | soft (only under `--strict`) | non-zero under `--strict`; zero otherwise |
| `evidence.yaml` is malformed (YAML parse error, missing required field) | **error** | non-zero |
| Citation appears in a `.md` or `.yaml` file but no `evidence.yaml` exists in any ancestor scope | **error** | non-zero |

The first row is the integrity invariant this capability protects. The orphan check is soft because orphans are common during active authoring: a record is captured before the prose that cites it lands, or prose moves and leaves the record behind for a future cite. Forcing every orphan to break CI would create incentive to delete records before they're used — the opposite of what the discipline wants.

### Exit codes

- `0` — clean. Every citation resolved.
- `1` — at least one error finding. Stderr lists each finding with file, line, and slug.
- `2` — usage error (wrong arguments, missing scope path, etc.).

### Scope discovery

The validator takes one scope path per invocation. Multi-scope validation is shell-wrapped:

```sh
find . -name evidence.yaml -print | while read f; do
  evidence-validate "$(dirname "$f")"
done
```

A future enhancement might add a discovery walker to the validator itself; v1 keeps the per-scope contract simple.

## Rationale

Strip-before-regex is a single source of false positives in this discipline. Fenced code blocks are well-defined; HTML comments are well-defined; excerpts are isolated to a known YAML field. All three skip rules are mechanical and don't require natural-language judgement.

Hard-fail on cited-but-missing matches the invariant the capability exists to protect: every claim is grounded. Soft-by-default on orphans matches the realities of active authoring: a record being ahead of its citation is fine; a claim ahead of its record is the bug.

Per-scope rather than tree-wide keeps the validator's job small. Scopes are independent by construction (per [evidence:DEC-002-evidence-record-schema]); a tree-wide validator would have to invent a "current scope" concept that the placement convention already expresses.

### Alternatives considered

- **Re-fetch every excerpt at validation time.** Considered. Rejected for v1: too slow for routine validation; mixes "the citation chain is intact" with "the excerpt is still verifiable." A separate `retire.py` script (deferred) is the right home for that work.
- **Confidence tiers / reliability ranks.** Considered (the example-brownfield project has them). Rejected for v1: the citation discipline alone is the integrity guarantee. Tiers add a second decision per record without earning their keep in this capability's grounded cases.
- **Whole-tree default with `--scope <path>` flag.** Considered. Rejected: the default would have to invent scope resolution rules; the shell wrapper is one line.

## Implications

- The validator script ships at `scripts/validate.py` with PEP 723 inline metadata so adopters can run it via `uv run --script` without configuring a host project (per COR-017's "Scripts the capability ships" pattern).
- A future strict mode (`--strict`) elevates orphans to errors. The default mode stays lenient.
- Excerpt fidelity (does the text in `excerpt:` actually appear at `source_url`?) is out of scope for v1 — adding it requires HTTP fetches and content extraction that this validator deliberately avoids. A separate adapter (e.g., a Zotero adapter) could ship richer verification.
- Variants of this capability (`yaml-python` is v1's reference; future `sqlite`, `zotero`, or `bibtex` flavours per COR-017's variants note) re-implement this validation contract under their own storage shape. The wire-level contract here (cited-but-missing is hard; orphans are soft) is what they preserve.
