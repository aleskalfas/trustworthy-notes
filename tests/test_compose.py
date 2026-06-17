"""Wave 2 stage 0–1: de-spacing, section keys, chapter grouping, page-set loading."""

from __future__ import annotations

import yaml

from trustworthy_notes.compose import (
    _despace,
    _ends_open,
    _group,
    _merge_oscillating,
    _section_key,
    dedup_candidates,
    load_page_sets,
    stitch_tail,
)


def _write_pages(work_dir, pages: dict[int, dict]):
    ex = work_dir / "1-extract"
    ex.mkdir(parents=True, exist_ok=True)
    for idx, data in pages.items():
        (ex / f"page-{idx:04d}.notes.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def test_dedup_clusters_same_type_statements_sharing_evidence(tmp_path):
    shared = "the king customarily had a number of wives during the old kingdom period"
    _write_pages(
        tmp_path,
        {
            13: {
                "evidence": [{"id": "e-1", "excerpt": shared}],
                "statements": [{"id": "s-1", "type": "claim", "text": "kings had many wives", "evidence": ["e-1"]}],
            },
            20: {
                "evidence": [{"id": "e-1", "excerpt": shared}],
                "statements": [{"id": "s-1", "type": "claim", "text": "the king had several wives", "evidence": ["e-1"]}],
            },
        },
    )
    clusters = dedup_candidates(tmp_path)
    assert len(clusters) == 1
    assert {s["key"] for s in clusters[0]} == {"p13:s-1", "p20:s-1"}


def test_assemble_chapter_applies_merge_terms_and_validates():
    from trustworthy_notes.compose import _assemble_chapter
    from trustworthy_notes.validation import validate_structure

    ch = {"key": "CHAPTER 1", "title": "CHAPTER 1", "page_indices": [13, 14], "page_numbers": [14, 15]}
    notes = {
        13: {
            "evidence": [{"id": "e-1", "excerpt": "kings had wives", "source": "body"}],
            "statements": [{"id": "s-1", "type": "claim", "text": "kings had wives", "evidence": ["e-1"]}],
            "relations": [],
        },
        14: {
            "evidence": [{"id": "e-1", "excerpt": "the king had several wives", "source": "body"}],
            "statements": [{"id": "s-1", "type": "claim", "text": "king had wives", "evidence": ["e-1"]}],
            "relations": [],
        },
    }
    cset = _assemble_chapter(
        ch, notes,
        merges=[{"members": ["p13:s-1", "p14:s-1"], "text": "The king customarily had several wives."}],
        xrels=[],
        links={"p13:s-1": ["t-polygamy"], "p14:s-1": ["t-polygamy"]},
        term_label={"t-polygamy": "polygamy"},
        document="Doc",
    )
    assert validate_structure(cset) == []                       # schema + referential valid
    assert cset["source"]["scope"] == "chapter"
    assert cset["source"]["page_range"] == [13, 14]
    assert len(cset["statements"]) == 1                          # the two merged into one
    assert cset["statements"][0]["text"] == "The king customarily had several wives."
    assert len(cset["statements"][0]["evidence"]) == 2          # evidence unioned from both pages
    assert cset["statements"][0]["terms"] == ["t-polygamy"]
    assert cset["terms"] == [{"id": "t-polygamy", "label": "polygamy"}]
    assert all("page_index" in e for e in cset["evidence"])     # each evidence tagged with origin page


def test_assemble_chapter_maps_cross_page_relation():
    from trustworthy_notes.compose import _assemble_chapter
    from trustworthy_notes.validation import validate_structure

    ch = {"key": "C", "title": "C", "page_indices": [1, 2], "page_numbers": [2, 3]}
    notes = {
        1: {"evidence": [{"id": "e-1", "excerpt": "aa", "source": "body"}],
            "statements": [{"id": "s-1", "type": "claim", "text": "a", "evidence": ["e-1"]}], "relations": []},
        2: {"evidence": [{"id": "e-1", "excerpt": "bb", "source": "body"}],
            "statements": [{"id": "s-1", "type": "claim", "text": "b", "evidence": ["e-1"]}], "relations": []},
    }
    cset = _assemble_chapter(
        ch, notes, merges=[], xrels=[{"from": "p1:s-1", "to": "p2:s-1", "type": "supports"}],
        links={}, term_label={}, document="D",
    )
    assert validate_structure(cset) == []
    assert cset["relations"] == [{"from": "s-1", "to": "s-2", "type": "supports"}]  # keys mapped to final ids


def test_dedup_does_not_cluster_across_types(tmp_path):
    shared = "the same long verbatim excerpt cited by two differently typed notes here"
    _write_pages(
        tmp_path,
        {
            5: {
                "evidence": [{"id": "e-1", "excerpt": shared}],
                "statements": [
                    {"id": "s-1", "type": "claim", "text": "a claim", "evidence": ["e-1"]},
                    {"id": "s-2", "type": "background", "text": "a background fact", "evidence": ["e-1"]},
                ],
            }
        },
    )
    assert dedup_candidates(tmp_path) == []  # different types → not duplicates


def test_ends_open_detects_midsentence_cut():
    assert _ends_open("best explained as an")          # truncated → open
    assert not _ends_open("Chapter 9: Children.")        # complete sentence
    assert not _ends_open("a love of learning'")         # closes with a quote


def test_stitch_tail_completes_quote_across_page_break():
    body_n = "Swinton concluded that the wife is perhaps best explained as an"
    body_next = "artistic device that derived from these new scenes. A new paragraph follows."
    full = stitch_tail("the wife is perhaps best explained as an", body_n, body_next)
    assert full == "the wife is perhaps best explained as an artistic device that derived from these new scenes."


def test_stitch_tail_skips_complete_sentences():
    # excerpt ends a sentence → not a truncation → no stitch
    assert stitch_tail("discussed in Chapter 9.", "text discussed in Chapter 9.", "Next page.") is None


def test_stitch_tail_requires_excerpt_at_page_end():
    # excerpt is open-ended but NOT flush at page end → not a boundary truncation
    assert stitch_tail("explained as an", "explained as an extra tail here", "more text.") is None


def test_despace_strips_cid_glyph_artifact():
    assert _despace("I NDEX OF M ONUMENTS : G IZA (cid:3)") == "INDEX OF MONUMENTS : GIZA"


def test_section_key_merges_cid_variants():
    assert _section_key("INDEX OF MONUMENTS : GIZA") == _section_key(
        "INDEX OF MONUMENTS : GIZA (cid:3)"
    )


def _ch(key, *pages):
    return {"key": key, "title": key.title(), "page_numbers": list(pages),
            "page_indices": [p - 1 for p in pages]}


def test_merge_oscillating_collapses_alternating_table_headers():
    chapters = [
        _ch("CHAPTER 9", 1, 2, 3),
        _ch("TABLE B: WIVES", 4), _ch("ACCESSORIES", 5),
        _ch("TABLE B: WIVES", 6), _ch("ACCESSORIES", 7),
        _ch("TABLE B: WIVES", 8),
        _ch("CHAPTER 10", 9, 10),
    ]
    merged = _merge_oscillating(chapters)
    keys = [c["key"] for c in merged]
    assert keys == ["CHAPTER 9", "TABLE B: WIVES", "CHAPTER 10"]
    table = next(c for c in merged if c["key"] == "TABLE B: WIVES")
    assert table["page_numbers"] == [4, 5, 6, 7, 8]   # the whole table, one section
    assert table["title"] == "Table B: Wives"          # the ':' side wins the title


def test_merge_oscillating_keeps_two_adjacent_short_chapters():
    # CH7 then PART THREE then CH8 — distinct keys, runs never reach min_run=3 → unchanged
    chapters = [_ch("CHAPTER 7", 1), _ch("PART THREE", 2), _ch("CHAPTER 8", 3, 4)]
    assert [c["key"] for c in _merge_oscillating(chapters)] == [
        "CHAPTER 7", "PART THREE", "CHAPTER 8"
    ]


def test_despace_merges_smallcaps_initials():
    assert _despace("C HAPTER 1: A IMS AND O BJECTIVES") == "CHAPTER 1: AIMS AND OBJECTIVES"
    assert _despace("T ABLE B: D EPICTIONS OF W IVES") == "TABLE B: DEPICTIONS OF WIVES"
    assert _despace("B IBLIOGRAPHY") == "BIBLIOGRAPHY"


def test_section_key_collapses_chapter_variants():
    # opening page and running header of the same chapter share a key
    assert _section_key("C HAPTER 5") == "CHAPTER 5"
    assert _section_key("C HAPTER 5: S ISTERS OF THE T OMB O WNER") == "CHAPTER 5"
    # non-chapter sections key by full text
    assert _section_key("B IBLIOGRAPHY") == "BIBLIOGRAPHY"
    assert _section_key("T ABLE B: D EPICTIONS OF W IVES") == "TABLE B: DEPICTIONS OF WIVES"


def test_group_forward_fills_and_collapses_variants():
    BOOK = "THE BOOK TITLE"           # most frequent → book title, never a boundary
    tops = [
        "",                            # 1 cover → front matter
        BOOK,                          # 2 recto, book title → still front matter
        "C HAPTER 1",                  # 3 chapter 1 opens
        BOOK,                          # 4 recto, inherits ch1
        "C HAPTER 1: A IMS",           # 5 running header, same key → still ch1
        "C HAPTER 2: D ATA",           # 6 chapter 2 opens
        BOOK,                          # 7 inherits ch2
        "B IBLIOGRAPHY",               # 8 back matter
    ]
    headers = {BOOK, "C HAPTER 1", "C HAPTER 1: A IMS", "C HAPTER 2: D ATA", "B IBLIOGRAPHY"}
    chapters = _group(list(range(1, 9)), tops, headers)
    keys = [c["key"] for c in chapters]
    assert keys == ["FRONT-MATTER", "CHAPTER 1", "CHAPTER 2", "BIBLIOGRAPHY"]
    by_key = {c["key"]: c["page_numbers"] for c in chapters}
    assert by_key["FRONT-MATTER"] == [1, 2]
    assert by_key["CHAPTER 1"] == [3, 4, 5]   # opening + recto + running header all one chapter
    assert by_key["CHAPTER 2"] == [6, 7]
    assert by_key["BIBLIOGRAPHY"] == [8]


def test_load_page_sets(tmp_path):
    extract = tmp_path / "1-extract"
    extract.mkdir()
    (extract / "page-0013.notes.yaml").write_text(
        yaml.safe_dump({"statements": [{"id": "s-1"}]}), encoding="utf-8"
    )
    (extract / "page-0007.notes.yaml").write_text(yaml.safe_dump({"statements": []}), encoding="utf-8")
    sets = load_page_sets(tmp_path)   # takes the work dir; looks in 1-extract/
    assert set(sets) == {7, 13}
    assert len(sets[13]["statements"]) == 1
