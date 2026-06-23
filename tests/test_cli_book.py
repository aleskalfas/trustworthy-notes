"""CLI test for the `tnotes book` output location: the combined book is written
beside the source PDF as ``<stem>.tnotes.md/.pdf`` (decision A, issue #18), with
the reading copy at ``<stem>.tnotes.reading.*``. No PDF parsing or network needed —
the book command only globs the export dir and renders Markdown.

Also covers issue #138: selection is driven off the EXPORT dir, so `book` works
from exported chapters alone (no compose stage) — the release smoke path — while
staying language-aware (no English/`.cs` mixing) and resolving titles from the
composed notes-set when it exists, else the export heading, else `Chapter N`."""

from __future__ import annotations

import pytest
import yaml
from typer.testing import CliRunner

from trustworthy_notes import cli, workspace

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Point config at a throwaway dir so language resolution is hermetic.

    `book`/`export` resolve the preferred language via config.resolve_language,
    which otherwise reads the developer's real ~/.trustworthy-notes/config.yaml.
    A real `language: cs` there would make a no-flag run look for `.cs.md`
    chapters and miss the bare-English files these tests seed. TN_CONFIG_DIR is
    the supported override (read live by config.config_dir), so the suite passes
    regardless of the ambient user config.
    """
    monkeypatch.setenv("TN_CONFIG_DIR", str(tmp_path / "cfg"))


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


def _seed_exported_chapter_only(notes_dir, num, body, style="outline", language=None):
    """Lay down ONLY the exported study-note Markdown for a chapter (no compose
    notes-set) — the post-export / release-smoke state of issue #138."""
    dest = workspace.chapter_export_path(notes_dir, num, style, language)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body, encoding="utf-8")


def test_book_builds_from_export_only_no_compose_stage(tmp_path, monkeypatch):
    # The release smoke (issue #138): only 4-export/chapter-001.outline.md exists, no
    # compose stage at all, and `book ... --all` must still assemble and render.
    from trustworthy_notes import pdf as pdfmod

    monkeypatch.setattr(
        pdfmod, "markdown_to_pdf", lambda md, out: out.write_text("pdf", encoding="utf-8")
    )

    src = tmp_path / "fixture.pdf"
    src.write_bytes(b"")  # placeholder source; book names off it but never opens it
    notes_dir = workspace.work_dir(src)
    _seed_exported_chapter_only(
        notes_dir, 1, "# Smoke chapter\n\nA line the book must carry through.\n"
    )

    res = runner.invoke(cli.app, ["book", str(src), "--all"])
    assert res.exit_code == 0, res.stdout

    assert (tmp_path / "fixture.tnotes.pdf").is_file()
    book_md = (tmp_path / "fixture.tnotes.md").read_text(encoding="utf-8")
    assert "A line the book must carry through." in book_md


def test_book_export_selection_does_not_mix_languages(tmp_path, monkeypatch):
    # Export-only (no compose) with both an English and a Czech chapter present: the
    # en book takes only the bare file, `--language cs` only the .cs.md one (#127/#138).
    from trustworthy_notes import pdf as pdfmod

    monkeypatch.setattr(
        pdfmod, "markdown_to_pdf", lambda md, out: out.write_text("pdf", encoding="utf-8")
    )

    src = tmp_path / "Foo-2506.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    notes_dir = workspace.work_dir(src)
    _seed_exported_chapter_only(notes_dir, 1, "# Chapter 1\n\nEnglish body.\n")
    _seed_exported_chapter_only(notes_dir, 1, "# Chapter 1\n\nČeské tělo.\n", language="cs")

    en = runner.invoke(cli.app, ["book", str(src), "--all"])
    assert en.exit_code == 0, en.stdout
    en_md = (tmp_path / "Foo-2506.tnotes.md").read_text(encoding="utf-8")
    assert "English body." in en_md and "České tělo." not in en_md

    cs = runner.invoke(cli.app, ["book", str(src), "--all", "--language", "cs"])
    assert cs.exit_code == 0, cs.stdout
    cs_md = (tmp_path / "Foo-2506.tnotes.md").read_text(encoding="utf-8")
    assert "České tělo." in cs_md and "English body." not in cs_md


