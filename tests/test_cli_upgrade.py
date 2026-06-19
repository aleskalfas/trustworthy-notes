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
