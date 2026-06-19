"""Self-update for the packaged Windows ``tnotes.exe`` — fail-safe in-place swap.

``tnotes upgrade`` (wired in ``cli.py``) pulls the latest published build over the
network and replaces the running executable with it, in a way that can never leave
the user without a working exe. This module owns that logic end to end: the
latest-release query, the checksum verification, the launchable-before-swap check,
and the rename/move/cleanup swap itself.

**Layering.** The pipeline never imports this module — the only caller is ``cli``
(architect constraint: ``cli`` → updater, never pipeline → updater). The updater
in turn depends only on the standard library plus ``build`` (for the running
version); it pulls in no pipeline code, so a self-update path can never drag the
extraction/compose machinery along with it.

**Trust model.** The trust root is GitHub over TLS: we fetch the release metadata
and the assets from ``api.github.com`` / ``github.com`` over HTTPS, and trust the
certificate chain the platform validates. The published SHA-256 (uploaded beside
the exe as ``tnotes.exe.sha256``) is *not* a second trust anchor — an attacker who
could forge the download could forge the checksum too — it guards against the
realistic failure that TLS does not: a **truncated or corrupted download**. So the
order is: trust the transport, then verify integrity, then verify the bytes are a
launchable tnotes, and only then swap.

**The Windows running-exe constraint.** Windows will not let a running process's
own ``.exe`` be overwritten or deleted, but it *will* let it be renamed. So the
swap renames the live ``tnotes.exe`` to ``tnotes.exe.old`` (allowed while running),
moves the verified new exe into the freed name, and leaves ``.old`` for the next
launch to delete (by then the old process has exited and the file is unlocked).
``cli`` calls :func:`cleanup_stale` on startup to sweep it.

**Validation note.** This is authored and unit-tested on macOS, where the actual
running-exe swap cannot be exercised (the OS file-locking semantics that make the
rename dance necessary are Windows-only). The network/checksum/swap-planning logic
is covered by tests that mock the API and download and exercise the rename/move/
cleanup with temp files; the first *real* validation is running ``tnotes upgrade``
on Windows against a published release.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__, build, config

# Releases live here; assets are named exactly as the workflow uploads them.
_REPO = "aleskalfas/trustworthy-notes"
_LATEST_RELEASE_URL = f"https://api.github.com/repos/{_REPO}/releases/latest"
_EXE_ASSET = "tnotes.exe"
_CHECKSUM_ASSET = "tnotes.exe.sha256"

# The suffix the running exe is renamed to during the swap, swept on next launch.
_OLD_SUFFIX = ".old"

_DOWNLOAD_TIMEOUT_S = 60

# The launch-time update *check* (issue #8) is a different budget from the upgrade
# download: it runs on the hot path of every frozen invocation, so its network call
# must be short enough that a slow or unreachable GitHub never makes the tool feel
# sluggish. A failed/timed-out check is swallowed silently — the requested command
# proceeds regardless — so a tight bound costs us only a missed nudge, never a hang.
_CHECK_TIMEOUT_S = 3

# The check is cached so at most one network call happens per day; within the window
# the cached "latest seen" answer is reused with no request.
_CHECK_INTERVAL_S = 24 * 60 * 60

# Where the check state (last-check timestamp + last-seen latest version) is persisted,
# and the env var that disables the check entirely (the config opt-out lives in config).
_CHECK_CACHE_FILE = "update-check.json"
_NO_CHECK_ENV = "TNOTES_NO_UPDATE_CHECK"


class UpgradeError(Exception):
    """A user-facing upgrade failure. The message is safe to print as-is.

    Raising this (rather than letting an arbitrary exception escape) is the
    updater's promise that, whatever went wrong, it stopped *before* touching the
    installed exe — the current working build is always still in place.
    """


@dataclass(frozen=True)
class Release:
    """The latest release's metadata, reduced to what an upgrade needs."""

    tag: str
    version: str  # tag with any leading 'v' stripped, e.g. "0.1.0"
    exe_url: str
    checksum_url: str


def running_version() -> str:
    """The version of the build that is currently running.

    ``build_identity()`` (version + stamp) keys the cache and is the right thing to
    *log*; the upgrade comparison is on the released version alone, since that is
    what release tags carry.
    """
    return __version__


def is_frozen() -> bool:
    """True when running as the packaged one-file exe, false from a source checkout.

    PyInstaller sets ``sys.frozen``; a normal ``python -m`` / console-script run
    does not. Only a frozen build has an exe to swap.
    """
    return bool(getattr(sys, "frozen", False))


