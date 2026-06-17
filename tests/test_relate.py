"""Stage 5 cross-page relations — no network."""

from __future__ import annotations

import json
from types import SimpleNamespace

from trustworthy_notes.relate import _candidates, _page_of, relations_for_chapter


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


def test_page_of():
    assert _page_of("p98:s-3") == 98


def test_candidates_need_shared_term_across_pages():
    keys = ["p1:s-1", "p2:s-1", "p1:s-2"]
    links = {
        "p1:s-1": ["t-polygamy"],
        "p2:s-1": ["t-polygamy"],   # shares t-polygamy with p1:s-1, different page → candidates
        "p1:s-2": ["t-vizier"],     # term used on only one page → excluded
    }
    assert _candidates(keys, links) == {"p1:s-1", "p2:s-1"}


def test_relations_validated_to_cross_page_and_known_keys():
    statements = [
        {"key": "p1:s-1", "type": "claim", "text": "a", "terms": []},
        {"key": "p2:s-1", "type": "claim", "text": "b", "terms": []},
    ]
    payload = {"relations": [
        {"from": "p1:s-1", "to": "p2:s-1", "type": "supports"},   # valid: cross-page
        {"from": "p1:s-1", "to": "p1:s-1", "type": "supports"},   # self → dropped
        {"from": "p1:s-1", "to": "p9:s-9", "type": "supports"},   # unknown key → dropped
    ]}
    rels = relations_for_chapter(statements, client=_FakeClient(payload), model="m")
    assert rels == [{"from": "p1:s-1", "to": "p2:s-1", "type": "supports"}]
