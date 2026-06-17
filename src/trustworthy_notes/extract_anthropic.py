"""Wave 1 — the Anthropic (Claude) extractor.

An `Extractor` (see ``trustworthy_notes.extract``) that turns a page into a notes-set by
calling Claude. This file is Claude/Anthropic-specific by design; a different
provider would be a separate adapter behind the same protocol.

Design:
- The model returns a *simple intermediate* (statements with inline verbatim
  evidence, terms by label, relations by local key) — no id bookkeeping. We then
  **assemble** the canonical notes-set, assigning `t-`/`s-`/`e-` ids. This keeps
  the model's job easy and id discipline ours.
- Output is constrained with structured outputs (``output_config.format``), and
  the methodology rules live in a prompt-cached system prompt (same every page →
  cheap across a whole document).
- Whatever the model returns, ``run_extract``'s anchor gate drops any excerpt
  that isn't verbatim on the page — so hallucinated quotes can't survive.

Defaults: ``claude-opus-4-8``, adaptive thinking, ``effort: medium``.
"""

from __future__ import annotations

import json
import re
from typing import Optional

import anthropic

from .models import PageText

MODEL = "claude-opus-4-8"


class ExtractionError(RuntimeError):
    """The model call returned no usable output for a page (e.g. token-budget
    exhausted by thinking). Raised so a batch run can skip/retry one page rather
    than abort."""

SYSTEM_PROMPT = """You extract TRUSTWORTHY NOTES from one page of a scholarly document.

These notes are not a summary. They re-represent the page's knowledge as small,
atomic, source-anchored pieces. Follow these rules exactly.

THE MODEL
- Term: a named concept the page uses (e.g. "polygamy"). A label only — not a claim.
- Statement: one atomic piece of knowledge, with:
  - type: definition | claim | method | question | background
      definition = fixes the meaning of a term
      claim      = an assertion that something is the case
      method     = what the study/author does (aims, scope, procedure)
      question   = an open question, aim, or hypothesis
      background = an accepted or contextual fact the author relies on
  - basis: author (default) | author-data (the author's own finding from her
      data) | reported (attributed to someone else).
  - text: YOUR wording of the idea; it MAY paraphrase for clarity.
  - evidence: one or more VERBATIM excerpts that prove it (see below).
  - terms: labels of the terms it is about (optional).
  - key: a short local id you choose (e.g. "s1"), used only to link relations.
- Evidence: a verbatim excerpt copied EXACTLY from the page text given to you:
  - excerpt: copied character-for-character from the BODY or FOOTNOTES below. Do
      NOT paraphrase, normalize, correct, or translate it. Keep any "[^N]"
      footnote markers and "⟨glyph-…⟩" placeholders exactly as they appear.
  - source: "body" or "footnote" — which section the excerpt came from.
  - locator: the footnote number, when the excerpt is from a footnote (optional).
  - script: "latin" (default) or "egyptian-transliteration" when the excerpt is
      transliterated source text (e.g. "ḥm.t=f").
- Relation: a labelled link between two statement keys (or a statement key and a
  term label): defines | supports | contrasts | elaborates | exemplifies | motivates.

RULES
- ONE IDEA PER STATEMENT. If you would join two ideas with "and", make two.
- COVER THE WHOLE PAGE. Sweep it top to bottom; every substantive sentence must
  end up in some statement. Do not summarize the page down to its highlights —
  prefer more atomic statements over compression. In particular, always capture
  the study's stated SUBJECTS, AIMS, and SCOPE when the page states them.
- LISTS: when the page enumerates items, make a PARENT statement for the set plus
  one CHILD statement PER ITEM, and link each child to the parent with an
  "elaborates" relation. Capture EVERY item — never drop or merge list items, even
  if there are many. If the page says "six" things, you produce six children.
- QUOTED SPEECH: when the body quotes someone's words (text in quotation marks
  attributed to a person), the QUOTED WORDS themselves are the evidence. Capture
  the quotation verbatim as body evidence (source: body) on a `reported` claim,
  AND attach the footnote citation as a second evidence item (source: footnote).
  Never replace the quotation with only its citation.
- EVIDENCE IS VERBATIM AND FROM THIS PAGE ONLY. Every excerpt must appear,
  exactly, in the BODY or FOOTNOTES text provided. If you cannot find a verbatim
  excerpt for a claim, do not make the claim. Context pages are for understanding
  only — never take evidence from them.
- A footnote that merely cites a source (e.g. "Robins (1993).") is supporting
  evidence on the body statement it backs (source: footnote), not its own
  statement. When the body names the studies/authors a footnote cites, attach
  BOTH the body sentence and those footnote citations to the same statement.
- TERMS ARE VOCABULARY, NOT DESCRIPTION. Be sparing — prefer FEWER terms. Coin a
  term only for a concept the page treats as a named, recurring technical idea
  (e.g. "polygamy", "consanguineous marriage"). Do NOT make terms out of ordinary
  descriptive noun phrases that merely say who or what is being discussed
  ("elite bureaucrats", "funerary chapels", "Old Kingdom family", "institution of
  marriage"). A parenthetical gloss like "(sẖ n sꜥnḫ)" stays inside the statement
  text and is never its own term.
- BASIS. Use "reported" ONLY when the CONTENT of the claim is attributed to
  another named person or source ("Bryant states…", "Johnson argues…"). The
  author's own statements are "author" (the default) — including her descriptions
  of what other studies exist or what areas they cover. A bibliographic mention
  ("studies by Robins, Watterson… cover social and legal positions") is an AUTHOR
  statement, not a reported claim. Use "author-data" only for a finding the author
  draws from her own data.

Return ONLY the structured object."""


