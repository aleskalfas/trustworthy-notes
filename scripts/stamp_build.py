#!/usr/bin/env python3
"""Bake a build stamp so frozen builds have a distinct cache identity.

Why: a frozen one-file build has no ``.py`` on disk, so the output cache
(``report.py``) can't hash module source for invalidation. It falls back to a
*build identity* — ``__version__`` plus a build stamp (see ``build.py``). Without
a stamp every frozen build ships ``0.1.0+dev`` and two builds with different code
collide on the cache key, so the second reads the first's stale output.

This script writes ``src/trustworthy_notes/_build_stamp.py`` holding
``STAMP = "<value>"``. ``build.py`` imports it (falling back to ``"dev"`` when the
file is absent, e.g. a clean checkout). The PyInstaller spec bundles the module
into the freeze. Run it once, right before the freeze:

    python scripts/stamp_build.py && uv run --with pyinstaller pyinstaller tn.spec

The stamp prefers the current git commit (short SHA, ``-dirty`` if the tree has
uncommitted changes); when git is unavailable it falls back to a UTC build
timestamp. Either is stable within a build and distinct across builds whose code
differs — which is all the cache key needs.

NOTE for #6 (CI build): CI is the natural place to call this. CI can override the
value via the ``TN_BUILD_STAMP`` env var (e.g. to inject the full release SHA or a
tag) — the env var wins over the auto-detected git/timestamp value when set.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

_TARGET = Path(__file__).resolve().parent.parent / "src" / "trustworthy_notes" / "_build_stamp.py"


def _git_stamp() -> str | None:
    """Short SHA of HEAD, with ``-dirty`` if the working tree is modified; or None."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    if not sha:
        return None
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True
    ).stdout.strip()
    return f"git-{sha}{'-dirty' if dirty else ''}"


def resolve_stamp() -> str:
    """The stamp to bake: explicit override, else git SHA, else a UTC timestamp."""
    override = os.environ.get("TN_BUILD_STAMP")
    if override:
        return override
    return _git_stamp() or "build-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> None:
    stamp = resolve_stamp()
    _TARGET.write_text(
        '"""Generated at build time by scripts/stamp_build.py — do not edit, do not commit."""\n'
        f'STAMP = "{stamp}"\n',
        encoding="utf-8",
    )
    print(f"wrote {_TARGET.name}: STAMP={stamp!r}")


if __name__ == "__main__":
    main()
