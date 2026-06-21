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

from trustworthy_notes import cli, feedback as feedbackmod, onboarding, winlaunch, workspace

runner = CliRunner()


def _doc_with_labelled_notes(tmp_path: Path, index_to_label: dict) -> Path:
    """A PDF whose .tnotes extract dir carries page_label-bearing notes (#60 picker)."""
    pdf = tmp_path / "Dropped.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    extract = workspace.extract_dir(workspace.work_dir(pdf))
    extract.mkdir(parents=True, exist_ok=True)
    for i, label in index_to_label.items():
        body = ["schema_version: 1", "source:", f"  page_index: {i}", "  scope: page"]
        if label is not None:
            body.append(f"  page_label: '{label}'")
        (extract / f"page-{i:04d}.notes.yaml").write_text("\n".join(body) + "\n", encoding="utf-8")
    return pdf


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

    # A dropped doc now shows the page-scope picker (#60) before the message prompt;
    # an empty choice (just Enter) means "the whole document", then the message.
    res = runner.invoke(cli.app, ["feedback", str(pdf)], input="\npage 7 wrong\n")
    assert res.exit_code == 0, res.output
    assert seen["doc"] == pdf
    assert seen["message"] == "page 7 wrong"
    assert seen["page_indices"] is None  # whole document
    assert "Dropped.pdf" in res.output  # confirmed the dropped doc to the user
    assert "How do you want to point at the problem?" in res.output


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


# --- windowless page-scope picker (issue #60) ------------------------------------


def _windowless_doc_flow(monkeypatch):
    """Common windowless setup for a dropped-doc picker test."""
    _no_startup_nudge(monkeypatch)
    _windowless(monkeypatch, True)
    monkeypatch.setattr(cli.config, "auth_source", lambda: "config")
    monkeypatch.setattr(cli.config, "get_reporter_name", lambda: "Jana")
    monkeypatch.setattr(winlaunch, "pause", lambda *a, **k: None)
    _stub_list_issues(monkeypatch)


def test_picker_printed_folio_scopes_bundle(tmp_path, monkeypatch):
    _windowless_doc_flow(monkeypatch)
    # Offset doc: printed "12" lives on PDF index 11.
    pdf = _doc_with_labelled_notes(tmp_path, {10: "11", 11: "12", 12: "13"})
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    # Choose [1] printed folio, type "p.12", then the message.
    res = runner.invoke(cli.app, ["feedback", str(pdf)], input="1\np.12\nthis page is wrong\n")
    assert res.exit_code == 0, res.output
    assert seen["page_indices"] == {11}  # resolved to the PDF index, not the literal 12
    assert seen["message"] == "this page is wrong"


def test_picker_document_page_scopes_by_index(tmp_path, monkeypatch):
    _windowless_doc_flow(monkeypatch)
    pdf = _doc_with_labelled_notes(tmp_path, {10: "11", 11: "12"})
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    # Choose [2] document page, type "12" → 1-based page 12 → 0-based index 11.
    res = runner.invoke(cli.app, ["feedback", str(pdf)], input="2\n12\nwrong\n")
    assert res.exit_code == 0, res.output
    assert seen["page_indices"] == {11}


def test_picker_enter_means_whole_document(tmp_path, monkeypatch):
    _windowless_doc_flow(monkeypatch)
    pdf = _doc_with_labelled_notes(tmp_path, {11: "12"})
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    res = runner.invoke(cli.app, ["feedback", str(pdf)], input="\nwhole thing\n")
    assert res.exit_code == 0, res.output
    assert seen["page_indices"] is None  # unscoped


def test_picker_no_match_then_fall_back_to_whole_document(tmp_path, monkeypatch):
    _windowless_doc_flow(monkeypatch)
    pdf = _doc_with_labelled_notes(tmp_path, {11: "12"})
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    # Printed "999" matches nothing → told clearly, then say yes to whole-doc fallback.
    res = runner.invoke(cli.app, ["feedback", str(pdf)], input="1\n999\ny\nmsg\n")
    assert res.exit_code == 0, res.output
    assert "No page matches p.999" in res.output
    assert seen["page_indices"] is None  # explicit fall back, never silently widened


