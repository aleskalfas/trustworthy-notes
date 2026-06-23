"""Wave 4 export — no network."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

from trustworthy_notes.export import study_document


class _FakeClient:
    def __init__(self, text: str):
        message = SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn")
        # The kwargs of EVERY stream() call this client received, in order. When
        # translating, study_document makes two calls — synthesis first, then a
        # separate gloss pass — so a prompt assertion must name which one it means.
        # user_prompt()/system_prompt() return the SYNTHESIS (first) call's prompt.
        self.calls: list[dict] = []

        class _Stream:
            def __enter__(s):
                return s

            def __exit__(s, *e):
                return False

            def get_final_message(s):
                return message

        def _stream(**kw):
            self.calls.append(kw)
            return _Stream()

        self.messages = SimpleNamespace(stream=_stream)

    def user_prompt(self) -> str:
        return self.calls[0]["messages"][0]["content"]

    def system_prompt(self) -> str:
        return self.calls[0]["system"][0]["text"]


def _cset():
    return {
        "source": {"chapter_id": "CHAPTER 1", "chapter_title": "CHAPTER 1"},
        "terms": [{"id": "t-polygamy", "label": "polygamy"}],
        "evidence": [
            {"id": "e-1", "excerpt": "The king customarily had several wives in the Old Kingdom",
             "source": "body", "page_index": 13, "page_label": "3"},
            {"id": "e-2", "excerpt": "the small-scale portrayal of the wife", "source": "body",
             "page_index": 14, "page_label": "4"},
        ],
        "statements": [
            {"id": "s-1", "type": "claim", "text": "a", "evidence": ["e-1"]},
            {"id": "s-2", "type": "claim", "text": "b", "evidence": ["e-2"]},
        ],
        "relations": [],
    }


def test_export_numbers_headings_and_builds_toc():
    body = "# Title\n## Background\ntext\n### Detail\nmore"
    md = study_document(_cset(), client=_FakeClient(body), model="m")["markdown"]
    assert "## 1. Background" in md and "### 1.1. Detail" in md   # numbered
    assert '<a id="sec-1"></a>' in md                             # anchor injected
    assert "- [1. Background](#sec-1)" in md                      # clickable TOC entry
    assert "## Contents" in md


def test_export_links_citations_to_anchored_notes():
    body = "## S\n- first point [s-1, s-2]"
    md = study_document(_cset(), client=_FakeClient(body), model="m")["markdown"]
    assert "[s-1](#note-s-1), [s-2](#note-s-2)" in md             # citations become links
    assert '<a id="note-s-1"></a>' in md                         # anchored appendix entry
    assert "— p.3 (body)" in md                                   # verbatim evidence + page


def test_export_cites_page_as_plain_text():
    body = "## S\n- point [s-1]"
    md = study_document(_cset(), client=_FakeClient(body), model="m")["markdown"]
    assert "— p.3 (body)" in md   # plain-text page citation (printed label)
    assert "#page=" not in md      # no fragile cross-PDF link
    assert "](../" not in md        # no source-file link


def test_export_citations_keep_line_breaks_and_join_adjacent():
    # adjacent [s-1][s-2] → one comma-joined set; the newline before "two" survives
    body = "## S\n- one [s-1][s-2]\n- two [s-1]"
    md = study_document(_cset(), client=_FakeClient(body), model="m")["markdown"]
    assert "- one [s-1](#note-s-1), [s-2](#note-s-2)" in md
    assert "\n- two [s-1](#note-s-1)" in md   # bullet line break preserved


def test_export_flags_stray_citations():
    body = "## S\n- real [s-1]\n- invented [s-99]"
    res = study_document(_cset(), client=_FakeClient(body), model="m")
    assert res["unknown"] == ["s-99"]
    assert res["cited"] == {"s-1"}
    assert "⚠" in res["markdown"]
    assert "[s-99](#note-s-99)" not in res["markdown"]            # stray not linked


def _user_prompt_for(language, *, body="## S\n- point [s-1]", warn=None):
    """Run study_document with a language and return (client, result) so a test can
    inspect the exact prompt sent and the resolved output."""
    client = _FakeClient(body)
    res = study_document(_cset(), client=client, model="m", language=language, warn=warn)
    return client, res


def test_language_directive_enters_the_prompt():
    # #112: a non-English target appends a write-in-<language> directive to the user
    # prompt; the system prompt is unchanged (the directive rides the style message).
    client, _ = _user_prompt_for("Czech")
    prompt = client.user_prompt()
    assert "WRITE THE STUDY NOTES IN Czech" in prompt
    assert "every `##`/`###` heading" in prompt          # prose AND invented headings
    assert "ascii tokens" in prompt                       # [s-N] preserved verbatim
    assert "use ONLY the provided notes" in prompt        # faithfulness unchanged
    assert "NOTES:" in prompt                             # the digest still follows


def test_english_and_none_leave_the_prompt_byte_for_byte_unchanged():
    # Regression guard: the default path adds NOTHING. Capture the no-language prompt,
    # then assert every English spelling and None produce the identical bytes.
    baseline = _user_prompt_for(None)[0].user_prompt()
    for lang in (None, "", "en", "en-US", "English", "english"):
        assert _user_prompt_for(lang)[0].user_prompt() == baseline, lang
        # and never the directive marker
        assert "WRITE THE STUDY NOTES IN" not in _user_prompt_for(lang)[0].user_prompt()


def test_translated_output_still_resolves_citations():
    # The [s-N] linking is language-agnostic: even with surrounding prose in another
    # language (the model would write it; here we just stand in non-ascii prose), the
    # citation still resolves to its anchored note.
    body = "## Téma\n- tvrzení s důkazem [s-1, s-2]"
    _, res = _user_prompt_for("cs", body=body)
    md = res["markdown"]
    assert "[s-1](#note-s-1), [s-2](#note-s-2)" in md   # citations linked regardless of prose
    assert res["cited"] == {"s-1", "s-2"}
    assert '<a id="note-s-1"></a>' in md


def test_unusual_language_soft_warns_but_still_runs():
    # ADR-008: no allowlist. A malformed value warns (once) yet is passed through.
    warnings: list[str] = []
    client, res = _user_prompt_for("??!", warn=warnings.append)
    assert warnings and "unusual" in warnings[0]
    assert "WRITE THE STUDY NOTES IN ??!" in client.user_prompt()   # not blocked
    assert res["markdown"]                                          # produced output


def test_plausible_language_does_not_warn():
    # A well-formed language never triggers the unusual-language soft warning. (The
    # degenerate _FakeClient returns no JSON for the translation passes, so a
    # translation-incompleteness warning is expected here; we assert only on the
    # language-plausibility warning this test is about.)
    warnings: list[str] = []
    _user_prompt_for("ja", warn=warnings.append)
    assert not any("unusual" in w for w in warnings)


class _ScriptedClient:
    """A fake client that returns a queued body per ``stream()`` call, in order — lets a
    test give the synthesis call one body and the gloss call another (e.g. JSON)."""

    def __init__(self, *bodies: str):
        self._bodies = list(bodies)
        self.calls: list[dict] = []
        outer = self

        class _Stream:
            def __init__(s, text):
                s._text = text

            def __enter__(s):
                return s

            def __exit__(s, *e):
                return False

            def get_final_message(s):
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text=s._text)], stop_reason="end_turn"
                )

        def _stream(**kw):
            outer.calls.append(kw)
            text = outer._bodies.pop(0) if outer._bodies else ""
            return _Stream(text)

        self.messages = SimpleNamespace(stream=_stream)


# When translating, study_document makes THREE model calls in this order: synthesis,
# the excerpt gloss, then the Notes & Sources appendix text + labels (#128). A scripted
# client must queue a body for each; an empty appendix body leaves the appendix in the
# source language (the fallback path). This default exercises the gloss without asserting
# on appendix translation.
def _appendix_body() -> str:
    """A stock appendix-translation JSON: the cited summary + the labels in 'cs'."""
    return json.dumps({
        "s-1": "překlad shrnutí",          # statement summary
        "label:claim": "tvrzení",           # basis kind
        "label:body": "tělo",               # source kind
        "label:p.": "s.",                   # page word abbreviation
    })


def test_gloss_rendered_under_quote_when_translating():
    # #116: a non-English target produces a reading-aid translation for the CITED
    # excerpts and renders it beneath the original quote in the cited copy.
    synth = "## S\n- point [s-1]"
    gloss = json.dumps({"e-1": "Král měl několik manželek"})
    client = _ScriptedClient(synth, gloss, _appendix_body())
    md = study_document(_cset(), client=client, model="m", language="cs")["markdown"]
    assert "The king customarily had several wives" in md      # original quote untouched
    assert "_translation: Král měl několik manželek_" in md    # gloss beneath, italic + labelled
    assert len(client.calls) == 3                              # synthesis + gloss + appendix


def test_gloss_only_covers_cited_excerpts_not_every_extracted():
    # cost bound (ADR-008): only excerpts the cited notes surface are sent to translate.
    # Here only s-1 (→ e-1) is cited, so e-2 is never offered for translation.
    synth = "## S\n- point [s-1]"
    client = _ScriptedClient(synth, json.dumps({"e-1": "x"}), _appendix_body())
    study_document(_cset(), client=client, model="m", language="cs")
    gloss_call = client.calls[1]["messages"][0]["content"]
    assert "e-1" in gloss_call
    assert "e-2" not in gloss_call                              # uncited excerpt not sent
    assert "the small-scale portrayal of the wife" not in gloss_call


def test_appendix_summaries_and_labels_render_in_target_language():
    # #128: the appendix's Layer-A note text (statement summary) and its chrome labels
    # (basis kind, source kind, page word) render in the target language; the verbatim
    # excerpt is unchanged with its gloss beneath.
    synth = "## S\n- point [s-1]"
    gloss = json.dumps({"e-1": "Král měl několik manželek"})
    md = study_document(
        _cset(), client=_ScriptedClient(synth, gloss, _appendix_body()),
        model="m", language="cs",
    )["markdown"]
    assert "_tvrzení_ — překlad shrnutí" in md                 # basis kind + summary translated
    assert "— s.3 (tělo)" in md                                # page word + source kind translated
    assert "p.3 (body)" not in md                              # English chrome NOT present
    assert "The king customarily had several wives" in md      # verbatim excerpt untouched
    assert "_translation: Král měl několik manželek_" in md    # gloss beneath


def test_appendix_only_translates_cited_statements_and_their_labels():
    # cost bound: only the CITED statement summary (s-1) and the labels it uses are sent.
    synth = "## S\n- point [s-1]"
    client = _ScriptedClient(synth, json.dumps({"e-1": "x"}), _appendix_body())
    study_document(_cset(), client=client, model="m", language="cs")
    appendix_call = client.calls[2]["messages"][0]["content"]
    assert "s-1" in appendix_call                              # cited summary sent
    assert "label:claim" in appendix_call and "label:body" in appendix_call
    assert "label:p." in appendix_call                         # page word sent
    assert '"s-2"' not in appendix_call                        # uncited statement not sent


def test_appendix_falls_back_to_source_when_translation_absent():
    # a key the model omits (or a blank/echo) falls back to the original — never an error.
    synth = "## S\n- point [s-1]"
    client = _ScriptedClient(synth, json.dumps({"e-1": "x"}), json.dumps({}))  # empty appendix map
    md = study_document(_cset(), client=client, model="m", language="cs")["markdown"]
    assert "_claim_ — a" in md                                 # original summary + basis kept
    assert "— p.3 (body)" in md                                # original chrome kept


def test_no_gloss_on_english_or_none_path():
    # native/English output → no translation pass at all (no gloss/appendix, single call).
    for lang in (None, "en", "English"):
        client = _ScriptedClient("## S\n- point [s-1]")
        md = study_document(_cset(), client=client, model="m", language=lang)["markdown"]
        assert "_translation:" not in md, lang
        assert len(client.calls) == 1, lang                    # synthesis only, no extra calls


def test_appendix_byte_for_byte_unchanged_on_english_path():
    # #128 regression guard: the English/None path renders the appendix exactly as before.
    body = "## S\n- point [s-1]\n- other [s-2]"
    en = study_document(_cset(), client=_FakeClient(body), model="m")["markdown"]
    for lang in (None, "", "en", "en-US", "English"):
        out = study_document(_cset(), client=_FakeClient(body), model="m", language=lang)["markdown"]
        assert out == en, lang


def test_gloss_absent_from_clean_reading_copy():
    # the clean reading copy strips the whole appendix, so the gloss never appears there.
    from trustworthy_notes.export import strip_citations
    synth = "## S\n- point [s-1]"
    gloss = json.dumps({"e-1": "Král měl několik manželek"})
    md = study_document(
        _cset(), client=_ScriptedClient(synth, gloss, _appendix_body()),
        model="m", language="cs",
    )["markdown"]
    clean = strip_citations(md)
    assert "_translation:" not in clean
    assert "Král měl několik manželek" not in clean
    assert "Notes & Sources" not in clean


def test_gloss_never_mutates_the_anchored_excerpt():
    # ADR-008: the gloss is a SEPARATE reading aid; the verbatim excerpt stays the sole
    # anchored evidence and must be left byte-for-byte intact (it is never anchor-checked
    # against a translation). Run a translating pass, then assert the source cset's stored
    # excerpts are unchanged — the gloss only adds a line beneath, never edits the quote.
    cset = _cset()
    before = [e["excerpt"] for e in cset["evidence"]]
    synth = "## S\n- point [s-1]"
    gloss = json.dumps({"e-1": "Král měl několik manželek"})
    study_document(cset, client=_ScriptedClient(synth, gloss, _appendix_body()), model="m", language="cs")
    after = [e["excerpt"] for e in cset["evidence"]]
    assert after == before                                     # anchored excerpt untouched
    assert all("excerpt_translation" not in e for e in cset["evidence"])  # not written back in


def test_anchor_checks_ignore_translated_appendix_text():
    # ADR-008 invariant: the §7 anchor reads the verbatim `excerpt` only — never the
    # translated summary, labels, or gloss. Translate fully, then assert traceability
    # still resolves the original excerpts against their source pages.
    from trustworthy_notes.export import study_document as _sd
    from trustworthy_notes.validation import check_traceability
    from trustworthy_notes.normalize import quote_is_anchored

    cset = _cset()
    synth = "## S\n- point [s-1, s-2]"
    gloss = json.dumps({"e-1": "Král měl několik manželek", "e-2": "malé vyobrazení manželky"})
    _sd(cset, client=_ScriptedClient(synth, gloss, _appendix_body()), model="m", language="cs")

    # The source "pages": the body stream must contain each verbatim excerpt. The
    # translated appendix text is NOT in these pages, so if any check read it, it'd fail.
    page13 = SimpleNamespace(
        page_index=13, text="The king customarily had several wives in the Old Kingdom.", footnotes=""
    )
    page14 = SimpleNamespace(
        page_index=14, text="Note the small-scale portrayal of the wife here.", footnotes=""
    )
    problems = check_traceability(cset, [page13, page14])
    assert problems == []                                      # original excerpts anchor fine
    # and the anchor function itself reads only the verbatim quote, not any translation
    assert quote_is_anchored("The king customarily had several wives in the Old Kingdom", page13.text)
    assert not quote_is_anchored("Král měl několik manželek", page13.text)  # translation never anchors


def test_gloss_echoing_source_is_dropped():
    # a model that just echoes the source text back adds no reading value → not rendered.
    synth = "## S\n- point [s-1]"
    echo = json.dumps({"e-1": "The king customarily had several wives in the Old Kingdom"})
    md = study_document(
        _cset(), client=_ScriptedClient(synth, echo, _appendix_body()),
        model="m", language="cs",
    )["markdown"]
    assert "_translation:" not in md


def _cset_n_cited(n: int) -> dict:
    """A cset whose synthesis cites ``n`` statements, each with its own evidence — so the
    gloss and appendix passes both see ``n`` cited entries (used to cross the batch size)."""
    evidence = [
        {"id": f"e-{i}", "excerpt": f"verbatim source quote number {i}", "source": "body",
         "page_index": i, "page_label": str(i)}
        for i in range(1, n + 1)
    ]
    statements = [
        {"id": f"s-{i}", "type": "claim", "text": f"summary {i}", "evidence": [f"e-{i}"]}
        for i in range(1, n + 1)
    ]
    return {
        "source": {"chapter_id": "BIG", "chapter_title": "BIG"},
        "terms": [], "evidence": evidence, "statements": statements, "relations": [],
    }


def _synth_citing(n: int) -> str:
    return "## S\n" + "\n".join(f"- point [s-{i}]" for i in range(1, n + 1))


class _BatchAwareClient:
    """A fake client whose FIRST stream() call returns the synthesis body, and every
    subsequent call (the batched gloss / appendix passes) returns a JSON object echoing
    back, for each requested id, a deterministic ``<lang> <id>`` translation. This lets a
    test feed a cited set larger than the batch size and assert every id came back AND
    that the translation passes were split across multiple calls."""

    def __init__(self, synth: str, *, fail_calls: set[int] | None = None, partial: bool = False):
        self.calls: list[dict] = []
        self._synth = synth
        self._fail_calls = fail_calls or set()
        self._partial = partial
        outer = self

        class _Stream:
            def __init__(s, text):
                s._text = text

            def __enter__(s):
                return s

            def __exit__(s, *e):
                return False

            def get_final_message(s):
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text=s._text)], stop_reason="end_turn"
                )

        def _stream(**kw):
            idx = len(outer.calls)
            outer.calls.append(kw)
            if idx == 0:
                return _Stream(outer._synth)            # synthesis call
            if idx in outer._fail_calls:
                raise RuntimeError("simulated batch failure")
            # echo a deterministic translation for each id in this batch's payload (the
            # instruction embeds the id -> source-text json object as its tail)
            content = kw["messages"][0]["content"]
            payload = json.loads(re.search(r"\{.*\}", content, re.S).group(0))
            mapping = {k: f"TR {k}" for k in payload}
            if outer._partial:                          # drop most keys → truncation signature
                keep = sorted(mapping)[: max(0, len(mapping) // 4)]
                mapping = {k: mapping[k] for k in keep}
            return _Stream(json.dumps(mapping))

        self.messages = SimpleNamespace(stream=_stream)


def test_large_cited_set_translates_every_entry_across_multiple_batches():
    # #132: a cited set larger than the batch size must translate IN FULL, split across
    # one model call per batch — not one oversized call that truncates to all-source.
    from trustworthy_notes.export import _TRANSLATE_BATCH_SIZE

    n = _TRANSLATE_BATCH_SIZE * 2 + 5            # spans three gloss batches and three appendix
    cset = _cset_n_cited(n)
    client = _BatchAwareClient(_synth_citing(n))
    warnings: list[str] = []
    md = study_document(cset, client=client, model="m", language="cs", warn=warnings.append)["markdown"]

    # every cited excerpt got a gloss line (no source-language fallback)
    for i in range(1, n + 1):
        assert f"_translation: TR e-{i}_" in md, i
    # and every cited summary rendered translated
    for i in range(1, n + 1):
        assert f"— TR s-{i}" in md, i

    # the gloss pass alone needed more than one call (so did the appendix); a single
    # oversized call is exactly the #132 bug. Calls = 1 synthesis + ceil(n/bs) gloss
    # + ceil((n+labels)/bs) appendix, all > 3.
    assert len(client.calls) > 3
    gloss_calls = [c for c in client.calls[1:] if "QUOTES" in c["messages"][0]["content"]]
    assert len(gloss_calls) >= 3                  # one per gloss batch
    assert warnings == []                         # full translation → no incompleteness warning


def test_transiently_failed_batch_recovers_via_retry_without_warning():
    # #141: a batch call that RAISES once is no longer fatal for its ids — they are retried
    # in smaller sub-chunks (where the client no longer hits the failing call index) and
    # recover in full. A transient failure that recovers emits NO incompleteness warning,
    # and never crashes the document.
    from trustworthy_notes.export import _TRANSLATE_BATCH_SIZE

    n = _TRANSLATE_BATCH_SIZE * 2               # two gloss batches, two appendix batches
    cset = _cset_n_cited(n)
    # fail the SECOND gloss batch only (call index 2: 0=synth, 1=gloss#1, 2=gloss#2); the
    # sub-chunk retries land on later call indices that succeed.
    client = _BatchAwareClient(_synth_citing(n), fail_calls={2})
    warnings: list[str] = []
    md = study_document(cset, client=client, model="m", language="cs", warn=warnings.append)["markdown"]

    assert warnings == []                                         # recovered → no warning
    # both the first-batch ids and the once-failed batch's ids translated in full
    assert "_translation: TR e-1_" in md
    assert f"_translation: TR e-{n}_" in md                       # last id recovered on retry
    assert md                                                     # produced a document (no crash)


def test_always_failing_batches_warn_and_fall_back_per_key_without_looping():
    # #141: when every call for a set fails regardless of chunk size, the sub-chunk retry
    # is BOUNDED (halve to the floor, then stop) — no infinite loop, no crash. The ids that
    # never came back warn once and fall back to the verbatim source at render time.
    from trustworthy_notes.export import _TRANSLATE_BATCH_SIZE

    n = _TRANSLATE_BATCH_SIZE                    # one gloss batch, one appendix batch
    cset = _cset_n_cited(n)
    # fail EVERY non-synthesis call: the gloss/appendix calls and all their sub-chunk retries
    client = _BatchAwareClient(_synth_citing(n), fail_calls=set(range(1, 500)))
    warnings: list[str] = []
    md = study_document(cset, client=client, model="m", language="cs", warn=warnings.append)["markdown"]

    assert any("translation incomplete" in w for w in warnings)  # surfaced, not silent
    assert "_translation:" not in md                             # nothing recovered → no gloss line
    assert f"verbatim source quote number {n}" in md             # original quote shown (fallback)
    assert md                                                     # bounded retries, no crash


class _ChunkSizeAwareClient:
    """Synthesis on the first call; thereafter translates each requested id ONLY when the
    batch is at or below ``max_usable`` entries — a larger batch returns nothing usable
    (simulating the flaky bulk call of #141). Used to prove the sub-chunk retry recovers a
    set that the full-size call cannot."""

    def __init__(self, synth: str, *, max_usable: int):
        self.calls: list[dict] = []
        self._synth = synth
        self._max_usable = max_usable
        outer = self

        class _Stream:
            def __init__(s, text):
                s._text = text

            def __enter__(s):
                return s

            def __exit__(s, *e):
                return False

            def get_final_message(s):
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text=s._text)], stop_reason="end_turn"
                )

        def _stream(**kw):
            idx = len(outer.calls)
            outer.calls.append(kw)
            if idx == 0:
                return _Stream(outer._synth)
            payload = json.loads(re.search(r"\{.*\}", kw["messages"][0]["content"], re.S).group(0))
            if len(payload) > outer._max_usable:
                return _Stream("")                      # bulk call returns nothing usable
            return _Stream(json.dumps({k: f"TR {k}" for k in payload}))

        self.messages = SimpleNamespace(stream=_stream)


def test_flaky_bulk_batch_recovers_fully_via_sub_chunk_retry():
    # #141 core: a full-size (25) call returns nothing usable, but smaller sub-chunks
    # succeed. The retry must recover EVERY entry and emit NO incompleteness warning.
    from trustworthy_notes.export import _TRANSLATE_BATCH_SIZE, _TRANSLATE_MIN_BATCH

    n = _TRANSLATE_BATCH_SIZE                    # a single full-size batch that fails whole
    cset = _cset_n_cited(n)
    # usable only at or below half the batch size — so the first full call yields nothing
    # and recovery happens once chunks shrink (still above the floor)
    client = _ChunkSizeAwareClient(_synth_citing(n), max_usable=_TRANSLATE_BATCH_SIZE // 2)
    assert _TRANSLATE_BATCH_SIZE // 2 >= _TRANSLATE_MIN_BATCH
    warnings: list[str] = []
    md = study_document(cset, client=client, model="m", language="cs", warn=warnings.append)["markdown"]

    for i in range(1, n + 1):
        assert f"_translation: TR e-{i}_" in md, i               # every gloss recovered
        assert f"— TR s-{i}" in md, i                            # every summary recovered
    assert warnings == []                                        # full recovery → no warning


def test_tolerant_parse_handles_json_fences_and_leading_prose():
    # #141 tolerant parse: a response wrapped in a ```json fence or carrying leading prose
    # is still parsed (not discarded as unusable) — exercised end-to-end via _translate_map.
    synth = "## S\n- point [s-1]"
    fenced_gloss = "Sure, here is the translation:\n```json\n" + json.dumps({"e-1": "Král"}) + "\n```"
    client = _ScriptedClient(synth, fenced_gloss, _appendix_body())
    md = study_document(_cset(), client=client, model="m", language="cs")["markdown"]
    assert "_translation: Král_" in md                          # parsed despite fence + prose


def test_partial_batch_marked_incomplete_warns():
    # #132: a batch that returns markedly fewer keys than asked (the truncation
    # signature) is surfaced via warn, even though the call did not raise.
    n = 8
    cset = _cset_n_cited(n)
    client = _BatchAwareClient(_synth_citing(n), partial=True)
    warnings: list[str] = []
    study_document(cset, client=client, model="m", language="cs", warn=warnings.append)
    assert any("translation incomplete" in w for w in warnings)


def test_small_set_uses_a_single_batch():
    # below the batch size: one gloss call + one appendix call (unchanged behaviour).
    from trustworthy_notes.export import _TRANSLATE_BATCH_SIZE

    n = 3
    assert n < _TRANSLATE_BATCH_SIZE
    cset = _cset_n_cited(n)
    client = _BatchAwareClient(_synth_citing(n))
    study_document(cset, client=client, model="m", language="cs")
    gloss_calls = [c for c in client.calls[1:] if "QUOTES" in c["messages"][0]["content"]]
    appendix_calls = [c for c in client.calls[1:] if "label:" in c["messages"][0]["content"]]
    assert len(gloss_calls) == 1                  # single gloss batch
    assert len(appendix_calls) == 1               # single appendix batch
    assert len(client.calls) == 3                 # synthesis + one gloss + one appendix


def test_strip_citations_removes_inline_cites_and_appendix():
    from trustworthy_notes.export import strip_citations
    md = (
        "## 1. Background\n"
        "- Kings had several wives [s-1](#note-s-1), [s-2](#note-s-2).\n"
        "- A nested point [s-3](#note-s-3)\n"
        "  - deeper still [s-4]\n"
        "\n---\n## Notes & Sources\n\n"
        "<a id=\"note-s-1\"></a>\n**[s-1]** _claim_ — text\n> quote\n> — p.3 (body)\n"
    )
    out = strip_citations(md)
    assert "[s-" not in out                      # no citation tokens anywhere
    assert "Notes & Sources" not in out          # appendix gone
    assert "Kings had several wives." in out     # punctuation tidied (no dangling space)
    assert "  - deeper still" in out             # nested-bullet indentation preserved
    assert "## 1. Background" in out             # headings + prose kept
