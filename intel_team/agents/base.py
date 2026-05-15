"""Abstract base for intel-team agents.

Each agent (specialist, audit, analyst, pir_router) extends ``BaseSpecialist``
and overrides ``analyze(...)``. The base centralises:

* loading the agent's Markdown system prompt from ``intel_team/prompts/``;
* tier-based model selection (``fast`` / ``specialist`` / ``analyst``);
* the single LLM call surface (``call_llm``) that goes through the existing
  ``core.provider_router.ProviderRouter`` — no parallel LLM stack.

The base is intentionally *small*. Specialists do the real work; the base
exists to keep them honest about their interface contract.
"""

from __future__ import annotations

import abc
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from intel_team.types import AgentReport, Domain, PIR

logger = logging.getLogger("intel_team.agents.base")


# Path to the markdown prompts shipped alongside the package.
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@dataclass
class AgentConfig:
    """Static configuration for a specialist class."""

    name: str
    domain: Domain
    system_prompt_file: str                       # relative to intel_team/prompts/
    allowed_tool_categories: list[str] = field(default_factory=list)
    model_tier: str = "specialist"                # "fast" | "specialist" | "analyst"
    max_tokens: int = 4096
    temperature: float = 0.2
    # Optional override of model id (else the provider's default is used)
    model_override: str | None = None


class BaseSpecialist(abc.ABC):
    """Abstract base — every intel-team agent extends this.

    Parameters
    ----------
    router:
        A ``core.provider_router.ProviderRouter`` instance (any object with an
        async ``chat(messages, system, max_tokens, temperature, model=None)``
        method works for tests).
    investigation_store:
        Optional ``core.investigation_store.InvestigationStore`` for the target.
        Specialists may consult / extend it.
    """

    config: ClassVar[AgentConfig]

    def __init__(self, router: Any, investigation_store: Any | None = None) -> None:
        self.router = router
        self.store = investigation_store
        self._system_prompt_cache: str | None = None

    # ------------------------------------------------------------------
    # Prompt management
    # ------------------------------------------------------------------

    @property
    def system_prompt(self) -> str:
        """Lazy-loaded system prompt from disk."""
        if self._system_prompt_cache is None:
            path = _PROMPTS_DIR / self.config.system_prompt_file
            if not path.exists():
                logger.warning("Prompt file missing: %s — using inline minimal prompt", path)
                self._system_prompt_cache = (
                    f"You are the {self.config.name} agent for domain "
                    f"{self.config.domain.value}. Be precise, cite sources, "
                    f"and never invent identifiers."
                )
            else:
                self._system_prompt_cache = path.read_text(encoding="utf-8")
        return self._system_prompt_cache

    # ------------------------------------------------------------------
    # LLM dispatch
    # ------------------------------------------------------------------

    async def call_llm(
        self,
        user_message: str,
        system_extra: str = "",
        *,
        model_override: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Single LLM dispatch surface — anchored to the existing ProviderRouter.

        Prompt caching: the underlying ``providers.anthropic_provider`` enables
        Anthropic prompt caching when the system prompt is large enough; nothing
        is needed here.
        """
        system = self.system_prompt
        if system_extra:
            system = f"{system}\n\n{system_extra}"

        messages = [{"role": "user", "content": user_message}]

        kwargs: dict[str, Any] = {
            "messages": messages,
            "system": system,
            "max_tokens": max_tokens if max_tokens is not None else self.config.max_tokens,
            "temperature": temperature if temperature is not None else self.config.temperature,
        }
        model = model_override or self.config.model_override
        if model:
            kwargs["model"] = model

        response = await self.router.chat(**kwargs)
        # ProviderRouter returns a ProviderResponse with .content
        return getattr(response, "content", str(response))

    # ------------------------------------------------------------------
    # Contract
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def analyze(self, pir: PIR, context: dict[str, Any]) -> AgentReport:
        """Run this agent against the PIR + context. Must return an AgentReport.

        ``context`` typically contains: ``store_summary`` (investigation snapshot),
        ``operator_notes``, ``prior_agent_reports`` (for audit/analyst), and
        ``tool_outputs`` (raw data already collected).
        """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _new_report(self, pir: PIR) -> AgentReport:
        return AgentReport(
            agent=self.config.name,
            domain=self.config.domain,
            pir_id=pir.id,
            model=self._effective_model_label(),
        )

    def _effective_model_label(self) -> str:
        """Best-effort label for the model used (for the audit trail)."""
        if self.config.model_override:
            return self.config.model_override
        try:
            return self.router.get_active_model()
        except Exception:  # router may be a test double
            return "unknown"

    async def _timed_call(self, *args: Any, **kwargs: Any) -> tuple[str, float]:
        """Call the LLM and return (content, latency_seconds)."""
        start = time.monotonic()
        content = await self.call_llm(*args, **kwargs)
        return content, time.monotonic() - start
