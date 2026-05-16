"""Abstract base for intel-team agents.

Each agent (specialist, audit, analyst, pir_router) extends ``BaseSpecialist``
and overrides ``analyze(...)``. The base centralises:

* loading the agent's Markdown system prompt from ``intel_team/prompts/``;
* tier-based model selection (``fast`` / ``specialist`` / ``analyst``);
* the single LLM call surface (``call_llm``) that goes through the existing
  ``core.provider_router.ProviderRouter`` — no parallel LLM stack;
* the standard *collect-LLM-output → parse JSON → coerce Finding objects*
  pipeline shared by every domain specialist (``_standard_analyze``).

The base is intentionally *small*. Specialists do the real work; the base
exists to keep them honest about their interface contract.
"""

from __future__ import annotations

import abc
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from intel_team.types import (
    AgentReport,
    Credibility,
    Domain,
    Finding,
    PIR,
    Reliability,
    Source,
)

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

    # Overridable by subclasses. ``_ALLOWED_TYPES`` empty = accept any
    # finding_type (and pass it through unchanged). ``_FORBIDDEN_TYPES``
    # defaults to phone-extraction guard from CLAUDE.md §3.4 — specialists
    # in the phone-specific domain (none of the standard intel-team agents)
    # would override this to ``frozenset()``.
    _ALLOWED_TYPES: ClassVar[frozenset[str]] = frozenset()
    _FORBIDDEN_TYPES: ClassVar[frozenset[str]] = frozenset({"phone", "phone_number"})

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
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        """Single LLM dispatch surface — anchored to the existing ProviderRouter.

        ``core.provider_router.ProviderRouter.chat()`` accepts only
        ``messages``, ``tools``, and ``system`` — the model, max_tokens and
        temperature are sourced from the active provider's settings. Per-agent
        tuning (``self.config.max_tokens``, ``temperature``, ``model_override``)
        is reserved for a future iteration when the router grows per-call
        knobs; today the values are advisory for budgeting / documentation.

        Prompt caching: the underlying ``providers.anthropic_provider`` enables
        Anthropic prompt caching when the system prompt is large enough; the
        intel-team prompts are large markdown files specifically designed to
        benefit from that cache.
        """
        system = self.system_prompt
        if system_extra:
            system = f"{system}\n\n{system_extra}"

        messages = [{"role": "user", "content": user_message}]
        response = await self.router.chat(messages=messages, tools=tools, system=system)
        # ProviderRouter returns a ProviderResponse with .content
        return getattr(response, "content", str(response))

    # ------------------------------------------------------------------
    # Contract
    # ------------------------------------------------------------------

    async def analyze(self, pir: PIR, context: dict[str, Any]) -> AgentReport:
        """Run this agent against the PIR + context. Returns an :class:`AgentReport`.

        Default behaviour: delegate to ``_standard_analyze``, which covers the
        canonical specialist flow (LLM call → JSON parse → coerce findings).
        Agents whose pipeline diverges from that pattern (``AuditAgent``,
        ``AnalystAgent``, ``PIRRouter``) override this method directly.

        ``context`` typically contains: ``store_summary`` (investigation snapshot),
        ``operator_notes``, ``prior_agent_reports`` (for audit/analyst), and
        ``tool_outputs`` (raw data already collected).
        """
        return await self._standard_analyze(pir, context)

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

    # ------------------------------------------------------------------
    # Shared building blocks for domain specialists
    # ------------------------------------------------------------------

    _CODE_FENCE_RE: ClassVar[re.Pattern[str]] = re.compile(r"^```[a-zA-Z]*\s*", re.MULTILINE)

    @classmethod
    def _safe_parse_json(cls, content: str) -> dict[str, Any] | None:
        """Strip code fences / prose and parse the JSON object the LLM emitted.

        Returns ``None`` if the result is not a JSON object.
        """
        text = cls._CODE_FENCE_RE.sub("", content).strip()
        if text.endswith("```"):
            text = text[:-3].strip()
        # If the model emits prose before/after the JSON, find the outermost { ... }
        if not text.startswith("{"):
            first = text.find("{")
            last = text.rfind("}")
            if first != -1 and last > first:
                text = text[first : last + 1]
        try:
            obj = json.loads(text)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None

    def _coerce_finding(self, item: dict[str, Any]) -> Finding | None:
        """Convert an LLM-emitted dict into a :class:`Finding`.

        Type guard:
          * ``_FORBIDDEN_TYPES`` are dropped (returns ``None`` → caller records in ``rejected``).
          * ``_ALLOWED_TYPES``, if non-empty, remaps unknown types to ``"other"``
            (the analyst can still see them; nothing is silently dropped).

        Source-presence rule: a finding without sources cannot be emitted —
        Palantir-Maven doctrine requires every finding to have provenance.
        """
        ftype = str(item.get("finding_type", "")).strip().lower()
        if ftype in self._FORBIDDEN_TYPES:
            logger.warning("%s refused to emit forbidden type %s", self.config.name, ftype)
            return None
        if self._ALLOWED_TYPES and ftype not in self._ALLOWED_TYPES:
            logger.debug("%s remapping unknown type %r → 'other'", self.config.name, ftype)
            ftype = "other"

        value = str(item.get("value", "")).strip()
        if not value:
            return None

        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        sources: list[Source] = []
        for s in item.get("sources", []):
            if not isinstance(s, dict):
                continue
            try:
                reliability = Reliability(str(s.get("reliability", "C")).upper())
            except ValueError:
                reliability = Reliability.C
            try:
                credibility = Credibility(str(s.get("credibility", "3")))
            except ValueError:
                credibility = Credibility.THREE
            sources.append(
                Source(
                    name=str(s.get("name", "")).strip() or "unknown_source",
                    upstream=str(s.get("upstream", "")).strip(),
                    reference=str(s.get("reference", "")).strip(),
                    reliability=reliability,
                    credibility=credibility,
                )
            )
        if not sources:
            # No source = automatic rejection — doctrine requires provenance
            return None

        return Finding(
            domain=self.config.domain,
            finding_type=ftype,
            value=value,
            sources=sources,
            confidence=confidence,
            notes=str(item.get("notes", "")).strip(),
            pivot_hints=[str(p) for p in item.get("pivot_hints", [])],
        )

    def _build_user_message(self, pir: PIR, context: dict[str, Any]) -> str:
        """Default user-message builder. Specialists may override to include
        domain-specific context fields (e.g. GEOINT may want the EXIF dump).
        """
        payload = {
            "pir": {
                "id": pir.id,
                "question": pir.question,
                "target": pir.target,
                "constraints": pir.constraints,
            },
            "investigation_store_summary": context.get("store_summary", ""),
            "recent_tool_outputs": context.get("tool_outputs", {}),
            "operator_notes": context.get("operator_notes", ""),
        }
        return (
            "Analyse the material below and produce a report per the JSON "
            "schema in your system prompt. Return ONLY the JSON object.\n\n"
            + json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        )

    async def _standard_analyze(self, pir: PIR, context: dict[str, Any]) -> AgentReport:
        """The canonical *specialist* flow.

        1. Call the LLM with ``self._build_user_message(pir, context)``.
        2. Robustly parse the JSON response.
        3. For each item in ``findings``: pass through ``self._coerce_finding`` and
           append to the report or to ``rejected``.
        4. Carry through ``gaps`` and ``rejected`` from the LLM verbatim.

        Specialists that need bespoke logic (e.g. audit / analyst) override
        ``analyze`` directly. Domain specialists almost never need to.
        """
        report = self._new_report(pir)

        try:
            content, latency = await self._timed_call(self._build_user_message(pir, context))
            report.latency_seconds = latency
        except Exception as exc:  # noqa: BLE001 — keep pipeline alive
            logger.error("%s LLM call failed: %s", self.config.name, exc, exc_info=True)
            report.error = f"LLM error: {exc}"
            return report

        parsed = self._safe_parse_json(content)
        if parsed is None:
            report.error = f"{self.config.name} returned unparseable JSON"
            report.gaps.append("LLM output could not be parsed as JSON")
            return report

        for item in parsed.get("findings", []) or []:
            if not isinstance(item, dict):
                continue
            f = self._coerce_finding(item)
            if f is None:
                report.rejected.append(
                    {
                        "type": str(item.get("finding_type", "unknown")),
                        "value": str(item.get("value", "")),
                        "reason": f"rejected by {self.config.domain.value} type/discipline check",
                        "domain": self.config.domain.value,
                    }
                )
                continue
            report.add_finding(f)

        for g in parsed.get("gaps", []) or []:
            report.gaps.append(str(g))
        for r in parsed.get("rejected", []) or []:
            if not isinstance(r, dict):
                continue
            report.rejected.append(
                {
                    "type": str(r.get("type", "unknown")),
                    "value": str(r.get("value", "")),
                    "reason": str(r.get("reason", "")),
                    "domain": self.config.domain.value,
                }
            )

        return report
