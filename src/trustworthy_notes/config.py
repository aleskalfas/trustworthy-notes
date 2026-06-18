"""User-level config for tn — auth credentials and defaults.

The API key is stored in ``~/.trustworthy-notes/config.yaml`` (in your home, NOT
the repo). ``TN_CONFIG_DIR`` overrides the location (used by tests). Because the
file lives outside the repo tree, git never sees it.

Location is the same on every OS (``Path.home()`` resolves to ``$HOME`` on
macOS/Linux and ``%USERPROFILE%`` — i.e. ``C:\\Users\\<you>`` — on Windows).

Privacy:
  * POSIX (macOS/Linux): we ``chmod`` the file to 0600.
  * Windows: POSIX bits are ignored; the file is instead protected by the NTFS
    ACLs it inherits from the user-profile directory, which already restricts
    reads to the user account (plus Administrators/SYSTEM).

Honest caveat (both OSes): this protects the file from *other* users, but any
process running as *you* (including an AI agent with shell access) can read it.
Same model as ``~/.aws/credentials`` or the ``ANTHROPIC_API_KEY`` env var. Use a
scoped key with a spend cap and rotate it if it's ever exposed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

# Built-in defaults used when neither a flag nor the user config supplies a value.
# Sonnet is the cost-appropriate default model; `low` keeps adaptive thinking from
# running long on this bounded task.
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_EFFORT = "low"


def config_dir() -> Path:
    override = os.environ.get("TN_CONFIG_DIR")
    return Path(override) if override else Path.home() / ".trustworthy-notes"


def config_file() -> Path:
    return config_dir() / "config.yaml"


def load() -> dict:
    f = config_file()
    if f.is_file():
        try:
            return yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            return {}
    return {}


def save(cfg: dict) -> None:
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    f = config_file()
    f.write_text(yaml.safe_dump(cfg, sort_keys=True), encoding="utf-8")
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass


def get_api_key() -> Optional[str]:
    return load().get("api_key") or None


def set_api_key(key: str) -> None:
    cfg = load()
    cfg["api_key"] = key
    save(cfg)


def clear_api_key() -> None:
    cfg = load()
    if cfg.pop("api_key", None) is not None:
        save(cfg)


def get_model() -> Optional[str]:
    """The user-configured extraction model, or None if unset."""
    return load().get("model") or None


def set_model(model: str) -> None:
    cfg = load()
    cfg["model"] = model
    save(cfg)


def get_effort() -> Optional[str]:
    """The user-configured effort, or None if unset.

    An empty string is a *meaningful* configured value (models without an effort
    knob, e.g. Haiku), so it is returned as-is rather than collapsed to None;
    only an absent key reads as unset.
    """
    cfg = load()
    return cfg.get("effort") if "effort" in cfg else None


def set_effort(effort: str) -> None:
    cfg = load()
    cfg["effort"] = effort
    save(cfg)


def auth_source() -> str:
    """Where tn will get Claude credentials: 'config' | 'env' | 'login' | 'none'."""
    if get_api_key():
        return "config"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "env"
    if (Path.home() / ".config" / "anthropic").exists():
        return "login"
    return "none"
