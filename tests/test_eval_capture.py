"""Capturing a flagged `.tnotes` page into the floor-score corpus (#84 / ADR-007).

Covers the round-trip the AC asks for — capture a flagged page → `eval` scores the
resulting corpus doc — plus the honest-scaffold contract (empty `text:` until the
maintainer pastes the real page stream), re-capture preserving pasted text, the
error paths, and the import isolation: the capture path never pulls the pipeline in,
and `eval` itself still imports nothing from `eval_capture`.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import yaml
from typer.testing import CliRunner

from trustworthy_notes import cli
from trustworthy_notes import eval as eval_mod
from trustworthy_notes import eval_capture, workspace

runner = CliRunner()

# A self-authored source page (no copyrighted material). The excerpt below is a
# verbatim span of it, so it anchors once the real text is pasted into the scaffold.
_SOURCE_TEXT = (
    "The lighthouse at Cragmouth was first lit in 1869. Its keeper recorded the "
    "weather twice a day in a leather-bound log."
)
_EXCERPT = "The lighthouse at Cragmouth was first lit in 1869."


def _write_flagged_doc(doc: Path, page_index: int = 0) -> None:
    """Author a `.tnotes` workspace for ``doc`` with one flagged page's notes.

    Mirrors what the pipeline leaves on disk: per-page notes under `1-extract/`, and
    NO source page text (the stream lives only in the PDF) — which is exactly why the
    capture helper must scaffold `source-pages.yaml` rather than derive it.
    """
    doc.write_bytes(b"%PDF-1.4")  # the source file the --doc option requires to exist
    work = workspace.work_dir(doc)
    extract = workspace.extract_dir(work)
    extract.mkdir(parents=True, exist_ok=True)
    notes = {
        "schema_version": 1,
        "source": {"document": doc.name, "scope": "page", "page_index": page_index},
        "terms": [],
        "evidence": [
            {"id": "e-1", "kind": "text", "excerpt": _EXCERPT, "source": "body"}
        ],
        "statements": [
            {"id": "s-1", "type": "claim", "text": "A claim.", "evidence": ["e-1"]}
        ],
        "relations": [],
    }
    workspace.page_notes_path(work, page_index).write_text(
        yaml.safe_dump(notes, sort_keys=False), encoding="utf-8"
    )


def test_capture_materialises_corpus_doc_layout(tmp_path):
    """A flagged page lands in `<corpus>/<doc>/1-extract/` with a source scaffold."""
    doc = tmp_path / "Foo.pdf"
    _write_flagged_doc(doc)
    corpus = tmp_path / "corpus"

    result = eval_capture.capture_flagged_page(doc=doc, pages="1", corpus_dir=corpus)

    assert result.pages_captured == [0]
    assert (corpus / "Foo.pdf" / "1-extract" / "page-0000.notes.yaml").is_file()
    assert result.source_pages_file.is_file()
    # The scaffold is unfilled, so the doc is flagged not-yet-scorable.
    assert result.needs_source_text is True


def test_scaffold_lists_excerpts_and_leaves_text_empty(tmp_path):
    """The scaffold leaves `text:` empty (honest) and lists the notes' excerpts."""
    doc = tmp_path / "Foo.pdf"
    _write_flagged_doc(doc)
    corpus = tmp_path / "corpus"

    result = eval_capture.capture_flagged_page(doc=doc, pages="1", corpus_dir=corpus)
    raw = result.source_pages_file.read_text(encoding="utf-8")

    # The excerpt is present as a paste-reference comment, but NOT as the stream —
    # faking the stream from excerpts would make §7.2 pass vacuously.
    assert f"# excerpt: {_EXCERPT}" in raw
    pages = yaml.safe_load(raw)["pages"]
    assert pages[0]["page_index"] == 0
    assert pages[0]["text"] == ""


def test_round_trip_eval_scores_a_captured_page_once_text_is_filled(tmp_path):
    """The AC: capture a flagged page, paste the real page text, `eval` scores it.

    Before the paste the excerpt cannot anchor (empty stream); after the maintainer
    fills `text:` with the real source, the floor anchors it — the captured page has
    become a genuine regression-corpus doc.
    """
    doc = tmp_path / "Foo.pdf"
    _write_flagged_doc(doc)
    corpus = tmp_path / "corpus"

    result = eval_capture.capture_flagged_page(doc=doc, pages="1", corpus_dir=corpus)

    # Empty stream → the floor honestly reports the excerpt as unanchored.
    before = eval_mod.score_corpus(corpus)
    assert before.aggregate.anchored_rate < 1.0

    # The maintainer pastes the real page text (the one manual step #84 documents).
    result.source_pages_file.write_text(
        yaml.safe_dump({"pages": [{"page_index": 0, "text": _SOURCE_TEXT, "footnotes": ""}]}),
        encoding="utf-8",
    )

    after = eval_mod.score_corpus(corpus)
    assert after.aggregate.anchored_rate == 1.0
    assert after.aggregate.excerpts_anchored == 1
    assert after.docs[0].problems == []


