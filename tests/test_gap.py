"""§7.6 gap-report tests."""

from __future__ import annotations

from types import SimpleNamespace

from trustworthy_notes.gap import gap_report


def _page(text="", footnotes=""):
    return SimpleNamespace(text=text, footnotes=footnotes)


def test_covered_sentence_is_not_a_gap():
    page = _page("The cat sat on the mat. The dog ran in the park.")
    notes = {"evidence": [{"excerpt": "The cat sat on the mat.", "source": "body"}]}
    rep = gap_report(notes, page)
    body = rep["body"]
    gap_texts = [g["text"] for g in body["gaps"]]
    assert any("dog ran" in g for g in gap_texts)       # uncovered sentence flagged
    assert all("cat sat" not in g for g in gap_texts)   # covered sentence not flagged
    assert 0.0 < body["ratio"] < 1.0


def test_full_coverage_has_no_gaps():
    page = _page("Alpha beta gamma delta epsilon. Zeta eta theta iota kappa.")
    notes = {
        "evidence": [
            {"excerpt": "Alpha beta gamma delta epsilon.", "source": "body"},
            {"excerpt": "Zeta eta theta iota kappa.", "source": "body"},
        ]
    }
    rep = gap_report(notes, page)
    assert rep["body"]["gaps"] == []           # every sentence covered
    assert rep["body"]["ratio"] >= 0.95        # only inter-sentence spaces uncovered


def test_curly_quote_stream_covered_by_straight_quote_excerpt():
    # Coverage uses the same normalization as anchoring: a straight-quote excerpt
    # covers a curly-quote sentence.
    page = _page("He said ‘marriage did not exist as a legal state’ in his book.")
    notes = {
        "evidence": [
            {"excerpt": "He said 'marriage did not exist as a legal state' in his book.", "source": "body"}
        ]
    }
    rep = gap_report(notes, page)
    assert rep["body"]["gaps"] == []


def test_empty_page_is_fully_covered():
    rep = gap_report({"evidence": []}, _page("", ""))
    assert rep["body"]["ratio"] == 1.0
    assert rep["footnotes"]["ratio"] == 1.0
