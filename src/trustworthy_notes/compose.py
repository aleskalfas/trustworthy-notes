"""Wave 2 (compose) — stages 0–1: load page-sets and group pages into chapters.

This is the deterministic foundation of compose (ARCHITECTURE §6). It contains
no model calls: it loads the per-page notes produced by Wave 1 and groups the
document's pages into chapters by reusing Wave 0's running-header detection —
the same headers that, leaked into the body, motivated the header fix are here
the *signal* for chapter boundaries.

Later stages (evidence stitching, dedup, term store, assembly) build on the
chapter map this produces.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Optional

import pdfplumber
import yaml

from . import ingest, workspace
from .normalize import normalize_for_match


def _despace(text: str) -> str:
    """Undo small-caps letter-spacing in a top line.

    pdfplumber renders a small-caps heading like "CHAPTER" as separate tokens
    "C" + "HAPTER" (the drop-initial is a different size), so ``top_line`` yields
    "C HAPTER 1: A IMS AND O BJECTIVES". A lone single-letter token is such an
    artifact; merge it into the following token. Multi-letter words ("AND") and
    tokens with punctuation ("B:", "1:") are left alone. Unmapped-glyph markers
    like "(cid:3)" are font artifacts, never content, and are dropped (otherwise
    "… GIZA" and "… GIZA (cid:3)" would key as two different sections).
    """
    text = re.sub(r"\(cid:\d+\)", " ", text)
    tokens = text.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if len(tok) == 1 and tok.isalpha() and i + 1 < len(tokens):
            out.append(tok + tokens[i + 1])
            i += 2
        else:
            out.append(tok)
            i += 1
    return " ".join(out)


def _section_key(top_line: str) -> str:
    """A stable grouping key for a section-header top line.

    Chapters are keyed by number so a chapter's *opening* page ("CHAPTER 5") and
    its *running* header ("CHAPTER 5: SISTERS OF THE TOMB OWNER") collapse to one
    chapter. Every other section header (PART ONE, BIBLIOGRAPHY, TABLE B: …,
    INDEX OF MONUMENTS: GIZA) keys by its full de-spaced text.
    """
    t = _despace(top_line).upper().strip()
    m = re.match(r"CHAPTER\s+(\d+|[IVXLCDM]+)\b", t)
    if m:
        return f"CHAPTER {m.group(1)}"
    return t


def chapter_map(pdf_path: str | Path) -> list[dict]:
    """Group the document's pages into ordered chapters (ARCHITECTURE §6, stage 1).

    A page begins a new chapter when its top line is a detected running header
    (caps-styled or repeated) that is *not* the book title and whose section key
    differs from the current one. Other pages (recto book-title pages, untitled
    pages) inherit the current chapter; pages before the first section header are
    'Front matter'. Returns ordered dicts: ``{key, title, page_numbers,
    page_indices}``.
    """
    with pdfplumber.open(pdf_path) as pdf:
        pages = list(pdf.pages)
        page_numbers = [p.page_number for p in pages]
        tops = [ingest.top_line(p) for p in pages]
        headers = ingest._detect_running_headers(tops)
        chapters = _absorb_stray(_merge_oscillating(_group(page_numbers, tops, headers)))
        _enrich_titles_from_toc(chapters, pages)   # while the PDF is open
    return chapters


def _is_reference(title: str) -> bool:
    """A section that is reference matter (tables/indexes/figures/accessory labels)."""
    return title.upper().startswith(("TABLE ", "INDEX ", "FIGURE", "ACCESSORIES"))


def _absorb_stray(chapters: list[dict]) -> list[dict]:
    """Fold a stray short section into the preceding reference section when both its
    neighbours are reference matter — e.g. a lone 'FAMILY' page between 'TABLE L' and
    'TABLE M' is a table column-label, not a chapter (systematic, not name-based)."""
    out: list[dict] = []
    for i, c in enumerate(chapters):
        stray = (
            0 < i < len(chapters) - 1
            and len(c["page_numbers"]) <= 2
            and not re.match(r"(CHAPTER \d+|PART )", c["key"])
            and not _is_reference(c["title"])
            and _is_reference(chapters[i - 1]["title"])
            and _is_reference(chapters[i + 1]["title"])
        )
        if stray and out:
            out[-1]["page_numbers"] += c["page_numbers"]
            out[-1]["page_indices"] += c["page_indices"]
        else:
            out.append(c)
    return out


def _enrich_titles_from_toc(chapters: list[dict], pages: list) -> None:
    """Give chapters whose running header is a bare 'CHAPTER N' a real name parsed
    from the document's Table of Contents (the systematic source of chapter names)."""
    toc_idx = [i for ch in chapters if "CONTENTS" in ch["title"].upper() for i in ch["page_indices"]]
    if not toc_idx:
        return
    names: dict[str, str] = {}
    for i in toc_idx:
        for m in re.finditer(r"CHAPTER\s+(\d+)\s+([A-Z][A-Za-z].*)", pages[i].extract_text() or ""):
            name = m.group(2).split(":")[0]
            name = re.sub(r"[\s.·…]+\d+\s*$", "", name).strip()  # drop dotted-leader page nums
            if name:
                names.setdefault(m.group(1), name)
    for ch in chapters:
        m = re.match(r"CHAPTER (\d+)$", ch["title"].strip())
        if m and ":" not in ch["title"] and m.group(1) in names:
            ch["title"] = f"CHAPTER {m.group(1)}: {names[m.group(1)]}"


