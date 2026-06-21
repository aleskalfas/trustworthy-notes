"""CLI wiring for `tnotes install-droplet` (issue #69).

These assert the command's two user-facing outcomes: on macOS the success path
reports the Desktop location and the one-time Terminal-consent note; off macOS it
prints a clear "macOS only" line and exits cleanly (no error). The droplet mechanics
are stubbed — we never run the real `osacompile` here (that lives in test_maclaunch).
"""

from __future__ import annotations

from typer.testing import CliRunner

from trustworthy_notes import cli, maclaunch

runner = CliRunner()


def _no_startup_nudge(monkeypatch):
    # Keep the #8 startup nudge / cleanup out of the way (source mode already does).
    from trustworthy_notes import updater

    monkeypatch.setattr(updater, "is_frozen", lambda: False)


def test_install_droplet_success_reports_location_and_consent(monkeypatch):
    _no_startup_nudge(monkeypatch)
    monkeypatch.setattr(cli.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(maclaunch, "create_feedback_droplet", lambda: True)

    res = runner.invoke(cli.app, ["install-droplet"])
    assert res.exit_code == 0, res.output
    assert "Send Feedback.app" in res.output
    assert "Desktop" in res.output
    # The one-time Terminal-automation consent note is surfaced.
    assert "Terminal" in res.output
    assert "one-time" in res.output


def test_install_droplet_off_macos_prints_clear_message_and_exits_clean(monkeypatch):
    _no_startup_nudge(monkeypatch)
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")

    def must_not_create():
        raise AssertionError("must not attempt the droplet off macOS")

    monkeypatch.setattr(maclaunch, "create_feedback_droplet", must_not_create)

    res = runner.invoke(cli.app, ["install-droplet"])
    assert res.exit_code == 0, res.output  # a gentle note, never an error
    assert "macOS only" in res.output


def test_install_droplet_reports_failure_nonzero(monkeypatch):
    _no_startup_nudge(monkeypatch)
    monkeypatch.setattr(cli.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(maclaunch, "create_feedback_droplet", lambda: False)

    res = runner.invoke(cli.app, ["install-droplet"])
    assert res.exit_code == 1
    assert "Couldn't create" in res.output or "couldn't create" in res.output.lower()
