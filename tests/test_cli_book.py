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


def _seed_chapter_for_language(notes_dir, num, title, language, body, style="outline"):
    """Seed one chapter's composed notes-set and its language-aware exported file."""
    cdir = workspace.compose_stage_dir(notes_dir, "chapters")
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / f"chapter-{num:03d}.notes.yaml").write_text(
        yaml.safe_dump({"source": {"chapter_title": title}}), encoding="utf-8"
    )
    dest = workspace.chapter_export_path(notes_dir, num, style, language)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body, encoding="utf-8")


def test_book_combines_the_language_aware_chapters(tmp_path, monkeypatch):
    # #127 scope edge: `book --language cs` is built from the .cs.md chapters via
    # workspace.chapter_export_path, never mixing in the English chapter-NNN.outline.md.
    from trustworthy_notes import pdf as pdfmod

    monkeypatch.setattr(
        pdfmod, "markdown_to_pdf", lambda md, out: out.write_text("pdf", encoding="utf-8")
    )

    src = tmp_path / "Foo-2506.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    notes_dir = workspace.work_dir(src)
    # Both languages exported for the same chapter; the bodies differ so we can tell
    # which file the book read.
    _seed_chapter_for_language(notes_dir, 6, "Background", None,
                               "# CHAPTER 6 — Study Notes\n\n## 1. English point\n")
    _seed_chapter_for_language(notes_dir, 6, "Background", "cs",
                               "# CHAPTER 6 — Study Notes\n\n## 1. Český bod\n")

    res = runner.invoke(cli.app, ["book", str(src), "--language", "cs"])
    assert res.exit_code == 0, res.stdout

    book_md = (tmp_path / "Foo-2506.tnotes.md").read_text(encoding="utf-8")
    assert "Český bod" in book_md          # the cs chapter was combined
    assert "English point" not in book_md  # the English chapter was NOT mixed in


def test_book_for_missing_language_errors_clearly(tmp_path, monkeypatch):
    # Asking for a language with no exported chapters errors rather than silently
    # building an English book under that name.
    src = tmp_path / "Foo-2506.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    notes_dir = workspace.work_dir(src)
    _seed_chapter(notes_dir, 6, "Background")  # English only

    res = runner.invoke(cli.app, ["book", str(src), "--language", "cs"])
    assert res.exit_code == 1                       # errors rather than silently producing a book
    assert not (tmp_path / "Foo-2506.tnotes.md").exists()


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
