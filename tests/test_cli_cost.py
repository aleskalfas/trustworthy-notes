"""The `extract` command shows a per-page and run-total cost estimate.

The extractor is stubbed to return a known usage object, so we assert on the
rendered estimate without any network call. Ingest is stubbed to a single text
page. Two paths matter: a priced model prints `est. $…`, an unknown model prints
the graceful 'unavailable' note and never `$0`.
"""

from __future__ import annotations

from typer.testing import CliRunner

from trustworthy_notes import cli
from trustworthy_notes.models import PageText

runner = CliRunner()


def _one_text_page():
    return [PageText(page_index=0, page_number=1, text="The cat sat.", width=1.0, height=1.0)]


def _stub_extract_flow(monkeypatch, *, usage):
    """Wire up auth, ingest, the extractor, and the extract result.

    `run_extract_with_usage` is imported into the command body from
    `trustworthy_notes.extract`, so we patch it on that source module.
    """
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")
    monkeypatch.setattr(cli.config, "get_api_key", lambda: "k")
    monkeypatch.setattr(cli.ingest, "read_pages", lambda _input: _one_text_page())

    class _StubExtractor:
        def __init__(self, **kw):
            pass

    monkeypatch.setattr(
        "trustworthy_notes.extract_anthropic.AnthropicExtractor", _StubExtractor
    )

    notes = {"statements": [], "evidence": [], "terms": [], "relations": []}

    def fake_run(page, extractor, document, context=None):
        return notes, [], usage

    monkeypatch.setattr(
        "trustworthy_notes.extract.run_extract_with_usage", fake_run
    )
    monkeypatch.setattr("trustworthy_notes.extract.write_notes", lambda *a, **k: None)


def test_extract_renders_per_page_and_run_total_estimate(tmp_path, monkeypatch):
    src = tmp_path / "Foo.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    # 1M input + 1M output on Sonnet = $3 + $15 = $18.0000 for the page.
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    _stub_extract_flow(monkeypatch, usage=usage)

    res = runner.invoke(
        cli.app, ["extract", str(src), "-p", "1", "-m", "claude-sonnet-4-6", "-o", str(tmp_path / "out")]
    )
    assert res.exit_code == 0, res.output
    assert "est. $18.0000 (pricing as of 2026-06-04)" in res.output
    assert "run total: est. $18.0000 (pricing as of 2026-06-04)" in res.output


def test_extract_unknown_model_renders_unavailable_not_zero(tmp_path, monkeypatch):
    src = tmp_path / "Foo.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    _stub_extract_flow(monkeypatch, usage=usage)

    res = runner.invoke(
        cli.app, ["extract", str(src), "-p", "1", "-m", "made-up-model", "-o", str(tmp_path / "out")]
    )
    assert res.exit_code == 0, res.output
    assert "cost estimate unavailable for 'made-up-model'" in res.output
    assert "$0" not in res.output
