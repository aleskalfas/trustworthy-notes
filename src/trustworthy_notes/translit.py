"""Egyptological transliteration: restore the real signs from MdC codes.

Egyptology PDFs typically set transliteration in a dedicated font (here
``...+Transliteration``) using the *Manuel de Codage* (MdC) convention, where an
ASCII code stands for a special sign — `T` is **ṯ**, `H` is **ḥ**, `S` is **š**,
and so on. pdfplumber reads the ASCII code, so `nṯr-nfr` arrives flattened as
`NTr-nfr`, losing a scholarly distinction (ṯ and t are different consonants).

When ingest sees a run in the transliteration font, it routes the text through
``mdc_to_unicode`` to restore the signs. The map is **case-sensitive** and only
touches the special MdC codes; every other letter (and letter *case*, e.g. a
capitalised name initial like `N`) is left exactly as printed.

The table is the standard MdC / CCER-"Transliteration" mapping. If a particular
font deviates, this is the one place to adjust — verify against the rendered
page (see the `render` command) before trusting a new sign.
"""

from __future__ import annotations

# Font code -> Unicode transliteration sign. Only codes that draw a special sign
# or a capital; plain punctuation in a transliteration run (- . ( ) = [ ] , ; /)
# is real and left untouched. The capital/punctuation positions were recovered by
# rasterising the embedded font and reading the glyphs (the cmap names are useless
# — code 0x23 is stored as "numbersign" but *draws* Ḫ), cross-checked against known
# names (Jm-Htp→Jm-ḥtp Imhotep, $nmw→H̱nmw Khnum, @wt-Hr→Ḥwt-Ḥr Hathor).
_MDC: dict[str, str] = {
    # MdC letter keys — a Shift-letter draws the special consonant.
    "A": "ꜣ",  # aleph        U+A723
    "a": "ꜥ",  # ayin         U+A725
    "H": "ḥ",  # h with dot   U+1E25
    "x": "ḫ",  # h with breve U+1E2B
    "X": "ẖ",  # h with line  U+1E96
    "S": "š",  # s with caron U+0161
    "T": "ṯ",  # t with line  U+1E6F
    "D": "ḏ",  # d with line  U+1E0F
    "q": "ḳ",  # k with dot   U+1E33
    "I": "Ꞽ",  # capital yod  U+A7BC
    # Capital signs sit on punctuation codes (used for name initials). The older
    # table omitted these, so they leaked into notes as literal # % + * © @ $.
    "@": "Ḥ",        # H dot below    U+1E24
    "#": "Ḫ",        # H breve below  U+1E2A
    "$": "H̱",  # H line below   (no precomposed capital; H + U+0331)
    "^": "Š",        # S caron        U+0160
    "*": "Ṯ",        # T line below   U+1E6E
    "+": "Ḏ",        # D line below   U+1E0E
    "©": "Ḏ",        # D line below   (alternate code)
    "!": "H",        # plain capital H
    "%": "S",        # plain capital S
    "&": "T",        # plain capital T
    "_": "D",        # plain capital D
    # Latin-1 block (0xA1–0xA7): alternate positions mirroring the above.
    "¡": "Ḥ", "¢": "Ḫ", "£": "H̱", "¤": "S", "¥": "Š", "¦": "T", "§": "Ṯ",
}


def mdc_to_unicode(text: str) -> str:
    """Map Manuel-de-Codage transliteration codes to Unicode signs.

    Idempotent for already-Unicode text (the signs aren't MdC codes). Leaves
    all non-special characters — including letter case and punctuation — intact.
    """
    return "".join(_MDC.get(ch, ch) for ch in text)


# Marker that a font is the transliteration font (matched as a substring of the
# pdfplumber `fontname`, which carries a random subset prefix like 'CBEOHM+').
TRANSLITERATION_FONT_HINT = "Transliteration"


def is_transliteration_font(fontname: str | None) -> bool:
    return bool(fontname) and TRANSLITERATION_FONT_HINT in fontname
