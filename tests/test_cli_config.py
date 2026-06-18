"""CLI tests for the `tn config` surface and the layered model/effort
resolution in `tn extract`. Uses TN_CONFIG_DIR so $HOME is untouched, and stubs
out ingest/extraction so no PDF and no network are needed."""

from __future__ import annotations

import importlib

import pytest
from typer.testing import CliRunner

from trustworthy_notes.models import PageText

runner = CliRunner()


@pytest.fixture()
def cli(tmp_path, monkeypatch):
    """Reload config (so it re-reads TN_CONFIG_DIR) and hand back the cli module."""
    monkeypatch.setenv("TN_CONFIG_DIR", str(tmp_path / "tn"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from trustworthy_notes import config as config_module

    importlib.reload(config_module)
    from trustworthy_notes import cli as cli_module

    importlib.reload(cli_module)
    return cli_module


def test_config_set_and_show_round_trip(cli):
    res = runner.invoke(cli.app, ["config", "set-model", "claude-opus-4-8"])
    assert res.exit_code == 0
    res = runner.invoke(cli.app, ["config", "set-effort", "high"])
    assert res.exit_code == 0

    res = runner.invoke(cli.app, ["config", "show"])
    assert res.exit_code == 0
    assert "claude-opus-4-8" in res.stdout
    assert "high" in res.stdout
    assert "from config" in res.stdout


def test_config_show_built_in_defaults_when_unset(cli):
    res = runner.invoke(cli.app, ["config", "show"])
    assert res.exit_code == 0
    assert "claude-sonnet-4-6" in res.stdout  # built-in model
    assert "built-in" in res.stdout


def _stub_extract_pipeline(cli, monkeypatch):
    """Stub ingest + extraction so `tn extract` runs without a PDF or network,
    and return a dict that captures the (model, effort) the extractor saw."""
    captured: dict = {}

    page = PageText(page_index=0, page_number=1, text="The cat sat.", width=1.0, height=1.0)
    monkeypatch.setattr(cli.ingest, "read_pages", lambda _input: [page])
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")
    monkeypatch.setattr(cli.config, "get_api_key", lambda: "sk-test")
    monkeypatch.setattr(cli.workspace, "work_dir", lambda _input, _out: cli.Path("."))
    monkeypatch.setattr(cli.workspace, "extract_dir", lambda _wd: cli.Path("."))
    monkeypatch.setattr(cli.workspace, "page_notes_path", lambda _wd, _idx: cli.Path("page.yaml"))

    class _CapturingExtractor:
        def __init__(self, *, model, effort, max_tokens, api_key):
            captured["model"] = model
            captured["effort"] = effort

    import trustworthy_notes.extract_anthropic as ea
    import trustworthy_notes.extract as ex

    monkeypatch.setattr(ea, "AnthropicExtractor", _CapturingExtractor)
    # No worklist will run (page_notes_path stub + skip-existing off still builds
    # the worklist, but run_extract is stubbed to a no-op for safety).
    monkeypatch.setattr(ex, "run_extract", lambda *a, **k: ({"statements": [], "evidence": [], "terms": [], "relations": []}, []))
    monkeypatch.setattr(ex, "write_notes", lambda *a, **k: None)
    return captured


def test_extract_flag_wins_over_config_and_built_in(cli, tmp_path, monkeypatch):
    cli.config.set_model("claude-opus-4-8")
    cli.config.set_effort("medium")
    captured = _stub_extract_pipeline(cli, monkeypatch)

    pdf = tmp_path / "doc.pdf"
    pdf.write_text("x")  # exists check only; read_pages is stubbed
    res = runner.invoke(
        cli.app, ["extract", str(pdf), "--pages", "1", "--model", "claude-haiku-4-5", "--effort", ""]
    )
    assert res.exit_code == 0, res.stdout
    assert captured["model"] == "claude-haiku-4-5"  # explicit flag wins over config
    assert captured["effort"] == ""  # explicit empty effort wins over config


def test_extract_config_wins_over_built_in(cli, tmp_path, monkeypatch):
    cli.config.set_model("claude-opus-4-8")
    captured = _stub_extract_pipeline(cli, monkeypatch)

    pdf = tmp_path / "doc.pdf"
    pdf.write_text("x")
    res = runner.invoke(cli.app, ["extract", str(pdf), "--pages", "1"])
    assert res.exit_code == 0, res.stdout
    assert captured["model"] == "claude-opus-4-8"  # config wins (no flag)
    assert captured["effort"] == "low"  # built-in, since effort not configured


def test_extract_built_in_sonnet_when_nothing_set(cli, tmp_path, monkeypatch):
    captured = _stub_extract_pipeline(cli, monkeypatch)

    pdf = tmp_path / "doc.pdf"
    pdf.write_text("x")
    res = runner.invoke(cli.app, ["extract", str(pdf), "--pages", "1"])
    assert res.exit_code == 0, res.stdout
    assert captured["model"] == "claude-sonnet-4-6"  # built-in default, NOT opus
    assert captured["effort"] == "low"
