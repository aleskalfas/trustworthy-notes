"""§7.6 gap report — advisory coverage check.

The mechanical checks (``validation.py``) prove the notes that EXIST are sound.
The gap report addresses the opposite risk: source content that *no* evidence
covers — content that may have been silently dropped. Per METHODOLOGY §7.6 this
is **heuristic and advisory**, never a pass/fail gate: it splits a page's body
(and footnotes) into sentences and flags those that little or no evidence
excerpt overlaps, so a human can confirm each gap is page furniture / repetition
rather than lost content.

It works entirely in normalized space (``normalize_for_match``), so the same
folding that lets a quote anchor (curly quotes, soft-wrap, footnote markers)
also governs what counts as "covered" — body text and evidence are compared on
equal terms.
"""

from __future__ import annotations

import re
from typing import Any

from .normalize import normalize_for_match

# Split normalized text into sentences: after .!? and before a capital/quote/paren.
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z'\"(])")
# Ignore tiny fragments (list joiners like "This involves:", stray tokens) — too
# short to be "lost content" worth a human's attention.
_MIN_SENTENCE = 15


def _covered_intervals(norm_stream: str, excerpts: list[str]) -> list[tuple[int, int]]:
    """Merged [start, end) spans of ``norm_stream`` that some excerpt covers."""
    spans: list[tuple[int, int]] = []
    for ex in excerpts:
        ne = normalize_for_match(ex)
        if not ne:
            continue
        start = norm_stream.find(ne)
        if start >= 0:
            spans.append((start, start + len(ne)))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _overlap(a: int, b: int, intervals: list[tuple[int, int]]) -> int:
    return sum(max(0, min(b, y) - max(a, x)) for x, y in intervals)


def _stream_report(stream: str, excerpts: list[str], threshold: float) -> dict[str, Any]:
    norm = normalize_for_match(stream)
    if not norm:
        return {"total_chars": 0, "covered_chars": 0, "ratio": 1.0, "gaps": []}
    intervals = _covered_intervals(norm, excerpts)
    covered = sum(b - a for a, b in intervals)
    gaps: list[dict[str, Any]] = []
    pos = 0
    for sent in _SENT_SPLIT.split(norm):
        s = sent.strip()
        if len(s) < _MIN_SENTENCE:
            continue
        idx = norm.find(s, pos)
        if idx < 0:
            idx = norm.find(s)
        if idx < 0:
            continue
        pos = idx + len(s)
        frac = _overlap(idx, idx + len(s), intervals) / len(s)
        if frac < threshold:
            gaps.append({"text": s, "coverage": round(frac, 2)})
    return {
        "total_chars": len(norm),
        "covered_chars": covered,
        "ratio": round(covered / len(norm), 3),
        "gaps": gaps,
    }


def gap_report(notes: dict[str, Any], page, threshold: float = 0.5) -> dict[str, Any]:
    """Coverage of one page by its notes' evidence (METHODOLOGY §7.6).

    Returns ``{"body": {...}, "footnotes": {...}}`` where each stream report has
    ``total_chars``, ``covered_chars``, ``ratio`` (0..1), and ``gaps`` — the
    sentences whose covered fraction is below ``threshold``, for human review.
    """
    ev = [e for e in notes.get("evidence", []) if e.get("kind", "text") == "text"]
    body_ex = [e.get("excerpt", "") for e in ev if e.get("source") == "body"]
    fn_ex = [e.get("excerpt", "") for e in ev if e.get("source") == "footnote"]
    return {
        "body": _stream_report(page.text or "", body_ex, threshold),
        "footnotes": _stream_report(page.footnotes or "", fn_ex, threshold),
    }
