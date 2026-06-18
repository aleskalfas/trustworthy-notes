# Methodology — Trustworthy Notes

This document is the **keystone** of the project. It describes *what we are
building* in plain English. Everything the software does must fulfil what is
written here, and the software is **validated against this document**. If we
change the methodology, we change the code and its schemas to match — never the
other way around.

It is deliberately written for a person, not a machine. The schemas later in the
file are illustrations of the same ideas in a form a machine can check.

---

## 1. The goal, in one sentence

Turn a large scientific document into a set of **trustworthy notes**: small,
clear, self-contained pieces of knowledge that **lose no important information**
and where **every piece can be traced back to the exact place it came from** in
the original document.

## 2. What this is *not*

It is **not summarization**. Summarizing means compressing — making the text
shorter and simpler, accepting that detail is lost. That is the wrong tool for
science, where the detail often *is* the information and cannot be thrown away.

Instead we **re-represent** the document: we break its knowledge into atomic
pieces, label what kind of knowledge each piece is, link the pieces together,
and attach to each piece a pointer back to the source. The result can be *read*
as notes, but underneath it is a small, traceable knowledge base. We shorten
things only where the source is genuinely repetitive — and even then, the
original wording is one click away through the source pointer.

## 3. The core principles (non-negotiable)

1. **Fidelity over brevity.** A note that is shorter but loses meaning is a bug,
   not a feature.
2. **Everything is anchored.** Every piece of knowledge carries at least one
   *anchor*: a verbatim quote from the source plus enough location information
   to find it again. No anchor, no note.
3. **One idea per note (atomicity).** A note holds a single statement or a
   single definition. If you need the word "and" to join two ideas, that is two
   notes. **Lists** are the common case: when a source *enumerates* items that
   together define one thing (a list of tasks, criteria, steps), model a
   **parent note** for the set plus **one atomic child note per item**, linked
   `child --elaborates--> parent`. The parent is grounded by the whole
   enumeration; each child by its own item. This keeps every item independently
   citable and linkable without losing the "these form one set" framing.
4. **Say what kind of knowledge it is.** A definition, a finding, an
   author's claim, someone else's reported claim, a method, an open question —
   these are different things and must be labelled differently.
5. **Keep the connections.** In science the *reasoning* between statements is
   itself information. We record how statements relate (this supports that, this
   contrasts with that) rather than letting the structure dissolve.
6. **Traceability is mechanically checked.** "Trustworthy" is not a promise; it
   is a test the notes either pass or fail (see §7).

## 4. The model: four kinds of thing

Everything we extract is one of four things.

### 4.1 Term  *(the vocabulary)*
A named idea the document uses — e.g. *polygamy*, *annuity contract (sX n
sanx)*, *consanguineous marriage*. A Term is just a label for a concept. A Term
**may** have one or more **Definitions** attached (a Definition is a kind of
Statement, see below). Terms are how we avoid re-explaining the same idea in
every note.

**Term identity is document-global.** A term id is unique and stable across the
*whole* document — `t-marriage` means the same concept on p.3 and p.250 — so a
statement on any page may reference it. But deciding true identity (is
"marriage" and "the institution of marriage" one term or two? does "house" mean
the building or the household?) needs the whole-document view, so it is
**reconciled at compose** (§4.6), not fixed page-by-page. Physically the term
store is a document-level artifact that page- and chapter-notes reference; a
single self-contained notes-set may inline it.

> This is the layer my earlier draft wrongly called "concept" for *everything*.
> A Term is a concept/word. It is **not** an assertion.

### 4.2 Statement  *(the atomic note)*
A single, self-contained piece of knowledge that could be true or false — the
actual "note". Every Statement has:
- a **text** — our wording of the idea (may paraphrase the source for clarity);
- a **type** — what *kind* of knowledge it is (see §5);
- a **basis** — *who* asserts it and on what grounds (see §5);
- one or more **references to Evidence** (by id) — its proof of origin (§4.4, §6);
- optional references to the **Terms** it is about.

