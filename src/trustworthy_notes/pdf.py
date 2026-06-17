"""Render a study-notes Markdown document into an interactive PDF.

Produces a self-contained PDF whose interactivity travels with the file and works
in every viewer (Preview, VS Code, browsers): a bookmarks/outline sidebar from the
numbered headings, a clickable Contents, and clickable ``[s-N]`` citations that
jump to their Notes & Sources entry. Page citations (``p.5``) are plain text — a
clickable jump into the *separate* source PDF isn't portable across viewers
(Preview drops the page; pdf.js won't follow cross-file links), and the verbatim
quote is shown inline anyway. The whole document is set in the bundled Charis SIL
serif (SIL OFL, under trustworthy_notes/fonts/), a full-Unicode scholarly face that covers
the transliteration signs, combining marks, and Latin-Extended names with no glyph
gaps. Pure-Python (reportlab); no system binaries.
"""

from __future__ import annotations

import importlib.resources
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

# We embed ONE full-coverage Unicode serif — Charis SIL (SIL Open Font License,
# bundled under trustworthy_notes/fonts/) — and set the whole document in it. Charis covers
# everything the source needs in proper Unicode: Latin-Extended letters in scholars'
# names (Myśliwiec, Świętochowski), Egyptological signs (ꜣ ꜥ ḥ ẖ š ṯ …), and combining
# marks (H̱ = H + combining macron) — so there are no glyph gaps and no per-glyph
# fallback, and it reads close to the source's Times. If the bundled font can't be
# loaded we degrade to the base-14 Helvetica (WinAnsi only).
_FONT, _FONT_BOLD, _FONT_ITALIC = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"


def _register_serif() -> bool:
    """Register the bundled Charis SIL family (regular/bold/italic/bold-italic)."""
    faces = {
        "Charis": "Charis-Regular.ttf", "Charis-Bold": "Charis-Bold.ttf",
        "Charis-Italic": "Charis-Italic.ttf", "Charis-BoldItalic": "Charis-BoldItalic.ttf",
    }
    fdir = importlib.resources.files("trustworthy_notes") / "fonts"
    try:
        for name, fn in faces.items():
            pdfmetrics.registerFont(TTFont(name, str(fdir / fn)))
        pdfmetrics.registerFontFamily(
            "Charis", normal="Charis", bold="Charis-Bold",
            italic="Charis-Italic", boldItalic="Charis-BoldItalic")
        return True
    except Exception:
        return False


if _register_serif():
    _FONT, _FONT_BOLD, _FONT_ITALIC = "Charis", "Charis-Bold", "Charis-Italic"

_ss = getSampleStyleSheet()
_TITLE = ParagraphStyle("t", parent=_ss["Title"], fontName=_FONT_BOLD, fontSize=20, spaceAfter=2)
_H1 = ParagraphStyle("h1", parent=_ss["Heading1"], fontName=_FONT_BOLD, fontSize=15, spaceBefore=16, spaceAfter=6,
                     textColor=colors.HexColor("#16466b"))
_H2 = ParagraphStyle("h2", parent=_ss["Heading2"], fontName=_FONT_BOLD, fontSize=12.5, spaceBefore=10, spaceAfter=3,
                     textColor=colors.HexColor("#2a6094"))
_H3 = ParagraphStyle("h3", parent=_ss["Heading3"], fontName=_FONT_BOLD, fontSize=11, spaceBefore=8, spaceAfter=2,
                     textColor=colors.HexColor("#3a6ea5"))
_BODY = ParagraphStyle("b", parent=_ss["Normal"], fontName=_FONT, fontSize=10.5, leading=15, spaceAfter=2)
_BUL = ParagraphStyle("bul", parent=_BODY, leftIndent=16, spaceAfter=2)
_BUL2 = ParagraphStyle("bul2", parent=_BODY, leftIndent=34, spaceAfter=1)
_QUOTE = ParagraphStyle("q", parent=_BODY, leftIndent=18, rightIndent=8, fontSize=9.2,
                        textColor=colors.HexColor("#3a3a3a"), backColor=colors.HexColor("#f5f5f3"),
                        borderPadding=4, spaceBefore=2, spaceAfter=5)
_NOTE = ParagraphStyle("n", parent=_BODY, spaceBefore=8)
_CELL = ParagraphStyle("cell", parent=_BODY, fontSize=9.3, leading=12, spaceAfter=0)
_CONTENT_W = A4[0] - 4 * cm   # frame width (page minus 2cm margins each side)

