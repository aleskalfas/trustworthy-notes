"""Tests for the Windows-only launch *mechanics* (issues #33, #39).

The real triggers — a Windows double-click / drag that gives the exe its own
console, and a real `.lnk` write — cannot be exercised on macOS/Linux/CI, so these
tests stub the platform check, `ctypes`, `input`, and `subprocess` to drive every
branch. The detector's own fail-safe contract is asserted directly (non-Windows →
False; a raising ctypes call → False; an ambiguous count → False), and the
shortcut primitive's PowerShell command + off-Windows no-op are asserted with
`subprocess` mocked. First real validation of the live launch is a Windows run.

The onboarding *flow* (key prompt, feedback setup) moved to `onboarding.py`; its
tests live in `test_onboarding.py`.
"""

from __future__ import annotations

import builtins
import subprocess

from trustworthy_notes import winlaunch


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


# --- create_feedback_shortcut: PowerShell command + off-Windows no-op -------------


def test_shortcut_is_a_noop_off_windows(monkeypatch):
    monkeypatch.setattr(winlaunch.platform, "system", lambda: "Darwin")

    def must_not_shell_out(*_a, **_k):
        raise AssertionError("must not shell out off Windows")

    monkeypatch.setattr(winlaunch.subprocess, "run", must_not_shell_out)
    assert winlaunch.create_feedback_shortcut() is False


def test_shortcut_builds_powershell_command_targeting_exe_feedback(monkeypatch):
    monkeypatch.setattr(winlaunch.platform, "system", lambda: "Windows")
    monkeypatch.setattr(winlaunch.sys, "executable", r"C:\Users\me\tnotes\tnotes.exe")
    captured = {}

    def fake_run(argv, **_k):
        captured["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(winlaunch.subprocess, "run", fake_run)

    assert winlaunch.create_feedback_shortcut() is True
    argv = captured["argv"]
    assert argv[0] == "powershell"
    assert "-Command" in argv
    script = argv[-1]
    # The target is the stable exe (sys.executable), the argument is `feedback`, and
    # it goes onto the Desktop — never a versioned/temp path (ADR-001 survivability).
    assert "WScript.Shell" in script and "CreateShortcut" in script
    assert r"C:\Users\me\tnotes\tnotes.exe" in script
    assert "$s.Arguments = 'feedback'" in script
    assert "Send Feedback.lnk" in script
    assert "Desktop" in script


def test_shortcut_returns_false_when_powershell_fails(monkeypatch):
    monkeypatch.setattr(winlaunch.platform, "system", lambda: "Windows")

    def fake_run(argv, **_k):
        return subprocess.CompletedProcess(argv, 1, b"", b"boom")

    monkeypatch.setattr(winlaunch.subprocess, "run", fake_run)
    assert winlaunch.create_feedback_shortcut() is False


def test_shortcut_returns_false_when_powershell_missing(monkeypatch):
    monkeypatch.setattr(winlaunch.platform, "system", lambda: "Windows")

    def fake_run(*_a, **_k):
        raise OSError("powershell not found")

    monkeypatch.setattr(winlaunch.subprocess, "run", fake_run)
    assert winlaunch.create_feedback_shortcut() is False
