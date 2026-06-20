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


def test_resolve_built_in_when_nothing_set(cfg):
    # No flag, nothing configured: the built-in Sonnet/low defaults apply.
    assert cfg.resolve_model(None) == "claude-sonnet-4-6"
    assert cfg.resolve_effort(None) == "low"


def test_resolve_config_wins_over_built_in(cfg):
    cfg.set_model("claude-opus-4-8")
    cfg.set_effort("high")
    assert cfg.resolve_model(None) == "claude-opus-4-8"
    assert cfg.resolve_effort(None) == "high"


def test_resolve_flag_wins_over_config(cfg):
    cfg.set_model("claude-opus-4-8")
    cfg.set_effort("high")
    # An explicit flag beats both config and built-in.
    assert cfg.resolve_model("claude-haiku-4-5") == "claude-haiku-4-5"
    assert cfg.resolve_effort("medium") == "medium"


def test_resolve_effort_preserves_configured_empty_string(cfg):
    # A configured '' (model without an effort knob) is load-bearing: it must
    # survive resolution as '', not collapse to the built-in default.
    cfg.set_effort("")
    assert cfg.resolve_effort(None) == ""


def test_resolve_effort_empty_flag_is_explicit_not_unset(cfg):
    # Passing '' on the flag is an explicit choice and wins over config.
    cfg.set_effort("high")
    assert cfg.resolve_effort("") == ""


def test_feedback_config_round_trips_and_is_isolated(cfg):
    assert cfg.get_feedback_repo() is None
    assert cfg.get_feedback_token() is None
    assert cfg.get_reporter_name() is None
    cfg.set_api_key("sk-keep")
    cfg.set_feedback_repo("acme/tn-feedback")
    cfg.set_feedback_token("ghp_xxx")
    cfg.set_reporter_name("Jana")
    assert cfg.get_feedback_repo() == "acme/tn-feedback"
    assert cfg.get_feedback_token() == "ghp_xxx"
    assert cfg.get_reporter_name() == "Jana"
    # Feedback keys must not clobber the API key (shared config file).
    assert cfg.get_api_key() == "sk-keep"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("acme/tn-feedback", "acme/tn-feedback"),
        ("https://github.com/acme/tn-feedback", "acme/tn-feedback"),
        ("https://github.com/acme/tn-feedback/", "acme/tn-feedback"),
        ("https://www.github.com/acme/tn-feedback.git", "acme/tn-feedback"),
        ("git@github.com:acme/tn-feedback.git", "acme/tn-feedback"),
    ],
)
def test_set_feedback_repo_normalises_url_to_owner_name(cfg, raw, expected):
    # #50: a URL must never be persisted verbatim (it would 404 on every call);
    # the storage boundary canonicalises to owner/name regardless of entry point.
    cfg.set_feedback_repo(raw)
    assert cfg.get_feedback_repo() == expected
