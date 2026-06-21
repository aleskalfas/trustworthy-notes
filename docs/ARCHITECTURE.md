# Architecture — how the methodology is implemented

`METHODOLOGY.md` is the **source of truth** (the *what*). This document is the
*how*: which code, schema, and tests realize each methodology rule — with a
reference back to the methodology section (`§N`) each one serves. Per
`METHODOLOGY.md` §9, the dependency runs **methodology → schema → code → tests**;
a methodology change obligates a change here too.

Status legend: **built** · **reserved** (shape declared, not yet implemented) ·
**planned** (not started).

### Terminology: waves vs stages

Two levels, used consistently throughout:

- **Wave** — a top-level pipeline phase (§1): `0 ingest · 1 extract · 2 compose ·
  3 validate · 4 export`. The per-document **workspace folders are named by wave**
  (`1-extract/`, `2-compose/`, `3-validate/`) — the number is the *phase an output
  belongs to (its role)*, **not** the order commands were run. So `tnotes gap`
  (validate) writes to `3-validate/` and `tnotes dedup` (compose) writes to
  `2-compose/` regardless of which you ran first.
- **Stage** — an internal step *within a wave*. Only **Wave 2 (compose)** has
  stages, numbered 0–6 (§6): `0 load · 1 chapter-group · 2 stitch · 3 dedup ·
  4 term-store · 5 relations · 6 assemble`. A stage may have named parts
  (e.g. stage 3 dedup = *blocking* then *adjudication*); parts are not numbered.

Command → wave/stage → output:

| Command | Wave / stage | Saves to |
|---|---|---|
| `tnotes extract` | Wave 1 | `1-extract/page-NNNN.notes.yaml` |
| `tnotes chapters` | Wave 2, stage 0–1 | `2-compose/1-chapter-map/chapters.txt` |
| `tnotes stitches` | Wave 2, stage 2 | `2-compose/2-stitches/stitches.txt` |
| `tnotes dedup` | Wave 2, stage 3 | `2-compose/3-dedup/` (dedup.txt, dedup-merges.yaml) |
| `tnotes terms` | Wave 2, stage 4 | `2-compose/4-terms/` (terms.txt, terms.yaml) |
| `tnotes relations` | Wave 2, stage 5 | `2-compose/5-relations/` (relations.txt, relations.yaml) |
| `tnotes assemble` | Wave 2, stage 6 | `2-compose/6-chapters/chapter-NNN.notes.yaml` |
| `tnotes gap` | Wave 3 | `3-validate/gaps.txt` |
| `tnotes export [--pdf]` | Wave 4 | `4-export/chapter-NNN.<style>.md` (+ `.pdf`) |

Wave 2 is multi-stage, so its folder is itself split into stage-numbered subfolders
(`2-compose/1-chapter-map/` … `6-chapters/`) — the deliverables (`6-chapters/`) kept
apart from the per-stage views/data.

---

## 1. The pipeline (waves)

```
  source PDF ──▶ Wave 0  ingest    ──▶ PageText (per page)        [built]
                  └─ layout-classify each page: text / figure / table / blank,
                     then route: text→columns, table→rows (no zipper),
                     figure→captions + drawing regions, blank→skip
                 Wave 1  extract   ──▶ page notes-set (per page)  [built]
                  └─ Claude adapter (claude-opus-4-8): page → intermediate JSON
                     (structured output) → assemble `t-`/`s-`/`e-` ids
                  └─ anchor gate: any evidence quote that doesn't verbatim-resolve
                     on the page is dropped, and any ungrounded statement with it
                 Wave 2  compose   ──▶ chapter notes-set          [built §6]
                 Wave 3  validate  ──▶ pass/fail + gap report     [partly built]
                 Wave 4  export    ──▶ study notes (markdown + PDF) [built: outline]
                  └─ Layer B: a study document synthesized ONLY from the chapter
                     notes, citing note ids that link to the verbatim evidence
                     (page citations plain text). Renders an interactive PDF
                     (bookmarks + clickable Contents + [s-N] links) with --pdf.
                     Styles pluggable; outline built, narrative/zettelkasten designed.
```

- **Per-page extraction is independent and parallel**; the chapter-level
  understanding is built at **compose**, not by reading sequentially
  (`METHODOLOGY.md` §4.6; rationale in
  `.pkit/scratchpad/active/2026-06-14-context-strategy.md`).
- **The anchoring invariant** holds across every context strategy: context
  informs understanding, but every anchor resolves against the **target page
  only**. This is what keeps provenance safe regardless of how Wave 1 is tuned
  (§6; context-strategy note).

