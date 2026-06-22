# The floor-score harness (`tnotes eval`)

`tnotes eval` is a **maintainer instrument**: an offline yardstick that scores how
well a corpus of generated notes clears the **mechanical floor** (METHODOLOGY §7),
emitting a fingerprinted, reproducible number so a model/prompt change can be
judged a regression. It is hidden from the user-facing `--help` on purpose — it is
a development tool, not part of the reading workflow.

Read [ADR-007](architecture/decisions/ADR-007-faithfulness-score-is-an-instrument.md)
first. The binding rules it sets, applied here:

- **An instrument reading, never a gate.** No correctness decision depends on the
  number. `tnotes eval` never touches the pipeline (`cli → eval`, never
  `pipeline → eval`); `eval` reuses the *real* floor checks
  (`eval → validation`, `eval → normalize`) rather than a second copy of them.
- **Floor only; the judge is deferred.** This is the deterministic floor —
  verbatim-anchoring (§7.2), grounding (§7.1), referential integrity (§7.4),
  schema validity (§7.5). The stochastic LLM entailment judge ADR-007 describes is
  **not built** (building the naive form is the failure mode the ADR forbids).
- **A reading is only comparable next to its fingerprint.** Every score carries an
  instrument fingerprint: corpus id, a hash of the doc list, the timestamp, the
  tool/build version, and the floor counts (including the **completeness** counts).
  Change the instrument (the corpus, the build) and you cannot compare across runs.
- **The floor is completeness-aware.** Anchoring/grounding are computed only over the
  notes that *exist* — so a run that silently lost pages (extraction failed mid-sweep,
  stale notes left behind) could read a *higher, perfect* number for *less* of the
  document. The floor closes that trap: a corpus doc records which pages are
  **expected** to have notes, and `eval` reports expected against present. A doc
  missing any expected page is **incomplete** and can never read as a clean 100%.

## Run it

Point it at a corpus directory:

`uv run tnotes eval --corpus tests/fixtures/eval-smoke`

It prints a per-doc + aggregate floor-score report. Each doc row ends with a
**completeness** column — `notes <present>/<expected>` — and any doc that lost
expected pages shows them inline:

```
 anchored   grounded  excerpts   stmts  ref  schema      notes  doc
     100%       100%      18/18      24    0       0      7/15   some-document  MISSING [2, 3, 4, 11, 12, 17, 20, 21]
```

`MISSING` lists the page indices that were **expected to have notes but don't** —
failed or un-extracted pages (exactly what a tuning sweep with token-exhausted pages
produces). A corpus with any incomplete doc prints an `INCOMPLETE` banner and does
**not** read as a clean 100%, even when every note that *does* exist anchors verbatim.
That is the point: a stale or partial run cannot launder itself into a perfect score.

To save a comparable artifact:

`uv run tnotes eval --corpus tests/fixtures/eval-smoke --json /tmp/score.json`

The JSON is a small, stable, sorted shape carrying the fingerprint, so two runs
diff cleanly. To compare two runs, **check the fingerprints match first** (corpus
hash + tool version) — a number that improved under a *different* instrument is not
a real improvement. `tnotes eval-compare A.json B.json [...]` does this check for
you and prints a labelled delta table (see the sweep section below).

## Tuning the extraction defaults (the sweep)

The point of the yardstick is to settle *which settings* produce the best notes,
empirically, instead of guessing. The two levers the pipeline exposes are the
**model** and the reasoning **effort** (the one-command run defaults to Sonnet +
`effort=low`). Both can be overridden per run with flags, so you can regenerate a
corpus at each setting without touching config:

```
tnotes ./doc.pdf --effort low      --force
tnotes ./doc.pdf --effort medium   --force
tnotes ./doc.pdf --effort high     --force
tnotes ./doc.pdf --model claude-opus-4-6 --effort high --force
```

`--force` is essential — it regenerates the notes (otherwise finished stages are
reused and the setting change has no effect).

> **Watch for page failures at high effort.** On dense pages, high effort can make
> the model think past the per-page token budget (default 32000) and emit no JSON —
> those pages produce no notes (and keep any stale notes from a prior run). The
> completeness check surfaces this as `MISSING [...]`; the fix is to raise the
> budget with `--max-tokens 64000`. A run with MISSING pages is **not** a valid
> comparison point, even if the pages that *did* extract score 100%.

The procedure:

1. Pick a small fixed set of documents you know well (your private corpus).
2. For each setting, regenerate the notes with the flags above, then run
   `tnotes eval --corpus <dir> --json score-<setting>.json`.