def _more_descriptive(a: str, b: str) -> bool:
    """True if header ``a`` names its section better than ``b`` — prefer one with a
    ':' (the descriptive 'CHAPTER 1: AIMS…' over the bare 'CHAPTER 1'), then longer."""
    return (":" in a, len(a)) > (":" in b, len(b))


def _group(page_numbers: list[int], tops: list[str], headers: set[str]) -> list[dict]:
    """Forward-fill pages into chapters (pure; no PDF). A page starts a new chapter
    when its top line is a section header (in ``headers``, not the book title) with
    a new section key; others inherit; pre-header pages are 'Front matter'. A
    chapter's title is upgraded to the most descriptive header seen for it."""
    counts = Counter(t for t in tops if t)
    book_title = counts.most_common(1)[0][0] if counts else None

    chapters: list[dict] = []
    current: Optional[dict] = None
    for num, top in zip(page_numbers, tops):
        if top and top in headers and top != book_title:
            key = _section_key(top)
            desp = _despace(top)
            if current is None or current["key"] != key:
                current = {"key": key, "title": desp, "page_numbers": [], "page_indices": []}
                chapters.append(current)
            elif _more_descriptive(desp, current["title"]):
                current["title"] = desp
        if current is None:
            current = {"key": "FRONT-MATTER", "title": "Front matter", "page_numbers": [], "page_indices": []}
            chapters.append(current)
        current["page_numbers"].append(num)
        current["page_indices"].append(num - 1)
    return chapters


def _merge_run(run: list[dict]) -> dict:
    """Fuse a run of chapters into one section. Title prefers a descriptive header
    (one with a ':', i.e. the 'TABLE B: …' side over the bare 'ACCESSORIES' side)."""
    titled = [c for c in run if ":" in c["key"]]
    rep = titled[0] if titled else max(run, key=lambda c: len(c["page_numbers"]))
    merged = {"key": rep["key"], "title": rep["title"], "page_numbers": [], "page_indices": []}
    for c in run:
        merged["page_numbers"] += c["page_numbers"]
        merged["page_indices"] += c["page_indices"]
    return merged


