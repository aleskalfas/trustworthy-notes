"""Wave 1 extractor tests.

The anchor-gate logic is tested with a synthetic page (no PDF). The end-to-end
path (extract -> gate -> validate) is tested by feeding the golden p.3 fixture
through a stub extractor against the real page; it SKIPS without the PDF.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from trustworthy_notes import ingest
from trustworthy_notes.extract import (
    LANGUAGE_MIXED,
    LANGUAGE_UNKNOWN,
    anchor_gate,
    roll_up_detected_language,
    run_extract,
    write_notes,
)
from trustworthy_notes.models import PageText
from trustworthy_notes.validation import validate_structure

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "notes.printed-p3.yaml"
PDFS = sorted((ROOT / "data").glob("*.pdf"))


class _StubExtractor:
    """A fake extractor that just replays a fixed notes-set (stands in for an LLM)."""

    def __init__(self, notes: dict):
        self._notes = notes

    def extract(self, page, context=None):
        return copy.deepcopy(self._notes)


# ---- anchor gate: synthetic, no PDF ----

def test_anchor_gate_drops_hallucinated_quote_and_its_statement():
    page = PageText(
        page_index=0, page_number=1, text="The cat sat on the mat.", width=1.0, height=1.0
    )
    notes = {
        "schema_version": 1,
        "source": {"document": "d", "page_index": 0},
        "terms": [{"id": "t-cat", "label": "cat"}, {"id": "t-dog", "label": "dog"}],
        "evidence": [
            {"id": "e-good", "excerpt": "cat sat", "source": "body"},
            {"id": "e-bad", "excerpt": "dog ran away", "source": "body"},
        ],
        "statements": [
            {"id": "s-good", "type": "claim", "text": "a cat sat", "terms": ["t-cat"], "evidence": ["e-good"]},
            {"id": "s-bad", "type": "claim", "text": "a dog ran", "terms": ["t-dog"], "evidence": ["e-bad"]},
        ],
        "relations": [{"from": "s-bad", "to": "s-good", "type": "contrasts"}],
    }
    cleaned, dropped = anchor_gate(notes, page)

    assert {s["id"] for s in cleaned["statements"]} == {"s-good"}
    assert {e["id"] for e in cleaned["evidence"]} == {"e-good"}
    assert {t["id"] for t in cleaned["terms"]} == {"t-cat"}   # orphan term pruned
    assert cleaned["relations"] == []                          # endpoint gone
    flagged = {(d["kind"], d["id"]) for d in dropped}
    assert ("evidence", "e-bad") in flagged
    assert ("statement", "s-bad") in flagged


def test_anchor_gate_keeps_statement_with_one_surviving_evidence():
    page = PageText(page_index=0, page_number=1, text="alpha beta gamma", width=1.0, height=1.0)
    notes = {
        "schema_version": 1, "source": {"document": "d", "page_index": 0}, "terms": [],
        "evidence": [
            {"id": "e-ok", "excerpt": "alpha beta", "source": "body"},
            {"id": "e-no", "excerpt": "not here", "source": "body"},
        ],
        "statements": [{"id": "s-1", "type": "claim", "text": "x", "evidence": ["e-ok", "e-no"]}],
        "relations": [],
    }
    cleaned, dropped = anchor_gate(notes, page)
    assert [s["id"] for s in cleaned["statements"]] == ["s-1"]
    assert cleaned["statements"][0]["evidence"] == ["e-ok"]  # bad ref pruned, statement kept
    assert {e["id"] for e in cleaned["evidence"]} == {"e-ok"}


def test_write_notes_round_trips(tmp_path):
    notes = {"schema_version": 1, "source": {"document": "d", "page_index": 0},
             "terms": [], "evidence": [], "statements": [], "relations": []}
    dest = tmp_path / "notes.yaml"
    write_notes(notes, dest)
    assert yaml.safe_load(dest.read_text()) == notes


# ---- generation provenance stamp (issue #98), synthetic page, no PDF ----


class _StubExtractorWithSettings:
    """A stub extractor exposing model/effort/max_tokens, like AnthropicExtractor."""

    def __init__(self, notes: dict, *, model: str, effort: str, max_tokens: int):
        self._notes = notes
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    def extract(self, page, context=None):
        return copy.deepcopy(self._notes)


def _synthetic_notes() -> dict:
    return {
        "schema_version": 1,
        "terms": [],
        "evidence": [{"id": "e-1", "excerpt": "alpha beta", "source": "body"}],
        "statements": [
            {"id": "s-1", "type": "claim", "text": "a claim", "evidence": ["e-1"]}
        ],
        "relations": [],
    }


def _synthetic_page() -> PageText:
    return PageText(
        page_index=0, page_number=1, text="alpha beta gamma",
        width=0.0, height=0.0, footnotes="",
    )


def test_run_extract_stamps_generation_and_stays_valid():
    """A note from an extractor with settings carries `generation` and validates."""
    extractor = _StubExtractorWithSettings(
        _synthetic_notes(), model="claude-x", effort="high", max_tokens=48000
    )
    notes, _ = run_extract(_synthetic_page(), extractor, document="d")

    assert notes["generation"] == {
        "model": "claude-x", "effort": "high", "max_tokens": 48000,
    }
    assert isinstance(notes["generation"]["max_tokens"], int)
    # The schema now declares `generation`, so a stamped note still passes structure.
    assert not validate_structure(notes)


def test_note_without_generation_still_validates():
    """Backward compat: a note lacking `generation` (pre-#98) is still schema-valid."""
    extractor = _StubExtractor(_synthetic_notes())  # no settings → no generation block
    notes, _ = run_extract(_synthetic_page(), extractor, document="d")

    assert "generation" not in notes
    assert not validate_structure(notes)


# ---- detected_language capture + carry-through (issue #115, ADR-008) ----


def test_anchor_gate_carries_detected_language_through_rebuild():
    """The gate rebuilds the notes dict from survivors; an additive top-level
    `detected_language` must survive that rebuild (the field most likely to be lost)."""
    page = PageText(page_index=0, page_number=1, text="alpha beta gamma", width=1.0, height=1.0)
    notes = {
        "schema_version": 1, "source": {"document": "d", "page_index": 0}, "terms": [],
        "evidence": [{"id": "e-1", "excerpt": "alpha beta", "source": "body"}],
        "statements": [{"id": "s-1", "type": "claim", "text": "x", "evidence": ["e-1"]}],
        "relations": [],
        "detected_language": "cs",
    }
    cleaned, _ = anchor_gate(notes, page)
    assert cleaned["detected_language"] == "cs"


def test_anchor_gate_omits_detected_language_when_absent():
    """Backward compat: notes with no detected_language stay without one after the gate."""
    page = PageText(page_index=0, page_number=1, text="alpha beta gamma", width=1.0, height=1.0)
    notes = {
        "schema_version": 1, "source": {"document": "d", "page_index": 0}, "terms": [],
        "evidence": [{"id": "e-1", "excerpt": "alpha beta", "source": "body"}],
        "statements": [{"id": "s-1", "type": "claim", "text": "x", "evidence": ["e-1"]}],
        "relations": [],
    }
    cleaned, _ = anchor_gate(notes, page)
    assert "detected_language" not in cleaned


def test_run_extract_carries_detected_language_and_stays_valid():
    """A page whose notes carry detected_language keeps it through extract and validates."""
    raw = {**_synthetic_notes(), "detected_language": "ja"}
    notes, _ = run_extract(_synthetic_page(), _StubExtractor(raw), document="d")
    assert notes["detected_language"] == "ja"
    assert not validate_structure(notes)


def test_note_without_detected_language_still_validates():
    """Backward compat: a note lacking detected_language (pre-#115) is schema-valid."""
    notes, _ = run_extract(_synthetic_page(), _StubExtractor(_synthetic_notes()), document="d")
    assert "detected_language" not in notes
    assert not validate_structure(notes)


# ---- doc-level detected-language roll-up (issue #115) ----


def test_roll_up_uniform_language():
    assert roll_up_detected_language(["cs", "cs", "cs"]) == "cs"


def test_roll_up_uniform_language_is_case_insensitive():
    assert roll_up_detected_language(["CS", "cs", " Cs "]) == "cs"


def test_roll_up_uniform_ignores_pages_without_a_language():
    # An unknown page is silent, not a contradiction: it does not veto agreement.
    assert roll_up_detected_language(["de", None, "de", ""]) == "de"


def test_roll_up_disagreement_is_mixed():
    assert roll_up_detected_language(["en", "cs"]) == LANGUAGE_MIXED


def test_roll_up_no_recorded_language_is_unknown():
    assert roll_up_detected_language([None, "", None]) == LANGUAGE_UNKNOWN
    assert roll_up_detected_language([]) == LANGUAGE_UNKNOWN


# ---- end to end against the real page (PDF-gated) ----

@pytest.mark.skipif(not PDFS, reason="no test PDF under data/ (gitignored)")
def test_run_extract_clean_fixture_passes_through():
    fixture = yaml.safe_load(FIXTURE.read_text())
    page = next(p for p in ingest.read_pages(PDFS[0]) if p.page_index == fixture["source"]["page_index"])
    notes, dropped = run_extract(page, _StubExtractor(fixture), fixture["source"]["document"])
    assert dropped == []                                   # every quote anchors
    assert not validate_structure(notes)                   # result is schema/ref valid
    assert len(notes["statements"]) == len(fixture["statements"])


@pytest.mark.skipif(not PDFS, reason="no test PDF under data/ (gitignored)")
def test_run_extract_drops_a_hallucinated_statement():
    fixture = yaml.safe_load(FIXTURE.read_text())
    bad = copy.deepcopy(fixture)
    # corrupt the sole evidence of a single-evidence statement so it can't anchor
    s = next(s for s in bad["statements"] if len(s["evidence"]) == 1)
    ev_id = s["evidence"][0]
    ev = next(e for e in bad["evidence"] if e["id"] == ev_id)
    ev["excerpt"] = "this phrase definitely does not occur on the page zzzqqq"

    page = next(p for p in ingest.read_pages(PDFS[0]) if p.page_index == fixture["source"]["page_index"])
    notes, dropped = run_extract(page, _StubExtractor(bad), fixture["source"]["document"])

    flagged = {(d["kind"], d["id"]) for d in dropped}
    assert ("evidence", ev_id) in flagged
    assert ("statement", s["id"]) in flagged
    assert s["id"] not in {st["id"] for st in notes["statements"]}
    assert not validate_structure(notes)  # still valid after gating
