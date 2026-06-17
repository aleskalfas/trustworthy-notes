"""Wave 4 — export: human-readable study documents from chapter notes.

Layer B (per the design discussion): a *reading layer* synthesized from the
trustworthy notes so a person can learn the material. It is generated ONLY from
the chapter notes-set (statements + terms + relations) — never by re-reading the
source — and cites the note ids it draws on, which we then resolve to printed
pages so every line stays traceable to the verbatim evidence behind it. The notes
remain the authority; the study document is a derived, checkable reading aid.

Styles are pluggable; "outline" is the first. Each is a synthesis prompt over the
same grounded digest.
"""

from __future__ import annotations

import re

import anthropic

from .extract_anthropic import ExtractionError

_SYSTEM = (
    "You write human STUDY NOTES from a set of already-extracted, source-anchored "
    "notes about one book chapter. Use ONLY the information in the provided notes — "
    "do not add facts or outside knowledge. Cite the note ids you draw on inline like "
    "[s-5]; cite the real ids given to you. Write so a person can LEARN the material."
)

_STYLES = {
    "outline": (
        "Produce STUDY NOTES as a structured outline a student uses to learn this "
        "chapter. Use markdown `##` and `###` headings for sub-themes (do NOT number "
        "them yourself), concise nested bullets, a short 'Key terms' section, and a "
        "final 'The argument in brief'. Teach the material clearly."
    ),
}

_ID = re.compile(r"s-[0-9a-z-]+")
_BRACKET = re.compile(r"\[([^\]\n]+)\]")
# a run of adjacent [s-N] citations — separators are spaces/commas only, NEVER
# newlines (matching across a line break would merge bullets onto one line).
_CITE_RUN = re.compile(r"\[s-[^\]\n]*\](?:[ \t,]*\[s-[^\]\n]*\])*")
_HEADING = re.compile(r"^(#{2,3})\s+(.*)$")
_LEADING_NUM = re.compile(r"^\d+(\.\d+)*\.?\s+")


def _digest(cset: dict) -> str:
    term = {t["id"]: t["label"] for t in cset.get("terms", [])}
    lines = []
    for s in cset.get("statements", []):
        tg = " {" + ", ".join(term.get(t, t) for t in s.get("terms", [])) + "}" if s.get("terms") else ""
        b = f"/{s['basis']}" if s.get("basis") else ""
        lines.append(f"[{s['id']}] ({s['type']}{b}) {s.get('text', '')}{tg}")
    rels = "; ".join(f"{r['from']} {r['type']} {r['to']}" for r in cset.get("relations", []))
    return "\n".join(lines) + ("\n\nRELATIONS: " + rels if rels else "")


def _number_and_toc(body: str) -> tuple[str, str]:
    """Number ## / ### headings (1, 1.1, …), inject anchor ids, and build a clickable
    table of contents. The model writes prose; numbering/anchors are deterministic."""
    out: list[str] = []
    toc: list[str] = []
    c1 = c2 = 0
    for line in body.splitlines():
        m = _HEADING.match(line)
        if not m:
            out.append(line)
            continue
        hashes, title = m.group(1), _LEADING_NUM.sub("", m.group(2).strip())
        # citations don't belong in headings — a raw [s-N] would break the TOC link
        title = _BRACKET.sub(lambda b: "" if _ID.search(b.group(1)) else b.group(0), title).strip()
        if len(hashes) == 2:
            c1 += 1
            c2 = 0
            num, anchor, indent = str(c1), f"sec-{c1}", ""
        else:
            c2 += 1
            num, anchor, indent = f"{c1}.{c2}", f"sec-{c1}-{c2}", "  "
        out.append(f'<a id="{anchor}"></a>\n{hashes} {num}. {title}')
        toc.append(f"{indent}- [{num}. {title}](#{anchor})")
    return "\n".join(out), "\n".join(toc)


def _link_citations(body: str, valid: set[str]) -> str:
    """Turn a run of citations — ``[s-5, s-6]`` *or* adjacent ``[s-5][s-6]`` — into a
    single comma-separated set of clickable links (so they don't render as 's-5s-6');
    unknown ids are left as plain text (flagged separately)."""
    def repl(m: re.Match) -> str:
        ids = _ID.findall(m.group(0))
        return ", ".join(f"[{i}](#note-{i})" if i in valid else i for i in ids)

    return _CITE_RUN.sub(repl, body)


# --- reading-copy transform: strip [s-N] citations + the Notes & Sources appendix ---
_CITE_TOKEN = r"\[s-[0-9a-z-]+\](?:\(#[^)\n]*\))?"   # linkified or bare [s-N]
_CITE_RUN_STRIP = re.compile(r"[ \t]*" + _CITE_TOKEN + r"(?:[ \t,]*" + _CITE_TOKEN + r")*")
_APPENDIX_RE = re.compile(r"\n+(?:-{3,}\n+)?#{2,4} +Notes & Sources\b.*\Z", re.S)


