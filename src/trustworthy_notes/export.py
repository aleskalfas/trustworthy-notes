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

import json
import re
from typing import Callable, Optional

import anthropic

from .extract_anthropic import ExtractionError

_SYSTEM = (
    "You write human STUDY NOTES from a set of already-extracted, source-anchored "
    "notes about one book chapter. Use ONLY the information in the provided notes — "
    "do not add facts or outside knowledge. Cite the note ids you draw on inline like "
    "[s-5]; cite the real ids given to you. Write so a person can LEARN the material."
)

# Common values that read as "the reader wants English, write as today". When the
# resolved language is one of these we make NO prompt change at all — the English
# path is byte-for-byte unchanged (no regression). Any other value is a target.
_DEFAULT_LANGUAGES = frozenset({"en", "en-us", "en-gb", "english"})

# Reasonable shape of a language code/name; anything outside it is *accepted* (no
# allowlist, per ADR-008) but soft-warned as possibly-unintended. We never block.
_PLAUSIBLE_LANGUAGE = re.compile(r"^[a-zA-Z]{2,}(?:[-_][a-zA-Z0-9]{2,})?$")


def _language_directive(language: str) -> str:
    """The instruction appended to the synthesis prompt when a non-English target
    language is requested. The model writes the reader prose AND the invented
    ``##``/``###`` headings in that language; the ``[s-N]`` citation markers and any
    note ids are ascii tokens, NOT prose, and must survive verbatim (ADR-008)."""
    return (
        f"\n\nWRITE THE STUDY NOTES IN {language}: all prose and every `##`/`###` heading "
        f"you invent must be in {language}. This is a re-representation of the SAME notes — "
        "use ONLY the provided notes, add nothing, and keep citing the real note ids. "
        "The `[s-N]` citation markers and note ids are literal ascii tokens, NOT prose: "
        "reproduce them EXACTLY (e.g. `[s-5]`), never translate or transliterate them."
    )


def _is_default_language(language: Optional[str]) -> bool:
    """True when ``language`` means 'write in English as today' — None, empty, or a
    common English spelling. Used to keep the English path a strict no-op."""
    return not language or language.strip().lower() in _DEFAULT_LANGUAGES


def _warn_if_unusual(language: str, warn: Optional[Callable[[str], None]]) -> None:
    """Soft-warn (never block) when a target language looks malformed — a typo guard
    only. ADR-008 keeps NO allowlist, so any well-formed value passes silently."""
    if warn and not _PLAUSIBLE_LANGUAGE.match(language.strip()):
        warn(f"language {language!r} looks unusual; passing it through to synthesis anyway")

# The gloss is a reading aid, NOT evidence (ADR-008). This system prompt is for the
# small, separate translation pass over the *cited* excerpts only — it never re-reads
# the source page and never touches the stored `excerpt`, only emits a translation
# beside it. Kept tight (low effort) because the gloss is help, not the anchor.
_GLOSS_SYSTEM = (
    "You translate short verbatim source quotations into a target language as a READING "
    "AID. You are NOT extracting or judging evidence — you only render each quote's "
    "meaning in the target language. Translate faithfully and literally; do not add, omit, "
    "explain, or interpret. Return ONLY a JSON object mapping each given id to its "
    "translation string, nothing else."
)


