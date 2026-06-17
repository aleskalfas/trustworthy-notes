---
authors:
  - Aleš Kalfas <kalfas.ales@gmail.com>
started: 2026-06-14
---

# Context strategy for per-page extraction

Exploratory (COR-012). How much of the *rest of the document* should a per-page
extraction worker see? Strict page-independence is reproducible and parallel but
loses cross-page meaning (a term defined on p.3 and called "the contract" on
p.50; a pronoun spanning a page break). Full accretion fixes that but is
sequential, drifts, and is hard to reproduce. We don't know the best point on
this axis — so we make it a **parameter** and measure it.

## The invariant that makes this safe to vary

**Context informs understanding; it never sources quotes.** Whatever context a
worker sees, every anchor it emits must resolve against the **target page only**
(METHODOLOGY §6; per-page validation). A page-worker emits evidence records with
`page_index == target` exclusively. Cross-page evidence is never minted during
extraction — it is assembled at COMPOSE time by referencing already-validated
page-level evidence ids.

Consequence: changing the context strategy can change *which statements/terms*
get extracted and *how consistently they are named*, but it can **never** change
whether a quote is faithful to its source. Provenance is invariant across all
strategies. That is what lets us experiment without risking the core guarantee.

## The strategy axis (a parameter: `context_strategy`)

| strategy        | worker sees …                              | parallel? | cost   | reproducible? |
|-----------------|--------------------------------------------|-----------|--------|---------------|
| `none`          | target page only                           | yes       | low    | yes (baseline)|
| `glossary`      | target page + shared Term glossary (pass A)| yes (B)   | low+   | yes           |
| `window:k`      | target page + k neighbour pages each side  | yes       | medium | yes           |
| `chapter`       | target page + its chapter's other pages    | yes       | medium | yes           |
| `prior-notes`   | target page + accumulated notes ≤ N-1      | **no**    | medium | no (order-dep)|
| `full-doc`      | target page + whole document text          | yes       | **high** | yes         |

Combos are allowed (e.g. `glossary + window:1`).

Notes:
- `full-doc` on a 303-page book = 303 calls each carrying the whole text —
  almost certainly cost-prohibitive and it dilutes the "anchor to THIS page"
  framing. Keep it only as an upper-bound comparison.
- `prior-notes` is the literal "gradual reading with a backloop". Best
  coreference potential, but sequential and order-dependent → keep as an
  experimental arm, not a default.

## Critique — why the two-pass glossary is NOT the default (2026-06-14)

The first draft proposed a cheap Pass-A glossary feeding parallel Pass-B
extraction. Adversarial review found it answers the wrong half of the problem at
a cost it doesn't admit. Failure modes:

1. **"Cheap + high-quality glossary" is near-contradictory.** Extracting the
   right terms *is* most of the understanding work. Cheap Pass A → shallow,
   wrong, or conflated terms; good Pass A → not cheap. The load-bearing
   assumption is unproven and probably false for scholarly prose.
