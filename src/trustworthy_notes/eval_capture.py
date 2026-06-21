"""Capture a flagged ``.tnotes`` page into the private floor-score corpus (#84).

When the user flags a page with ``tnotes feedback --doc X -p N``, that page's
generated notes are *exactly* a candidate corpus doc (ADR-007): her real complaint
becomes the maintainer's regression set. This module materialises a flagged page
into the corpus-doc layout :mod:`eval` scores — without ever importing the pipeline.

What it can do honestly, and what it cannot. The on-disk ``.tnotes`` workspace
carries the per-page **notes** (``page-NNNN.notes.yaml``) but NOT the full source
page *text* — that stream lives only in the PDF, which ``eval`` is forbidden to read
(importing ``ingest`` would invert ADR-007's ``cli → eval`` isolation). So this helper:

  * copies the flagged page's notes into ``<corpus>/<doc>/1-extract/`` (the layout
    :func:`eval.score_corpus` discovers), and
  * writes a ``source-pages.yaml`` **scaffold** — one entry per captured page, with
    the page's stored excerpts listed as a paste-reference and an empty ``text:``
    the maintainer fills with the real page text.

The empty ``text:`` is deliberate and honest: §7.2 anchors each excerpt against the
*real* page stream, so faking the stream from the excerpts themselves would make
every excerpt anchor by construction — a vacuous pass that defeats the floor. The
maintainer pastes the real page text once (see ``docs/EVAL.md``); the floor then
scores the page truthfully. This is the smallest honest mechanism (#84): the helper
does all the mechanical layout, leaving only the one thing it cannot derive on disk.

Isolation (ADR-007 Invariant 5). This module imports neither ``eval`` nor any
pipeline module (``pipeline``/``extract``/``compose``/``ingest``) — it only reads the
on-disk ``.tnotes`` notes (via ``workspace``, the same artifacts ``feedback`` reads)
and writes YAML. ``eval`` stays import-isolated; the capture path is a separate,
optional ``cli → eval_capture`` arrow.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from . import feedback, workspace
from .eval import SOURCE_PAGES_FILE

# The header that opens a freshly scaffolded source-pages.yaml, telling the
# maintainer the one manual step (paste the real page text) the helper cannot do on
# disk. Kept beside the data so a captured-but-unfilled corpus is self-explaining.
_SCAFFOLD_HEADER = (
    "# Floor-score corpus source streams — SCAFFOLD, fill before scoring (#84 / ADR-007).\n"
    "#\n"
    "# Each page below was captured from a flagged `.tnotes` page. The `text:` (and\n"
    "# `footnotes:`) fields are EMPTY on purpose: the floor (§7.2) anchors each excerpt\n"
    "# against the REAL source page stream, which is not stored on disk. Paste the real\n"
    "# page text into `text:` (and any footnote stream into `footnotes:`) from your\n"
    "# source — then `tnotes eval` scores this doc truthfully. The `# excerpts:` comment\n"
    "# under each page lists what the notes quote, as a paste reference.\n"
)


@dataclass(frozen=True)
class CaptureResult:
    """What a capture did, for the caller to report to the maintainer.

    ``doc_dir`` is the corpus doc folder created/updated; ``pages_captured`` are the
    0-based indices whose notes were copied in; ``source_pages_file`` is the scaffold
    written for the maintainer to fill. ``needs_source_text`` is True whenever any
    captured page still has an empty ``text:`` stream — the signal that the doc is not
    yet scorable and the maintainer must paste the page text first.
    """

    doc_dir: Path
    pages_captured: list[int]
    source_pages_file: Path
    needs_source_text: bool


def capture_flagged_page(
    *,
    doc: Path,
    pages: Optional[str],
    corpus_dir: Path,
    doc_id: Optional[str] = None,
    notes_dir: Optional[Path] = None,
    page_indices: Optional[set[int]] = None,
) -> CaptureResult:
    """Materialise a flagged ``.tnotes`` page (or page range) as a corpus doc.

    Mirrors ``feedback``'s scoping exactly so a page captured here is the same page a
    feedback bundle would ship: ``pages`` is the 1-based ``--pages`` spec, or
    ``page_indices`` a pre-resolved index set (e.g. a printed ``p.N`` the on-disk scan
    resolved — ADR-006). The selected notes are copied into ``<corpus>/<doc_id>/
    1-extract/`` and a ``source-pages.yaml`` scaffold is written beside them.

    ``doc_id`` defaults to the source filename (so ``data/Foo.pdf`` → corpus doc
    ``Foo.pdf``); pass it to choose a stable corpus name. Raises ``FileNotFoundError``
    if the document has no extracted notes, or ``ValueError`` if the page selection
    matches none — capturing nothing into the regression set is a mistake worth
    surfacing, not a silent no-op.
    """
    notes_files = feedback.collect_bundle_files(
        doc, pages, notes_dir, indices=page_indices
    )
    work = workspace.work_dir(doc, notes_dir)
    if not workspace.extract_dir(work).is_dir():
        raise FileNotFoundError(
            f"no extracted notes for {doc} (looked in {workspace.extract_dir(work)}) "
            "— run the pipeline first, then capture a flagged page"
        )
    if not notes_files:
        raise ValueError(
            f"no notes matched the page selection for {doc} "
            f"(pages={pages!r}, indices={page_indices!r}) — nothing to capture"
        )

    name = doc_id or Path(doc).name
    dest_doc = Path(corpus_dir) / name
    dest_extract = workspace.extract_dir(dest_doc)
    dest_extract.mkdir(parents=True, exist_ok=True)

    captured: list[int] = []
    for notes_path in sorted(notes_files):
        shutil.copy2(notes_path, dest_extract / notes_path.name)
        index = feedback._page_index_of(notes_path)
        if index is not None:
            captured.append(index)

    source_pages_file = dest_doc / SOURCE_PAGES_FILE
    needs_text = _write_source_scaffold(source_pages_file, sorted(notes_files))

    return CaptureResult(
        doc_dir=dest_doc,
        pages_captured=sorted(captured),
        source_pages_file=source_pages_file,
        needs_source_text=needs_text,
    )


def _write_source_scaffold(path: Path, notes_files: list[Path]) -> bool:
    """Write a ``source-pages.yaml`` scaffold for the captured pages; return whether
    any page still needs its source text pasted.

    One entry per captured page, keyed by the page index encoded in its filename, with
    empty ``text``/``footnotes`` for the maintainer to fill and the notes' own excerpts
    listed (as YAML comments) for reference. Pre-existing entries are preserved and
    merged on by ``page_index``, so re-capturing into a corpus the maintainer has
    already filled does not clobber pasted text — only adds the new pages.
    """
    existing = _load_existing_pages(path)
    by_index: dict[int, dict] = {
        int(e["page_index"]): e
        for e in existing
        if isinstance(e, dict) and "page_index" in e
    }

    excerpts_by_index: dict[int, list[str]] = {}
    for notes_path in notes_files:
        index = feedback._page_index_of(notes_path)
        if index is None:
            continue
        excerpts_by_index[index] = feedback._excerpts_of(notes_path)
        by_index.setdefault(
            index, {"page_index": index, "text": "", "footnotes": ""}
        )

    ordered = [by_index[i] for i in sorted(by_index)]
    needs_text = any(not (e.get("text") or "").strip() for e in ordered)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _render_scaffold(ordered, excerpts_by_index), encoding="utf-8"
    )
    return needs_text


def _render_scaffold(
    pages: list[dict], excerpts_by_index: dict[int, list[str]]
) -> str:
    """Render the scaffold YAML: the header, then each page with its excerpts inlined
    as a reference comment. Hand-rendered (not ``yaml.safe_dump``) so the per-page
    excerpt comments survive — a dump would strip them."""
    lines = [_SCAFFOLD_HEADER, "pages:"]
    for entry in pages:
        index = int(entry["page_index"])
        text = entry.get("text") or ""
        footnotes = entry.get("footnotes") or ""
        lines.append(f"  - page_index: {index}")
        for excerpt in excerpts_by_index.get(index, []):
            lines.append(f"    # excerpt: {_one_line(excerpt)}")
        lines.append(f"    text: {_yaml_scalar(text)}")
        lines.append(f"    footnotes: {_yaml_scalar(footnotes)}")
    return "\n".join(lines) + "\n"


def _one_line(text: str) -> str:
    """Collapse an excerpt to a single comment-safe line (whitespace folded)."""
    return " ".join(text.split())


def _yaml_scalar(text: str) -> str:
    """A YAML scalar for a (possibly empty/multiline) source stream.

    Empty stays ``''`` (an explicit empty string the maintainer overwrites); anything
    with real text is emitted as a single-line double-quoted scalar via ``json.dumps``
    — YAML is a JSON superset, so this round-trips text with colons/quotes/newlines
    cleanly and, unlike ``yaml.safe_dump``, never line-wraps a long scalar into a
    multi-line form that would break when inlined after ``text:``."""
    if not text.strip():
        return "''"
    return json.dumps(text, ensure_ascii=False)


def _load_existing_pages(path: Path) -> list[dict]:
    """The existing page entries in a scaffold (to preserve pasted text on re-capture).

    Reads the same ``pages:`` list ``eval._load_source_pages`` reads. A missing or
    unreadable file yields an empty list — a first capture, or a corrupt scaffold we
    simply rewrite, never crash on."""
    if not path.is_file():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    entries = raw.get("pages") if isinstance(raw, dict) else raw
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