def _merge_oscillating(chapters: list[dict], min_run: int = 3) -> list[dict]:
    """Collapse a run of consecutive chapters whose headers alternate between just
    two titles into one section (recto/verso headers of a single multi-page table:
    'TABLE B …' / 'ACCESSORIES' / 'TABLE B …' / …). A run must be at least
    ``min_run`` chapters long, so two genuinely-adjacent short chapters are kept."""
    out: list[dict] = []
    i = 0
    while i < len(chapters):
        keys: set[str] = set()
        j = i
        while j < len(chapters) and len(keys | {chapters[j]["key"]}) <= 2:
            keys.add(chapters[j]["key"])
            j += 1
        run = chapters[i:j]
        if len(run) >= min_run and len(keys) == 2:
            out.append(_merge_run(run))
            i = j
        else:
            out.append(chapters[i])
            i += 1
    return out


# A trailing char that closes a sentence/clause — its ABSENCE means the text was
# cut mid-sentence (a page-break truncation worth stitching).
_CLOSERS = set(".!?\"'”’)]")
# A sentence terminator: . ! ? possibly trailed by closing quotes/brackets and/or
# a footnote marker ("context'.[^30]"), then whitespace or end of text.
_TERMINATORS = re.compile(r"[.!?][\"'”’)\]]*(?:\[\^\d+\])?(?=\s|$)")


def _ends_open(text: str) -> bool:
    """True if ``text`` ends mid-sentence (no terminal punctuation) — i.e. it was
    cut at a page break rather than ending a complete sentence."""
    t = (text or "").rstrip()
    return bool(t) and t[-1] not in _CLOSERS


def _completion(body_next: str, max_chars: int = 400) -> str:
    """The head of the next page's body up to and including the first sentence
    terminator — the continuation of a quote cut at the previous page's end."""
    head = (body_next or "").lstrip()
    m = _TERMINATORS.search(head)
    end = m.end() if m and m.end() <= max_chars else min(len(head), max_chars)
    return head[:end].strip()


def stitch_tail(tail_excerpt: str, body_n: str, body_next: str) -> Optional[str]:
    """If ``tail_excerpt`` is a truncated quote at the end of page N, return the
    full sentence completed from page N+1; else ``None``.

    Requires the excerpt to (a) end mid-sentence and (b) be a verbatim suffix of
    page N's body. The completion is a verbatim prefix of page N+1's body, so the
    joined excerpt is verbatim across the boundary (anchoring preserved).
    """
    if not _ends_open(tail_excerpt):
        return None
    if not normalize_for_match(body_n).endswith(normalize_for_match(tail_excerpt)):
        return None
    comp = _completion(body_next)
    if not comp:
        return None
    return f"{tail_excerpt.rstrip()} {comp}"


def find_stitches(pdf_path: str | Path, notes_dir: str | Path) -> list[dict]:
    """Propose cross-page evidence stitches over the corpus (ARCHITECTURE §6,
    stage 2). For each truncated-tail body-evidence record, compute the completed
    quote from the following text page. Mechanical; no API; mutates nothing."""
    pages = {p.page_index: p for p in ingest.read_pages(pdf_path)}
    notes = load_page_sets(notes_dir)
    out: list[dict] = []
    for idx in sorted(notes):
        page, nxt = pages.get(idx), pages.get(idx + 1)
        if not page or page.page_type != "text" or not nxt or nxt.page_type != "text":
            continue
        for e in notes[idx].get("evidence", []):
            if e.get("source") != "body":
                continue
            full = stitch_tail(e.get("excerpt", ""), page.text, nxt.text)
            if full:
                out.append(
                    {
                        "page_index": idx,
                        "next_page_index": idx + 1,
                        "evidence_id": e.get("id"),
                        "tail": e.get("excerpt"),
                        "stitched": full,
                    }
                )
    return out


# Sections that are reference matter, not prose: a low evidence-coverage there is
# expected (a table of names has nothing to "claim"), so they should not appear
# on a "pages with missed content" list.
_NON_PROSE_TITLES = {
    "FRONT MATTER", "ACKNOWLEDGEMENTS", "TABLE OF CONTENTS", "TABLES",
    "CHRONOLOGY ABBREVIATIONS", "ABBREVIATIONS", "BIBLIOGRAPHY",
    "BIBLIOGRAPHY FOR THE TEXT", "INDICES", "PART ONE", "PART TWO", "PART THREE",
}


