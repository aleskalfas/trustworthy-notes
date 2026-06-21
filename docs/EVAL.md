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
  tool/build version, and the floor counts. Change the instrument (the corpus, the
  build) and you cannot compare across runs.

## Run it

Point it at a corpus directory:

`uv run tnotes eval --corpus tests/fixtures/eval-smoke`

It prints a per-doc + aggregate floor-score report. To save a comparable artifact:

`uv run tnotes eval --corpus tests/fixtures/eval-smoke --json /tmp/score.json`

The JSON is a small, stable, sorted shape carrying the fingerprint, so two runs
diff cleanly. To compare two runs, **check the fingerprints match first** (corpus
hash + tool version) — a number that improved under a *different* instrument is not
a real improvement.

## The corpus

A corpus is a directory of **document subfolders**. Each doc folder carries the
generated per-page notes plus the source page streams §7.2 anchors against:

```
corpus/
  some-document/
    source-pages.yaml         # the source page streams: page_index / text / footnotes
    1-extract/
      page-0000.notes.yaml    # the generated notes (workspace layout)
      page-0001.notes.yaml
  another-document/
    ...
```

`source-pages.yaml` is a list of `{ page_index, text, footnotes }` — the only three
fields the §7.2 traceability check reads. Keeping the streams beside the notes makes
the corpus self-contained: `eval` needs no PDF and never calls back into the
pipeline (the isolation ADR-007 requires).

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
