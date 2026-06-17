"""Unit tests for the evidence-anchoring normalizer.

These need no PDF; they pin the matching contract resolved during the Wave 1
hand-simulation (see design note, open-question 2).
"""

from __future__ import annotations

import pytest

from trustworthy_notes.normalize import normalize_for_match, quote_is_anchored


def test_collapses_softwrap_newlines():
    wrapped = "The subjects of this\nstudy are the female\nmembers."
    assert normalize_for_match(wrapped) == "The subjects of this study are the female members."


def test_drops_pua_bullet_glyph():
    # U+F0B7 is the Symbol-font list bullet seen on printed p.3.
    assert normalize_for_match("a  b") == "a b"


def test_strips_glued_superscript_ref_marker():
    assert normalize_for_match("Gay Robins1, Watterson2") == "Gay Robins, Watterson"
    assert normalize_for_match("Ancient Egypt10 contains") == "Ancient Egypt contains"


@pytest.mark.parametrize(
    "text",
    [
        "Robins (1993).",       # digit after "(" — not glued to a letter
        "P. BM 1",              # digit after a space
        "1.1 The place",        # section number, leading
        "Capel-Markoe (1996: 36).",  # year inside parens
    ],
)
def test_real_numbers_survive(text):
    assert normalize_for_match(text) == text


def test_folds_typographic_punctuation():
    # Curly quotes, dashes and ellipsis fold to ASCII so a faithfully-retyped
    # quotation anchors regardless of glyph variant.
    assert normalize_for_match("‘Oddly’ — really…") == "'Oddly' - really..."
    assert normalize_for_match("Capel–Markoe") == "Capel-Markoe"


def test_straight_quote_anchors_against_curly_stream():
    stream = "the tomb ‘Oddly, marriage did not exist’ as stated"
    assert quote_is_anchored("'Oddly, marriage did not exist'", stream)


def test_idempotent():
    s = "Gay Robins1\n  Watterson2  spans   lines"
    once = normalize_for_match(s)
    assert normalize_for_match(once) == once


def test_quote_is_anchored_against_wrapped_stream():
    stream = "These include studies by Gay Robins1, Watterson2,\nTyldesley3, Lesko4 and Hawass5."
    assert quote_is_anchored("Tyldesley, Lesko and Hawass", stream)
    assert not quote_is_anchored("Tyldesley, Lesko and Petrie", stream)


def test_footnote_ref_markers_ignored_in_anchoring():
    # a quote anchors whether or not it spans an inserted [^N] reference marker
    stream = "These include studies by Gay Robins[^1], Watterson[^2], and Hawass[^5]."
    assert quote_is_anchored("Gay Robins, Watterson, and Hawass", stream)
    assert normalize_for_match("a[^13] b") == "a b"


def test_empty():
    assert normalize_for_match("") == ""
    assert normalize_for_match(None) == ""  # type: ignore[arg-type]
