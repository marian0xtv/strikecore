"""Token ledger — every LLM call gets a row in Postgres ``token_ledger``.

Designed to wrap ``providers/anthropic_provider.py``'s ``ProviderResponse``
return path with a single helper, so the rest of the codebase stays unaware
of persistence concerns. The same helper is used by every other provider
(``openrouter``, ``ollama``, …) — they all return the same ``ProviderResponse``
shape (``input_tokens``, ``output_tokens``, ``model``, ``latency``, …).

Cost estimation uses the static pricing table in ``governance/limits.py``;
the API does not expose pricing, so the table must be kept current.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

try:  # psycopg2 is optional — DB logging is best-effort (see log_llm_call)
    import psycopg2
    from psycopg2.extras import Json
    _HAS_PSYCOPG2 = True
except ImportError:  # pragma: no cover - exercised in DB-less environments
    psycopg2 = None  # type: ignore
    Json = None  # type: ignore
    _HAS_PSYCOPG2 = False

from governance.limits import model_info

logger = logging.getLogger("governance.token_ledger")


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------


def estimate_cost_micros(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_read_tokens: int = 0,
    cached_write_tokens: int = 0,
) -> int:
    """Estimate the USD cost in *micros* (1 USD = 1_000_000).

    Cached *read* tokens are billed at the cached-read rate, cached *write*
    tokens (the segments newly written into the cache) at the cache-write
    rate; uncached input at the regular input rate.
    """
    m = model_info(model)
    uncached_input = max(0, input_tokens - cached_read_tokens - cached_write_tokens)

    cost = (
        uncached_input         * m.pricing_input_per_mtok_usd
        + output_tokens        * m.pricing_output_per_mtok_usd
        + cached_read_tokens   * m.pricing_cached_read_per_mtok_usd
        + cached_write_tokens  * m.pricing_cache_write_per_mtok_usd
    ) / 1_000_000.0  # rates are per-MTok

    return int(round(cost * 1_000_000.0))  # USD → micros


# ---------------------------------------------------------------------------
# DSN resolution from .env (loaded by strikecore.sh)
# ---------------------------------------------------------------------------


def _dsn() -> str:
    """Build the Postgres DSN from env vars (loaded by strikecore.sh from .env)."""
    return (
        f"host={os.environ.get('POSTGRES_HOST', '127.0.0.1')}"
        f" port={os.environ.get('POSTGRES_PORT', '5433')}"
        f" dbname={os.environ.get('POSTGRES_DB', 'strikecore')}"
        f" user={os.environ.get('POSTGRES_USER', 'strikecore')}"
        f" password={os.environ.get('POSTGRES_PASSWORD', '')}"
        f" application_name=strikecore-governance"
        f" connect_timeout=5"
    )


# ---------------------------------------------------------------------------
# Module-level lazy connection (autocommit ON for fire-and-forget writes)
# ---------------------------------------------------------------------------


_CONN: Optional[psycopg2.extensions.connection] = None


def _conn() -> psycopg2.extensions.connection:
    global _CONN
    if _CONN is None or _CONN.closed:
        _CONN = psycopg2.connect(_dsn())
        _CONN.autocommit = True
    return _CONN


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def log_llm_call(
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    cache_write_tokens: int = 0,
    latency_ms: Optional[int] = None,
    cache_hit: bool = False,
    task_type: Optional[str] = None,
    agent_run_id: Optional[int] = None,
    subagent_inv_id: Optional[int] = None,
    dossier_id: Optional[int] = None,
    error: Optional[str] = None,
) -> Optional[int]:
    """Insert one row into ``token_ledger``. Returns the new id, or ``None`` on failure.

    Failures here MUST NOT crash the agent loop — the ledger is observability,
    not correctness-critical.
    """
    try:
        cost = estimate_cost_micros(model, input_tokens, output_tokens, cached_tokens, cache_write_tokens)
    except Exception:  # noqa: BLE001
        cost = 0

    if not _HAS_PSYCOPG2:
        return None  # DB-less environment: cost still computable via estimate_cost_micros

    sql = """
        INSERT INTO token_ledger
            (provider, model, task_type, input_tokens, output_tokens, cached_tokens,
             cost_usd_micros, latency_ms, cache_hit, error,
             agent_run_id, subagent_inv_id, dossier_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """

    try:
        with _conn().cursor() as cur:
            cur.execute(sql, (
                provider, model, task_type, input_tokens, output_tokens, cached_tokens,
                cost, latency_ms, cache_hit, error,
                agent_run_id, subagent_inv_id, dossier_id,
            ))
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as exc:  # noqa: BLE001 — non-blocking observability
        logger.warning("token_ledger insert failed: %s", exc)
        # Reset the cached connection so the next call tries again
        try:
            _conn().close()
        except Exception:
            pass
        global _CONN
        _CONN = None
        return None


class TokenLedger:
    """Convenience wrapper for the rare caller who wants an instance API."""

    @staticmethod
    def log(**kwargs: Any) -> Optional[int]:
        return log_llm_call(**kwargs)

    @staticmethod
    @contextmanager
    def timed(*, provider: str, model: str, **kwargs: Any) -> Iterator["_LedgerCtx"]:
        """Context manager: ``with TokenLedger.timed(...) as c: c.record(...)``."""
        start = time.monotonic()
        ctx = _LedgerCtx(provider=provider, model=model, base_kwargs=kwargs)
        try:
            yield ctx
        finally:
            if ctx._recorded:
                return
            # If the caller didn't record, log a zero-token failure for visibility
            log_llm_call(
                provider=provider, model=model,
                input_tokens=0, output_tokens=0,
                latency_ms=int((time.monotonic() - start) * 1000),
                error="call_did_not_complete",
                **kwargs,
            )


class _LedgerCtx:
    def __init__(self, *, provider: str, model: str, base_kwargs: dict[str, Any]) -> None:
        self.provider = provider
        self.model = model
        self.base = base_kwargs
        self._recorded = False
        self._start = time.monotonic()

    def record(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        cache_write_tokens: int = 0,
        cache_hit: bool = False,
        error: Optional[str] = None,
    ) -> Optional[int]:
        self._recorded = True
        latency = int((time.monotonic() - self._start) * 1000)
        return log_llm_call(
            provider=self.provider, model=self.model,
            input_tokens=input_tokens, output_tokens=output_tokens,
            cached_tokens=cached_tokens, cache_write_tokens=cache_write_tokens,
            cache_hit=cache_hit, latency_ms=latency, error=error,
            **self.base,
        )
