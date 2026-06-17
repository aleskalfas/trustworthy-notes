"""Team membership predicate library (per DEC-021).

Resolves the invoker's identity from `gh` / `git` / env, reads the
adopter's `members.yaml`, and returns whether the invoker is allowed
to mutate methodology state.

Two modes:
  * Open mode  — `members.yaml` is absent OR `members:` is empty list.
                 Any invoker passes.
  * Closed mode — `members.yaml` has ≥1 member entry. Only listed
                  members pass. Identity matches by `github_login` or
                  `email`; either surface is sufficient.

The library is dependency-free at import time so it can be imported
from any PEP 723 script regardless of what `dependencies:` block the
script declares. YAML parsing is the caller's responsibility — scripts
read `members.yaml` themselves and pass the parsed `members` list to
`check_membership()`.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


CAPABILITY_NAME = "project-management"
MEMBERS_RELATIVE = "project/members.yaml"


@dataclass(frozen=True)
class Identity:
    """Resolved identity for the user invoking a pm script."""

    github_login: str | None
    email: str | None

    def label(self) -> str:
        """A single human-readable label for refusal / log lines."""
        return self.github_login or self.email or "<unresolved>"


@dataclass(frozen=True)
class MembershipResult:
    """Outcome of a membership predicate check."""

    allowed: bool
    mode: str  # "open" | "closed"
    invoker: Identity
    refusal_message: str | None = None


def resolve_invoker_identity(
    config: dict | None = None,
    gh_login_provider=None,
    email_provider=None,
) -> Identity:
    """Resolve the invoker's identity from gh / git / env.

    Order of preference for `github_login`:
      1. `PM_INVOKER_LOGIN` env var (for CI / agent contexts).
      2. `gh api user --jq .login` — routed through the gh helper per
         [project-management:DEC-023-gh-host-and-owner], so the call
         lands on the host declared in `config['gh']['host']` when set.
    The email comes from `git config user.email` when available.

    `config` is the adopter's parsed `project/config.yaml`. When omitted,
    the gh call uses ambient state (equivalent to single-org github.com).
    `gh_login_provider` and `email_provider` are testing seams —
    callables returning a string-or-None. Production uses subprocess.
    """
    if gh_login_provider is None:
        gh_login_provider = lambda: _gh_login_via_subprocess(config or {})
    if email_provider is None:
        email_provider = _email_via_subprocess

    env_login = os.environ.get("PM_INVOKER_LOGIN")
    login = env_login.strip() if env_login else gh_login_provider()
    email = email_provider()
    return Identity(github_login=login or None, email=email or None)


def check_membership(
    members: list[dict],
    invoker: Identity,
) -> MembershipResult:
    """Apply the membership predicate to a parsed members list.

    `members` is the `members:` field of the parsed `members.yaml`.
    An empty list (or absent / unparseable file represented as `[]`
    by the caller) means open mode.

    Returns a `MembershipResult`. When `allowed=False`, the
    `refusal_message` field carries the standard structured refusal.
    """
    if not members:
        return MembershipResult(allowed=True, mode="open", invoker=invoker)

    for entry in members:
        if not isinstance(entry, dict):
            continue
        if (
            invoker.github_login
            and entry.get("github_login") == invoker.github_login
        ):
            return MembershipResult(allowed=True, mode="closed", invoker=invoker)
        if invoker.email and entry.get("email") == invoker.email:
            return MembershipResult(allowed=True, mode="closed", invoker=invoker)

    return MembershipResult(
        allowed=False,
        mode="closed",
        invoker=invoker,
        refusal_message=format_refusal(invoker),
    )


def format_refusal(invoker: Identity) -> str:
    """Standard refusal message per DEC-021's structured refusal."""
    return (
        "[refused] Membership required for this operation\n"
        f"          → This repository is in closed mode "
        f"(.pkit/capabilities/{CAPABILITY_NAME}/{MEMBERS_RELATIVE} "
        "has ≥1 entry).\n"
        f"          → Your identity ({invoker.label()}) is not in the "
        "member list.\n"
        "          → Remediation: ask an existing member to add you via "
        f"`pkit {CAPABILITY_NAME} add-member`."
    )


def members_path(capability_root: Path) -> Path:
    """The canonical path to `members.yaml` for this capability."""
    return capability_root / MEMBERS_RELATIVE


def resolve_capability_root(explicit: Path | None) -> Path | None:
    """Walk up from CWD until `.pkit/capabilities/<CAPABILITY_NAME>/` is found.

    Returns None when the capability is not installed at the expected
    path. Used by every pm script for adopter-root discovery.
    """
    if explicit is not None:
        return explicit if explicit.is_dir() else None
    cur = Path.cwd()
    while cur != cur.parent:
        candidate = cur / ".pkit" / "capabilities" / CAPABILITY_NAME
        if candidate.is_dir():
            return candidate
        cur = cur.parent
    return None


# ---- subprocess helpers (testing seams) ----------------------------


def _gh_login_via_subprocess(config: dict | None = None) -> str | None:
    """Resolve `gh api user --jq .login` through the gh helper.

    Routes the call through `_lib.gh.gh_run` so the adopter's pinned host
    (per DEC-023) determines which GitHub instance answers. Without
    config (or with no `gh.host` set), the call uses ambient `gh` state.

    Uses `from _lib.gh import gh_run` matching the convention used by
    parent scripts (e.g. move-issue.py, start-work.py). This requires
    that the caller has `scripts/` on sys.path, which every pm script
    ensures via `sys.path.insert(0, str(_HERE))` before importing.
    """
    from _lib.gh import gh_run  # noqa: PLC0415 — deferred to avoid circular import at module load

    try:
        proc = gh_run(
            ["gh", "api", "user", "--jq", ".login"],
            config or {},
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _email_via_subprocess() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None
