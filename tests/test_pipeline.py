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


def test_export_forwards_language_to_study_document(tmp_path, stub_pipeline, monkeypatch):
    # #112: _export must hand the resolved language to export.study_document (the call
    # that synthesizes the reader prose), not just accept it.
    seen = {}

    def capturing_study(cset, **kw):
        seen.update(kw)
        return {"markdown": "## P\n- a [s-1](#note-s-1)\n", "cited": {"s-1"}, "unknown": []}

    monkeypatch.setattr(pipeline.exp, "study_document", capturing_study)
    src = _src(tmp_path)
    pipeline.run(src, language="cs", parse_pages=_parse_pages)
    assert seen["language"] == "cs"


def test_language_absent_with_unknown_source_is_native(tmp_path, stub_pipeline, monkeypatch):
    # #115: with no flag, the preferred language still resolves via config (here "ja"),
    # but the advisory gate runs. The stub notes carry no detected_language → the source
    # rolls up to "unknown", so without an explicit flag the gate declines and export
    # gets native (None), never a guessed translation.
    monkeypatch.setattr(pipeline.config, "resolve_language", lambda flag: flag or "ja")
    seen = {}
    real_export = pipeline._export

    def capturing_export(*args, language=None, **kw):
        seen["language"] = language
        return real_export(*args, language=language, **kw)

    monkeypatch.setattr(pipeline, "_export", capturing_export)
    src = _src(tmp_path)
    pipeline.run(src, parse_pages=_parse_pages)  # no language flag
    assert seen["language"] is None  # unknown source + no flag → native, no guessing


# ---- the advisory translate gate (issue #115, ADR-008) ----


def _yes(detected, preferred):
    return True


def _no(detected, preferred):
    return False


def test_gate_match_no_prompt_native():
    # source already in the preferred language → native, confirm never consulted.
    calls = []
    out = pipeline.resolve_translation(
        detected="cs", preferred="cs", explicit=False,
        confirm=lambda d, p: calls.append((d, p)) or True,
    )
    assert out is None
    assert calls == []  # no prompt


def test_gate_explicit_language_translates_without_prompting():
    calls = []
    out = pipeline.resolve_translation(
        detected="cs", preferred="en", explicit=True,
        confirm=lambda d, p: calls.append((d, p)) or True,
    )
    assert out == "en"  # the flag is the decision
    assert calls == []  # never asked


def test_gate_differ_confirm_yes_translates():
    out = pipeline.resolve_translation(
        detected="cs", preferred="en", explicit=False, confirm=_yes,
    )
    assert out == "en"


def test_gate_differ_confirm_no_is_native():
    out = pipeline.resolve_translation(
        detected="cs", preferred="en", explicit=False, confirm=_no,
    )
    assert out is None


def test_gate_unknown_or_mixed_source_does_not_prompt():
    calls = []
    record = lambda d, p: calls.append((d, p)) or True
    assert pipeline.resolve_translation(
        detected="unknown", preferred="en", explicit=False, confirm=record) is None
    assert pipeline.resolve_translation(
        detected="mixed", preferred="cs", explicit=False, confirm=record) is None
    assert calls == []  # never offered on a guess


def test_gate_unknown_source_with_explicit_flag_still_translates():
    # An explicit --language is the decision even when the source language is unclear.
    out = pipeline.resolve_translation(
        detected="unknown", preferred="cs", explicit=True, confirm=_no,
    )
    assert out == "cs"


def _stub_detected(monkeypatch, language):
    """Make the per-page extraction stamp `language` on every page's notes, so the
    gate's roll-up sees it through the real load_page_sets path."""
    def fake_run_extract(target, extractor, *, document, context):
        notes = {"statements": [{"id": "s-1"}], "evidence": [], "terms": [], "relations": []}
        if language is not None:
            notes["detected_language"] = language
        return notes, []
    monkeypatch.setattr(pipeline, "run_extract", fake_run_extract)


def test_gate_through_pipeline_confirm_yes_passes_language_to_export(
    tmp_path, stub_pipeline, monkeypatch
):
    # detected (cs) ≠ preferred (en): confirm fires, Yes → "en" reaches _export.
    monkeypatch.setattr(pipeline.config, "resolve_language", lambda flag: flag or "en")
    _stub_detected(monkeypatch, "cs")
    seen = {}
    real_export = pipeline._export
    monkeypatch.setattr(pipeline, "_export",
                        lambda *a, language=None, **k: seen.update(language=language)
                        or real_export(*a, language=language, **k))
    asked = []
    pipeline.run(_src(tmp_path), parse_pages=_parse_pages,
                 confirm_translation=lambda d, p: asked.append((d, p)) or True)
    assert asked == [("cs", "en")]      # the gate offered cs→en
    assert seen["language"] == "en"     # Yes → translation language to export