Inputs, working artifacts, and outputs live in **user-owned folders, never in
the repo** (a per-document workspace). This is operational, not methodology;
spec is being worked out (see the data-flow discussion / planned `tnotes` CLI +
`.trustworthy-notes/config.yaml`).

---

## 2. Components and the methodology each serves

| Module / file | Role | Implements (methodology) | Status |
|---|---|---|---|
| `src/trustworthy_notes/ingest.py` | Wave 0: PDF → `PageText`; layout-classify + route (text columns / table rows / figure captions+regions / blank); running headers stripped; footnotes split; printed-label captured; transliteration (MdC) restored to Unicode; inline drawn glyphs → `⟨glyph-HASH⟩` placeholders (+ region registry); footnote-reference superscripts → `[^N]` markers (body↔footnote link) | §6 source model — the `body`/`footnote` streams and `page_index` vs `page_label` an anchor resolves against | built (text/table/figure-captions); figure-image crop + glyph OCR **planned** |
| `src/trustworthy_notes/models.py` | `PageText` (Wave 0 output) with `page_type` + `figure_regions` | §6 (the page an anchor points into) | built |
| `src/trustworthy_notes/normalize.py` | `normalize_for_match`, `quote_is_anchored` — verbatim matching | §6 anchoring rule for `text`: normalized-substring containment (whitespace / PUA glyph / superscript & `[^N]` footnote-ref handling); never fuzzy | built |
| `src/trustworthy_notes/translit.py` | `mdc_to_unicode` — restore Egyptological transliteration signs (MdC `T`→ṯ, `H`→ḥ …) from the source font | §1 fidelity (ṯ≠t); §4.4 evidence `script` | built |
| `src/trustworthy_notes/schemas/notes.schema.json` | The notes-set shape, machine-checkable | §4 four kinds · §5 vocabularies · §4.5 id prefixes (`t-`/`s-`/`e-`) · §4.6 `scope` · §6 evidence fields · enforces §7.1/§7.3/§7.5 by shape | built (text); figure/table evidence & chapter **reserved** |
| `src/trustworthy_notes/validation.py` | `validate_structure`, `check_traceability` — the §7 checks as code | §7.5 schema-valid, §7.1 grounded, §7.3 well-typed (via schema); §7.4 referential integrity; §7.2 traceability (`text` only) | built; §7.6 coverage **planned** |
| `src/trustworthy_notes/extract.py` | Wave 1: `Extractor` protocol + `anchor_gate` + `run_extract` + `write_notes` | §7.1 grounded & §7.2 traceable **enforced at extraction** (drops unanchored evidence + ungrounded statements) | built |
| `src/trustworthy_notes/extract_anthropic.py` | Wave 1 Claude adapter: prompt-cached methodology rules + structured output → `assemble` ids; `claude-opus-4-8`, adaptive thinking, `effort: medium` | the whole notes model (§4, §5, §6) as extraction instructions | built (unit-tested with a fake client; live behaviour to be tuned) |
| `src/trustworthy_notes/cli.py` | The `tnotes` command: `extract` (Wave 1, Claude), `probe` (per-page dump), `render` (annotated scan PNGs), `layout` (page-type sweep) | — (operational / inspection surface) | built |
| `tests/test_normalize.py` · `test_notes.py` · `test_ingest.py` | Conformance: anchoring rule, §7 validity, and ingest layout classification | §6 · §7.1–§7.5 · §4.5/§4.6 · Wave-0 routing | built |
| `tests/fixtures/notes.printed-p3.yaml` | Hand-built golden notes-set (printed p.3) | the whole model — the executable example the validators run against | built |

### Packaging & out-of-pipeline surfaces (v0.2.0)

These ship the tool as a self-contained Windows exe and add the
user-facing-but-not-pipeline features. Each is tagged with its **trust domain**:
*pipeline* (inside the extraction trust domain) or *out-of-pipeline* (an isolated
module the pipeline never imports — see Invariant 5).