def test_recapture_preserves_pasted_source_text(tmp_path):
    """Re-capturing a page the maintainer already filled must not clobber the text."""
    doc = tmp_path / "Foo.pdf"
    _write_flagged_doc(doc)
    corpus = tmp_path / "corpus"

    result = eval_capture.capture_flagged_page(doc=doc, pages="1", corpus_dir=corpus)
    result.source_pages_file.write_text(
        yaml.safe_dump({"pages": [{"page_index": 0, "text": _SOURCE_TEXT, "footnotes": ""}]}),
        encoding="utf-8",
    )

    again = eval_capture.capture_flagged_page(doc=doc, pages="1", corpus_dir=corpus)

    pages = yaml.safe_load(again.source_pages_file.read_text(encoding="utf-8"))["pages"]
    assert pages[0]["text"] == _SOURCE_TEXT
    # A filled page no longer signals "needs source text".
    assert again.needs_source_text is False


def test_capture_all_pages_when_no_range_given(tmp_path):
    """Omitting --pages captures every extracted page of the document."""
    doc = tmp_path / "Foo.pdf"
    _write_flagged_doc(doc, page_index=0)
    _write_flagged_doc(doc, page_index=1)  # adds a second page beside the first
    corpus = tmp_path / "corpus"

    result = eval_capture.capture_flagged_page(doc=doc, pages=None, corpus_dir=corpus)

    assert result.pages_captured == [0, 1]


def test_missing_notes_raises(tmp_path):
    """A document with no extracted notes is a clear error, not a silent empty doc."""
    doc = tmp_path / "Missing.pdf"
    doc.write_bytes(b"%PDF-1.4")  # exists, but no `.tnotes` workspace
    corpus = tmp_path / "corpus"

    try:
        eval_capture.capture_flagged_page(doc=doc, pages="1", corpus_dir=corpus)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected FileNotFoundError for a doc with no notes")


def test_empty_page_selection_raises(tmp_path):
    """A page range matching no notes is surfaced, never captured as nothing."""
    doc = tmp_path / "Foo.pdf"
    _write_flagged_doc(doc, page_index=0)
    corpus = tmp_path / "corpus"

    try:
        eval_capture.capture_flagged_page(doc=doc, pages="99", corpus_dir=corpus)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for a page selection matching nothing")


# --- the hidden CLI entry ------------------------------------------------------


def test_cli_eval_add_page_captures_and_tells_the_maintainer(tmp_path):
    """`tnotes eval-add-page` captures the flagged page and names the next manual step."""
    doc = tmp_path / "Foo.pdf"
    _write_flagged_doc(doc)
    corpus = tmp_path / "corpus"

    res = runner.invoke(
        cli.app,
        ["eval-add-page", "--doc", str(doc), "-p", "1", "--corpus", str(corpus)],
    )

    assert res.exit_code == 0, res.output
    assert (corpus / "Foo.pdf" / "1-extract" / "page-0000.notes.yaml").is_file()
    # The command must surface the one manual step (paste the source text).
    assert "paste the real page text" in res.output.lower()


def test_cli_eval_add_page_errors_without_a_corpus(tmp_path, monkeypatch):
    """With no --corpus and no configured corpus dir, the command errors clearly."""
    monkeypatch.setattr(cli.config, "get_eval_corpus_dir", lambda: None)
    doc = tmp_path / "Foo.pdf"
    _write_flagged_doc(doc)

    res = runner.invoke(cli.app, ["eval-add-page", "--doc", str(doc), "-p", "1"])

    assert res.exit_code == 1
    assert "no corpus given" in res.output.lower()


# --- import isolation (ADR-007 Invariant 5) ------------------------------------


def _imported_names(module) -> set[str]:
    """The bare module names imported by ``module`` (ImportFrom + Import)."""
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
            names.add(node.module.split(".")[-1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
    return names


def test_eval_capture_does_not_import_the_pipeline():
    """The capture path reads on-disk notes only — never the pipeline (ADR-007).

    It may import `feedback`/`workspace` (the same artifacts feedback reads) and the
    `eval` module's corpus-layout constant, but importing `pipeline`/`extract`/
    `compose`/`ingest` would invert the isolation the ADR protects.
    """
    imported = _imported_names(eval_capture)
    assert imported.isdisjoint({"pipeline", "extract", "compose", "ingest"})


def test_eval_does_not_import_the_capture_helper():
    """`eval` stays isolated: the capture helper is a separate, optional arrow.

    `eval` must not depend on `eval_capture`; the dependency runs the other way
    (`eval_capture → eval` for the layout constant only), keeping `eval`'s import set
    exactly what the #83 isolation test asserts.
    """
    assert "eval_capture" not in _imported_names(eval_mod)
