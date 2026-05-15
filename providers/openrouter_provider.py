"""OpenRouter provider using the openai SDK with a custom base URL."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, AsyncGenerator

import httpx
from openai import AsyncOpenAI

from .base import BaseProvider, ProviderResponse, ToolCall

logger = logging.getLogger(__name__)

_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "anthropic/claude-sonnet-4-5"
_MODELS_CACHE_TTL_S = 300  # 5 minutes


class OpenRouterProvider(BaseProvider):
    """Proxy provider that routes requests through OpenRouter."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        model: str = _DEFAULT_MODEL,
        max_tokens: int = 4096,
    ) -> None:
        config = config or {}
        api_key = config.get("api_key") or os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError(
                "OpenRouter API key must be provided via config['api_key'] "
                "or the OPENROUTER_API_KEY environment variable."
            )

        self._extra_headers = {
            "HTTP-Referer": "https://strikecore.local",
            "X-Title": "StrikeCore Security Assessment",
        }

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=config.get("base_url", _BASE_URL),
            default_headers=self._extra_headers,
        )
        self._model = model
        self._max_tokens = max_tokens

        # Cached model catalogue
        self._models_cache: list[dict[str, Any]] = []
        self._models_cache_ts: float = 0.0
        self._api_key = api_key
        self._base_url = config.get("base_url", _BASE_URL)

    # ------------------------------------------------------------------
    # BaseProvider interface
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "openrouter"

    def get_model_name(self) -> str:
        return self._model

    def supports_tools(self) -> bool:
        """Check the cached model catalogue for tool support."""
        for m in self._models_cache:
            if m.get("id") == self._model:
                # OpenRouter exposes supported features in the model object.
                supported = m.get("supported_parameters") or []
                if "tools" in supported:
                    return True
                # Fallback: Anthropic / OpenAI models generally support tools.
                description = (m.get("description") or "").lower()
                if any(kw in description for kw in ("tool", "function calling")):
                    return True
                break
        # Default True -- most routed models support tools.
        return True

    async def health_check(self) -> bool:
        try:
            await self.fetch_models()
            return True
        except Exception as exc:
            logger.warning("OpenRouter health-check failed: %s", exc)
            return False

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> ProviderResponse:
        kwargs = self._build_request(messages, tools, system)
        response = await self._client.chat.completions.create(**kwargs)
        return self._normalize(response)

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncGenerator[str, None]:
        kwargs = self._build_request(messages, tools, system)
        kwargs["stream"] = True
        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    # ------------------------------------------------------------------
    # Model catalogue
    # ------------------------------------------------------------------

    async def fetch_models(self) -> list[dict[str, Any]]:
        """Fetch the model list from OpenRouter, honouring a TTL cache."""
        now = time.monotonic()
        if self._models_cache and (now - self._models_cache_ts) < _MODELS_CACHE_TTL_S:
            return self._models_cache

        async with httpx.AsyncClient() as http:
            resp = await http.get(
                f"{self._base_url}/models",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    **self._extra_headers,
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()

        self._models_cache = data.get("data", [])
        self._models_cache_ts = now
        logger.debug("Cached %d OpenRouter models", len(self._models_cache))
        return self._models_cache

    async def list_model_ids(self) -> list[str]:
        """Return a sorted list of available model identifiers."""
        models = await self.fetch_models()
        return sorted(m["id"] for m in models if "id" in m)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        system: str | None,
    ) -> dict[str, Any]:
        formatted: list[dict[str, Any]] = []

        if system:
            formatted.append({"role": "system", "content": system})

        for msg in messages:
            if msg["role"] == "tool":
                formatted.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg["tool_call_id"],
                        "content": msg.get("content", ""),
                    }
                )
            elif msg["role"] == "assistant" and msg.get("tool_calls"):
                formatted.append(
                    {
                        "role": "assistant",
                        "content": msg.get("content") or None,
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["function"]["name"],
                                    "arguments": tc["function"]["arguments"]
                                    if isinstance(tc["function"]["arguments"], str)
                                    else json.dumps(tc["function"]["arguments"]),
                                },
                            }
                            for tc in msg["tool_calls"]
                        ],
                    }
                )
            else:
                formatted.append({"role": msg["role"], "content": msg["content"]})

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": formatted,
        }
        if tools:
            kwargs["tools"] = self._ensure_openai_tools(tools)
        return kwargs

    @staticmethod
    def _ensure_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Guarantee tools are in OpenAI function-calling format."""
        normalized: list[dict[str, Any]] = []
        for tool in tools:
            if tool.get("type") == "function":
                normalized.append(tool)
            else:
                normalized.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": tool.get("description", ""),
                            "parameters": tool.get("input_schema") or tool.get("parameters", {}),
                        },
                    }
                )
        return normalized

    def _normalize(self, response: Any) -> ProviderResponse:
        choice = response.choices[0]
        message = choice.message

        tool_calls: list[ToolCall] | None = None
        if message.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments)
                    if isinstance(tc.function.arguments, str)
                    else tc.function.arguments,
                )
                for tc in message.tool_calls
            ]

        usage = response.usage
        return ProviderResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=response.model or self._model,
            provider=self.provider_name,
            finish_reason=choice.finish_reason or "unknown",
            raw=response.model_dump(),
        )
