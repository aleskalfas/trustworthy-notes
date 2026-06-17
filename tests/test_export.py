"""Wave 4 export — no network."""

from __future__ import annotations

from types import SimpleNamespace

from trustworthy_notes.export import study_document


class _FakeClient:
    def __init__(self, text: str):
        message = SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn")

        class _Stream:
            def __enter__(s):
                return s

            def __exit__(s, *e):
                return False

            def get_final_message(s):
                return message

        self.messages = SimpleNamespace(stream=lambda **kw: _Stream())


def _cset():
    return {
        "source": {"chapter_id": "CHAPTER 1", "chapter_title": "CHAPTER 1"},
        "terms": [{"id": "t-polygamy", "label": "polygamy"}],
        "evidence": [
            {"id": "e-1", "excerpt": "The king customarily had several wives in the Old Kingdom",
             "source": "body", "page_index": 13, "page_label": "3"},
            {"id": "e-2", "excerpt": "the small-scale portrayal of the wife", "source": "body",
             "page_index": 14, "page_label": "4"},
        ],
        "statements": [
            {"id": "s-1", "type": "claim", "text": "a", "evidence": ["e-1"]},
            {"id": "s-2", "type": "claim", "text": "b", "evidence": ["e-2"]},
        ],
        "relations": [],
    }


def test_export_numbers_headings_and_builds_toc():
    body = "# Title\n## Background\ntext\n### Detail\nmore"
    md = study_document(_cset(), client=_FakeClient(body), model="m")["markdown"]
    assert "## 1. Background" in md and "### 1.1. Detail" in md   # numbered
    assert '<a id="sec-1"></a>' in md                             # anchor injected
    assert "- [1. Background](#sec-1)" in md                      # clickable TOC entry
    assert "## Contents" in md


def test_export_links_citations_to_anchored_notes():
    body = "## S\n- first point [s-1, s-2]"
    md = study_document(_cset(), client=_FakeClient(body), model="m")["markdown"]
    assert "[s-1](#note-s-1), [s-2](#note-s-2)" in md             # citations become links
    assert '<a id="note-s-1"></a>' in md                         # anchored appendix entry
    assert "— p.3 (body)" in md                                   # verbatim evidence + page


def test_export_cites_page_as_plain_text():
    body = "## S\n- point [s-1]"
    md = study_document(_cset(), client=_FakeClient(body), model="m")["markdown"]
    assert "— p.3 (body)" in md   # plain-text page citation (printed label)
    assert "#page=" not in md      # no fragile cross-PDF link
    assert "](../" not in md        # no source-file link


def test_export_citations_keep_line_breaks_and_join_adjacent():
    # adjacent [s-1][s-2] → one comma-joined set; the newline before "two" survives
    body = "## S\n- one [s-1][s-2]\n- two [s-1]"
    md = study_document(_cset(), client=_FakeClient(body), model="m")["markdown"]
    assert "- one [s-1](#note-s-1), [s-2](#note-s-2)" in md
    assert "\n- two [s-1](#note-s-1)" in md   # bullet line break preserved


def test_export_flags_stray_citations():
    body = "## S\n- real [s-1]\n- invented [s-99]"
    res = study_document(_cset(), client=_FakeClient(body), model="m")
    assert res["unknown"] == ["s-99"]
    assert res["cited"] == {"s-1"}
    assert "⚠" in res["markdown"]
    assert "[s-99](#note-s-99)" not in res["markdown"]            # stray not linked


def test_strip_citations_removes_inline_cites_and_appendix():
    from trustworthy_notes.export import strip_citations
    md = (
        "## 1. Background\n"
        "- Kings had several wives [s-1](#note-s-1), [s-2](#note-s-2).\n"
        "- A nested point [s-3](#note-s-3)\n"
        "  - deeper still [s-4]\n"
        "\n---\n## Notes & Sources\n\n"
        "<a id=\"note-s-1\"></a>\n**[s-1]** _claim_ — text\n> quote\n> — p.3 (body)\n"
    )
    out = strip_citations(md)
    assert "[s-" not in out                      # no citation tokens anywhere
    assert "Notes & Sources" not in out          # appendix gone
    assert "Kings had several wives." in out     # punctuation tidied (no dangling space)
    assert "  - deeper still" in out             # nested-bullet indentation preserved
    assert "## 1. Background" in out             # headings + prose kept
