"""Persisted, human-readable command outputs.

The inspection views (chapters, stitches, gap) are expensive only because they
re-parse the PDF (~30s). Rather than a hidden cache, we save each view as a
plainly-named text file in the document's workspace (``chapters.txt`` etc.) with
a one-line provenance header. You can open the file anytime to see the last run;
re-running shows it instantly when nothing changed, and regenerates when it did.

Freshness is a fingerprint of everything the output depends on — the PDF bytes,
the ingest source (so a parser change rebuilds it), the per-page notes' state,
and the command's options. No version numbers to remember to bump.
"""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path
from typing import Callable

import typer

from . import build, ingest, models, translit, workspace

_HEADER = "# tn artifact"


def _code_identity() -> bytes:
    """Bytes identifying the output-producing code, for cache invalidation.

    In a dev checkout, hash the source of the modules an artifact depends on
    (``ingest``/``translit``/``models``) for fine-grained invalidation — editing
    one rebuilds the dependent artifacts. A frozen build has no ``.py`` on disk,
    so fall back to the baked build identity (version + build stamp), which is
    stable within a build and distinct across builds whose code differs.
    """
    if getattr(sys, "frozen", False):
        return build.build_identity().encode()
    parts = []
    for mod in (ingest, translit, models):
        parts.append(Path(mod.__file__).read_bytes())
    return b"".join(parts)


def inputs_fingerprint(pdf_path: str | Path, work_dir: str | Path, params: str = "") -> str:
    """A short hash over the PDF, the ingest source, the per-page notes' state, and
    the command options — changes whenever any output-affecting input changes."""
    h = hashlib.sha256()
    h.update(Path(pdf_path).read_bytes())
    h.update(_code_identity())
    for f in sorted(workspace.extract_dir(work_dir).glob("page-*.notes.yaml")):
        s = f.stat()
        h.update(f"{f.name}:{s.st_size}:{s.st_mtime_ns}".encode())
    h.update(params.encode())
    return h.hexdigest()[:16]


def read_fresh(path: Path, fingerprint: str) -> str | None:
    """Return the saved body (sans header) if ``path`` exists and its fingerprint
    matches; else ``None``."""
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines and lines[0].startswith(_HEADER) and f"fp={fingerprint}" in lines[0]:
        return "\n".join(lines[1:])
    return None


def emit(path: Path, fingerprint: str, force: bool, render: Callable[[], str], *, label: str) -> None:
    """Show the saved artifact if still fresh; else render it, print, and save it.

    ``render`` does the expensive work and returns the report body as text.
    """
    if not force:
        cached = read_fresh(path, fingerprint)
        if cached is not None:
            typer.echo(cached)
            typer.echo(f"\n[unchanged since last run — saved view at {path}; --force to regenerate]", err=True)
            return
    body = render()
    header = f"{_HEADER}  {label}  generated {time.strftime('%Y-%m-%d %H:%M')}  fp={fingerprint}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n" + body + "\n", encoding="utf-8")
    typer.echo(body)
    typer.echo(f"\n[saved to {path} — shown instantly next time unless inputs change]", err=True)
