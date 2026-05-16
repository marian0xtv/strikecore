"""Anthropic prompt-caching helper.

Wraps the operation that turns a plain string system prompt into the
*list-of-blocks* form that the Anthropic Messages API requires for
``cache_control: ephemeral``. The 5-minute ephemeral cache is enough for an
intra-session use case (dossier construction, planner reasoning) — the
*beta* header we set is ``prompt-caching-2024-07-31``, the stable feature
behind that flag.

Cacheable segments (per CLAUDE.md doctrine + measured stability of the
prompts in ``intel_team/prompts/`` and the planning/critic system prompts
in ``agent/`` once Phase B lands):

* Long stable system prompts (≥ 1024 tokens — Anthropic's minimum for
  caching).
* Tool descriptions and few-shot examples (also stable).

We do *not* cache the per-call user message — it changes every time.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger("governance.prompt_cache")


# Min length to bother caching, in approximate characters (≈ 4 chars/tok).
# Anthropic enforces a real minimum of ~1024 tokens for the cache to engage.
_MIN_CACHE_CHARS: int = 4096


def build_cached_system_blocks(
    *segments: str,
    cache_last: bool = True,
) -> list[dict[str, Any]]:
    """Convert N text segments into Anthropic system-block format.

    Only segments long enough to be worth caching get a ``cache_control``
    marker; very short prefixes (e.g. a one-line preamble) are emitted as
    plain text. The *last* cacheable segment gets the marker by default,
    because Anthropic caches up to and including the most recent
    ``cache_control`` block.

    Returns the list of blocks ready to pass as the ``system`` argument
    of ``client.messages.create``.
    """
    blocks: list[dict[str, Any]] = []
    cacheable_indices: list[int] = []

    for i, seg in enumerate(segments):
        seg = (seg or "").strip()
        if not seg:
            continue
        block: dict[str, Any] = {"type": "text", "text": seg}
        blocks.append(block)
        if len(seg) >= _MIN_CACHE_CHARS:
            cacheable_indices.append(len(blocks) - 1)

    if not blocks:
        return blocks

    if cacheable_indices:
        target_idx = cacheable_indices[-1] if cache_last else cacheable_indices[0]
        blocks[target_idx]["cache_control"] = {"type": "ephemeral"}
    else:
        logger.debug(
            "build_cached_system_blocks: no segment ≥ %d chars to cache (got sizes %s)",
            _MIN_CACHE_CHARS, [len(b["text"]) for b in blocks],
        )

    return blocks


def system_with_cache(system_text: str) -> list[dict[str, Any]]:
    """Single-segment convenience: cache the whole system string if large enough."""
    return build_cached_system_blocks(system_text)


# ---------------------------------------------------------------------------
# Cache-hit accounting (read from anthropic_provider's ``ProviderResponse``)
# ---------------------------------------------------------------------------


def extract_cache_usage(usage_obj: Any) -> dict[str, int]:
    """Pull cache-read / cache-write counts off an Anthropic usage dict.

    Anthropic's ``message.usage`` exposes:
      * ``cache_creation_input_tokens`` — tokens written to the cache this call
      * ``cache_read_input_tokens``     — tokens served from cache this call
      * ``input_tokens``                — *uncached* input tokens
      * ``output_tokens``               — generated tokens

    Returns a normalised dict with safe defaults.
    """
    def _g(name: str) -> int:
        if isinstance(usage_obj, dict):
            return int(usage_obj.get(name, 0) or 0)
        return int(getattr(usage_obj, name, 0) or 0)

    return {
        "cache_read_input_tokens":     _g("cache_read_input_tokens"),
        "cache_creation_input_tokens": _g("cache_creation_input_tokens"),
        "input_tokens":                _g("input_tokens"),
        "output_tokens":               _g("output_tokens"),
    }


def cache_hit_rate(*, cache_read: int, total_input: int) -> float:
    """Cache hit ratio in [0..1]. Returns 0 when *total_input* is 0."""
    return (cache_read / total_input) if total_input > 0 else 0.0


def anthropic_beta_header() -> dict[str, str]:
    """Header to opt in to prompt-caching beta (still required as of 2026-05)."""
    return {"anthropic-beta": "prompt-caching-2024-07-31"}
