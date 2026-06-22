"""The deterministic floor-score harness (ADR-007) — instrument, never a gate.

Covers the floor scoring (known-good → full anchoring; known-bad → the floor
catches the unanchored excerpt), determinism (same corpus → identical score bar
the timestamp), the public smoke corpus running through `tnotes eval`, and the
import-isolation ADR-007 requires: `eval` imports no pipeline module, and the
pipeline imports no `eval` (mirroring the feedback isolation test).
"""

from __future__ import annotations

import ast
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml
from typer.testing import CliRunner

from trustworthy_notes import cli, config
from trustworthy_notes import eval as eval_mod

runner = CliRunner()

FIXTURE = Path(__file__).parent / "fixtures" / "eval-smoke"

# A self-authored source page (no copyrighted material) used to build corpora in
# this test. The excerpts below are verbatim spans of it.
_SOURCE_TEXT = (
    "The lighthouse at Cragmouth was first lit in 1869. Its keeper recorded the "
    "weather twice a day in a leather-bound log. Storms in the autumn of 1881 "
    "tore the slates from the cottage roof, and the lamp burned whale oil until "
    "the harbour board converted it to paraffin in 1890."
)


def _write_doc(corpus: Path, doc_id: str, *, excerpt: str) -> None:
    """Author a one-page doc into ``corpus``: its source page + one notes-set.

    ``excerpt`` is the single text-evidence excerpt — a verbatim span of the source
    anchors (§7.2), an altered one fails. The lone statement always cites it, so the
    grounding rate (§7.1) over these corpora is 1.0.
    """
    doc_dir = corpus / doc_id
    extract = doc_dir / "1-extract"
    extract.mkdir(parents=True, exist_ok=True)
    (doc_dir / "source-pages.yaml").write_text(
        yaml.safe_dump({"pages": [{"page_index": 0, "text": _SOURCE_TEXT, "footnotes": ""}]}),
        encoding="utf-8",
    )
    notes = {
        "schema_version": 1,
        "source": {"document": doc_id, "scope": "page", "page_index": 0},
        "terms": [],
        "evidence": [{"id": "e-1", "kind": "text", "excerpt": excerpt, "source": "body"}],
        "statements": [
            {
                "id": "s-1",
                "type": "claim",
                "text": "A claim about the lighthouse.",
                "evidence": ["e-1"],
            }
        ],
        "relations": [],
    }
    (extract / "page-0000.notes.yaml").write_text(
        yaml.safe_dump(notes, sort_keys=False), encoding="utf-8"
    )


# --- floor scoring: known-good and known-bad -----------------------------------


def test_known_good_corpus_anchors_fully(tmp_path):
    """A doc whose excerpt is a verbatim span of the source → anchoring rate 1.0."""
    corpus = tmp_path / "good"
    _write_doc(corpus, "doc-a", excerpt="The lighthouse at Cragmouth was first lit in 1869.")

    score = eval_mod.score_corpus(corpus)

    assert score.aggregate.anchored_rate == 1.0
    assert score.aggregate.excerpts_anchored == 1
    assert score.docs[0].problems == []


def test_known_bad_corpus_floor_catches_unanchored_excerpt(tmp_path):
    """An excerpt NOT present in the source → the floor catches it: rate < 1, surfaced."""
    corpus = tmp_path / "bad"
    _write_doc(corpus, "doc-a", excerpt="The lighthouse was painted bright purple in 1869.")

    score = eval_mod.score_corpus(corpus)

    assert score.aggregate.anchored_rate < 1.0
    assert score.aggregate.excerpts_anchored == 0
    # The problem is surfaced with the §7.2 traceability label, not silently dropped.
    assert any("traceability" in p for p in score.docs[0].problems)


def test_floor_counts_grounding(tmp_path):
    """§7.1: every statement here cites evidence, so grounded == total."""
    corpus = tmp_path / "grounded"
    _write_doc(corpus, "doc-a", excerpt="Its keeper recorded the weather twice a day")

    score = eval_mod.score_corpus(corpus)

    assert score.aggregate.statements_total == 1
    assert score.aggregate.statements_grounded == 1
    assert score.aggregate.grounded_rate == 1.0