def test_gate_through_pipeline_confirm_no_is_native(tmp_path, stub_pipeline, monkeypatch):
    monkeypatch.setattr(pipeline.config, "resolve_language", lambda flag: flag or "en")
    _stub_detected(monkeypatch, "cs")
    seen = {}
    real_export = pipeline._export
    monkeypatch.setattr(pipeline, "_export",
                        lambda *a, language=None, **k: seen.update(language=language)
                        or real_export(*a, language=language, **k))
    pipeline.run(_src(tmp_path), parse_pages=_parse_pages,
                 confirm_translation=lambda d, p: False)
    assert seen["language"] is None     # decline → native


def test_gate_through_pipeline_match_does_not_prompt(tmp_path, stub_pipeline, monkeypatch):
    monkeypatch.setattr(pipeline.config, "resolve_language", lambda flag: flag or "cs")
    _stub_detected(monkeypatch, "cs")  # source == preferred
    asked = []
    seen = {}
    real_export = pipeline._export
    monkeypatch.setattr(pipeline, "_export",
                        lambda *a, language=None, **k: seen.update(language=language)
                        or real_export(*a, language=language, **k))
    pipeline.run(_src(tmp_path), parse_pages=_parse_pages,
                 confirm_translation=lambda d, p: asked.append((d, p)) or True)
    assert asked == []                  # match → no prompt
    assert seen["language"] is None     # no translation


def test_gate_through_pipeline_explicit_flag_translates_without_prompt(
    tmp_path, stub_pipeline, monkeypatch
):
    monkeypatch.setattr(pipeline.config, "resolve_language", lambda flag: flag or "en")
    _stub_detected(monkeypatch, "cs")
    asked = []
    seen = {}
    real_export = pipeline._export
    monkeypatch.setattr(pipeline, "_export",
                        lambda *a, language=None, **k: seen.update(language=language)
                        or real_export(*a, language=language, **k))
    pipeline.run(_src(tmp_path), language="de", parse_pages=_parse_pages,
                 confirm_translation=lambda d, p: asked.append((d, p)) or True)
    assert asked == []                  # explicit flag → never asked
    assert seen["language"] == "de"     # translate to the requested language


def test_gate_default_non_interactive_confirm_declines(tmp_path, stub_pipeline, monkeypatch):
    # The default confirm_translation (no callable injected) declines, so a
    # non-interactive run produces native output even when languages differ.
    monkeypatch.setattr(pipeline.config, "resolve_language", lambda flag: flag or "en")
    _stub_detected(monkeypatch, "cs")
    seen = {}
    real_export = pipeline._export
    monkeypatch.setattr(pipeline, "_export",
                        lambda *a, language=None, **k: seen.update(language=language)
                        or real_export(*a, language=language, **k))
    pipeline.run(_src(tmp_path), parse_pages=_parse_pages)  # no confirm injected
    assert seen["language"] is None


# ---- language-aware export cache (issue #127) ----


def _study_calls(monkeypatch):
    """Replace study_document with a stub that records each (style, language) it was
    called with and writes language-distinguishable markdown, so a test can assert
    which language actually (re)ran and which prose the book assembled from."""
    seen: list[dict] = []

    def capturing_study(cset, *, style, language=None, **kw):
        seen.append({"style": style, "language": language})
        lang = language or "en"
        return {"markdown": f"## Point ({lang})\n- a claim [s-1](#note-s-1)\n",
                "cited": {"s-1"}, "unknown": []}

    monkeypatch.setattr(pipeline.exp, "study_document", capturing_study)
    return seen


def test_language_change_regenerates_export_not_reuses_english(
    tmp_path, stub_pipeline, monkeypatch
):
    # #127: an English run then a `--language cs` run must REGENERATE the export
    # (study_document invoked with language="cs"), not skip on the English files.
    study = _study_calls(monkeypatch)
    src = _src(tmp_path)

    pipeline.run(src, parse_pages=_parse_pages)                      # English (native)
    assert [c["language"] for c in study] == [None]                 # one English export

    study.clear()
    pipeline.run(src, language="cs", parse_pages=_parse_pages)       # now Czech
    assert study, "cs run must regenerate the export, not reuse the English cache"
    assert all(c["language"] == "cs" for c in study)

    # Both languages now cached as separate files in the export dir.
    exdir = workspace.export_dir(workspace.work_dir(src))
    names = {p.name for p in exdir.glob("chapter-*.md")}
    assert "chapter-001.outline.md" in names        # English: bare name (backward-compat)
    assert "chapter-001.outline.cs.md" in names      # Czech: language-suffixed


