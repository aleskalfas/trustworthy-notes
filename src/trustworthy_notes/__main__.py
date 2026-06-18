"""Run the tnotes CLI as ``python -m trustworthy_notes`` and as the frozen exe.

The ``tnotes`` console-script entry (``trustworthy_notes.cli:app``) is what pip/uv
installs; a PyInstaller one-file build instead invokes this module as the program
entry point. Both call the same typer app, so the frozen exe behaves identically.
"""

from __future__ import annotations

# Absolute (not relative) import on purpose: PyInstaller invokes this file as a
# top-level script with no parent package, so ``from .cli import app`` would raise
# "attempted relative import with no known parent package". The absolute form
# works both ways — as ``python -m trustworthy_notes`` and as the frozen exe.
from trustworthy_notes.cli import app


def main() -> None:
    app()


if __name__ == "__main__":
    main()