| Module / file | Role | Trust domain | Status / ADR |
|---|---|---|---|
| `src/trustworthy_notes/__main__.py` | Frozen-exe + `python -m` entry point; invokes the same typer app | pipeline (entry) | built — frozen-packaging surface (ADR-002) |
| `tn.spec` (+ build deps) | PyInstaller one-file spec; bundles fonts/schemas/pdfminer cmaps, bakes the build stamp | pipeline (packaging) | built (ADR-002) |
| `src/trustworthy_notes/resources.py` | The single frozen-aware resource seam — `importlib.resources.as_file()` for any consumer needing a real path (fonts, schema); fonts → process-lifetime temp dir | pipeline (cross-cutting) | built (ADR-002) |
| `src/trustworthy_notes/build.py` | Build identity (`<version>+<stamp>`); the frozen substitute for source-hashing in the output cache | pipeline (cross-cutting) | built (ADR-002) |
| `src/trustworthy_notes/updater.py` | `tnotes upgrade` + launch-time update nudge; GitHub+TLS trust root, checksum-as-corruption-guard, verify-launchable-before fail-safe in-place swap | **out-of-pipeline** (self-update trust domain) | built; Windows swap validated on real HW (ADR-001) |
| `src/trustworthy_notes/feedback.py` | `tnotes feedback`; private-repo upload via out-of-band fine-grained PAT, consent gate, local-file fallback | **out-of-pipeline** (feedback / exfiltration trust domain) | built (ADR-003) |
| `src/trustworthy_notes/winlaunch.py` | Windowless-launch (double-click / drag) detection, pause-to-read, first-run key onboarding | **out-of-pipeline** (Windows UX) | built; Windows path validated on real HW |
| `src/trustworthy_notes/maclaunch.py` | `tnotes install-droplet`; compiles a "Send Feedback" AppleScript droplet onto the macOS Desktop via `osacompile`, with the absolute `tnotes` path baked in. **Touches no network** — shells to a local `tnotes` — so it's an OS-integration module, not a network one | **out-of-pipeline** (macOS OS-integration) | built; macOS path validated on real HW (ADR-005) |
| `src/trustworthy_notes/pricing.py` | Per-model cost **estimate** from provider usage × hardcoded `PRICING_AS_OF` rate table; non-authoritative (leaf, no pipeline imports) | pipeline (leaf, advisory figure) | built (ADR-004) |
| `src/trustworthy_notes/eval.py` | Maintainer faithfulness yardstick: a deterministic **floor** (verbatim-anchoring §7.2, grounding §7.1, referential integrity §7.4, reusing `validation`/`normalize`) plus a future stochastic **judge**, reported separately next to an instrument fingerprint; **advisory, never a gate** (`cli → eval`, never `pipeline → eval`). Touches the model only for the deferred judge; ships floor-only now | **out-of-pipeline** (maintainer eval) | built (floor); LLM judge **deferred** (ADR-007) |

---

## 3. Methodology → implementation traceability matrix

Every methodology section, and where it lives in the implementation.

| `METHODOLOGY.md` | Concept | Realized by | Status |
|---|---|---|---|
| §1–§3 | Purpose; fidelity-over-brevity; atomicity (incl. list = parent + children) | Encoded as constraints across the schema + validators; the list rule is a Wave-1 *authoring* discipline (not mechanically enforced) | principles |
| §4.1 | **Term**, document-global identity, reconciled at compose | `term` def + global `terms` store in schema; reconciliation is **planned** (compose) | partial |
| §4.2 | **Statement** (text/type/basis/evidence refs) | `statement` def in schema; `text` paraphrase vs verbatim split enforced by putting quotes only in evidence | built |
| §4.3 | **Relation** (typed links) | `relation` def in schema; referential check in `validation.py` | built |
| §4.4 | **Evidence** kinds (`text` / `figure` / `table`); stored once, referenced by id; `script` tag | `evidence` def + `kind` discriminator + `script` field; transliteration restored at ingest (`translit.py`); `text`/`script` built, `figure`/`table` **reserved** | partial |
| §4.5 | **Id prefixes** `t-`/`s-`/`e-` | `term_id`/`statement_id`/`evidence_id` patterns in schema (mechanically rejects wrong-kind refs) | built |
| §4.6 | **Scope** `page` \| `chapter` | `source.scope` + conditional requirements (page→`page_index`, chapter→`page_range`); chapter **reserved** | partial |
| §5 | Vocabularies (type, basis, relation, evidence kind) | `enum`s in the schema | built |
| §6 | **Anchoring rule** (kind-aware) | `normalize.py` (`text`); `figure`/`table` region+caption rule **reserved** | partial |
| §7.1 | Grounded (≥1 evidence) | schema `minItems: 1` on `statement.evidence` | built |
| §7.2 | Traceable | `validation.check_traceability` (`text`) | built (text) |
| §7.3 | Well-typed | schema `enum`s on `type`/`basis`/`kind` | built |
| §7.4 | Referentially whole | `validation.validate_structure` (refs + relation endpoints) | built |
| §7.5 | Schema-valid | `validation.validate_structure` (Draft 2020-12) | built |
| §7.6 | Coverage / gap report | — | **planned** |
| §8 | Illustrative schema | `notes.schema.json` is the real, normative version | built |
| §9 | Governance (methodology → schema → code → tests) | this document + the change discipline | process |
| §10 | Foundations (Adler, CER, Zettelkasten, …) | — (and still **unanchored**: a known evidence-debt to close via the `evidence` capability) | debt |