def running_exe_path() -> Path:
    """The path to the running executable (the file the swap replaces).

    Only meaningful when :func:`is_frozen` is true; under a freeze ``sys.executable``
    is the exe itself rather than a Python interpreter.
    """
    return Path(sys.executable)


def _version_tuple(version: str) -> tuple[int, ...]:
    """Parse a dotted numeric version into a comparable tuple.

    Tolerant by design: a non-numeric component stops the parse (treated as the
    end of the comparable prefix) rather than raising, so an unexpected tag like
    ``"0.2.0-rc1"`` still compares on its ``0.2.0`` prefix instead of crashing an
    upgrade check.
    """
    parts: list[int] = []
    for chunk in version.split("."):
        if chunk.isdigit():
            parts.append(int(chunk))
        else:
            break
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    """True when ``candidate`` is a strictly newer version than ``current``."""
    return _version_tuple(candidate) > _version_tuple(current)


def _http_get(url: str, *, accept: str | None = None, timeout: int = _DOWNLOAD_TIMEOUT_S) -> bytes:
    """GET ``url`` over HTTPS and return the body bytes, or raise :class:`UpgradeError`.

    Wraps the stdlib so every network failure surfaces as one user-facing error
    type. A ``User-Agent`` is sent because the GitHub API rejects requests without
    one. ``timeout`` defaults to the download budget; the launch-time check passes a
    much shorter one so a slow GitHub never stalls the hot path.
    """
    headers = {"User-Agent": f"tnotes/{__version__}"}
    if accept:
        headers["Accept"] = accept
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as exc:  # urllib raises a zoo of types; collapse to one
        raise UpgradeError(f"could not reach {url}: {exc}") from exc


def fetch_latest_release(*, get=_http_get) -> Release:
    """Query GitHub for the latest release and return its :class:`Release`.

    ``get`` is injected so tests can supply the API JSON without a network call.
    Raises :class:`UpgradeError` if the response is unparseable or is missing the
    ``tnotes.exe`` / ``tnotes.exe.sha256`` assets the upgrade depends on.
    """
    raw = get(_LATEST_RELEASE_URL, accept="application/vnd.github+json")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise UpgradeError(f"unexpected release response from GitHub: {exc}") from exc

    tag = data.get("tag_name")
    if not tag:
        raise UpgradeError("latest release has no tag — nothing to upgrade to")

    assets = {a.get("name"): a.get("browser_download_url") for a in data.get("assets", [])}
    exe_url = assets.get(_EXE_ASSET)
    checksum_url = assets.get(_CHECKSUM_ASSET)
    if not exe_url:
        raise UpgradeError(f"release {tag} has no {_EXE_ASSET} asset to download")
    if not checksum_url:
        raise UpgradeError(
            f"release {tag} has no {_CHECKSUM_ASSET} asset — refusing to install an "
            "exe whose checksum cannot be verified"
        )
    return Release(
        tag=tag,
        version=tag.lstrip("v"),
        exe_url=exe_url,
        checksum_url=checksum_url,
    )


def _parse_published_checksum(text: str) -> str:
    """Extract the SHA-256 hex digest from a ``*.sha256`` file's contents.

    Accepts both the bare-digest form and the ``sha256sum`` form
    ``"<digest>  <filename>"``; takes the first whitespace-delimited token and
    validates it is a 64-char hex digest.
    """
    token = text.strip().split()[0] if text.strip() else ""
    token = token.lower()
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise UpgradeError(f"published checksum is not a SHA-256 hex digest: {text!r}")
    return token


def verify_checksum(data: bytes, published: str) -> None:
    """Raise :class:`UpgradeError` unless ``data`` hashes to the published digest.

    ``published`` is the raw contents of the ``.sha256`` asset (either form).
    """
    expected = _parse_published_checksum(published)
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise UpgradeError(
            "downloaded exe failed SHA-256 verification "
            f"(expected {expected}, got {actual}) — download corrupted, not installing"
        )


def verify_launchable(exe: Path) -> None:
    """Raise :class:`UpgradeError` unless ``exe`` runs and reports a version.

    Runs ``<exe> --version`` and requires a clean exit. This is the gate that keeps
    a corrupt-but-correctly-checksummed or incompatible download from ever being
    swapped in: a download that hashes correctly but cannot launch (wrong arch, a
    truncation the hash somehow missed, an OS that refuses it) is rejected here,
    before the live exe is touched.
    """
    try:
        result = subprocess.run(
            [str(exe), "--version"],
            capture_output=True,
            timeout=_DOWNLOAD_TIMEOUT_S,
        )
    except Exception as exc:
        raise UpgradeError(
            f"downloaded exe is not launchable ({exc}) — not installing"
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or b"").decode("utf-8", "replace").strip()
        raise UpgradeError(
            f"downloaded exe exited {result.returncode} on --version "
            f"({detail or 'no output'}) — not installing"
        )


