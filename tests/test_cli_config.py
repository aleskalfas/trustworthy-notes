"""CLI tests for the `tnotes config` surface and the layered model/effort
resolution in `tnotes extract`. Uses TN_CONFIG_DIR so $HOME is untouched, and stubs
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


def test_config_set_no_update_check_round_trips(cli):
    assert cli.config.get_no_update_check() is False  # default: nudge on
    res = runner.invoke(cli.app, ["config", "set-no-update-check", "true"])
    assert res.exit_code == 0
    assert cli.config.get_no_update_check() is True
    res = runner.invoke(cli.app, ["config", "set-no-update-check", "false"])
    assert res.exit_code == 0
    assert cli.config.get_no_update_check() is False


def test_config_set_feedback_repo_and_reporter_round_trip(cli):
    res = runner.invoke(cli.app, ["config", "set-feedback-repo", "acme/tn-feedback"])
    assert res.exit_code == 0
    res = runner.invoke(cli.app, ["config", "set-reporter-name", "Jana"])
    assert res.exit_code == 0
    assert cli.config.get_feedback_repo() == "acme/tn-feedback"
    assert cli.config.get_reporter_name() == "Jana"
    res = runner.invoke(cli.app, ["config", "show"])
    assert "acme/tn-feedback" in res.stdout
    assert "Jana" in res.stdout


def test_config_set_feedback_token_prompts_and_saves(cli):
    res = runner.invoke(cli.app, ["config", "set-feedback-token"], input="ghp_secret\n")
    assert res.exit_code == 0
    assert cli.config.get_feedback_token() == "ghp_secret"
    # The token value must not be echoed back to the terminal (hidden input).
    assert "ghp_secret" not in res.stdout


def test_feedback_unconfigured_saves_local_file(cli, tmp_path, monkeypatch):
    # No feedback repo/token + no API key → raw-text report saved to a local file,
    # no consent prompt (nothing leaves the machine). No network at all.
    monkeypatch.setattr(cli.config, "get_api_key", lambda: None)
    monkeypatch.setattr(cli.config, "config_dir", lambda: tmp_path)
    res = runner.invoke(cli.app, ["feedback", "page 12 looks wrong"], input="Jana\n")
    assert res.exit_code == 0, res.stdout
    assert "Saved your report to" in res.stdout
    saved = list(tmp_path.glob("feedback-*.txt"))
    assert len(saved) == 1
    assert "page 12 looks wrong" in saved[0].read_text(encoding="utf-8")


def _stub_extract_pipeline(cli, monkeypatch):
    """Stub ingest + extraction so `tnotes extract` runs without a PDF or network,
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


def _mixed_document():
    """A 4-page document with two text pages and two non-text pages, so the
    page-type filter is observable. Page types mirror the layout classifier's
    labels (text / figure / table / blank) that read_pages stamps onto PageText."""
    return [
        PageText(page_index=0, page_number=1, text="Intro prose.", width=1.0, height=1.0, page_type="text"),
        PageText(page_index=1, page_number=2, text="(figure)", width=1.0, height=1.0, page_type="figure"),
        PageText(page_index=2, page_number=3, text="More prose.", width=1.0, height=1.0, page_type="text"),
        PageText(page_index=3, page_number=4, text="(blank)", width=1.0, height=1.0, page_type="blank"),
    ]


def _stub_extract_capturing_pages(cli, monkeypatch, doc):
    """Stub the extract pipeline over `doc` and capture which page numbers reach
    the extractor. Returns the list `extracted` that gets filled during the run."""
    extracted: list[int] = []

    monkeypatch.setattr(cli.ingest, "read_pages", lambda _input: doc)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")
    monkeypatch.setattr(cli.config, "get_api_key", lambda: "sk-test")
    monkeypatch.setattr(cli.config, "get_model", lambda: None)
    monkeypatch.setattr(cli.config, "get_effort", lambda: None)
    monkeypatch.setattr(cli.workspace, "work_dir", lambda _input, _out: cli.Path("."))
    monkeypatch.setattr(cli.workspace, "extract_dir", lambda _wd: cli.Path("."))
    monkeypatch.setattr(cli.workspace, "page_notes_path", lambda _wd, idx: cli.Path(f"page-{idx}.yaml"))

    class _NoopExtractor:
        def __init__(self, **_kwargs):
            pass

    import trustworthy_notes.extract_anthropic as ea
    import trustworthy_notes.extract as ex

    monkeypatch.setattr(ea, "AnthropicExtractor", _NoopExtractor)

    def _run_extract(page, *_a, **_k):
        extracted.append(page.page_number)
        return ({"statements": [], "evidence": [], "terms": [], "relations": []}, [], None)

    monkeypatch.setattr(ex, "run_extract_with_usage", _run_extract)
    monkeypatch.setattr(ex, "write_notes", lambda *a, **k: None)
    return extracted


