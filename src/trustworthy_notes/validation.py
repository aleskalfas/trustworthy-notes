"""Validate a notes-set against METHODOLOGY §7 — the mechanical checks.

This is the code side of the methodology↔code contract (§9): the schema encodes
shape, and this module enforces the checks the schema cannot express. Split into:

  * ``validate_structure`` — no source needed. Covers §7.5 schema-valid,
    §7.1 grounded, §7.3 well-typed (both via the JSON Schema), plus §7.4
    referential integrity (evidence/term refs + relation endpoints resolve).
  * ``check_traceability`` — needs the extracted pages. Covers §7.2: every
    ``text`` evidence excerpt resolves verbatim in its cited source stream
    (``figure``/``table`` are reserved, so skipped).

Both return a list of human-readable problem strings; empty means valid.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator

from .normalize import quote_is_anchored


@lru_cache(maxsize=1)
def load_notes_schema() -> dict[str, Any]:
    """Load the notes JSON Schema shipped inside the package."""
    text = (files("trustworthy_notes") / "schemas" / "notes.schema.json").read_text(encoding="utf-8")
    return json.loads(text)


def validate_structure(data: dict[str, Any]) -> list[str]:
    """Schema-validity + referential integrity (§7.1, §7.3, §7.4, §7.5)."""
    problems: list[str] = []

    validator = Draft202012Validator(load_notes_schema())
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.path) or "<root>"
        problems.append(f"schema [{loc}]: {err.message}")

    evidence_ids = {e["id"] for e in data.get("evidence", []) if "id" in e}
    term_ids = {t["id"] for t in data.get("terms", []) if "id" in t}
    statement_ids = {s["id"] for s in data.get("statements", []) if "id" in s}
    nodes = statement_ids | term_ids

    for s in data.get("statements", []):
        sid = s.get("id", "<no-id>")
        for ref in s.get("evidence", []):
            if ref not in evidence_ids:
                problems.append(f"referential: statement {sid} references missing evidence {ref!r}")
        for ref in s.get("terms", []):
            if ref not in term_ids:
                problems.append(f"referential: statement {sid} references missing term {ref!r}")

    for r in data.get("relations", []):
        for end in (r.get("from"), r.get("to")):
            if end not in nodes:
                problems.append(f"referential: relation endpoint {end!r} is not a known statement or term")

    return problems


def check_traceability(data: dict[str, Any], pages: list) -> list[str]:
    """§7.2: every text-evidence excerpt resolves in its cited source stream.

    ``pages`` is a list of PageText (from ``ingest.extract_pages``). An evidence
    record's page defaults to ``source.page_index`` unless it overrides.
    """
    problems: list[str] = []
    by_index = {p.page_index: p for p in pages}
    default_index = (data.get("source") or {}).get("page_index")

    for e in data.get("evidence", []):
        if e.get("kind", "text") != "text":
            continue  # figure/table fidelity is reserved (METHODOLOGY §6)
        index = e.get("page_index", default_index)
        page = by_index.get(index)
        eid = e.get("id", "<no-id>")
        if page is None:
            problems.append(f"traceability: evidence {eid} cites page_index {index} not among extracted pages")
            continue
        stream = page.text if e.get("source") == "body" else page.footnotes
        if not quote_is_anchored(e.get("excerpt", ""), stream):
            problems.append(
                f"traceability: evidence {eid} excerpt not found in {e.get('source')} stream of page_index {index}"
            )

    return problems