def swap_in_place(new_exe: Path, target: Path) -> Path:
    """Atomically-as-possible replace ``target`` with ``new_exe``; return the ``.old`` path.

    The Windows-safe sequence, and why each step is ordered as it is:

    1. Rename the running ``target`` → ``target.old``. Windows forbids overwriting
       or deleting a running exe but permits renaming it, so this frees the name
       without disturbing the running process.
    2. Move the verified ``new_exe`` into the now-free ``target``.
    3. If that move fails, roll the ``.old`` back to ``target`` so the user is left
       with exactly the working exe they started with, then re-raise.

    The ``.old`` file is intentionally left behind: the old exe is still running and
    still locked, so it cannot be deleted now — :func:`cleanup_stale` sweeps it on
    the next launch, once the process has exited.
    """
    old = target.with_name(target.name + _OLD_SUFFIX)
    # A leftover .old from an earlier upgrade would block the rename; clear it first.
    # Safe because by now any process that held it has long exited.
    if old.exists():
        try:
            old.unlink()
        except OSError:
            pass  # cleanup_stale will retry on a later launch

    os.replace(target, old)  # step 1: free the live name (rename is allowed)
    try:
        os.replace(new_exe, target)  # step 2: move the verified exe into place
    except OSError as exc:
        # Step 3: restore the working exe, never leaving the user without one.
        try:
            os.replace(old, target)
        except OSError:
            pass
        raise UpgradeError(
            f"could not move the new exe into place ({exc}); restored the existing build"
        ) from exc
    return old


def cleanup_stale(target: Path | None = None) -> None:
    """Delete a leftover ``tnotes.exe.old`` from a previous in-place upgrade, if any.

    Called on startup (from ``cli``). After a swap, the prior exe is renamed to
    ``.old`` but cannot be deleted while it is still the running process; by the
    next launch that process has exited and the file is unlocked, so this removes
    it. Best-effort and silent: a still-locked or absent ``.old`` is not an error.
    """
    target = target or running_exe_path()
    old = target.with_name(target.name + _OLD_SUFFIX)
    try:
        if old.exists():
            old.unlink()
    except OSError:
        pass  # still locked or vanished — try again next launch


@dataclass(frozen=True)
class UpgradeOutcome:
    """What :func:`upgrade` did, for the CLI to report."""

    status: str  # "upgraded" | "up-to-date" | "not-frozen"
    message: str


def upgrade(*, get=_http_get, log=lambda _msg: None) -> UpgradeOutcome:
    """Run the full upgrade: query, compare, download, verify, swap.

    ``get`` injects the HTTP layer for tests; ``log`` receives progress lines. The
    contract is fail-safe: any failure raises :class:`UpgradeError` *before* the
    live exe is touched (everything up to and including :func:`verify_launchable`
    runs against a temp file), so a failed or interrupted upgrade always leaves the
    current working exe in place.

    Returns an :class:`UpgradeOutcome`; the only side effect on success is the swap.
    """
    if not is_frozen():
        return UpgradeOutcome(
            status="not-frozen",
            message=(
                "tnotes upgrade updates the packaged tnotes.exe only, and you are "
                "running from source. Update with `git pull` instead."
            ),
        )

    current = running_version()
    log(f"current build: {build.build_identity()}")
    release = fetch_latest_release(get=get)
    log(f"latest release: {release.tag}")

    if not is_newer(release.version, current):
        return UpgradeOutcome(
            status="up-to-date",
            message=f"already up to date (running {current}, latest {release.version}).",
        )

    log(f"downloading {release.version} …")
    exe_bytes = get(release.exe_url)
    checksum_text = get(release.checksum_url).decode("utf-8", "replace")

    log("verifying checksum …")
    verify_checksum(exe_bytes, checksum_text)

    target = running_exe_path()
    # Stage the download beside the target so the final move is same-filesystem
    # (os.replace is only atomic within one filesystem; a cross-device temp would
    # turn the swap into a copy and reopen the partial-write window we are avoiding).
    staging_dir = Path(tempfile.mkdtemp(prefix="tnotes-upgrade-", dir=str(target.parent)))
    new_exe = staging_dir / _EXE_ASSET
    new_exe.write_bytes(exe_bytes)

    try:
        log("verifying the download is launchable …")
        verify_launchable(new_exe)
        log("swapping the new exe into place …")
        swap_in_place(new_exe, target)
    finally:
        # Remove the staging dir whether we swapped (new_exe moved out, dir empty)
        # or bailed (new_exe still there). Never touches the installed exe.
        try:
            if new_exe.exists():
                new_exe.unlink()
            staging_dir.rmdir()
        except OSError:
            pass

    return UpgradeOutcome(
        status="upgraded",
        message=f"upgraded {current} → {release.version}. Restart tnotes to use it.",
    )


