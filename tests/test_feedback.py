"""Feedback module tests — bundle, AI-structure (+ raw-text fallback), consent,
local-file fallback, and the GitHub filing path with a mocked client.

These never touch a real repo/PAT or the network: the GitHub HTTP layer is injected
(``GitHubClient(post=..., get=...)`` or a whole stub ``github_client=``), the
AI-structure step takes an injected ``structure_client``, and the local-file
fallback is exercised for real on disk. ``now=`` is pinned for deterministic
timestamps. (Caveat: the live private-repo/PAT path cannot be exercised here — only
the mocked filing path is — see the issue's no-real-repo caveat.)
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from trustworthy_notes import feedback, workspace

_NOW = datetime(2026, 6, 18, 9, 30, 0, tzinfo=timezone.utc)


# --- helpers / fakes -----------------------------------------------------------


def _notes_dir(tmp_path: Path, doc: Path, indices: list[int]) -> None:
    """Lay down a doc's .tnotes extract dir with page-NNNN.notes.yaml files."""
    extract = workspace.extract_dir(workspace.work_dir(doc))
    extract.mkdir(parents=True, exist_ok=True)
    for i in indices:
        (extract / f"page-{i:04d}.notes.yaml").write_text(
            f"statements: [excerpt for page index {i}]\n", encoding="utf-8"
        )


def _labelled_notes_dir(doc: Path, index_to_label: dict[int, object]) -> Path:
    """Lay down notes files carrying ``source.page_label`` (the printed folio).

    Mirrors a real ``page-NNNN.notes.yaml`` shape closely enough for the locator scan:
    a top-level ``source`` block with ``page_index`` + (optional) ``page_label``. A
    label of None writes no ``page_label`` key (the nullable case). Returns the extract
    dir so a test can point the resolver at it.
    """
    extract = workspace.extract_dir(workspace.work_dir(doc))
    extract.mkdir(parents=True, exist_ok=True)
    for i, label in index_to_label.items():
        lines = ["schema_version: 1", "source:", f"  page_index: {i}", "  scope: page"]
        if label is not None:
            lines.append(f"  page_label: '{label}'")
        (extract / f"page-{i:04d}.notes.yaml").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
    return extract


def _excerpt_notes_dir(doc: Path, index_to_excerpts: dict[int, list[str]]) -> Path:
    """Lay down notes carrying ``evidence[].excerpt`` (the verbatim source quotes).

    Mirrors a real ``page-NNNN.notes.yaml`` closely enough for the #61 passage scan: a
    top-level ``evidence`` list of items each with an ``excerpt``. Returns the extract
    dir so a test can point :func:`feedback.resolve_passage` at it.
    """
    extract = workspace.extract_dir(workspace.work_dir(doc))
    extract.mkdir(parents=True, exist_ok=True)
    for i, excerpts in index_to_excerpts.items():
        data = {"evidence": [{"id": f"e{n}", "excerpt": e} for n, e in enumerate(excerpts)]}
        (extract / f"page-{i:04d}.notes.yaml").write_text(
            yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
        )
    return extract


class _FakeMessage:
    def __init__(self, text: str):
        self.content = [type("Block", (), {"type": "text", "text": text})()]


class _FakeAnthropic:
    """Stands in for ``anthropic.Anthropic`` — returns a canned JSON structure."""

    def __init__(self, payload: dict | None = None, raises: bool = False):
        self._payload = payload
        self._raises = raises
        self.messages = self

    def create(self, **_kwargs):
        if self._raises:
            raise RuntimeError("model exploded")
        return _FakeMessage(json.dumps(self._payload))


class _RecordingGitHub(feedback.GitHubClient):
    """A GitHubClient whose post/get are recorded and answered from canned data."""

    def __init__(self, token="tok"):
        self.posts: list[tuple[str, dict]] = []
        super().__init__(
            token=token,
            post=self._post,
            get=lambda url, tok: {},
        )

    def _post(self, url: str, token: str, payload: dict) -> dict:
        self.posts.append((url, payload))
        if "/contents/" in url:
            return {"content": {"html_url": "https://github.com/o/r/blob/main/bundle.zip"}}
        return {"html_url": "https://github.com/o/r/issues/7"}


# --- diagnostics ---------------------------------------------------------------


