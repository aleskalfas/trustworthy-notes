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
