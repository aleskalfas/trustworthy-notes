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
    "explain, or interpret. Return each given id together with its translation string."
)


# Structured-output schema for a translation call (#146). JSON-schema structured outputs
# forbid open/dynamic keys (`additionalProperties` must be false), so the result can't be a
# dynamic-key `{id: translation}` object; we ask for a FIXED list of {id, translation} pairs
# and rebuild the map in code. The API then returns schema-validated, properly-escaped JSON,
# which fixes the intermittent unescaped-quote parse failure of free-text JSON (a translated
# value containing a `"` used to break `json.loads`, falling the entry to the source language).
_TRANSLATION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "translation": {"type": "string"},
                },
                "required": ["id", "translation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["translations"],
    "additionalProperties": False,
}


# Per-call cap on how many id -> text entries one translation request carries (#132).
# A single call over the WHOLE cited set (≈90 entries on a large chapter) made the model
# truncate / return partial-or-unparseable JSON, and the per-key source-fallback then
# rendered the entire appendix in the source language with no warning. Keeping each call
# small enough to return one complete valid JSON object is the fix; ~25 leaves generous
# token headroom for both the gloss (verbatim quotes) and the appendix (summaries) passes.
_TRANSLATE_BATCH_SIZE = 25

# Floor for the retry-in-smaller-sub-chunks recovery (#141). A flaky bulk call can come
# back unusable (entries unchanged, blank, or the call raising) for a whole batch; rather
# than falling that batch's ids straight to the source language, we retry the still-missing
# ids in progressively smaller sub-chunks (halving each round). We stop halving at this
# floor so the work stays bounded — below it the extra calls cost more than they recover.
_TRANSLATE_MIN_BATCH = 5


def _translate_batch(
    items: dict[str, str], *, system: str, instruction: str,
    client: "anthropic.Anthropic", model: str, effort: str, max_tokens: int,
) -> dict[str, str]:
    """One model call translating ``items`` (already a single batch). Returns the kept
    id -> translation map for this batch — ids we asked about whose translation is
    non-blank and actually DIFFERS from the source (an echo adds no value). May raise if
    the call itself fails; the caller decides how to surface that. A blank/unusable body is
    not an error here — it just yields {} (the retry / per-key fallback applies).

    The call uses structured outputs (#146): ``_TRANSLATION_SCHEMA`` constrains the response
    to schema-validated, properly-escaped JSON — a fixed ``{"translations": [{"id", ...}]}``
    list of pairs (open keys are disallowed). We parse it with ``json.loads`` (now guaranteed
    valid even when a translation contains a quote character) and rebuild the id -> translation
    map. The keep-if-differs filter is unchanged."""
    output_config: dict = {"format": {"type": "json_schema", "schema": _TRANSLATION_SCHEMA}}
    if effort:
        output_config["effort"] = effort
    with client.messages.stream(
        model=model, max_tokens=max_tokens, thinking={"type": "adaptive"},
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": instruction}],
        output_config=output_config,
    ) as stream:
        response = stream.get_final_message()
    body = next((b.text for b in response.content if b.type == "text"), None)
    if not body:
        return {}
    parsed = _parse_translations(body)
    return {
        k: v.strip()
        for k, v in parsed.items()
        if k in items and isinstance(v, str) and v.strip() and v.strip() != items[k].strip()
    }


def _translate_round(
    items: dict[str, str], chunk_size: int, *,
    system: str, build_instruction: Callable[[dict[str, str]], str],
    client: "anthropic.Anthropic", model: str, effort: str, max_tokens: int,
) -> dict[str, str]:
    """One pass over ``items`` in calls of at most ``chunk_size`` entries; returns the kept
    id -> translation map. A call that RAISES is swallowed (its ids stay missing for the
    caller to retry smaller or fall back) so one flaky call never blocks the rest."""
    keys = list(items)
    out: dict[str, str] = {}
    for start in range(0, len(keys), chunk_size):
        batch = {k: items[k] for k in keys[start:start + chunk_size]}
        try:
            out.update(_translate_batch(
                batch, system=system, instruction=build_instruction(batch),
                client=client, model=model, effort=effort, max_tokens=max_tokens,
            ))
        except Exception:  # noqa: BLE001 — a failed call must not block the document
            continue
    return out


