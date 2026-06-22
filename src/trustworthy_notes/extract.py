"""Wave 1 — extract a notes-set from a single page.

The extractor is **provider-agnostic**: any `Extractor` turns a page (plus
optional context) into a notes-set; an LLM adapter is one implementation, swapped
in later. Whatever the extractor returns, `run_extract` applies the **anchor
gate** — the production side of the trust guarantee (METHODOLOGY §7.2): every
`text` evidence quote must verbatim-resolve against the page, or it is dropped,
and any statement left ungrounded is dropped with it. So nothing the model merely
*asserts* survives without source backing; hallucinated quotes can't leak in.

The page's identity (document, page_index/label) is authoritative and set from
the `PageText` — never trusted from the model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol

import yaml

from .models import PageText
from .normalize import quote_is_anchored


class Extractor(Protocol):
    """Turns a page (+ optional context) into a notes-set dict (schema shape)."""

    def extract(self, page: PageText, context: Optional[dict] = None) -> dict: ...


def anchor_gate(notes: dict, page: PageText) -> tuple[dict, list[dict]]:
    """Enforce grounding: drop unanchored evidence, then ungrounded statements.

    Steps, in order:
      1. each `text` evidence must resolve verbatim in its source stream, else
         it is dropped (`figure`/`table` are reserved — kept, not yet verifiable);
      2. a statement survives only if it still references >= 1 anchored evidence;
      3. prune evidence/terms/relations down to what the survivors use.

    Returns (cleaned_notes, dropped) where `dropped` records what was removed and
    why — the audit trail of what the model produced that the source didn't back.
    """
    dropped: list[dict] = []

    anchored: dict[str, dict] = {}
    for e in notes.get("evidence", []):
        if e.get("kind", "text") != "text":
            anchored[e["id"]] = e  # reserved kinds can't be verified yet
            continue
        stream = page.text if e.get("source") == "body" else page.footnotes
        if quote_is_anchored(e.get("excerpt", ""), stream):
            anchored[e["id"]] = e
        else:
            dropped.append({"kind": "evidence", "id": e["id"], "reason": "quote not found on page"})

    statements = []
    for s in notes.get("statements", []):
        refs = [r for r in s.get("evidence", []) if r in anchored]
        if refs:
            statements.append({**s, "evidence": refs})
        else:
            dropped.append({"kind": "statement", "id": s["id"], "reason": "ungrounded after anchor gate"})

    used_ev = {r for s in statements for r in s["evidence"]}
    evidence = [e for e in notes.get("evidence", []) if e["id"] in used_ev and e["id"] in anchored]
    used_terms = {t for s in statements for t in s.get("terms", [])}
    terms = [t for t in notes.get("terms", []) if t["id"] in used_terms]
    nodes = {s["id"] for s in statements} | used_terms
    relations = [
        r for r in notes.get("relations", []) if r.get("from") in nodes and r.get("to") in nodes
    ]

    cleaned = {
        "schema_version": notes.get("schema_version", 1),
        "source": notes.get("source", {}),
        "terms": terms,
        "evidence": evidence,
        "statements": statements,
        "relations": relations,
    }
    # Carry the generation provenance through unchanged when present (issue #98); the
    # gate rebuilds the notes dict from the survivors, so an additive top-level block
    # would otherwise be dropped. Omitted when absent, keeping pre-#98 notes unchanged.
    if "generation" in notes:
        cleaned["generation"] = notes["generation"]
    return cleaned, dropped


def _generation_of(extractor: Extractor) -> Optional[dict]:
    """The extractor's generation settings as a stamp block, or None if unavailable.

    Reads ``model``/``effort``/``max_tokens`` off the extractor instance — the settings
    that *produced* the notes (issue #98). Recorded per page so the fact rides along for
    free through note-copying capture and lets ``eval`` detect a doc whose pages were
    generated under *mixed* settings (ADR-007). An extractor that exposes none of these
    (a bare test stub) yields None, so the block is simply omitted — backward-compatible
    with notes made before the field existed (they read as "unknown" generation).
    """
    model = getattr(extractor, "model", None)
    effort = getattr(extractor, "effort", None)
    max_tokens = getattr(extractor, "max_tokens", None)
    if model is None and effort is None and max_tokens is None:
        return None
    return {"model": model, "effort": effort, "max_tokens": max_tokens}


def _finalize(
    raw: dict,
    page: PageText,
    document: str,
    generation: Optional[dict] = None,
) -> tuple[dict, list[dict]]:
    """Stamp the authoritative source onto a raw notes dict, then anchor-gate.

    ``generation`` (the model/effort/max-tokens that made these notes, issue #98) is
    stamped beside the per-page ``source`` block when supplied; omitted when None so
    notes stay valid without it (the field is additive — ADR-007). It is the production
    settings of the *notes*, distinct from the out-of-band token ``usage`` a caller may
    also collect, which stays a pricing concern and never enters the notes payload.
    """
    source = {"document": document, "scope": "page", "page_index": page.page_index}
    if page.page_label is not None:
        source["page_label"] = page.page_label
    raw = {**raw, "schema_version": 1, "source": source}
    if generation is not None:
        raw["generation"] = generation
    return anchor_gate(raw, page)


def run_extract(
    page: PageText, extractor: Extractor, document: str, context: Optional[dict] = None
) -> tuple[dict, list[dict]]:
    """Extract a page's notes, stamp the authoritative source, and anchor-gate."""
    raw = extractor.extract(page, context)
    return _finalize(raw, page, document, _generation_of(extractor))


def run_extract_with_usage(
    page: PageText, extractor: Extractor, document: str, context: Optional[dict] = None
) -> tuple[dict, list[dict], Optional[object]]:
    """Like ``run_extract`` but also returns the provider's token ``usage``.

    Uses the extractor's ``extract_with_usage`` when available (the Anthropic
    adapter), falling back to ``extract`` (usage ``None``) for any extractor that
    only implements the base protocol. The usage object is what
    ``pricing.estimate_cost`` consumes.
    """
    fn = getattr(extractor, "extract_with_usage", None)
    if fn is not None:
        raw, usage = fn(page, context)
    else:
        raw, usage = extractor.extract(page, context), None
    notes, dropped = _finalize(raw, page, document, _generation_of(extractor))
    return notes, dropped, usage


def write_notes(notes: dict, path: str | Path) -> None:
    """Persist a notes-set to YAML (Unicode preserved for transliteration)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(notes, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
