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

try:  # rich is a UI nicety — the router must run headless (cron, hooks, dry-runs)
    from rich.console import Console
    from rich.table import Table
except ImportError:  # pragma: no cover - exercised in minimal environments
    class Console:  # minimal stand-in with a .print()
        def print(self, *args, **kwargs):
            print(*[a for a in args])

    class Table:  # placeholder; real rendering only used when rich is present
        def __init__(self, *a, **k): ...
        def add_column(self, *a, **k): ...
        def add_row(self, *a, **k): ...

from providers.base import BaseProvider, ProviderResponse
from governance.model_router import (
    ModelPolicy,
    policy_from_settings,
    resolve_model_name,
)
from governance.token_ledger import estimate_cost_micros, log_llm_call


# Account-availability remap. Claude Fable 5 is not available on this account
# (the API returns HTTP 404 directing to Opus 4.8). The routing *policy* still
# expresses intent (heaviest reasoning -> the "fable" tier); this provider-layer
# substitution makes those calls actually succeed by routing them to Opus 4.8.
# Cost is recorded against the model truly called. One-line revert when Fable
# access is granted: empty this dict.
_UNAVAILABLE_MODEL_SUBSTITUTIONS: dict[str, str] = {
    "claude-fable-5": "claude-opus-4-8",
}


# ---------------------------------------------------------------------------
# Per-call cost telemetry (cost-aware router, GR3)
# ---------------------------------------------------------------------------