def test_book_title_prefers_compose_notes_set(tmp_path, monkeypatch):
    # When the compose notes-set is present, its chapter_title wins over the export
    # heading.
    from trustworthy_notes import pdf as pdfmod

    monkeypatch.setattr(
        pdfmod, "markdown_to_pdf", lambda md, out: out.write_text("pdf", encoding="utf-8")
    )

    src = tmp_path / "Foo-2506.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    notes_dir = workspace.work_dir(src)
    _seed_chapter(notes_dir, 1, "Notes-Set Title")  # seeds both export md and notes-set
    # The export heading differs from the notes-set title so we can tell which won.
    workspace.chapter_export_path(notes_dir, 1, "outline", None).write_text(
        "# Heading Title\n\nBody.\n", encoding="utf-8"
    )

    res = runner.invoke(cli.app, ["book", str(src)])
    assert res.exit_code == 0, res.stdout
    book_md = (tmp_path / "Foo-2506.tnotes.md").read_text(encoding="utf-8")
    assert "Notes-Set Title" in book_md
    assert "Heading Title" not in book_md


def test_book_title_falls_back_to_export_heading(tmp_path, monkeypatch):
    # No compose notes-set: the title comes from the export's first `# ` heading.
    from trustworthy_notes import pdf as pdfmod

    monkeypatch.setattr(
        pdfmod, "markdown_to_pdf", lambda md, out: out.write_text("pdf", encoding="utf-8")
    )

    src = tmp_path / "Foo-2506.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    notes_dir = workspace.work_dir(src)
    _seed_exported_chapter_only(notes_dir, 1, "# Heading From Export\n\nBody.\n")

    res = runner.invoke(cli.app, ["book", str(src), "--all"])
    assert res.exit_code == 0, res.stdout
    book_md = (tmp_path / "Foo-2506.tnotes.md").read_text(encoding="utf-8")
    assert "Heading From Export" in book_md


def test_book_title_falls_back_to_chapter_n_placeholder(tmp_path, monkeypatch):
    # No notes-set and no heading in the export: the title is the "Chapter N"
    # placeholder, and --all still includes it (no prose judgement on a placeholder).
    from trustworthy_notes import pdf as pdfmod

    monkeypatch.setattr(
        pdfmod, "markdown_to_pdf", lambda md, out: out.write_text("pdf", encoding="utf-8")
    )

    src = tmp_path / "Foo-2506.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    notes_dir = workspace.work_dir(src)
    _seed_exported_chapter_only(notes_dir, 4, "Body with no heading at all.\n")

    res = runner.invoke(cli.app, ["book", str(src), "--all"])
    assert res.exit_code == 0, res.stdout
    book_md = (tmp_path / "Foo-2506.tnotes.md").read_text(encoding="utf-8")
    assert "Chapter 4" in book_md


def test_book_prose_filter_applies_when_title_known(tmp_path, monkeypatch):
    # Default (prose-only) run: a reference-matter title (from the notes-set) is
    # excluded, a prose one is kept.
    from trustworthy_notes import pdf as pdfmod

    monkeypatch.setattr(
        pdfmod, "markdown_to_pdf", lambda md, out: out.write_text("pdf", encoding="utf-8")
    )

    src = tmp_path / "Foo-2506.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    notes_dir = workspace.work_dir(src)
    _seed_chapter(notes_dir, 1, "Introduction")  # prose
    _seed_chapter(notes_dir, 2, "Bibliography")   # reference matter (in _NON_PROSE_TITLES)
    # Distinct bodies so we can see which chapters were combined.
    workspace.chapter_export_path(notes_dir, 1, "outline", None).write_text(
        "# Introduction\n\nProse body.\n", encoding="utf-8"
    )
    workspace.chapter_export_path(notes_dir, 2, "outline", None).write_text(
        "# Bibliography\n\nReference body.\n", encoding="utf-8"
    )

    res = runner.invoke(cli.app, ["book", str(src)])  # prose-only default
    assert res.exit_code == 0, res.stdout
    book_md = (tmp_path / "Foo-2506.tnotes.md").read_text(encoding="utf-8")
    assert "Prose body." in book_md
    assert "Reference body." not in book_md


def test_book_empty_export_dir_errors_clearly(tmp_path):
    # Genuinely no exported chapters: the clear "run export first" error, exit 1.
    src = tmp_path / "Foo-2506.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    notes_dir = workspace.work_dir(src)
    workspace.export_dir(notes_dir).mkdir(parents=True, exist_ok=True)  # present but empty

    res = runner.invoke(cli.app, ["book", str(src)])
    assert res.exit_code == 1
    assert "no exported chapters" in res.stdout + str(res.stderr)
    assert not (tmp_path / "Foo-2506.tnotes.md").exists()
