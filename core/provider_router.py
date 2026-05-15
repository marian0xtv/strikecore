"""
Provider router with fallback chain and per-provider statistics for StrikeCore.

Reads the active provider and fallback chain from the Settings singleton,
lazily instantiates the correct provider class, and provides a unified
``chat()`` / ``stream_chat()`` interface that automatically falls through
the chain when a provider returns an error.
"""

from __future__ import annotations

import importlib
import os
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from rich.console import Console
from rich.table import Table

from providers.base import BaseProvider, ProviderResponse

# ---------------------------------------------------------------------------
# Provider stats
# ---------------------------------------------------------------------------

# Approximate per-1K-token cost for rough estimation.  Values are intentionally
# conservative and are updated infrequently -- they exist only to give the
# operator a ballpark idea of spend.
_COST_PER_1K: dict[str, dict[str, float]] = {
    "anthropic": {"input": 0.003, "output": 0.015},
    "openrouter": {"input": 0.002, "output": 0.010},
    "ollama": {"input": 0.0, "output": 0.0},
    "vllm": {"input": 0.0, "output": 0.0},
    "lmstudio": {"input": 0.0, "output": 0.0},
    "custom": {"input": 0.001, "output": 0.005},
}


@dataclass
class ProviderStats:
    """Accumulated per-provider statistics."""

    total_requests: int = 0
    total_errors: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_latency: float = 0.0
    last_error: str = ""
    last_request_at: float = 0.0

    @property
    def avg_latency(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_latency / self.total_requests

    @property
    def error_rate(self) -> float:
        total = self.total_requests + self.total_errors
        if total == 0:
            return 0.0
        return self.total_errors / total

    def estimated_cost(self, provider_name: str) -> float:
        """Rough USD cost estimate based on token counts."""
        rates = _COST_PER_1K.get(provider_name, {"input": 0.0, "output": 0.0})
        return (
            (self.total_input_tokens / 1000) * rates["input"]
            + (self.total_output_tokens / 1000) * rates["output"]
        )

    def to_dict(self, provider_name: str = "") -> dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "error_rate": round(self.error_rate, 4),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "avg_latency_seconds": round(self.avg_latency, 3),
            "estimated_cost_usd": round(self.estimated_cost(provider_name), 4),
            "last_error": self.last_error,
        }


# ---------------------------------------------------------------------------
# Provider class registry (dotted import path -> class)
# ---------------------------------------------------------------------------

PROVIDER_MAP: dict[str, str] = {
    "anthropic": "providers.anthropic_provider.AnthropicProvider",
    "openrouter": "providers.openrouter_provider.OpenRouterProvider",
    "ollama": "providers.ollama_provider.OllamaProvider",
    "vllm": "providers.vllm_provider.VLLMProvider",
    "lmstudio": "providers.lmstudio_provider.LMStudioProvider",
    "custom": "providers.generic_openai.GenericOpenAIProvider",
}

