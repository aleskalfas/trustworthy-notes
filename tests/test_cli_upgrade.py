"""CLI tests for `tnotes upgrade` and the `--version` flag (issue #7).

These cover the thin CLI seam — that the command routes to the updater, reports
its outcome, and turns an UpgradeError into a non-zero exit with a message — by
stubbing the updater. The updater's own logic is tested in test_updater.py.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from trustworthy_notes import __version__, cli, updater

runner = CliRunner()


def test_version_flag_prints_version():
    res = runner.invoke(cli.app, ["--version"])
    assert res.exit_code == 0
    assert res.stdout.strip() == __version__


def test_upgrade_reports_the_outcome_message(monkeypatch):
    monkeypatch.setattr(
        updater, "upgrade",
        lambda **_k: updater.UpgradeOutcome(status="upgraded", message="upgraded 0.1.0 → 0.2.0."),
    )
    # Don't let startup cleanup touch the real running exe.
    monkeypatch.setattr(updater, "is_frozen", lambda: False)
    res = runner.invoke(cli.app, ["upgrade"])
    assert res.exit_code == 0
    assert "upgraded 0.1.0 → 0.2.0." in res.stdout


def test_upgrade_surfaces_an_error_as_nonzero_exit(monkeypatch):
    def boom(**_k):
        raise updater.UpgradeError("could not reach GitHub")

    monkeypatch.setattr(updater, "upgrade", boom)
    monkeypatch.setattr(updater, "is_frozen", lambda: False)
    res = runner.invoke(cli.app, ["upgrade"])
    assert res.exit_code == 1
    assert "could not reach GitHub" in res.stderr


def test_upgrade_from_source_exits_cleanly(monkeypatch):
    # Real updater, but force the source-checkout branch: clean exit, helpful note.
    monkeypatch.setattr(updater, "is_frozen", lambda: False)
    res = runner.invoke(cli.app, ["upgrade"])
    assert res.exit_code == 0
    assert "git pull" in res.stdout


# --- the launch-time nudge (issue #8) ---
#
# The nudge fires from the @app.callback, which runs for EVERY invocation. These
# tests stub the release-check and isatty so we exercise the prompt/skip logic
# without a network call or a real terminal. The cache/timeout/silent-fail half is
# covered in test_updater.py; here we prove the TTY guard, the one-tap behaviour,
# and — critically — that a non-interactive run can never hang or affect output.


def _frozen(monkeypatch):
    """Pretend we are a frozen build so the callback's nudge path is reached."""
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setattr(updater, "cleanup_stale", lambda *a, **k: None)


def _tty(monkeypatch, value: bool):
    """Force the interactive-TTY guard (CliRunner swaps the std streams, so we stub
    the cli._interactive helper rather than isatty directly)."""
    monkeypatch.setattr(cli, "_interactive", lambda: value)


def test_nudge_offers_and_one_tap_yes_runs_the_upgrade(monkeypatch):
    _frozen(monkeypatch)
    _tty(monkeypatch, True)
    monkeypatch.setattr(updater, "check_for_update", lambda *a, **k: "0.2.0")
    called = {"upgraded": False}

    def fake_upgrade(**_k):
        called["upgraded"] = True
        return updater.UpgradeOutcome(status="upgraded", message="upgraded 0.1.0 → 0.2.0.")

    monkeypatch.setattr(updater, "upgrade", fake_upgrade)

    # `Y` answers the prompt; the args after it are the command that would have run.
    res = runner.invoke(cli.app, ["config", "show"], input="Y\n")
    assert "0.2.0 is available" in res.stdout
    assert called["upgraded"] is True
    assert "upgraded 0.1.0 → 0.2.0." in res.stdout


def test_nudge_decline_proceeds_with_the_requested_command(monkeypatch):
    _frozen(monkeypatch)
    _tty(monkeypatch, True)
    monkeypatch.setattr(updater, "check_for_update", lambda *a, **k: "0.2.0")

    def must_not_upgrade(**_k):
        raise AssertionError("declining the nudge must not upgrade")

    monkeypatch.setattr(updater, "upgrade", must_not_upgrade)

    res = runner.invoke(cli.app, ["config", "show"], input="n\n")
    assert res.exit_code == 0
    assert "config file" in res.stdout  # the real command ran


def test_nudge_skips_entirely_without_a_tty_and_does_not_hang(monkeypatch):
    # The CI release smoke runs `tnotes.exe --help` with stdout captured (no TTY).
    # The nudge must skip without ever reading stdin, so it can never block.
    _frozen(monkeypatch)
    _tty(monkeypatch, False)

    def must_not_check(*a, **k):
        raise AssertionError("non-interactive run must not even check")

    monkeypatch.setattr(updater, "check_for_update", must_not_check)

    # No stdin provided: if the nudge tried to prompt, this would hang/error.
    res = runner.invoke(cli.app, ["config", "show"])
    assert res.exit_code == 0
    assert "config file" in res.stdout


def test_nudge_silent_when_up_to_date(monkeypatch):
    _frozen(monkeypatch)
    _tty(monkeypatch, True)
    monkeypatch.setattr(updater, "check_for_update", lambda *a, **k: None)
    res = runner.invoke(cli.app, ["config", "show"])
    assert res.exit_code == 0
    assert "available" not in res.stdout


def test_nudge_never_fires_in_source_mode(monkeypatch):
    monkeypatch.setattr(updater, "is_frozen", lambda: False)

    def must_not_check(*a, **k):
        raise AssertionError("source run must not nudge")

    monkeypatch.setattr(updater, "check_for_update", must_not_check)
    res = runner.invoke(cli.app, ["config", "show"])
    assert res.exit_code == 0


def test_nudge_does_not_break_help_output(monkeypatch):
    # --help is an eager path: it must short-circuit before the nudge body runs.
    _frozen(monkeypatch)
    _tty(monkeypatch, True)

    def must_not_check(*a, **k):
        raise AssertionError("--help must not trigger the nudge")

    monkeypatch.setattr(updater, "check_for_update", must_not_check)
    res = runner.invoke(cli.app, ["--help"])
    assert res.exit_code == 0
    assert "trustworthy" in res.stdout.lower()


def test_nudge_does_not_break_version_output(monkeypatch):
    # --version is eager too — it prints the version and exits before the nudge.
    _frozen(monkeypatch)
    _tty(monkeypatch, True)

    def must_not_check(*a, **k):
        raise AssertionError("--version must not trigger the nudge")

    monkeypatch.setattr(updater, "check_for_update", must_not_check)
    res = runner.invoke(cli.app, ["--version"])
    assert res.exit_code == 0
    assert res.stdout.strip() == __version__
