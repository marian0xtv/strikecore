"""Anthropic provider using the official anthropic Python SDK.

Phase A (2026-05-16) additions:
  * Reads ``max_tokens`` from ``governance/limits.py`` (real per-model limits)
    instead of the hardcoded 4096 default. Config override still honoured.
  * Wraps the system prompt in cacheable Anthropic blocks via
    ``governance/prompt_cache.py`` (``cache_control: ephemeral``) so stable
    system prompts hit the prompt cache on subsequent calls.
  * Sets the ``anthropic-beta: prompt-caching-2024-07-31`` request header.
  * After every call, persists a row to ``token_ledger`` via
    ``governance/token_ledger.py`` (provider, model, in/out/cached tokens,
    cost_usd_micros, latency_ms, cache_hit). Logging failures must never
    bubble up to the caller.

Public interface (``chat`` / ``stream_chat`` signature) is UNCHANGED, so the
intel_team agents and the legacy nlp_engine keep working without edits.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, AsyncGenerator

import anthropic
from anthropic import AsyncAnthropic

from .base import BaseProvider, ProviderResponse, ToolCall

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Governance layer (Phase A) — optional, falls back to legacy behaviour if absent
# ----------------------------------------------------------------------------

try:
    from governance.limits import max_for as _gov_max_for
    from governance.prompt_cache import (
        anthropic_beta_header as _gov_cache_beta,
        build_cached_system_blocks as _gov_build_blocks,
        extract_cache_usage as _gov_cache_usage,
    )
    from governance.token_ledger import log_llm_call as _gov_log
    _HAS_GOVERNANCE = True
except Exception as _exc:  # noqa: BLE001 — keep provider importable even pre-Phase-A
    logger.info("governance layer unavailable (%s) — using legacy behaviour", _exc)
    _HAS_GOVERNANCE = False

    def _gov_max_for(_model: str, headroom: int = 0) -> int:
        return 4096

    def _gov_build_blocks(*segs: str, cache_last: bool = True) -> list[dict[str, Any]]:
        return [{"type": "text", "text": s} for s in segs if s]

    def _gov_cache_beta() -> dict[str, str]:
        return {}

    def _gov_cache_usage(usage: Any) -> dict[str, int]:
        def _g(name: str) -> int:
            if isinstance(usage, dict):
                return int(usage.get(name, 0) or 0)
            return int(getattr(usage, name, 0) or 0)
        return {
            "cache_read_input_tokens":     _g("cache_read_input_tokens"),
            "cache_creation_input_tokens": _g("cache_creation_input_tokens"),
            "input_tokens":                _g("input_tokens"),
            "output_tokens":               _g("output_tokens"),
        }

    def _gov_log(**_kwargs: Any) -> None:
        return None


SUPPORTED_MODELS = (
    # Account-accessible 2026-05-15 — informational only (not enforced).
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-5-20251101",
    "claude-opus-4-1-20250805",
    # Historical defaults — kept for back-compat with old config.toml values
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
)

_RETRYABLE_STATUS_CODES = (429, 529)
_MAX_RETRIES = 5
_INITIAL_BACKOFF_S = 1.0


class AnthropicProvider(BaseProvider):
    """Wraps the Anthropic Messages API with native tool-use support."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        model: str = "claude-sonnet-4-6",
        max_tokens: int | None = None,
    ) -> None:
        config = config or {}
        api_key = config.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "Anthropic API key must be provided via config['api_key'] "
                "or the ANTHROPIC_API_KEY environment variable."
            )

        self._client = AsyncAnthropic(
            api_key=api_key,
            base_url=config.get("base_url"),
        )
        # Prefer config-supplied values over constructor defaults so settings.toml
        # / env overrides flow through (CLAUDE.md §8 engineering hygiene).
        cfg_model = config.get("model")
        self._model = cfg_model if cfg_model else model

        # ``max_tokens`` is now governance-driven by default. A config override
        # (``[ai.anthropic].max_tokens`` in config.toml) or an explicit
        # constructor arg still wins — operators can pin a value when they
        # want predictability, otherwise we use the real model limit.
        cfg_max = config.get("max_tokens")
        if cfg_max is not None:
            try:
                self._max_tokens_override: int | None = int(cfg_max)
            except (TypeError, ValueError):
                self._max_tokens_override = None
        elif max_tokens is not None:
            self._max_tokens_override = int(max_tokens)
        else:
            self._max_tokens_override = None

    # ------------------------------------------------------------------
    # BaseProvider interface
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def get_model_name(self) -> str:
        return self._model

    def supports_tools(self) -> bool:
        return True

    def _effective_max_tokens(self) -> int:
        """Resolve max_tokens at call time — override wins, else governance limits."""
        if self._max_tokens_override is not None:
            return self._max_tokens_override
        # Headroom of 0 — caller already requested via the real limit
        return _gov_max_for(self._model)

    async def health_check(self) -> bool:
        """Send a minimal request to verify connectivity."""
        try:
            await self._client.messages.create(
                model=self._model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception as exc:
            logger.warning("Anthropic health-check failed: %s", exc)
            return False

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> ProviderResponse:
        """Execute a chat completion with exponential-backoff retry.

        Now also: (a) caches the system prompt via Anthropic prompt caching,
        (b) logs the call to ``token_ledger`` with cache usage info.
        """
        kwargs, extra_headers = self._build_request(messages, tools, system)
        start = time.monotonic()
        response = await self._send_with_retry(kwargs, extra_headers=extra_headers)
        latency_ms = int((time.monotonic() - start) * 1000)
        normalized = self._normalize(response)

        # Phase A — token ledger (best-effort; never raises)
        try:
            usage = _gov_cache_usage(getattr(response, "usage", None))
            _gov_log(
                provider="anthropic",
                model=getattr(response, "model", self._model),
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                cached_tokens=usage["cache_read_input_tokens"],
                cache_write_tokens=usage["cache_creation_input_tokens"],
                latency_ms=latency_ms,
                cache_hit=usage["cache_read_input_tokens"] > 0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("token_ledger logging skipped: %s", exc)

        return normalized

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Yield partial content deltas as they arrive."""
        kwargs, extra_headers = self._build_request(messages, tools, system)
        backoff = _INITIAL_BACKOFF_S

        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with self._client.messages.stream(extra_headers=extra_headers, **kwargs) as stream:
                    async for text in stream.text_stream:
                        yield text
                return
            except anthropic.RateLimitError:
                if attempt == _MAX_RETRIES:
                    raise
                logger.info(
                    "Rate-limited (attempt %d/%d), backing off %.1fs",
                    attempt + 1, _MAX_RETRIES, backoff,
                )
                await asyncio.sleep(backoff)
                backoff *= 2
            except anthropic.InternalServerError as exc:
                if getattr(exc, "status_code", None) in _RETRYABLE_STATUS_CODES:
                    if attempt == _MAX_RETRIES:
                        raise
                    await asyncio.sleep(backoff)
                    backoff *= 2
                else:
                    raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        system: str | None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Construct the kwargs dict for the Anthropic Messages API.

        Returns (kwargs, extra_headers).
        """
        anthropic_messages = self._convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._effective_max_tokens(),
            "messages": anthropic_messages,
        }

        if system:
            # When a plain string is passed, wrap it in cacheable blocks so
            # subsequent identical calls hit the Anthropic prompt cache.
            if isinstance(system, str):
                kwargs["system"] = _gov_build_blocks(system)
            else:
                # Caller already provided a structured system list (advanced path)
                kwargs["system"] = system

        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        return kwargs, _gov_cache_beta()

    async def _send_with_retry(
        self,
        kwargs: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        """Call messages.create with exponential backoff on 429/529."""
        backoff = _INITIAL_BACKOFF_S
        headers = extra_headers or {}

        for attempt in range(_MAX_RETRIES + 1):
            try:
                return await self._client.messages.create(extra_headers=headers, **kwargs)
            except anthropic.RateLimitError:
                if attempt == _MAX_RETRIES:
                    raise
                logger.info(
                    "Rate-limited (attempt %d/%d), backing off %.1fs",
                    attempt + 1, _MAX_RETRIES, backoff,
                )
                await asyncio.sleep(backoff)
                backoff *= 2
            except anthropic.InternalServerError as exc:
                if getattr(exc, "status_code", None) in _RETRYABLE_STATUS_CODES:
                    if attempt == _MAX_RETRIES:
                        raise
                    await asyncio.sleep(backoff)
                    backoff *= 2
                else:
                    raise

        # Unreachable, but keeps type-checkers happy.
        raise RuntimeError("Retry loop exited unexpectedly")

    # ------------------------------------------------------------------
    # Message / tool format conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI-style messages to Anthropic format."""
        converted: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            # Anthropic expects 'user' / 'assistant' only (system is separate kwarg)
            if role == "system":
                continue

            # Plain text or pre-formatted content arrays pass through.
            converted.append({"role": role, "content": msg["content"]})

        return converted

    @staticmethod
    def _convert_tools(
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Convert OpenAI-style tool definitions to Anthropic format."""
        anthropic_tools: list[dict[str, Any]] = []
        for tool in tools:
            if tool.get("type") == "function":
                fn = tool["function"]
                anthropic_tools.append(
                    {
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                    }
                )
            else:
                # Already in Anthropic format.
                anthropic_tools.append(tool)
        return anthropic_tools

    def _normalize(self, response: Any) -> ProviderResponse:
        """Map an Anthropic Message object to ProviderResponse."""
        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else json.loads(block.input),
                    )
                )

        return ProviderResponse(
            content="\n".join(content_parts),
            tool_calls=tool_calls if tool_calls else None,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
            provider=self.provider_name,
            finish_reason=response.stop_reason or "unknown",
            raw=response.model_dump(),
        )
