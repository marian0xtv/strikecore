"""Abstract base class for all StrikeCore AI providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator


@dataclass
class ToolCall:
    """Represents a single tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ProviderResponse:
    """Normalized response returned by every provider implementation."""

    content: str
    tool_calls: list[ToolCall] | None
    input_tokens: int
    output_tokens: int
    model: str
    provider: str
    finish_reason: str
    raw: dict[str, Any]


class BaseProvider(ABC):
    """Contract that every AI provider must satisfy.

    Subclasses implement chat completion, streaming, tool support detection,
    and a lightweight health check so the orchestrator can route requests
    across heterogeneous backends.
    """

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> ProviderResponse:
        """Send a chat completion request and return a normalized response."""
        ...

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Yield partial content strings as they arrive from the model."""
        ...

    @abstractmethod
    def supports_tools(self) -> bool:
        """Return True if the current model supports native tool calling."""
        ...

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the identifier of the model in use."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider endpoint is reachable and functional."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable name for this provider (e.g. 'anthropic', 'ollama')."""
        ...
