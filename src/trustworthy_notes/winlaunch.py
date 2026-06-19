"""Make the Windows ``tnotes.exe`` usable with no terminal (issue #33).

A non-technical Windows user double-clicks the exe, or drags a PDF onto it. In
both cases Windows opens a fresh console window that the exe *owns* — and the
instant the process returns, that window closes. Without help the user sees the
help text (or a result) flash past and vanish, with no chance to read it, paste a
key, or learn what to do next.

This module supplies the three pieces that fix that, and nothing the pipeline
needs:

* :func:`is_windowless_launch` — detect "we own our own console" (double-click /
  drag), fail-safe to ``False`` everywhere else;
* :func:`pause` — hold the window open until a keypress, but only when windowless;
* :func:`onboard` / :func:`ensure_api_key` — the first-run key prompt and the
  friendly "drag a PDF onto me" screen.

It is deliberately import-light and the pipeline never imports it: the detection
relies on Windows-only ``ctypes`` calls that must degrade to a plain "no" off
Windows, and keeping it isolated means a source/CI run never pays for or trips
over any of it. Everything here is unit-testable by stubbing the detector and
``input`` — see the macOS caveat below.

**macOS / CI caveat.** The author develops on macOS and cannot exercise a real
Windows double-click, drag-and-drop, or console-ownership query. The branching
and the fail-safe are covered by tests that stub the detector and ``input``; the
*first real validation of the windowless path is a Windows run* of the packaged
exe.
"""

from __future__ import annotations

import platform
import sys

from . import config


def is_windowless_launch() -> bool:
    """True only when this process owns its own console — a double-click / drag launch.

    The crux of issue #33. On Windows, when a user double-clicks the exe or drags a
    file onto it, Windows spawns a brand-new console attached to *only* this
    process; when the user instead runs it from an existing PowerShell/cmd, that
    shell is already attached to the console, so the console has more than one
    process. ``kernel32.GetConsoleProcessList`` reports how many processes share the
    console: ``1`` means we are alone → windowless (the window will vanish on exit);
    ``>1`` means launched from a shell → behave exactly as a normal terminal.

    Fail-safe by construction — returns ``False`` whenever we cannot be *certain* we
    are windowless:

    * non-Windows (no such API): ``False``;
    * the ``ctypes``/``windll`` call is unavailable or raises (locked-down build,
      no console at all, redirected handles): ``False``;
    * an ambiguous count (``<= 1`` only counts as windowless when it is exactly 1;
      ``0`` or a negative error return does not): ``False``.

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
    return attached == 1


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


def ensure_api_key() -> bool:
    """Make sure a key is configured for a windowless run; prompt + save if not.

    Returns ``True`` when tnotes can authenticate to Claude (a key was already
    present, or one was just pasted and saved), ``False`` when the user gave nothing
    and we cannot proceed. Honours any existing auth source — env var or account
    login count as configured, exactly as the rest of the CLI treats them, so we
    never nag a user who is already set up another way.

    The prompt is plain ``input`` (not hidden): a double-click user pastes the key
    with a right-click, and a hidden field gives no feedback that the paste landed,
    which reads as "frozen". The key lands in the *same* place as ``tnotes auth
    set-key`` (:func:`config.set_api_key`), so the two are interchangeable.
    """
    if config.auth_source() != "none":
        return True
    print(
        "tnotes needs your Anthropic API key the first time.\n"
        "Paste your key below and press Enter (right-click to paste), or just press\n"
        "Enter to skip. Get one at https://console.anthropic.com/settings/keys.\n"
    )
    try:
        key = input("Anthropic API key: ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not key:
        print("\nNo key entered — nothing saved. Run me again when you have one.")
        return False
    config.set_api_key(key)
    print(f"\nSaved. (Stored privately in {config.config_file()}, never in any project.)")
    return True


def onboard() -> None:
    """The friendly first-screen for a bare double-click (no PDF given).

    Shows what tnotes is, makes sure a key is set (prompting on first run), and
    tells the user the one thing they need to do next — drag a PDF onto the icon.
    Always ends paused (via the caller) so the window stays readable.

    Deliberately *not* the raw ``--help`` dump: that lists a dozen power-user
    subcommands and Typer option syntax, which is noise to someone who just
    double-clicked an icon.
    """
    print("tnotes — turn a PDF into trustworthy, source-anchored notes.\n")
    if not ensure_api_key():
        return
    print(
        "\nSetup complete. Drag a PDF file onto this tnotes icon to make notes.\n"
        "The finished book is written right next to your PDF as <name>.tnotes.pdf."
    )
