---
authors:
  - Aleš Kalfas <kalfas.ales@gmail.com>
started: 2026-06-13
---

# Session handoff — trustworthy-notes

Continuation note for resuming the evidence-based PDF summarizer in a fresh
session. This repo was copied from `../summarizer` (the original prototype);
`.git` and `.venv` were not copied — run `uv sync` to rebuild the environment.

## What this project is

A CLI tool: input a PDF, output an **evidence-based** summary in a chosen format
(PDF default; also md/json). Every claim must be validable against the source
via a verifiable anchor (page + verbatim quote) and a validation pass.

## Where to read the design

- **`.pkit/scratchpad/active/2026-06-13-evidence-summarizer-design.md`** — the
  full decision log: tooling choices, the wave pipeline, and the column-aware
  ingest work. Read this first.
- **`.pkit/scratchpad/active/2026-06-13-pkit-sandbox-uv-sync.md`** — an
  escalation note for the project-kit repo (pkit panics under a sandbox via
  uv's proxy probe). Not about the summarizer itself; carried over for upstream.

## Current state (what works)

- **Wave 0 ingest — DONE and verified.** `src/summarizer/ingest.py` does
  column-aware extraction: detects the gutter, extracts each column in reading
  order, splits the footnote block into its own stream, and reads the printed
  page label. Verified clean on PDF page 14 (= printed p.3) of the test book.
- **CLI scaffold** — `evsum` (typer). Two commands:
  - `evsum probe INPUT.pdf [--page N]` — runs ingest only; prints the text-layer
    report and, with `--page`, that page's body + footnotes + label.
  - `evsum summarize INPUT.pdf [--format pdf|md|json] [--out] [--dest] [--model]`
    — full pipeline entry point; waves 1+ are stubs.
- **Data structures** — `src/summarizer/models.py` (PageText, Evidence, Concept,
  Summary). Serialization-friendly for per-wave YAML/JSON artifacts.
- **Pipeline skeleton** — `src/summarizer/pipeline.py`; waves 1–5 raise
  NotImplementedError with design-intent docstrings.

## How to run

- `uv sync` — rebuild the venv (not copied).
- `uv run evsum probe data/<the>.pdf --page 14` — see clean ingest output.
- Test fixture PDF is gitignored (copyrighted). Place a PDF under `data/` locally.

## Stack decisions (see design note for rationale)

- Python-first, OS-agnostic (macOS + Windows); no system binaries in core path.
- `uv` tooling; `typer` CLI; `pdfplumber` (MIT) extraction with char coordinates.
- Wave pipeline, each wave persists an artifact and is independently re-runnable.
- LLM reads ONE page at a time in Wave 1 and must cite a verbatim quote per idea.

## Wave 1 hand-simulation — DONE (this session)

Hand-extracted printed p.3 into a golden fixture and pinned the schema. All four
open questions are resolved; see the design note's "Wave 1 hand-simulation"
section for the full rationale. Landed this session:

- **`tests/fixtures/concepts.p3.yaml`** — 14 concepts, 26 verbatim evidence
  quotes, hand-extracted. The regression fixture for the future extractor.
- **`src/summarizer/normalize.py`** — the evidence-anchoring contract:
  `statement` paraphrases; `evidence.quote` is verbatim, confirmed by
  *normalized-substring containment*. Normalization collapses soft-wrap
  newlines, drops PUA bullet glyphs (U+F0B7), and strips glued superscript
  footnote markers ("Robins1") narrowly enough that real numbers survive.
- **`src/summarizer/models.py`** — Evidence gained `source` ("body"/"footnote")
  + `locator`; Concept gained `section`, `kind`, `page_label`. Footnotes are
  supporting evidence on the body concept, not first-class concepts.
- **`tests/`** — pytest added (dev group). 13 tests pass: `test_normalize.py`
  (no PDF needed) + `test_fixture_anchoring.py` (skips when `data/*.pdf` absent).
  Run with `uv run pytest`.

Reviewed the installed `evidence` pkit capability: it's a docs-citation tool for
THIS repo, not a runtime lib — but it confirmed our Wave 4 design (re-check every
quote by containment, which it deliberately defers). See design note.

## NEXT STEP (where we stopped)

**Write the Wave 1 extractor** (`pipeline.run_extract`) against the golden
fixture: per-page LLM call, schema-constrained output (the `concepts.yaml`
shape), then assert each quote with `normalize.quote_is_anchored` and DROP or
flag any concept whose evidence fails to anchor. Decide the LLM provider/SDK
(open question 3 in the design note — keep it swappable; per-page calls on a
303-page book is the cost concern). The fixture is the acceptance target.

## Known minor issues / TODO

- Ingest: superscript footnote-ref markers leak into body text glued to words
  ("Robins1", "Egypt10"). MEASURED this session: they are separate words at
  ~6.5pt vs 10pt body, on a raised baseline. `normalize.py` now strips them for
  *matching* (defense-in-depth), but the PRIMARY fix belongs in ingest's body
  extraction (filter small + raised digit words) so *exported* text is clean
  too. Beware regressing the verified column extraction when reworking it.
- Build a doc-wide printed-label -> PDF-index map (label detector exists).
- Decide character-offset anchoring strategy now that text is contiguous.
- Rebrand done: package `trustworthy-notes`, command `tn`, repo `trustworthy-notes`.
- The `evidence` pkit capability is installed and looks directly relevant to the
  evidence/validation goal — review it when designing Waves 1 and 4.

## Repo hygiene notes

- `.gitignore` added: ignores `.venv/`, caches, and `data/*.pdf` (copyrighted
  test material kept local). Drop the PDF line for PDFs you own.
- Nothing committed yet in this repo — first commit is the next session's call.
