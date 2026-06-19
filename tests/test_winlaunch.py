"""Tests for the windowless-launch helpers (issue #33).

The real trigger — a Windows double-click / drag that gives the exe its own
console — cannot be exercised on macOS/Linux/CI, so these tests stub the detector
(`is_windowless_launch`) and `input` to drive every branch. The detector's own
fail-safe contract is asserted directly (non-Windows → False; a raising ctypes
call → False; an ambiguous count → False). First real validation of the live
console-ownership query is a Windows run.
"""

from __future__ import annotations

import builtins

import pytest

from trustworthy_notes import config, winlaunch


# --- is_windowless_launch: fail-safe contract -----------------------------------


def test_detector_false_off_windows(monkeypatch):
    monkeypatch.setattr(winlaunch.platform, "system", lambda: "Darwin")
    assert winlaunch.is_windowless_launch() is False


def test_detector_false_when_ctypes_call_raises(monkeypatch):
    # Pretend we're on Windows, but the console-list query blows up (no console,
    # locked-down build): the safe answer is "not windowless".
    monkeypatch.setattr(winlaunch.platform, "system", lambda: "Windows")
    import ctypes

    def boom(*_a, **_k):
        raise OSError("no console")

    # The function imports ctypes internally; patch the attribute it reaches for.
    monkeypatch.setattr(ctypes, "windll", _Raiser(boom), raising=False)
    assert winlaunch.is_windowless_launch() is False


class _Raiser:
    def __init__(self, fn):
        self._fn = fn

    def __getattr__(self, _name):
        self._fn()


def test_detector_true_only_for_exactly_one_attached(monkeypatch):
    monkeypatch.setattr(winlaunch.platform, "system", lambda: "Windows")
    import ctypes

    # A fake kernel32 whose GetConsoleProcessList returns a configurable count.
    class _K:
        count = 1

        def GetConsoleProcessList(self, _slot, _n):
            return self.count

    fake = type("W", (), {"kernel32": _K()})()
    monkeypatch.setattr(ctypes, "windll", fake, raising=False)

    fake.kernel32.count = 1
    assert winlaunch.is_windowless_launch() is True
    fake.kernel32.count = 2  # launched from a shell → not windowless
    assert winlaunch.is_windowless_launch() is False
    fake.kernel32.count = 0  # ambiguous error return → fail safe
    assert winlaunch.is_windowless_launch() is False


# --- pause: windowless-only --------------------------------------------------------


def test_pause_is_a_noop_when_not_windowless(monkeypatch):
    monkeypatch.setattr(winlaunch, "is_windowless_launch", lambda: False)

    def must_not_read(*_a, **_k):
        raise AssertionError("pause must not read stdin in a terminal/CI run")

    monkeypatch.setattr(builtins, "input", must_not_read)
    winlaunch.pause()  # returns immediately, no block


def test_pause_waits_for_a_keypress_when_windowless(monkeypatch):
    monkeypatch.setattr(winlaunch, "is_windowless_launch", lambda: True)
    seen = {"called": False}

    def fake_input(_prompt=""):
        seen["called"] = True
        return ""

    monkeypatch.setattr(builtins, "input", fake_input)
    winlaunch.pause()
    assert seen["called"] is True


def test_pause_swallows_eof(monkeypatch):
    monkeypatch.setattr(winlaunch, "is_windowless_launch", lambda: True)

    def eof(_prompt=""):
        raise EOFError

    monkeypatch.setattr(builtins, "input", eof)
    winlaunch.pause()  # must not propagate


# --- ensure_api_key: prompt + save on first run -----------------------------------


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point the config at a throwaway dir and clear the auth env/login signals."""
    monkeypatch.setenv("TN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # auth_source() also checks ~/.config/anthropic; force a clean "none".
    monkeypatch.setattr(config, "auth_source", _real_then("none"))
    return tmp_path


def _real_then(_value):
    # auth_source must reflect the saved key after we write it, so we delegate to a
    # live reimplementation keyed only on the saved config (env already cleared).
    def fn():
        return "config" if config.get_api_key() else "none"

    return fn


def test_ensure_api_key_prompts_and_saves_when_unset(isolated_config, monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _p="": "sk-ant-test-123")
    assert config.get_api_key() is None
    assert winlaunch.ensure_api_key() is True
    assert config.get_api_key() == "sk-ant-test-123"


def test_ensure_api_key_returns_false_on_empty_input(isolated_config, monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _p="": "   ")
    assert winlaunch.ensure_api_key() is False
    assert config.get_api_key() is None


def test_ensure_api_key_skips_prompt_when_already_set(isolated_config, monkeypatch):
    config.set_api_key("sk-already-there")

    def must_not_prompt(_p=""):
        raise AssertionError("must not prompt when a key is already configured")

    monkeypatch.setattr(builtins, "input", must_not_prompt)
    assert winlaunch.ensure_api_key() is True


def test_onboard_prompts_for_key_then_prints_next_step(isolated_config, monkeypatch, capsys):
    monkeypatch.setattr(builtins, "input", lambda _p="": "sk-ant-onboard")
    winlaunch.onboard()
    out = capsys.readouterr().out
    assert config.get_api_key() == "sk-ant-onboard"
    assert "Drag a PDF" in out
