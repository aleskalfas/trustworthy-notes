"""Output-location convention tests (METHODOLOGY/ARCHITECTURE IO convention)."""

from __future__ import annotations

from pathlib import Path

from trustworthy_notes import workspace


def test_default_work_dir_is_sibling_dot_notes_folder():
    assert workspace.work_dir("data/Foo.pdf") == Path("data/Foo.pdf.notes")
    assert workspace.work_dir("/abs/path/Kim_2013_BAR_2513.pdf") == Path(
        "/abs/path/Kim_2013_BAR_2513.pdf.notes"
    )


def test_work_dir_never_collides_with_source_file():
    # The marker is the whole point: the output dir must differ from the PDF path.
    assert workspace.work_dir("data/Foo.pdf") != Path("data/Foo.pdf")


def test_override_wins():
    assert workspace.work_dir("data/Foo.pdf", "/tmp/out") == Path("/tmp/out")


def test_page_notes_path():
    # per-page notes live in the 1-extract wave folder inside the work dir
    assert workspace.page_notes_path("data/Foo.pdf.notes", 13) == Path(
        "data/Foo.pdf.notes/1-extract/page-0013.notes.yaml"
    )


def test_wave_dirs():
    assert workspace.extract_dir("w") == Path("w/1-extract")
    assert workspace.compose_dir("w") == Path("w/2-compose")
    assert workspace.validate_dir("w") == Path("w/3-validate")