def test_picker_no_match_then_re_enter_a_valid_folio(tmp_path, monkeypatch):
    _windowless_doc_flow(monkeypatch)
    pdf = _doc_with_labelled_notes(tmp_path, {11: "12"})
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    # Miss "999", decline the whole-doc fallback (n), back to the menu, pick "12".
    res = runner.invoke(cli.app, ["feedback", str(pdf)], input="1\n999\nn\n1\n12\nmsg\n")
    assert res.exit_code == 0, res.output
    assert "No page matches p.999" in res.output
    assert seen["page_indices"] == {11}


def test_picker_skipped_when_no_doc(tmp_path, monkeypatch):
    _windowless_doc_flow(monkeypatch)
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    res = runner.invoke(cli.app, ["feedback"], input="general gripe\n")
    assert res.exit_code == 0, res.output
    assert "How do you want to point at the problem?" not in res.output
    assert seen["page_indices"] is None


def test_picker_skipped_when_pages_flag_given(tmp_path, monkeypatch):
    _windowless_doc_flow(monkeypatch)
    pdf = _doc_with_labelled_notes(tmp_path, {11: "12"})
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    # An explicit -p scopes directly; the windowless picker is bypassed.
    res = runner.invoke(cli.app, ["feedback", str(pdf), "-p", "12"], input="msg\n")
    assert res.exit_code == 0, res.output
    assert "How do you want to point at the problem?" not in res.output
    assert seen["pages"] == "12"
    assert seen["page_indices"] is None


def test_windowless_consent_preview_reflects_resolved_pages(tmp_path, monkeypatch):
    """End-to-end windowless: pick a printed folio, then the REAL run_feedback builds
    the consent preview from the resolved scope (not a stub) — it names only that page.
    """
    _windowless_doc_flow(monkeypatch)
    monkeypatch.setattr(cli.config, "get_feedback_repo", lambda: "o/r")
    monkeypatch.setattr(cli.config, "get_feedback_token", lambda: "tok")
    monkeypatch.setattr(cli.config, "resolve_model", lambda _m: "model")
    monkeypatch.setattr(cli.config, "get_api_key", lambda: None)  # raw-text, no network
    pdf = _doc_with_labelled_notes(tmp_path, {10: "11", 11: "12", 12: "13"})

    # Pick [1] p.12 → index 11; at the consent gate, decline (n) so nothing uploads.
    res = runner.invoke(cli.app, ["feedback", str(pdf)], input="1\np.12\nbad page\nn\n")
    assert res.exit_code == 0, res.output
    assert "page-0011.notes.yaml" in res.output  # the resolved page is in the preview
    assert "page-0010.notes.yaml" not in res.output
    assert "page-0012.notes.yaml" not in res.output


# --- windowless passage picker (issue #61) ---------------------------------------


def _doc_with_excerpt_notes(tmp_path: Path, index_to_excerpts: dict) -> Path:
    """A PDF whose .tnotes notes carry ``evidence[].excerpt`` (the #61 passage scan)."""
    import yaml

    pdf = tmp_path / "Dropped.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    extract = workspace.extract_dir(workspace.work_dir(pdf))
    extract.mkdir(parents=True, exist_ok=True)
    for i, excerpts in index_to_excerpts.items():
        data = {"evidence": [{"id": f"e{n}", "excerpt": e} for n, e in enumerate(excerpts)]}
        (extract / f"page-{i:04d}.notes.yaml").write_text(
            yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
        )
    return pdf


def test_picker_passage_match_scopes_bundle_and_quotes_in_report(tmp_path, monkeypatch):
    _windowless_doc_flow(monkeypatch)
    pdf = _doc_with_excerpt_notes(
        tmp_path, {10: ["The verdict was read aloud."], 11: ["Other content."]}
    )
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    # Choose [3] paste a passage, paste a phrase that lives on index 10, then the message.
    res = runner.invoke(
        cli.app,
        ["feedback", str(pdf)],
        input="3\nThe verdict was read aloud.\nthis quote is mangled\n",
    )
    assert res.exit_code == 0, res.output
    assert seen["page_indices"] == {10}  # scoped to the matching page
    # The pasted passage reaches the report body even though it matched a page.
    assert "this quote is mangled" in seen["message"]
    assert "The verdict was read aloud." in seen["message"]