> Type and basis are **independent axes**. "What kind of statement this is"
> (a claim, a definition…) is a different question from "whose assertion it is"
> (the author's own, derived from her data, or reported from someone else).
> Mixing them — as an earlier draft did with `finding` and `reported-claim` —
> hides that a reported claim is still a *claim*; it just has a different basis.

A **Definition** is simply a Statement of type `definition` that fixes the
meaning of a Term.

### 4.3 Relation  *(the connections)*
A labelled link between two Statements (or a Statement and a Term) — e.g. one
finding *supports* another, two claims *contrast*, a statement *defines* a term.
Relations are what keep the reasoning intact.

### 4.4 Evidence  *(the proof of origin)*
A verifiable pointer into the source document. This is the heart of
"trustworthy". Evidence records are **stored once, in a separate list**, and
Statements **reference them by id** — so one excerpt can ground several
statements, and "what the source says" stays cleanly separated from "what we
assert". Every Statement references at least one. (This is the same idea as the
pkit `evidence` capability's records; we use a project-local *superset* of that
shape because we need structured source fields it doesn't carry — see §9.)

Evidence comes in **kinds**, because not everything in a source is text:
- `text` — a verbatim excerpt. Re-checkable by *exact re-find* (the quote appears
  in the extracted page text). **Never a paraphrase** — the paraphrase lives in
  the Statement's *text*; the verbatim copy lives in the evidence `excerpt`.
- `figure` — a visual region (image, graph, diagram). Re-checkable by its
  **region** (a bounding box on the page) plus, where present, its **verbatim
  caption** (which is text, so still exactly verifiable).
- `table` — a tabular region; like `figure`, plus (later) transcribed cells.

> **Reading a figure or table is a Statement, not Evidence.** "The graph shows X
> rising" is a `claim` with `basis: author-data` that *cites* a `figure` record.
> The evidence is the region + caption; the reading is an explicit, labelled
> author-interpretation. We never claim to validate a pixel-level reading — we
> make the region locatable, the caption verifiable, and the interpretation
> honestly ours.
>
> Only `text` is fully built today. `figure` and `table` are **reserved**: the
> shape is declared, but we implement each variant the first time a real page
> needs it (the document's plate pages are that trigger).

**Script.** A `text` evidence record may carry a `script` naming the writing
system of its excerpt — `latin` (default), or e.g. `egyptian-transliteration`.
Egyptological transliteration is set in a dedicated font using Manuel-de-Codage
ASCII codes (`T`=ṯ, `H`=ḥ, `S`=š, `A`=ꜣ …); ingest detects that font and restores
the real Unicode signs, so `nṯr` stays faithful and is not flattened to `ntr`
(a real consonant distinction). The tag marks the excerpt as source-language
rather than prose, and lets later stages render or search it correctly.

**Drawn glyphs (inline).** Some signs — e.g. a hieroglyphic determinative — are
*drawn* inline as vector art with no character behind them, so they would be
silently dropped. Ingest replaces such a glyph with a stable, copyable
placeholder `⟨glyph-HASH⟩`, where HASH is a content hash of the glyph's
geometry: the same sign hashes identically everywhere (so distinct signs stay
distinct and repeats are recognisable), and the glyph's region is recorded. A
later OCR pass can map one HASH to one identified sign and substitute it
everywhere — fidelity is preserved now, identification deferred.

### 4.5 Ids
Every id is a kebab-case slug with a one-letter **kind prefix**, so a reference
announces what it points at without a lookup:
- `t-` — a **Term** (`t-marriage`)
- `s-` — a **Statement** (`s-king-polygamy`)
- `e-` — an **Evidence** record (`e-bryant-quote`)

Thus `terms: [t-marriage]`, `evidence: [e-bryant-quote]`, and a relation
`from: s-king-polygamy` each self-identify. Because a Relation may link a
Statement to another Statement *or* to a Term (§4.3), a relation endpoint is
`s-` or `t-`.

### 4.6 Scope: page and chapter
A notes-set has a **scope** — the span of source it covers:
- **`page`** — one page. Produced first, one set per page, independently and in
  parallel. *Intermediate.*
- **`chapter`** — one chapter. **The deliverable** a reader consumes, *composed*
  from its pages' page-sets.

Per-page extraction is independent and parallel; the chapter-level understanding
is built at **compose**, which over a chapter's page-sets:
- **stitches** statements that span a page break (e.g. p.3 ending mid-sentence
  on "Gee…"),
- **dedupes** repeated statements,
- **reconciles** term ids into the document-global store (§4.1),
- builds chapter-level **relations**.

So the gradual "mental model" forms at *compose* over the page-sets — not by
reading pages sequentially. Both scopes are valid notes-sets and obey every rule
in §7. (Why page-first-then-compose rather than sequential accretion: see the
context-strategy scratchpad note.)

**Compose does not re-extract.** It operates on the already-anchored page-sets:
evidence records are *moved unchanged* into the chapter set — their verbatim
excerpts are never regenerated — so §7.2 traceability is preserved across the
scope change by construction. Where compose needs judgement (is this the same
claim restated? what is the chapter's vocabulary?), candidates are found
**mechanically** (shared evidence, text similarity, the detected chapter
headers) and only the small candidate groups are put to the model. Faithfulness
is never delegated wholesale to one big model call over the whole document; the
model proposes on bounded inputs, the mechanical layer disposes. See
ARCHITECTURE §6 for the staged pipeline.

## 5. The small vocabularies

We keep the lists short and plain. They are tunable, but start here. A Statement
is described on **two independent axes**: its *type* and its *basis*.

**Statement type** — what *kind* of knowledge it is
- `definition` — fixes the meaning of a Term.
- `claim` — an assertion that something is the case.
- `method` — what the study/author *does*: its **subjects, data, aims, scope**,
  and analytical procedure. A declarative statement of design ("The subjects of
  this study are…", "The basic aim is to…", "This involves analysing…").
- `question` — an **open** question or hypothesis the document raises and leaves
  unsettled ("it is unclear whether officials practised polygamy").
- `background` — an accepted or contextual fact the author relies on.

> **Resolved (was Q3): aims/scope take no dedicated type.** A study's stated aim
> or scope is a *declarative* method statement (`method`); only an aim phrased as
> an unresolved question becomes a `question`. We deliberately do **not** add an
> `aim`/`scope` type: it would fragment the taxonomy for a distinction the
> `method`/`question` split already carries. The cue is grammatical mood —
> declarative design → `method`; open interrogative → `question`.

**Statement basis** — *who* asserts it and on what grounds (default `author`)
- `author` — the author asserts it in her own voice.
- `author-data` — the author establishes it from her own data or analysis (this
  is what we used to call a *finding*).
- `reported` — the author attributes it to someone else (a *reported claim*);
  the attribution is normally carried as a footnote evidence record.

The two axes combine freely: a `definition` may be `author` (the author's own)
or `reported` (a standard definition she cites); a `claim` may be `author`,
`author-data`, or `reported`.

**Evidence kinds** — see §4.4: `text` (built), `figure`, `table` (reserved).

**Evidence script** — open vocabulary (§4.4): `latin` (default),
`egyptian-transliteration`, … (other writing systems as they appear).

**Relation types**
- `defines` — Statement → Term.
- `supports` — evidence/argument for another Statement.
- `contrasts` — sets against / disagrees with another Statement.
- `elaborates` — adds detail to another Statement.
- `exemplifies` — gives an example of another Statement.
- `motivates` — gives the reason a question/aim exists.

## 6. The anchoring rule (what "traceable" means exactly)

Every evidence record carries location info:
- **source stream** — *which* part of the page: `body` or `footnote`. (Footnotes
  are a separate stream and are usually *supporting* evidence attached to a body
  Statement, not Statements of their own.) The in-text superscript that points
  at a footnote is detected by its smaller font and rewritten as an explicit
  marker `[^N]` — so a *reference* (`[^13]`) is never confused with a real number
  (a year, `S 216`, the document `10416`), and a body Statement can be linked to
  footnote N. Matching ignores these markers (§ normalization below).
- **locator** — a footnote marker (e.g. `11`), figure/table number, or section
  label when relevant.
- **page label** — the *printed* page number a scholar would cite (e.g. `3`).
- **page index** — the *PDF* page number we resolve against (e.g. `13`,
  0-based). These differ; both are recorded so a human cite and a machine lookup
  never disagree. (Both inherit from the notes-set's `source` when omitted.)

How a record is **valid** depends on its kind:
- **`text`** — its `excerpt` can be found in the named source stream after light
  normalization (collapsing line-wrap whitespace, dropping decorative glyphs,
  stripping footnote-reference superscripts glued to words — the rule already in
  `trustworthy_notes/normalize.py`). Matching is **exact substring after
  normalization** — never fuzzy or "close enough". This is the strong guarantee.
- **`figure` / `table`** *(reserved)* — its `bbox` lies within the page bounds,
  and if a `caption` is present, the caption resolves as `text` does. This is a
  **weaker** guarantee — "locatable, and its caption verifies" — and we say so
  honestly. The figure's *content* is not validated; the reading that cites it
  is a labelled Statement (§4.4).

## 7. What makes a set of notes *valid*

A notes-set either passes or fails these checks. The first five are mechanical
(the software enforces them); the sixth is a reviewed judgement the software
*assists* but cannot prove.

1. **Grounded** — every Statement references at least one Evidence record.
2. **Traceable** — every Evidence record is valid for its kind (§6): a `text`
   record's excerpt resolves in its named source stream; a `figure`/`table`
   record is locatable and its caption (if any) resolves.
3. **Well-typed** — every Statement has a `type` from the list in §5, and a
   `basis` from the list in §5 (defaulting to `author` when omitted); every
   Evidence record has a `kind` (defaulting to `text`).
4. **Referentially whole** — every Term a Statement references exists in the
   document's term store (§4.1); every Evidence id a Statement references
   exists; every Relation points to nodes that exist.
5. **Schema-valid** — the stored artifact matches the schema (§8).
6. **Complete (coverage)** — no *important* information was dropped. This cannot
   be proven mechanically. The software instead produces a **gap report**
   (`trustworthy_notes.gap`, surfaced by `tnotes gap` and `tnotes extract --gaps`): it splits a
   page's body and footnotes into sentences and flags those no evidence record
   covers, for a human to confirm are genuinely unimportant (page furniture,
   repetition) rather than lost content. It is advisory, never a gate — coverage
   is a goal enforced by *review*, not a mathematical guarantee, and we say so
   honestly.

> **Enforced at extraction, not only checked after.** Grounding (1) and
> traceability (2) are applied as a *gate* when notes are produced: the Wave-1
> extractor drops any evidence whose quote doesn't anchor and any statement left
> ungrounded (the "anchor gate"). So an unverifiable claim never reaches a
> notes-set in the first place — the model's wording is a *proposal*, the source
> is the authority.

## 8. Illustrative schema

This is the same model in a form a machine can validate. First, what real notes
look like (drawn from printed p.3 of the test document); then the shape rules.

### 8.1 Example notes (YAML)

```yaml
source:
  scope: page          # page (intermediate) | chapter (deliverable) — §4.6
  document: "McCorquodale 2013, BAR 2513"
  page_label: "3"      # what a scholar cites
  page_index: 13       # 0-based PDF page we resolve against

terms:
  - id: t-polygamy
    label: "polygamy"

evidence:                       # stored ONCE; statements reference by id
  - id: e-polygamy-aim
    kind: text                  # default; shown for clarity
    excerpt: "The latter aim involves the issue of polygamy."
    source: body
  - id: e-officials-unclear
    excerpt: "it is less clear whether officials adopted this practice."
    source: body
  - id: e-bryant-quote
    excerpt: >-
      ‘Oddly, marriage did not exist as a legal state in ancient Egypt.
      Marriages were economic and procreative unions that were often
      monogamous, enduring, loving. There was no marriage ceremony, however.’
    source: body
  - id: e-bryant-attribution
    excerpt: "Bryant in Capel–Markoe (1996: 36)."
    source: footnote
    locator: "11"

statements:
  - id: s-officials-polygamy-open
    type: question
    text: "It is unclear whether Old Kingdom officials practised polygamy."
    terms: [t-polygamy]
    evidence: [e-polygamy-aim, e-officials-unclear]    # reference by id

  - id: s-bryant-no-legal-marriage
    type: claim
    basis: reported
    text: >-
      Bryant argues marriage was not a legal state in ancient Egypt; marriages
      were economic and procreative unions, often monogamous, with no ceremony.
    evidence: [e-bryant-quote, e-bryant-attribution]

relations:
  - from: s-childbirth-death-rate   # (another statement, omitted here)
    to: s-officials-polygamy-open
    type: motivates
```

A `figure` evidence record (reserved) would look like:

```yaml
  - id: e-fig-1
    kind: figure
    locator: "Fig. 1"
    bbox: [72.0, 120.0, 520.0, 460.0]   # region on the page
    caption: "Figure 1. Plan of the tomb chapel of …"   # verbatim, verifiable
```

### 8.2 Shape rules (JSON-Schema sketch)

```json
{
  "Statement": {
    "required": ["id", "type", "text", "evidence"],
    "properties": {
      "id":     {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
      "type":   {"enum": ["definition","claim","method","question","background"]},
      "basis":  {"enum": ["author","author-data","reported"],
                 "default": "author"},
      "text":   {"type": "string", "minLength": 1},
      "terms":  {"type": "array", "items": {"type": "string"}},
      "evidence":{"type": "array", "minItems": 1,
                  "items": {"type": "string"}, "comment": "ids into the evidence store"}
    }
  },
  "Evidence": {
    "required": ["id"],
    "properties": {
      "id":      {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
      "kind":    {"enum": ["text", "figure", "table"], "default": "text"},
      "excerpt": {"type": "string", "minLength": 1, "comment": "verbatim; required for kind=text"},
      "source":  {"enum": ["body", "footnote"], "comment": "required for kind=text"},
      "locator": {"type": "string"},
      "caption": {"type": "string", "comment": "verbatim caption for figure/table"},
      "bbox":    {"type": "array", "items": {"type": "number"},
                  "minItems": 4, "maxItems": 4, "comment": "region for figure/table"},
      "page_label": {"type": "string"},
      "page_index": {"type": "integer"}
    }
  },
  "Relation": {
    "required": ["from", "to", "type"],
    "properties": {
      "type": {"enum": ["defines","supports","contrasts","elaborates",
                        "exemplifies","motivates"]}
    }
  }
}
```

## 9. How the methodology governs the code

- The **methodology is the source of truth.** This document defines the model,
  the vocabularies (§5), the anchoring rule (§6), and validity (§7).
- The **schemas (§8) encode that model mechanically.** They are the bridge
  between this prose and the program.
- The **code must produce artifacts that conform to the schemas and pass the
  validity checks.** A "validate" step checks every notes-set against §7.
- **Change control:** changing this document means updating the schemas, then
  the code and its tests, in that order. A methodology change with no
  corresponding code/test change is a defect.
- **Implementation map:** `ARCHITECTURE.md` traces each section here to the code,
  schema, and tests that realize it (with status: built / reserved / planned).
  Keep it in sync when this document or the implementation changes.

## 10. Foundations (and an honesty note)

This model is a synthesis of established ideas, not an invention:
- **Term / proposition / argument** as distinct layers — after Adler's
  analytical reading; the *term ↔ concept ↔ definition* split mirrors
  terminology science.
- **Claim + evidence + reasoning**, and typed argument roles — after the CER
  framework and argumentative-zoning schemes for scientific text.
- **One idea per note + every note references its source** — the Zettelkasten
  atomicity and traceability discipline.
- **Statements linked by typed relations** — concept-map propositions / RDF
  triples.

These attributions are from background knowledge at **medium confidence**; the
exact definitions in the named standards should be verified before we treat them
as authoritative. Given the whole point of this project, that verification is
itself worth doing — by the project's own rules, a claim is only trustworthy
once it is anchored.