def test_extract_no_pages_selects_all_text_pages(cli, tmp_path, monkeypatch):
    extracted = _stub_extract_capturing_pages(cli, monkeypatch, _mixed_document())

    pdf = tmp_path / "doc.pdf"
    pdf.write_text("x")
    res = runner.invoke(cli.app, ["extract", str(pdf)])  # no --pages
    assert res.exit_code == 0, res.stdout
    # Only the text pages (1 and 3) reach the extractor; figure/blank are skipped.
    assert extracted == [1, 3]


def test_extract_explicit_pages_overrides_default(cli, tmp_path, monkeypatch):
    extracted = _stub_extract_capturing_pages(cli, monkeypatch, _mixed_document())

    pdf = tmp_path / "doc.pdf"
    pdf.write_text("x")
    res = runner.invoke(cli.app, ["extract", str(pdf), "--pages", "3"])
    assert res.exit_code == 0, res.stdout
    # Explicit range wins: only page 3, default text-page derivation not applied.
    assert extracted == [3]


# --- Regression for issue #9: the compose-stage commands must honour the
# configured model too, not just `tnotes extract`. Before the fix these hardcoded
# claude-opus-4-8 and silently ran an expensive stage. ---


def test_terms_build_uses_configured_model_not_opus(cli, tmp_path, monkeypatch):
    cli.config.set_model("claude-sonnet-4-6")  # configured; no --model flag
    captured: dict = {}

    stage_dir = tmp_path / "stage"
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")
    monkeypatch.setattr(cli.config, "get_api_key", lambda: "sk-test")
    monkeypatch.setattr(cli.workspace, "work_dir", lambda _input, _notes: tmp_path)
    monkeypatch.setattr(cli.workspace, "compose_stage_dir", lambda _wd, _stage: stage_dir)

    import trustworthy_notes.term_store as term_store

    def _build_store(_pdf, _wd, *, model, effort, api_key):
        captured["model"] = model
        captured["effort"] = effort
        return {"terms": [], "links": {}}

    monkeypatch.setattr(term_store, "build_store", _build_store)

    pdf = tmp_path / "doc.pdf"
    pdf.write_text("x")
    res = runner.invoke(cli.app, ["terms", str(pdf), "--build"])
    assert res.exit_code == 0, res.stdout
    assert captured["model"] == "claude-sonnet-4-6"  # configured value, NOT opus
    assert captured["model"] != "claude-opus-4-8"


def test_relations_build_uses_configured_model_not_opus(cli, tmp_path, monkeypatch):
    cli.config.set_model("claude-sonnet-4-6")  # configured; no --model flag
    captured: dict = {}

    stage_dir = tmp_path / "stage"
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")
    monkeypatch.setattr(cli.config, "get_api_key", lambda: "sk-test")
    monkeypatch.setattr(cli.workspace, "work_dir", lambda _input, _notes: tmp_path)
    monkeypatch.setattr(cli.workspace, "compose_stage_dir", lambda _wd, _stage: stage_dir)

    import trustworthy_notes.relate as relate

    def _build_relations(_pdf, _wd, *, model, effort, api_key):
        captured["model"] = model
        captured["effort"] = effort
        return []

    monkeypatch.setattr(relate, "build_relations", _build_relations)

    pdf = tmp_path / "doc.pdf"
    pdf.write_text("x")
    res = runner.invoke(cli.app, ["relations", str(pdf), "--build"])
    assert res.exit_code == 0, res.stdout
    assert captured["model"] == "claude-sonnet-4-6"  # configured value, NOT opus
    assert captured["model"] != "claude-opus-4-8"