def test_capture_diagnostics_has_version_os_message_reporter():
    d = feedback.capture_diagnostics("page 12 looks wrong", "Jana")
    assert d.message == "page 12 looks wrong"
    assert d.reporter == "Jana"
    assert d.version  # build identity, non-empty
    assert d.os  # platform string, non-empty
    assert "Reported by: Jana" in d.as_text()


# --- bundle --------------------------------------------------------------------


def test_collect_bundle_all_notes_when_no_range(tmp_path):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    _notes_dir(tmp_path, doc, [0, 1, 2])
    files = feedback.collect_bundle_files(doc, None)
    assert [f.name for f in files] == ["page-0000.notes.yaml", "page-0001.notes.yaml", "page-0002.notes.yaml"]


def test_collect_bundle_restricts_to_page_range(tmp_path):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    _notes_dir(tmp_path, doc, [0, 1, 2, 3, 4])
    # 1-based pages 2-3 → 0-based indices 1,2.
    files = feedback.collect_bundle_files(doc, "2-3")
    assert [f.name for f in files] == ["page-0001.notes.yaml", "page-0002.notes.yaml"]


def test_collect_bundle_empty_when_no_doc_or_no_notes(tmp_path):
    assert feedback.collect_bundle_files(None, None) == []
    doc = tmp_path / "NoNotes.pdf"
    doc.write_text("x")
    assert feedback.collect_bundle_files(doc, None) == []


def test_write_bundle_zips_files_flat(tmp_path):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    _notes_dir(tmp_path, doc, [0, 1])
    files = feedback.collect_bundle_files(doc, None)
    dest = feedback.write_bundle(files, tmp_path / "bundle.zip")
    with zipfile.ZipFile(dest) as zf:
        assert sorted(zf.namelist()) == ["page-0000.notes.yaml", "page-0001.notes.yaml"]


# --- page locators (printed folio ↔ PDF index, ADR-006) ------------------------


def test_build_label_index_maps_printed_folio_to_indices(tmp_path):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    # An offset document: index 11 prints "1", index 12 prints "2" (10 front-matter
    # sheets); index 5 has no detected footer (nullable label).
    extract = _labelled_notes_dir(doc, {5: None, 11: "1", 12: "2"})
    index = feedback.build_label_index(extract)
    assert index == {"1": {11}, "2": {12}}  # the unlabelled page is absent


def test_printed_page_matching_one_page_resolves_to_that_index(tmp_path):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    extract = _labelled_notes_dir(doc, {11: "12", 12: "13"})
    res = feedback.resolve_printed_page(extract, "p.12")
    assert res.matched is True
    assert res.indices == {11}
    assert res.is_whole_document is False
    assert res.label == "p.12"


def test_printed_page_matching_several_pages_resolves_to_all(tmp_path):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    # A roman→arabic restart puts printed "1" on two different sheets.
    extract = _labelled_notes_dir(doc, {2: "1", 11: "1"})
    res = feedback.resolve_printed_page(extract, "1")
    assert res.matched is True
    assert res.indices == {2, 11}  # both, never silently one


def test_printed_page_matching_none_is_a_clear_miss_not_whole_doc(tmp_path):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    extract = _labelled_notes_dir(doc, {11: "12", 12: "13"})
    res = feedback.resolve_printed_page(extract, "999")
    assert res.matched is False
    assert res.indices == set()  # empty, NOT None (which would widen to whole doc)
    assert res.is_whole_document is False


def test_document_page_resolves_by_index(tmp_path):
    # 1-based page 12 → 0-based index 11; a range too.
    assert feedback.resolve_document_page("12").indices == {11}
    assert feedback.resolve_document_page("10-12").indices == {9, 10, 11}
    miss = feedback.resolve_document_page("")  # empty spec → clear miss, no widen
    assert miss.matched is False and miss.indices == set()


def test_whole_document_resolution_is_unscoped(tmp_path):
    res = feedback.resolve_whole_document()
    assert res.is_whole_document is True
    assert res.indices is None
    assert res.matched is True


def test_collect_bundle_scopes_by_resolved_indices(tmp_path):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    _notes_dir(tmp_path, doc, [0, 1, 2, 3])
    files = feedback.collect_bundle_files(doc, None, indices={1, 3})
    assert [f.name for f in files] == ["page-0001.notes.yaml", "page-0003.notes.yaml"]


