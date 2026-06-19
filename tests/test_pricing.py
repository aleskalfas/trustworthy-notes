"""Tests for the cost-estimate price table — pure arithmetic, no network.

These pin the per-model rates and the calculation so a stale or fat-fingered
edit to the table is caught. The figure is a convenience estimate; these tests
guard that it is at least internally consistent.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from trustworthy_notes import pricing


def _usage(**kw):
    base = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_input_plus_output_each_model():
    # 1M input + 1M output, priced at the table's per-MTok rates.
    cases = {
        "claude-sonnet-4-6": 3.00 + 15.00,
        "claude-opus-4-8": 5.00 + 25.00,
        "claude-haiku-4-5": 1.00 + 5.00,
    }
    for model, expected in cases.items():
        usage = _usage(input_tokens=1_000_000, output_tokens=1_000_000)
        assert pricing.estimate_cost(model, usage) == pytest.approx(expected)


def test_cache_tokens_priced_at_their_tiers():
    # 1M cache-write (default 5-minute tier) + 1M cache-read on Sonnet.
    usage = _usage(
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
    )
    assert pricing.estimate_cost("claude-sonnet-4-6", usage) == pytest.approx(3.75 + 0.30)


def test_one_hour_cache_breakdown_prefers_1h_rate():
    # When the API splits out a 1-hour slice, that slice is priced at the 1h rate
    # and the remainder stays at the 5-minute rate.
    usage = _usage(
        cache_creation_input_tokens=1_000_000,
        cache_creation=SimpleNamespace(ephemeral_1h_input_tokens=400_000),
    )
    # 600k at the 5-minute write rate (6.25) + 400k at the 1-hour rate (10.00).
    expected = 600_000 * 6.25 / 1_000_000 + 400_000 * 10.00 / 1_000_000
    assert pricing.estimate_cost("claude-opus-4-8", usage) == pytest.approx(expected)


def test_dict_usage_is_accepted():
    usage = {"input_tokens": 1_000_000, "output_tokens": 0}
    assert pricing.estimate_cost("claude-haiku-4-5", usage) == pytest.approx(1.00)


def test_missing_cache_fields_count_as_zero():
    usage = _usage(input_tokens=1_000_000)  # no cache fields exercised → just input
    assert pricing.estimate_cost("claude-sonnet-4-6", usage) == pytest.approx(3.00)


def test_unknown_model_returns_none():
    usage = _usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert pricing.estimate_cost("gpt-something", usage) is None


def test_pricing_as_of_is_stamped():
    assert pricing.PRICING_AS_OF == "2026-06-04"