def _is_prose_section(title: str) -> bool:
    """True for narrative sections (chapters, discussion); False for reference
    matter (tables, indexes, figure catalogues, front/back matter, part dividers)."""
    t = title.upper().strip()
    if t.startswith(("TABLE ", "INDEX ", "FIGURE")):
        return False
    return t not in _NON_PROSE_TITLES


def page_sections(pdf_path: str | Path) -> dict[int, dict]:
    """Map each page_index → its section ``{title, prose}`` (from the chapter map)."""
    out: dict[int, dict] = {}
    for ch in chapter_map(pdf_path):
        prose = _is_prose_section(ch["title"])
        for idx in ch["page_indices"]:
            out[idx] = {"title": ch["title"], "prose": prose}
    return out


def load_page_sets(work_dir: str | Path) -> dict[int, dict]:
    """Load every per-page notes file (in ``<work_dir>/1-extract/``), keyed by page_index."""
    out: dict[int, dict] = {}
    for f in sorted(workspace.extract_dir(work_dir).glob("page-*.notes.yaml")):
        idx = int(f.stem.split("-")[1].split(".")[0])
        out[idx] = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    return out


def _statements_with_evidence(work_dir: str | Path) -> list[dict]:
    """Flatten all per-page statements into records carrying their type, text, and
    the set of normalized evidence excerpts they cite (the dedup blocking signal)."""
    notes = load_page_sets(work_dir)
    out: list[dict] = []
    for idx in sorted(notes):
        ev = {
            e["id"]: normalize_for_match(e.get("excerpt", ""))
            for e in notes[idx].get("evidence", [])
            if "id" in e
        }
        for s in notes[idx].get("statements", []):
            excerpts = {ev.get(eid, "") for eid in s.get("evidence", [])}
            out.append(
                {
                    "key": f"p{idx}:{s.get('id', '?')}",
                    "page_index": idx,
                    "type": s.get("type"),
                    "text": s.get("text", ""),
                    "evidence": {e for e in excerpts if len(e) >= 25},
                }
            )
    return out


def dedup_candidates(work_dir: str | Path) -> list[list[dict]]:
    """Mechanical dedup blocking (ARCHITECTURE §6, stage 3).

    Groups statements that are candidate duplicates using the high-precision
    shared-evidence signal: two statements of the SAME type that cite the same
    verbatim excerpt are almost certainly one claim. Returns clusters (≥2 members,
    largest first) for a later bounded model pass to confirm/merge. Mutates
    nothing; this is only the candidate-generation step.
    """
    stmts = _statements_with_evidence(work_dir)
    by_key = {s["key"]: s for s in stmts}
    parent = {s["key"]: s["key"] for s in stmts}

    def find(k: str) -> str:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    # Invert: excerpt → statements citing it; union same-type statements that share one.
    ev_index: dict[str, list[str]] = {}
    for s in stmts:
        for e in s["evidence"]:
            ev_index.setdefault(e, []).append(s["key"])
    for keys in ev_index.values():
        by_type: dict[str, list[str]] = {}
        for k in keys:
            by_type.setdefault(by_key[k]["type"], []).append(k)
        for same in by_type.values():
            for k in same[1:]:
                union(same[0], k)

    clusters: dict[str, list[dict]] = {}
    for k in parent:
        clusters.setdefault(find(k), []).append(by_key[k])
    multi = [sorted(c, key=lambda s: s["page_index"]) for c in clusters.values() if len(c) > 1]
    return sorted(multi, key=len, reverse=True)


