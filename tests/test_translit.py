"""Unit tests for the MdC transliteration mapping (no PDF needed)."""

from __future__ import annotations

import pytest

from trustworthy_notes.translit import is_transliteration_font, mdc_to_unicode


@pytest.mark.parametrize(
    "mdc, expected",
    [
        ("NTr-nfr", "Nṯr-nfr"),          # the page-92 example: nṯr-nfr ("perfect god")
        ("Hm.t=f", "ḥm.t=f"),            # ḥmt = wife
        ("jrj.t xt nswt", "jrj.t ḫt nswt"),  # royal acquaintance
        ("Nfr-Htp.s", "Nfr-ḥtp.s"),
        ("sX n sanx", "sẖ n sꜥnḫ"),
    ],
)
def test_mdc_to_unicode(mdc, expected):
    assert mdc_to_unicode(mdc) == expected


@pytest.mark.parametrize(
    "mdc, expected",
    [
        ("#wtj", "Ḫwtj"),               # leading capital Ḫ (was leaking as '#')
        ("%nnw", "Snnw"),               # plain capital S (was '%')
        ("+Atjj", "Ḏꜣtjj"),             # capital Ḏ + aleph (was '+')
        ("*Awtj", "Ṯꜣwtj"),             # capital Ṯ (was '*')
        ("@wt-Hr", "Ḥwt-ḥr"),           # Hathor: @→Ḥ; 2nd sign is lowercase key H→ḥ
        ("$nmw", "H̱nmw"),         # Khnum: $→H̱ (H + combining macron below)
        ("Jm-Htp", "Jm-ḥtp"),           # Imhotep
        ("anx-HA.f", "ꜥnḫ-ḥꜣ.f"),        # Ankhhaf
        ("%bk-Htp", "Sbk-ḥtp"),         # Sobekhotep
        ("^Stj", "Šštj"),               # ^→Š followed by S→š
    ],
)
def test_capital_and_punctuation_signs(mdc, expected):
    assert mdc_to_unicode(mdc) == expected


def test_real_punctuation_in_run_preserved():
    # hyphen, period, parens and the suffix '=' are real punctuation, not signs
    assert mdc_to_unicode("Nj-anx (P 067)") == "Nj-ꜥnḫ (P 067)"
    assert mdc_to_unicode("Hm.t=f") == "ḥm.t=f"


def test_case_and_punctuation_preserved():
    # capital name-initial N is kept; only the special signs change
    assert mdc_to_unicode("N")[0] == "N"
    assert mdc_to_unicode("[Hm].t=f") == "[ḥm].t=f"


def test_plain_text_unchanged():
    assert mdc_to_unicode("his wife") == "his wife"


def test_idempotent_on_unicode():
    once = mdc_to_unicode("NTr-nfr")
    assert mdc_to_unicode(once) == once


def test_font_detection():
    assert is_transliteration_font("CBEOHM+Transliteration,Italic")
    assert not is_transliteration_font("CBEOCJ+TimesNewRoman")
    assert not is_transliteration_font(None)
