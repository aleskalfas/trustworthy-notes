"""The single frozen-aware resource seam — fonts and schema both route here."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from trustworthy_notes.resources import package_path, read_text


def test_package_path_yields_a_real_existing_file():
    # as_file() must hand out an honest filesystem path (not a Traversable) so
    # APIs that open by filename — reportlab's TTFont — can use it.
    with package_path("fonts", "Charis-Regular.ttf") as path:
        assert path.is_file()
        assert path.suffix == ".ttf"
        assert path.read_bytes()[:4] == b"\x00\x01\x00\x00"  # TrueType signature


def test_read_text_loads_the_bundled_schema():
    text = read_text("schemas", "notes.schema.json")
    schema = json.loads(text)
    assert schema.get("$schema")
    assert "properties" in schema


def test_charis_renders_after_the_seam_block_exits():
    # The frozen hazard: as_file() may delete the extracted path on block exit,
    # so a font registered from a seam path could become a use-after-free at PDF
    # build time (reportlab may open the .ttf lazily, after registration). Here
    # we (1) confirm we can leave the seam block, then (2) build a PDF in the
    # Charis family well after any such block has exited. pdf.py registers Charis
    # once into a process-lifetime temp dir, so the registered paths outlive the
    # seam — this asserts that end to end, not merely path-existence inside a block.
    import trustworthy_notes.pdf as pdfmod

    with package_path("fonts", "Charis-Regular.ttf") as fpath:
        assert fpath.is_file()
    # Block has exited; under a freeze the seam path may now be gone. Registration
    # happened at import; render must still succeed using the registered family.
    assert pdfmod._FONT == "Charis", "Charis family did not register"

    out = Path(tempfile.mkdtemp(prefix="tn-pdftest-")) / "out.pdf"
    pdfmod.markdown_to_pdf("# Title\n\n## Heading\n\nBody **bold** and *italic* with ḥ ꜣ signs.\n", out)
    assert out.is_file()
    assert out.read_bytes()[:5] == b"%PDF-"


def test_validation_and_pdf_consume_the_same_seam():
    # Guard the architecture: both resource consumers go through resources.py and
    # do not reach for importlib.resources themselves (one seam, COR-007).
    import trustworthy_notes.pdf as pdfmod
    import trustworthy_notes.validation as valmod

    pdf_src = (pdfmod.__file__,)
    val_src = (valmod.__file__,)

    assert "from .resources import" in Path(*pdf_src).read_text(encoding="utf-8")
    assert "from .resources import" in Path(*val_src).read_text(encoding="utf-8")
    for src in (pdf_src, val_src):
        assert "importlib.resources" not in Path(*src).read_text(encoding="utf-8")
