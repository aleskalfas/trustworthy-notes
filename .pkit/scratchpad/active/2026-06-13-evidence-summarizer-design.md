---
authors:
  - Aleš Kalfas <kalfas.ales@gmail.com>
started: 2026-06-13
---

# Evidence summarizer design

Live decision log + open questions for the evidence-based PDF summarizer. We
update this as we debate. Non-normative exploration (per COR-012); decisions
that firm up should crystallise into PRJ records.

## Goal

A CLI tool: input a PDF, output an **evidence-based** summary in a chosen format
(PDF default; also md/json). Every claim must be validable against the source.

## Decisions

- **Python-first, OS-agnostic** (macOS + Windows). No reliance on system binaries
  (poppler, pandoc) in the core path.
- **Tooling: `uv`** — same behaviour on both OSes, reproducible lockfile.
- **CLI: `typer`** — command `evsum`.
- **Extraction: `pdfplumber`** — MIT license, pure-Python, char-level bounding
  boxes (needed for evidence anchoring). Rejected pymupdf (AGPL) and pypdf
  (weak coordinates).
- **Wave-based pipeline**, each wave persists an artifact and is re-runnable:
  - Wave 0 ingest:      PDF -> pages (REAL, column-aware, footnotes split, DONE)
  - Wave 1 extract:     per-page concepts + evidence quotes (STUB)
  - Wave 2 link:        relate/merge concepts across pages (STUB)
  - Wave 3 synthesize:  compose summary (STUB)
  - Wave 4 validate:    re-check each quote against cited page (STUB)
  - Wave 5 export:      render to pdf/md/json (STUB)
- **Per-page extraction, not whole-doc-at-once** — the LLM reads ONE page at a
  time in Wave 1 and must cite a verbatim quote per idea.

## Open questions (to settle)

1. ~~Text layer vs OCR~~ **RESOLVED**: probe shows a clean text layer — 303
   pages, ~3076 chars/page avg, only 11 low-text pages (figure/plate pages:
   5,7,12,13,76,143,145,167,169,263,303). `needs_ocr_likely=False`. pdfplumber
   alone is sufficient; OCR deferred to an optional fallback for low-text pages.
2. **PDF export library**: needs to be pure-Python/cross-platform. Candidates:
   `reportlab` (BSD), `fpdf2` (LGPL). Avoid weasyprint (cairo/pango system deps).
3. **LLM integration**: which provider/SDK, how to keep it swappable, how to
   handle cost (per-page calls on a long book = many calls).
4. ~~Evidence granularity~~ **RESOLVED** (Wave 1 hand-simulation, see below):
   the `statement` may paraphrase; the `evidence.quote` is ALWAYS a verbatim
   span anchored by *normalized-substring containment* — never fuzzy/semantic.
   Paraphrase lives only in `statement`, never in a quote.
5. ~~Concept schema~~ **RESOLVED**: shape pinned in `models.py` + the golden
   fixture `tests/fixtures/concepts.p3.yaml`. See the simulation section below.
6. **Page numbering offset**: PDF page index != printed page label. PDF page 3
   is the ISBN/copyright page. Evidence citations must disambiguate (e.g.
   "printed p.3 = PDF page N"). Page-label detector built; doc-wide map TODO.

## Manual walkthrough notes

### CRITICAL FINDING (PDF page 14 = printed p.3)

- **Page-offset confirmed**: printed p.3 == PDF page 14 (+11 offset). Front
  matter is roman; arabic starts at Chapter 1.
- **Two-column layout breaks naive extraction**: `page.extract_text()` zippers
  the left and right columns line-by-line into scrambled prose (e.g. the "1.1"
  heading is interleaved with body text from the right column). This is FATAL
  for evidence anchoring: quotes are non-contiguous, meaning is corrupted, and
  it fails SILENTLY (char count looks normal).

### Decision: Wave 0 must be COLUMN-AWARE before Wave 1 is meaningful

- Detect column count / gutter per page (crossing-count argmin in central band).
  Extract each column region in reading order, then concatenate.
- Footnotes (the "1 Robins (1993)" block at page bottom) captured as a distinct
  stream, not inlined into prose.
- Page numbers in footer ("3") stripped from body text but USED to build the
  printed-label -> PDF-index map.

### Column-aware extraction — DONE (verified on PDF p14)

Implemented in `src/summarizer/ingest.py` (~100 lines, all inspectable):
- `_detect_gutter`: crossing-count argmin in central band → robust to full-width
  titles crossing the centre.
- `_lines` + `_footnote_top`: line-median font size, walk up from bottom,
  skip the page-label line. Computed PER COLUMN (each column has its own
  footnote block at a different y).
