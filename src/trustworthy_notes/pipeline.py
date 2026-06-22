"""One-command orchestration: a bare PDF through the whole pipeline.

The per-stage subcommands in ``cli`` each expose one wave for inspection and
control. A non-technical user shouldn't have to learn that map: ``tnotes <pdf>``
runs every stage end-to-end and drops the finished book beside the source.

This module is *foreground* orchestration, not a daemon — it drives the existing
stage implementations in order, printing progress to stderr, and returns when the
book is written. It owns no pipeline logic of its own: every stage calls the same
function the matching subcommand calls (``term_store.build_store``,
``relate.build_relations``, ``compose.assemble_document``, ``export.study_document``,
``book.combine``, …). The only behaviour it adds is the glue between stages and a
few defaults chosen for the non-technical path:

- **Resumable by default.** A stage whose output already exists is skipped;
  ``force`` regenerates everything.
- **No dead-ends.** Export and book run with the ``--all`` behaviour (prose_only
  off), so a single-section document (a paper with no chapter headers) still
  yields a book instead of the "0 prose chapters" dead-end.
- **Prose reading copy by default.** The book is the clean prose copy named
  ``<stem>[.pRANGE].tnotes.pdf`` beside the source; ``cite`` makes that same file
  the anchored version ([s-N] markers + Notes & Sources appendix).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import yaml

from . import (
    adjudicate as adj,
    book as bookmod,
    compose,
    config,
    export as exp,
    ingest,
    pdf as pdfmod,
    relate,
    term_store,
    workspace,
)
from .extract import run_extract, write_notes
from .extract_anthropic import AnthropicExtractor


def page_range_tag(pages: Optional[str]) -> str:
    """The filename tag for a ``--pages`` spec: ``"14"`` → ``.p14``, ``"1-30"`` →
    ``.p1-30``, ``"14,16"`` → ``.p14,16``; ``None`` (whole document) → ``""``.

    The spec's own punctuation is preserved (it already reads as a range), only
    whitespace is stripped so the tag is filename-safe and matches what the user
    typed.
    """
    if not pages:
        return ""
    compact = pages.replace(" ", "")
    return f".p{compact}"


def book_path(input_path: Path, pages: Optional[str]) -> Path:
    """Where the one-command book lands: ``<stem>[.pRANGE].tnotes.pdf`` beside the
    source (e.g. ``data/Foo.pdf`` + ``-p 1-30`` → ``data/Foo.p1-30.tnotes.pdf``)."""
    stem = input_path.stem + page_range_tag(pages) + ".tnotes"
    return input_path.parent / f"{stem}.pdf"


def run(
    input_path: Path,
    *,
    pages: Optional[str] = None,
    force: bool = False,
    cite: bool = False,
    keep_md: bool = False,
    style: str = "outline",
    model: Optional[str] = None,
    effort: Optional[str] = None,
    max_tokens: Optional[int] = None,
    language: Optional[str] = None,
    log: Callable[[str], None] = lambda msg: None,
    parse_pages: Callable[[str, int], list[int]],
) -> Path:
    """Run the whole pipeline for ``input_path`` and return the book's path.

    ``parse_pages`` is the CLI's page-spec parser, injected so the orchestrator
    and the ``extract`` subcommand share one interpretation of ``-p``. ``log``
    receives human-readable progress lines (the CLI routes them to stderr).

    ``language`` is the reader's preferred language, resolved here on the same
    flag > config > built-in chain as ``model``/``effort`` (ADR-008; the OS-locale
    link is the bootstrap seed only, never read on this hot path). It is carried to
    the reading/export stage, which is where translation will consume it (#112);
    until then ``_export`` simply receives and ignores it.
    """
    model = config.resolve_model(model)
    effort = config.resolve_effort(effort)
    language = config.resolve_language(language)
    api_key = config.get_api_key()
    work = workspace.work_dir(input_path)

    log(f"tnotes: {input_path.name} → {book_path(input_path, pages).name}")
    log(f"model {model} (effort={effort or 'none'}){' [force: regenerating all]' if force else ''}")

    _extract(input_path, work, pages, force, model, effort, api_key, parse_pages, log,
             max_tokens=max_tokens)
    _build_terms(input_path, work, force, model, effort, api_key, log)
    _build_dedup(input_path, work, force, model, effort, api_key, log)
    _build_relations(input_path, work, force, model, effort, api_key, log)
    _assemble(input_path, work, force, log)
    _export(input_path, work, force, style, model, effort, api_key, log, language=language)
    return _book(input_path, work, pages, cite, style, log, keep_md=keep_md)


def _extract(input_path, work, pages, force, model, effort, api_key, parse_pages, log,
             *, max_tokens=None) -> None:
    """Wave 1: per-page notes. Already-extracted pages are skipped unless ``force``."""
    all_pages = ingest.read_pages(input_path)
    by_number = {p.page_number: p for p in all_pages}
    if pages is None:
        selected = [p.page_number for p in all_pages if p.page_type == "text"]
    else:
        selected = parse_pages(pages, len(all_pages))
    if not selected:
        raise ValueError(f"no extractable pages selected from {input_path.name}")

    workspace.extract_dir(work).mkdir(parents=True, exist_ok=True)
    # max_tokens=None → the extractor's own default (32000); raise it when a dense
    # page exhausts the budget while thinking at higher effort (issue #93).
    extra = {"max_tokens": max_tokens} if max_tokens else {}
    extractor = AnthropicExtractor(model=model, effort=effort, api_key=api_key, **extra)

    todo: list[int] = []
    for n in selected:
        target = by_number[n]
        if target.page_type not in ("text", "figure"):
            continue
        dest = workspace.page_notes_path(work, target.page_index)
        if dest.is_file() and not force:
            continue
        todo.append(n)

    if not todo:
        log(f"[1/7] extract: all {len(selected)} page(s) already extracted — skipping")
        return

    log(f"[1/7] extract: {len(todo)} of {len(selected)} page(s) (the rest are up to date)")
    failed: list[int] = []
    for i, n in enumerate(todo, 1):
        target = by_number[n]
        idx = all_pages.index(target)
        neighbors = [
            all_pages[j]
            for j in range(max(0, idx - 1), min(len(all_pages), idx + 2))
            if j != idx and all_pages[j].page_type == "text"
        ]
        try:
            notes, _ = run_extract(
                target, extractor, document=input_path.stem, context={"neighbors": neighbors}
            )
        except Exception as exc:  # one page must not abort the whole run
            failed.append(n)
            log(f"  page {n} FAILED: {exc} — continuing")
            continue
        write_notes(notes, workspace.page_notes_path(work, target.page_index))
        log(f"  page {n} ({i}/{len(todo)}): {len(notes['statements'])} statements")
    if failed:
        log(f"  {len(failed)} page(s) failed: {failed} — re-run to retry just those")


def _build_terms(input_path, work, force, model, effort, api_key, log) -> None:
    """Wave 2 stage 4: the document-global term store (``terms.yaml``)."""
    dest = workspace.compose_stage_dir(work, "terms") / "terms.yaml"
    if dest.is_file() and not force:
        log("[2/7] terms: store up to date — skipping")
        return
    log("[2/7] terms: building the document-global term store…")
    store = term_store.build_store(input_path, work, model=model, effort=effort, api_key=api_key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(yaml.safe_dump(store, allow_unicode=True, sort_keys=False), encoding="utf-8")
    log(f"  {len(store['terms'])} terms, {len(store['links'])} statements linked")


def _build_dedup(input_path, work, force, model, effort, api_key, log) -> None:
    """Wave 2 stage 3 (part b): adjudicated merge groups (``dedup-merges.yaml``)."""
    dest = workspace.compose_stage_dir(work, "dedup") / "dedup-merges.yaml"
    if dest.is_file() and not force:
        log("[3/7] dedup: merges up to date — skipping")
        return
    clusters = compose.dedup_candidates(work)
    if not clusters:
        log("[3/7] dedup: no duplicate candidates")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(yaml.safe_dump({"merges": []}, allow_unicode=True), encoding="utf-8")
        return
    log(f"[3/7] dedup: adjudicating {len(clusters)} candidate cluster(s)…")
    decisions = adj.adjudicate(clusters, model=model, effort=effort, api_key=api_key)
    merges = [m for d in decisions for m in d["merges"]]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(yaml.safe_dump({"merges": merges}, allow_unicode=True), encoding="utf-8")
    log(f"  {len(merges)} confirmed merge group(s)")


def _build_relations(input_path, work, force, model, effort, api_key, log) -> None:
    """Wave 2 stage 5: cross-page relations (``relations.yaml``)."""
    dest = workspace.compose_stage_dir(work, "relations") / "relations.yaml"
    if dest.is_file() and not force:
        log("[4/7] relations: up to date — skipping")
        return
    log("[4/7] relations: discovering cross-page argument structure…")
    rels = relate.build_relations(input_path, work, model=model, effort=effort, api_key=api_key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(yaml.safe_dump({"relations": rels}, allow_unicode=True), encoding="utf-8")
    log(f"  {len(rels)} cross-page relation(s)")


def _assemble(input_path, work, force, log) -> None:
    """Wave 2 stage 6: chapter-scope notes-sets (``chapter-NNN.notes.yaml``).

    Assembly is cheap (no API) and consumes the upstream artifacts, so it always
    re-runs — a downstream change must be reflected even when extraction was a
    no-op. (``force`` is accepted for signature symmetry.)"""
    log("[5/7] assemble: lifting per-page notes to chapter scope…")
    summaries = compose.assemble_document(input_path, work, document=input_path.stem)
    if not summaries:
        raise ValueError("nothing to assemble — extraction produced no notes")
    log(f"  {len(summaries)} chapter notes-set(s)")


def _export(input_path, work, force, style, model, effort, api_key, log, *, language=None) -> None:
    """Wave 4: per-chapter study documents. ``prose_only`` is off (the ``--all``
    behaviour) so a single-section document still exports.

    ``language`` is the resolved preferred reading language, threaded here because
    the reading/export layer is where translation lives (ADR-008). It is accepted
    now and not yet consumed — the confirm-then-translate offer is task #112; this
    keeps the seam in place so wiring it up there is a one-spot change."""
    import anthropic

    src_dir = workspace.compose_stage_dir(work, "chapters")
    files = sorted(src_dir.glob("chapter-*.notes.yaml"))
    if not files:
        raise ValueError("no composed chapters to export")
    out_dir = workspace.export_dir(work)
    out_dir.mkdir(parents=True, exist_ok=True)

    skipped = 0
    pending = []
    for f in files:
        num = int(f.stem.split("-")[1].split(".")[0])
        dest = out_dir / f"chapter-{num:03d}.{style}.md"
        if dest.is_file() and not force:
            skipped += 1
            continue
        pending.append((num, f, dest))

    if not pending:
        log(f"[6/7] export: all {skipped} chapter(s) already exported — skipping")
        return

    log(f"[6/7] export: {len(pending)} of {len(files)} chapter(s) (the rest are up to date)")
    client = anthropic.Anthropic(api_key=api_key)
    for num, f, dest in pending:
        cset = yaml.safe_load(f.read_text(encoding="utf-8"))
        title = cset.get("source", {}).get("chapter_title", f.name)
        try:
            res = exp.study_document(cset, style=style, client=client, model=model, effort=effort)
        except Exception as exc:
            log(f"  chapter {num} ({title}) FAILED: {exc} — continuing")
            continue
        dest.write_text(res["markdown"], encoding="utf-8")
        log(f"  chapter {num} ({title}): {len(res['cited'])} notes cited")


def _book(input_path, work, pages, cite, style, log, keep_md=False) -> Path:
    """Combine the per-chapter exports into the finished book beside the source.

    The orchestrator's book includes all sections (the ``--all`` behaviour) and is
    PROSE by default; ``cite`` keeps the [s-N] markers and Notes & Sources
    appendix. The single output is ``<stem>[.pRANGE].tnotes.pdf``; ``keep_md`` (the
    ``--md`` flag) also writes the Markdown book beside it for those who want it."""
    exdir = workspace.export_dir(work)
    files = sorted(exdir.glob(f"chapter-*.{style}.md"))
    if not files:
        raise ValueError("no exported chapters to assemble into a book")

    chapters: list[tuple[int, str, str]] = []
    for f in files:
        num = int(f.stem.split("-")[1].split(".")[0])
        cfile = workspace.compose_stage_dir(work, "chapters") / f"chapter-{num:03d}.notes.yaml"
        src = (yaml.safe_load(cfile.read_text(encoding="utf-8")) or {}).get("source", {}) if cfile.is_file() else {}
        title = src.get("chapter_title") or src.get("chapter_id") or f"Chapter {num}"
        md = f.read_text(encoding="utf-8")
        if not cite:
            md = exp.strip_citations(md)
        chapters.append((num, title, md))

    book_md = bookmod.combine(chapters, doc_title=input_path.stem)
    pdf_path = book_path(input_path, pages)
    # The PDF renders from the in-memory book text; the Markdown is only persisted
    # beside the source when explicitly requested (--md), so the default one-command
    # run leaves a single book file (issue #73).
    pdfmod.markdown_to_pdf(book_md, pdf_path)
    if keep_md:
        pdf_path.with_suffix(".md").write_text(book_md, encoding="utf-8")
    kind = "cited" if cite else "prose reading copy"
    extra = " + .md" if keep_md else ""
    log(f"[7/7] book: {len(chapters)} chapter(s) → {pdf_path.name}{extra} ({kind})")
    return pdf_path
