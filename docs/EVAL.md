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
