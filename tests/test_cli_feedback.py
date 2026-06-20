"""CLI wiring for `tnotes feedback` (issues #39/#40): the guided, windowless flow
driven from the "Send Feedback" desktop shortcut, plus the positional-doc routing.

These assert the Typer wiring around `feedback.run_feedback` (which is exercised
directly in test_feedback): the positional-vs-message disambiguation, and the
windowless branch the cli takes given the detector. They stub
`winlaunch.is_windowless_launch`, `input`, `winlaunch.pause`, and `run_feedback`,
never a real Windows console. The two guarantees under test mirror the run-path
(#33) ones: a windowless launch ensures the key, prompts for the message, runs
the flow, and PAUSEs; a NON-windowless launch is unchanged and never blocks on
stdin. First real validation of the live launch is a Windows run of the exe.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from trustworthy_notes import cli, feedback as feedbackmod, onboarding, winlaunch

runner = CliRunner()


def _windowless(monkeypatch, value: bool):
    monkeypatch.setattr(winlaunch, "is_windowless_launch", lambda: value)


def _no_startup_nudge(monkeypatch):
    from trustworthy_notes import updater

    monkeypatch.setattr(updater, "is_frozen", lambda: False)


def _stub_run_feedback(monkeypatch, seen: dict, *, drive_consent: bool = False):
    """Capture the args run_feedback is called with; return a 'saved locally' outcome.

    With ``drive_consent`` the stub also invokes the injected ``confirm`` callback
    (the real consent gate the cli wires to ``typer.confirm``), so a test can assert
    the gate is reached before any upload. Tests that don't need that leave it off,
    so they need not feed a confirm answer on stdin.
    """

    def fake(message, **kwargs):
        seen["message"] = message
        seen.update(kwargs)
        if drive_consent:
            seen["consented"] = kwargs["confirm"]("PREVIEW-TEXT")
        return feedbackmod.FeedbackOutcome(
            filed=False, location="/tmp/feedback-x.txt", reporter=kwargs["reporter"],
            ai_structured=False, reason="no feedback repo/token configured",
        )

    monkeypatch.setattr(feedbackmod, "run_feedback", fake)


def _stub_list_issues(monkeypatch, listing=None):
    """Stub the read-only issue listing so the windowless flow never hits the network.

    Defaults to an empty, available listing; pass a listing to assert the display.
    """
    listing = listing or feedbackmod.IssueListing(available=True, issues=[])
    monkeypatch.setattr(feedbackmod, "list_recent_issues", lambda *a, **k: listing)


# --- positional disambiguation (terminal usage) -----------------------------------


def test_positional_existing_file_routes_as_doc(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, False)
    pdf = tmp_path / "Foo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    monkeypatch.setattr(cli.config, "get_reporter_name", lambda: "Jana")
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    # A bare PDF path + an explicit message flag: the path is the doc, -m is the message.
    res = runner.invoke(cli.app, ["feedback", str(pdf), "-m", "page 3 is wrong"])
    assert res.exit_code == 0, res.output
    assert seen["doc"] == pdf
    assert seen["message"] == "page 3 is wrong"


def test_positional_text_routes_as_message(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, False)
    monkeypatch.setattr(cli.config, "get_reporter_name", lambda: "Jana")
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    res = runner.invoke(cli.app, ["feedback", "the export crashed"])
    assert res.exit_code == 0, res.output
    assert seen["message"] == "the export crashed"
    assert seen["doc"] is None


def test_doc_option_still_works(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, False)
    pdf = tmp_path / "Foo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    monkeypatch.setattr(cli.config, "get_reporter_name", lambda: "Jana")
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    res = runner.invoke(cli.app, ["feedback", "broken", "--doc", str(pdf), "-p", "1-2"])
    assert res.exit_code == 0, res.output
    assert seen["doc"] == pdf
    assert seen["pages"] == "1-2"
    assert seen["message"] == "broken"


def test_positional_doc_and_doc_option_agree(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, False)
    pdf = tmp_path / "Foo.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    monkeypatch.setattr(cli.config, "get_reporter_name", lambda: "Jana")
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    # Same document by both routes is fine; the message comes from the flag.
    res = runner.invoke(cli.app, ["feedback", str(pdf), "--doc", str(pdf), "-m", "x"])
    assert res.exit_code == 0, res.output
    assert seen["doc"] == pdf


def test_positional_doc_conflicting_with_doc_option_errors(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, False)
    a = tmp_path / "A.pdf"
    b = tmp_path / "B.pdf"
    a.write_bytes(b"%PDF-1.4")
    b.write_bytes(b"%PDF-1.4")
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    res = runner.invoke(cli.app, ["feedback", str(a), "--doc", str(b)])
    assert res.exit_code == 2
    assert "different documents" in res.output
    assert seen == {}  # never reached run_feedback


# --- windowless guided flow -------------------------------------------------------


def test_windowless_prompts_for_message_runs_and_pauses(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, True)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")  # key already set
    monkeypatch.setattr(cli.config, "get_reporter_name", lambda: "Jana")
    paused = {"n": 0}
    monkeypatch.setattr(winlaunch, "pause", lambda *a, **k: paused.__setitem__("n", paused["n"] + 1))
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)
    _stub_list_issues(monkeypatch)

    # The double-click user has no -m flag: the message comes from the prompt.
    res = runner.invoke(cli.app, ["feedback"], input="the book came out blank\n")
    assert res.exit_code == 0, res.output
    assert seen["message"] == "the book came out blank"
    assert seen["doc"] is None
    assert "general problem" in res.output
    assert paused["n"] == 1  # paused exactly once, on the success exit


def test_windowless_dropped_pdf_reports_against_it(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, True)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")
    monkeypatch.setattr(cli.config, "get_reporter_name", lambda: "Jana")
    monkeypatch.setattr(winlaunch, "pause", lambda *a, **k: None)
    pdf = tmp_path / "Dropped.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)
    _stub_list_issues(monkeypatch)

    res = runner.invoke(cli.app, ["feedback", str(pdf)], input="page 7 wrong\n")
    assert res.exit_code == 0, res.output
    assert seen["doc"] == pdf
    assert seen["message"] == "page 7 wrong"
    assert "Dropped.pdf" in res.output  # confirmed the dropped doc to the user


def test_windowless_reaches_consent_gate_before_upload(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, True)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")
    monkeypatch.setattr(cli.config, "get_reporter_name", lambda: "Jana")
    monkeypatch.setattr(winlaunch, "pause", lambda *a, **k: None)
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen, drive_consent=True)
    _stub_list_issues(monkeypatch)

    # The stub invokes the confirm() callback (the consent gate) — which the cli
    # wires to typer.confirm; a "y\n" after the message answers it.
    res = runner.invoke(cli.app, ["feedback"], input="something broke\ny\n")
    assert res.exit_code == 0, res.output
    assert "PREVIEW-TEXT" in res.output  # the consent preview was shown
    assert seen["consented"] is True


def test_windowless_missing_key_exits_and_pauses(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, True)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "none")
    paused = {"n": 0}
    monkeypatch.setattr(winlaunch, "pause", lambda *a, **k: paused.__setitem__("n", paused["n"] + 1))
    called = {"run": False}
    monkeypatch.setattr(feedbackmod, "run_feedback", lambda *a, **k: called.__setitem__("run", True))

    # No key pasted (just Enter at the key prompt) → bail before any feedback flow.
    res = runner.invoke(cli.app, ["feedback"], input="\n")
    assert res.exit_code == 1
    assert called["run"] is False
    assert paused["n"] == 1


def test_windowless_empty_message_exits_without_running(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, True)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")
    paused = {"n": 0}
    monkeypatch.setattr(winlaunch, "pause", lambda *a, **k: paused.__setitem__("n", paused["n"] + 1))
    called = {"run": False}
    monkeypatch.setattr(feedbackmod, "run_feedback", lambda *a, **k: called.__setitem__("run", True))
    _stub_list_issues(monkeypatch)

    res = runner.invoke(cli.app, ["feedback"], input="\n")  # empty message
    assert res.exit_code == 1
    assert "nothing to report" in res.output
    assert called["run"] is False
    assert paused["n"] == 1


# --- NON-windowless: unchanged, never pauses, never extra-prompts -----------------


def test_non_windowless_does_not_pause(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, False)
    monkeypatch.setattr(cli.config, "get_reporter_name", lambda: "Jana")
    paused = {"n": 0}
    monkeypatch.setattr(winlaunch, "pause", lambda *a, **k: paused.__setitem__("n", paused["n"] + 1))
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    res = runner.invoke(cli.app, ["feedback", "-m", "a problem"])
    assert res.exit_code == 0, res.output
    # winlaunch.pause is a no-op off windowless even when called — but assert the
    # terminal path never showed the windowless guidance lines.
    assert "general problem" not in res.output
    assert "Reporting a problem with" not in res.output
    assert seen["message"] == "a problem"


# --- issue listing in the windowless flow (issue #41) ----------------------------


def test_windowless_shows_already_reported_issues(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, True)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")
    monkeypatch.setattr(cli.config, "get_reporter_name", lambda: "Jana")
    monkeypatch.setattr(winlaunch, "pause", lambda *a, **k: None)
    _stub_run_feedback(monkeypatch, {})
    _stub_list_issues(monkeypatch, feedbackmod.IssueListing(
        available=True,
        issues=[
            feedbackmod.IssueSummary(number=7, title="export looks blank", state="open"),
            feedbackmod.IssueSummary(number=4, title="page 3 garbled", state="open"),
        ],
    ))

    res = runner.invoke(cli.app, ["feedback"], input="another problem\n")
    assert res.exit_code == 0, res.output
    assert "Already reported:" in res.output
    assert "#7 [open] export looks blank" in res.output
    assert "#4 [open] page 3 garbled" in res.output


def test_windowless_listing_unavailable_shows_fallback_line(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, True)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")
    monkeypatch.setattr(cli.config, "get_reporter_name", lambda: "Jana")
    monkeypatch.setattr(winlaunch, "pause", lambda *a, **k: None)
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)
    _stub_list_issues(monkeypatch, feedbackmod.IssueListing(
        available=False, reason="could not reach the feedback repo: offline",
    ))

    # Listing failure must not crash the flow — the report still goes through.
    res = runner.invoke(cli.app, ["feedback"], input="still works\n")
    assert res.exit_code == 0, res.output
    assert "Couldn't reach the feedback repo to list existing reports" in res.output
    assert seen["message"] == "still works"


def test_windowless_no_issues_yet_shows_first_line(tmp_path, monkeypatch):
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, True)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")
    monkeypatch.setattr(cli.config, "get_reporter_name", lambda: "Jana")
    monkeypatch.setattr(winlaunch, "pause", lambda *a, **k: None)
    _stub_run_feedback(monkeypatch, {})
    _stub_list_issues(monkeypatch, feedbackmod.IssueListing(available=True, issues=[]))

    res = runner.invoke(cli.app, ["feedback"], input="the very first\n")
    assert res.exit_code == 0, res.output
    assert "yours would be the first" in res.output