def test_picker_passage_no_match_falls_back_to_whole_doc_with_message(tmp_path, monkeypatch):
    _windowless_doc_flow(monkeypatch)
    pdf = _doc_with_excerpt_notes(tmp_path, {10: ["Only this exists."]})
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    # Paste a passage that matches nothing → told clearly, say yes to whole-doc fallback.
    res = runner.invoke(
        cli.app,
        ["feedback", str(pdf)],
        input="3\na passage found nowhere\ny\nmsg\n",
    )
    assert res.exit_code == 0, res.output
    assert "No page matches pasted passage" in res.output
    assert "still be included in the report" in res.output  # never silent
    assert seen["page_indices"] is None  # explicit fall back, never silently widened
    # The passage is STILL in the report so the maintainer can find it by hand.
    assert "a passage found nowhere" in seen["message"]


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


# --- dragging the generated book (issue #62) -------------------------------------
#
# A user reports against the book she is reading by dragging <name>.tnotes.pdf onto
# Send Feedback. The book name dropped the source extension (pipeline.book_path uses
# input_path.stem), so the cli resolves the SOURCE's `.tnotes` notes dir by its sibling
# and threads it through as `notes_dir` — the source-PDF drag is unchanged.


def _source_with_book(tmp_path: Path, *, stem="Foo", ext=".pdf", pages_tag="", index_to_label=None):
    """A source PDF + its populated `<source>.tnotes` notes dir + the generated book.

    Mirrors the real layout: notes live in ``<stem><ext>.tnotes`` (work_dir of the
    source), while the book beside them is ``<stem>[.pRANGE].tnotes.pdf`` (book_path,
    which dropped the source extension). Returns ``(source, book)``.
    """
    source = tmp_path / f"{stem}{ext}"
    source.write_bytes(b"%PDF-1.4 stub")
    extract = workspace.extract_dir(workspace.work_dir(source))
    extract.mkdir(parents=True, exist_ok=True)
    for i, label in (index_to_label or {11: "12"}).items():
        body = ["schema_version: 1", "source:", f"  page_index: {i}", "  scope: page"]
        if label is not None:
            body.append(f"  page_label: '{label}'")
        (extract / f"page-{i:04d}.notes.yaml").write_text("\n".join(body) + "\n", encoding="utf-8")
    book = tmp_path / f"{stem}{pages_tag}.tnotes.pdf"
    book.write_bytes(b"%PDF-1.4 book")
    return source, book


# --- unit: book → notes-dir resolution at the cli edge ---------------------------


def test_resolve_book_to_notes_dir_finds_sibling(tmp_path):
    source, book = _source_with_book(tmp_path)
    resolved = cli._resolve_book_to_notes_dir(book)
    assert resolved == workspace.work_dir(source)  # Foo.pdf.tnotes


def test_resolve_book_with_page_range_tag(tmp_path):
    source, book = _source_with_book(tmp_path, pages_tag=".p1-30")
    # Book Foo.p1-30.tnotes.pdf still resolves to Foo.pdf.tnotes (the tag is stripped).
    assert cli._resolve_book_to_notes_dir(book) == workspace.work_dir(source)


def test_resolve_book_no_sibling_raises_clear(tmp_path):
    book = tmp_path / "Foo.tnotes.pdf"
    book.write_bytes(b"%PDF-1.4 book")  # no Foo*.tnotes dir beside it
    try:
        cli._resolve_book_to_notes_dir(book)
        assert False, "expected BookNotesNotFound"
    except cli.BookNotesNotFound as exc:
        assert "couldn't find the notes" in str(exc)


def test_resolve_book_ambiguous_prefers_exact_extension_shape(tmp_path):
    # Same title as both .pdf and .epub → two siblings sharing the "Foo" prefix.
    for ext in (".pdf", ".epub"):
        (workspace.work_dir(tmp_path / f"Foo{ext}")).mkdir(parents=True)
    # Add a decoy that is NOT the exact <stem>.<ext>.tnotes shape (extra dot segment).
    (tmp_path / "Foo.draft.v2.tnotes").mkdir()
    book = tmp_path / "Foo.tnotes.pdf"
    book.write_bytes(b"%PDF-1.4 book")
    try:
        cli._resolve_book_to_notes_dir(book)
        assert False, "expected BookNotesNotFound on a genuine tie"
    except cli.BookNotesNotFound as exc:
        assert "several possible notes folders" in str(exc)