def test_collect_bundle_indices_beats_pages_spec(tmp_path):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    _notes_dir(tmp_path, doc, [0, 1, 2])
    # Resolved indices win over a pages string when both are supplied.
    files = feedback.collect_bundle_files(doc, "1", indices={2})
    assert [f.name for f in files] == ["page-0002.notes.yaml"]


def test_build_label_index_skips_unreadable_and_missing_dir(tmp_path):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    extract = _labelled_notes_dir(doc, {11: "12"})
    (extract / "page-0099.notes.yaml").write_text(": not valid yaml :", encoding="utf-8")
    index = feedback.build_label_index(extract)
    assert index == {"12": {11}}  # the broken file is skipped, the scan still resolves
    assert feedback.build_label_index(tmp_path / "nope") == {}  # missing dir → empty


# --- passage locator (issue #61) -----------------------------------------------


def test_passage_matching_one_page_resolves_to_that_index(tmp_path):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    extract = _excerpt_notes_dir(
        doc,
        {
            0: ["The cat sat on the mat."],
            1: ["Something else entirely."],
        },
    )
    res = feedback.resolve_passage(extract, "the cat sat on the mat")
    assert res.matched is True
    assert res.indices == {0}


def test_passage_matching_several_pages_resolves_to_all(tmp_path):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    # The same phrase appears verbatim on two pages (e.g. a repeated epigraph).
    extract = _excerpt_notes_dir(
        doc,
        {
            2: ["A recurring motif of the work."],
            5: ["A recurring motif of the work, restated."],
            7: ["Nothing in common here."],
        },
    )
    res = feedback.resolve_passage(extract, "A recurring motif of the work")
    assert res.matched is True
    assert res.indices == {2, 5}  # all matches, never silently one


def test_passage_matching_none_is_a_clear_miss_not_whole_doc(tmp_path):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    extract = _excerpt_notes_dir(doc, {0: ["Only this text exists."]})
    res = feedback.resolve_passage(extract, "a passage that appears nowhere")
    assert res.matched is False
    assert res.indices == set()  # empty, NOT None (which would widen to whole doc)


def test_passage_match_is_whitespace_and_case_insensitive(tmp_path):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    # Stored excerpt has line breaks / double spaces; pasted text is lower-case, single-spaced.
    extract = _excerpt_notes_dir(doc, {3: ["The   quick brown\nfox  jumps."]})
    res = feedback.resolve_passage(extract, "the quick brown fox jumps.")
    assert res.matched is True
    assert res.indices == {3}


def test_passage_match_either_direction(tmp_path):
    """A pasted span longer than any single excerpt still matches when an excerpt is a
    substring of it (the user pasted more than one stored quote's worth)."""
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    extract = _excerpt_notes_dir(doc, {4: ["jumps over the lazy dog"]})
    res = feedback.resolve_passage(extract, "the quick brown fox jumps over the lazy dog today")
    assert res.matched is True
    assert res.indices == {4}


def test_passage_blank_matches_nothing(tmp_path):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    extract = _excerpt_notes_dir(doc, {0: ["Some text."]})
    res = feedback.resolve_passage(extract, "   ")
    assert res.matched is False
    assert res.indices == set()  # a blank passage must not match every page


def test_passage_skips_unreadable_and_missing_dir(tmp_path):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    extract = _excerpt_notes_dir(doc, {0: ["findable passage"]})
    (extract / "page-0099.notes.yaml").write_text(": not valid yaml :", encoding="utf-8")
    res = feedback.resolve_passage(extract, "findable passage")
    assert res.indices == {0}  # the broken file is skipped, the scan still resolves
    miss = feedback.resolve_passage(tmp_path / "nope", "anything")
    assert miss.matched is False and miss.indices == set()  # missing dir → clear miss


# --- AI structuring + raw-text fallback ----------------------------------------


def test_structure_report_ai_path():
    d = feedback.capture_diagnostics("page 12 wrong", "Jana")
    client = _FakeAnthropic({"title": "Page 12 export wrong", "body": "## Summary\nIt's wrong."})
    report = feedback.structure_report(d, model="m", api_key="sk", client=client)
    assert report.ai_structured is True
    assert report.title == "Page 12 export wrong"
    assert "## Summary" in report.body
    # Attribution + diagnostics are always re-attached verbatim.
    assert "Reported by: Jana" in report.body


