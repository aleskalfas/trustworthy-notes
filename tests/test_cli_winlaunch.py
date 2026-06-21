"""CLI wiring for the windowless (double-click / drag) launch (issue #33).

These assert the branch the cli takes given the windowless detector — they stub
`winlaunch.is_windowless_launch`, `input`, and the pipeline, never a real Windows
console. The two guarantees under test: a windowless launch onboards / runs and
PAUSEs; a NON-windowless launch (terminal, pipe, CI) is byte-for-byte unchanged
and never blocks on stdin. First real validation of the live launch is a Windows
run of the packaged exe.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from trustworthy_notes import cli, winlaunch

runner = CliRunner()


def _windowless(monkeypatch, value: bool):
    monkeypatch.setattr(winlaunch, "is_windowless_launch", lambda: value)


def _no_startup_nudge(monkeypatch):
    # Keep the #8 startup nudge / cleanup out of the way (source mode already does).
    from trustworthy_notes import updater

    monkeypatch.setattr(updater, "is_frozen", lambda: False)


# --- windowless BARE launch (double-click, no PDF) → onboarding + pause ------------


def test_windowless_bare_launch_onboards_and_pauses_when_key_unset(monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, True)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "none")
    saved = {}
    monkeypatch.setattr(cli.config, "set_api_key", lambda k: saved.update(key=k))

    # First input answers the key prompt; second satisfies the pause.
    res = runner.invoke(cli.app, [], input="sk-ant-paste\n\n")
    assert res.exit_code == 0, res.output
    assert saved.get("key") == "sk-ant-paste"
    assert "Drag a PDF" in res.output
    # It must NOT have dumped the raw --help.
    assert "--concurrency" not in res.output


def test_windowless_bare_launch_with_key_skips_prompt(monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, True)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")

    res = runner.invoke(cli.app, [], input="\n")  # only the pause keypress
    assert res.exit_code == 0, res.output
    assert "Setup complete" in res.output
    assert "Drag a PDF" in res.output


# --- windowless PDF launch (drag) → run + pause -----------------------------------


def test_windowless_pdf_launch_runs_pipeline_and_pauses(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, True)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")
    src = tmp_path / "Foo.pdf"
    src.write_bytes(b"%PDF-1.4 stub")

    def fake_run(pdf, **_k):
        return pdf.parent / "Foo.tnotes.pdf"

    monkeypatch.setattr("trustworthy_notes.pipeline.run", fake_run)

    # First \n answers the clean-vs-cited prompt (clean); second satisfies the pause.
    res = runner.invoke(cli.app, [str(src)], input="\n\n")
    assert res.exit_code == 0, res.output
    assert "Done — wrote Foo.tnotes.pdf" in res.output
    assert str(tmp_path) in res.output


def test_windowless_pdf_launch_prompts_clean_vs_cited(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, True)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")
    src = tmp_path / "Foo.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    seen = {}

    def fake_run(pdf, **kw):
        seen["cite"] = kw["cite"]
        return pdf.parent / "Foo.tnotes.pdf"

    monkeypatch.setattr("trustworthy_notes.pipeline.run", fake_run)

    # 'c' at the prompt selects the cited copy; trailing \n satisfies the pause.
    res = runner.invoke(cli.app, [str(src)], input="c\n\n")
    assert res.exit_code == 0, res.output
    assert seen["cite"] is True

    # Enter (empty) keeps the clean default.
    seen.clear()
    res = runner.invoke(cli.app, [str(src)], input="\n\n")
    assert res.exit_code == 0, res.output
    assert seen["cite"] is False


def test_windowless_pdf_launch_prompts_for_key_first(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, True)
    src = tmp_path / "Foo.pdf"
    src.write_bytes(b"%PDF-1.4 stub")

    # auth_source returns "none" until a key is saved, then "config" (real flow).
    state = {"key": None}
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config" if state["key"] else "none")
    monkeypatch.setattr(cli.config, "set_api_key", lambda k: state.update(key=k))
    monkeypatch.setattr(cli.config, "get_api_key", lambda: state["key"])

    def fake_run(pdf, **_k):
        return pdf.parent / "Foo.tnotes.pdf"

    monkeypatch.setattr("trustworthy_notes.pipeline.run", fake_run)

    # key prompt, then the clean-vs-cited prompt, then the pause.
    res = runner.invoke(cli.app, [str(src)], input="sk-ant-drag\n\n\n")
    assert res.exit_code == 0, res.output
    assert state["key"] == "sk-ant-drag"
    assert "Done — wrote Foo.tnotes.pdf" in res.output


def test_windowless_pdf_launch_pauses_on_pipeline_error(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, True)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")
    src = tmp_path / "Foo.pdf"
    src.write_bytes(b"%PDF-1.4 stub")

    def boom(pdf, **_k):
        raise ValueError("no text pages")

    monkeypatch.setattr("trustworthy_notes.pipeline.run", boom)

    # clean-vs-cited prompt, then the pause after the error.
    res = runner.invoke(cli.app, [str(src)], input="\n\n")
    assert res.exit_code == 1
    assert "no text pages" in res.output


# --- NON-windowless: every path unchanged, never blocks ---------------------------


def test_non_windowless_bare_launch_shows_help_and_does_not_block(monkeypatch):
    # A normal terminal `tnotes` with no args: Typer's help, no pause, no stdin read.
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, False)
    # No `input=` is passed: if anything tried to read stdin it would EOF/hang.
    res = runner.invoke(cli.app, [])
    # no_args_is_help exits 0 (Typer's help) — and crucially it returned at all.
    assert "trustworthy" in res.output.lower()
    assert "Setup complete" not in res.output


def test_non_windowless_help_path_is_untouched(monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, False)
    res = runner.invoke(cli.app, ["--help"])
    assert res.exit_code == 0
    assert "--concurrency" not in res.output  # group help, not extract's
    assert "extract" in res.output


def test_non_windowless_pdf_run_is_the_plain_path_no_pause(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, False)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")
    src = tmp_path / "Foo.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    monkeypatch.setattr("trustworthy_notes.pipeline.run", lambda pdf, **_k: pdf.parent / "Foo.tnotes.pdf")

    # No stdin: the plain path prints the bare path and exits, never pausing.
    res = runner.invoke(cli.app, [str(src)])
    assert res.exit_code == 0, res.output
    assert "Done — wrote" not in res.output  # the windowless-only friendly line
    assert "Foo.tnotes.pdf" in res.output
