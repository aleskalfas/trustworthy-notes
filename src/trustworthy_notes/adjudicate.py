"""Wave 2, stage 3 (dedup) — the adjudication part.

Mechanical blocking (``compose.dedup_candidates``) proposes small clusters of
statements that *might* be the same claim (they share verbatim evidence). This
module asks the model to confirm, on **one tiny cluster at a time** (never the
corpus), which members truly assert the same claim and should merge — and what
the merged wording is. The model decides text only; code unions the evidence at
assembly, so anchoring is never re-touched (ARCHITECTURE §6, METHODOLOGY §4.6).
"""

from __future__ import annotations

import json
from typing import Optional

import anthropic

from .extract_anthropic import ExtractionError

SYSTEM_PROMPT = """You decide whether short scholarly notes state the SAME claim.

You are given a small group of statements that are all the same type and cite
overlapping source evidence. Output only the SUBGROUPS that assert the SAME claim
and should be merged into one note. Rules:
- Merge only genuine restatements of the same claim — NOT statements that merely
  share a source or topic but assert different things (different people, different
  details, sub-types of one category are all DISTINCT).
- For each merged subgroup, give one `text` that preserves the combined meaning,
  in neutral wording.
- A subgroup must have 2+ members. Statements that are distinct go in no subgroup.
- If nothing should merge, return an empty list.
Return ONLY the structured object."""

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["merges"],
    "properties": {
        "merges": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["members", "text"],
                "properties": {
                    "members": {"type": "array", "items": {"type": "string"}},
                    "text": {"type": "string"},
                },
            },
        }
    },
}


def _user_message(cluster: list[dict]) -> str:
    lines = [f"These {len(cluster)} statements are all type={cluster[0]['type']!r}.", ""]
    for s in cluster:
        lines.append(f"id {s['key']}: {s['text']}")
    return "\n".join(lines)


def adjudicate_cluster(
    cluster: list[dict], *, client: "anthropic.Anthropic", model: str, effort: str = "low",
    max_tokens: int = 4000,
) -> list[dict]:
    """Return the model's merge subgroups for one candidate cluster.

    Each subgroup is ``{"members": [keys], "text": merged}``; only members that
    belong to the cluster and groups of 2+ are kept.
    """
    output_config: dict = {"format": {"type": "json_schema", "schema": _SCHEMA}}
    if effort:
        output_config["effort"] = effort
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": _user_message(cluster)}],
        output_config=output_config,
    ) as stream:
        response = stream.get_final_message()
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise ExtractionError(f"adjudicator returned no output (stop_reason={response.stop_reason!r})")
    keys = {s["key"] for s in cluster}
    merges = []
    for m in json.loads(text).get("merges", []):
        members = [k for k in m.get("members", []) if k in keys]
        if len(members) >= 2:
            merges.append({"members": members, "text": m.get("text", "").strip()})
    return merges


def adjudicate(
    clusters: list[list[dict]], *, model: str, effort: str = "low",
    api_key: Optional[str] = None, client: Optional["anthropic.Anthropic"] = None,
) -> list[dict]:
    """Adjudicate every candidate cluster. Returns ``[{"cluster", "merges"}]`` —
    one bounded model call per cluster."""
    client = client or anthropic.Anthropic(api_key=api_key)
    out: list[dict] = []
    for c in clusters:
        out.append({"cluster": c, "merges": adjudicate_cluster(c, client=client, model=model, effort=effort)})
    return out