def _assemble_chapter(ch: dict, notes: dict, *, merges, xrels, links, term_label, document) -> Optional[dict]:
    """Build one chapter-scope notes-set from its pages' page-sets, applying dedup
    merges, term links, and intra-page + cross-page relations. Evidence is carried
    verbatim (each tagged with its origin page_index); stitching is deferred."""
    idxs = ch["page_indices"]
    stmts: dict[str, dict] = {}  # "pIDX:sid" -> {s, idx}
    evs: dict[str, tuple] = {}   # "pIDX:eid" -> (idx, page_label, evidence record)
    for idx in idxs:
        n = notes.get(idx) or {}
        page_label = (n.get("source") or {}).get("page_label")
        for e in n.get("evidence", []):
            if "id" in e:
                evs[f"p{idx}:{e['id']}"] = (idx, page_label, e)
        for s in n.get("statements", []):
            if "id" in s:
                stmts[f"p{idx}:{s['id']}"] = {"s": s, "idx": idx}
    if not stmts:
        return None

    member_to_merge: dict[str, str] = {}
    merge_text: dict[str, str] = {}
    merge_members: dict[str, list[str]] = {}
    for i, m in enumerate(merges):
        members = [k for k in m.get("members", []) if k in stmts]
        if len(members) >= 2:
            mk = f"m{i}"
            merge_text[mk], merge_members[mk] = m.get("text", ""), members
            for k in members:
                member_to_merge[k] = mk

    keymap: dict[str, str] = {}          # statement global key / merge key -> final s-id
    finals: list[dict] = []
    si = 0
    emitted: set[str] = set()
    for gk in sorted(stmts, key=lambda k: (stmts[k]["idx"], k)):
        if gk in member_to_merge:
            mk = member_to_merge[gk]
            if mk in emitted:
                continue
            emitted.add(mk)
            members = merge_members[mk]
            si += 1
            sid = f"s-{si}"
            for k in members:
                keymap[k] = sid
            keymap[mk] = sid
            ev_keys, terms, stype, basis = [], set(), None, None
            for k in members:
                src = stmts[k]["s"]
                stype = stype or src.get("type")
                basis = basis or src.get("basis")
                ev_keys += [f"p{stmts[k]['idx']}:{eid}" for eid in src.get("evidence", [])]
                terms.update(links.get(k, []))
            finals.append({"id": sid, "type": stype, "basis": basis, "text": merge_text[mk],
                           "ev_keys": ev_keys, "terms": terms})
        else:
            src = stmts[gk]["s"]
            si += 1
            sid = f"s-{si}"
            keymap[gk] = sid
            finals.append({"id": sid, "type": src.get("type"), "basis": src.get("basis"),
                           "text": src.get("text", ""),
                           "ev_keys": [f"p{stmts[gk]['idx']}:{eid}" for eid in src.get("evidence", [])],
                           "terms": set(links.get(gk, []))})

    # assign evidence ids (dedup, first-use order), tagging each with its origin page
    ev_id: dict[str, str] = {}
    out_ev: list[dict] = []
    for fs in finals:
        for ek in fs["ev_keys"]:
            if ek in evs and ek not in ev_id:
                idx, page_label, rec = evs[ek]
                ev_id[ek] = f"e-{len(out_ev) + 1}"
                item = {"id": ev_id[ek], "kind": rec.get("kind", "text"),
                        "excerpt": rec.get("excerpt", ""), "source": rec.get("source", "body"),
                        "page_index": idx}
                if page_label is not None:
                    item["page_label"] = page_label
                for opt in ("locator", "script", "caption"):
                    if opt in rec:
                        item[opt] = rec[opt]
                out_ev.append(item)

    used_terms: set[str] = set()
    out_stmts: list[dict] = []
    for fs in finals:
        terms = [t for t in sorted(fs["terms"]) if t in term_label]
        used_terms.update(terms)
        st = {"id": fs["id"], "type": fs["type"], "text": fs["text"],
              "evidence": [ev_id[ek] for ek in fs["ev_keys"] if ek in ev_id]}
        if fs.get("basis"):
            st["basis"] = fs["basis"]
        if terms:
            st["terms"] = terms
        out_stmts.append(st)

    rels: list[dict] = []
    seen: set[tuple] = set()

    def add(a_key: str, b_key: str, rtype: str) -> None:
        a, b = keymap.get(a_key), keymap.get(b_key)
        if a and b and a != b and (a, b, rtype) not in seen:
            seen.add((a, b, rtype))
            rels.append({"from": a, "to": b, "type": rtype})

    for idx in idxs:
        for r in (notes.get(idx) or {}).get("relations", []):
            fr, to = r.get("from"), r.get("to")
            if isinstance(fr, str) and isinstance(to, str) and fr.startswith("s-") and to.startswith("s-"):
                add(f"p{idx}:{fr}", f"p{idx}:{to}", r.get("type"))
    for r in xrels:
        add(r.get("from"), r.get("to"), r.get("type"))

    return {
        "schema_version": 1,
        "source": {
            "document": document, "scope": "chapter", "chapter_id": ch["key"],
            "chapter_title": ch["title"], "page_range": [idxs[0], idxs[-1]],
        },
        "terms": [{"id": t, "label": term_label[t]} for t in sorted(used_terms)],
        "evidence": out_ev,
        "statements": out_stmts,
        "relations": rels,
    }


