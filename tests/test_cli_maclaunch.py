"""CLI wiring for `tnotes install-droplet` (issues #69, #102).

These assert the command's user-facing outcomes: on macOS the success path creates
BOTH droplets (Make Notes + Send Feedback), reporting each Desktop location and the
one-time Terminal-consent note; off macOS it prints a clear "macOS only" line and
exits cleanly (no error); a per-droplet osacompile failure is reported and exits
non-zero without skipping the other. The droplet mechanics are stubbed — we never run
the real `osacompile` here (that lives in test_maclaunch).
"""

from __future__ import annotations

from typer.testing import CliRunner

from trustworthy_notes import cli, maclaunch

runner = CliRunner()


def _no_startup_nudge(monkeypatch):
    # Keep the #8 startup nudge / cleanup out of the way (source mode already does).
    from trustworthy_notes import updater

    monkeypatch.setattr(updater, "is_frozen", lambda: False)


def test_install_droplet_success_creates_both_and_reports_consent(monkeypatch):
    _no_startup_nudge(monkeypatch)
    monkeypatch.setattr(cli.platform, "system", lambda: "Darwin")

    called = {"make_notes": False, "feedback": False}

    def _make_notes():
        called["make_notes"] = True
        return True

    def _feedback():
        called["feedback"] = True
        return True

    monkeypatch.setattr(maclaunch, "create_make_notes_droplet", _make_notes)
    monkeypatch.setattr(maclaunch, "create_feedback_droplet", _feedback)

    res = runner.invoke(cli.app, ["install-droplet"])
    assert res.exit_code == 0, res.output
    # Both primitives were invoked, and both are reported with their Desktop location.
    assert called["make_notes"] and called["feedback"]
    assert "Make Notes.app" in res.output
    assert "Send Feedback.app" in res.output
    assert "Desktop" in res.output
    # The one-time Terminal-automation consent note is surfaced.
    assert "Terminal" in res.output
    assert "one-time" in res.output


def test_install_droplet_off_macos_prints_clear_message_and_exits_clean(monkeypatch):
    _no_startup_nudge(monkeypatch)
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")

    def must_not_create():
        raise AssertionError("must not attempt a droplet off macOS")

    monkeypatch.setattr(maclaunch, "create_make_notes_droplet", must_not_create)
    monkeypatch.setattr(maclaunch, "create_feedback_droplet", must_not_create)

    res = runner.invoke(cli.app, ["install-droplet"])
    assert res.exit_code == 0, res.output  # a gentle note, never an error
    assert "macOS only" in res.output


def test_install_droplet_one_failure_still_attempts_both_and_exits_nonzero(monkeypatch):
    """A failed osacompile on one droplet must not silently skip the other (issue #102)."""
    _no_startup_nudge(monkeypatch)
    monkeypatch.setattr(cli.platform, "system", lambda: "Darwin")

    called = {"make_notes": False, "feedback": False}

    def _make_notes():
        called["make_notes"] = True
        return False  # this one fails

    def _feedback():
        called["feedback"] = True
        return True  # the other still succeeds

    monkeypatch.setattr(maclaunch, "create_make_notes_droplet", _make_notes)
    monkeypatch.setattr(maclaunch, "create_feedback_droplet", _feedback)

    res = runner.invoke(cli.app, ["install-droplet"])
    assert res.exit_code == 1
    # Both were attempted despite the first failing, and the failure was reported.
    assert called["make_notes"] and called["feedback"]
    assert "Couldn't create" in res.output or "couldn't create" in res.output.lower()
    # The succeeding droplet is still reported.
    assert "Send Feedback.app" in res.output
