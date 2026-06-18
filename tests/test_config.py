"""User-config / auth-resolution tests. Uses TN_CONFIG_DIR so $HOME is untouched."""

from __future__ import annotations

import importlib
import sys

import pytest


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("TN_CONFIG_DIR", str(tmp_path / "tn"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from trustworthy_notes import config as config_module

    return importlib.reload(config_module)


def test_set_get_clear_api_key(cfg):
    assert cfg.get_api_key() is None
    cfg.set_api_key("sk-test-123")
    assert cfg.get_api_key() == "sk-test-123"
    # persisted privately (POSIX perms; Windows uses ACLs, so skip the bit check)
    if sys.platform != "win32":
        assert cfg.config_file().stat().st_mode & 0o777 == 0o600
    cfg.clear_api_key()
    assert cfg.get_api_key() is None


def test_auth_source_precedence(cfg, monkeypatch):
    assert cfg.auth_source() in ("none", "login")  # no saved key, no env key

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    assert cfg.auth_source() == "env"

    cfg.set_api_key("sk-saved")
    assert cfg.auth_source() == "config"  # saved key wins over env


def test_set_get_model_round_trip(cfg):
    assert cfg.get_model() is None  # unset
    cfg.set_model("claude-opus-4-8")
    assert cfg.get_model() == "claude-opus-4-8"


def test_set_get_effort_round_trip(cfg):
    assert cfg.get_effort() is None  # unset
    cfg.set_effort("medium")
    assert cfg.get_effort() == "medium"


def test_effort_empty_string_is_a_real_value_not_unset(cfg):
    # '' means "this model has no effort knob" — distinct from unset (None).
    cfg.set_effort("")
    assert cfg.get_effort() == ""


def test_model_and_effort_do_not_clobber_api_key(cfg):
    cfg.set_api_key("sk-keep")
    cfg.set_model("claude-opus-4-8")
    cfg.set_effort("high")
    assert cfg.get_api_key() == "sk-keep"
    assert cfg.get_model() == "claude-opus-4-8"
    assert cfg.get_effort() == "high"


def test_resolution_built_in_when_nothing_set(cfg):
    # Mirrors the flag > config > built-in resolution in `tn extract`, with no
    # flag and nothing configured: the built-in Sonnet/low defaults apply.
    model = None or cfg.get_model() or cfg.DEFAULT_MODEL
    cfg_effort = cfg.get_effort()
    effort = cfg_effort if cfg_effort is not None else cfg.DEFAULT_EFFORT
    assert model == "claude-sonnet-4-6"
    assert effort == "low"


def test_resolution_config_wins_over_built_in(cfg):
    cfg.set_model("claude-opus-4-8")
    cfg.set_effort("")
    model = None or cfg.get_model() or cfg.DEFAULT_MODEL
    cfg_effort = cfg.get_effort()
    effort = cfg_effort if cfg_effort is not None else cfg.DEFAULT_EFFORT
    assert model == "claude-opus-4-8"
    assert effort == ""  # configured empty wins, not collapsed to the built-in
