"""Generic OpenAI-compatible provider for any conforming endpoint.

Works with any OpenAI-compatible endpoint: LocalAI, text-generation-webui,
Groq, Together AI, Fireworks, Mistral API, custom vLLM deployments, etc.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

from openai import AsyncOpenAI

from .base import BaseProvider, ProviderResponse, ToolCall

logger = logging.getLogger(__name__)


class GenericOpenAIProvider(BaseProvider):
    """Connect to any server that exposes an OpenAI-compatible chat API.

    The caller must supply ``base_url``, ``api_key``, and ``model_name``
    either directly or via the *config* dict.  This provider assumes full
    OpenAI tool-calling support.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
        max_tokens: int = 4096,
    ) -> None:
        config = config or {}
        self._base_url = config.get("base_url") or base_url
        self._api_key = config.get("api_key") or api_key
        self._model = config.get("model_name") or config.get("model") or model_name
        self._max_tokens = config.get("max_tokens", max_tokens)

        if not self._base_url:
            raise ValueError("base_url is required for GenericOpenAIProvider.")
        if not self._model:
            raise ValueError("model_name is required for GenericOpenAIProvider.")

        self._client = AsyncOpenAI(
            api_key=self._api_key or "EMPTY",
            base_url=self._base_url,
        )

    # ------------------------------------------------------------------
    # BaseProvider interface
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "generic_openai"

    def get_model_name(self) -> str:
        return self._model  # type: ignore[return-value]

    def supports_tools(self) -> bool:
        return True

    async def health_check(self) -> bool:
        """Attempt a minimal completion to verify the endpoint is alive."""
        try:
            await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            return True
        except Exception as exc:
            logger.warning("Generic OpenAI health-check failed: %s", exc)
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
    # Model listing (best-effort)
    # ------------------------------------------------------------------

    async def list_models(self) -> list[str]:
        """Try to list models; not all endpoints support this."""
        try:
            resp = await self._client.models.list()
            return sorted(m.id for m in resp.data)
        except Exception:
            return [self._model] if self._model else []

    # ------------------------------------------------------------------
    # Request building
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
            role = msg["role"]
            if role == "tool":
                formatted.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg["tool_call_id"],
                        "content": msg.get("content", ""),
                    }
                )
            elif role == "assistant" and msg.get("tool_calls"):
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
                                    "arguments": (
                                        tc["function"]["arguments"]
                                        if isinstance(tc["function"]["arguments"], str)
                                        else json.dumps(tc["function"]["arguments"])
                                    ),
                                },
                            }
                            for tc in msg["tool_calls"]
                        ],
                    }
                )
            else:
                formatted.append({"role": role, "content": msg["content"]})

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": formatted,
        }

        if tools:
            kwargs["tools"] = _ensure_openai_tools(tools)

        return kwargs

    # ------------------------------------------------------------------
    # Response normalization
    # ------------------------------------------------------------------

    def _normalize(self, response: Any) -> ProviderResponse:
        choice = response.choices[0]
        message = choice.message

        tool_calls: list[ToolCall] | None = None
        if message.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=(
                        json.loads(tc.function.arguments)
                        if isinstance(tc.function.arguments, str)
                        else tc.function.arguments
                    ),
                )
                for tc in message.tool_calls
            ]

        usage = response.usage
        return ProviderResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=response.model or self._model or "",
            provider=self.provider_name,
            finish_reason=choice.finish_reason or "unknown",
            raw=response.model_dump(),
        )


# ------------------------------------------------------------------
# Shared utility
# ------------------------------------------------------------------


def _ensure_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Guarantee every tool entry is in OpenAI function-calling format."""
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
