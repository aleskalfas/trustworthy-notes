"""Stage 3 dedup adjudication — no network."""

from __future__ import annotations

import json
from types import SimpleNamespace

from trustworthy_notes.adjudicate import adjudicate_cluster


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


def _cluster():
    return [
        {"key": "p1:s-1", "type": "claim", "text": "kings had many wives"},
        {"key": "p2:s-1", "type": "claim", "text": "the king had several wives"},
        {"key": "p3:s-9", "type": "claim", "text": "a different, distinct claim"},
    ]


def test_adjudicate_keeps_valid_merge_group():
    payload = {"merges": [{"members": ["p1:s-1", "p2:s-1"], "text": "The king had several wives."}]}
    merges = adjudicate_cluster(_cluster(), client=_FakeClient(payload), model="m")
    assert merges == [{"members": ["p1:s-1", "p2:s-1"], "text": "The king had several wives."}]


def test_adjudicate_drops_unknown_members_and_singletons():
    payload = {"merges": [
        {"members": ["p1:s-1", "nope:s-99"], "text": "x"},   # one real member → singleton after filter → dropped
        {"members": ["p9:s-9"], "text": "y"},                 # not in cluster → dropped
    ]}
    assert adjudicate_cluster(_cluster(), client=_FakeClient(payload), model="m") == []


def test_adjudicate_empty_when_nothing_merges():
    assert adjudicate_cluster(_cluster(), client=_FakeClient({"merges": []}), model="m") == []
