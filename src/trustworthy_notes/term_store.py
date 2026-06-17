"""Wave 2, stage 4 — the document-global term store.

A Term is document-global by definition (METHODOLOGY §4.1), so it is derived at
compose, not per page (per-page extraction collapsed under low effort). One
bounded model pass per chapter names that chapter's controlled vocabulary; code
then deduplicates the labels across chapters into a single store and links each
statement to the terms whose label it mentions. The model only *names* concepts;
the linking is mechanical.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Optional

import anthropic

from . import compose
from .extract_anthropic import ExtractionError

SYSTEM_PROMPT = """You identify the controlled VOCABULARY of a scholarly chapter:
the recurring, named technical/domain concepts it uses (e.g. "polygamy",
"consanguineous marriage", "false door", "offering formula", "eldest son").

Return canonical short noun-phrase labels, deduplicated, lowercase unless a
proper noun. Exclude generic words ("study", "evidence", "page", "woman", "tomb",
"figure") and one-off mentions. Aim for the ~5-25 concepts a reader would index.
Return ONLY the structured object."""

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["terms"],
    "properties": {"terms": {"type": "array", "items": {"type": "string"}}},
}


_IRREGULAR = {"wives": "wife", "lives": "life", "children": "child",
              "women": "woman", "men": "man", "feet": "foot", "teeth": "tooth"}


def _singularize(word: str) -> str:
    """Crude singular of one lowercased token (for the dedup/match key only)."""
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    if len(word) <= 3 or word.endswith("ss"):
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("ses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    return word[:-1] if word.endswith("s") else word


def _slug(label: str) -> str:
    """Stable kebab id. Accent-fold first so transliteration reads as base letters
    (ḥm.t → t-hm-t, not t-m-t)."""
    folded = "".join(c for c in unicodedata.normalize("NFKD", label) if not unicodedata.combining(c))
    return "t-" + re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")


def _norm(text: str) -> str:
    """Match/dedup key: lowercase, singularize each word, so 'half-siblings' and
    'half-sibling', 'inscription(s)', 'wife/wives' collapse to one term."""
    return " ".join(_singularize(t) for t in text.lower().split())


def terms_for_chapter(
    statement_texts: list[str], *, client: "anthropic.Anthropic", model: str,
    effort: str = "low", max_tokens: int = 4000,
) -> list[str]:
    """Ask the model for one chapter's vocabulary labels (bounded input)."""
    msg = "Notes from one chapter:\n" + "\n".join(f"- {t}" for t in statement_texts)
    output_config: dict = {"format": {"type": "json_schema", "schema": _SCHEMA}}
    if effort:
        output_config["effort"] = effort
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": msg}],
        output_config=output_config,
    ) as stream:
        response = stream.get_final_message()
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise ExtractionError(f"term extractor returned no output (stop_reason={response.stop_reason!r})")
    return [t.strip() for t in json.loads(text).get("terms", []) if t.strip()]


def build_store(
    pdf_path: str | Path, work_dir: str | Path, *, model: str, effort: str = "low",
    api_key: Optional[str] = None, client: Optional["anthropic.Anthropic"] = None,
) -> dict:
    """Build the document-global term store and statement→term links.

    Returns ``{"terms": [{"id","label","count"}], "links": {statement_key: [ids]}}``.
    One model call per prose chapter; label dedup and linking are mechanical.
    """
    client = client or anthropic.Anthropic(api_key=api_key)
    notes = compose.load_page_sets(work_dir)
    chapters = compose.chapter_map(pdf_path)

    # 1) per prose chapter, the model names its vocabulary
    label_count: dict[str, int] = {}
    label_surface: dict[str, str] = {}
    for ch in chapters:
        if not compose._is_prose_section(ch["title"]):
            continue
        texts = [
            s.get("text", "")
            for idx in ch["page_indices"]
            for s in (notes.get(idx) or {}).get("statements", [])
            if s.get("text")
        ]
        if not texts:
            continue
        for label in terms_for_chapter(texts, client=client, model=model, effort=effort):
            key = _norm(label)
            label_count[key] = label_count.get(key, 0) + 1
            label_surface.setdefault(key, label)

    # 2) one global store (dedup by normalized label), id by slug
    terms = []
    seen_ids: set[str] = set()
    for key, count in sorted(label_count.items(), key=lambda kv: (-kv[1], kv[0])):
        tid = _slug(label_surface[key])
        if not tid or tid in seen_ids:
            continue
        seen_ids.add(tid)
        terms.append({"id": tid, "label": label_surface[key], "count": count})

    # 3) link statements to terms whose label they mention (mechanical substring)
    links: dict[str, list[str]] = {}
    for idx in sorted(notes):
        for s in notes[idx].get("statements", []):
            ntext = _norm(s.get("text", ""))
            hit = [t["id"] for t in terms if _norm(t["label"]) in ntext]
            if hit:
                links[f"p{idx}:{s.get('id', '?')}"] = hit
    return {"terms": terms, "links": links}
