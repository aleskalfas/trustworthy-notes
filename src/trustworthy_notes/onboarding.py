"""First-run onboarding flow for a windowless ``tnotes.exe`` (issues #33, #39).

A non-technical Windows user double-clicks the exe with no PDF. This module is the
*flow* that greets them: it shows what tnotes is, makes sure a Claude key is set,
optionally captures the feedback credentials so ``tnotes feedback`` works with no
terminal, and optionally drops a "Send Feedback" shortcut on the desktop. It then
hands back to the caller, which pauses so the window stays readable.

This is deliberately split from :mod:`winlaunch`, which now holds only the
Windows-only launch *mechanics* (console-ownership detection, the pause, and the
shortcut platform-glue). The flow here *calls* those primitives; it carries no
Windows-only ctypes/subprocess of its own, so it is plain, import-light, and fully
unit-testable by stubbing ``input`` and the config setters.

**macOS / CI caveat.** The author develops on macOS and cannot exercise a real
Windows double-click. The branching is covered by tests that stub ``input`` and
the config setters; the *first real validation of the windowless path is a Windows
run* of the packaged exe — the same honesty :mod:`winlaunch` already states for
its console code, and ADR-005 restates for the shortcut.
"""

from __future__ import annotations

from . import config, winlaunch


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


def setup_feedback() -> bool:
    """Optional first-run step: capture the feedback credentials, no terminal needed.

    Returns ``True`` when the feedback feature is now configured to file online (a
    repo + token are present after this call), ``False`` when the user skipped or
    gave too little. Skipping is the easy default — a user who isn't doing feedback
    just presses Enter at the first prompt and the step is over.

    Why collect repo + token + name together in one optional step: ``tnotes
    feedback`` can only file online when it has *both* the repo and the token (one
    without the other still falls back to a local file), and the whole point of #39
    is that a windowless user can be fully set up without ever opening a terminal.
    So the three pieces that ``tnotes config set-feedback-*`` would otherwise set
    by hand are gathered here in one pass. Each lands in the *same* place as those
    commands (:func:`config.set_feedback_repo` / :func:`config.set_feedback_token`
    / :func:`config.set_reporter_name`), so the two are interchangeable.

    The token prompt is plain ``input`` (not hidden), for the same paste-feedback
    reason as the API key above. An already-configured repo+token short-circuits to
    ``True`` without nagging.
    """
    if config.get_feedback_repo() and config.get_feedback_token():
        return True
    print(
        "\nOptional: set up feedback so you can report a problem with one click.\n"
        "You'll need a private feedback repo and its access token from whoever\n"
        "gave you tnotes. Press Enter to skip — you can always do this later.\n"
    )
    try:
        repo = input("Feedback repo (owner/name), or Enter to skip: ").strip()
        if not repo:
            print("Skipped feedback setup.")
            return False
        token = input("Feedback access token (right-click to paste): ").strip()
        if not token:
            print("No token entered — skipping feedback setup. Run me again to finish it.")
            return False
        name = input("Your name (tagged onto reports), or Enter to skip: ").strip()
    except (EOFError, KeyboardInterrupt):
        return False

    config.set_feedback_repo(repo)
    config.set_feedback_token(token)
    if name:
        config.set_reporter_name(name)
    print(f"\nFeedback ready. (Saved privately in {config.config_file()}.)")
    return True


def offer_feedback_shortcut() -> None:
    """Offer, behind a one-tap confirm, to drop a "Send Feedback" desktop shortcut.

    Per ADR-005: never silent — the shortcut is created only when the user agrees.
    Defaults to yes (Enter accepts) so the easy path is one keypress, but any answer
    other than yes declines cleanly. The actual ``.lnk`` creation is delegated to
    :func:`winlaunch.create_feedback_shortcut`, which is a no-op off Windows; this
    flow only handles the consent and the user-facing reporting.
    """
    try:
        answer = input(
            "\nAdd a Send Feedback shortcut to your Desktop? [Y/n] "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if answer not in ("", "y", "yes"):
        return
    if winlaunch.create_feedback_shortcut():
        print("Added a Send Feedback shortcut to your Desktop.")
    else:
        print("Couldn't create the shortcut — you can still run feedback any time.")


def onboard() -> None:
    """The friendly first-screen for a bare double-click (no PDF given).

    Shows what tnotes is, makes sure a key is set (prompting on first run), offers
    the optional feedback setup and its desktop shortcut, then tells the user the
    one thing they need to do next — drag a PDF onto the icon. Always ends paused
    (via the caller) so the window stays readable.

    Deliberately *not* the raw ``--help`` dump: that lists a dozen power-user
    subcommands and Typer option syntax, which is noise to someone who just
    double-clicked an icon.

    The feedback steps run *after* the key is confirmed: a user who skips the key
    isn't ready to use tnotes at all, so we don't pile feedback questions on top —
    we return early and let them come back once they have a key.
    """
    print("tnotes — turn a PDF into trustworthy, source-anchored notes.\n")
    if not ensure_api_key():
        return
    if setup_feedback():
        offer_feedback_shortcut()
    print(
        "\nSetup complete. Drag a PDF file onto this tnotes icon to make notes.\n"
        "The finished book is written right next to your PDF as <name>.tnotes.pdf."
    )
