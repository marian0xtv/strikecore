"""Ollama provider using httpx against the native Ollama REST API."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncGenerator

import httpx

from .base import BaseProvider, ProviderResponse, ToolCall

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:11434"

TOOL_COMPATIBLE_MODELS = frozenset(
    {
        "llama3.1",
        "llama3.2",
        "qwen2.5",
        "mistral-nemo",
        "codestral",
    }
)

_JSON_FALLBACK_SYSTEM_TEMPLATE = """\
You have access to the following tools. When you want to use a tool, respond \
with a JSON object matching this schema exactly:

{{"tool_calls": [{{"name": "<tool_name>", "arguments": {{...}}}}]}}

If you do not need a tool, respond normally with plain text.

Available tools:
{tool_descriptions}
"""


class OllamaProvider(BaseProvider):
    """Talks to a local Ollama instance via its REST API."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        model: str = "llama3.2",
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        config = config or {}
        self._base_url = config.get("base_url", base_url).rstrip("/")
        self._model = config.get("model", model)
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=120.0)

    # ------------------------------------------------------------------
    # BaseProvider interface
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "ollama"

    def get_model_name(self) -> str:
        return self._model

    def supports_tools(self) -> bool:
        """True when the active model is known to handle native tool calling."""
        base_name = self._model.split(":")[0].lower()
        return base_name in TOOL_COMPATIBLE_MODELS

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get("/api/tags")
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("Ollama health-check failed: %s", exc)
            return False

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> ProviderResponse:
        payload = self._build_payload(messages, tools, system, stream=False)
        resp = await self._client.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

        if tools and not self.supports_tools():
            return self._parse_json_fallback(data)

        return self._normalize(data)

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncGenerator[str, None]:
        payload = self._build_payload(messages, tools, system, stream=True)
        async with self._client.stream("POST", "/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------

    async def list_models(self) -> list[dict[str, Any]]:
        """Return installed models via /api/tags."""
        resp = await self._client.get("/api/tags")
        resp.raise_for_status()
        return resp.json().get("models", [])

    async def list_model_names(self) -> list[str]:
        models = await self.list_models()
        return sorted(m["name"] for m in models)

    async def is_model_available(self, model: str | None = None) -> bool:
        """Check whether the given (or current) model is already pulled."""
        model = model or self._model
        names = await self.list_model_names()
        # Match with and without the :latest tag.
        return model in names or f"{model}:latest" in names

    async def pull_model(self, model: str | None = None) -> bool:
        """Pull a model from the Ollama library. Returns True on success."""
        model = model or self._model
        logger.info("Pulling Ollama model %s ...", model)
        try:
            resp = await self._client.post(
                "/api/pull",
                json={"name": model},
                timeout=600.0,
            )
            resp.raise_for_status()
            return True
        except Exception as exc:
            logger.error("Failed to pull model %s: %s", model, exc)
            return False

    async def ensure_model(self, model: str | None = None) -> bool:
        """Pull the model if it is not already available. Returns True on success."""
        model = model or self._model
        if await self.is_model_available(model):
            return True
        logger.info("Model %s not found locally, attempting pull.", model)
        return await self.pull_model(model)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        system: str | None,
        stream: bool,
    ) -> dict[str, Any]:
        formatted: list[dict[str, Any]] = []

        use_native_tools = tools and self.supports_tools()
        use_json_fallback = tools and not self.supports_tools()

        # Build the system message.
        system_text = system or ""
        if use_json_fallback:
            tool_desc = self._tools_as_text(tools)  # type: ignore[arg-type]
            fallback_system = _JSON_FALLBACK_SYSTEM_TEMPLATE.format(tool_descriptions=tool_desc)
            system_text = f"{system_text}\n\n{fallback_system}" if system_text else fallback_system

        if system_text:
            formatted.append({"role": "system", "content": system_text})

        for msg in messages:
            role = msg["role"]
            if role == "tool":
                formatted.append(
                    {
                        "role": "tool",
                        "content": msg.get("content", ""),
                    }
                )
            else:
                formatted.append({"role": role, "content": msg.get("content", "")})

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": formatted,
            "stream": stream,
        }

        if use_native_tools:
            payload["tools"] = self._convert_tools(tools)  # type: ignore[arg-type]

        if use_json_fallback:
            payload["format"] = "json"

        return payload

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Ensure tools are in Ollama's expected format."""
        converted: list[dict[str, Any]] = []
        for tool in tools:
            if tool.get("type") == "function":
                converted.append(tool)
            else:
                converted.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": tool.get("description", ""),
                            "parameters": tool.get("input_schema") or tool.get("parameters", {}),
                        },
                    }
                )
        return converted

    @staticmethod
    def _tools_as_text(tools: list[dict[str, Any]]) -> str:
        """Render tools as human-readable text for the JSON-mode fallback."""
        lines: list[str] = []
        for tool in tools:
            if tool.get("type") == "function":
                fn = tool["function"]
            else:
                fn = tool
            name = fn.get("name", "unknown")
            desc = fn.get("description", "")
            params = json.dumps(fn.get("parameters") or fn.get("input_schema", {}), indent=2)
            lines.append(f"- {name}: {desc}\n  Parameters: {params}")
        return "\n".join(lines)

    def _normalize(self, data: dict[str, Any]) -> ProviderResponse:
        message = data.get("message", {})
        content = message.get("content", "")

        tool_calls: list[ToolCall] | None = None
        raw_calls = message.get("tool_calls")
        if raw_calls:
            tool_calls = []
            for idx, tc in enumerate(raw_calls):
                fn = tc.get("function", {})
                tool_calls.append(
                    ToolCall(
                        id=f"call_{idx}",
                        name=fn.get("name", ""),
                        arguments=fn.get("arguments", {}),
                    )
                )

        return ProviderResponse(
            content=content,
            tool_calls=tool_calls,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            model=data.get("model", self._model),
            provider=self.provider_name,
            finish_reason=data.get("done_reason", "stop"),
            raw=data,
        )

    def _parse_json_fallback(self, data: dict[str, Any]) -> ProviderResponse:
        """Extract tool calls from a JSON-mode response produced by a non-tool model."""
        message = data.get("message", {})
        raw_content = message.get("content", "")

        tool_calls: list[ToolCall] | None = None
        content = raw_content

        try:
            parsed = json.loads(raw_content)
            if isinstance(parsed, dict) and "tool_calls" in parsed:
                tool_calls = []
                for idx, tc in enumerate(parsed["tool_calls"]):
                    tool_calls.append(
                        ToolCall(
                            id=f"json_call_{idx}",
                            name=tc.get("name", ""),
                            arguments=tc.get("arguments", {}),
                        )
                    )
                content = ""
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.debug("JSON fallback parsing failed; treating as plain text.")

        return ProviderResponse(
            content=content,
            tool_calls=tool_calls,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            model=data.get("model", self._model),
            provider=self.provider_name,
            finish_reason=data.get("done_reason", "stop"),
            raw=data,
        )

    async def aclose(self) -> None:
        """Shut down the underlying httpx client."""
        await self._client.aclose()
