"""Wave 0 - Ingest.

Turn a PDF into per-page text with layout metadata. This is the foundation the
evidence system rests on: every later claim must point back to a page extracted
here. Uses pdfplumber (MIT, pure-Python, cross-platform).

Key behaviours (see the design notes for the why):
  * COLUMN-AWARE reading. Naive `page.extract_text()` zippers multi-column
    layouts into scrambled prose. We detect the vertical gutter and read each
    column separately, in reading order.
  * FOOTNOTE separation. The small-font block at the page bottom is captured as
    a distinct stream rather than inlined into body prose.
  * RUNNING-HEADER stripping. The repeated page-top title (e.g. the book title)
    leaks into the body and is split across columns by the gutter. We detect it
    by repetition across pages and drop it, so it never reaches the body.
  * PAGE-LABEL capture. The printed page number (footer) is read so we can map
    printed labels (what a scholar cites) to PDF page indices.

Nomenclature: this is the *ingest* wave; its action is to *read* the document
into Pages. "extract" is reserved for Wave 1 (notes from text). See ARCHITECTURE.

The heuristics are intentionally small and inspectable: for an evidence system
we prefer ~100 lines we can debug over a black-box layout model. This targets
clean 1-2 column academic layouts; messy layouts would warrant a heavier tool.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path
from statistics import median

import pdfplumber

from . import translit
from .models import PageText

# Pages with fewer than this many body characters look image-only/scanned.
_LOW_TEXT_THRESHOLD = 40
# A line is "footnote-sized" if its median font is this fraction of body size.
_FOOTNOTE_SIZE_RATIO = 0.85
# Group words into the same visual line when their tops are within this many pts.
_LINE_TOL = 3.0
# Page-label search region (bottom fraction of the page).
_LABEL_REGION_TOP = 0.92

_ROMAN = set("ivxlcdm")


def _is_label(token: str) -> bool:
    """True for a bare arabic or roman-numeral page label like '3' or 'iv'."""
    t = token.strip().strip(".")
    if not t:
        return False
    return t.isdigit() or all(c in _ROMAN for c in t.lower())


def _detect_gutter(words, width, lo_frac=0.30, hi_frac=0.70):
    """Find the x of the column gutter, or None for single-column.

    Uses a *crossing count* per x (how many words span that x) rather than a
    boolean, so a full-width chapter title crossing the centre doesn't hide the
    gutter: the gutter is the central x-band with the fewest crossings.
    """
    if not words:
        return None
    n = int(width) + 1
    counts = [0] * (n + 1)
    for w in words:
        a = max(0, int(w["x0"]))
        b = min(n, int(w["x1"]))
        for x in range(a, b + 1):
            counts[x] += 1

    lo, hi = int(width * lo_frac), int(width * hi_frac)
    if hi <= lo:
        return None
    band_min = min(counts[lo : hi + 1])
    overall_max = max(counts)
    # If the "gap" is nearly as dense as the densest column, it's not a gutter.
    if overall_max == 0 or band_min >= overall_max * 0.5:
        return None

    # Centre of the widest run of minimum-crossing x within the central band.
    best_len, best_center, run, start = 0, None, 0, lo
    for x in range(lo, hi + 1):
        if counts[x] == band_min:
            if run == 0:
                start = x
            run += 1
            if run > best_len:
                best_len, best_center = run, start + run / 2
        else:
            run = 0
    return best_center


def _lines(words, tol=_LINE_TOL):
    """Group words into full-width visual lines, each tagged with median size.

    Grouping spans columns on purpose: a horizontal band that contains body
    text in *either* column keeps a body-size median, so isolated small-font
    superscripts don't get mistaken for the footnote block.
    """
    lines: list[dict] = []
    for w in sorted(words, key=lambda w: w["top"]):
        for ln in lines:
            if abs(ln["top"] - w["top"]) <= tol:
                ln["words"].append(w)
                break
        else:
            lines.append({"top": w["top"], "words": [w]})
    for ln in lines:
        ss = [x.get("size") for x in ln["words"] if x.get("size")]
        ln["size"] = median(ss) if ss else 0.0
    return sorted(lines, key=lambda ln: ln["top"])


def _footnote_top(words, height, body_size):
    """Y where the contiguous bottom footnote block begins (page height if none).

    Walk lines from the bottom upward while each line's median font stays small;
    stop at the first body-size line. This isolates the footnote *block* and
    ignores small superscript markers embedded in body prose.
    """
    lines = _lines(words)
    fn_top = height
    for ln in reversed(lines):
        toks = [w["text"].strip() for w in ln["words"]]
        # The footer page-label line is body-size; skip it so it doesn't end
        # the walk before we reach the actual footnote block above it.
        if len(toks) == 1 and _is_label(toks[0]):
            continue
        if ln["size"] and ln["size"] < body_size * _FOOTNOTE_SIZE_RATIO:
            fn_top = ln["top"]
        else:
            break
    return fn_top


def _page_label(words, height):
    """Read the printed page label from the footer, if present."""
    cands = [
        w["text"].strip().strip(".")
        for w in words
        if w["top"] > height * _LABEL_REGION_TOP and _is_label(w["text"])
    ]
    return cands[-1] if cands else None


def _glyph_fingerprint(objs) -> str:
    """Stable content hash of a drawn glyph's vector geometry.

    Position- and scale-invariant, so the SAME sign hashes identically wherever
    it appears (lets the LLM tell glyphs apart and dedupe them), and a later OCR
    pass can map one hash -> one identified sign and substitute everywhere.
    """
    pts = [(x, y) for o in objs for (x, y) in o.get("pts", [])]
    if not pts:
        return "00000000"
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, miny = min(xs), min(ys)
    span = max(max(xs) - minx, max(ys) - miny) or 1.0
    norm = sorted(
        (round((x - minx) / span * 1000), round((y - miny) / span * 1000)) for x, y in pts
    )
    return hashlib.sha1(repr(norm).encode()).hexdigest()[:8]


_FN_MARKER_RE = re.compile(r"(\D*)(\d+)(\D*)")


def _footnote_marker(text: str, size: float, median_size: float):
    """If `text` is a superscript footnote-reference (a small-font digit run),
    return it rewritten as `[^N]`; otherwise None.

    Size is the discriminator: a footnote marker is set markedly smaller than the
    surrounding body, which is exactly what tells a *reference* (`.13`) apart from
    a real number (a year, a catalogue id like `S 216`, the document `10416`).
    """
    if not (median_size and size and size < 0.75 * median_size):
        return None
    m = _FN_MARKER_RE.fullmatch(text)
    if not m:
        return None
    pre, num, post = m.groups()
    return f"{pre}[^{num}]{post}"


def _region_text(region) -> tuple[str, list[dict]]:
    """Text of a cropped region (reassembled from words), plus inline drawn glyphs.

    Reassembling from words (rather than `extract_text`) lets us see each word's
    font and restore Egyptological transliteration runs (MdC -> Unicode, e.g.
    `NTr` -> `Nṯr`). Whitespace differs slightly from `extract_text`, but
    anchoring normalizes whitespace (§6), so matching is unaffected.

    A glyph *drawn* in the gap between two words (vector curves/lines, no
    character — e.g. a hieroglyphic determinative) is replaced by a stable,
    copyable placeholder `⟨glyph-HASH⟩`, so it is neither silently dropped nor
    un-copyable; its region is recorded for the future OCR/crop pass.
    """
    words = region.extract_words(extra_attrs=["fontname", "size"])
    if not words:
        return "", []
    for w in words:
        if translit.is_transliteration_font(w.get("fontname")):
            w["text"] = translit.mdc_to_unicode(w["text"])
    all_sizes = [w.get("size") for w in words if w.get("size")]
    median_size = median(all_sizes) if all_sizes else 0.0
    vectors = list(region.curves) + list(region.lines)
    glyphs: list[dict] = []
    lines_out = []
    for ln in _lines(words):
        ordered = sorted(ln["words"], key=lambda w: w["x0"])
        top = min(w["top"] for w in ordered)
        bottom = max(w["bottom"] for w in ordered)
        parts: list[str] = []
        prev = None
        for w in ordered:
            if prev is not None:
                gap = w["x0"] - prev["x1"]
                size = w.get("size") or prev.get("size") or 10.0
                in_gap = [
                    o
                    for o in vectors
                    if prev["x1"] - 1 < (o["x0"] + o["x1"]) / 2 < w["x0"] + 1
                    and top - 3 < (o["top"] + o["bottom"]) / 2 < bottom + 3
                ]
                if gap > 2 and in_gap:
                    fp = _glyph_fingerprint(in_gap)
                    parts.append(f" ⟨glyph-{fp}⟩ ")
                    glyphs.append(
                        {
                            "id": fp,
                            "bbox": (
                                min(o["x0"] for o in in_gap),
                                min(o["top"] for o in in_gap),
                                max(o["x1"] for o in in_gap),
                                max(o["bottom"] for o in in_gap),
                            ),
                        }
                    )
                elif gap > max(1.0, 0.2 * size):
                    parts.append(" ")
            marker = _footnote_marker(w["text"], w.get("size") or 0.0, median_size)
            parts.append(marker if marker else w["text"])
            prev = w
        lines_out.append("".join(parts))
    return "\n".join(_dehyphenate(lines_out)).strip(), glyphs


def _dehyphenate(lines: list[str]) -> list[str]:
    """Rejoin words split by a line-break hyphen ("half-\\nsiblings" -> "half-siblings").

    pdfplumber preserves the typeset line break, so a word hyphenated across two
    lines reads as "...half-" + "siblings...". After whitespace-collapse that
    becomes "half- siblings", which no faithfully-retyped excerpt can anchor to.
    We join when the previous line ends with letter+hyphen and the next line
    starts with a letter, keeping the hyphen (this document's breaks are
    overwhelmingly genuine compounds and Egyptian names — "Nfr-kꜣ", "ꜥnḫ-jr-Ptḥ").
    We do NOT join when the next line starts with a digit (e.g. "sons-\\n4.5.1"),
    so a dash before a section number is left alone.
    """
    out: list[str] = []
    for ln in lines:
        if (
            out
            and len(out[-1]) >= 2
            and out[-1][-1] == "-"
            and out[-1][-2].isalpha()
            and ln[:1].isalpha()
        ):
            out[-1] = out[-1] + ln
        else:
            out.append(ln)
    return out


def _read_column(page, x0, x1, words, body_size, height, top=0.0) -> tuple[str, str, list[dict]]:
    """Return (body, footnotes, glyphs) for one column region [x0, x1), below `top`.

    `top` is the y where the body starts — just below any running header that
    was cropped off (0.0 when there is none). The footnote boundary is computed
    within this column only, because in a multi-column layout each column has
    its own footnote block at a different y.
    """
    col_words = [w for w in words if x0 <= (w["x0"] + w["x1"]) / 2 < x1]
    fn_top = _footnote_top(col_words, height, body_size) if body_size else height
    body, body_glyphs = _region_text(page.crop((x0, top, x1, fn_top)))
    foot, foot_glyphs = ("", [])
    if fn_top < height:
        foot, foot_glyphs = _region_text(page.crop((x0, fn_top, x1, height)))
    return body, foot, body_glyphs + foot_glyphs


def _strip_label_lines(text, label):
    """Drop standalone page-label lines (e.g. a bare '3') from a text stream."""
    if not text:
        return text
    kept = [ln for ln in text.splitlines() if ln.strip().strip(".") != (label or "\0")]
    return "\n".join(kept).strip()


def _top_line(page) -> str:
    """The topmost visual line's text — the running-header candidate.

    Read full-width, BEFORE any column split, so a header spanning both columns
    stays one intact string that is identical across pages — unlike the
    per-column fragments the gutter produces, whose split point wanders.
    """
    words = page.extract_words(extra_attrs=["size"])
    if not words:
        return ""
    first = _lines(words)[0]
    return " ".join(w["text"] for w in sorted(first["words"], key=lambda w: w["x0"])).strip()


def _header_band_bottom(words, body_size) -> float:
    """Y where the body begins on a header page: the bottom of the whole top block.

    General principle (no book-specific rules): crop the entire top cluster —
    header text *and* any oversized drop-initials hanging below it — by extending
    down to the first clear vertical gap (the top margin) before the body. This
    handles single- or multi-line headers and odd header typography uniformly.
    """
    lines = _lines(words)
    if len(lines) < 2 or not body_size:
        return 0.0
    cut = 0
    gap_found = False
    for i in range(len(lines) - 1):
        if lines[i + 1]["top"] - lines[i]["top"] > body_size * 1.8:
            cut = i
            gap_found = True
            break
    header_bottom = max(w["bottom"] for ln in lines[: cut + 1] for w in ln["words"])
    if gap_found:
        # Cut in the MIDDLE of the top-margin gap, not flush against the header
        # bottom — a crop flush to the edge keeps glyphs sitting on that boundary
        # (e.g. oversized drop-initials), which would leak into the body.
        return (header_bottom + lines[cut + 1]["top"]) / 2.0
    # No clear gap before the body: pad below the header line to clear the edge.
    return header_bottom + body_size * 0.5


def _looks_like_header(text: str) -> bool:
    """True if a top line is styled like a running head: predominantly UPPERCASE.

    Scholarly books set running heads (book title, chapter/section title, table
    title) in caps or small-caps — pdfplumber renders both as uppercase letters —
    whereas body text is mixed case. This is the per-page signal that catches a
    header even when its section is so short the string recurs only once (e.g. a
    one-page interior recto), which a repetition test alone can never see.
    """
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 4:
        return False
    return sum(ch.isupper() for ch in letters) / len(letters) >= 0.8


def _detect_running_headers(top_texts: list[str], *, min_count: int = 2) -> set[str]:
    """Top lines that are running headers — by caps-styling OR by repetition.

    Detected on the full-width top line (pre-gutter), so the string is stable.
    Two independent signals, because neither alone is enough on real books:

      * **Caps-styling** (`_looks_like_header`) — the typographic convention for
        running heads. Catches short-section and chapter-opening headers that
        appear only once or twice (e.g. a short chapter's single interior page),
        which repetition cannot.
      * **Repetition** (>= ``min_count``) — a belt-and-suspenders signal for any
        running head that is *not* caps-styled (mixed-case running feet, etc.).

    A one-off mixed-case line (real body) matches neither and is left as content.
    """
    counts = Counter(t for t in top_texts if t)
    return {t for t, c in counts.items() if c >= min_count or _looks_like_header(t)}


def _read_page(page, strip_header: bool) -> PageText:
    """Read one page into a PageText; if strip_header, crop the top header block."""
    words = page.extract_words(extra_attrs=["size"])
    width, height = float(page.width), float(page.height)
    sizes = [w.get("size") for w in words if w.get("size")]
    body_size = median(sizes) if sizes else 0.0
    label = _page_label(words, height)
    header_bottom = _header_band_bottom(words, body_size) if strip_header else 0.0

    gutter = _detect_gutter(words, width)
    if gutter:
        lb, lf, lg = _read_column(page, 0, gutter, words, body_size, height, header_bottom)
        rb, rf, rg = _read_column(page, gutter, width, words, body_size, height, header_bottom)
        body = (lb + "\n\n" + rb).strip()
        footnotes = (lf + "\n\n" + rf).strip()
        glyphs = lg + rg
        columns = 2
    else:
        body, footnotes, glyphs = _read_column(page, 0, width, words, body_size, height, header_bottom)
        columns = 1

    footnotes = _strip_label_lines(footnotes, label)
    return PageText(
        page_index=page.page_number - 1,
        page_number=page.page_number,
        text=body,
        width=width,
        height=height,
        footnotes=footnotes,
        column_count=columns,
        page_label=label,
        glyphs=glyphs,
    )


def classify_page(page) -> dict:
    """Classify a page's layout so it can be routed to the right reader.

    Returns the perceived `type` plus the signals behind it, so the thresholds
    are inspectable and tunable (see the `layout` CLI command). Heuristics, in
    order: a page with almost nothing is *blank*; heavy ruling lines mean a
    *table*; raster images with little text mean a *figure* plate; otherwise
    *text*. A text page with one inline image stays *text* (its caption/figure is
    handled later); the dominant content decides the type.
    """
    words = len(page.extract_words())
    images = len(page.images)
    lines = len(page.lines)
    if words < 5 and images == 0 and lines < 10:
        ptype = "blank"
    elif lines >= 60:
        ptype = "table"
    elif images >= 1 and words < 200:
        ptype = "figure"
    else:
        ptype = "text"
    return {"type": ptype, "words": words, "images": images, "lines": lines}


def _table_text(page) -> str:
    """Read a table page WITHOUT column-splitting.

    Structured cells ('cell | cell') when pdfplumber can detect the grid;
    otherwise plain top-to-bottom reading order — which for a table IS row order
    (the column reader is the only thing that scrambles tables, so we bypass it).
    """
    blocks = []
    for table in page.extract_tables():
        rows = []
        for row in table:
            cells = [(c or "").replace("\n", " ").strip() for c in row]
            rows.append(" | ".join(cells))
        if rows:
            blocks.append("\n".join(rows))
    if blocks:
        return "\n\n".join(blocks).strip()
    return (page.extract_text() or "").strip()


def top_line(page) -> str:
    """Public wrapper: the page's full-width top line (header candidate)."""
    return _top_line(page)


def detect_headers(pages) -> set[str]:
    """Public: the document's running-header lines, detected by repetition."""
    return _detect_running_headers([_top_line(p) for p in pages])


def region_map(page, strip_header: bool) -> dict:
    """The regions the reader perceives on a page, for visualization/debug.

    Returns the header band, the gutter, and per-column body/footnote boundaries
    — the exact geometry `read_pages` uses to crop. `strip_header` should be the
    page's header flag (e.g. ``top_line(page) in detect_headers(pages)``).
    """
    words = page.extract_words(extra_attrs=["size"])
    width, height = float(page.width), float(page.height)
    sizes = [w.get("size") for w in words if w.get("size")]
    body_size = median(sizes) if sizes else 0.0
    header_bottom = _header_band_bottom(words, body_size) if strip_header else 0.0
    gutter = _detect_gutter(words, width)
    bounds = [(0.0, gutter), (gutter, width)] if gutter else [(0.0, width)]
    columns = []
    for x0, x1 in bounds:
        col_words = [w for w in words if x0 <= (w["x0"] + w["x1"]) / 2 < x1]
        fn_top = _footnote_top(col_words, height, body_size) if body_size else height
        columns.append({"x0": x0, "x1": x1, "fn_top": fn_top})
    return {
        "width": width,
        "height": height,
        "header_bottom": header_bottom,
        "gutter": gutter,
        "columns": columns,
    }


def read_pages(pdf_path: str | Path) -> list[PageText]:
    """Ingest every page: running headers stripped, column-aware, footnotes split.

    Two passes within one open: (1) read each page's full-width top line and
    detect the document's running headers by repetition; (2) read each page,
    cropping the header band off before column splitting so the gutter never
    fragments it.
    """
    pdf_path = Path(pdf_path)
    with pdfplumber.open(pdf_path) as pdf:
        pages = list(pdf.pages)
        tops = [_top_line(page) for page in pages]
        headers = _detect_running_headers(tops)
        result: list[PageText] = []
        for page, top in zip(pages, tops):
            ptype = classify_page(page)["type"]
            if ptype == "blank":
                pt = PageText(
                    page_index=page.page_number - 1,
                    page_number=page.page_number,
                    text="",
                    width=float(page.width),
                    height=float(page.height),
                    page_type="blank",
                )
            elif ptype == "table":
                pt = PageText(
                    page_index=page.page_number - 1,
                    page_number=page.page_number,
                    text=_table_text(page),
                    width=float(page.width),
                    height=float(page.height),
                    page_type="table",
                )
            else:
                # text and figure pages share the column-aware reader (figure
                # pages yield their captions); they differ only in page_type
                # and that figures record their drawing regions.
                pt = _read_page(page, bool(top) and top in headers)
                pt.page_type = ptype
                if ptype == "figure":
                    pt.figure_regions = [
                        (im["x0"], im["top"], im["x1"], im["bottom"]) for im in page.images
                    ]
                # classify_page counts RAW words; the column-aware reader may still
                # recover almost nothing (e.g. a plate page with a stray glyph).
                # If a text page yields no real body, it's blank — so extract skips
                # it instead of paying for an empty LLM call.
                elif len((pt.text or "").strip()) + len((pt.footnotes or "").strip()) < 20:
                    pt.page_type = "blank"
            result.append(pt)
    return result


def text_layer_report(pages: list[PageText]) -> dict:
    """Summarize how usable the embedded text layer is across the document."""
    total = len(pages)
    low_text = [p.page_number for p in pages if p.char_count < _LOW_TEXT_THRESHOLD]
    total_chars = sum(p.char_count for p in pages)
    return {
        "total_pages": total,
        "total_chars": total_chars,
        "avg_chars_per_page": (total_chars / total) if total else 0,
        "low_text_pages": low_text,
        "needs_ocr_likely": len(low_text) > total / 2 if total else False,
    }
