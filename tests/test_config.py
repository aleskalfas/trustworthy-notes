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


def test_set_get_language_round_trip(cfg):
    assert cfg.get_language() is None  # unset
    cfg.set_language("cs")
    assert cfg.get_language() == "cs"


def test_set_get_eval_corpus_dir_round_trip(cfg):
    assert cfg.get_eval_corpus_dir() is None  # unset
    cfg.set_eval_corpus_dir("/path/to/private/eval-corpus")
    assert cfg.get_eval_corpus_dir() == "/path/to/private/eval-corpus"


def test_effort_empty_string_is_a_real_value_not_unset(cfg):
    # '' means "this model has no effort knob" — distinct from unset (None).
    cfg.set_effort("")
    assert cfg.get_effort() == ""


def test_model_and_effort_do_not_clobber_api_key(cfg):
    cfg.set_api_key("sk-keep")
    cfg.set_model("claude-opus-4-8")
    cfg.set_effort("high")
    cfg.set_language("cs")
    assert cfg.get_api_key() == "sk-keep"
    assert cfg.get_model() == "claude-opus-4-8"
    assert cfg.get_effort() == "high"
    assert cfg.get_language() == "cs"


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
    # The repo is no longer None when unset — it falls back to the built-in default
    # (#52/#53), so feedback works with only a token. The token is never defaulted.
    assert cfg.get_feedback_repo() == cfg.DEFAULT_FEEDBACK_REPO
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


def test_feedback_repo_defaults_when_unset_token_does_not(cfg):
    # #53: the repo always resolves to a clean owner/name — the built-in default
    # when nothing is stored — so feedback needs only a token. The token, by
    # contrast, is never defaulted: it stays None until explicitly set.
    assert cfg.get_feedback_repo() == cfg.DEFAULT_FEEDBACK_REPO
    assert cfg.get_feedback_token() is None


def test_feedback_repo_explicit_value_overrides_default(cfg):
    # #53: an explicitly stored repo wins over the built-in default.
    cfg.set_feedback_repo("acme/override")
    assert cfg.get_feedback_repo() == "acme/override"


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


def test_resolve_language_built_in_when_nothing_set(cfg):
    # No flag, nothing configured: the built-in "en" default applies (ADR-008).
    assert cfg.resolve_language(None) == "en"


def test_resolve_language_config_wins_over_built_in(cfg):
    cfg.set_language("cs")
    assert cfg.resolve_language(None) == "cs"


def test_resolve_language_flag_wins_over_config(cfg):
    cfg.set_language("cs")
    # An explicit flag beats both config and the built-in default.
    assert cfg.resolve_language("ja") == "ja"


def test_resolve_language_does_not_read_os_locale(cfg, monkeypatch):
    # ADR-008 keeps platform I/O off the hot resolve path: resolution must reach
    # the built-in default without ever calling detect_os_language.
    def _boom():
        raise AssertionError("resolve_language must not read the OS locale")

    monkeypatch.setattr(cfg, "detect_os_language", _boom)
    assert cfg.resolve_language(None) == "en"


@pytest.mark.parametrize(
    "stubbed,expected",
    [
        ("cs_CZ.UTF-8", "cs"),
        ("en-US", "en"),
        ("en_US", "en"),
        ("ja_JP", "ja"),
        ("pt_BR.UTF-8", "pt"),
    ],
)
def test_detect_os_language_returns_language_part(cfg, monkeypatch, stubbed, expected):
    # The bare language subtag is recovered from the stubbed locale, with any
    # territory and encoding stripped and both _/- separators accepted.
    monkeypatch.setattr(cfg.locale, "getlocale", lambda *a: (stubbed, "UTF-8"))
    assert cfg.detect_os_language() == expected


@pytest.mark.parametrize("stubbed", [None, "", "C", "POSIX"])
def test_detect_os_language_none_when_locale_unset(cfg, monkeypatch, stubbed):
    # An unset / sentinel locale and no usable env locale read as None, never as a
    # spurious language code.
    monkeypatch.setattr(cfg.locale, "getlocale", lambda *a: (stubbed, None))
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    assert cfg.detect_os_language() is None


def test_detect_os_language_none_when_locale_raises(cfg, monkeypatch):
    # Fully fail-safe: any error from the platform read collapses to None so the
    # caller can fall back to DEFAULT_LANGUAGE (ADR-008).
    def _raise(*a):
        raise ValueError("unknown locale")

    monkeypatch.setattr(cfg.locale, "getlocale", _raise)
    assert cfg.detect_os_language() is None


def test_detect_os_language_falls_back_to_env_locale(cfg, monkeypatch):
    # When getlocale yields nothing, the LC_ALL/LC_MESSAGES/LANG env locale is
    # consulted (the precedence getdefaultlocale used before it was deprecated).
    monkeypatch.setattr(cfg.locale, "getlocale", lambda *a: (None, None))
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.setenv("LANG", "cs_CZ.UTF-8")
    assert cfg.detect_os_language() == "cs"
