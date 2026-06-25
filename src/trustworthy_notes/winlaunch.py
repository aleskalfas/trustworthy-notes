"""Windows-only launch *mechanics* for the windowless ``tnotes.exe`` (issues #33, #39).

A non-technical Windows user double-clicks the exe, or drags a PDF onto it. In
both cases Windows opens a fresh console window that the exe *owns* — and the
instant the process returns, that window closes. Without help the user sees the
help text (or a result) flash past and vanish, with no chance to read it, paste a
key, or learn what to do next.

This module is the thin platform-glue seam — the pieces that touch Windows-only
APIs and nothing the pipeline needs:

* :func:`is_windowless_launch` — detect "we own our own console" (double-click /
  drag), fail-safe to ``False`` everywhere else (Windows-only ``ctypes``);
* :func:`pause` — hold the window open until a keypress, but only when windowless;
* :func:`create_make_notes_shortcut` — drop a "Make Notes" ``.lnk`` on the desktop
  running the bare exe on a dropped PDF (issue #105), a no-op off Windows;
* :func:`create_feedback_shortcut` — drop a "Send Feedback" ``.lnk`` on the
  desktop via a PowerShell shell-out (ADR-005), a no-op off Windows.

Both shortcuts share a single private builder (:func:`_create_shortcut`); each only
chooses the ``.lnk`` name and the ``Arguments`` baked into it — mirroring how
:mod:`maclaunch` factors its droplets through ``_create_droplet``.

The first-run *flow* that calls these — the welcome screen, the key prompt, the
optional feedback setup — lives in :mod:`onboarding`, deliberately kept separate
so this module stays pure Windows mechanics.

It is deliberately import-light and the pipeline never imports it: the detection
and shortcut code rely on Windows-only calls that must degrade to a plain "no" off
Windows, and keeping it isolated means a source/CI run never pays for or trips
over any of it. Everything here is unit-testable by stubbing the platform check,
``ctypes``, ``input``, and ``subprocess`` — see the macOS caveat below.

**macOS / CI caveat.** The author develops on macOS and cannot exercise a real
Windows double-click, drag-and-drop, console-ownership query, or ``.lnk``
creation. The branching and the fail-safe are covered by tests that stub those;
the *first real validation of the windowless path is a Windows run* of the
packaged exe.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path


def _windowless_attached_count() -> int:
    """How many of *our own* processes share a freshly-spawned console — the
    count :func:`is_windowless_launch` must see for a bare double-click / drag.

    The crux of issue #158. The original detector assumed this was always ``1``,
    but that only holds for a source / one-dir run. The distributed build is a
    PyInstaller **one-file** exe (``tn.spec``), and a one-file build runs a
    *bootloader* parent that unpacks the payload to a temp dir and launches the
    real app as a **child** — and the bootloader stays alive, attached to the
    same console, until the child exits. So a double-clicked one-file exe shows
    *two* of our processes on the console, not one; a shell launch shows three
    (shell + bootloader + child). Keying off ``== 1`` therefore never fired on a
    real frozen double-click, the onboarding screen was skipped, and the window
    flashed shut — exactly the reported symptom.

    We detect "frozen" via ``sys.frozen`` (PyInstaller sets it). We ship one-file
    only, so frozen ⇒ bootloader present ⇒ expect ``2``; otherwise expect ``1``.
    The terminal case stays cleanly separated either way — a shell always adds
    exactly one more process than the windowless case.
    """
    return 2 if getattr(sys, "frozen", False) else 1


def is_windowless_launch() -> bool:
    """True only when this process owns its own console — a double-click / drag launch.

    The crux of issue #33 (and the one-file fix in #158). On Windows, when a user
    double-clicks the exe or drags a file onto it, Windows spawns a brand-new
    console attached to *only* this program's process(es); when the user instead
    runs it from an existing PowerShell/cmd, that shell is already attached to the
    console, so the console has one more process than the windowless case.
    ``kernel32.GetConsoleProcessList`` reports how many processes share the
    console; we compare it against :func:`_windowless_attached_count` (``1`` for a
    source/one-dir run, ``2`` for the one-file frozen build whose bootloader parent
    stays attached). An exact match → windowless (the window will vanish on exit);
    one more → launched from a shell → behave exactly as a normal terminal.

    Fail-safe by construction — returns ``False`` whenever we cannot be *certain* we
    are windowless:

    * non-Windows (no such API): ``False``;
    * the ``ctypes``/``windll`` call is unavailable or raises (locked-down build,
      no console at all, redirected handles): ``False``;
    * an ambiguous count (only the exact expected count is windowless; ``0`` or a
      negative error return does not): ``False``.

    The reason the unsafe direction is "behave like a terminal" is that the only
    behaviours gated on this — pausing and prompting on stdin — are *harmful* in a
    terminal/pipe/CI run (they would block automation). A false negative merely
    means a double-click window might close fast, which is a cosmetic regression to
    today's behaviour; a false positive could hang CI. So we only ever say "yes"
    when the OS tells us, unambiguously, that we are the sole owner.
    """
    if platform.system() != "Windows":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        # Ask for the count: pass a 1-slot buffer; the return value is the true
        # number of processes attached to the console, regardless of buffer size.
        count_slot = (wintypes.DWORD * 1)()
        attached = kernel32.GetConsoleProcessList(count_slot, 1)
    except Exception:
        # Any failure to query — no console, missing API, restricted build —
        # resolves to "not windowless", the safe direction.
        return False
    return attached == _windowless_attached_count()


def pause(prompt: str = "\nPress Enter to close this window…") -> None:
    """Hold the console window open until the user presses a key — windowless only.

    Guarded on :func:`is_windowless_launch` so it is a complete no-op in a terminal,
    a pipe, or CI: those runs must never block on stdin (that is the guarantee CI's
    ``tnotes.exe --help`` smoke depends on). Only a double-click/drag launch, whose
    window would otherwise flash and close, gets the pause.

    Reads via ``input`` (mockable in tests). A stdin that is closed/EOF — which a
    real windowless launch should not have, but a defensive run might — raises
    ``EOFError``; we swallow it so the pause can never itself crash the exit.
    """
    if not is_windowless_launch():
        return
    try:
        input(prompt)
    except (EOFError, KeyboardInterrupt):
        pass


def _create_shortcut(name: str, arguments: str) -> bool:
    """Create a Desktop ``.lnk`` targeting the stable exe — Windows only (ADR-005).

    The shared mechanism behind :func:`create_make_notes_shortcut` and
    :func:`create_feedback_shortcut`; they differ only in the ``.lnk`` basename and
    the baked ``Arguments``, so the platform gate, fail-safe, ``sys.executable``
    target, WorkingDirectory, quoting, and the ``powershell -Command`` invocation
    live here once. ``name`` is the Desktop ``.lnk`` basename without extension (e.g.
    ``"Make Notes"``); ``arguments`` is the fixed argument string to bake in (``""``
    for the bare exe → run/orchestrator flow, ``"feedback"`` for feedback) — both
    authored literals, never user input.

    Returns ``True`` when a shortcut was created, ``False`` on any other outcome:
    off Windows it is a **no-op** that returns ``False`` (mirroring how
    :func:`is_windowless_launch` gates its ctypes call behind a platform check), and
    a failed shell-out is swallowed and returns ``False`` so onboarding never
    crashes over a cosmetic extra. The *consent* gate lives in
    :func:`onboarding.offer_desktop_shortcuts`; this is just the platform glue.

    Mechanism (ADR-005, exactly): a ``powershell -Command`` shell-out invoking
    ``WScript.Shell.CreateShortcut`` — **no** ``win32com``/``pywin32`` dependency,
    since PowerShell ships on every Windows 10/11. The shortcut targets the *stable*
    running exe name (``sys.executable`` when frozen), so it survives ADR-001's
    upgrade rename (which moves the new build into the freed stable name); we
    deliberately do not encode a versioned path.
    """
    if platform.system() != "Windows":
        return False
    target = sys.executable
    desktop = Path.home() / "Desktop"
    lnk = desktop / f"{name}.lnk"
    # WScript.Shell builds the .lnk; TargetPath is the stable exe, Arguments is the
    # baked argument string, WorkingDirectory the exe's folder. Quoting: PowerShell
    # single-quotes take any path verbatim, and we escape an embedded single quote
    # the PowerShell way (doubling it) so a username with a quote can't break out.
    def ps_quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    script = (
        "$w = New-Object -ComObject WScript.Shell; "
        f"$s = $w.CreateShortcut({ps_quote(str(lnk))}); "
        f"$s.TargetPath = {ps_quote(target)}; "
        f"$s.Arguments = {ps_quote(arguments)}; "
        f"$s.WorkingDirectory = {ps_quote(str(Path(target).parent))}; "
        "$s.Save()"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            check=False,
        )
    except OSError:
        # PowerShell missing or unlaunchable — the safe direction is "no shortcut".
        return False
    return result.returncode == 0


def create_make_notes_shortcut() -> bool:
    """Create a "Make Notes" ``.lnk`` on the user's desktop — Windows only (ADR-005, #105).

    The book-flow analogue of :func:`create_feedback_shortcut` and the Windows twin of
    :func:`maclaunch.create_make_notes_droplet`: dropping a PDF onto it launches the bare
    exe with the file (``Arguments`` empty), so Windows hands the dropped path to the
    run/orchestrator flow. See :func:`_create_shortcut` for the shared platform gate,
    fail-safe, stable-exe target, and PowerShell mechanism; this only names the ``.lnk``
    and bakes no argument.
    """
    return _create_shortcut("Make Notes", "")


def create_feedback_shortcut() -> bool:
    """Create a "Send Feedback" ``.lnk`` on the user's desktop — Windows only (ADR-005).

    Dropping a PDF onto it (or double-clicking it) launches ``tnotes.exe feedback``. See
    :func:`_create_shortcut` for the shared platform gate, fail-safe, stable-exe target,
    and PowerShell mechanism; this only names the ``.lnk`` and bakes the ``feedback``
    argument. The shortcut targets the *stable* exe so it survives ADR-001's upgrade
    rename; we deliberately do not encode a versioned path.
    """
    return _create_shortcut("Send Feedback", "feedback")
