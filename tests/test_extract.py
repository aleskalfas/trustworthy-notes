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
from trustworthy_notes.extract import anchor_gate, run_extract, write_notes
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
