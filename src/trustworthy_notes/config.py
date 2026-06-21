"""User-level config for tnotes — auth credentials and defaults.

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
import re
from pathlib import Path
from typing import Optional

import yaml

# A GitHub repo reference we are willing to reduce to ``owner/name`` so a pasted
# browser/clone URL is never stored verbatim (a stored URL produces a malformed
# API path and a 404 on every call). Matches the host with the common prefixes
# (https/http, optional ``www.``, the ``git@`` SCP form); a trailing ``.git``
# and/or ``/`` are trimmed separately so the one expression stays readable.
_GITHUB_URL_RE = re.compile(
    r"^(?:https?://(?:www\.)?github\.com/|git@github\.com:)(?P<path>.+)$",
    re.IGNORECASE,
)


def normalise_feedback_repo(raw: str) -> str:
    """Reduce a pasted repo reference to the ``owner/name`` form the API expects.

    A bare ``owner/name`` passes through unchanged. A full GitHub URL — the browser
    address ``https://github.com/owner/name``, the ``git@github.com:owner/name``
    clone form, with or without a trailing ``.git`` or ``/`` — is stripped back to
    ``owner/name``. Forgiving by design: anything it doesn't recognise as a URL is
    returned trimmed and otherwise untouched, so a typo still reaches the connection
    check (which decides whether the value works) rather than being silently rewritten.

    Canonicalising here, at the storage boundary, means no entry point — the
    ``config set-feedback-repo`` command, a maintainer pre-seed, or the onboarding
    default — can persist a URL that later 404s.
    """
    value = raw.strip()
    match = _GITHUB_URL_RE.match(value)
    if match:
        value = match.group("path")
    value = value.rstrip("/")
    if value.endswith(".git"):
        value = value[: -len(".git")]
    return value.strip("/")

# Built-in defaults used when neither a flag nor the user config supplies a value.
# Sonnet is the cost-appropriate default model; `low` keeps adaptive thinking from
# running long on this bounded task.
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_EFFORT = "low"

# Built-in default feedback repo (#52). The repo name is NOT a secret — only the
# token is (ADR-003's bright line), and the token is never defaulted or baked in.
# Defaulting the repo here means feedback works with only a token, no repo setup
# by the maintainer or the user. An explicit config value still overrides it.
DEFAULT_FEEDBACK_REPO = "aleskalfas/trustworthy-notes-feedback"


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


def resolve_model(flag: Optional[str]) -> str:
    """Resolve the model to use: an explicit flag wins, then user config, then the
    built-in default. The single source of model resolution for every command."""
    return flag or get_model() or DEFAULT_MODEL


def resolve_effort(flag: Optional[str]) -> str:
    """Resolve the effort to use: an explicit flag wins, then user config, then the
    built-in default. The single source of effort resolution for every command.

    A configured empty string (``effort: ''`` — models without an effort knob) is a
    meaningful value and is preserved; only ``None`` (flag not passed, key absent)
    reads as unset. ``flag is None`` distinguishes "not passed" from "passed as ''".
    """
    if flag is not None:
        return flag
    cfg_effort = get_effort()
    return cfg_effort if cfg_effort is not None else DEFAULT_EFFORT


def get_feedback_repo() -> str:
    """The private feedback repo as ``owner/name`` — a configured value or the default.

    Where ``tnotes feedback`` files issues + commits repro bundles. Falls back to the
    built-in :data:`DEFAULT_FEEDBACK_REPO` when nothing is configured (#52), so the
    repo needs no setup — only the token does. An explicit config value overrides it.
    The repo name is not a secret; the token is the thing kept out of the binary
    (ADR-003). Normalised on read so any value — the default, a freshly-set one, or
    a pre-#50 config dirtied with a URL — comes back as clean ``owner/name``.
    """
    return normalise_feedback_repo(load().get("feedback_repo") or DEFAULT_FEEDBACK_REPO)


def set_feedback_repo(repo: str) -> None:
    """Store the feedback repo, normalised to ``owner/name``.

    Normalising at this boundary means a pasted URL (from the config command, a
    maintainer pre-seed, or the onboarding default) can never be persisted verbatim
    and later 404 — see :func:`normalise_feedback_repo`.
    """
    cfg = load()
    cfg["feedback_repo"] = normalise_feedback_repo(repo)
    save(cfg)


def get_feedback_token() -> Optional[str]:
    """The fine-grained GitHub PAT for the feedback repo, or None if unset.

    Scoped to one private repo (Issues + Contents). Delivered out-of-band (1Password)
    and stored here in the user config — *never* baked into the binary. Absent or
    expired (401 at use), feedback falls back to a local file.
    """
    return load().get("feedback_token") or None


def set_feedback_token(token: str) -> None:
    cfg = load()
    cfg["feedback_token"] = token
    save(cfg)


def get_reporter_name() -> Optional[str]:
    """The reporter's name, asked once on first feedback and remembered.

    Tagged into every report ("Reported by: <name>") because the PAT authors as the
    maintainer's account, so the body carries the attribution the author can't.
    """
    return load().get("reporter_name") or None


def set_reporter_name(name: str) -> None:
    cfg = load()
    cfg["reporter_name"] = name
    save(cfg)


def get_no_update_check() -> bool:
    """True when the launch-time update nudge is opted out in the user config.

    The env var ``TNOTES_NO_UPDATE_CHECK`` is the other opt-out; that one is read in
    ``updater`` so it works even without a config file. This is the persisted form.
    """
    return bool(load().get("no_update_check"))


def set_no_update_check(disabled: bool) -> None:
    """Persist the update-nudge opt-out (``no_update_check`` in the user config)."""
    cfg = load()
    cfg["no_update_check"] = bool(disabled)
    save(cfg)


def auth_source() -> str:
    """Where tnotes will get Claude credentials: 'config' | 'env' | 'login' | 'none'."""
    if get_api_key():
        return "config"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "env"
    if (Path.home() / ".config" / "anthropic").exists():
        return "login"
    return "none"
