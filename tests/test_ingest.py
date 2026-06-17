"""Regression tests for Wave 0 ingest layout handling.

Needs the gitignored source PDF; SKIPS when it's absent. read_pages over the
whole book is run once and reused (it's the slow part).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trustworthy_notes import ingest

ROOT = Path(__file__).resolve().parent.parent
PDFS = sorted((ROOT / "data").glob("*.pdf"))

pytestmark = pytest.mark.skipif(not PDFS, reason="no test PDF under data/ (gitignored)")


@pytest.fixture(scope="module")
def by_number() -> dict:
    return {p.page_number: p for p in ingest.read_pages(PDFS[0])}


@pytest.mark.parametrize(
    "page_number, expected_type",
    [(13, "blank"), (15, "text"), (22, "text"), (147, "figure"), (172, "table")],
)
def test_page_type_classification(by_number, page_number, expected_type):
    assert by_number[page_number].page_type == expected_type


def test_table_page_reads_rows_not_scrambled(by_number):
    table = by_number[172]
    assert table.page_type == "table"
    # the appendix rows must be present and in order, not zippered away
    assert "TABLE A" in table.text
    assert "G 060" in table.text
    assert table.text.index("G 060") < table.text.index("G 070")


def test_figure_page_keeps_captions_and_regions(by_number):
    fig = by_number[147]
    assert fig.page_type == "figure"
    assert fig.figure_regions, "figure page should record its drawing regions"
    assert "tomb owner" in fig.text  # caption text is still captured (region + caption)


def test_text_page_unaffected(by_number):
    page = by_number[15]
    assert page.page_type == "text"
    assert page.column_count == 2
    assert "10416" in page.text  # body intact, header stripped


def test_transliteration_restored_to_unicode(by_number):
    page = by_number[92]
    assert "Nṯr-nfr" in page.text       # MdC `NTr` restored to the real sign ṯ
    assert "NTr-nfr" not in page.text   # the flattened ASCII form is gone


def test_inline_drawn_glyph_gets_placeholder(by_number):
    page = by_number[93]
    # the determinative drawn as vector art becomes a stable, copyable placeholder
    assert "determinative ⟨glyph-" in page.text
    assert page.glyphs, "the drawn glyph's region must be recorded"
    g = page.glyphs[0]
    assert len(g["id"]) == 8 and len(g["bbox"]) == 4
    # placeholder id in text matches the registry id (reversible for OCR later)
    assert f"⟨glyph-{g['id']}⟩" in page.text


def test_no_spurious_glyphs_on_plain_text_page(by_number):
    assert by_number[15].glyphs == []


def test_footnote_references_marked_not_confused_with_numbers(by_number):
    p92 = by_number[92].text
    assert "[^739]" in p92          # a superscript reference → explicit marker
    assert "S 216" in p92           # a real catalogue number stays a number
    assert "CG 1447" in p92
    p15 = by_number[15].text
    assert "[^13]" in p15
    assert "10416" in p15           # the P.BM document number (body size) is untouched
    assert "[^10416]" not in p15
