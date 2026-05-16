"""Strikecore Token Governance Layer.

Owns four cross-cutting concerns for every LLM call in the system:

1. ``limits``         single source of truth for *real* model context windows
                      and max-output limits — kills the hardcoded ``max_tokens=4096``
                      sprinkled across providers/intel_team/agents.
2. ``token_ledger``   persists every LLM call to Postgres (provider, model,
                      task_type, input/output/cached tokens, cost_usd_micros,
                      latency, dossier/run linkage). Wraps ``ProviderResponse``.
3. ``prompt_cache``   builds cache_control segments for Anthropic prompt-caching
                      (ephemeral, 5-min TTL); tracks cache-hit rate.
4. ``model_router``   reads ``model_routing`` table; selects model per task_type;
                      Phase D adds bandit-style exploration and policy updates.

Designed to be *additive*: existing code continues to work; opting into the
governance layer is a per-call decision made by the new agent-loop code in
``agent/`` and (post-Phase-A) by ``providers/anthropic_provider.py``.
"""

from governance.limits import (
    DEFAULT_MAX_OUTPUT,
    context_for,
    max_for,
    model_info,
)
from governance.token_ledger import TokenLedger, estimate_cost_micros, log_llm_call

__all__ = [
    "DEFAULT_MAX_OUTPUT",
    "TokenLedger",
    "context_for",
    "estimate_cost_micros",
    "log_llm_call",
    "max_for",
    "model_info",
]
