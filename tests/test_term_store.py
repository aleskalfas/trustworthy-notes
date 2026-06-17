"""Stage 4 term store — no network."""

from __future__ import annotations

import json
from types import SimpleNamespace

from trustworthy_notes.term_store import _norm, _slug, terms_for_chapter


class _FakeClient:
    def __init__(self, payload: dict):
        message = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(payload))], stop_reason="end_turn"
        )

        class _Stream:
            def __enter__(s):
                return s

            def __exit__(s, *e):
                return False

            def get_final_message(s):
                return message

        self.messages = SimpleNamespace(stream=lambda **kw: _Stream())


def test_slug_accent_folds():
    assert _slug("Consanguineous Marriage") == "t-consanguineous-marriage"
    assert _slug("ḥm.t") == "t-hm-t"   # accent-folded (was t-m-t)


def test_norm_merges_singular_plural_variants():
    assert _norm("inscriptions") == _norm("inscription")
    assert _norm("half-siblings") == _norm("half-sibling")
    assert _norm("wives") == _norm("wife")            # irregular plural
    assert _norm("consanguineous marriages") == _norm("consanguineous marriage")


def test_terms_for_chapter_parses_and_trims():
    payload = {"terms": ["polygamy", "  false door ", "", "eldest son"]}
    labels = terms_for_chapter(["t1", "t2"], client=_FakeClient(payload), model="m")
    assert labels == ["polygamy", "false door", "eldest son"]