def test_is_generated_book_only_for_tnotes_pdf(tmp_path):
    assert cli._is_generated_book(Path("Foo.tnotes.pdf"))
    assert cli._is_generated_book(Path("Foo.p1-30.tnotes.pdf"))
    assert not cli._is_generated_book(Path("Foo.pdf"))  # source PDF
    assert not cli._is_generated_book(Path("Foo.tnotes.md"))


# --- integration: a dragged book flows the resolved notes through ----------------


def test_windowless_dragged_book_resolves_notes_into_run(tmp_path, monkeypatch):
    """Drag the BOOK: the resolved source notes dir reaches run_feedback as notes_dir."""
    _windowless_doc_flow(monkeypatch)
    source, book = _source_with_book(tmp_path, index_to_label={10: "11", 11: "12"})
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    # Drag the book, press Enter for the whole document, then the message.
    res = runner.invoke(cli.app, ["feedback", str(book)], input="\nbook looks off\n")
    assert res.exit_code == 0, res.output
    assert seen["doc"] == book  # the dragged path stays as doc
    assert seen["notes_dir"] == workspace.work_dir(source)  # but notes come from the source
    assert seen["message"] == "book looks off"


def test_windowless_dragged_book_picker_reads_resolved_notes(tmp_path, monkeypatch):
    """The page picker scans the RESOLVED notes dir: a printed folio resolves there."""
    _windowless_doc_flow(monkeypatch)
    _, book = _source_with_book(tmp_path, index_to_label={10: "11", 11: "12", 12: "13"})
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    # [1] printed folio "12" → PDF index 11, scanned from the source notes, not <book>.tnotes.
    res = runner.invoke(cli.app, ["feedback", str(book)], input="1\np.12\nthis page\n")
    assert res.exit_code == 0, res.output
    assert seen["page_indices"] == {11}


def test_windowless_dragged_book_consent_preview_from_resolved_notes(tmp_path, monkeypatch):
    """End-to-end with the REAL run_feedback: the consent preview lists the source notes."""
    _windowless_doc_flow(monkeypatch)
    monkeypatch.setattr(cli.config, "get_feedback_repo", lambda: "o/r")
    monkeypatch.setattr(cli.config, "get_feedback_token", lambda: "tok")
    monkeypatch.setattr(cli.config, "resolve_model", lambda _m: "model")
    monkeypatch.setattr(cli.config, "get_api_key", lambda: None)  # raw-text, no network
    _, book = _source_with_book(tmp_path, index_to_label={10: "11", 11: "12", 12: "13"})

    # Pick p.12 → index 11; decline at the consent gate so nothing uploads.
    res = runner.invoke(cli.app, ["feedback", str(book)], input="1\np.12\nbad page\nn\n")
    assert res.exit_code == 0, res.output
    assert "page-0011.notes.yaml" in res.output  # from the resolved source notes dir
    assert "page-0010.notes.yaml" not in res.output


def test_windowless_dragged_book_no_notes_is_clear_not_empty(tmp_path, monkeypatch):
    """A book with no sibling notes dir is a hard stop — never a silent empty bundle."""
    _windowless_doc_flow(monkeypatch)
    book = tmp_path / "Orphan.tnotes.pdf"
    book.write_bytes(b"%PDF-1.4 book")  # no Orphan*.tnotes beside it
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    res = runner.invoke(cli.app, ["feedback", str(book)])
    assert res.exit_code == 1
    assert "couldn't find the notes" in res.output
    assert seen == {}  # never reached run_feedback


def test_source_pdf_drag_unchanged_no_resolution(tmp_path, monkeypatch):
    """Dragging the SOURCE PDF still works: no .tnotes.pdf suffix → no notes_dir override."""
    _windowless_doc_flow(monkeypatch)
    source, _ = _source_with_book(tmp_path)
    seen: dict = {}
    _stub_run_feedback(monkeypatch, seen)

    res = runner.invoke(cli.app, ["feedback", str(source)], input="\nsource drag\n")
    assert res.exit_code == 0, res.output
    assert seen["doc"] == source
    assert seen["notes_dir"] is None  # current behaviour: doc's own work dir resolves notes
