"""Where a document's generated artifacts live.

Convention: every output for a source document goes in a sibling folder named
after the full source filename plus a ``.tnotes`` marker — ``data/Foo.pdf`` →
``data/Foo.pdf.tnotes/``. The marker is what makes this legal: a directory cannot
share a name with the source file, so we keep the full filename (incl. its
extension, so it sorts beside the source) and append ``.tnotes``. One folder per
document keeps all generated artifacts beside their source and never mixes two
documents. Any command's ``--out`` overrides the location.

Inside the work dir, outputs are grouped into **numbered wave folders** that mirror
the pipeline (ARCHITECTURE §1), so a listing reads in pipeline order::

    Foo.pdf.tnotes/
      1-extract/    page-NNNN.notes.yaml            (Wave 1: per-page atoms)
      2-compose/    chapters.txt, stitches.txt, …   (Wave 2: chapter assembly)
      3-validate/   gaps.txt                        (Wave 3: coverage/validation)
"""

from __future__ import annotations

from pathlib import Path

WAVE_EXTRACT = "1-extract"
WAVE_COMPOSE = "2-compose"
WAVE_VALIDATE = "3-validate"
WAVE_EXPORT = "4-export"


def work_dir(input_path: str | Path, override: str | Path | None = None) -> Path:
    """The output folder for ``input_path`` — ``override`` if given, else the
    sibling ``<filename>.tnotes`` folder (``data/Foo.pdf`` → ``data/Foo.pdf.tnotes``)."""
    if override is not None:
        return Path(override)
    p = Path(input_path)
    return p.parent / (p.name + ".tnotes")


def extract_dir(work_dir: str | Path) -> Path:
    """Wave 1 folder (per-page notes) inside a work dir."""
    return Path(work_dir) / WAVE_EXTRACT


def compose_dir(work_dir: str | Path) -> Path:
    """Wave 2 folder (chapter assembly + its views) inside a work dir."""
    return Path(work_dir) / WAVE_COMPOSE


# Wave 2 is multi-stage, so its folder is itself split into stage-numbered
# subfolders (mirroring §6), keeping the 40 chapter deliverables apart from the
# per-stage views/data.
COMPOSE_SUBDIRS = {
    "chapter-map": "1-chapter-map",
    "stitches": "2-stitches",
    "dedup": "3-dedup",
    "terms": "4-terms",
    "relations": "5-relations",
    "chapters": "6-chapters",
}


def compose_stage_dir(work_dir: str | Path, stage: str) -> Path:
    """A stage subfolder inside the Wave 2 folder, e.g. ``2-compose/3-dedup/``."""
    return compose_dir(work_dir) / COMPOSE_SUBDIRS[stage]


def validate_dir(work_dir: str | Path) -> Path:
    """Wave 3 folder (coverage/validation views) inside a work dir."""
    return Path(work_dir) / WAVE_VALIDATE


def export_dir(work_dir: str | Path) -> Path:
    """Wave 4 folder (human-readable study documents) inside a work dir."""
    return Path(work_dir) / WAVE_EXPORT


def page_notes_path(work_dir: str | Path, page_index: int) -> Path:
    """Canonical per-page notes file: ``<work_dir>/1-extract/page-NNNN.notes.yaml``."""
    return extract_dir(work_dir) / f"page-{page_index:04d}.notes.yaml"
