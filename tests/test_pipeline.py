"""One-command orchestration (`tnotes <pdf>`) — no network, no real PDF parsing.

Every API-touching or PDF-parsing stage is stubbed (the same approach the per-stage
tests use), so these assert the *orchestration*: stage ordering, output naming with
and without ``-p``, that ``--force`` re-runs finished stages, that ``--cite`` toggles
citation content, and that a single-section document still yields a book.
"""

from __future__ import annotations

import pytest
import yaml

from trustworthy_notes import pipeline, workspace
from trustworthy_notes.models import PageText


def _parse_pages(spec, max_page):
    # Mirror the CLI parser closely enough for the orchestrator's needs.
    out = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return [n for n in out if 1 <= n <= max_page]


@pytest.fixture
def stub_pipeline(monkeypatch):
    """Stub every stage that would parse a PDF or call the API. Records the order
    stages ran and whether each was reached (vs skipped), and lays down the artifact
    files the orchestrator checks for skip/force and reads downstream."""
    calls: list[str] = []

    pages = [PageText(page_index=i, page_number=i + 1, text=f"page {i}", width=1, height=1)
             for i in range(3)]
    monkeypatch.setattr(pipeline.ingest, "read_pages", lambda p: pages)

    def fake_run_extract(target, extractor, *, document, context):
        calls.append(f"extract:{target.page_number}")
        return {"statements": [{"id": "s-1"}], "evidence": [], "terms": [], "relations": []}, []

    monkeypatch.setattr(pipeline, "run_extract", fake_run_extract)
    monkeypatch.setattr(pipeline, "write_notes",
                        lambda notes, dest: dest.write_text(yaml.safe_dump(notes), encoding="utf-8"))
    monkeypatch.setattr(pipeline, "AnthropicExtractor", lambda **kw: object())

    def fake_build_store(pdf, work, **kw):
        calls.append("terms")
        return {"terms": [{"id": "t-1", "label": "x", "count": 1}], "links": {"p0:s-1": ["t-1"]}}

    monkeypatch.setattr(pipeline.term_store, "build_store", fake_build_store)

    def fake_dedup_candidates(work):
        return [[{"key": "p0:s-1", "type": "claim", "text": "a"}]]

    monkeypatch.setattr(pipeline.compose, "dedup_candidates", fake_dedup_candidates)

    def fake_adjudicate(clusters, **kw):
        calls.append("dedup")
        return [{"cluster": clusters[0], "merges": []}]

    monkeypatch.setattr(pipeline.adj, "adjudicate", fake_adjudicate)

    def fake_build_relations(pdf, work, **kw):
        calls.append("relations")
        return [{"from": "p0:s-1", "to": "p1:s-1", "type": "supports"}]

    monkeypatch.setattr(pipeline.relate, "build_relations", fake_build_relations)

    def fake_assemble(pdf, work, *, document):
        calls.append("assemble")
        cdir = workspace.compose_stage_dir(work, "chapters")
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "chapter-001.notes.yaml").write_text(
            yaml.safe_dump({"source": {"chapter_title": "The Whole Paper"}}), encoding="utf-8"
        )
        return [{"file": "chapter-001.notes.yaml", "title": "The Whole Paper",
                 "statements": 1, "evidence": 0, "terms": 1, "relations": 1}]

    monkeypatch.setattr(pipeline.compose, "assemble_document", fake_assemble)

    def fake_study(cset, **kw):
        calls.append("export")
        # Markdown carries a citation marker so --cite vs prose is observable.
        return {"markdown": "## Point\n- a claim [s-1](#note-s-1)\n", "cited": {"s-1"}, "unknown": []}

    monkeypatch.setattr(pipeline.exp, "study_document", fake_study)
    monkeypatch.setattr(pipeline.exp, "strip_citations",
                        lambda md: md.replace(" [s-1](#note-s-1)", ""))

    written_books: dict = {}

    def fake_pdf(md, out):
        calls.append("book")
        written_books["md"] = md
        out.write_text("PDF", encoding="utf-8")

    monkeypatch.setattr(pipeline.pdfmod, "markdown_to_pdf", fake_pdf)
    monkeypatch.setattr(pipeline.bookmod, "combine", lambda chapters, doc_title: "\n".join(
        f"# {t}\n{md}" for _, t, md in chapters))

    monkeypatch.setattr(pipeline.config, "resolve_model", lambda m: "test-model")
    monkeypatch.setattr(pipeline.config, "resolve_effort", lambda e: "low")
    monkeypatch.setattr(pipeline.config, "get_api_key", lambda: "test-key")

    # anthropic.Anthropic(...) is constructed in _export but never called (study stubbed).
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: object())

    return {"calls": calls, "books": written_books}


def _src(tmp_path):
    p = tmp_path / "Paper-2506.pdf"
    p.write_bytes(b"%PDF-1.4 stub")
    return p


def test_page_range_tag():
    assert pipeline.page_range_tag(None) == ""
    assert pipeline.page_range_tag("1-30") == ".p1-30"
    assert pipeline.page_range_tag("14") == ".p14"
    assert pipeline.page_range_tag("14, 16") == ".p14,16"   # whitespace stripped


def test_runs_every_stage_in_order_and_writes_book(tmp_path, stub_pipeline):
    src = _src(tmp_path)
    out = pipeline.run(src, parse_pages=_parse_pages)

    assert out == tmp_path / "Paper-2506.tnotes.pdf"
    assert out.is_file()
    order = [c for c in stub_pipeline["calls"] if not c.startswith("extract:")]
    assert order == ["terms", "dedup", "relations", "assemble", "export", "book"]
    # all 3 text pages extracted
    assert {c for c in stub_pipeline["calls"] if c.startswith("extract:")} == {
        "extract:1", "extract:2", "extract:3"}