3. Compare the **floor-scores** across settings — a worse setting often shows up
   mechanically (lower anchoring/grounding rates: the model invented or mangled
   quotes). Instead of diffing the JSONs by hand, run `eval-compare` to print a
   labelled delta table:

   `tnotes eval-compare score-low.json score-high.json --label low --label high`

   It lines the runs up as columns and shows the first→last Δ on each metric
   (rates as percentage points; counts on the numerator — e.g. statements 163 → 248
   reads `+85`). `--label` is optional; omitted, columns are labelled by filename
   stem. The table **leads with a comparability line**: `✓ same corpus` when every
   run shares one `corpus_hash`, or a loud `⚠ NOT COMPARABLE — different corpus`
   when they don't (a fingerprint mismatch means you compared *different documents*,
   not different settings — ADR-007). It also flags any **incomplete** run
   (`⚠ INCOMPLETE`), so a page-losing run can't look "better" for having
   fewer-but-cleaner notes.
4. The floor can't see *mischaracterization* (a real quote, wrongly described), so
   also apply the **spot-check rubric** below on a few pages per setting.
5. If a setting clearly wins on both, change the default (`DEFAULT_EFFORT` /
   `DEFAULT_MODEL` in `config.py`) and record the finding. A default change is a
   deliberate follow-up, justified by the sweep — not a guess.

Cost note: higher effort and Opus cost more per page; the sweep is a one-off
maintainer experiment, not something the end user runs.

## The corpus

A corpus is a directory of **document subfolders**. Each doc folder carries the
generated per-page notes plus the source page streams §7.2 anchors against:

```
corpus/
  some-document/
    source-pages.yaml         # source streams + expected-notes markers (see below)
    1-extract/
      page-0000.notes.yaml    # the generated notes (workspace layout)
      page-0001.notes.yaml
  another-document/
    ...
```

`source-pages.yaml` is a list of `{ page_index, text, footnotes, expected_notes }`:

- `text` / `footnotes` are the source streams the §7.2 traceability check anchors
  excerpts against. Keeping them beside the notes makes the corpus self-contained:
  `eval` needs no PDF and never calls back into the pipeline (the isolation ADR-007
  requires).
- `expected_notes: true/false` is the **completeness** marker — whether the page is
  expected to have notes (a *text* page; the pipeline extracts exactly those). `eval`
  compares the expected pages against the pages that actually have a notes file and
  flags any gap as MISSING.

**Backward compatibility.** `expected_notes` is optional. A `source-pages.yaml` with
**no** markers on any page (the older shape, e.g. the public smoke corpus) falls back
to "expected = the pages that have notes" — completeness is then trivially satisfied
and no false MISSING is fabricated. Only corpora captured by `tnotes eval add-doc`
(which writes the markers) get a real completeness check.

### Build a corpus doc — `tnotes eval add-doc`

The real corpus-build path. After running a document through the pipeline, capture the
whole generated doc into your corpus in one command:

`tnotes eval add-doc --doc data/Foo.pdf --corpus /path/to/your/eval-corpus`

(Omit `--corpus` to use your configured `eval_corpus_dir`.) It:

1. copies the doc's per-page notes into `<corpus>/Foo.pdf/1-extract/`, and
2. reads the source pages (via `ingest`, **cli-side**) and writes
   `<corpus>/Foo.pdf/source-pages.yaml` with the real `text`/`footnotes` *and* the
   `expected_notes` marker per page — so §7.2 anchoring is honest and the completeness
   check has its expected-page denominator.

Reading the source streams cli-side at capture time keeps `eval` itself
import-isolated from the pipeline (it scores the manifest the capture *wrote*; it never
re-reads a PDF — ADR-007). This supersedes the throwaway corpus-builder script.

If the document has expected pages with no notes (a failed/partial extraction),
`add-doc` says so immediately (`INCOMPLETE … MISSING [...]`) — re-extract those pages
before relying on the doc, or it will score as incomplete.

### The private real corpus

