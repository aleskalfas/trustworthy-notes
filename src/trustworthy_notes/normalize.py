"""Text normalization for evidence anchoring.

The evidence contract (see design note, open-question 2): a concept's
``statement`` may paraphrase, but every ``evidence.quote`` is a VERBATIM span
lifted from a page. The validator (Wave 4) confirms a quote by *normalized
substring containment* against the cited stream — never fuzzy/semantic match.

Normalization is the single knob that decides what "verbatim" tolerates. It is
applied identically to both the stored quote (needle) and the extracted page
text (haystack), so it must be idempotent. It absorbs two artifacts that the
hand-simulation on printed p.3 surfaced in real pdfplumber output:

  1. Soft-wrap newlines. pdfplumber emits a newline at every visual line break;
     the same sentence reads across many lines. Collapsing all whitespace runs
     to a single space makes line-wrapping irrelevant to matching.

  2. Symbol-font bullet glyphs in the Unicode Private Use Area (e.g. U+F0B7,
     a list bullet). These carry no textual meaning and appear mid-stream
     between enumerated items; we drop them.

  3. Superscript footnote-reference markers glued to a word. In the body,
     "Gay Robins1" and "Ancient Egypt10" are the citation superscripts 1 and 10
     rendered at ~0.65x body size and rejoined without a space by
     extract_text(). The PRIMARY fix is upstream in ingest (it alone has the
     font-size/baseline data to strip them at extraction — see ingest TODO);
     this matcher rule is defense-in-depth so anchoring is robust even on
     un-cleaned text. It is deliberately narrow: only a 1-2 digit run *glued to
     a letter* and sitting at a token boundary is stripped, so real numbers
     survive — "(1993)" (digit after "("), "P. BM 1" (space before "1"),
     section "1.1" (after whitespace) are all untouched.
"""

from __future__ import annotations

import re

# Unicode Private Use Area (BMP block U+E000-U+F8FF) — Symbol/Wingdings-style
# decorative glyphs land here; the list bullet on printed p.3 is U+F0B7.
_PUA = re.compile("[\uE000-\uF8FF]")

# Explicit footnote-reference markers that ingest inserts (e.g. `[^13]`).
# They are metadata, not content, so they are removed for matching — a quote
# anchors whether or not it happens to span a reference marker.
_FOOTNOTE_REF = re.compile(r"\[\^\d+\]")

# A 1-2 digit run glued to the end of an alphabetic word, at a token boundary.
# Fallback for any superscript ingest didn't catch and convert to `[^N]`.
# Lookbehind requires a letter; lookahead requires whitespace/punct/end so we
# never bite into a longer digit run (years, page ranges) or letter+digit codes.
_SUPERSCRIPT_REF = re.compile(
    "(?<=[A-Za-z])\\d{1,2}(?=[\\s.,;:!?’'\"\\)\\]]|$)"
)

_WS = re.compile(r"\s+")

# Typographic punctuation → ASCII. The page is typeset with curly quotes (‘ ’),
# en/em dashes, and ellipses; an LLM faithfully RE-TYPING a quotation routinely
# emits the ASCII equivalents (' " - ...). Folding both sides to ASCII before the
# containment check lets a genuinely-verbatim quote anchor regardless of which
# glyph variant it carries — without weakening the check to fuzzy matching (only
# these fixed punctuation pairs are unified; letters/words must still match).
_PUNCT_FOLD = str.maketrans(
    {
        "‘": "'", "’": "'", "‚": "'", "‛": "'",  # single quotes
        "“": '"', "”": '"', "„": '"', "‟": '"',  # double quotes
        "–": "-", "—": "-", "―": "-", "−": "-",  # dashes / minus
        "…": "...",                                              # ellipsis
        " ": " ", " ": " ",                                # NBSP / narrow NBSP
    }
)


def normalize_for_match(text: str) -> str:
    """Canonicalize text for verbatim-quote containment checks.

    Idempotent: ``normalize_for_match(normalize_for_match(x)) ==
    normalize_for_match(x)``. Apply to both the quote and the page stream, then
    test ``quote in stream``.
    """
    if not text:
        return ""
    text = _PUA.sub(" ", text)
    text = text.translate(_PUNCT_FOLD)
    text = _FOOTNOTE_REF.sub("", text)
    text = _SUPERSCRIPT_REF.sub("", text)
    text = _WS.sub(" ", text)
    return text.strip()


def quote_is_anchored(quote: str, stream: str) -> bool:
    """True if ``quote`` occurs verbatim (post-normalization) in ``stream``.

    This is the atomic check Wave 4 runs per evidence item: the stream is the
    body or footnotes of the cited page, chosen by ``Evidence.source``.
    """
    return normalize_for_match(quote) in normalize_for_match(stream)
