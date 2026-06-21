# eval-smoke — the public floor-score smoke corpus

A tiny, **self-authored, non-copyrighted** corpus (one document, one page) that
exercises the deterministic floor-score harness (`tnotes eval`, ADR-007) end to
end in CI. It is NOT real source material: the page text and its notes were
written by hand for this fixture, so it can ship in the repo.

The real eval corpus is verbatim copyrighted excerpts and stays **private**,
pointed at by the `eval_corpus_dir` config key, and is **never committed**
(ADR-007 inherits ADR-003's privacy stance). This smoke corpus only proves the
harness runs; it does not produce a meaningful faithfulness number.

## Layout

```
eval-smoke/
  willowmere/                 one document
    source-pages.yaml         the source page streams §7.2 anchors against
    1-extract/
      page-0000.notes.yaml    the generated notes for that page
```

Every text excerpt in the notes is a verbatim span of `source-pages.yaml`, so the
floor's anchoring rate over this corpus is 100%.
