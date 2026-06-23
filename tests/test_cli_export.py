"""CLI test for the `tnotes export` command's --language flag (#112): the standalone
export resolves the preferred language (flag > config > built-in) and hands it to
export.study_document, the call that synthesizes the reader prose (ADR-008). No
network — study_document and the Anthropic client are stubbed."""

from __future__ import annotations

import anthropic
import yaml
from typer.testing import CliRunner

from trustworthy_notes import cli, config, export as exp, workspace

runner = CliRunner()


def _seed_chapter(notes_dir, num=6, title="Background"):
    """Lay down one composed chapter notes-set for `export` to synthesize from."""
    cdir = workspace.compose_stage_dir(notes_dir, "chapters")
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / f"chapter-{num:03d}.notes.yaml").write_text(
        yaml.safe_dump({"source": {"chapter_id": title, "chapter_title": title},
                        "statements": [{"id": "s-1", "type": "claim", "text": "a"}]}),
        encoding="utf-8",
    )


def _stub_synthesis(monkeypatch, seen):
    """Stub the API edges: a no-op Anthropic client and a study_document that records
    the language it was called with and returns a minimal document."""
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: object())
    monkeypatch.setattr(config, "auth_source", lambda: "config")

    def fake_study(cset, **kw):
        seen["language"] = kw.get("language")
        return {"markdown": "## P\n- a [s-1](#note-s-1)\n", "cited": {"s-1"}, "unknown": []}

    monkeypatch.setattr(exp, "study_document", fake_study)


def _run(tmp_path, monkeypatch, args):
    seen: dict = {}
    _stub_synthesis(monkeypatch, seen)
    src = tmp_path / "Foo-2506.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    _seed_chapter(workspace.work_dir(src))
    res = runner.invoke(cli.app, ["export", str(src), "--all", *args])
    assert res.exit_code == 0, res.stdout
    return seen


def test_export_passes_language_flag_to_study_document(tmp_path, monkeypatch):
    seen = _run(tmp_path, monkeypatch, ["--language", "cs"])
    assert seen["language"] == "cs"   # explicit flag reaches synthesis


def test_export_resolves_language_from_config_when_flag_absent(tmp_path, monkeypatch):
    # No flag → resolve_language falls through to config (here stubbed to "ja").
    monkeypatch.setattr(config, "resolve_language", lambda flag: flag or "ja")
    seen = _run(tmp_path, monkeypatch, [])
    assert seen["language"] == "ja"


def test_export_defaults_to_english_when_unset(tmp_path, monkeypatch):
    # No flag, no config → the built-in default (en); the English path is a no-op in
    # study_document, but the resolved value is still threaded through.
    monkeypatch.setattr(config, "get_language", lambda: None)
    seen = _run(tmp_path, monkeypatch, [])
    assert seen["language"] == config.DEFAULT_LANGUAGE


def test_export_writes_language_aware_filename(tmp_path, monkeypatch):
    # #127 scope edge: the standalone `export` writes the language-aware file via
    # workspace.chapter_export_path — `--language cs` writes chapter-006.outline.cs.md,
    # and the English run writes the bare chapter-006.outline.md, never colliding.
    _stub_synthesis(monkeypatch, {})
    src = tmp_path / "Foo-2506.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    work = workspace.work_dir(src)
    _seed_chapter(work)

    assert runner.invoke(cli.app, ["export", str(src), "--all"]).exit_code == 0
    assert runner.invoke(cli.app, ["export", str(src), "--all", "--language", "cs"]).exit_code == 0

    en = workspace.chapter_export_path(work, 6, "outline", None)
    cs = workspace.chapter_export_path(work, 6, "outline", "cs")
    assert en.name == "chapter-006.outline.md"
    assert cs.name == "chapter-006.outline.cs.md"
    assert en.is_file() and cs.is_file()   # both written; the cs run did not overwrite English