def test_footnote_excerpt_anchors_against_footnote_stream(tmp_path):
    """Smoke corpus exercises the footnote stream too — assert it anchors there."""
    score = eval_mod.score_corpus(FIXTURE)
    assert score.aggregate.anchored_rate == 1.0
    assert score.aggregate.excerpts_anchored == 4


def test_unreadable_notes_count_as_schema_problem(tmp_path):
    """A malformed notes file is scored as a schema problem, not a crash."""
    corpus = tmp_path / "broken"
    extract = corpus / "doc-a" / "1-extract"
    extract.mkdir(parents=True, exist_ok=True)
    (corpus / "doc-a" / "source-pages.yaml").write_text("pages: []\n", encoding="utf-8")
    (extract / "page-0000.notes.yaml").write_text("[ not: valid: mapping", encoding="utf-8")

    score = eval_mod.score_corpus(corpus)
    assert score.aggregate.schema_problems >= 1


# --- completeness (ADR-007 completeness-aware floor) ---------------------------


def _write_completeness_doc(
    corpus: Path, doc_id: str, *, expected_indices: list[int], present_indices: list[int]
) -> None:
    """Author a multi-page doc with explicit ``expected_notes`` markers.

    Every page in ``expected_indices`` is marked ``expected_notes: true`` in the
    source-pages manifest; only the pages in ``present_indices`` get a notes file. A
    page expected but not present is the failed/stale gap the completeness check
    surfaces. Each notes-set's lone statement cites its one verbatim excerpt, so
    anchoring/grounding are 1.0 over whatever notes exist.
    """
    doc_dir = corpus / doc_id
    extract = doc_dir / "1-extract"
    extract.mkdir(parents=True, exist_ok=True)
    pages = [
        {
            "page_index": i,
            "expected_notes": i in expected_indices,
            "text": _SOURCE_TEXT,
            "footnotes": "",
        }
        for i in sorted(set(expected_indices) | set(present_indices))
    ]
    (doc_dir / "source-pages.yaml").write_text(
        yaml.safe_dump({"pages": pages}), encoding="utf-8"
    )
    for i in present_indices:
        notes = {
            "schema_version": 1,
            "source": {"document": doc_id, "scope": "page", "page_index": i},
            "terms": [],
            "evidence": [
                {"id": "e-1", "kind": "text",
                 "excerpt": "The lighthouse at Cragmouth was first lit in 1869.",
                 "source": "body"}
            ],
            "statements": [
                {"id": "s-1", "type": "claim", "text": "A claim.", "evidence": ["e-1"]}
            ],
            "relations": [],
        }
        (extract / f"page-{i:04d}.notes.yaml").write_text(
            yaml.safe_dump(notes, sort_keys=False), encoding="utf-8"
        )


def test_all_expected_pages_present_scores_complete(tmp_path):
    """Every expected page has notes → complete, no MISSING, complete_rate 1.0."""
    corpus = tmp_path / "complete"
    _write_completeness_doc(
        corpus, "doc-a", expected_indices=[0, 1, 2], present_indices=[0, 1, 2]
    )

    score = eval_mod.score_corpus(corpus)
    doc = score.docs[0]

    assert doc.is_complete
    assert doc.missing_pages == []
    assert doc.expected_pages == [0, 1, 2]
    assert doc.present_pages == [0, 1, 2]
    assert score.aggregate.complete_rate == 1.0
    assert score.aggregate.pages_expected == 3
    assert score.aggregate.pages_present == 3


def test_missing_expected_page_flags_incomplete(tmp_path):
    """An expected page with no notes file → incomplete, MISSING lists it, NOT a clean 100%."""
    corpus = tmp_path / "partial"
    _write_completeness_doc(
        corpus, "doc-a", expected_indices=[0, 1, 2, 3], present_indices=[0, 2]
    )

    score = eval_mod.score_corpus(corpus)
    doc = score.docs[0]

    assert not doc.is_complete
    assert doc.missing_pages == [1, 3]
    assert doc.present_pages == [0, 2]
    # The gap is surfaced as a problem, not silently dropped from the denominator.
    assert any("completeness" in p for p in doc.problems)
    # And the corpus does NOT read as a clean 100% even though every present note anchors.
    assert score.aggregate.anchored_rate == 1.0
    assert score.aggregate.complete_rate < 1.0
    assert score.aggregate.pages_expected == 4
    assert score.aggregate.pages_present == 2


