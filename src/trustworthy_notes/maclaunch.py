"""macOS-only launch *mechanics* for the desktop droplets (issues #69, #102).

The macOS analogue of :mod:`winlaunch`'s ``create_feedback_shortcut``. Where Windows
gets a ``.lnk`` from a PowerShell shell-out, macOS gets an AppleScript **droplet** —
an ``.app`` with an ``on open`` handler — compiled by ``osacompile``, the OS's own
always-present scripting toolchain (ADR-005). A user drags a PDF onto the droplet (or
double-clicks it) and it opens Terminal running ``tnotes`` against that file.

This module is the thin platform-glue seam — the pieces that touch macOS-only tooling
and nothing the pipeline needs:

* :func:`create_make_notes_droplet` — compile a "Make Notes" droplet onto the user's
  Desktop, running the bare ``tnotes <pdf>`` book flow on a dropped PDF (issue #102).
* :func:`create_feedback_droplet` — compile a "Send Feedback" droplet onto the
  user's Desktop, running ``tnotes feedback <pdf>`` (issue #69).

Both are produced via ``osacompile`` (ADR-005) and are a no-op off macOS. They share a
single private builder (:func:`_create_droplet`); each only chooses the ``.app`` name
and the ``tnotes`` arguments to bake in.

Mirroring :mod:`winlaunch`, it is gated (``platform.system() != "Darwin"`` → a no-op
returning ``False``) and fail-safe (a failed shell-out is swallowed → ``False``), so a
droplet hiccup never breaks the install. The *flow* that calls it — the install step —
lives in ``scripts/bootstrap.sh`` via the ``tnotes install-droplet`` command, kept
separate so this module stays pure macOS mechanics.

It is deliberately import-light and the pipeline never imports it (ADR-005, and the
network/OS-module invariant in ARCHITECTURE.md §4): the droplet touches **no network**
— it bakes a local ``tnotes`` path and shells to it — so this is an OS-integration
module, not a network one. Everything here is unit-testable by stubbing the platform
check, the path resolver, and ``subprocess`` — see the cross-OS caveat below.

**Why the absolute path is baked in.** A Finder-launched ``.app`` gets only the
minimal launchd environment, not the user's shell PATH, so a bare ``tnotes`` in the
droplet would not resolve (ADR-005). So we resolve the absolute ``tnotes`` path *at
install time* — when this runs from the user's shell — and bake it into the compiled
script. The macOS analogue of the Windows "stable target" choice, rooted in
environment isolation rather than the upgrade rename.

**Cross-OS caveat.** The droplet path is validated on macOS (where the author works);
the Windows ``.lnk`` path in :mod:`winlaunch` is validated on Windows. Each launcher is
first exercised for real only on its own platform (ADR-005); off-macOS this is a tested
no-op.
"""

from __future__ import annotations

import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _resolve_tnotes_path(tnotes_path: str | None) -> str:
    """Resolve the absolute ``tnotes`` path to bake into the droplet (ADR-005).

    A Finder launch can't see the shell PATH, so the droplet must carry an absolute
    target. Resolution order, first hit wins:

    1. an explicit ``tnotes_path`` argument (the caller already knows it);
    2. ``shutil.which("tnotes")`` — the installed console script on the shell PATH,
       which is exactly the install-time context this runs in;
    3. ``sys.argv[0]`` resolved to an absolute path — a last-ditch fallback to
       whatever invoked us.

    Always returns an absolute path string so the bake is unambiguous.
    """
    if tnotes_path:
        return str(Path(tnotes_path).resolve())
    found = shutil.which("tnotes")
    if found:
        return str(Path(found).resolve())
    return str(Path(sys.argv[0]).resolve())


def _applescript_source(tnotes_abs: str, subcommand: str = "") -> str:
    """The droplet's AppleScript: ``on open`` (drag) + ``on run`` (double-click).

    Per dropped file, opens Terminal running ``<abs-tnotes>[ <subcommand>] <abs-path>``;
    a double-click with no file runs ``<abs-tnotes>[ <subcommand>][ --help]`` for a
    friendly hint. The absolute ``tnotes`` is baked in (a Finder launch has no shell
    PATH — ADR-005). ``subcommand`` is the optional tnotes subcommand to bake in
    (``"feedback"`` for the feedback droplet; ``""`` for the bare ``tnotes <pdf>`` book
    flow — issue #102); it is a fixed literal we author, never user input.

    Two quoting layers, because the path crosses two interpreters. The shell command
    Terminal runs is built with :func:`shlex.quote` (POSIX shell safety); the resulting
    string is then embedded as an AppleScript string literal, where we escape the
    AppleScript metacharacters ``\\`` and ``"``. The dropped file's POSIX path comes
    from ``quoted form of POSIX path of f`` so AppleScript itself shell-quotes it.
    """
    # The baked tnotes path is shell-quoted once (it may contain spaces — e.g. an
    # install under "Application Support"), then embedded as an AppleScript literal.
    tnotes_shell = shlex.quote(tnotes_abs)
    tnotes_literal = _as_applescript_string(tnotes_shell)
    # The space-padded subcommand spliced into each baked command, and what a
    # double-click with no file runs. Bare droplet (no subcommand) gets a single
    # trailing space before the dropped path and a `--help` hint on double-click;
    # a subcommand droplet keeps the existing ` feedback ` / ` feedback` shape.
    open_infix = f" {subcommand} " if subcommand else " "
    run_suffix = f" {subcommand}" if subcommand else " --help"
    open_infix_literal = _as_applescript_string(open_infix)
    run_suffix_literal = _as_applescript_string(run_suffix)
    return (
        "on open theFiles\n"
        "    repeat with f in theFiles\n"
        "        set cmd to " + tnotes_literal + " & " + open_infix_literal
        + " & quoted form of POSIX path of f\n"
        "        tell application \"Terminal\" to do script cmd\n"
        "    end repeat\n"
        "end open\n"
        "\n"
        "on run\n"
        "    tell application \"Terminal\" to do script " + tnotes_literal
        + " & " + run_suffix_literal + "\n"
        "end run\n"
    )


