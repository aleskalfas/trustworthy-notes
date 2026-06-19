"""Tests for the Anthropic extractor — no network, no API key.

A fake client replays a canned structured response, so we test the assembler,
the adapter wiring, and the anchor gate end-to-end without calling Claude.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from jsonschema import Draft202012Validator

from trustworthy_notes.extract import run_extract, run_extract_with_usage
from trustworthy_notes.extract_anthropic import _INTERMEDIATE_SCHEMA, AnthropicExtractor, assemble
from trustworthy_notes.models import PageText
from trustworthy_notes.validation import validate_structure


class _FakeClient:
    """Stands in for anthropic.Anthropic — replays a fixed JSON payload over the
    streaming API (messages.stream(...).get_final_message())."""

    def __init__(self, payload: dict, usage: object = None):
        message = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(payload))],
            stop_reason="end_turn",
            usage=usage,
        )

        class _FakeStream:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

            def get_final_message(self_inner):
                return message

        class _Messages:
            def stream(self, **kwargs):
                return _FakeStream()

        self.messages = _Messages()


def test_intermediate_schema_is_well_formed():
    Draft202012Validator.check_schema(_INTERMEDIATE_SCHEMA)


def test_assemble_assigns_ids_and_links():
    raw = {
        "terms": [{"label": "polygamy"}],
        "statements": [
            {
                "key": "s1",
                "type": "claim",
                "basis": "reported",
                "text": "Bryant argues marriage was not a legal state",
                "terms": ["polygamy"],
                "evidence": [{"excerpt": "‘Oddly, marriage", "source": "body"}],
            },
            {
                "key": "s2",
                "type": "background",
                "text": "the king had several wives",
                "evidence": [{"excerpt": "the king", "source": "body"}],
            },
        ],
        "relations": [{"from": "s2", "to": "s1", "type": "contrasts"}],
    }
    notes = assemble(raw)
    assert [s["id"] for s in notes["statements"]] == ["s-1", "s-2"]
    assert notes["statements"][0]["evidence"] == ["e-1"]
    assert notes["statements"][0]["basis"] == "reported"
    assert notes["statements"][0]["terms"] == ["t-polygamy"]
    assert notes["terms"][0]["id"] == "t-polygamy"
    # relation endpoints resolved from local keys to assigned ids
    assert notes["relations"][0] == {"from": "s-2", "to": "s-1", "type": "contrasts"}


def test_extractor_end_to_end_clean(monkeypatch):
    page = PageText(page_index=0, page_number=1, text="The cat sat on the mat.", width=1.0, height=1.0)
    payload = {
        "terms": [{"label": "cat"}],
        "statements": [
            {
                "key": "s1",
                "type": "claim",
                "text": "a cat sat",
                "terms": ["cat"],
                "evidence": [{"excerpt": "cat sat", "source": "body"}],
            }
        ],
        "relations": [],
    }
    extractor = AnthropicExtractor(client=_FakeClient(payload))
    notes, dropped = run_extract(page, extractor, document="d")

    assert dropped == []
    assert not validate_structure(notes)
    assert notes["statements"][0]["text"] == "a cat sat"
    assert notes["source"]["page_index"] == 0  # source stamped from the page, not the model


def test_extractor_hallucinated_quote_is_gated_out():
    page = PageText(page_index=0, page_number=1, text="The cat sat on the mat.", width=1.0, height=1.0)
    payload = {
        "statements": [
            {
                "key": "s1",
                "type": "claim",
                "text": "a dog ran",
                "evidence": [{"excerpt": "the dog sprinted away", "source": "body"}],
            }
        ],
    }
    extractor = AnthropicExtractor(client=_FakeClient(payload))
    notes, dropped = run_extract(page, extractor, document="d")

    assert notes["statements"] == []  # ungrounded statement dropped
    assert any(d["kind"] == "evidence" for d in dropped)
    assert not validate_structure(notes)


def test_run_extract_with_usage_surfaces_the_final_message_usage():
    page = PageText(page_index=0, page_number=1, text="The cat sat.", width=1.0, height=1.0)
    payload = {
        "statements": [
            {
                "key": "s1",
                "type": "claim",
                "text": "a cat sat",
                "evidence": [{"excerpt": "cat sat", "source": "body"}],
            }
        ],
    }
    usage = SimpleNamespace(input_tokens=120, output_tokens=45)
    extractor = AnthropicExtractor(client=_FakeClient(payload, usage=usage))
    notes, dropped, got = run_extract_with_usage(page, extractor, document="d")

    assert notes["statements"][0]["text"] == "a cat sat"
    assert got is usage  # surfaced out-of-band, not folded into the notes