def assemble_document(pdf_path: str | Path, work_dir: str | Path, *, document: str) -> list[dict]:
    """Stage 6: assemble each section with statements into a chapter-scope notes-set,
    written to ``2-compose/chapter-NNN.notes.yaml``. Returns per-chapter summaries."""
    def _load(stage: str, name: str, key: str) -> list:
        p = workspace.compose_stage_dir(work_dir, stage) / name
        return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get(key, []) if p.is_file() else []

    merges = _load("dedup", "dedup-merges.yaml", "merges")
    xrels = _load("relations", "relations.yaml", "relations")
    terms_path = workspace.compose_stage_dir(work_dir, "terms") / "terms.yaml"
    terms_doc = (yaml.safe_load(terms_path.read_text(encoding="utf-8"))
                 if terms_path.is_file() else {"terms": [], "links": {}})
    term_label = {t["id"]: t["label"] for t in terms_doc.get("terms", [])}
    links = terms_doc.get("links", {})

    out_dir = workspace.compose_stage_dir(work_dir, "chapters")
    notes = load_page_sets(work_dir)
    summaries: list[dict] = []
    n = 0
    for ch in chapter_map(pdf_path):
        cset = _assemble_chapter(ch, notes, merges=merges, xrels=xrels, links=links,
                                 term_label=term_label, document=document)
        if cset is None:
            continue
        n += 1
        dest = out_dir / f"chapter-{n:03d}.notes.yaml"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(yaml.safe_dump(cset, sort_keys=False, allow_unicode=True), encoding="utf-8")
        summaries.append({
            "file": dest.name, "title": ch["title"],
            "statements": len(cset["statements"]), "evidence": len(cset["evidence"]),
            "terms": len(cset["terms"]), "relations": len(cset["relations"]),
        })
    return summaries


def chapter_summaries(pdf_path: str | Path, notes_dir: str | Path) -> list[dict]:
    """The chapter map annotated with how many pages have notes and how many
    statements/evidence each chapter holds — the inspectable Stage 0–1 output."""
    notes = load_page_sets(notes_dir)
    out: list[dict] = []
    for ch in chapter_map(pdf_path):
        idxs = ch["page_indices"]
        present = [i for i in idxs if i in notes]
        out.append(
            {
                "key": ch["key"],
                "title": ch["title"],
                "page_numbers": ch["page_numbers"],
                "pages": len(idxs),
                "with_notes": len(present),
                "statements": sum(len(notes[i].get("statements", [])) for i in present),
                "evidence": sum(len(notes[i].get("evidence", [])) for i in present),
            }
        )
    return out
