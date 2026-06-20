"""Tests for the first-run onboarding flow (issues #33, #39).

The real trigger — a Windows double-click that gives the exe its own console —
can't be exercised on macOS/Linux/CI, so these stub `input` and the config setters
to drive every branch: the API-key prompt (extracted from `winlaunch` unchanged),
the optional feedback-setup step (opt-in stores repo/token/name; declining skips
cleanly), and the one-tap desktop-shortcut offer. First real validation of the
live windowless path is a Windows run of the packaged exe.
"""

from __future__ import annotations

import builtins

import pytest

from trustworthy_notes import config, onboarding, winlaunch


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point the config at a throwaway dir and clear the auth env/login signals."""
    monkeypatch.setenv("TN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # auth_source() also checks ~/.config/anthropic; force a clean "none".
    monkeypatch.setattr(config, "auth_source", _real_then())
    return tmp_path


def _real_then():
    # auth_source must reflect the saved key after we write it, so we delegate to a
    # live reimplementation keyed only on the saved config (env already cleared).
    def fn():
        return "config" if config.get_api_key() else "none"

    return fn


def _scripted_input(answers):
    """An `input` stub that returns the queued answers in order."""
    queue = list(answers)

    def fake_input(_prompt=""):
        return queue.pop(0)

    return fake_input


# --- ensure_api_key: prompt + save on first run (unchanged after extraction) -------


def test_ensure_api_key_prompts_and_saves_when_unset(isolated_config, monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _p="": "sk-ant-test-123")
    assert config.get_api_key() is None
    assert onboarding.ensure_api_key() is True
    assert config.get_api_key() == "sk-ant-test-123"


def test_ensure_api_key_returns_false_on_empty_input(isolated_config, monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _p="": "   ")
    assert onboarding.ensure_api_key() is False
    assert config.get_api_key() is None


def test_ensure_api_key_skips_prompt_when_already_set(isolated_config, monkeypatch):
    config.set_api_key("sk-already-there")

    def must_not_prompt(_p=""):
        raise AssertionError("must not prompt when a key is already configured")

    monkeypatch.setattr(builtins, "input", must_not_prompt)
    assert onboarding.ensure_api_key() is True


# --- setup_feedback: opt-in stores repo/token/name; declining skips cleanly --------


def test_setup_feedback_stores_repo_token_and_name_when_opted_in(isolated_config, monkeypatch):
    monkeypatch.setattr(
        builtins,
        "input",
        _scripted_input(["acme/tnotes-feedback", "ghp_test_token", "Ada Lovelace"]),
    )
    assert onboarding.setup_feedback() is True
    assert config.get_feedback_repo() == "acme/tnotes-feedback"
    assert config.get_feedback_token() == "ghp_test_token"
    assert config.get_reporter_name() == "Ada Lovelace"


def test_setup_feedback_name_is_optional(isolated_config, monkeypatch):
    monkeypatch.setattr(
        builtins, "input", _scripted_input(["acme/fb", "ghp_tok", ""])
    )
    assert onboarding.setup_feedback() is True
    assert config.get_feedback_repo() == "acme/fb"
    assert config.get_feedback_token() == "ghp_tok"
    assert config.get_reporter_name() is None


def test_setup_feedback_skips_cleanly_on_empty_repo(isolated_config, monkeypatch):
    # The user just presses Enter at the first prompt: nothing is stored.
    monkeypatch.setattr(builtins, "input", _scripted_input([""]))
    assert onboarding.setup_feedback() is False
    assert config.get_feedback_repo() is None
    assert config.get_feedback_token() is None


def test_setup_feedback_skips_when_token_left_blank(isolated_config, monkeypatch):
    # A repo without a token can't file online, so we store neither and report skip.
    monkeypatch.setattr(builtins, "input", _scripted_input(["acme/fb", ""]))
    assert onboarding.setup_feedback() is False
    assert config.get_feedback_repo() is None
    assert config.get_feedback_token() is None


def test_setup_feedback_short_circuits_when_already_configured(isolated_config, monkeypatch):
    config.set_feedback_repo("acme/fb")
    config.set_feedback_token("ghp_existing")

    def must_not_prompt(_p=""):
        raise AssertionError("must not prompt when feedback is already configured")

    monkeypatch.setattr(builtins, "input", must_not_prompt)
    assert onboarding.setup_feedback() is True


# --- offer_feedback_shortcut: one-tap confirm gates the (mocked) primitive ----------


def test_shortcut_offer_creates_on_yes(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _p="": "y")
    calls = {"n": 0}

    def fake_create():
        calls["n"] += 1
        return True

    monkeypatch.setattr(winlaunch, "create_feedback_shortcut", fake_create)
    onboarding.offer_feedback_shortcut()
    assert calls["n"] == 1


def test_shortcut_offer_defaults_to_yes_on_enter(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _p="": "")
    calls = {"n": 0}
    monkeypatch.setattr(
        winlaunch, "create_feedback_shortcut", lambda: calls.__setitem__("n", calls["n"] + 1) or True
    )
    onboarding.offer_feedback_shortcut()
    assert calls["n"] == 1


def test_shortcut_offer_declines_on_no(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _p="": "n")

    def must_not_create():
        raise AssertionError("must not create the shortcut when the user declines")

    monkeypatch.setattr(winlaunch, "create_feedback_shortcut", must_not_create)
    onboarding.offer_feedback_shortcut()  # no exception → declined cleanly


# --- onboard: end-to-end flow stitches the steps together -------------------------


def test_onboard_full_optin_flow_stores_everything(isolated_config, monkeypatch, capsys):
    # Key prompt, then repo/token/name, then 'y' to the shortcut offer.
    monkeypatch.setattr(
        builtins,
        "input",
        _scripted_input(["sk-ant-onboard", "acme/fb", "ghp_tok", "Grace", "y"]),
    )
    monkeypatch.setattr(winlaunch, "create_feedback_shortcut", lambda: True)
    onboarding.onboard()
    out = capsys.readouterr().out
    assert config.get_api_key() == "sk-ant-onboard"
    assert config.get_feedback_repo() == "acme/fb"
    assert config.get_feedback_token() == "ghp_tok"
    assert config.get_reporter_name() == "Grace"
    assert "Drag a PDF" in out


def test_onboard_key_then_skip_feedback(isolated_config, monkeypatch, capsys):
    # Key set, but the user skips feedback (empty repo): no shortcut offer reached.
    monkeypatch.setattr(builtins, "input", _scripted_input(["sk-ant-onboard", ""]))

    def must_not_create():
        raise AssertionError("shortcut offer must not run when feedback was skipped")

    monkeypatch.setattr(winlaunch, "create_feedback_shortcut", must_not_create)
    onboarding.onboard()
    out = capsys.readouterr().out
    assert config.get_api_key() == "sk-ant-onboard"
    assert config.get_feedback_repo() is None
    assert "Drag a PDF" in out


def test_onboard_returns_early_when_no_key(isolated_config, monkeypatch):
    # No key entered: we don't pile feedback questions on a user who isn't ready.
    monkeypatch.setattr(builtins, "input", _scripted_input([""]))

    def must_not_run(*_a, **_k):
        raise AssertionError("feedback setup must not run without a key")

    monkeypatch.setattr(onboarding, "setup_feedback", must_not_run)
    onboarding.onboard()
    assert config.get_api_key() is None
