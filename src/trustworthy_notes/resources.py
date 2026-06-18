"""The single frozen-aware seam for reaching files shipped inside the package.

Several consumers need files that travel with the code — the bundled Charis SIL
fonts (``pdf.py``) and the notes JSON Schema (``validation.py``) — and a frozen
one-file build (PyInstaller) is the hazard they all share: under a freeze the
package has no directory on disk, its contents live unpacked under ``_MEIPASS``,
and ``importlib.resources.files()`` returns a ``Traversable`` that is not
guaranteed to be a real filesystem path. Anything that needs an honest path on
disk (reportlab's ``TTFont`` opens by filename; a jsonschema file-path use would
too) must therefore go through ``importlib.resources.as_file()``, which
materialises a real path for the duration of a ``with`` block.

So this is the one place that knows how to reach package data, frozen or not.
Both real consumers route through here; new ones should too rather than calling
``importlib.resources`` directly. (pdfminer's cmap data is the third member of
the same hazard, but pdfminer locates its own data internally — the build config
bundles it via ``--collect-data pdfminer``; there is no runtime call to make here.)
"""

from __future__ import annotations

from contextlib import contextmanager
from importlib.resources import as_file, files
from pathlib import Path
from typing import Iterator

_PACKAGE = "trustworthy_notes"


@contextmanager
def package_path(*parts: str) -> Iterator[Path]:
    """Yield a real filesystem ``Path`` to a packaged file, frozen-safe.

    ``parts`` is the path under the package, e.g. ``package_path("fonts",
    "Charis-Regular.ttf")``. Use this whenever a consumer needs a path it can
    hand to an API that opens files by name (reportlab, jsonschema). The path is
    only guaranteed valid inside the ``with`` block: under a freeze ``as_file``
    may extract to a temporary location that is cleaned up on exit, so do the
    file work (open/read/register) before leaving the block.
    """
    resource = files(_PACKAGE)
    for part in parts:
        resource = resource / part
    with as_file(resource) as path:
        yield path


def read_text(*parts: str, encoding: str = "utf-8") -> str:
    """Read a packaged text file in one call (frozen-safe).

    A convenience over :func:`package_path` for the common case of "read the
    whole file as text" — the read happens inside the managed path's lifetime.
    """
    with package_path(*parts) as path:
        return path.read_text(encoding=encoding)