- `_extract_column`: crop body above fn_top, footnotes below, per column.
- `_page_label` / `_strip_label_lines`: read + remove the printed page number.

Result on p14: body in correct reading order; all 12 footnotes cleanly split;
label '3' captured. Known minor artifact: a trailing superscript ref marker
('1') leaks to body end — normalize later.

### Remaining ingest TODO (not blocking Wave 1 trial)
- Normalize superscript footnote-reference markers in body.
- Build the printed-label -> PDF-index map across the whole doc.
- Decide character-offset anchoring strategy now that text is contiguous.

### Wave 1 hand-simulation on printed p.3 (PDF p14) — DONE

Hand-extracted the full page by reading the clean ingest output, then wrote the
result as a golden fixture `tests/fixtures/concepts.p3.yaml` (14 concepts, 26
evidence quotes). A verification harness confirmed **every** evidence quote
anchors against the real ingest output via `summarizer.normalize`
(`concepts=14  evidence: ok=26 miss=0`), and the YAML round-trips into the
`Concept`/`Evidence` dataclasses. This is now the regression fixture for the
future Wave 1 extractor.

Resolved open questions:

1. **Concept granularity.** One discrete, independently-checkable assertion =
   one concept. A paragraph usually carries several (§1.1 yielded 6). The
   exception is an explicit enumeration that *jointly defines a single thing*:
   §1.2's six-bullet investigation list is kept as ONE `kind: scope` concept
   whose evidence is the verbatim list, not six siblings. Heuristic for the
   extractor: "one assertion = one concept; an enumeration defining one thing =
   one concept carrying the list."

2. **Evidence anchoring (the big one).** The `statement` paraphrases; the
   `evidence.quote` is a verbatim span confirmed by *normalized-substring
   containment*. Normalization (`summarizer.normalize.normalize_for_match`,
   applied identically to needle and haystack, idempotent) absorbs three real
   artifacts the simulation surfaced in pdfplumber output:
     - soft-wrap newlines → collapse all whitespace to single spaces;
     - PUA bullet glyphs (the list bullet is **U+F0B7**) → drop;
     - superscript footnote-ref markers glued to a word ("Robins1", "Egypt10",
       measured at ~6.5pt vs 10pt body, raised baseline, separate small-font
       words) → strip a 1-2 digit run glued to a letter at a token boundary.
       This is narrow by construction so real numbers survive ("(1993)",
       "P. BM 1", "1.1"). PRIMARY fix still belongs upstream in ingest (it alone
       has font/baseline data); the matcher rule is defense-in-depth.

3. **Footnotes: supporting evidence, not first-class concepts.** On p.3 every
   footnote is either a bibliographic ref (fn 1-5 backing the §1.3 studies
   claim) or a substantive example/attribution (fn 9 example; fn 11/12 attribute
   the Bryant/Johnson quotes). Modelled as `Evidence(source="footnote",
   locator="<n>")` attached to the body concept they support, validated against
   the footnotes stream. A footnote becomes its own concept only if it asserts
   something the body does not — none did here. Reported claims the author sets
   in quotation marks get `kind: reported-claim` (the body quote is itself
   verbatim; the footnote is its source).

4. **Concept schema.** `id` (page-scoped slug `p3-NN`), `statement`, `section`,
   `kind` (claim|aim|scope|reported-claim), `page_index` + `page_label`,
   `evidence[]`, `related[]` (Wave 2), `tags[]`. Persisted YAML is wrapped
   (`schema_version` + `page:` block + `concepts:` list), echoing the evidence
   capability's wrapped-record convention.

Cross-page finding: p.3 ends mid-sentence ("Gee ... P. BM 1"); the trailing "1"
is the known superscript leak. Left unextracted on purpose — demonstrates the
cross-page-stitching need (a page-overlap read in Wave 1, or a merge in Wave 2).

### Relationship to the installed `evidence` pkit capability

Reviewed it (DEC-001/002/003 + schema). It is a **methodology tool for this
repo's own docs** — external facts as `evidence.yaml` records cited by
`[ev:<slug>]` tokens, with a validator that checks the citation chain but, per
[evidence:DEC-003], deliberately does NOT re-verify excerpt fidelity (too slow;
mixes concerns). It is NOT a runtime library for the summarizer. But the model
maps onto ours and hands us one sharp lever: it separates "chain intact" (cheap)
from "excerpt faithful" (deferred). Our Wave 4 can do what it defers — our
source (the extracted pages) is local, so we re-check every quote by
containment. Our `normalize.quote_is_anchored` is that check.

(Next: write the Wave 1 extractor against this fixture — per-page LLM call,
schema-constrained output, then assert anchoring with `normalize`. Also lift
the superscript strip into ingest for clean exports, and build the doc-wide
printed-label -> PDF-index map.)