# --- launch-time update nudge (issue #8) ---
#
# On startup the frozen exe checks — at most once per day, with a short timeout and
# all errors swallowed — whether a newer release exists, and if so the CLI offers a
# one-keypress upgrade. The design contract: this must NEVER block normal use or
# break a non-interactive run (the CI release smoke runs `tnotes.exe --help` with
# stdout captured). So the network check here only ever *reports* what it found; the
# CLI decides whether to prompt, and prompts only when there is an interactive TTY.


def _check_cache_path() -> Path:
    """Where the daily-check state lives — alongside the user config (``~/.trustworthy-notes/``)."""
    return config.config_dir() / _CHECK_CACHE_FILE


def _read_check_cache() -> dict:
    """The last check's persisted state, or ``{}`` if absent/unreadable.

    Best-effort by design: a missing, corrupt, or unreadable cache simply reads as
    "no record", which forces a fresh check — never an error on the hot path.
    """
    path = _check_cache_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_check_cache(checked_at: float, latest_version: str) -> None:
    """Persist the check timestamp and last-seen latest version. Best-effort, silent.

    A write failure (read-only home, permissions) just means the next launch checks
    again rather than honouring the cache window — harmless, never raised.
    """
    try:
        d = config.config_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / _CHECK_CACHE_FILE).write_text(
            json.dumps({"checked_at": checked_at, "latest_version": latest_version}),
            encoding="utf-8",
        )
    except OSError:
        pass


def update_check_disabled() -> bool:
    """True when the launch-time check is opted out, via env var or config.

    ``TNOTES_NO_UPDATE_CHECK=1`` (any non-empty value) or ``no_update_check: true``
    in the user config disables the check. Reading config is best-effort — if it
    fails we simply do not treat it as a disable.
    """
    if os.environ.get(_NO_CHECK_ENV):
        return True
    try:
        return config.get_no_update_check()
    except Exception:
        return False


def check_for_update(*, get=_http_get, now=time.time) -> str | None:
    """Return the newer version available, or ``None``. Never raises, never blocks long.

    The full contract this satisfies for the launch-time nudge:

    * **Frozen-only.** A source run has no exe to swap, so the check is skipped.
    * **Opt-out.** Honours :func:`update_check_disabled` (env var / config).
    * **Cached — at most one network call per day.** If the persisted check is within
      ``_CHECK_INTERVAL_S``, the last-seen latest version is reused with *no* request;
      a still-newer cached version returns the nudge string, an up-to-date one returns
      ``None``.
    * **Short timeout, silent failure.** The live query uses ``_CHECK_TIMEOUT_S`` and
      every error (network, parse, anything) is swallowed and returns ``None`` — a
      failed check can never affect the command the user actually ran.

    ``get`` and ``now`` are injected so tests exercise every branch without a network
    call or real clock. Returns the newer version string (e.g. ``"0.2.0"``) to nudge
    toward, or ``None`` to stay silent.
    """
    if not is_frozen() or update_check_disabled():
        return None

    try:
        current = running_version()
        cache = _read_check_cache()
        last_checked = cache.get("checked_at")
        if isinstance(last_checked, (int, float)) and (now() - last_checked) < _CHECK_INTERVAL_S:
            cached_latest = cache.get("latest_version")
            if cached_latest and is_newer(cached_latest, current):
                return cached_latest
            return None

        # Window elapsed (or no record): one short, fail-safe network query.
        def short_get(url, **kwargs):
            return get(url, timeout=_CHECK_TIMEOUT_S, **kwargs)

        release = fetch_latest_release(get=short_get)
        _write_check_cache(now(), release.version)
        if is_newer(release.version, current):
            return release.version
        return None
    except Exception:
        # Anything at all — network, parse, disk, clock — must not surface here.
        return None