@dataclass
class CallRecord:
    """One LLM call's routing decision + token usage + estimated cost."""

    task_type: str
    model: str
    routing_reason: str
    input_tokens: int
    output_tokens: int
    cost_micros: int
    dry_run: bool = False


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

        # Cost-aware routing (GR3): the shared policy + an in-memory ledger so
        # cost is visible per run/mode without depending on Postgres.
        self.policy: ModelPolicy = policy_from_settings(settings)
        self._dry_run: bool = bool(settings.get("ai.model_policy.dry_run", False))
        self.call_log: list[CallRecord] = []

    # ------------------------------------------------------------------
    # Cost-aware routing API
    # ------------------------------------------------------------------

    def set_policy(self, policy: ModelPolicy) -> None:
        self.policy = policy

    def set_dry_run(self, on: bool) -> None:
        self._dry_run = bool(on)

    def reset_log(self) -> None:
        self.call_log = []

    def run_cost(self) -> dict[str, Any]:
        """Aggregate the in-memory call log into a per-mode cost summary."""
        by_model: dict[str, dict[str, int]] = {}
        by_task: dict[str, dict[str, Any]] = {}
        total_in = total_out = total_cost = 0
        for r in self.call_log:
            total_in += r.input_tokens
            total_out += r.output_tokens
            total_cost += r.cost_micros
            m = by_model.setdefault(r.model, {"calls": 0, "input_tokens": 0,
                                              "output_tokens": 0, "cost_micros": 0})
            m["calls"] += 1
            m["input_tokens"] += r.input_tokens
            m["output_tokens"] += r.output_tokens
            m["cost_micros"] += r.cost_micros
            t = by_task.setdefault(r.task_type or "unknown",
                                   {"model": r.model, "reason": r.routing_reason,
                                    "calls": 0, "cost_micros": 0})
            t["calls"] += 1
            t["cost_micros"] += r.cost_micros
        return {
            "profile": self.policy.profile,
            "policy": self.policy.as_dict(),
            "totals": {"calls": len(self.call_log), "input_tokens": total_in,
                       "output_tokens": total_out, "cost_usd_micros": total_cost},
            "by_model": by_model,
            "by_task_type": by_task,
        }

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
        *,
        task_type: str | None = None,
        model: str | None = None,
        dry_run: bool | None = None,
    ) -> ProviderResponse:
        """Send a chat completion request through the fallback chain.

        The cost-aware router (GR3) picks the model from ``self.policy`` based on
        ``task_type`` unless an explicit ``model`` is given. Every call is
        recorded to ``self.call_log`` with model/reason/tokens/cost. When
        ``dry_run`` is on, no provider is called — a synthetic response is
        returned with estimated tokens so routing + cost can be exercised
        offline.
        """
        # 1) resolve the model + routing reason
        if model:
            chosen, reason = resolve_model_name(model), f"explicit:{resolve_model_name(model)}"
        else:
            chosen, reason = self.policy.resolve(task_type)

        # 1b) substitute account-unavailable models (e.g. Fable 5 -> Opus 4.8)
        substitute = _UNAVAILABLE_MODEL_SUBSTITUTIONS.get(chosen)
        if substitute:
            reason = f"{reason} (unavailable:{chosen}->{substitute})"
            chosen = substitute

        # 2) dry-run short-circuit (no network, no credits)
        use_dry = self._dry_run if dry_run is None else dry_run
        if use_dry:
            return self._dry_run_response(messages, system, chosen, reason, task_type)

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
                try:
                    response = await provider.chat(
                        messages, effective_tools, system,
                        model=chosen, task_type=task_type,
                    )
                except TypeError:
                    # provider not yet updated for the per-call model knob
                    response = await provider.chat(messages, effective_tools, system)

                latency = time.monotonic() - start
                stats.total_requests += 1
                stats.total_latency += latency
                stats.total_input_tokens += response.input_tokens
                stats.total_output_tokens += response.output_tokens
                stats.last_request_at = time.time()

                # Tag the response with the provider that actually served it.
                response.provider = name
                response.task_type = task_type or ""
                response.routing_reason = reason
                self._record_call(response, name, chosen, reason, task_type, latency)
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

    # ------------------------------------------------------------------
    # Telemetry helpers
    # ------------------------------------------------------------------

    def _record_call(self, response: ProviderResponse, provider_name: str,
                     model: str, reason: str, task_type: str | None,
                     latency: float) -> None:
        """Record one live call's cost to the in-memory ledger + best-effort DB."""
        try:
            cost = estimate_cost_micros(
                response.model or model,
                response.input_tokens, response.output_tokens,
                getattr(response, "cached_read_tokens", 0),
                getattr(response, "cache_write_tokens", 0),
            )
        except Exception:  # noqa: BLE001
            cost = 0
        self.call_log.append(CallRecord(
            task_type=task_type or "", model=response.model or model,
            routing_reason=reason, input_tokens=response.input_tokens,
            output_tokens=response.output_tokens, cost_micros=cost, dry_run=False,
        ))
        # Best-effort Postgres ledger (no-op without psycopg2).
        try:
            log_llm_call(
                provider=provider_name, model=response.model or model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cached_tokens=getattr(response, "cached_read_tokens", 0),
                cache_write_tokens=getattr(response, "cache_write_tokens", 0),
                latency_ms=int(latency * 1000), task_type=task_type,
            )
        except Exception:  # noqa: BLE001
            pass

    def _dry_run_response(self, messages: list[dict[str, Any]], system: str | None,
                          model: str, reason: str,
                          task_type: str | None) -> ProviderResponse:
        """Synthetic response for offline routing/cost verification (no network)."""
        text = (system or "")
        for m in messages or []:
            c = m.get("content", "")
            text += c if isinstance(c, str) else str(c)
        in_tokens = max(1, len(text) // 4)
        out_tokens = 200  # nominal generation
        try:
            cost = estimate_cost_micros(model, in_tokens, out_tokens)
        except Exception:  # noqa: BLE001
            cost = 0
        self.call_log.append(CallRecord(
            task_type=task_type or "", model=model, routing_reason=reason,
            input_tokens=in_tokens, output_tokens=out_tokens,
            cost_micros=cost, dry_run=True,
        ))
        return ProviderResponse(
            content=f"[dry-run:{model}] {reason}",
            tool_calls=None, input_tokens=in_tokens, output_tokens=out_tokens,
            model=model, provider="dry-run", finish_reason="end_turn",
            raw={"dry_run": True}, task_type=task_type or "", routing_reason=reason,
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
