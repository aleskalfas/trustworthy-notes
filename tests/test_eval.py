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