2. **Cold-start disambiguation.** Term identity (one sense vs many; polysemy
   like "house" = building vs household; "marriage" vs "the institution of
   marriage") is decided in Pass A *with the least context* — exactly where it
   goes wrong. A global glossary wrongly merges senses or spawns near-duplicates.
3. **Solves the wrong problem.** The original worry was cross-page *meaning* —
   "the contract", pronouns, "this practice", "as argued above". A glossary of
   term-ids fixes term *naming*, not coreference/anaphora. `window`/`chapter`
   context handles the actual concern; the glossary mostly doesn't.
4. **Glossary can't be complete after Pass A.** A term's importance often only
   shows once its claims appear (Pass B). Late-discovered terms → integrity
   failure or re-invented ids (defeating the point). The feedback loop makes the
   glossary mutable → already-processed pages go stale. We didn't remove the
   ordering problem, we relocated it from "accreting notes" to "a shared
   mutable glossary".
5. **Forces an unacknowledged schema change.** If p.50 reuses a term whose
   defining evidence is on p.3, per-page referential integrity breaks — terms
   must become a **document-global store**, separate from per-page notes.
6. **Cost leaks back.** A 303-page book's glossary could be hundreds of terms;
   injecting it into every Pass-B worker re-creates the `full-doc` cost we were
   avoiding. Relevance-filtering needs retrieval = more machinery + failure modes.
   And it is ≥2× extraction cost (read everything twice).
7. **Difficulty migrates to compose.** Simpler Pass B buys a heavier, least-
   specified compose (merge inconsistent terms, dedupe, stitch). The hard work
   is deferred, not removed.
8. **Our corpus is the failure case.** The glossary pass suits documents with a
   stable, explicitly-defined vocabulary (textbooks, specs). It is weakest on
   argumentative humanities prose with emergent, polysemous, context-carried
   terms — i.e. exactly the Egyptology monograph we test on.

## Revised working hypothesis: local context + compose-time term reconciliation

Demote the glossary from an extraction *input* to a compose *output*. Let terms
emerge bottom-up with *local* context, and resolve identity where the global view
actually exists — compose.

```
EXTRACT (per page, PARALLEL) →  page-notes
        worker sees: target page + LOCAL context (window:k or its chapter),
        which handles coreference ("the contract", pronouns, "as argued above").
        Terms emerge locally/bottom-up. Anchors target page only (invariant).

COMPOSE (per chapter)        →  chapter-notes + reconciled term set
        now holding the global view AND the per-page evidence:
          - term reconciliation (entity-resolution): merge t-* ids that denote
            the same concept; this is where disambiguation belongs;
          - stitch cross-page statements, dedupe, build chapter relations.
```

Why this is better: it targets the *actual* concern (coreference) with local
context; it stays parallel and reproducible-in-input; it resolves term identity
with maximum context instead of minimum; and it stops pretending a cheap global
glossary exists. The cost is a more serious compose step — but that work was
unavoidable anyway (the draft just hid it).

Default extraction context: **`window:1`** (page + one neighbour each side),
revisited to `chapter` once chapter boundaries exist. `none`, `prior-notes`,
`full-doc`, and a pre-pass `glossary` remain selectable as experimental arms for
the harness to compare against — the hypothesis is falsifiable, not fixed.

## How we choose — measure, don't guess

We can score strategies objectively because the methodology already defines
validity. On the same fixed set of pages, run each strategy and compare:

- **anchor-pass rate** — fraction of emitted anchors that resolve (should be ~100%
  for *all* strategies; if a strategy drops it, it's hallucinating quotes).
- **term consistency** — does the same concept get one stable `t-` id across
  pages, or many duplicates? (the metric the whole question is about)
- **coverage gap** — how much source text no statement covers (§7.6).
- **duplicate-statement rate** — same claim extracted twice across pages.
- **cost / tokens / latency** — the practical budget.

Cheap-but-consistent beats expensive-but-marginally-better; the table above is a
hypothesis, the harness decides.

**Caveat (from the critique):** only **anchor-pass rate** and **cost** are truly
objective. **Term-consistency** and **coverage** have *no ground truth* — judging
"same concept → same id" presupposes the true concept set, which is the thing we
are trying to produce. Those dimensions need slow, subjective human judgement, so
the harness can rank cost/fidelity cleanly but only *assist* on quality. Build a
small hand-labelled gold set (a few pages, terms reconciled by hand) before
trusting any consistency metric.

## How it plugs in

- A `ContextStrategy` provider sits in front of the per-page `Extractor`: given
  the target page + document state (glossary, neighbours), it assembles the
  worker's context. The `Extractor` itself stays strategy-agnostic.
- `context_strategy` is a config knob in `.trustworthy-notes/config.yaml`;
  default chosen after the first experiment (lean: `glossary` or
  `glossary + window:1`).
- Parallelism (`max_parallel`) is orthogonal and applies to whichever strategies
  are parallel-safe.

## Open questions (revised)

1. **Term reconciliation at compose** is now the crux: what's the merge rule for
   deciding two `t-` ids denote the same concept? (surface-form match is too
   weak; embedding similarity + human confirm? evidence overlap?) This is the
   risk that moved here from Pass A — it must be specified, not hand-waved again.
2. **Chapter boundaries** — needed for `chapter` context, for compose, and for
   the chapter-level deliverable. How? (TOC parse, heading detection, manual
   page→chapter map to start). Blocks the default eventually moving to `chapter`.
3. `window:k` — what k? Is a fixed page window even the right unit, or should the
   window follow *paragraph/section* boundaries rather than page edges?
4. Schema consequence: terms likely become a **document-global store** (see
   critique #5) regardless of strategy — confirm and reflect in METHODOLOGY/schema.
5. Is `prior-notes` worth implementing at all, given it forfeits parallelism and
   the local-window + compose-reconciliation path covers its motivation?
6. Gold set: which pages, and who reconciles terms by hand, to make the quality
   metrics trustworthy?
