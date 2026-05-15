"""Anthropic provider using the official anthropic Python SDK."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, AsyncGenerator

import anthropic
from anthropic import AsyncAnthropic

from .base import BaseProvider, ProviderResponse, ToolCall

logger = logging.getLogger(__name__)

SUPPORTED_MODELS = (
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
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
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
        self._model = model
        self._max_tokens = max_tokens

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
        """Execute a chat completion with exponential-backoff retry."""
        kwargs = self._build_request(messages, tools, system)
        response = await self._send_with_retry(kwargs)
        return self._normalize(response)

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Yield partial content deltas as they arrive."""
        kwargs = self._build_request(messages, tools, system)
        backoff = _INITIAL_BACKOFF_S

        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with self._client.messages.stream(**kwargs) as stream:
                    async for text in stream.text_stream:
                        yield text
                return
            except anthropic.RateLimitError:
                if attempt == _MAX_RETRIES:
                    raise
                logger.info(
                    "Rate-limited (attempt %d/%d), backing off %.1fs",
                    attempt + 1,
                    _MAX_RETRIES,
                    backoff,
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
    ) -> dict[str, Any]:
        """Construct the kwargs dict for the Anthropic Messages API."""
        anthropic_messages = self._convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": anthropic_messages,
        }

        if system:
            kwargs["system"] = system

        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        return kwargs

    async def _send_with_retry(self, kwargs: dict[str, Any]) -> Any:
        """Call messages.create with exponential backoff on 429/529."""
        backoff = _INITIAL_BACKOFF_S

        for attempt in range(_MAX_RETRIES + 1):
            try:
                return await self._client.messages.create(**kwargs)
            except anthropic.RateLimitError:
                if attempt == _MAX_RETRIES:
                    raise
                logger.info(
                    "Rate-limited (attempt %d/%d), backing off %.1fs",
                    attempt + 1,
                    _MAX_RETRIES,
                    backoff,
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
    def _convert_messages(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Translate generic messages into Anthropic's expected format.

        Handles plain text messages, multi-block content arrays, and
        tool_result messages that reference a previous tool_use id.
        """
        converted: list[dict[str, Any]] = []

        for msg in messages:
            role = msg["role"]

            # tool_result messages carry the output of a tool invocation.
            if role == "tool":
                converted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg["tool_call_id"],
                                "content": msg.get("content", ""),
                            }
                        ],
                    }
                )
                continue

            # assistant messages that contain tool_use blocks
            if role == "assistant" and isinstance(msg.get("tool_calls"), list):
                blocks: list[dict[str, Any]] = []
                if msg.get("content"):
                    blocks.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "input": json.loads(tc["function"]["arguments"])
                            if isinstance(tc["function"]["arguments"], str)
                            else tc["function"]["arguments"],
                        }
                    )
                converted.append({"role": "assistant", "content": blocks})
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
