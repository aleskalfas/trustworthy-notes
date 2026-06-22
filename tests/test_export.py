"""Wave 4 export — no network."""

from __future__ import annotations

import json
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
    warnings: list[str] = []
    _user_prompt_for("ja", warn=warnings.append)
    assert warnings == []


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


def test_gloss_rendered_under_quote_when_translating():
    # #116: a non-English target produces a reading-aid translation for the CITED
    # excerpts and renders it beneath the original quote in the cited copy.
    synth = "## S\n- point [s-1]"
    gloss = json.dumps({"e-1": "Král měl několik manželek"})
    client = _ScriptedClient(synth, gloss)
    md = study_document(_cset(), client=client, model="m", language="cs")["markdown"]
    assert "The king customarily had several wives" in md      # original quote untouched
    assert "_translation: Král měl několik manželek_" in md    # gloss beneath, italic + labelled
    assert len(client.calls) == 2                              # synthesis + one gloss pass


def test_gloss_only_covers_cited_excerpts_not_every_extracted():
    # cost bound (ADR-008): only excerpts the cited notes surface are sent to translate.
    # Here only s-1 (→ e-1) is cited, so e-2 is never offered for translation.
    synth = "## S\n- point [s-1]"
    client = _ScriptedClient(synth, json.dumps({"e-1": "x"}))
    study_document(_cset(), client=client, model="m", language="cs")
    gloss_call = client.calls[1]["messages"][0]["content"]
    assert "e-1" in gloss_call
    assert "e-2" not in gloss_call                              # uncited excerpt not sent
    assert "the small-scale portrayal of the wife" not in gloss_call


def test_no_gloss_on_english_or_none_path():
    # native/English output → no translation pass at all (no gloss, single model call).
    for lang in (None, "en", "English"):
        client = _ScriptedClient("## S\n- point [s-1]")
        md = study_document(_cset(), client=client, model="m", language=lang)["markdown"]
        assert "_translation:" not in md, lang
        assert len(client.calls) == 1, lang                    # synthesis only, no gloss call


def test_gloss_absent_from_clean_reading_copy():
    # the clean reading copy strips the whole appendix, so the gloss never appears there.
    from trustworthy_notes.export import strip_citations
    synth = "## S\n- point [s-1]"
    gloss = json.dumps({"e-1": "Král měl několik manželek"})
    md = study_document(_cset(), client=_ScriptedClient(synth, gloss), model="m", language="cs")["markdown"]
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
    study_document(cset, client=_ScriptedClient(synth, gloss), model="m", language="cs")
    after = [e["excerpt"] for e in cset["evidence"]]
    assert after == before                                     # anchored excerpt untouched
    assert all("excerpt_translation" not in e for e in cset["evidence"])  # not written back in


def test_gloss_echoing_source_is_dropped():
    # a model that just echoes the source text back adds no reading value → not rendered.
    synth = "## S\n- point [s-1]"
    echo = json.dumps({"e-1": "The king customarily had several wives in the Old Kingdom"})
    md = study_document(_cset(), client=_ScriptedClient(synth, echo), model="m", language="cs")["markdown"]
    assert "_translation:" not in md


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