# Intermediate the model returns. Structured-output friendly: no patterns,
# no minLength/minItems (those constraints are unsupported and would be stripped).
_INTERMEDIATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["statements"],
    "properties": {
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label"],
                "properties": {"label": {"type": "string"}},
            },
        },
        "statements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["key", "type", "text", "evidence"],
                "properties": {
                    "key": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["definition", "claim", "method", "question", "background"],
                    },
                    "basis": {
                        "type": "string",
                        "enum": ["author", "author-data", "reported"],
                    },
                    "text": {"type": "string"},
                    "terms": {"type": "array", "items": {"type": "string"}},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["excerpt", "source"],
                            "properties": {
                                "excerpt": {"type": "string"},
                                "source": {"type": "string", "enum": ["body", "footnote"]},
                                "locator": {"type": "string"},
                                "script": {
                                    "type": "string",
                                    "enum": ["latin", "egyptian-transliteration"],
                                },
                            },
                        },
                    },
                },
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["from", "to", "type"],
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": [
                            "defines",
                            "supports",
                            "contrasts",
                            "elaborates",
                            "exemplifies",
                            "motivates",
                        ],
                    },
                },
            },
        },
    },
}


def _slug(text: str, prefix: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"
    return f"{prefix}-{s}"


def assemble(raw: dict) -> dict:
    """Convert the model's intermediate output into a canonical notes-set dict.

    Assigns `t-`/`s-`/`e-` ids, builds the evidence store, and resolves relation
    endpoints (statement keys or term labels). `source` is added later by
    `run_extract`; the anchor gate then drops any non-verbatim evidence.
    """
    term_id_by_label: dict[str, str] = {}
    terms: list[dict] = []

    def term_id(label: str) -> str:
        label = label.strip()
        if label in term_id_by_label:
            return term_id_by_label[label]
        tid = _slug(label, "t")
        # guard against two labels colliding to one slug
        if any(t["id"] == tid for t in terms):
            tid = f"{tid}-{len(terms)}"
        term_id_by_label[label] = tid
        terms.append({"id": tid, "label": label})
        return tid

    for t in raw.get("terms", []):
        if t.get("label", "").strip():
            term_id(t["label"])

    statements: list[dict] = []
    evidence: list[dict] = []
    key_to_id: dict[str, str] = {}
    ecount = 0

    for i, s in enumerate(raw.get("statements", []), 1):
        sid = f"s-{i}"
        key_to_id[s.get("key", sid)] = sid
        ev_ids: list[str] = []
        for e in s.get("evidence", []):
            ecount += 1
            eid = f"e-{ecount}"
            rec = {
                "id": eid,
                "kind": "text",
                "excerpt": e.get("excerpt", ""),
                "source": e.get("source", "body"),
            }
            if e.get("locator"):
                rec["locator"] = str(e["locator"])
            if e.get("script") and e["script"] != "latin":
                rec["script"] = e["script"]
            evidence.append(rec)
            ev_ids.append(eid)

        stmt = {
            "id": sid,
            "type": s.get("type", "claim"),
            "text": (s.get("text") or "").strip(),
            "evidence": ev_ids,
        }
        if s.get("basis") and s["basis"] != "author":
            stmt["basis"] = s["basis"]
        sterms = [term_id(lab) for lab in s.get("terms", []) if lab and lab.strip()]
        if sterms:
            stmt["terms"] = sterms
        statements.append(stmt)

    relations: list[dict] = []
    for r in raw.get("relations", []):
        src = key_to_id.get(r.get("from")) or term_id_by_label.get((r.get("from") or "").strip())
        dst = key_to_id.get(r.get("to")) or term_id_by_label.get((r.get("to") or "").strip())
        if src and dst and r.get("type"):
            relations.append({"from": src, "to": dst, "type": r["type"]})

    return {
        "schema_version": 1,
        "terms": terms,
        "evidence": evidence,
        "statements": statements,
        "relations": relations,
    }


def _user_message(page: PageText, context: Optional[dict]) -> str:
    parts: list[str] = []
    neighbors = (context or {}).get("neighbors") or []
    if neighbors:
        parts.append("CONTEXT PAGES — for understanding only; DO NOT take evidence from these:")
        for n in neighbors:
            parts.append(f"--- context (printed label {n.page_label!r}) ---\n{n.text}")
        parts.append("")
    parts.append(
        f"TARGET PAGE — printed label {page.page_label!r}. Extract notes from THIS page only. "
        f"Every evidence excerpt must be copied verbatim from the BODY or FOOTNOTES below."
    )
    parts.append("\n=== BODY ===\n" + page.text)
    if page.footnotes:
        parts.append("\n=== FOOTNOTES ===\n" + page.footnotes)
    return "\n".join(parts)


class AnthropicExtractor:
    """Claude-backed `Extractor`. Returns an assembled notes-set dict."""

    def __init__(
        self,
        client: Optional["anthropic.Anthropic"] = None,
        model: str = MODEL,
        effort: str = "medium",
        max_tokens: int = 32000,
        api_key: Optional[str] = None,
    ):
        if client is not None:
            self._client = client
        elif api_key:
            self._client = anthropic.Anthropic(api_key=api_key)
        else:
            self._client = anthropic.Anthropic()  # resolves env key or `ant` login profile
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    def extract(self, page: PageText, context: Optional[dict] = None) -> dict:
        output_config: dict = {"format": {"type": "json_schema", "schema": _INTERMEDIATE_SCHEMA}}
        if self.effort:  # some cheaper models (e.g. Haiku) reject `effort`
            output_config["effort"] = self.effort
        # Stream: with a high max_tokens + adaptive thinking the request can run
        # several minutes, and the SDK refuses a non-streaming call that might
        # exceed 10 minutes. Streaming + get_final_message() avoids that guard and
        # request timeouts, then hands back the assembled Message.
        with self._client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            thinking={"type": "adaptive"},
            system=[
                {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
            ],
            messages=[{"role": "user", "content": _user_message(page, context)}],
            output_config=output_config,
        ) as stream:
            response = stream.get_final_message()
        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            # No output block — almost always the model spent the whole token
            # budget on thinking before emitting the JSON. Surface it clearly so
            # the caller can skip/retry this one page rather than crash the batch.
            raise ExtractionError(
                f"model returned no text/JSON block (stop_reason={response.stop_reason!r}); "
                f"likely exhausted max_tokens={self.max_tokens} while thinking — retry or raise --max-tokens"
            )
        return assemble(json.loads(text))