The real corpus is **verbatim copyrighted excerpts** — the most sensitive data the
tool handles — so it is **private, config-pointed, and never committed** (ADR-007
inherits ADR-003's privacy stance). Point at it once:

`tnotes config set-eval-corpus-dir /path/to/your/private/eval-corpus`

Then `tnotes eval` (no `--corpus`) scores it. The accepted consequence is that the
number is **deliberately not portable**: a contributor without your corpus can run
the harness on the smoke corpus but cannot reproduce *your* faithfulness number.
Onboarding a second maintainer means handing over the corpus out of band.

**Never commit a real corpus.** Only the public smoke corpus
(`tests/fixtures/eval-smoke/` — self-authored, non-copyrighted) ships, and it only
proves the harness runs.

## The human spot-check (the faithfulness layer the floor can't see)

The floor is deterministic and shippable, but it only checks *mechanics*: an excerpt
either appears verbatim in the source or it doesn't. It **cannot** see the failure
that matters most — a **real quote that the note then mischaracterizes**. The excerpt
anchors (so the floor is green), yet the statement built on it says something the
source does not. Catching that is a *judgement*, so it is the human's job
([ADR-007](architecture/decisions/ADR-007-faithfulness-score-is-an-instrument.md):
software assists, the human judges; no model/judge here). This is the §7.6 stance
applied to faithfulness.

Run this **after any model/prompt/effort change**, before trusting a floor delta.

### The rubric

Pick 3–5 pages whose source you can read (your own corpus pages are ideal). For each
page, open its notes (`<doc>.tnotes/1-extract/page-NNNN.notes.yaml`) beside the real
source page, and grade **each statement** into exactly one of:

- **faithful** — the statement says what the cited excerpt(s) actually say, no more.
- **mischaracterized** — the excerpt is real and anchors, but the statement **distorts,
  over-claims, or reverses** it (the failure the floor cannot see). This is the one to
  hunt for.
- **dropped-important** — a load-bearing claim on the page has **no statement at all**
  (the coverage gap §7.6 owns). Note the page; the floor won't flag an omission.

Tally `mischaracterized` and `dropped-important` per run. A change is a **faithfulness
regression** if those rise — even when the floor's anchored/grounded rates hold steady
or improve. The floor number and this tally are read **side by side**, never blended
(ADR-007): a green floor with rising mischaracterizations is still a regression.

### A worked example

Source page says:

> The harbour board converted the lamp to paraffin in 1890, *after rejecting an
> earlier proposal to electrify it.*

Notes for that page:

```yaml
evidence:
  - id: e-1
    kind: text
    excerpt: The harbour board converted the lamp to paraffin in 1890
    source: body
statements:
  - id: s-1
    text: The harbour board modernized the lamp by electrifying it in 1890.
    evidence: [e-1]
```

The floor passes `s-1`: `e-1` anchors verbatim (§7.2) and `s-1` cites it (§7.1). But the
human grades `s-1` **mischaracterized** — the source says the board *rejected*
electrification and chose paraffin; the note asserts the opposite. No mechanical check
catches this; the spot-check does. (If a page also had a key claim with no statement,
that page would additionally be marked **dropped-important**.)

## Turn a flagged feedback page into a regression-corpus doc

`eval add-doc` (above) is the path for a *whole* document you still have the PDF for —
it reads the real source streams for you. `eval-add-page` is the narrower,
**single-page feedback-capture** path: when the user flags one page and you want just
that page in your regression set. It leaves `text:` empty for you to paste, because the
flagged-page flow does not assume the PDF is on hand.

When the user flags a page (`tnotes feedback --doc X -p N`), that page's notes are
**exactly** a candidate corpus doc (ADR-007) — her real complaint is the best possible
regression test. Promote it into your private corpus with the hidden helper:

`tnotes eval-add-page --doc data/Foo.pdf -p 14 --corpus /path/to/your/eval-corpus`

(Omit `--corpus` to use your configured `eval_corpus_dir`; omit `-p` to capture every
extracted page of the document.) It copies the flagged page's `.tnotes` notes into the
corpus layout `tnotes eval` scores (`<corpus>/Foo.pdf/1-extract/page-NNNN.notes.yaml`)
and writes a `source-pages.yaml` **scaffold** beside them.

**One manual step remains, by design.** The scaffold's `text:` field is left empty.
The floor (§7.2) anchors each excerpt against the **real source page stream**, and that
full page text is **not stored on disk** — it lives only in the PDF, which `eval` is
forbidden to read (importing the pipeline would invert ADR-007's `cli → eval`
isolation). Faking the stream from the notes' own excerpts would make every excerpt
anchor *by construction* — a vacuous pass that defeats the floor's whole purpose. So:

1. Run `tnotes eval-add-page …` as above.
2. Open the printed `source-pages.yaml` path. Each page has a `text: ''` line and, just
   above it, `# excerpt:` comments listing what the notes quote (a paste reference).
3. Paste the page's **real source text** into `text:` (and any footnote stream into
   `footnotes:`) from your copy of the document.
4. `tnotes eval` now scores the page truthfully and it is part of your regression set.

Re-running the helper on a page you've already filled **preserves** your pasted text
(it merges by `page_index`), so you can safely re-capture to add more pages.

### Or, the fully manual path (no helper)

The helper only saves typing; the corpus shape is plain files. To add a page by hand:

1. `mkdir -p /path/to/eval-corpus/Foo.pdf/1-extract`
2. Copy the flagged notes: `cp data/Foo.pdf.tnotes/1-extract/page-0013.notes.yaml /path/to/eval-corpus/Foo.pdf/1-extract/`
3. Create `/path/to/eval-corpus/Foo.pdf/source-pages.yaml` with one entry per copied
   page — `page_index`, the real `text`, and any `footnotes` — matching the smoke
   corpus shape (`tests/fixtures/eval-smoke/willowmere/source-pages.yaml`).
4. `tnotes eval --corpus /path/to/eval-corpus` scores it.
