"""CLI routing for the one-command path (issue #19): a bare PDF runs the whole
pipeline, while the per-stage subcommands still dispatch unchanged. The pipeline
itself is stubbed (see test_pipeline for the orchestration); here we assert the
Typer wiring around it."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from trustworthy_notes import cli

runner = CliRunner()


def test_help_lists_subcommands_and_hides_run():
    res = runner.invoke(cli.app, ["--help"])
    assert res.exit_code == 0, res.stdout
    for name in ("extract", "book", "terms", "relations", "assemble", "export", "dedup"):
        assert name in res.stdout, name
    # the orchestrator's internal `run` command is hidden from the listing
    assert " run " not in res.stdout


def test_subcommands_still_dispatch():
    # A subcommand and its own options must parse as before, untouched by the
    # bare-PDF routing.
    res = runner.invoke(cli.app, ["extract", "--help"])
    assert res.exit_code == 0, res.stdout
    assert "--concurrency" in res.stdout

    res = runner.invoke(cli.app, ["layout", "--help"])
    assert res.exit_code == 0
    assert "Source PDF" in res.stdout


def test_bare_pdf_routes_to_orchestrator(tmp_path, monkeypatch):
    src = tmp_path / "Foo.pdf"
    src.write_bytes(b"%PDF-1.4 stub")

    seen = {}

    def fake_run(pdf, *, pages, force, cite, keep_md, model, effort, max_tokens, language,
                 confirm_translation, log, parse_pages):
        seen.update(pdf=Path(pdf), pages=pages, force=force, cite=cite, keep_md=keep_md,
                    model=model, effort=effort, max_tokens=max_tokens, language=language)
        return pdf.parent / "Foo.tnotes.pdf"

    monkeypatch.setattr("trustworthy_notes.pipeline.run", fake_run)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")

    res = runner.invoke(cli.app, [str(src)])
    assert res.exit_code == 0, res.stdout
    assert seen["pdf"] == src
    # model/effort/max_tokens/language default to None → pipeline.run falls back to config/default.
    assert seen == {"pdf": src, "pages": None, "force": False, "cite": False,
                    "keep_md": False, "model": None, "effort": None, "max_tokens": None,
                    "language": None}
    assert "Foo.tnotes.pdf" in res.stdout


def test_bare_pdf_threads_pages_force_cite(tmp_path, monkeypatch):
    src = tmp_path / "Foo.pdf"
    src.write_bytes(b"%PDF-1.4 stub")

    seen = {}

    def fake_run(pdf, *, pages, force, cite, keep_md, model, effort, max_tokens, language,
                 confirm_translation, log, parse_pages):
        seen.update(pages=pages, force=force, cite=cite, keep_md=keep_md,
                    model=model, effort=effort, max_tokens=max_tokens, language=language)
        return pdf.parent / "out.pdf"

    monkeypatch.setattr("trustworthy_notes.pipeline.run", fake_run)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")

    res = runner.invoke(cli.app, [str(src), "-p", "1-30", "--force", "--cite", "--md",
                                  "--model", "claude-opus-4-6", "--effort", "high",
                                  "--max-tokens", "64000", "--language", "cs"])
    assert res.exit_code == 0, res.stdout
    assert seen == {"pages": "1-30", "force": True, "cite": True, "keep_md": True,
                    "model": "claude-opus-4-6", "effort": "high", "max_tokens": 64000,
                    "language": "cs"}


def test_confirm_translation_is_passed_and_declines_non_interactively(tmp_path, monkeypatch):
    # #115: the CLI builds a TTY-gated confirm callable and hands it to pipeline.run.
    # Under CliRunner the streams aren't TTYs (and it's not a windowless launch), so the
    # callable declines without prompting — the documented non-interactive behaviour.
    src = tmp_path / "Foo.pdf"
    src.write_bytes(b"%PDF-1.4 stub")

    captured = {}

    def fake_run(pdf, *, confirm_translation, **kw):
        captured["confirm"] = confirm_translation
        return pdf.parent / "Foo.tnotes.pdf"

    monkeypatch.setattr("trustworthy_notes.pipeline.run", fake_run)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")

    res = runner.invoke(cli.app, [str(src)])
    assert res.exit_code == 0, res.stdout
    # the gate would call confirm(detected, preferred); non-interactive → declines
    assert captured["confirm"]("cs", "en") is False


def test_bare_pdf_requires_auth(tmp_path, monkeypatch):
    src = tmp_path / "Foo.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    monkeypatch.setattr(cli.config, "auth_source", lambda: "none")

    res = runner.invoke(cli.app, [str(src)])
    assert res.exit_code == 1
    assert "auth set-key" in res.output


def test_missing_pdf_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")
    res = runner.invoke(cli.app, [str(tmp_path / "nope.pdf")])
    # routed to the orchestrator, which validates the path exists
    assert res.exit_code == 2
