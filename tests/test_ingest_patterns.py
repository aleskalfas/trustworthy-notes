"""Wave-0 pattern fixes: running-header detection and line-break de-hyphenation."""

from __future__ import annotations

from trustworthy_notes.ingest import (
    _dehyphenate,
    _detect_running_headers,
    _looks_like_header,
    _split_word_on_char_gaps,
)


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


# --- word re-splitting from char gaps (#22) ---------------------------------
#
# Some PDF text layers set inter-word gaps below pdfplumber's `x_tolerance`, so
# `extract_words` merges adjacent words into one token. `_split_word_on_char_gaps`
# recovers the breaks from the raw chars: intra-word char gaps sit near zero while
# word gaps are wider, and a font-relative threshold lands in the empty valley.

_SIZE = 10.0
_CHAR_W = 4.0  # each synthetic glyph is this wide


def _chars_with_gaps(text: str, gaps: list[float], top: float = 100.0) -> list[dict]:
    """Lay out one char per `text` letter, with `gaps[i]` of space *before* char i.

    Mimics pdfplumber char dicts: each carries x0/x1/top/bottom/size/text, with
    glyphs of fixed width separated by the requested horizontal gaps (gaps[0]==0).
    """
    assert len(gaps) == len(text) and gaps[0] == 0
    chars = []
    x = 0.0
    for ch, gap in zip(text, gaps):
        x += gap
        chars.append(
            {"text": ch, "x0": x, "x1": x + _CHAR_W, "top": top, "bottom": top + _SIZE, "size": _SIZE}
        )
        x += _CHAR_W
    return chars


def _word_over(chars: list[dict]) -> dict:
    """A merged `extract_words`-style token spanning all of `chars` on one line."""
    return {
        "text": "".join(c["text"] for c in chars),
        "x0": chars[0]["x0"],
        "x1": chars[-1]["x1"],
        "top": chars[0]["top"],
        "bottom": chars[0]["bottom"],
        "size": _SIZE,
        "fontname": "Body",
    }


def test_splits_run_together_words_on_subtolerance_gaps():
    # "andLLMs" merged: word gap ~2.2pt (below pdfplumber's x_tolerance=3), intra ~0.
    text = "andLLMs"
    gaps = [0.0, 0.0, 0.0, 2.2, 0.0, 0.0, 0.0]  # break before the 'L'
    word = _word_over(_chars_with_gaps(text, gaps))
    pieces = [w["text"] for w in _split_word_on_char_gaps(word, _chars_with_gaps(text, gaps))]
    assert pieces == ["and", "LLMs"]


def test_split_preserves_word_metadata():
    text = "andLLMs"
    gaps = [0.0, 0.0, 0.0, 2.2, 0.0, 0.0, 0.0]
    word = _word_over(_chars_with_gaps(text, gaps))
    out = _split_word_on_char_gaps(word, _chars_with_gaps(text, gaps))
    # each sub-word keeps the parent's font/size/line (so translit + footnote
    # logic still see the same attributes), only text/x are recomputed.
    for sub in out:
        assert sub["fontname"] == "Body"
        assert sub["size"] == _SIZE
        assert sub["top"] == word["top"]
    assert out[1]["x0"] > out[0]["x1"]


def test_does_not_oversplit_normal_word():
    # A normal word has near-zero intra-char gaps; it must stay one token.
    text = "balance"
    gaps = [0.0] * len(text)
    word = _word_over(_chars_with_gaps(text, gaps))
    pieces = [w["text"] for w in _split_word_on_char_gaps(word, _chars_with_gaps(text, gaps))]
    assert pieces == ["balance"]


def test_does_not_split_hyphenated_compound():
    # "brain-to-body": hyphen glyph is a real char with tight gaps, not a word break.
    text = "brain-to-body"
    gaps = [0.0] * len(text)
    word = _word_over(_chars_with_gaps(text, gaps))
    pieces = [w["text"] for w in _split_word_on_char_gaps(word, _chars_with_gaps(text, gaps))]
    assert pieces == ["brain-to-body"]


def test_split_recovers_multiple_words():
    # Three words run together, each separated by a sub-tolerance gap.
    text = "SLMsbyanalogy"
    gaps = [0.0, 0.0, 0.0, 0.0, 2.2, 0.0, 2.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    word = _word_over(_chars_with_gaps(text, gaps))
    pieces = [w["text"] for w in _split_word_on_char_gaps(word, _chars_with_gaps(text, gaps))]
    assert pieces == ["SLMs", "by", "analogy"]


def test_single_char_token_unchanged():
    # A lone glyph (e.g. a bullet) has no internal gap to split on.
    chars = _chars_with_gaps("a", [0.0])
    word = _word_over(chars)
    assert _split_word_on_char_gaps(word, chars) == [word]
