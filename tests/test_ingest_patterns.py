"""Wave-0 pattern fixes: running-header detection and line-break de-hyphenation."""

from __future__ import annotations

from trustworthy_notes.ingest import _dehyphenate, _detect_running_headers, _looks_like_header


# --- header styling ---------------------------------------------------------

def test_looks_like_header_caps():
    assert _looks_like_header("CHAPTER 1: AIMS AND OBJECTIVES")
    assert _looks_like_header("TABLE B: DEPICTIONS OF WIVES")


def test_looks_like_header_rejects_body_and_short():
    assert not _looks_like_header("The basic aim of the study is to examine")
    assert not _looks_like_header("3")          # page label
    assert not _looks_like_header("a.")         # too few letters


# --- header detection: caps OR repetition -----------------------------------

def test_detects_caps_header_even_when_it_appears_once():
    # A short chapter's interior header recurs only once — caps styling catches it.
    tops = ["CHAPTER 1: AIMS AND OBJECTIVES", "Some ordinary body first line here",
            "Another quite different body opening sentence"]
    assert _detect_running_headers(tops) == {"CHAPTER 1: AIMS AND OBJECTIVES"}


def test_detects_repeated_mixed_case_header():
    tops = ["running foot text", "running foot text", "a unique body line"]
    assert "running foot text" in _detect_running_headers(tops)


def test_leaves_one_off_mixed_case_body_line():
    tops = ["A unique mixed-case opening sentence", "Another unrelated body line"]
    assert _detect_running_headers(tops) == set()


# --- de-hyphenation ---------------------------------------------------------

def test_dehyphenates_compound_across_linebreak():
    assert _dehyphenate(["between half-", "siblings, are known"]) == [
        "between half-siblings, are known"
    ]


def test_keeps_hyphen_for_egyptian_name():
    assert _dehyphenate(["chapel of Nfr-", "kꜣ(.j) (G 24"]) == ["chapel of Nfr-kꜣ(.j) (G 24"]


def test_does_not_join_when_next_line_is_a_number():
    # "of their sons-\n4.5.1 Data" — a dash before a section number, not a hyphenation.
    assert _dehyphenate(["of their sons-", "4.5.1 Data section"]) == [
        "of their sons-",
        "4.5.1 Data section",
    ]
