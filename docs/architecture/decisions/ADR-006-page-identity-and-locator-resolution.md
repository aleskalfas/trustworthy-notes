# ADR-006: Page identity and locator resolution

- Status: Accepted
- Date: 2026-06-21

**In one minute:** a document has two distinct page identities, and the tool must not conflate them. The **printed folio** — the `page_label` read off the page footer (`ingest.py`'s `_page_label`) — is what the book shows the reader as `p.N`. The **PDF page index** (`page_number - 1`) is what the per-page notes files are *named* by (`page-NNNN.notes.yaml`). They differ whenever the document has front-matter or offset — roman-numeral pages, unnumbered plates — and coincide only by accident in a document with none. The mapping between them is recovered from on-disk data, never carried through the pipeline: each notes file encodes its index in its filename and its printed folio in `source.page_label`, so the feedback-side locators resolve a user-supplied `p.N` by scanning stored labels in the `.tnotes` dir — preserving the `cli → feedback` isolation of ADR-003. Because `page_label` is nullable and not unique, a printed-`p.N` locator resolves to a *set* of indices, degrades clearly when nothing matches, and never silently widens to the whole document.

## Context

The tool reasons about pages under two different names, and a user reasons about them under a third — the one printed in the book. Keeping these straight is the whole problem this record exists to pin.

- The **PDF page index** is `page.page_number - 1` (`ingest.py`): the zero-based position of a sheet in the PDF. It is stable, total (every page has one), and unique. The per-page notes artifacts are *named* by it — `page-NNNN.notes.yaml` in the `.tnotes` directory.
- The **printed folio** is the `page_label` that `ingest.py`'s `_page_label` reads from the page footer and `extract.py` stores at `source.page_label` (when present). It is what the reader sees as the page number, what `export.py` renders as `p.{page_label}`, and therefore the only page identity a non-technical user can name.

These two identities diverge the moment a document carries any front-matter or offset — roman-numeral preliminaries, an unnumbered frontispiece, plate inserts, a numbering restart. In a document with none of that they happen to coincide, which makes the conflation easy to write and easy to miss in testing.

The feedback feature needs to accept a locator a user can actually type — a printed `p.N` — and find the underlying notes file, which is named by index. So it must resolve printed folio to PDF index. The constraint is *where* that resolution may get its data: ADR-003 established that feedback re-reads the produced artifacts and the only dependency arrow is `cli → feedback`; the pipeline never imports feedback, and feedback must never import the pipeline. Resolving the mapping by calling back into `compose.load_page_sets`, `ingest`, `extract`, or `normalize` would invert that arrow and dissolve the boundary ADR-003 exists to protect.

## Decision

**The two identities are kept distinct and named distinctly.** PDF index (`page_number - 1`) names files and is the tool's internal handle; printed folio (`page_label`) is the user-facing identity and the only thing rendered as `p.N`. No code path may treat one as a substitute for the other on the assumption they coincide.

**The mapping is recovered from on-disk artifacts, never from the pipeline.** Each `page-NNNN.notes.yaml` already carries both halves: the filename encodes the index, and `source.page_label` inside encodes the printed folio. The feedback locator resolves a user-supplied printed `p.N` to a PDF index by scanning the stored `page_label` values across the notes files in the `.tnotes` directory — the same directory feedback already reads under ADR-003. This keeps the resolution entirely on the artifact-reading side of the boundary: feedback re-reads produced output and imports none of `compose.load_page_sets`, `ingest`, `extract`, or `normalize`. Importing any of them to recover the mapping would invert the `cli → feedback` dependency arrow and is off-limits.

**The printed-`p.N` locator is partial and many-to-one, and resolves to a set.** `page_label` is nullable — a page with no detected footer label has none, and `export.py` prints `idx{N}` for it — and not guaranteed unique, since a roman-then-arabic restart can put the same printed number on two different sheets. A printed-`p.N` locator therefore resolves to the *set* of indices whose stored label matches, not a single index. When a label matches nothing it degrades with a clear "no page matches" rather than guessing, and it never falls back to widening the locator to the whole document. The total, unique PDF index remains available as the unambiguous locator when the caller already has it.

## Consequences

- **`source.page_label` is now a load-bearing output, not an incidental field.** The feedback printed-`p.N` locator depends on every notes file carrying its printed folio. A future change to `extract.py` that drops `source.page_label` from the stored note would look local and harmless but would silently break locator resolution — the scan would find nothing to match against. The label must be treated as a contract of the artifact, not a convenience.
- **This record is a fact the feedback locators stand on, and it stands on ADR-003.** The resolution strategy is only sound because it reads artifacts rather than calling the pipeline; that is the exfiltration/isolation boundary ADR-003 draws. Anyone changing how feedback resolves pages must re-read ADR-003 before reaching for a pipeline import.
- **Callers must handle a set, not a scalar.** Because a printed `p.N` can map to zero, one, or several indices, any consumer of the locator handles all three: empty (clear miss), one (the common case), and many (ambiguous — present all, never silently pick one). Code written as if `p.N` is a unique key is wrong on offset documents.
- **The two-identity distinction is a standing review check.** New code that joins a printed folio to a file, or vice versa, must go through the recovered mapping. A path that derives one identity from the other by arithmetic — or by assuming they coincide — is correct only on documents with no offset and is a latent bug everywhere else.