def test_max_tokens_threads_to_extractor(tmp_path, stub_pipeline, monkeypatch):
    # #93: --max-tokens reaches AnthropicExtractor; absent → not passed (class default).
    seen = {}
    monkeypatch.setattr(pipeline, "AnthropicExtractor",
                        lambda **kw: seen.update(kw) or object())
    src = _src(tmp_path)
    pipeline.run(src, max_tokens=64000, parse_pages=_parse_pages)
    assert seen.get("max_tokens") == 64000


def test_max_tokens_absent_uses_extractor_default(tmp_path, stub_pipeline, monkeypatch):
    seen = {}
    monkeypatch.setattr(pipeline, "AnthropicExtractor",
                        lambda **kw: seen.update(kw) or object())
    src = _src(tmp_path)
    pipeline.run(src, parse_pages=_parse_pages)
    assert "max_tokens" not in seen  # None → omitted, so the extractor's own default applies


def test_default_run_writes_only_pdf_not_md(tmp_path, stub_pipeline):
    # #73: the one-command flow leaves a single book file (the PDF) beside the source.
    src = _src(tmp_path)
    out = pipeline.run(src, parse_pages=_parse_pages)
    assert out == tmp_path / "Paper-2506.tnotes.pdf"
    assert out.is_file()
    assert not (tmp_path / "Paper-2506.tnotes.md").exists()


def test_md_flag_also_writes_markdown(tmp_path, stub_pipeline):
    # #73: --md (keep_md) additionally writes the Markdown book beside the PDF.
    src = _src(tmp_path)
    out = pipeline.run(src, keep_md=True, parse_pages=_parse_pages)
    assert out.is_file()
    md = tmp_path / "Paper-2506.tnotes.md"
    assert md.is_file()
    assert md.read_text(encoding="utf-8") == stub_pipeline["books"]["md"]


def test_page_range_tags_the_output_name(tmp_path, stub_pipeline):
    src = _src(tmp_path)
    out = pipeline.run(src, pages="1-2", parse_pages=_parse_pages)
    assert out == tmp_path / "Paper-2506.p1-2.tnotes.pdf"
    assert out.is_file()
    # only the two requested pages were extracted
    assert {c for c in stub_pipeline["calls"] if c.startswith("extract:")} == {
        "extract:1", "extract:2"}


def test_resumable_skips_finished_stages_then_force_redoes(tmp_path, stub_pipeline):
    src = _src(tmp_path)
    pipeline.run(src, parse_pages=_parse_pages)
    stub_pipeline["calls"].clear()

    # Second run: extract pages already on disk, term/dedup/relation artifacts exist,
    # exported chapter exists → those API stages are skipped (assemble always re-runs).
    pipeline.run(src, parse_pages=_parse_pages)
    second = stub_pipeline["calls"]
    assert not any(c.startswith("extract:") for c in second)
    assert "terms" not in second and "dedup" not in second
    assert "relations" not in second and "export" not in second
    assert "assemble" in second and "book" in second

    stub_pipeline["calls"].clear()
    pipeline.run(src, force=True, parse_pages=_parse_pages)
    forced = stub_pipeline["calls"]
    assert any(c.startswith("extract:") for c in forced)
    for stage in ("terms", "dedup", "relations", "export"):
        assert stage in forced, stage


def test_cite_toggles_citation_content(tmp_path, stub_pipeline):
    src = _src(tmp_path)
    pipeline.run(src, cite=False, parse_pages=_parse_pages)
    prose_md = stub_pipeline["books"]["md"]
    assert "[s-1]" not in prose_md   # prose reading copy: citations stripped

    pipeline.run(src, force=True, cite=True, parse_pages=_parse_pages)
    cited_md = stub_pipeline["books"]["md"]
    assert "[s-1](#note-s-1)" in cited_md   # anchored copy keeps the markers


def test_language_flag_resolves_and_threads_to_export(tmp_path, stub_pipeline, monkeypatch):
    # #114: an explicit language is resolved on the flag>config>built-in chain and
    # carried to the reading/export stage (where #112 will consume it). We capture
    # the language _export receives by wrapping it.
    seen = {}
    real_export = pipeline._export

    def capturing_export(*args, language=None, **kw):
        seen["language"] = language
        return real_export(*args, language=language, **kw)

    monkeypatch.setattr(pipeline, "_export", capturing_export)
    src = _src(tmp_path)
    pipeline.run(src, language="cs", parse_pages=_parse_pages)
    assert seen["language"] == "cs"  # explicit flag wins


def test_language_absent_resolves_via_config_default(tmp_path, stub_pipeline, monkeypatch):
    # #114: with no flag, the resolver falls through to the configured value (here
    # stubbed to "ja"); resolution lives in pipeline.run, not the CLI edge.
    monkeypatch.setattr(pipeline.config, "resolve_language", lambda flag: flag or "ja")
    seen = {}
    real_export = pipeline._export

    def capturing_export(*args, language=None, **kw):
        seen["language"] = language
        return real_export(*args, language=language, **kw)

    monkeypatch.setattr(pipeline, "_export", capturing_export)
    src = _src(tmp_path)
    pipeline.run(src, parse_pages=_parse_pages)  # no language flag
    assert seen["language"] == "ja"  # config/default resolved inside pipeline.run


def test_single_section_document_still_yields_a_book(tmp_path, stub_pipeline):
    # The stub assemble emits exactly one section; with prose_only off (the --all
    # behaviour) it must still export and produce a book — no "0 chapters" dead-end.
    src = _src(tmp_path)
    out = pipeline.run(src, parse_pages=_parse_pages)
    assert out.is_file()
    assert "export" in stub_pipeline["calls"]