def test_smoke_corpus_without_markers_scores_complete(tmp_path):
    """Backward-compat: a corpus with NO expected markers fabricates no gap (smoke corpus)."""
    score = eval_mod.score_corpus(FIXTURE)
    doc = score.docs[0]

    assert doc.is_complete
    assert doc.missing_pages == []
    # Expected falls back to the pages that have notes, so present == expected.
    assert doc.expected_pages == doc.present_pages
    assert score.aggregate.complete_rate == 1.0


def test_completeness_is_in_the_fingerprint(tmp_path):
    """Coverage is part of the instrument fingerprint's floor counts (ADR-007)."""
    corpus = tmp_path / "fp-complete"
    _write_completeness_doc(
        corpus, "doc-a", expected_indices=[0, 1], present_indices=[0]
    )

    fp = eval_mod.score_corpus(corpus).fingerprint
    assert fp.floor_counts.pages_expected == 2
    assert fp.floor_counts.pages_present == 1


# --- determinism ---------------------------------------------------------------


def test_same_corpus_yields_identical_score_bar_timestamp(tmp_path):
    """Reproducibility (ADR-007): same corpus bytes → identical score, timestamp aside.

    Pin ``now`` so even the timestamp matches, then compare the full serialised JSON.
    """
    corpus = tmp_path / "repro"
    _write_doc(corpus, "doc-a", excerpt="Its keeper recorded the weather twice a day")
    _write_doc(corpus, "doc-b", excerpt="the lamp burned whale oil")
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)

    first = eval_mod.to_json(eval_mod.score_corpus(corpus, now=fixed))
    second = eval_mod.to_json(eval_mod.score_corpus(corpus, now=fixed))

    assert first == second


def test_fingerprint_carries_corpus_id_version_and_counts(tmp_path):
    """Every reading carries its instrument fingerprint (ADR-007) — uninterpretable without it."""
    corpus = tmp_path / "fp"
    _write_doc(corpus, "doc-a", excerpt="The lighthouse at Cragmouth was first lit in 1869.")

    fp = eval_mod.score_corpus(corpus).fingerprint
    assert fp.corpus_id == "fp"
    assert fp.corpus_hash  # non-empty hash of the doc list
    assert fp.tool_version  # build identity
    assert fp.floor_counts.excerpts_total == 1


def test_corpus_hash_changes_when_doc_set_changes(tmp_path):
    """A corpus that gained a doc is a *different instrument* — its hash differs."""
    one = tmp_path / "one"
    _write_doc(one, "doc-a", excerpt="the lamp burned whale oil")
    two = tmp_path / "two"
    _write_doc(two, "doc-a", excerpt="the lamp burned whale oil")
    _write_doc(two, "doc-b", excerpt="Its keeper recorded the weather twice a day")

    assert (
        eval_mod.score_corpus(one).fingerprint.corpus_hash
        != eval_mod.score_corpus(two).fingerprint.corpus_hash
    )


# --- the smoke corpus through the CLI ------------------------------------------


def test_smoke_corpus_through_cli_produces_a_score(tmp_path):
    """The public smoke corpus runs end to end through `tnotes eval` (CliRunner)."""
    json_out = tmp_path / "score.json"
    result = runner.invoke(
        cli.app, ["eval", "--corpus", str(FIXTURE), "--json", str(json_out)]
    )
    assert result.exit_code == 0, result.output
    # The output labels itself a maintainer instrument, floor-only, never a gate.
    assert "instrument" in result.output.lower()
    assert "AGGREGATE" in result.output

    written = json.loads(json_out.read_text(encoding="utf-8"))
    assert written["kind"] == "floor-only"
    assert written["aggregate"]["anchored_rate"] == 1.0
    assert written["fingerprint"]["corpus_id"] == "eval-smoke"


