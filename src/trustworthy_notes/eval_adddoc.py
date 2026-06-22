"""Capture a whole generated document into the floor-score corpus (#92).

The real corpus-build path for ``tnotes eval`` (ADR-007). Given a source PDF that
has been run through the pipeline, this materialises it as a corpus doc:

  * it copies the doc's per-page notes (``page-*.notes.yaml``) into the corpus
    layout :func:`eval.score_corpus` discovers (``<corpus>/<doc>/1-extract/``), and
  * it reads the **real source page streams** via :func:`ingest.read_pages` and writes
    ``<corpus>/<doc>/source-pages.yaml`` with, per page, ``page_index`` / ``text`` /
    ``footnotes`` *and* ``expected_notes`` — the marker recording whether the page is
    expected to have notes (a text page; the pipeline extracts exactly those).

That ``expected_notes`` marker is the **completeness denominator** ADR-007 requires:
``eval`` compares the expected pages against the pages that actually have notes, so a
run that lost half a document (extraction failed mid-sweep, leaving stale or no notes)
can never read as a clean 100%. This supersedes the throwaway ``build_eval_corpus.py``
builder.

Isolation (ADR-007 Invariant 5). This is **cli-side**: the only inbound arrow stays
``cli → eval``, and ``eval`` itself imports no pipeline module. This helper *may* use
``ingest`` — capturing the expected-page set is a corpus-*build* step, not a *scoring*
step. ``eval`` reads the markers this wrote; it never imports ``ingest`` to recompute
them. The capture is a separate, optional ``cli → eval_adddoc`` arrow, distinct from
the per-page ``eval_capture`` path (#84), which stays ingest-free.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import ingest, workspace
from .eval import SOURCE_PAGES_FILE

# The page type the pipeline extracts notes from (see pipeline._extract:
# `selected = [p for p in all_pages if p.page_type == "text"]`). A page of this type
# is therefore *expected* to have notes — the completeness denominator (ADR-007).
_EXPECTED_PAGE_TYPE = "text"

_SOURCE_HEADER = (
    "# Floor-score corpus source streams, captured by `tnotes eval add-doc` (#92 / ADR-007).\n"
    "#\n"
    "# Each page carries the REAL source `text`/`footnotes` (read from the PDF at capture\n"
    "# time, so §7.2 anchoring is honest) and `expected_notes`: whether the page is a text\n"
    "# page the pipeline extracts. `eval` compares expected pages against the pages that\n"
    "# actually have notes — so a partial/stale run can never read as a clean 100%.\n"
)


@dataclass(frozen=True)
class AddDocResult:
    """What an ``add-doc`` capture did, for the caller to report.

    ``doc_dir`` is the corpus doc folder written; ``pages_captured`` are the 0-based
    indices whose notes were copied in; ``expected_pages`` are the source pages marked
    expected (text pages); ``source_pages_file`` is the ``source-pages.yaml`` written.
    ``missing_pages`` are expected pages that have no notes file in the workspace — the
    incompleteness the floor will surface, reported here so the maintainer sees it at
    capture time too.
    """

    doc_dir: Path
    pages_captured: list[int]
    expected_pages: list[int]
    missing_pages: list[int]
    source_pages_file: Path


def capture_doc(
    *,
    doc: Path,
    corpus_dir: Path,
    doc_id: Optional[str] = None,
    notes_dir: Optional[Path] = None,
) -> AddDocResult:
    """Materialise a generated document as a floor-score corpus doc.

    Copies the doc's per-page notes from its ``.tnotes`` workspace into
    ``<corpus_dir>/<doc_id>/1-extract/`` and writes a ``source-pages.yaml`` carrying the
    real page streams (via :func:`ingest.read_pages`) and the ``expected_notes`` marker
    per page. ``doc_id`` defaults to the source filename (``data/Foo.pdf`` → corpus doc
    ``Foo.pdf``). Raises ``FileNotFoundError`` if the document has no extracted notes —
    capturing an un-run document into the regression set is a mistake worth surfacing.
    """
    work = workspace.work_dir(doc, notes_dir)
    extract = workspace.extract_dir(work)
    if not extract.is_dir():
        raise FileNotFoundError(
            f"no extracted notes for {doc} (looked in {extract}) "
            "— run the pipeline first, then capture the doc"
        )
    notes_files = sorted(extract.glob("page-*.notes.yaml"))
    if not notes_files:
        raise FileNotFoundError(
            f"no page-*.notes.yaml in {extract} — run `tnotes extract` first"
        )

    name = doc_id or Path(doc).name
    dest_doc = Path(corpus_dir) / name
    dest_extract = workspace.extract_dir(dest_doc)
    dest_extract.mkdir(parents=True, exist_ok=True)

    captured: list[int] = []
    for notes_path in notes_files:
        shutil.copy2(notes_path, dest_extract / notes_path.name)
        index = _page_index_of(notes_path)
        if index is not None:
            captured.append(index)

    pages = ingest.read_pages(doc)
    expected = [p.page_index for p in pages if p.page_type == _EXPECTED_PAGE_TYPE]
    source_pages_file = dest_doc / SOURCE_PAGES_FILE
    source_pages_file.write_text(_render_source_pages(pages), encoding="utf-8")

    present = set(captured)
    missing = sorted(i for i in expected if i not in present)

    return AddDocResult(
        doc_dir=dest_doc,
        pages_captured=sorted(captured),
        expected_pages=sorted(expected),
        missing_pages=missing,
        source_pages_file=source_pages_file,
    )


def _render_source_pages(pages: list) -> str:
    """Render ``source-pages.yaml``: the header, then each page with its real streams
    and the ``expected_notes`` marker.

    Hand-rendered (not ``yaml.safe_dump``) so the header comment survives and each
    scalar is a single-line double-quoted form (``json.dumps`` — YAML is a JSON
    superset) that round-trips colons/quotes/newlines without line-wrapping."""
    lines = [_SOURCE_HEADER, "pages:"]
    for page in pages:
        expected = "true" if page.page_type == _EXPECTED_PAGE_TYPE else "false"
        lines.append(f"  - page_index: {page.page_index}")
        lines.append(f"    expected_notes: {expected}")
        lines.append(f"    text: {_yaml_scalar(page.text)}")
        lines.append(f"    footnotes: {_yaml_scalar(page.footnotes)}")
    return "\n".join(lines) + "\n"


def _yaml_scalar(text: str) -> str:
    """A single-line YAML scalar for a (possibly empty/multiline) source stream.

    Empty stays ``''``; real text is a JSON-encoded double-quoted scalar (YAML is a
    JSON superset), which round-trips colons/quotes/newlines cleanly and never
    line-wraps the way ``yaml.safe_dump`` would when inlined after ``text:``."""
    if not text:
        return "''"
    return json.dumps(text, ensure_ascii=False)


def _page_index_of(notes_path: Path) -> Optional[int]:
    """The 0-based page index encoded in a ``page-NNNN.notes.yaml`` filename, or None."""
    stem = notes_path.name.split(".")[0]  # "page-0013"
    try:
        return int(stem.split("-")[1])
    except (IndexError, ValueError):
        return None