def strip_citations(md: str) -> str:
    """Return a reading-only copy of a study document: drop the inline ``[s-N]``
    citations and the whole 'Notes & Sources' appendix, keeping the prose and its
    section navigation. For a clean read-through not meant for source-checking — the
    cited version stays the authority. Pure text transform (no model call)."""
    md = _APPENDIX_RE.sub("", md)                  # remove the sources appendix (to EOF)
    md = _CITE_RUN_STRIP.sub("", md)               # remove inline [s-N] runs (with leading space)
    md = re.sub(r"[ \t]+([.,;:!?)])", r"\1", md)   # no space left dangling before punctuation
    md = re.sub(r"\(\s*\)", "", md)                # drop any emptied parentheses
    md = re.sub(r"(?<=\S) {2,}(?=\S)", " ", md)    # collapse internal double spaces (keep indent)
    return md.rstrip() + "\n"


def _notes_appendix(cset: dict, cited: set[str]) -> str:
    """Anchored 'Notes & Sources' entries for each cited note: the note text plus its
    verbatim evidence and printed-page citation — the click-through target for every
    ``[s-N]``. The page is a plain-text citation (a clickable jump into the *separate*
    source PDF isn't portable across viewers); the verbatim quote is right here."""
    ev = {e["id"]: e for e in cset.get("evidence", [])}
    out = ["", "---", "## Notes & Sources", "",
           "Every citation links here; each note shows its verbatim source evidence and printed page."]
    for s in sorted((s for s in cset.get("statements", []) if s["id"] in cited),
                    key=lambda s: (len(s["id"]), s["id"])):
        b = f", {s['basis']}" if s.get("basis") else ""
        out.append(f'\n<a id="note-{s["id"]}"></a>')
        out.append(f"**[{s['id']}]** _{s['type']}{b}_ — {s.get('text', '')}")
        for eid in s.get("evidence", []):
            e = ev.get(eid)
            if not e:
                continue
            page = e.get("page_label") or f"idx{e.get('page_index', '?')}"
            loc = f", fn {e['locator']}" if e.get("locator") else ""
            q = e.get("excerpt", "")
            q = q if len(q) <= 240 else q[:237] + "…"
            out.append(f"> {q}  \n> — p.{page}{loc} ({e.get('source', 'body')})")
    return "\n".join(out)


def study_document(
    cset: dict, *, style: str = "outline", client: "anthropic.Anthropic", model: str,
    effort: str = "low", max_tokens: int = 4000,
) -> dict:
    """Synthesize a study document from one chapter notes-set.

    Returns ``{markdown, cited, unknown}`` — the document (with a resolved Sources
    section appended), the set of cited statement ids, and any cited ids that do
    NOT exist in the chapter (a faithfulness flag)."""
    if style not in _STYLES:
        raise ValueError(f"unknown style {style!r}; have {sorted(_STYLES)}")
    output_config: dict = {}
    if effort:
        output_config["effort"] = effort
    with client.messages.stream(
        model=model, max_tokens=max_tokens, thinking={"type": "adaptive"},
        system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": _STYLES[style] + "\n\nNOTES:\n" + _digest(cset)}],
        **({"output_config": output_config} if output_config else {}),
    ) as stream:
        response = stream.get_final_message()
    body = next((b.text for b in response.content if b.type == "text"), None)
    if not body:
        raise ExtractionError(f"export returned no output (stop_reason={response.stop_reason!r})")

    ids = {s["id"] for s in cset.get("statements", [])}
    found = set(_ID.findall(body))
    cited = found & ids
    unknown = sorted(found - ids)            # cited but not a real note → faithfulness flag

    # drop a model-supplied H1 title; we render our own + meta + TOC
    lines = body.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    numbered, toc = _number_and_toc("\n".join(lines).strip())
    numbered = _link_citations(numbered, cited)

    src = cset.get("source", {})
    title = src.get("chapter_title", src.get("chapter_id", "Chapter"))
    rng = src.get("page_range", [None, None])
    doc = [
        f"<!-- study notes · style={style} · authority: {src.get('chapter_id', '?')} notes "
        f"(2-compose/6-chapters); every [s-N] links to its verbatim source below -->",
        f"\n# {title} — Study Notes",
        f"*{src.get('document', '')} · PDF pages {rng[0]}–{rng[1]}*\n",
        "## Contents", "", toc, "",
        numbered,
        _notes_appendix(cset, cited),
    ]
    if unknown:
        doc.append(f"\n> ⚠ {len(unknown)} citation(s) reference notes not in this chapter "
                   f"(possible synthesis drift): {', '.join(unknown)}")
    return {"markdown": "\n".join(doc) + "\n", "cited": cited, "unknown": unknown}
