"""vLLM provider using the openai SDK pointed at a local vLLM server."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

from openai import AsyncOpenAI

from .base import BaseProvider, ProviderResponse, ToolCall

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:8000/v1"


class VLLMProvider(BaseProvider):
    """Speaks the OpenAI-compatible API exposed by vLLM.

    vLLM exposes ``/v1/models``, ``/v1/chat/completions`` and related
    endpoints.  This provider auto-detects available models when none is
    specified and supports OpenAI-format tool calling.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        model: str | None = None,
        base_url: str = _DEFAULT_BASE_URL,
        max_tokens: int = 4096,
    ) -> None:
        config = config or {}
        self._base_url = config.get("base_url", base_url)
        self._max_tokens = config.get("max_tokens", max_tokens)
        self._client = AsyncOpenAI(
            api_key=config.get("api_key", "EMPTY"),
            base_url=self._base_url,
        )
        self._model: str | None = config.get("model") or model
        self._available_models: list[str] = []

    # ------------------------------------------------------------------
    # BaseProvider interface
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "vllm"

    def get_model_name(self) -> str:
        return self._model or "(auto-detect)"

    def supports_tools(self) -> bool:
        return True

    async def health_check(self) -> bool:
        """Verify that vLLM is reachable and serving at least one model."""
        try:
            models = await self.detect_models()
            return len(models) > 0
        except Exception as exc:
            logger.warning("vLLM health-check failed: %s", exc)
            return False

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> ProviderResponse:
        await self._ensure_model()
        kwargs = self._build_request(messages, tools, system)
        response = await self._client.chat.completions.create(**kwargs)
        return self._normalize(response)

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncGenerator[str, None]:
        await self._ensure_model()
        kwargs = self._build_request(messages, tools, system)
        kwargs["stream"] = True
        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    # ------------------------------------------------------------------
    # Model detection
    # ------------------------------------------------------------------

    async def detect_models(self) -> list[str]:
        """Query ``/v1/models`` and cache the result."""
        resp = await self._client.models.list()
        self._available_models = sorted(m.id for m in resp.data)
        logger.debug("vLLM models detected: %s", self._available_models)
        return self._available_models

    async def list_models(self) -> list[str]:
        """Public alias kept for backward compatibility."""
        return await self.detect_models()

    async def _ensure_model(self) -> None:
        """If no model was explicitly set, pick the first available one."""
        if self._model:
            return
        if not self._available_models:
            await self.detect_models()
        if self._available_models:
            self._model = self._available_models[0]
            logger.info("Auto-selected vLLM model: %s", self._model)
        else:
            raise RuntimeError("No models available on the vLLM server.")

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
