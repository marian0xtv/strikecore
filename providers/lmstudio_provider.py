"""LM Studio provider using the openai SDK with JSON-mode fallback."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncGenerator

from openai import AsyncOpenAI

from .base import BaseProvider, ProviderResponse, ToolCall

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:1234/v1"

# Model families known to support native tool calling in LM Studio.
_TOOL_COMPATIBLE_PREFIXES = frozenset(
    {
        "llama-3",
        "llama3",
        "qwen2",
        "mistral",
        "codestral",
        "granite",
        "command-r",
        "hermes",
        "functionary",
    }
)

_JSON_FALLBACK_SYSTEM = """\
You have access to the following security tools. When you want to use a \
tool, respond ONLY with valid JSON matching this schema:

{{"tool_calls": [{{"name": "<tool_name>", "arguments": {{...}}}}]}}

If you do not need a tool, respond with plain text.

Available tools:
{tool_descriptions}
"""


class LMStudioProvider(BaseProvider):
    """Connects to a local LM Studio server.

    For models that support native tool calling the provider uses the
    standard OpenAI function-calling protocol.  For all other models it
    falls back to JSON-mode: the tool schemas are injected into the system
    prompt and the response is parsed as JSON.
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
            api_key=config.get("api_key", "lm-studio"),
            base_url=self._base_url,
        )
        self._model: str | None = config.get("model") or model
        self._available_models: list[str] = []

    # ------------------------------------------------------------------
    # BaseProvider interface
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "lmstudio"

    def get_model_name(self) -> str:
        return self._model or "(auto-detect)"

    def supports_tools(self) -> bool:
        """Heuristic: check if the model name contains a known tool-capable prefix."""
        if not self._model:
            return False
        lower = self._model.lower()
        return any(prefix in lower for prefix in _TOOL_COMPATIBLE_PREFIXES)

    async def health_check(self) -> bool:
        try:
            models = await self.detect_models()
            return len(models) > 0
        except Exception as exc:
            logger.warning("LM Studio health-check failed: %s", exc)
            return False

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> ProviderResponse:
        await self._ensure_model()
        use_native = tools and self.supports_tools()
        use_fallback = tools and not self.supports_tools()

        kwargs = self._build_request(
            messages, tools, system,
            native_tools=use_native,
            json_fallback=use_fallback,
        )

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message
        content = message.content or ""

        # --- extract tool calls ---
        tool_calls: list[ToolCall] | None = None

        if message.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id or str(uuid.uuid4()),
                    name=tc.function.name,
                    arguments=(
                        json.loads(tc.function.arguments)
                        if isinstance(tc.function.arguments, str)
                        else tc.function.arguments
                    ),
                )
                for tc in message.tool_calls
            ]
        elif use_fallback and content.strip():
            parsed = self._parse_json_fallback(content)
            if parsed is not None:
                tool_calls = parsed
                content = ""

        usage = response.usage
        return ProviderResponse(
            content=content,
            tool_calls=tool_calls,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=response.model or self._model or "",
            provider=self.provider_name,
            finish_reason=choice.finish_reason or "stop",
            raw=response.model_dump(),
        )

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncGenerator[str, None]:
        await self._ensure_model()
        kwargs = self._build_request(messages, tools, system, native_tools=False, json_fallback=False)
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
        """Auto-detect loaded models from LM Studio."""
        resp = await self._client.models.list()
        self._available_models = sorted(m.id for m in resp.data)
        logger.debug("LM Studio models detected: %s", self._available_models)
        return self._available_models

    async def list_models(self) -> list[str]:
        """Public alias for detect_models."""
        return await self.detect_models()

    async def _ensure_model(self) -> None:
        if self._model:
            return
        if not self._available_models:
            await self.detect_models()
        if self._available_models:
            self._model = self._available_models[0]
            logger.info("Auto-selected LM Studio model: %s", self._model)
        else:
            raise RuntimeError("No models loaded in LM Studio.")

    # ------------------------------------------------------------------
    # Request building
    # ------------------------------------------------------------------

    def _build_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        system: str | None,
        *,
        native_tools: bool,
        json_fallback: bool,
    ) -> dict[str, Any]:
        formatted: list[dict[str, Any]] = []

        # Construct system message.
        system_text = system or ""
        if json_fallback and tools:
            fallback = _JSON_FALLBACK_SYSTEM.format(
                tool_descriptions=self._tools_as_text(tools),
            )
            system_text = f"{system_text}\n\n{fallback}" if system_text else fallback

        if system_text:
            formatted.append({"role": "system", "content": system_text})

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

        if native_tools and tools:
            kwargs["tools"] = _ensure_openai_tools(tools)

        if json_fallback:
            kwargs["response_format"] = {"type": "json_object"}

        return kwargs

    # ------------------------------------------------------------------
    # JSON-mode fallback parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_fallback(text: str) -> list[ToolCall] | None:
        """Attempt to extract tool calls from a JSON-mode model response."""
        text = text.strip()
        # Strip optional markdown code fences.
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None

        if not isinstance(parsed, dict):
            return None

        # Format A: {"tool_calls": [{"name": ..., "arguments": ...}]}
        if "tool_calls" in parsed:
            calls: list[ToolCall] = []
            for tc in parsed["tool_calls"]:
                calls.append(
                    ToolCall(
                        id=str(uuid.uuid4()),
                        name=tc.get("name", ""),
                        arguments=tc.get("arguments", {}),
                    )
                )
            return calls if calls else None

        # Format B: {"tool": "name", "params": {...}}
        if "tool" in parsed:
            return [
                ToolCall(
                    id=str(uuid.uuid4()),
                    name=parsed["tool"],
                    arguments=parsed.get("params") or parsed.get("arguments", {}),
                )
            ]

        # Not a tool invocation.
        return None

    @staticmethod
    def _tools_as_text(tools: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for tool in tools:
            fn = tool.get("function", tool)
            name = fn.get("name", "unknown")
            desc = fn.get("description", "")
            params = json.dumps(
                fn.get("parameters") or fn.get("input_schema", {}),
                indent=2,
            )
            lines.append(f"- {name}: {desc}\n  Parameters: {params}")
        return "\n".join(lines)


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