---

## 4. Invariants (must always hold)

1. **Anchoring invariant** — context never sources quotes; every anchor resolves
   to its target page (§6; context-strategy note). Lets Wave 1's context
   strategy vary without risking provenance.
2. **Methodology is the source of truth** — code/schema answer to
   `METHODOLOGY.md`; a methodology change with no corresponding schema/code/test
   change is a defect (§9).
3. **Paraphrase vs verbatim** — a Statement's `text` may paraphrase; an
   Evidence `excerpt` is verbatim. Quotes never live in `text` (§4.2, §6).
4. **No dead code** — every module on the live surface is used; planned
   structures are added when first needed, not before.
5. **Network posture** — the pipeline commands (Waves 0–4) touch the network
   **only** for the Anthropic extract calls they already make. Everything that
   reaches the network for any other reason — version-check / upgrade
   (`updater`), feedback (`feedback`), the launch-time update nudge, and the
   windowless-launch onboarding (`winlaunch`) — is an **isolated module the
   pipeline never imports**. The dependency arrows are `cli → updater`,
   `cli → feedback`, `cli → winlaunch`, never `pipeline → *`. This keeps Waves
   0–4 runnable offline with no second-credential surface, and keeps the
   self-update / feedback trust domains out of the extraction trust domain
   (ADR-001 distribution & self-upgrade trust model; ADR-003 feedback
   data-exfiltration boundary). The macOS `maclaunch` module
   (`cli → maclaunch`, never `pipeline → *`) is the same isolated shape but an
   **OS-integration, not a network, module**: it touches **no network** — it
   compiles a desktop droplet that shells to a local `tnotes` (ADR-005) — so it
   sits beside `winlaunch` outside the pipeline for OS-glue isolation, not for a
   network surface. The maintainer `eval` module
   (`cli → eval`, never `pipeline → eval`) is isolated for the same reason: it
   *reuses* the real floor (`eval → validation`, `eval → normalize` — never
   re-implementing the checks, COR-007), and the pipeline never imports it, so the
   faithfulness yardstick can never gate extraction and its future stochastic
   judge stays out of the extraction trust domain (ADR-007). It ships floor-only
   today (no network); the deferred judge would touch the model.

---

## 5. What is built, reserved, and planned

> **Release status (v0.2.0):** the full extraction pipeline (Waves 0–4) is
> implemented, and v0.2.0 packages it as a **self-contained Windows `tnotes.exe`**
> with **in-place auto-update** (`tnotes upgrade` + a launch nudge) and a
> **no-terminal (double-click / drag) launch** path. The packaging and
> out-of-pipeline surfaces are listed in §2's "Packaging & out-of-pipeline
> surfaces" table and their foundational decisions in
> `docs/architecture/decisions/` (ADR-001…004). The per-wave maturity below
> still applies to the *pipeline internals* (e.g. figure/table evidence remains
> reserved).

- **Built:** Wave 0 ingest incl. **layout classification + routing** (text
  columns / table rows / figure captions+regions / blank); running-header
  stripping; **Egyptological transliteration restored to Unicode** + evidence
  `script` tag; inline-glyph `⟨glyph-HASH⟩` placeholders; footnote-ref `[^N]`
  markers; the anchoring normalizer; the notes schema (text path); the §7.1–§7.5
  validators; the **Wave-1 extractor — provider-agnostic core + anchor gate +
  Claude adapter** (`tnotes extract`); the `probe` / `render` / `layout` CLIs;
  golden fixture + tests (53 passing).
- **Reserved** (shape declared in schema/methodology, no behaviour yet):
  `figure`/`table` *evidence kinds* in the notes model (§4.4, §6); `chapter`
  scope (§4.6).
- **Built (Wave 2 compose, §6):** chapter map, statement dedup (mechanical
  blocking + bounded model adjudication), document-global term store, cross-page
  relations (term-blocked), and assembly into validated `chapter-NNN.notes.yaml`.
  Each view is saved as a readable artifact in the wave folders.
- **Designed, not yet built:** applying cross-page evidence **stitches** at
  assembly (needs spanning-evidence `page_index_end` + §7.2 update); cross-page
  relations are carried as proposals.
- **Planned** (not started): figure-image cropping + structured table cells (we
  capture region+caption / linear rows for now); Wave 4 export; closing the §10
  evidence-debt.

---

## 6. Wave 2 (compose) — design & status [built]

