"""Combine the per-chapter study-note documents into one navigable book.

Concatenates the chapter Markdown exports into a single document with a master,
hierarchical Contents (every chapter and its sub-sections, renumbered globally)
and a chapter→section→subsection bookmark tree. Each chapter's anchors and
internal links are namespaced (``c006-sec-1``, ``c006-note-s-5``) so the
``[s-N]`` cross-references stay unique and clickable across the whole book.
Chapter *titles* come from the composed notes-set (the descriptive running
header, e.g. "CHAPTER 1: AIMS AND OBJECTIVES"), not the bare opener.
"""

from __future__ import annotations

import re

_TITLE = re.compile(r"^#\s+")
_HEAD = re.compile(r"^(#{2,3})\s+(.*)$")
_SECNUM = re.compile(r"^(\d+(?:\.\d+)*)\.\s+")
_ANCHOR = re.compile(r'^<a id="([^"]+)"></a>\s*$')


def _strip_md(t: str) -> str:
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    return re.sub(r"[*_`]", "", t).strip()


def _process_chapter(book_n: int, file_num: int, title: str, md: str) -> tuple[list[tuple], str]:
    """Return (toc_entries, section_markdown) for one chapter.

    toc_entries: ``[(level, number, title, anchor), …]`` (chapter=level 0, section=1,
    subsection=2) for the master Contents. The section markdown has the md's own
    title/Contents dropped, anchors+links namespaced, headings demoted one level and
    renumbered under the book chapter number.
    """
    prefix = f"c{file_num:03d}"
    toc: list[tuple] = [(0, str(book_n), title, f"{prefix}-chap")]
    out = [f'<a id="{prefix}-chap"></a>', f"## {book_n}. {title}"]
    skipping_contents = False
    last_anchor: str | None = None

    for line in md.splitlines():
        if line.startswith("<!--") or (_TITLE.match(line) and not line.startswith("##")):
            continue
        if re.match(r"^##\s+Contents\b", line):
            skipping_contents = True
            continue
        if skipping_contents:
            if line.startswith("<a id=") or _HEAD.match(line):
                skipping_contents = False
            else:
                continue
        am = _ANCHOR.match(line)
        if am:
            last_anchor = f"{prefix}-{am.group(1)}"
            out.append(f'<a id="{last_anchor}"></a>')
            continue
        hm = _HEAD.match(line)
        if hm:
            hashes, rest = hm.group(1), hm.group(2)
            nm = _SECNUM.match(rest)
            if nm:
                num = f"{book_n}.{nm.group(1)}"
                text = rest[nm.end():].strip()
                level = len(hashes) - 1   # ## section → 1, ### subsection → 2
                if last_anchor:
                    toc.append((level, num, _strip_md(text), last_anchor))
                out.append(f"{hashes}# {num}. {text}")
            else:
                out.append(f"{hashes}# {rest}")   # unnumbered (e.g. Notes & Sources)
            last_anchor = None
            continue
        out.append(re.sub(r"\]\(#([^)]+)\)", lambda m: f"](#{prefix}-{m.group(1)})", line))
        last_anchor = None

    return toc, "\n".join(out)


def combine(chapters: list[tuple[int, str, str]], doc_title: str) -> str:
    """Build the book markdown from ``[(file_num, title, chapter_md), …]`` in order."""
    all_toc: list[tuple] = []
    sections: list[str] = []
    for book_n, (file_num, title, md) in enumerate(chapters, start=1):
        toc, section = _process_chapter(book_n, file_num, title, md)
        all_toc.extend(toc)
        sections.append(section)

    contents = ["## Contents", ""]
    for level, num, title, anchor in all_toc:
        contents.append(f"{'  ' * level}- [{num}. {title}](#{anchor})")
    head = [f"# {doc_title} — Study Notes", "", *contents, ""]
    # page-break before each chapter so Contents links land at a clean chapter start
    body = "\n\n<!--pagebreak-->\n\n".join(sections)
    return "\n".join(head) + "\n\n<!--pagebreak-->\n\n" + body + "\n"