def test_eval_uses_config_corpus_when_no_flag(tmp_path, monkeypatch):
    """`tnotes eval` falls back to the private `eval_corpus_dir` config when no --corpus."""
    monkeypatch.setenv("TN_CONFIG_DIR", str(tmp_path / "cfg"))
    config.set_eval_corpus_dir(str(FIXTURE))

    result = runner.invoke(cli.app, ["eval"])
    assert result.exit_code == 0, result.output
    assert "eval-smoke" in result.output


def test_eval_errors_clearly_with_no_corpus(tmp_path, monkeypatch):
    """No --corpus and no config → a clear error, not a stack trace."""
    monkeypatch.setenv("TN_CONFIG_DIR", str(tmp_path / "empty-cfg"))
    result = runner.invoke(cli.app, ["eval"])
    assert result.exit_code == 1
    assert "no corpus" in result.output.lower()


# --- eval add-doc capture round-trip (#92) -------------------------------------


def _fake_pages(specs):
    """Build PageText-like stand-ins for a mocked ingest.read_pages.

    ``specs`` is a list of ``(page_index, page_type, text)`` tuples. Uses the real
    PageText so the capture sees the same shape ingest returns.
    """
    from trustworthy_notes.models import PageText

    return [
        PageText(page_index=i, page_number=i + 1, text=text, width=0.0, height=0.0,
                 page_type=ptype)
        for i, ptype, text in specs
    ]


def test_add_doc_round_trip_captures_notes_and_expected_markers(tmp_path, monkeypatch):
    """`eval add-doc` captures a doc's notes + source-pages with expected markers, then
    `eval` scores it — a full round-trip with ingest.read_pages mocked.
    """
    from trustworthy_notes import eval_adddoc

    # A synthetic .tnotes workspace: a stub PDF beside its extracted notes. Pages 0 and
    # 1 are text (expected); page 2 is a figure (not expected). Only page 0 got notes —
    # page 1 is an expected-but-missing gap.
    doc = tmp_path / "Foo.pdf"
    doc.write_bytes(b"%PDF-1.4 stub")
    work = tmp_path / "Foo.pdf.tnotes"
    extract = work / "1-extract"
    extract.mkdir(parents=True)
    notes = {
        "schema_version": 1,
        "source": {"document": "Foo.pdf", "scope": "page", "page_index": 0},
        "terms": [],
        "evidence": [{"id": "e-1", "kind": "text",
                      "excerpt": "The lighthouse at Cragmouth was first lit in 1869.",
                      "source": "body"}],
        "statements": [{"id": "s-1", "type": "claim", "text": "A claim.", "evidence": ["e-1"]}],
        "relations": [],
    }
    (extract / "page-0000.notes.yaml").write_text(
        yaml.safe_dump(notes, sort_keys=False), encoding="utf-8"
    )

    monkeypatch.setattr(
        eval_adddoc.ingest, "read_pages",
        lambda _pdf: _fake_pages([
            (0, "text", _SOURCE_TEXT),
            (1, "text", "Another text page that should have notes."),
            (2, "figure", "A figure caption."),
        ]),
    )

    corpus = tmp_path / "corpus"
    result = eval_adddoc.capture_doc(doc=doc, corpus_dir=corpus)

    # The notes were copied and the source-pages.yaml written with expected markers.
    assert (corpus / "Foo.pdf" / "1-extract" / "page-0000.notes.yaml").is_file()
    assert result.expected_pages == [0, 1]
    assert result.pages_captured == [0]
    assert result.missing_pages == [1]  # page 1 is expected text but has no notes

    # eval reads what the capture wrote and scores it — page 1 surfaces as missing.
    score = eval_mod.score_corpus(corpus)
    captured = score.docs[0]
    assert captured.expected_pages == [0, 1]
    assert captured.present_pages == [0]
    assert captured.missing_pages == [1]
    assert not captured.is_complete
    # Page 0's excerpt anchors against the real source text the capture wrote.
    assert captured.counts.excerpts_anchored == 1