def test_structure_report_falls_back_when_no_key():
    d = feedback.capture_diagnostics("page 12 wrong", "Jana")
    report = feedback.structure_report(d, model="m", api_key=None)
    assert report.ai_structured is False
    assert "page 12 wrong" in report.body
    assert "Reported by: Jana" in report.body


def test_structure_report_falls_back_when_model_raises():
    d = feedback.capture_diagnostics("boom", "Jana")
    report = feedback.structure_report(d, model="m", api_key="sk", client=_FakeAnthropic(raises=True))
    assert report.ai_structured is False
    assert "boom" in report.body


def test_structure_report_falls_back_on_unparseable_response():
    d = feedback.capture_diagnostics("boom", "Jana")
    client = _FakeAnthropic()
    client._payload = "not json"  # create() will json.dumps a bare string → not a dict
    report = feedback.structure_report(d, model="m", api_key="sk", client=client)
    assert report.ai_structured is False


# --- GitHub filing (mocked client) ---------------------------------------------


def test_file_issue_commits_bundle_and_returns_url(tmp_path):
    report = feedback.StructuredReport(title="T", body="B", ai_structured=True)
    bundle = tmp_path / "b.zip"
    bundle.write_bytes(b"PK\x03\x04zip")
    gh = _RecordingGitHub()
    url = feedback.file_issue(report, "o/r", gh, bundle=bundle, now=_NOW)
    assert url == "https://github.com/o/r/issues/7"
    # Two POSTs: contents (bundle) then issue; bundle link is in the issue body.
    assert any("/contents/" in u for u, _ in gh.posts)
    issue_payload = next(p for u, p in gh.posts if u.endswith("/issues"))
    assert "Reproduction bundle:" in issue_payload["body"]


def test_file_issue_without_bundle_only_posts_issue():
    report = feedback.StructuredReport(title="T", body="B", ai_structured=True)
    gh = _RecordingGitHub()
    url = feedback.file_issue(report, "o/r", gh, bundle=None, now=_NOW)
    assert url == "https://github.com/o/r/issues/7"
    assert all("/contents/" not in u for u, _ in gh.posts)


class _LabelRecordingGitHub(feedback.GitHubClient):
    """A client whose issue-create returns a number, so the reporter-label path runs.

    ``fail_labels`` makes every ``/labels`` POST raise, to prove a label failure
    never breaks a filed report.
    """

    def __init__(self, fail_labels: bool = False):
        self.posts: list[tuple[str, dict]] = []
        self._fail_labels = fail_labels
        super().__init__(token="tok", post=self._post, get=lambda url, tok: [])

    def _post(self, url: str, token: str, payload: dict) -> dict:
        self.posts.append((url, payload))
        if "/labels" in url:
            if self._fail_labels:
                raise feedback.FeedbackError("label boom")
            return {}
        return {"html_url": "https://github.com/o/r/issues/9", "number": 9}


def test_file_issue_prefixes_title_with_reporter():
    report = feedback.StructuredReport(title="export looks blank", body="B", ai_structured=True)
    gh = _RecordingGitHub()
    feedback.file_issue(report, "o/r", gh, reporter="Ales Test", now=_NOW)
    issue_payload = next(p for u, p in gh.posts if u.endswith("/issues"))
    assert issue_payload["title"] == "[Ales Test] export looks blank"


def test_file_issue_without_reporter_keeps_bare_title():
    report = feedback.StructuredReport(title="T", body="B", ai_structured=True)
    gh = _RecordingGitHub()
    feedback.file_issue(report, "o/r", gh, now=_NOW)
    issue_payload = next(p for u, p in gh.posts if u.endswith("/issues"))
    assert issue_payload["title"] == "T"


def test_file_issue_applies_reporter_label():
    report = feedback.StructuredReport(title="T", body="B", ai_structured=True)
    gh = _LabelRecordingGitHub()
    url = feedback.file_issue(report, "o/r", gh, reporter="Ales Test", now=_NOW)
    assert url == "https://github.com/o/r/issues/9"
    # The label is created (slugged) and added to the just-filed issue.
    assert any(u.endswith("/labels") and p.get("name") == "reporter:ales-test" for u, p in gh.posts)
    assert any(
        u.endswith("/issues/9/labels") and p.get("labels") == ["reporter:ales-test"]
        for u, p in gh.posts
    )


