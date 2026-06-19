"""Convenience cost estimates for extraction runs.

A small leaf module: it computes an *estimated* USD cost from the provider's
reported token usage times a hardcoded per-model price table. There is no
Anthropic pricing API, so the rates are constants stamped with an "as of" date
(``PRICING_AS_OF``) — they will drift and must be refreshed by hand.

This figure is a convenience only. The real spend guardrail is the server-side
cap; a stale rate here can mislead but cannot overspend.

Keep this module free of pipeline imports — it is depended on, never depends.
"""

from __future__ import annotations

from typing import Optional

# When the rates below were last checked against Anthropic's published pricing.
# Bump this whenever a number in PRICING changes.
PRICING_AS_OF = "2026-06-04"

# Per-MILLION-token USD rates, by model id. Cache rates derive from `input`:
#   cache_write_5m = input * 1.25   (5-minute ephemeral TTL — the tool's default)
#   cache_write_1h = input * 2.0    (1-hour TTL)
#   cache_read     = input * 0.1
# We store the derived numbers explicitly so the table reads as a price sheet.
PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_write_5m": 3.75,
        "cache_write_1h": 6.00,
        "cache_read": 0.30,
    },
    "claude-opus-4-8": {
        "input": 5.00,
        "output": 25.00,
        "cache_write_5m": 6.25,
        "cache_write_1h": 10.00,
        "cache_read": 0.50,
    },
    "claude-haiku-4-5": {
        "input": 1.00,
        "output": 5.00,
        "cache_write_5m": 1.25,
        "cache_write_1h": 2.00,
        "cache_read": 0.10,
    },
}

_PER_TOKEN = 1_000_000  # the table is per million tokens


def _field(usage: object, name: str) -> int:
    """Read a token count from a usage object that may be an SDK model or a dict.

    Missing or null fields count as zero — the Anthropic API omits cache fields
    when no caching happened, and reports them as ``None`` otherwise.
    """
    if isinstance(usage, dict):
        value = usage.get(name)
    else:
        value = getattr(usage, name, None)
    return int(value or 0)


def estimate_cost(model: str, usage: object) -> Optional[float]:
    """Estimate the USD cost of one extraction call from its token usage.

    `usage` is the provider's usage report (an Anthropic ``Usage`` object or a
    plain dict) carrying ``input_tokens``, ``output_tokens``,
    ``cache_creation_input_tokens`` and ``cache_read_input_tokens``.

    Cache *creation* (write) is priced at the 5-minute ephemeral rate — the rate
    matching the tool's default cache_control. If the usage object exposes a
    1-hour breakdown (``cache_creation.ephemeral_1h_input_tokens``), that slice
    is priced at the 1-hour rate instead.

    Returns ``None`` for a model id not in the price table, so the caller can say
    the estimate is unavailable rather than print a misleading ``$0``.
    """
    rates = PRICING.get(model)
    if rates is None:
        return None

    input_tokens = _field(usage, "input_tokens")
    output_tokens = _field(usage, "output_tokens")
    cache_read = _field(usage, "cache_read_input_tokens")
    cache_create = _field(usage, "cache_creation_input_tokens")

    # Split cache creation into 1h / 5m slices when the API breaks it down;
    # otherwise the whole amount is the default 5-minute ephemeral tier.
    breakdown = usage.get("cache_creation") if isinstance(usage, dict) else getattr(
        usage, "cache_creation", None
    )
    cache_create_1h = _field(breakdown, "ephemeral_1h_input_tokens") if breakdown else 0
    cache_create_5m = max(cache_create - cache_create_1h, 0)

    cost = (
        input_tokens * rates["input"]
        + output_tokens * rates["output"]
        + cache_create_5m * rates["cache_write_5m"]
        + cache_create_1h * rates["cache_write_1h"]
        + cache_read * rates["cache_read"]
    )
    return cost / _PER_TOKEN