def _translate_excerpts(
    excerpts: dict[str, str], language: str, *,
    client: "anthropic.Anthropic", model: str, effort: str = "low", max_tokens: int = 2000,
) -> dict[str, str]:
    """Translate cited source excerpts into ``language`` for the reading-aid gloss.

    ``excerpts`` maps evidence-id -> verbatim ``excerpt`` for the CITED evidence only
    (cost-bounded: a study document surfaces a small subset of all extracted evidence,
    and ADR-008 produces the gloss for those alone). Returns evidence-id -> translation
    for the ids the model returned; ids it omits or returns blank are simply skipped
    (the appendix then renders the original quote with no gloss line — never an error).

    This is a SEPARATE pass over the original quotes; it never mutates ``excerpt`` and
    its output never enters a §7 check. The model seam is the same injectable
    ``client``/``model`` the synthesis uses, so it is testable without a network call.
    """
    if not excerpts:
        return {}
    payload = json.dumps(excerpts, ensure_ascii=False)
    instruction = (
        f"Translate each quotation below into {language}. Keep the SAME json keys (the "
        f"ids); the value of each is the {language} translation of that quotation. "
        f"Return ONLY the json object.\n\nQUOTES (json id -> source text):\n{payload}"
    )
    output_config: dict = {}
    if effort:
        output_config["effort"] = effort
    with client.messages.stream(
        model=model, max_tokens=max_tokens, thinking={"type": "adaptive"},
        system=[{"type": "text", "text": _GLOSS_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": instruction}],
        **({"output_config": output_config} if output_config else {}),
    ) as stream:
        response = stream.get_final_message()
    body = next((b.text for b in response.content if b.type == "text"), None)
    if not body:
        return {}
    parsed = _parse_gloss_json(body)
    # Keep only ids we asked about, with a non-blank translation that actually differs
    # from the original (a model echoing the source text back adds no reading value).
    return {
        eid: t.strip()
        for eid, t in parsed.items()
        if eid in excerpts and isinstance(t, str) and t.strip() and t.strip() != excerpts[eid].strip()
    }


# The gloss pass is asked for raw JSON, but a model may wrap it in a ```json fence or
# add a sentence; pull the first {...} object out before parsing. A parse failure is
# non-fatal — the gloss is advisory, so we return {} and render the originals alone.
_JSON_OBJECT = re.compile(r"\{.*\}", re.S)


def _parse_gloss_json(body: str) -> dict:
    m = _JSON_OBJECT.search(body)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


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


def _notes_appendix(cset: dict, cited: set[str], gloss: Optional[dict[str, str]] = None) -> str:
    """Anchored 'Notes & Sources' entries for each cited note: the note text plus its
    verbatim evidence and printed-page citation — the click-through target for every
    ``[s-N]``. The page is a plain-text citation (a clickable jump into the *separate*
    source PDF isn't portable across viewers); the verbatim quote is right here.

    ``gloss`` (evidence-id -> reading-aid translation) is rendered as a visually
    distinct line BENEATH the original quote, never replacing it (ADR-008). It prefers
    an in-record ``excerpt_translation`` (carried through compose) and falls back to a
    freshly-produced map; absent for an evidence id, only the original quote shows. The
    quote itself is always the source's verbatim words — the gloss is help, not the
    anchor, and is shown only in this cited copy (the clean reading copy strips the
    whole appendix, so it never appears there)."""
    gloss = gloss or {}
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
            tr = gloss.get(eid) or e.get("excerpt_translation")
            if tr:
                tr = tr if len(tr) <= 240 else tr[:237] + "…"
                # reading aid, BENEATH the quote, visually distinct (italic) and labelled —
                # never a replacement for the verbatim evidence above (ADR-008).
                out.append(f"> _translation: {tr}_")
    return "\n".join(out)


def study_document(
    cset: dict, *, style: str = "outline", client: "anthropic.Anthropic", model: str,
    effort: str = "low", max_tokens: int = 4000, language: Optional[str] = None,
    warn: Optional[Callable[[str], None]] = None,
) -> dict:
    """Synthesize a study document from one chapter notes-set.

    Returns ``{markdown, cited, unknown}`` — the document (with a resolved Sources
    section appended), the set of cited statement ids, and any cited ids that do
    NOT exist in the chapter (a faithfulness flag).

    ``language`` is the reader's resolved preferred language. When it is None or an
    English spelling the synthesis prompt is unchanged — the English path is
    byte-for-byte as before. For any other target the prompt gains a directive to
    write the reader prose AND the invented ``##``/``###`` headings in that language,
    while still drawing ONLY on the provided notes and citing the real ``[s-N]`` ids
    verbatim. This is the safe reader-layer translation seam: extraction stays native
    and the anchored excerpts are never touched (ADR-008). ``warn`` (optional) is a
    sink for a soft, non-blocking warning when a target value looks malformed.

    When translating, a SEPARATE small pass also produces a reading-aid gloss for the
    CITED excerpts only (cost-bounded — never every extracted quote), rendered beneath
    each original quote in the Notes & Sources appendix. The verbatim ``excerpt`` is
    left untouched and stays the sole anchored evidence; the gloss never enters a §7
    check. On the English/None path no gloss is produced."""
    if style not in _STYLES:
        raise ValueError(f"unknown style {style!r}; have {sorted(_STYLES)}")
    # The English/None path adds nothing to the prompt (strict no-op, no regression);
    # a target language appends the write-in-<language> directive and soft-warns on a
    # malformed value (never blocking — no allowlist, per ADR-008).
    instruction = _STYLES[style]
    if not _is_default_language(language):
        _warn_if_unusual(language, warn)
        instruction += _language_directive(language)
    output_config: dict = {}
    if effort:
        output_config["effort"] = effort
    with client.messages.stream(
        model=model, max_tokens=max_tokens, thinking={"type": "adaptive"},
        system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": instruction + "\n\nNOTES:\n" + _digest(cset)}],
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

    # Reading-aid gloss (ADR-008): only when translating, and ONLY over the excerpts the
    # cited notes actually surface — a small subset of all extracted evidence (cost bound).
    # The original `excerpt` is never touched; the gloss renders beneath it and is never
    # anchor-checked. The English/None path produces nothing (`gloss` stays empty).
    gloss: dict[str, str] = {}
    if not _is_default_language(language):
        ev_by_id = {e["id"]: e for e in cset.get("evidence", [])}
        cited_excerpts = {
            eid: ev_by_id[eid].get("excerpt", "")
            for s in cset.get("statements", []) if s["id"] in cited
            for eid in s.get("evidence", [])
            if eid in ev_by_id and ev_by_id[eid].get("excerpt")
        }
        gloss = _translate_excerpts(
            cited_excerpts, language, client=client, model=model, effort=effort
        )

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
        _notes_appendix(cset, cited, gloss),
    ]
    if unknown:
        doc.append(f"\n> ⚠ {len(unknown)} citation(s) reference notes not in this chapter "
                   f"(possible synthesis drift): {', '.join(unknown)}")
    return {"markdown": "\n".join(doc) + "\n", "cited": cited, "unknown": unknown}