def test_file_issue_label_failure_does_not_break_filing():
    report = feedback.StructuredReport(title="T", body="B", ai_structured=True)
    gh = _LabelRecordingGitHub(fail_labels=True)
    # A label step that blows up must not lose the report — the issue already filed.
    url = feedback.file_issue(report, "o/r", gh, reporter="Ada", now=_NOW)
    assert url == "https://github.com/o/r/issues/9"


def test_urllib_request_401_raises_feedback_error_with_expired_hint(monkeypatch):
    import urllib.error
    import urllib.request

    def raise_401(*_a, **_k):
        raise urllib.error.HTTPError("u", 401, "unauth", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", raise_401)
    # A 401 (missing/expired token) must surface as FeedbackError mentioning expiry,
    # so the caller falls back locally with a 'ping the maintainer' reason.
    with pytest.raises(feedback.FeedbackError, match="expired"):
        feedback._urllib_request("https://x", "tok", method="POST", payload={})


def test_urllib_request_offline_raises_feedback_error(monkeypatch):
    import urllib.request

    def raise_offline(*_a, **_k):
        raise OSError("Network is unreachable")

    monkeypatch.setattr(urllib.request, "urlopen", raise_offline)
    with pytest.raises(feedback.FeedbackError, match="could not reach"):
        feedback._urllib_request("https://x", "tok", method="GET", payload=None)


# --- local-file fallback -------------------------------------------------------


def test_write_local_fallback_writes_report_and_points_at_bundle(tmp_path):
    d = feedback.capture_diagnostics("msg", "Jana")
    report = feedback.StructuredReport(title="Title", body="Body here", ai_structured=False)
    bundle = tmp_path / "b.zip"
    bundle.write_bytes(b"zip")
    dest = feedback.write_local_fallback(report, d, bundle, tmp_path, now=_NOW)
    assert dest.name == "feedback-20260618-093000.txt"
    text = dest.read_text(encoding="utf-8")
    assert "Title" in text and "Body here" in text
    assert str(bundle) in text


# --- orchestration: every off-ramp lands on the local file ---------------------


def _run(tmp_path, monkeypatch, **overrides):
    """Run run_feedback with safe defaults; overrides tune one off-ramp at a time."""
    doc = overrides.pop("doc", None)
    kwargs = dict(
        reporter="Jana",
        doc=doc,
        pages=overrides.pop("pages", None),
        model="m",
        api_key=None,  # raw-text fallback by default (no network)
        repo=overrides.pop("repo", None),
        token=overrides.pop("token", None),
        fallback_dir=tmp_path,
        confirm=overrides.pop("confirm", lambda _p: True),
        log=lambda _m: None,
        github_client=overrides.pop("github_client", None),
        now=_NOW,
    )
    kwargs.update(overrides)
    return feedback.run_feedback("page 12 wrong", **kwargs)


def test_run_unconfigured_writes_local_file(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch)  # no repo/token
    assert out.filed is False
    assert "no feedback repo/token configured" in out.reason
    assert Path(out.location).is_file()


def test_run_consent_no_writes_local_file(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, repo="o/r", token="tok", confirm=lambda _p: False)
    assert out.filed is False
    assert out.reason == "upload declined"
    assert Path(out.location).is_file()


def test_run_offline_or_401_writes_local_file(tmp_path, monkeypatch):
    class _Offline(feedback.GitHubClient):
        def __init__(self):
            super().__init__(token="tok",
                             post=lambda *a: (_ for _ in ()).throw(feedback.FeedbackError("401 expired")),
                             get=lambda *a: {})

    out = _run(tmp_path, monkeypatch, repo="o/r", token="tok", github_client=_Offline())
    assert out.filed is False
    assert "401" in out.reason
    assert Path(out.location).is_file()


def test_run_happy_path_files_issue_with_mocked_github(tmp_path, monkeypatch):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    _notes_dir(tmp_path, doc, [11])  # 0-based index 11 == page 12
    gh = _RecordingGitHub()
    out = _run(tmp_path, monkeypatch, doc=doc, pages="12", repo="o/r", token="tok", github_client=gh)
    assert out.filed is True
    assert out.location == "https://github.com/o/r/issues/7"
    # Consent was granted and the bundle was committed (contents POST happened).
    assert any("/contents/" in u for u, _ in gh.posts)


def test_run_consent_preview_reflects_resolved_page_indices(tmp_path, monkeypatch):
    """The file list the user consents to is the resolved scope, not the raw doc.

    Pre-resolved ``page_indices`` (what the windowless picker hands in) must scope the
    bundle BEFORE the consent preview, so the preview names exactly the pages going up
    (ADR-003). Here the doc has four pages but only index 2 is scoped.
    """
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    _notes_dir(tmp_path, doc, [0, 1, 2, 3])
    seen_preview: dict = {}

    def confirm(preview: str) -> bool:
        seen_preview["text"] = preview
        return False  # decline → local fallback (we only care about the preview)

    _run(tmp_path, monkeypatch, doc=doc, page_indices={2}, repo="o/r", token="tok", confirm=confirm)
    preview = seen_preview["text"]
    assert "page-0002.notes.yaml" in preview
    assert "page-0000.notes.yaml" not in preview
    assert "page-0003.notes.yaml" not in preview


def test_feedback_module_does_not_import_the_pipeline():
    """ADR-003/ADR-006 isolation: feedback reads artifacts, never imports the pipeline.

    The locator resolution must scan ``.tnotes`` with an inline ``yaml.safe_load``, not
    by calling back into ``compose``/``ingest``/``extract``/``normalize`` — doing so
    would invert the ``cli → feedback`` dependency arrow.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(feedback))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[-1])
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[-1])
    assert imported.isdisjoint({"compose", "ingest", "extract", "normalize"})


def test_run_consent_preview_lists_bundle_files(tmp_path, monkeypatch):
    doc = tmp_path / "Doc.pdf"
    doc.write_text("x")
    _notes_dir(tmp_path, doc, [11])
    seen: dict = {}

    def capture_confirm(preview: str) -> bool:
        seen["preview"] = preview
        return False  # decline so we don't file

    _run(tmp_path, monkeypatch, doc=doc, pages="12", repo="o/r", token="tok", confirm=capture_confirm)
    # The preview must disclose the verbatim-excerpt bundle file by name + warn.
    assert "page-0011.notes.yaml" in seen["preview"]
    assert "VERBATIM" in seen["preview"]


# --- listing existing issues (read-only inbound, issue #41) ---------------------


def _github_with_get(payload, *, raises: bool = False):
    """A GitHubClient whose injected get returns ``payload`` (or raises FeedbackError)."""
    def _get(url, tok):
        if raises:
            raise feedback.FeedbackError("could not reach the feedback repo: offline")
        return payload
    return feedback.GitHubClient(token="tok", get=_get)


def test_list_recent_issues_parses_get():
    gh = _github_with_get([
        {"number": 7, "title": "export looks blank", "state": "open"},
        {"number": 4, "title": "page 3 garbled", "state": "open"},
    ])
    listing = feedback.list_recent_issues("o/r", "tok", github_client=gh)
    assert listing.available is True
    assert [(i.number, i.title, i.state) for i in listing.issues] == [
        (7, "export looks blank", "open"),
        (4, "page 3 garbled", "open"),
    ]


def test_list_recent_issues_skips_pull_requests():
    gh = _github_with_get([
        {"number": 9, "title": "a real report", "state": "open"},
        {"number": 8, "title": "a PR not a report", "state": "open", "pull_request": {"url": "x"}},
    ])
    listing = feedback.list_recent_issues("o/r", "tok", github_client=gh)
    assert [i.number for i in listing.issues] == [9]


def test_list_recent_issues_unconfigured_is_unavailable():
    assert feedback.list_recent_issues(None, "tok").available is False
    assert feedback.list_recent_issues("o/r", None).available is False


def test_list_recent_issues_get_raising_is_unavailable_not_raised():
    gh = _github_with_get(None, raises=True)
    listing = feedback.list_recent_issues("o/r", "tok", github_client=gh)
    assert listing.available is False
    assert "offline" in listing.reason


def test_list_recent_issues_unexpected_shape_is_unavailable():
    gh = _github_with_get({"message": "Not Found"})  # a dict, not the expected array
    listing = feedback.list_recent_issues("o/r", "tok", github_client=gh)
    assert listing.available is False
