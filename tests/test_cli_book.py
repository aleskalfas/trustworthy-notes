"""CLI test for the `tnotes book` output location: the combined book is written
beside the source PDF as ``<stem>.tnotes.md/.pdf`` (decision A, issue #18), with
the reading copy at ``<stem>.tnotes.reading.*``. No PDF parsing or network needed —
the book command only globs the export dir and renders Markdown."""

from __future__ import annotations

import yaml
from typer.testing import CliRunner

from trustworthy_notes import cli, workspace

runner = CliRunner()


def _seed_chapter(notes_dir, num, title, style="outline"):
    """Lay down the two files `book` reads for one chapter: the exported study-note
    Markdown (4-export) and the composed notes-set that carries its title."""
    exdir = workspace.export_dir(notes_dir)
    exdir.mkdir(parents=True, exist_ok=True)
    (exdir / f"chapter-{num:03d}.{style}.md").write_text(
        f"# CHAPTER {num} — Study Notes\n\n## 1. Point [s-1](#note-s-1)\n",
        encoding="utf-8",
    )
    cdir = workspace.compose_stage_dir(notes_dir, "chapters")
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / f"chapter-{num:03d}.notes.yaml").write_text(
        yaml.safe_dump({"source": {"chapter_title": title}}), encoding="utf-8"
    )


def test_book_writes_beside_source_named_after_it(tmp_path, monkeypatch):
    # markdown_to_pdf is stubbed to just touch the path so we assert the location,
    # not reportlab's output.
    from trustworthy_notes import pdf as pdfmod

    monkeypatch.setattr(
        pdfmod, "markdown_to_pdf", lambda md, out: out.write_text("pdf", encoding="utf-8")
    )

    src = tmp_path / "Foo-2506.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    notes_dir = workspace.work_dir(src)
    _seed_chapter(notes_dir, 6, "Background")

    res = runner.invoke(cli.app, ["book", str(src)])
    assert res.exit_code == 0, res.stdout

    md = tmp_path / "Foo-2506.tnotes.md"
    pdf = tmp_path / "Foo-2506.tnotes.pdf"
    assert md.is_file() and pdf.is_file()
    # not the old 4-export/book.* location
    assert not (workspace.export_dir(notes_dir) / "book.md").exists()


def test_book_reading_copy_gets_reading_marker_beside_source(tmp_path, monkeypatch):
    from trustworthy_notes import pdf as pdfmod

    monkeypatch.setattr(
        pdfmod, "markdown_to_pdf", lambda md, out: out.write_text("pdf", encoding="utf-8")
    )

    src = tmp_path / "Foo-2506.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    notes_dir = workspace.work_dir(src)
    _seed_chapter(notes_dir, 6, "Background")

    res = runner.invoke(cli.app, ["book", str(src), "--no-citations"])
    assert res.exit_code == 0, res.stdout

    assert (tmp_path / "Foo-2506.tnotes.reading.md").is_file()
    assert (tmp_path / "Foo-2506.tnotes.reading.pdf").is_file()
    # the cited copy is not produced in a --no-citations run
    assert not (tmp_path / "Foo-2506.tnotes.md").exists()
