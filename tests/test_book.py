"""Combining per-chapter exports into one book — names, namespacing, nested TOC."""

from __future__ import annotations

from trustworthy_notes.book import _process_chapter, combine

CH = """<!-- comment -->
# CHAPTER 1 — Study Notes
*doc · PDF pages 13–16*

## Contents

- [1. Background](#sec-1)

<a id="sec-1"></a>
## 1. Background

- a point [s-1](#note-s-1)

<a id="sec-1-1"></a>
### 1.1. Detail

more

---
## Notes & Sources

<a id="note-s-1"></a>
**[s-1]** _claim_ — text
> quote
> — p.3 (body)
"""

NAME = "CHAPTER 1: AIMS AND OBJECTIVES"


def test_process_chapter_uses_passed_title_namespaces_demotes_renumbers():
    toc, sec = _process_chapter(book_n=2, file_num=6, title=NAME, md=CH)
    assert f"## 2. {NAME}" in sec                          # full chapter name, numbered by book_n
    assert '<a id="c006-chap"></a>' in sec
    assert "### 2.1. Background" in sec                     # ## → ###, renumbered 1.→2.1.
    assert "#### 2.1.1. Detail" in sec                      # ### → ####, 1.1.→2.1.1.
    assert '<a id="c006-sec-1"></a>' in sec                 # anchors namespaced
    assert "[s-1](#c006-note-s-1)" in sec                   # citation link namespaced
    assert "## Contents" not in sec                         # per-chapter Contents dropped
    # hierarchical TOC entries
    assert (0, "2", NAME, "c006-chap") in toc
    assert (1, "2.1", "Background", "c006-sec-1") in toc
    assert (2, "2.1.1", "Detail", "c006-sec-1-1") in toc


def test_combine_builds_nested_master_contents_with_names():
    bk = combine([(6, NAME, CH), (9, "CHAPTER 2: DATA", CH)], doc_title="MyDoc")
    assert "# MyDoc — Study Notes" in bk
    assert f"- [1. {NAME}](#c006-chap)" in bk               # chapter with full name
    assert "  - [1.1. Background](#c006-sec-1)" in bk        # nested section
    assert "    - [1.1.1. Detail](#c006-sec-1-1)" in bk      # nested subsection
    assert "- [2. CHAPTER 2: DATA](#c009-chap)" in bk        # second chapter, distinct prefix
