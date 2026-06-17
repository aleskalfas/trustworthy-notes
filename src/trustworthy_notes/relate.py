"""Wave 2, stage 5 — cross-page relations (term-blocked).

Per-page extraction can only relate statements on the same page (the 667 existing
intra-page relations). This stage adds the relations that only appear at chapter
scope — the argument structure across pages — using the same blocking discipline
as dedup: the Stage-4 term links bound the candidates (only statements that share
a *discriminating* term, across different pages), and a bounded model call per
chapter proposes typed relations among that focused set. Relations are proposals
with provenance, not asserted as fact; assembly carries them in (METHODOLOGY §4.6).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import anthropic
import yaml

from . import compose, workspace
from .extract_anthropic import ExtractionError

_TYPES = ["defines", "supports", "contrasts", "elaborates", "exemplifies", "motivates"]

SYSTEM_PROMPT = """You map the ARGUMENT STRUCTURE of a chapter: typed relations
between its notes that span DIFFERENT pages.

Each statement is given with its id, the page it is on, and the terms it concerns.
Identify pairs that are genuinely argumentatively related across pages:
- supports: one gives evidence or a reason for another
- contrasts: they present opposed or conflicting cases
- elaborates: one adds detail/specifics to another
- exemplifies: one is a concrete instance of another
- motivates: one gives the reason another question/aim exists
- defines: one fixes the meaning of a term the other uses

Only assert relations you are confident of from the texts; omit weak or merely
topical overlaps. Prefer FEW, strong relations. `from` and `to` must be statement
ids given to you. Return ONLY the structured object."""

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["relations"],
    "properties": {
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["from", "to", "type"],
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "type": {"type": "string", "enum": _TYPES},
                },
            },
        }
    },
}


def _page_of(key: str) -> int:
    return int(key.split(":")[0][1:])  # "p98:s-3" → 98


def _candidates(chapter_keys: list[str], links: dict[str, list[str]], max_group: int = 12) -> set[str]:
    """Statements that share a *discriminating* term (2..max_group uses in-chapter)
    with another statement on a different page — the term-blocked candidate set."""
    term_to_keys: dict[str, list[str]] = {}
    for k in chapter_keys:
        for tid in links.get(k, []):
            term_to_keys.setdefault(tid, []).append(k)
    out: set[str] = set()
    for keys in term_to_keys.values():
        if 2 <= len(keys) <= max_group and len({_page_of(k) for k in keys}) >= 2:
            out.update(keys)
    return out


def relations_for_chapter(
    statements: list[dict], *, client: "anthropic.Anthropic", model: str,
    effort: str = "low", max_tokens: int = 8000,
) -> list[dict]:
    """One bounded model call → proposed typed relations among a chapter's
    term-blocked candidate statements."""
    lines = []
    for s in statements:
        terms = ", ".join(s.get("terms", []))
        lines.append(f"[{s['key']}] ({s['type']}) {{{terms}}} {s['text']}")
    output_config: dict = {"format": {"type": "json_schema", "schema": _SCHEMA}}
    if effort:
        output_config["effort"] = effort
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": "\n".join(lines)}],
        output_config=output_config,
    ) as stream:
        response = stream.get_final_message()
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise ExtractionError(f"relation pass returned no output (stop_reason={response.stop_reason!r})")
    keys = {s["key"] for s in statements}
    rels = []
    for r in json.loads(text).get("relations", []):
        a, b, t = r.get("from"), r.get("to"), r.get("type")
        if a in keys and b in keys and a != b and t in _TYPES and _page_of(a) != _page_of(b):
            rels.append({"from": a, "to": b, "type": t})
    return rels


def build_relations(
    pdf_path: str | Path, work_dir: str | Path, *, model: str, effort: str = "low",
    api_key: Optional[str] = None, client: Optional["anthropic.Anthropic"] = None,
) -> list[dict]:
    """Discover cross-page relations chapter by chapter (term-blocked). Requires the
    Stage-4 term store (``terms.yaml``). Returns deduped ``[{from,to,type}]``."""
    terms_path = workspace.compose_stage_dir(work_dir, "terms") / "terms.yaml"
    if not terms_path.is_file():
        raise FileNotFoundError("terms.yaml not found — run `tn terms --build` first")
    links = (yaml.safe_load(terms_path.read_text(encoding="utf-8")) or {}).get("links", {})

    client = client or anthropic.Anthropic(api_key=api_key)
    notes = compose.load_page_sets(work_dir)
    found: list[dict] = []
    for ch in compose.chapter_map(pdf_path):
        if not compose._is_prose_section(ch["title"]):
            continue
        keys = [
            f"p{idx}:{s.get('id', '?')}"
            for idx in ch["page_indices"]
            for s in (notes.get(idx) or {}).get("statements", [])
        ]
        cand = _candidates(keys, links)
        if len(cand) < 2:
            continue
        statements = []
        for idx in ch["page_indices"]:
            for s in (notes.get(idx) or {}).get("statements", []):
                key = f"p{idx}:{s.get('id', '?')}"
                if key in cand:
                    statements.append(
                        {"key": key, "type": s.get("type"), "text": s.get("text", ""), "terms": links.get(key, [])}
                    )
        found.extend(relations_for_chapter(statements, client=client, model=model, effort=effort))

    seen = set()
    out = []
    for r in found:
        sig = (r["from"], r["to"], r["type"])
        if sig not in seen:
            seen.add(sig)
            out.append(r)
    return out
