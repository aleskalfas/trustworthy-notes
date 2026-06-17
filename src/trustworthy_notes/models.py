"""Core data structures.

Currently just ``PageText`` — the Wave 0 ingest output that everything else
anchors against. The notes model (Term / Statement / Evidence / Relation) is not
mirrored as dataclasses: it lives as YAML validated against
``schemas/notes.schema.json`` (see ``trustworthy_notes.validation``). Typed builders for
it will be added only when the extractor needs them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PageText:
    """Text extracted from a single PDF page, with layout metadata.

    page_number is the 1-based label a human would cite; page_index is 0-based.
    `page_type` records the layout the reader detected (text / figure / table /
    blank); it decides how `text` was produced. For a figure page, `text` holds
    the captions and `figure_regions` the drawing bboxes (region + caption only —
    images are not cropped yet). For a table page, `text` holds the rows.
    """

    page_index: int
    page_number: int
    text: str
    width: float
    height: float
    # Column-aware ingest enrichments:
    footnotes: str = ""
    column_count: int = 1
    page_label: Optional[str] = None
    # Layout classification:
    page_type: str = "text"  # text | figure | table | blank
    figure_regions: list[tuple[float, float, float, float]] = field(default_factory=list)
    # Inline drawn glyphs (e.g. hieroglyphic determinatives): each {id, bbox}.
    # `id` is a content hash of the glyph's vector geometry — stable across
    # occurrences, so a later OCR pass can reassign one id -> one sign.
    glyphs: list[dict] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return len(self.text)