def _translate_chunk(
    items: dict[str, str], chunk_size: int, *,
    system: str, build_instruction: Callable[[dict[str, str]], str],
    client: "anthropic.Anthropic", model: str, effort: str, max_tokens: int,
) -> dict[str, str]:
    """Translate ``items``, recovering a flaky bulk call by retrying the still-missing ids
    in progressively smaller sub-chunks (#141).

    Returns the kept id -> translation map (entries that differ from the source); ids that
    never came back are simply absent — the caller decides how to surface that. A call that
    returns its entries unchanged, omits ids, or RAISES leaves those ids missing, so a
    transient bulk-call failure still has a path to recover.

    Bounded descent: start at ``chunk_size`` and, while ids remain missing, HALVE the size
    and re-attempt only those ids. The loop stops on the first of three conditions — no ids
    left missing, the size has reached ``_TRANSLATE_MIN_BATCH`` (the floor), or a whole
    round recovered NOTHING new (a set the model will not translate, so further shrinking is
    futile). The genuinely-still-missing ids after the loop are left for the caller's per-key
    source fallback."""
    merged = _translate_round(
        items, chunk_size, system=system, build_instruction=build_instruction,
        client=client, model=model, effort=effort, max_tokens=max_tokens,
    )
    size = chunk_size
    while size > _TRANSLATE_MIN_BATCH:
        missing = {k: v for k, v in items.items() if k not in merged}
        if not missing:
            break
        size = max(_TRANSLATE_MIN_BATCH, size // 2)
        recovered = _translate_round(
            missing, size, system=system, build_instruction=build_instruction,
            client=client, model=model, effort=effort, max_tokens=max_tokens,
        )
        if not recovered:                   # this round gained nothing → stop, don't churn
            break
        merged.update(recovered)
    return merged


def _translate_map(
    items: dict[str, str], language: str, *,
    system: str, build_instruction: Callable[[dict[str, str]], str],
    client: "anthropic.Anthropic", model: str, effort: str = "low", max_tokens: int = 2000,
    warn: Optional[Callable[[str], None]] = None,
) -> dict[str, str]:
    """Translate an id -> source-text map into ``language`` across BOUNDED batches (#132).

    The shared core behind both reading-layer translation passes (ADR-008): the excerpt
    gloss and the Notes & Sources appendix text. ``items`` maps an id to the source
    string to translate; ``system`` is the caller's system prompt and
    ``build_instruction`` renders the user prompt for one batch of items (the payload
    differs per batch, so the caller supplies a builder rather than a fixed string).

    ``items`` is split into chunks of at most ``_TRANSLATE_BATCH_SIZE`` and each chunk is
    one model call; the returned maps are merged, preserving keys. Keeping each call small
    avoids the truncated / partial JSON that an oversized single call produced, which used
    to silently fall the whole appendix back to the source language (#132).

    A flaky chunk — one that RAISES, returns its entries unchanged, or omits ids — used to
    fall its whole batch back to the source language (#141: in a Czech book, later notes'
    bold summaries stayed English while their labels were Czech). Now such a
    chunk is RETRIED in smaller sub-chunks (``_translate_chunk``, halving down to
    ``_TRANSLATE_MIN_BATCH``) and anything recovered is merged. Only the ids that remain
    untranslated AFTER retries are surfaced via ``warn`` (one line) and fall back per-key to
    the original at render time — never a crash, never blocking. A document that fully
    recovers emits NO warning. Kept entries are those with a non-blank translation that
    DIFFERS from the source (an echo adds no value).

    This never re-reads the source page and its output never enters a §7 check. The model
    seam is the same injectable ``client``/``model`` the synthesis uses, so it is testable
    without a network call.
    """
    if not items:
        return {}
    merged = _translate_chunk(
        items, _TRANSLATE_BATCH_SIZE,
        system=system, build_instruction=build_instruction,
        client=client, model=model, effort=effort, max_tokens=max_tokens,
    )
    # The warning reflects POST-RETRY reality (#141): only ids still untranslated after the
    # sub-chunk recovery count — a batch that retried successfully emits nothing.
    missing = [k for k in items if k not in merged]
    if missing and warn:
        warn(
            f"translation incomplete: {len(missing)} of {len(items)} entries kept their "
            f"original language after retries (source-language fallback)"
        )
    return merged


def _translate_excerpts(
    excerpts: dict[str, str], language: str, *,
    client: "anthropic.Anthropic", model: str, effort: str = "low", max_tokens: int = 2000,
    warn: Optional[Callable[[str], None]] = None,
) -> dict[str, str]:
    """Translate cited source excerpts into ``language`` for the reading-aid gloss.

    ``excerpts`` maps evidence-id -> verbatim ``excerpt`` for the CITED evidence only
    (cost-bounded: a study document surfaces a small subset of all extracted evidence,
    and ADR-008 produces the gloss for those alone). Returns evidence-id -> translation;
    ids the model omits or returns blank are simply skipped (the appendix then renders
    the original quote with no gloss line — never an error). Batches via the shared
    ``_translate_map`` so a large cited set still translates in full (#132).

    This is a SEPARATE pass over the original quotes; it never mutates ``excerpt`` and
    its output never enters a §7 check.
    """
    def build_instruction(batch: dict[str, str]) -> str:
        payload = json.dumps(batch, ensure_ascii=False)
        return (
            f"Translate each quotation below into {language}. For every id, return that same id "
            f"with the {language} translation of its quotation.\n\n"
            f"QUOTES (json id -> source text):\n{payload}"
        )

    return _translate_map(
        excerpts, language, system=_GLOSS_SYSTEM, build_instruction=build_instruction,
        client=client, model=model, effort=effort, max_tokens=max_tokens, warn=warn,
    )


# The Notes & Sources appendix renders Layer-A note text (the statement summaries) and
# a small fixed set of chrome labels (basis kinds like `claim`/`reported`, source kinds
# `body`/`footnote`, and the `p.` page-label word). When the reader asked for a target
# language these render in that language too (issue #128) — a re-representation of notes
# already anchored, exactly the faithfulness-neutral seam ADR-008 draws. The VERBATIM
# excerpt, the page number, the locator, and the `[s-N]` ids are NOT here and are never
# translated; this pass touches only the note text and the labels.
_APPENDIX_SYSTEM = (
    "You translate short note text and a few fixed UI labels into a target language for a "
    "study-document appendix. You are NOT extracting or judging evidence and you NEVER see "
    "or translate any verbatim source quotation — only the note summaries and labels given "
    "to you. Translate faithfully and literally; do not add, omit, explain, or interpret. "
    "Return each given id together with its translation string."
)

# Sentinel ids for the fixed chrome labels, sent in the SAME appendix-translation call as
# the statement summaries. The `label:` prefix can't collide with a statement id (`s-…`),
# so one returned JSON map carries both. The page-label token is the reader-visible `p.`
# abbreviation (sent and rendered as one unit, so English stays exactly `p.<page>`); a
# target language translates the abbreviation in place (e.g. `s.` in German).
_PAGE_WORD = "p."
_LABEL_PREFIX = "label:"


def _translate_appendix(
    summaries: dict[str, str], labels: set[str], language: str, *,
    client: "anthropic.Anthropic", model: str, effort: str = "low", max_tokens: int = 2000,
    warn: Optional[Callable[[str], None]] = None,
) -> dict[str, str]:
    """Translate the cited appendix text — statement summaries + chrome labels — in one pass.

    ``summaries`` maps statement-id -> the Layer-A note ``text`` for the CITED statements
    only (cost-bounded, like the gloss). ``labels`` is the small fixed set of chrome words
    actually used by the cited set (basis kinds, source kinds, plus the page-label word),
    each sent under a ``label:<word>`` sentinel id so one JSON map carries both. Returns a
    dict keyed by statement-id (translated summary) and by ``label:<word>`` (translated
    label); a missing key falls back to the original at render time — never an error.

    A SEPARATE reading-layer pass; it never re-reads the source and its output never enters
    a §7 check. The verbatim excerpt is not in ``items`` and is never touched (ADR-008).
    Batches via the shared ``_translate_map`` so a large cited set still translates (#132)."""
    items = dict(summaries)
    for word in labels:
        items[f"{_LABEL_PREFIX}{word}"] = word

    def build_instruction(batch: dict[str, str]) -> str:
        return (
            f"Translate each value below into {language}. For every id, return that same id with "
            f"the {language} translation of its value. Ids starting with `label:` are short fixed "
            f"UI words — translate just the word.\n\n"
            f"TEXT (json id -> source text):\n{json.dumps(batch, ensure_ascii=False)}"
        )

    return _translate_map(
        items, language, system=_APPENDIX_SYSTEM, build_instruction=build_instruction,
        client=client, model=model, effort=effort, max_tokens=max_tokens, warn=warn,
    )


def _parse_translations(body: str) -> dict:
    """Rebuild the id -> translation map from a structured-output body (#146).

    ``body`` is the text block of a structured-output call, so it is guaranteed valid JSON
    in the ``_TRANSLATION_SCHEMA`` shape — a ``{"translations": [{"id", "translation"}, ...]}``
    list of pairs. We rebuild the dynamic-key map the rest of the pipeline expects. A parse
    failure is non-fatal — the gloss is advisory, so we return {} and the caller renders the
    originals alone (the retry / per-key fallback applies)."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        pair["id"]: pair["translation"]
        for pair in data.get("translations", [])
        if isinstance(pair, dict) and isinstance(pair.get("id"), str)
    }


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


def _blockquote(text: str) -> str:
    """Prefix EVERY line of ``text`` with ``> `` so a multi-line value stays one
    contiguous Markdown blockquote (#148). An interior ``\\n`` that is NOT re-prefixed
    closes the quote early and spills the rest into plain body text — the verbatim
    excerpts carry the source PDF's hard-wrapped breaks, so this bites. The words are
    untouched, only line-prefix added (ADR-008 verbatim invariant)."""
    return "\n".join(f"> {line}" for line in text.split("\n"))


def _notes_appendix(
    cset: dict, cited: set[str], gloss: Optional[dict[str, str]] = None,
    appendix: Optional[dict[str, str]] = None,
) -> str:
    """Anchored 'Notes & Sources' entries for each cited note: the note text plus its
    verbatim evidence and printed-page citation — the click-through target for every
    ``[s-N]``. The page is a plain-text citation (a clickable jump into the *separate*
    source PDF isn't portable across viewers); the verbatim quote is right here.

    ``gloss`` (evidence-id -> reading-aid translation) is rendered as a visually
    distinct line BENEATH the original quote, never replacing it (ADR-008). It prefers
    an in-record ``excerpt_translation`` (carried through compose) and falls back to a
    freshly-produced map; absent for an evidence id, only the original quote shows.

    ``appendix`` (issue #128) carries reading-layer translations of the appendix's
    Layer-A note text and its chrome labels: keyed by statement-id for the translated
    summary, and by ``label:<word>`` for a translated basis/source-kind/page word. When
    None (the English/native path) every label and summary renders exactly as before —
    byte-for-byte unchanged, no regression. A key missing from a non-None map falls back
    to the original. The VERBATIM excerpt, the page number, the locator, and the
    ``[s-N]`` id are never in this map and are never translated — the quote stays the
    source's own words, the sole anchored evidence (ADR-008)."""
    gloss = gloss or {}
    appendix = appendix or {}

    def label(word: str) -> str:
        """The target-language label for ``word`` if translated, else the word as-is."""
        return appendix.get(f"{_LABEL_PREFIX}{word}", word)

    ev = {e["id"]: e for e in cset.get("evidence", [])}
    out = ["", "---", "## Notes & Sources", "",
           "Every citation links here; each note shows its verbatim source evidence and printed page."]
    for s in sorted((s for s in cset.get("statements", []) if s["id"] in cited),
                    key=lambda s: (len(s["id"]), s["id"])):
        kind = label(s["type"])
        b = f", {label(s['basis'])}" if s.get("basis") else ""
        summary = appendix.get(s["id"], s.get("text", ""))
        out.append(f'\n<a id="note-{s["id"]}"></a>')
        out.append(f"**[{s['id']}]** _{kind}{b}_ — {summary}")
        for eid in s.get("evidence", []):
            e = ev.get(eid)
            if not e:
                continue
            page = e.get("page_label") or f"idx{e.get('page_index', '?')}"
            loc = f", fn {e['locator']}" if e.get("locator") else ""
            q = e.get("excerpt", "")
            q = q if len(q) <= 240 else q[:237] + "…"
            page_word = label(_PAGE_WORD)
            source_kind = label(e.get("source", "body"))
            # prefix EVERY line of the (possibly multi-line) excerpt so it stays one
            # blockquote (#148); keep the trailing 2-space hard break so the citation
            # line below stays in the same block.
            out.append(f"{_blockquote(q)}  \n> — {page_word}{page}{loc} ({source_kind})")
            tr = gloss.get(eid) or e.get("excerpt_translation")
            if tr:
                tr = tr if len(tr) <= 240 else tr[:237] + "…"
                # reading aid, BENEATH the quote, visually distinct (italic) and labelled —
                # never a replacement for the verbatim evidence above (ADR-008).
                # per-line prefix defensively in case a gloss ever carries a newline (#148).
                out.append(_blockquote(f"_translation: {tr}_"))
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
    #
    # The Notes & Sources appendix's own Layer-A text (the cited statement summaries) and
    # its chrome labels (basis/source kinds + page word) are translated too (issue #128),
    # in a SEPARATE pass over the notes already in hand — never by re-reading the source.
    # Both maps stay empty on the English/None path, so the appendix renders byte-for-byte
    # as before and no extra model call is made.
    gloss: dict[str, str] = {}
    appendix_tr: dict[str, str] = {}
    if not _is_default_language(language):
        ev_by_id = {e["id"]: e for e in cset.get("evidence", [])}
        cited_excerpts = {
            eid: ev_by_id[eid].get("excerpt", "")
            for s in cset.get("statements", []) if s["id"] in cited
            for eid in s.get("evidence", [])
            if eid in ev_by_id and ev_by_id[eid].get("excerpt")
        }
        if cited_excerpts:
            gloss = _translate_excerpts(
                cited_excerpts, language, client=client, model=model, effort=effort, warn=warn
            )

        # Cited statement summaries + the chrome labels they actually use (basis kinds,
        # source kinds, page word) — one bounded translation pass over the cited set.
        cited_statements = [s for s in cset.get("statements", []) if s["id"] in cited]
        summaries = {s["id"]: s.get("text", "") for s in cited_statements if s.get("text")}
        labels: set[str] = {_PAGE_WORD}
        for s in cited_statements:
            labels.add(s["type"])
            if s.get("basis"):
                labels.add(s["basis"])
            for eid in s.get("evidence", []):
                e = ev_by_id.get(eid)
                if e:
                    labels.add(e.get("source", "body"))
        if summaries or labels:
            appendix_tr = _translate_appendix(
                summaries, labels, language, client=client, model=model, effort=effort, warn=warn
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
        _notes_appendix(cset, cited, gloss, appendix_tr),
    ]
    if unknown:
        doc.append(f"\n> ⚠ {len(unknown)} citation(s) reference notes not in this chapter "
                   f"(possible synthesis drift): {', '.join(unknown)}")
    return {"markdown": "\n".join(doc) + "\n", "cited": cited, "unknown": unknown}