def test_add_doc_through_cli_reports_incomplete(tmp_path, monkeypatch):
    """`tnotes eval-add-doc` CLI captures and reports the incomplete gap (#92)."""
    from trustworthy_notes import eval_adddoc

    doc = tmp_path / "Bar.pdf"
    doc.write_bytes(b"%PDF-1.4 stub")
    extract = tmp_path / "Bar.pdf.tnotes" / "1-extract"
    extract.mkdir(parents=True)
    notes = {
        "schema_version": 1,
        "source": {"document": "Bar.pdf", "scope": "page", "page_index": 0},
        "terms": [], "evidence": [], "statements": [], "relations": [],
    }
    (extract / "page-0000.notes.yaml").write_text(
        yaml.safe_dump(notes, sort_keys=False), encoding="utf-8"
    )
    monkeypatch.setattr(
        eval_adddoc.ingest, "read_pages",
        lambda _pdf: _fake_pages([(0, "text", "p0"), (1, "text", "p1")]),
    )

    corpus = tmp_path / "corpus"
    result = runner.invoke(
        cli.app, ["eval-add-doc", "--doc", str(doc), "--corpus", str(corpus)]
    )
    assert result.exit_code == 0, result.output
    assert "INCOMPLETE" in result.output
    assert "MISSING" in result.output


def test_eval_report_shows_missing_for_incomplete_corpus(tmp_path):
    """The `tnotes eval` report surfaces MISSING and the INCOMPLETE banner."""
    corpus = tmp_path / "partial"
    _write_completeness_doc(
        corpus, "doc-a", expected_indices=[0, 1, 2], present_indices=[0]
    )

    result = runner.invoke(cli.app, ["eval", "--corpus", str(corpus)])
    assert result.exit_code == 0, result.output
    assert "MISSING" in result.output
    assert "INCOMPLETE" in result.output


# --- import isolation (ADR-007 Invariant 5) ------------------------------------


def _imported_names(module) -> set[str]:
    """The bare module names imported by ``module`` (ImportFrom + Import)."""
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[-1])
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[-1])
    return names


def test_eval_does_not_import_the_pipeline():
    """ADR-007: the only inbound arrow is cli → eval; eval never reaches into the pipeline.

    eval → validation/normalize is required (reuse the real floor); but importing
    pipeline/extract/compose — or ingest — would couple a corpus-private grade to the
    deterministic extraction path (Invariant 5).
    """
    imported = _imported_names(eval_mod)
    assert imported.isdisjoint({"pipeline", "extract", "compose", "ingest"})


def test_pipeline_and_extract_do_not_import_eval():
    """ADR-007: pipeline.py / extract.py must NEVER import eval (a forbidden arrow)."""
    from trustworthy_notes import extract as extract_mod
    from trustworthy_notes import pipeline as pipeline_mod

    assert "eval" not in _imported_names(pipeline_mod)
    assert "eval" not in _imported_names(extract_mod)


def test_eval_does_not_import_the_adddoc_capture(tmp_path):
    """`eval` stays isolated: the #92 add-doc capture is a separate, optional arrow.

    The ingest-using capture lives cli-side in `eval_adddoc`; `eval` reads the markers
    it wrote but never imports it (so `eval`'s import set stays what the #83 test asserts).
    """
    assert "eval_adddoc" not in _imported_names(eval_mod)


def test_adddoc_capture_uses_ingest_but_not_the_pipeline():
    """ADR-007: `eval_adddoc` MAY use `ingest` (capture is cli-side) but never the
    extraction pipeline. The ingest use is proved by the round-trip test (which
    monkeypatches `eval_adddoc.ingest.read_pages`); here we assert it imports ingest
    AND that it never reaches into the extraction path (pipeline/extract/compose).
    """
    from trustworthy_notes import eval_adddoc

    assert hasattr(eval_adddoc, "ingest")  # capture reads source streams via ingest
    imported = _imported_names(eval_adddoc)
    assert imported.isdisjoint({"pipeline", "extract", "compose", "eval_capture"})