def test_same_language_run_twice_caches(tmp_path, stub_pipeline, monkeypatch):
    # Second identical cs run skips (cached); English twice skips too.
    study = _study_calls(monkeypatch)
    src = _src(tmp_path)

    pipeline.run(src, language="cs", parse_pages=_parse_pages)
    assert [c["language"] for c in study] == ["cs"]
    study.clear()
    pipeline.run(src, language="cs", parse_pages=_parse_pages)        # cached
    assert study == [], "a second identical cs run must skip the export"

    study.clear()
    pipeline.run(src, parse_pages=_parse_pages)                       # English, first time
    assert [c["language"] for c in study] == [None]
    study.clear()
    pipeline.run(src, parse_pages=_parse_pages)                       # English, cached
    assert study == [], "a second English run must skip the export"


def test_force_regenerates_regardless_of_language(tmp_path, stub_pipeline, monkeypatch):
    study = _study_calls(monkeypatch)
    src = _src(tmp_path)
    pipeline.run(src, language="cs", parse_pages=_parse_pages)
    study.clear()
    pipeline.run(src, language="cs", force=True, parse_pages=_parse_pages)
    assert [c["language"] for c in study] == ["cs"]   # --force always re-runs


def test_book_assembles_the_runs_language_not_a_mix(tmp_path, stub_pipeline, monkeypatch):
    # #127: after both languages are exported, a cs run's book must assemble from the
    # cs chapter files — not the English ones, and not a mix of both.
    _study_calls(monkeypatch)
    src = _src(tmp_path)

    pipeline.run(src, parse_pages=_parse_pages)                       # English exported
    pipeline.run(src, language="cs", parse_pages=_parse_pages)        # cs exported
    cs_book = stub_pipeline["books"]["md"]
    assert "(cs)" in cs_book and "(en)" not in cs_book

    pipeline.run(src, parse_pages=_parse_pages)                       # English book again
    en_book = stub_pipeline["books"]["md"]
    assert "(en)" in en_book and "(cs)" not in en_book


def test_english_path_filenames_unchanged(tmp_path, stub_pipeline, monkeypatch):
    # Backward-compat: the English/native path writes the same bare names as before.
    _study_calls(monkeypatch)
    src = _src(tmp_path)
    pipeline.run(src, parse_pages=_parse_pages)
    exdir = workspace.export_dir(workspace.work_dir(src))
    names = sorted(p.name for p in exdir.glob("chapter-*.md"))
    assert names == ["chapter-001.outline.md"]   # no language segment on the default path


def test_translation_log_only_on_actual_regeneration(tmp_path, stub_pipeline, monkeypatch):
    # #127: the "writing in <lang>" line must reflect reality — emitted when the cs
    # export actually runs, and NOT on a fully-cached cs reuse.
    _study_calls(monkeypatch)
    src = _src(tmp_path)

    logs: list[str] = []
    pipeline.run(src, language="cs", parse_pages=_parse_pages, log=logs.append)
    assert any("writing in cs" in m for m in logs)   # first cs run translates → announces

    logs.clear()
    pipeline.run(src, language="cs", parse_pages=_parse_pages, log=logs.append)
    assert not any("writing in" in m for m in logs)  # fully cached → no false claim


def test_english_run_never_announces_translation(tmp_path, stub_pipeline, monkeypatch):
    _study_calls(monkeypatch)
    src = _src(tmp_path)
    logs: list[str] = []
    pipeline.run(src, parse_pages=_parse_pages, log=logs.append)
    assert not any("writing in" in m for m in logs)  # native path makes no claim


def test_single_section_document_still_yields_a_book(tmp_path, stub_pipeline):
    # The stub assemble emits exactly one section; with prose_only off (the --all
    # behaviour) it must still export and produce a book — no "0 chapters" dead-end.
    src = _src(tmp_path)
    out = pipeline.run(src, parse_pages=_parse_pages)
    assert out.is_file()
    assert "export" in stub_pipeline["calls"]
