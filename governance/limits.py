"""Single source of truth for LLM model limits.

Kills the hardcoded ``max_tokens=4096`` / 6000 / 8000 magic numbers sprinkled
across ``providers/anthropic_provider.py``, ``intel_team/agents/base.py`` and
every specialist ``AgentConfig``.

The numbers in ``_ANTHROPIC_MODELS`` were verified against the
``/v1/models`` endpoint on 2026-05-16 with the operator's rotated key
(fingerprint ``5QAA / 64414aad``) and Anthropic's public documentation.
``refresh_from_provider()`` re-queries the API at runtime when the operator
wants to detect a newly-rolled-out model without code changes.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional
from urllib.request import Request, urlopen

logger = logging.getLogger("governance.limits")

DEFAULT_MAX_OUTPUT: int = 4096
DEFAULT_CONTEXT_WINDOW: int = 200_000


@dataclass(frozen=True)
class ModelLimits:
    """Real published limits for a given model id."""

    context_window: int
    max_output: int
    pricing_input_per_mtok_usd: float = 0.0   # USD per 1M input tokens
    pricing_output_per_mtok_usd: float = 0.0  # USD per 1M output tokens
    pricing_cached_read_per_mtok_usd: float = 0.0  # USD per 1M cache-read tokens
    pricing_cache_write_per_mtok_usd: float = 0.0  # USD per 1M cache-write tokens
    supports_prompt_caching: bool = True


# Static table — refresh_from_provider() can extend / overwrite at runtime.
# Pricing reflects Anthropic's public 2026 pricing page.
_ANTHROPIC_MODELS: dict[str, ModelLimits] = {
    "claude-opus-4-7": ModelLimits(
        context_window=200_000, max_output=32_000,
        pricing_input_per_mtok_usd=15.0, pricing_output_per_mtok_usd=75.0,
        pricing_cached_read_per_mtok_usd=1.5, pricing_cache_write_per_mtok_usd=18.75,
    ),
    "claude-opus-4-6": ModelLimits(
        context_window=200_000, max_output=32_000,
        pricing_input_per_mtok_usd=15.0, pricing_output_per_mtok_usd=75.0,
        pricing_cached_read_per_mtok_usd=1.5, pricing_cache_write_per_mtok_usd=18.75,
    ),
    "claude-opus-4-5-20251101": ModelLimits(
        context_window=200_000, max_output=32_000,
        pricing_input_per_mtok_usd=15.0, pricing_output_per_mtok_usd=75.0,
        pricing_cached_read_per_mtok_usd=1.5, pricing_cache_write_per_mtok_usd=18.75,
    ),
    "claude-opus-4-1-20250805": ModelLimits(
        context_window=200_000, max_output=32_000,
        pricing_input_per_mtok_usd=15.0, pricing_output_per_mtok_usd=75.0,
        pricing_cached_read_per_mtok_usd=1.5, pricing_cache_write_per_mtok_usd=18.75,
    ),
    "claude-sonnet-4-6": ModelLimits(
        context_window=200_000, max_output=64_000,
        pricing_input_per_mtok_usd=3.0, pricing_output_per_mtok_usd=15.0,
        pricing_cached_read_per_mtok_usd=0.30, pricing_cache_write_per_mtok_usd=3.75,
    ),
    "claude-sonnet-4-5-20250929": ModelLimits(
        context_window=200_000, max_output=64_000,
        pricing_input_per_mtok_usd=3.0, pricing_output_per_mtok_usd=15.0,
        pricing_cached_read_per_mtok_usd=0.30, pricing_cache_write_per_mtok_usd=3.75,
    ),
    "claude-haiku-4-5-20251001": ModelLimits(
        context_window=200_000, max_output=8_000,
        pricing_input_per_mtok_usd=1.0, pricing_output_per_mtok_usd=5.0,
        pricing_cached_read_per_mtok_usd=0.10, pricing_cache_write_per_mtok_usd=1.25,
    ),
    # Historical default kept so legacy configs do not crash if anyone still
    # references the rotated-off Sonnet alias. They will pay Sonnet-4-6 prices
    # if the model id is somehow accepted; in practice the API returns 404.
    "claude-sonnet-4-20250514": ModelLimits(
        context_window=200_000, max_output=8_000,
        pricing_input_per_mtok_usd=3.0, pricing_output_per_mtok_usd=15.0,
    ),
}

_MODELS: dict[str, ModelLimits] = dict(_ANTHROPIC_MODELS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def model_info(model_id: str) -> ModelLimits:
    """Return :class:`ModelLimits` for *model_id*; fall back to safe defaults."""
    info = _MODELS.get(model_id)
    if info is not None:
        return info
    logger.debug("Unknown model %r — using safe defaults (200k ctx, 4096 out)", model_id)
    return ModelLimits(context_window=DEFAULT_CONTEXT_WINDOW, max_output=DEFAULT_MAX_OUTPUT)


def max_for(model_id: str, headroom: int = 0) -> int:
    """Maximum *output* tokens for *model_id*, minus an optional headroom."""
    m = model_info(model_id).max_output
    return max(1, m - max(0, headroom))


def context_for(model_id: str) -> int:
    """Context window for *model_id* in tokens."""
    return model_info(model_id).context_window


def refresh_from_provider(api_key: Optional[str] = None, timeout: float = 10.0) -> int:
    """Re-fetch the model catalogue from Anthropic's ``/v1/models`` endpoint.

    Returns the number of models retrieved. Only ``max_output`` and
    ``context_window`` are refreshed when the API exposes them; pricing
    remains from the static table because Anthropic does not expose it
    through the SDK.
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        logger.warning("refresh_from_provider: no ANTHROPIC_API_KEY available")
        return 0

    req = Request(
        "https://api.anthropic.com/v1/models?limit=100",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — diagnostic-only path
        logger.warning("refresh_from_provider failed: %s", exc)
        return 0

    count = 0
    for entry in body.get("data", []) or []:
        mid = entry.get("id")
        if not mid:
            continue
        existing = _MODELS.get(mid)
        ctx = entry.get("context_window") or (existing.context_window if existing else DEFAULT_CONTEXT_WINDOW)
        out = entry.get("max_output_tokens") or (existing.max_output if existing else DEFAULT_MAX_OUTPUT)
        pricing = {
            "pricing_input_per_mtok_usd":  existing.pricing_input_per_mtok_usd  if existing else 0.0,
            "pricing_output_per_mtok_usd": existing.pricing_output_per_mtok_usd if existing else 0.0,
            "pricing_cached_read_per_mtok_usd": existing.pricing_cached_read_per_mtok_usd if existing else 0.0,
            "pricing_cache_write_per_mtok_usd": existing.pricing_cache_write_per_mtok_usd if existing else 0.0,
        }
        _MODELS[mid] = ModelLimits(context_window=ctx, max_output=out, **pricing)
        count += 1

    logger.info("refresh_from_provider: refreshed %d models", count)
    return count


def all_known_models() -> dict[str, ModelLimits]:
    """Snapshot of the current in-memory model catalogue."""
    return dict(_MODELS)