> **Status:** stages 0–6 built (`tnotes chapters/stitches/dedup/terms/relations/assemble`).
> `assemble` produces validated `chapter-NNN.notes.yaml`. **Deferred:** applying
> cross-page **stitches** at assembly (needs a spanning-evidence representation —
> `page_index_end` — plus a §7.2 traceability update for it); they are computed and
> shown today but not yet folded into the chapter evidence.

Compose turns the **per-page atoms** (typed statements + anchored evidence +
relations, `scope: page`) into **chapter-scope** notes-sets (`METHODOLOGY.md`
§4.6). It is a **mostly-deterministic pipeline**; the model is used only on
small, bounded inputs. Rationale: the corpus is large (~3.1k statements, ~4.6k
evidence, ~388k tokens) — too big and too unauditable to "compose in one LLM
call", and evidence must be *moved verbatim*, never regenerated.

**Principle:** *code blocks and disposes; the model proposes on bounded inputs;
evidence is never re-touched.*

### Stages

| # | Stage | How | Model input |
|---|---|---|---|
| 0 | Load page-sets; give every node a **document-global id** (page-scoped `s-1` collide), keep `page_index` provenance | code | — |
| 1 | Group pages → **chapters** (reuse Wave 0 running-header detection / TOC) | code | — |
| 2 | **Stitch cross-page evidence** — a quote truncated at a page break rejoined with its continuation on the neighbour page | code (string adjacency on normalized text) | — |
| 3 | **Dedup/merge** restated statements | code blocks candidates → model adjudicates small clusters → code unions evidence | one cluster (2–6 statements) |
| 4 | Build the **document-global term store** (§4.1) + link statements | model names a chapter's concepts → code dedups labels & links | one chapter's statements |
| 5 | **Cross-page/chapter relations** via shared terms/entities | code (optional model per chapter) | one chapter |
| 6 | Assemble `scope: chapter` sets, **re-validate** (§7.1–§7.5), write to the per-document folder | code | — |

The model appears only in stages 3–4, always over one chapter or one small
cluster — never the whole corpus.

### Stage 3 dedup: blocking / candidate-generation

Never compare all pairs (3135² ≈ 10M). **Block** mechanically, then adjudicate
only survivors:

- **Strong signal — shared evidence.** Two statements of the same `type` citing
  the same verbatim excerpt are almost certainly one claim. On this corpus this
  alone yields **36 candidate clusters (79 statements)** out of 3,135 — high
  precision, near-free.
- **Recall knob — fuzzy text similarity** (token Jaccard / cosine over the
  normalized statement text), to catch a claim *restated with different
  evidence* (which shared-evidence misses; there are **0 exact-text duplicates**,
  so exact match is useless). The threshold tunes how many candidates reach the
  model.
- **Deferred — embeddings** (best semantic recall) would add an embedding
  provider (Voyage) or a local model, cutting against the pure-Python /
  no-heavy-deps goal. Out of scope for v1; the knob above is enough to start.

Tiers: *auto-merge* identical text (0 here) → *adjudicate* clustered-but-distinct
(~36 groups) → *skip* singletons (~the other 3,000, untouched). The model returns
merge/keep + the merged paraphrase **text only**; code unions the existing
anchored evidence records, so §7.2 is preserved.

> **Scale finding:** only ~36–79 obvious duplicate candidates in 3,135 means the
> corpus is *mostly distinct atoms* — dedup is a small, bounded, cheap
> sub-problem here, not where Wave 2's cost or risk lives (that is the term store
> and chapter assembly).

### Stage 4 term store

Per-page term extraction collapsed under `low` effort (8 term records across 201
pages) — but a term is **document-global** by definition (§4.1), so per-page was
the wrong layer anyway. Compose derives the vocabulary once: a **per-chapter**
model pass names the recurring technical concepts (bounded input = one chapter's
statements), code **dedups labels** across chapters into the single store and
links statements to it by label match.

---

## 7. References

- `METHODOLOGY.md` — the source of truth this document maps from.
- `docs/architecture/decisions/` — the application's ADRs. ADR-001 (distribution
  & self-upgrade trust model), ADR-002 (frozen-build correctness), ADR-003
  (feedback data-exfiltration boundary), ADR-004 (cost estimate is
  non-authoritative) own the rationale for the v0.2.0 packaging and
  out-of-pipeline surfaces (§2) and the network-posture invariant (§4).
- `.pkit/scratchpad/active/2026-06-14-context-strategy.md` — per-page context
  strategy + the page-vs-accretion decision.
- `.pkit/scratchpad/active/2026-06-13-evidence-summarizer-design.md` — earlier
  design log (ingest, waves).