_ANCHOR = re.compile(r'^\s*<a id="([^"]+)"></a>\s*$')
_H = re.compile(r"^(#{1,4})\s+(.*)$")
_BULLET = re.compile(r"^(\s*)-\s+(.*)$")
_TROW = re.compile(r"^\s*\|.*\|\s*$")
_TSEP = re.compile(r"^[\s:|-]+$")


def _row_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _make_table(rows: list[list[str]]):
    ncols = max(len(r) for r in rows)
    data = []
    for ri, r in enumerate(rows):
        cells = [Paragraph(("<b>" + _inline(c) + "</b>") if ri == 0 else _inline(c), _CELL) for c in r]
        cells += [Paragraph("", _CELL)] * (ncols - len(cells))
        data.append(cells)
    t = Table(data, colWidths=[_CONTENT_W / ncols] * ncols)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d2dc")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(t: str) -> str:
    t = _esc(t)
    t = re.sub(r"\[([^\]]+)\]\(#([^)]+)\)", r'<a href="#\2" color="#1565c0">\1</a>', t)  # internal link
    t = re.sub(r"\[([^\]]+)\]\(([^)#][^)]*)\)", r"\1", t)  # external/source ref → plain text
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", t)
    t = re.sub(r"(?<![A-Za-z0-9_])_([^_\n]+)_(?![A-Za-z0-9_])", r"<i>\1</i>", t)  # _underscore italic_
    t = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', t)
    return t


def _plain(t: str) -> str:
    """Strip markdown for a clean bookmark/outline title."""
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    return re.sub(r"[*_`]", "", t).strip()


class _Doc(BaseDocTemplate):
    def afterFlowable(self, fl):
        o = getattr(fl, "outline", None)
        if o:
            text, key, level = o
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level, closed=(level > 0))


def markdown_to_pdf(md_text: str, out_path: str | Path) -> None:
    """Render a study-notes Markdown string to an interactive PDF at ``out_path``."""
    flow: list = []
    pending: list[str] = []
    n = [0]

    def emit(text: str, style, outline=None) -> None:
        dests = "".join(f'<a name="{d}"/>' for d in pending)
        pending.clear()
        p = Paragraph(dests + text, style)
        if outline:
            p.outline = outline
        flow.append(p)

    tbuf: list[str] = []

    def flush_table() -> None:
        rows = [_row_cells(line) for line in tbuf if not _TSEP.match(line)]
        tbuf.clear()
        if rows:
            flow.append(_make_table(rows))
            flow.append(Spacer(1, 4))

    for raw in md_text.splitlines():
        if _TROW.match(raw):              # markdown table row → buffer, render as a real table
            tbuf.append(raw)
            continue
        flush_table()
        if raw.strip() == "<!--pagebreak-->":
            flow.append(PageBreak())
            continue
        if raw.startswith("<!--"):
            continue
        m = _ANCHOR.match(raw)
        if m:
            pending.append(m.group(1))
            continue
        m = _H.match(raw)
        if m:
            hashes, txt = m.group(1), m.group(2).strip()
            if len(hashes) == 1:
                emit(_inline(txt), _TITLE)
            else:
                n[0] += 1
                lvl = len(hashes) - 2          # 0 = chapter/##, 1 = ###, 2 = ####
                style = (_H1, _H2, _H3)[min(lvl, 2)]
                emit(_inline(txt), style, outline=(_plain(txt), f"bm{n[0]}", lvl))
            continue
        s = raw.strip()
        if not s or s == "---":
            flow.append(Spacer(1, 6))
            continue
        if s.startswith("> "):
            emit(_inline(s[2:]), _QUOTE)
            continue
        mb = _BULLET.match(raw)
        if mb:
            emit("•&nbsp;" + _inline(mb.group(2)), _BUL2 if len(mb.group(1)) >= 2 else _BUL)
            continue
        emit(_inline(s), _NOTE if s.startswith("**[s-") else _BODY)
    flush_table()

    doc = _Doc(str(out_path), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
               topMargin=2 * cm, bottomMargin=2 * cm, title="Study Notes")
    doc.addPageTemplates([PageTemplate(id="m", frames=[
        Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height)])])
    doc.build(flow)
