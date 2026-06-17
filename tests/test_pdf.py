"""Wave 4 PDF rendering — bookmarks + internal links, no network."""

from __future__ import annotations

import pdfplumber
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfparser import PDFParser

from trustworthy_notes.pdf import markdown_to_pdf

MD = """# Demo — Study Notes
*doc · PDF pages 13–16*

## Contents

- [1. Background](#sec-1)
  - [1.1. Detail](#sec-1-1)

<a id="sec-1"></a>
## 1. Background

- a point citing [s-1](#note-s-1) and **bold** text

<a id="sec-1-1"></a>
### 1.1. Detail

- more, see [s-1](#note-s-1)

---
## Notes & Sources

<a id="note-s-1"></a>
**[s-1]** _claim_ — kings had wives
> the king customarily had wives
> — p.3 (body)
"""


def test_markdown_to_pdf_has_pages_bookmarks_and_links(tmp_path):
    out = tmp_path / "doc.pdf"
    markdown_to_pdf(MD, out)
    assert out.is_file()

    with open(out, "rb") as f:
        doc = PDFDocument(PDFParser(f))
        outlines = list(doc.get_outlines())
    # one bookmark per ## / ### heading: Contents, 1. Background, 1.1. Detail, Notes & Sources
    assert len(outlines) == 4
    titles = [t for _, t, *_ in outlines]
    assert any("Background" in t for t in titles)
    assert all("*" not in t for t in titles)   # emphasis stripped from bookmark titles

    pdf = pdfplumber.open(out)
    annots = [a for pg in pdf.pages for a in (pg.annots or [])]
    assert len(annots) >= 3   # internal Contents + [s-N] link annotations present


def test_embedded_serif_registered_and_covers_glyphs():
    import trustworthy_notes.pdf as pdfmod
    from reportlab.pdfbase import pdfmetrics
    # the bundled full-coverage serif is the document font (not Helvetica)
    assert pdfmod._FONT == "Charis"
    face = pdfmetrics.getFont("Charis").face
    cmap = getattr(face, "charToGlyph", {})
    for ch in "ꜣꜥḥḫẖšṯḏḳ" + "ś" + "̱" + "Ꞽ":   # egyptological + ś + macron + capital yod
        assert ord(ch) in cmap, f"Charis missing U+{ord(ch):04X}"


def test_inline_leaves_unicode_unwrapped_with_full_coverage_font():
    # with one full-coverage font there is no per-glyph <font> wrapping; the
    # characters pass through unchanged (the base font draws them all)
    from trustworthy_notes.pdf import _inline
    out = _inline("H̱nmw-nḏm Myśliwiec sꜣ=s")
    assert "H̱nmw-nḏm Myśliwiec sꜣ=s" in out
    assert "<font" not in out


def test_inline_emphasis_bold_and_underscore_italic():
    from trustworthy_notes.pdf import _inline
    assert _inline("**[s-1]** _method_ — text") == "<b>[s-1]</b> <i>method</i> — text"
    assert _inline("a *star* and _under_ italic") == "a <i>star</i> and <i>under</i> italic"
    assert "_" in _inline("keep note_s_1 literal")   # identifier underscores untouched