def _as_applescript_string(value: str) -> str:
    """Wrap ``value`` as an AppleScript double-quoted string literal, escaped.

    AppleScript string literals use ``"…"`` with ``\\`` and ``"`` as the two
    metacharacters; escape both so a path containing either can't break out of the
    literal (defence in depth — the value is already shell-quoted).
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped + '"'


def _create_droplet(app_name: str, subcommand: str, tnotes_path: str | None) -> bool:
    """Compile a Desktop droplet running ``tnotes[ <subcommand>] <dropped>`` — macOS only.

    The shared mechanism behind :func:`create_make_notes_droplet` and
    :func:`create_feedback_droplet`; they differ only in the ``.app`` name and the
    baked subcommand, so the platform gate, fail-safe, path bake, and ``osacompile``
    invocation live here once. ``app_name`` is the Desktop ``.app`` basename (e.g.
    ``"Make Notes.app"``); ``subcommand`` is the fixed tnotes subcommand to bake in
    (``""`` for the bare book flow, ``"feedback"`` for feedback) — both authored
    literals, never user input.

    Returns ``True`` when a droplet was compiled, ``False`` on any other outcome: off
    macOS it is a **no-op** that returns ``False`` (mirroring how
    :func:`winlaunch.create_feedback_shortcut` gates its PowerShell call behind a
    platform check), and a failed ``osacompile`` is swallowed and returns ``False`` so
    the install never breaks over a cosmetic extra. The *user-initiated* gate is the
    install/bootstrap step the user chose to run, or an explicit ``tnotes
    install-droplet`` (ADR-005); this is just the platform glue.

    Mechanism (ADR-005, exactly): build an AppleScript droplet (an ``on open`` handler
    that does ``tell application "Terminal" to do script "<tnotes>[ <subcommand>]
    <dropped>"``, plus an ``on run`` for a double-click) and compile it to an ``.app``
    with ``osacompile`` — **no** bundled app framework, since ``osacompile`` ships on
    every macOS. The target is the **absolute** ``tnotes`` path resolved here, in the
    user's shell, and baked into the script — a Finder launch gets only the minimal
    launchd PATH, so a bare ``tnotes`` would not resolve.
    """
    if platform.system() != "Darwin":
        return False
    tnotes_abs = _resolve_tnotes_path(tnotes_path)
    source = _applescript_source(tnotes_abs, subcommand)
    droplet = Path.home() / "Desktop" / app_name
    try:
        # osacompile reads the source from a file; write it to a temp .applescript,
        # compile, then clean up. delete=False so osacompile can reopen the path on any
        # platform; we remove it ourselves in finally.
        with tempfile.NamedTemporaryFile(
            "w", suffix=".applescript", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(source)
            script_path = handle.name
        try:
            result = subprocess.run(
                ["osacompile", "-o", str(droplet), script_path],
                capture_output=True,
                check=False,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)
    except OSError:
        # osacompile missing or unlaunchable, or the temp write failed — the safe
        # direction is "no droplet".
        return False
    return result.returncode == 0


def create_make_notes_droplet(tnotes_path: str | None = None) -> bool:
    """Create a "Make Notes" droplet on the user's Desktop — macOS only (ADR-005, #102).

    The book-flow analogue of :func:`create_feedback_droplet`: dragging a PDF onto it
    opens Terminal running the bare ``tnotes <pdf>`` (the windowless run flow → book +
    the clean-vs-cited prompt), with **no** subcommand. A double-click with no file runs
    ``tnotes --help`` as a friendly hint to drag a PDF on. See :func:`_create_droplet`
    for the shared platform gate, fail-safe, absolute-path bake, and ``osacompile``
    mechanism; this only names the ``.app`` and bakes no subcommand.
    """
    return _create_droplet("Make Notes.app", "", tnotes_path)


def create_feedback_droplet(tnotes_path: str | None = None) -> bool:
    """Create a "Send Feedback" droplet on the user's Desktop — macOS only (ADR-005).

    Dragging a PDF onto it opens Terminal running ``tnotes feedback <pdf>``; a
    double-click with no file runs ``tnotes feedback`` for a general report. See
    :func:`_create_droplet` for the shared platform gate, fail-safe, absolute-path
    bake, and ``osacompile`` mechanism; this only names the ``.app`` and bakes the
    ``feedback`` subcommand.
    """
    return _create_droplet("Send Feedback.app", "feedback", tnotes_path)