# Environment variable names for API keys, keyed by provider name.
_ENV_KEY_MAP: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "vllm": "VLLM_API_KEY",
    "custom": "CUSTOM_API_KEY",
}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class ProviderRouter:
    """Routes AI requests to the active provider with automatic fallback.

    Parameters
    ----------
    settings:
        A :class:`~strikecore.config.settings.Settings` instance (or any
        object providing ``.get(key, default)``).
    console:
        Optional Rich console for status output.

    Usage::

        from config.settings import get_settings
        router = ProviderRouter(get_settings())
        response = await router.chat(messages=[...], system="...")
    """

    def __init__(self, settings: Any, console: Console | None = None) -> None:
        self.settings = settings
        self._console = console or Console()
        self._providers: dict[str, BaseProvider] = {}
        self._stats: dict[str, ProviderStats] = {}
        self._active_name: str = settings.get("ai.active_provider", "anthropic")
        self._fallback_chain: list[str] = list(
            settings.get("ai.fallback_chain", [self._active_name])
        )

        # Ensure the active provider is at the head of the chain.
        if self._active_name not in self._fallback_chain:
            self._fallback_chain.insert(0, self._active_name)

        self._init_providers()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_providers(self) -> None:
        """Eagerly instantiate every provider in the fallback chain."""
        for name in self._fallback_chain:
            try:
                provider = self._create_provider(name)
                if provider is not None:
                    self._providers[name] = provider
                    self._stats[name] = ProviderStats()
            except Exception as exc:
                self._stats[name] = ProviderStats(last_error=str(exc))

    def _create_provider(self, name: str) -> BaseProvider | None:
        """Dynamically import and instantiate a provider by *name*."""
        dotted = PROVIDER_MAP.get(name)
        if dotted is None:
            return None

        module_path, class_name = dotted.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)

        # Build config dict from settings.
        config: dict[str, Any] = {}
        raw = self.settings.get(f"ai.{name}", {})
        if isinstance(raw, dict):
            config.update(raw)

        # Override API key from environment variable if available.
        env_key = _ENV_KEY_MAP.get(name)
        if env_key:
            env_val = os.environ.get(env_key)
            if env_val:
                config["api_key"] = env_val

        return cls(config)

    # ------------------------------------------------------------------
    # Provider access
    # ------------------------------------------------------------------

    def get_active_provider(self) -> BaseProvider | None:
        """Return the currently active provider instance, or ``None``."""
        return self._providers.get(self._active_name)

    def get_active_name(self) -> str:
        """Return the name of the currently active provider."""
        return self._active_name

    def get_active_model(self) -> str:
        """Return the model name from the active provider."""
        provider = self.get_active_provider()
        return provider.get_model_name() if provider else "unknown"

    # ------------------------------------------------------------------
    # Provider switching
    # ------------------------------------------------------------------

    def switch_provider(self, name: str) -> bool:
        """Switch the active provider to *name*.

        If the provider has not been instantiated yet, it is created on the
        fly.  Returns ``True`` on success.
        """
        if name in self._providers:
            self._active_name = name
            return True

        # Try to create on demand.
        try:
            provider = self._create_provider(name)
            if provider is not None:
                self._providers[name] = provider
                self._stats.setdefault(name, ProviderStats())
                self._active_name = name
                return True
        except Exception:
            pass
        return False

    def switch_model(self, model: str) -> None:
        """Change the model on the active provider (if supported)."""
        provider = self.get_active_provider()
        if provider is not None and hasattr(provider, "model"):
            provider.model = model  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Chat (with fallback)
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> ProviderResponse:
        """Send a chat completion request through the fallback chain.

        Tries the active provider first, then each subsequent provider in the
        fallback chain.  If all fail, raises ``ConnectionError``.
        """
        chain = self._ordered_chain()
        last_error: Exception | None = None

        for name in chain:
            provider = self._providers.get(name)
            if provider is None:
                continue

            stats = self._stats.setdefault(name, ProviderStats())
            start = time.monotonic()

            try:
                # Only pass tools if the provider supports them.
                effective_tools = tools if provider.supports_tools() else None
                response = await provider.chat(messages, effective_tools, system)

                latency = time.monotonic() - start
                stats.total_requests += 1
                stats.total_latency += latency
                stats.total_input_tokens += response.input_tokens
                stats.total_output_tokens += response.output_tokens
                stats.last_request_at = time.time()

                # Tag the response with the provider that actually served it.
                response.provider = name
                return response

            except Exception as exc:
                latency = time.monotonic() - start
                stats.total_errors += 1
                stats.total_latency += latency
                stats.last_error = str(exc)
                last_error = exc

                # Log the failure and continue to the next provider.
                self._console.print(
                    f"[yellow]Provider '{name}' failed: {exc}  "
                    f"-- falling back...[/yellow]"
                )
                continue

        raise ConnectionError(
            f"All providers in the fallback chain failed.  "
            f"Last error: {last_error}"
        )

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream a chat completion from the active provider.

        Streaming does **not** use the fallback chain because partial output
        has already been emitted.  Falls back to non-streaming ``chat()`` if
        streaming is not available.
        """
        chain = self._ordered_chain()
        last_error: Exception | None = None

        for name in chain:
            provider = self._providers.get(name)
            if provider is None:
                continue

            stats = self._stats.setdefault(name, ProviderStats())
            start = time.monotonic()

            try:
                effective_tools = tools if provider.supports_tools() else None
                async for chunk in provider.stream_chat(messages, effective_tools, system):
                    yield chunk

                latency = time.monotonic() - start
                stats.total_requests += 1
                stats.total_latency += latency
                stats.last_request_at = time.time()
                return  # success

            except Exception as exc:
                stats.total_errors += 1
                stats.last_error = str(exc)
                last_error = exc
                continue

        raise ConnectionError(
            f"All providers failed for streaming. Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    async def health_check_all(self) -> dict[str, bool]:
        """Run health checks on all instantiated providers."""
        results: dict[str, bool] = {}
        for name, provider in self._providers.items():
            try:
                results[name] = await provider.health_check()
            except Exception:
                results[name] = False
        return results

    # ------------------------------------------------------------------
    # Stats and listing
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, ProviderStats]:
        """Return per-provider statistics."""
        return dict(self._stats)

    def list_providers(self) -> list[dict[str, Any]]:
        """Return a list of provider info dicts for display."""
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for name in self._fallback_chain:
            if name in seen:
                continue
            seen.add(name)
            provider = self._providers.get(name)
            stats = self._stats.get(name, ProviderStats())
            result.append({
                "name": name,
                "active": name == self._active_name,
                "loaded": provider is not None,
                "model": provider.get_model_name() if provider else "N/A",
                "supports_tools": provider.supports_tools() if provider else False,
                "requests": stats.total_requests,
                "errors": stats.total_errors,
                "avg_latency": f"{stats.avg_latency:.2f}s",
                "estimated_cost": f"${stats.estimated_cost(name):.4f}",
                "error_rate": f"{stats.error_rate:.1%}",
            })
        return result

    def print_stats(self) -> None:
        """Print a Rich table summarising provider statistics."""
        table = Table(title="Provider Statistics", show_lines=True)
        table.add_column("Provider", style="cyan")
        table.add_column("Active", justify="center")
        table.add_column("Model", style="white")
        table.add_column("Tools", justify="center")
        table.add_column("Requests", justify="right")
        table.add_column("Errors", justify="right")
        table.add_column("Avg Latency", justify="right")
        table.add_column("Est. Cost", justify="right")

        for info in self.list_providers():
            active_marker = "[green]>>>[/green]" if info["active"] else ""
            tools_marker = "[green]Y[/green]" if info["supports_tools"] else "[red]N[/red]"
            err_style = "red" if info["errors"] > 0 else "dim"
            table.add_row(
                info["name"],
                active_marker,
                info["model"],
                tools_marker,
                str(info["requests"]),
                f"[{err_style}]{info['errors']}[/{err_style}]",
                info["avg_latency"],
                info["estimated_cost"],
            )

        self._console.print(table)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ordered_chain(self) -> list[str]:
        """Return the fallback chain with the active provider first."""
        chain = [self._active_name]
        for name in self._fallback_chain:
            if name != self._active_name:
                chain.append(name)
        return chain
