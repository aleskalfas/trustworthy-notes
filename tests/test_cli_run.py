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

    def fake_run(pdf, *, pages, force, cite, log, parse_pages):
        seen.update(pdf=Path(pdf), pages=pages, force=force, cite=cite)
        return pdf.parent / "Foo.tnotes.pdf"

    monkeypatch.setattr("trustworthy_notes.pipeline.run", fake_run)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")

    res = runner.invoke(cli.app, [str(src)])
    assert res.exit_code == 0, res.stdout
    assert seen["pdf"] == src
    assert seen == {"pdf": src, "pages": None, "force": False, "cite": False}
    assert "Foo.tnotes.pdf" in res.stdout


def test_bare_pdf_threads_pages_force_cite(tmp_path, monkeypatch):
    src = tmp_path / "Foo.pdf"
    src.write_bytes(b"%PDF-1.4 stub")

    seen = {}

    def fake_run(pdf, *, pages, force, cite, log, parse_pages):
        seen.update(pages=pages, force=force, cite=cite)
        return pdf.parent / "out.pdf"

    monkeypatch.setattr("trustworthy_notes.pipeline.run", fake_run)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")

    res = runner.invoke(cli.app, [str(src), "-p", "1-30", "--force", "--cite"])
    assert res.exit_code == 0, res.stdout
    assert seen == {"pages": "1-30", "force": True, "cite": True}


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
