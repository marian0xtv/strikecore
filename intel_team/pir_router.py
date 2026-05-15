"""PIR Router — classifies a Priority Intelligence Requirement into intel domains.

The router is the *first* LLM call in any intel-team investigation. It reads
the PIR and decides which domain specialists to dispatch, the constraints
(passive-only, jurisdiction), and the expected pivots.

Implementation: a thin specialist that always uses the ``fast`` tier model
(Haiku-class) since classification is cheap and high-frequency.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from intel_team.agents.base import AgentConfig, BaseSpecialist
from intel_team.types import AgentReport, Domain, PIR

logger = logging.getLogger("intel_team.pir_router")


class PIRRouter(BaseSpecialist):
    """LLM-driven PIR classifier.

    Public API is :py:meth:`classify` — ``analyze`` is implemented for
    interface compatibility but returns an essentially empty report; the real
    output is the :py:class:`RoutingDecision` returned by ``classify``.
    """

    config = AgentConfig(
        name="pir_router",
        domain=Domain.META,
        system_prompt_file="pir_router.md",
        model_tier="fast",
        max_tokens=800,
        temperature=0.0,
    )

    DEFAULT_DOMAINS = [Domain.SOCINT, Domain.WEBINT]

    # Lightweight regex fallback if the LLM call fails or returns malformed JSON
    _TARGET_PATTERNS: dict[str, list[Domain]] = {
        r"^https?://": [Domain.WEBINT, Domain.TECHINT],
        r"^[\w.-]+@[\w.-]+\.[a-zA-Z]{2,}$": [Domain.WEBINT, Domain.SOCINT, Domain.CROSSDB],
        r"^\+?\d[\d\s().-]{6,}$": [Domain.CROSSDB, Domain.SOCINT],
        r"^@?[\w.]+$": [Domain.SOCINT, Domain.WEBINT],
        r"^\d{1,3}(?:\.\d{1,3}){3}$": [Domain.TECHINT, Domain.THREATINT],
    }

    async def classify(self, pir: PIR) -> "RoutingDecision":
        """Return a :class:`RoutingDecision`. Falls back to regex if LLM fails."""

        user_message = json.dumps(
            {
                "pir": {
                    "id": pir.id,
                    "question": pir.question,
                    "target": pir.target,
                    "operator_hints": [d.value for d in pir.domains_hint],
                    "constraints": pir.constraints,
                },
            },
            indent=2,
            ensure_ascii=False,
        )

        try:
            content, latency = await self._timed_call(user_message)
            decision = self._parse(content, pir)
            decision.latency_seconds = latency
            return decision
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.warning("PIR router LLM call failed (%s); falling back to regex heuristic", exc)
            return self._regex_fallback(pir, error=str(exc))

    # ------------------------------------------------------------------
    # BaseSpecialist contract
    # ------------------------------------------------------------------

    async def analyze(self, pir: PIR, context: dict[str, Any]) -> AgentReport:
        """No-op for the router; real output is via :py:meth:`classify`."""
        return self._new_report(pir)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _parse(self, content: str, pir: PIR) -> "RoutingDecision":
        cleaned = _strip_code_fence(content)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"PIR router did not return valid JSON: {exc}") from exc

        if data.get("error"):
            return RoutingDecision(
                pir_id=pir.id,
                primary_domains=[],
                secondary_domains=[],
                rationale=str(data["error"]),
                constraints={"error": data["error"]},
                expected_pivots=[],
            )

        primary = [Domain(d) for d in data.get("primary_domains", []) if d in _DOMAIN_VALUES]
        secondary = [Domain(d) for d in data.get("secondary_domains", []) if d in _DOMAIN_VALUES]
        if not primary:
            primary = self.DEFAULT_DOMAINS[:]

        return RoutingDecision(
            pir_id=pir.id,
            primary_domains=primary,
            secondary_domains=secondary,
            rationale=str(data.get("rationale", "")),
            constraints={**pir.constraints, **dict(data.get("constraints", {}))},
            expected_pivots=list(data.get("expected_pivots", [])),
        )

    def _regex_fallback(self, pir: PIR, error: str = "") -> "RoutingDecision":
        target = pir.target.strip()
        primary: list[Domain] = []
        for pat, doms in self._TARGET_PATTERNS.items():
            if re.search(pat, target):
                for d in doms:
                    if d not in primary:
                        primary.append(d)
                break
        if not primary:
            primary = list(self.DEFAULT_DOMAINS)

        return RoutingDecision(
            pir_id=pir.id,
            primary_domains=primary,
            secondary_domains=[],
            rationale=(
                "Regex fallback used (LLM router unavailable)."
                + (f" Original error: {error}" if error else "")
            ),
            constraints={**pir.constraints, "fallback": True},
            expected_pivots=[],
        )


# ---------------------------------------------------------------------------
# RoutingDecision — what the orchestrator consumes
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field  # noqa: E402 — placed near consumer for readability


@dataclass
class RoutingDecision:
    pir_id: str
    primary_domains: list[Domain] = field(default_factory=list)
    secondary_domains: list[Domain] = field(default_factory=list)
    rationale: str = ""
    constraints: dict[str, Any] = field(default_factory=dict)
    expected_pivots: list[str] = field(default_factory=list)
    latency_seconds: float = 0.0

    @property
    def all_domains(self) -> list[Domain]:
        """Primary + secondary, de-duplicated, primary first."""
        seen: set[Domain] = set()
        out: list[Domain] = []
        for d in self.primary_domains + self.secondary_domains:
            if d not in seen:
                seen.add(d)
                out.append(d)
        return out


_DOMAIN_VALUES = {d.value for d in Domain}


def _strip_code_fence(s: str) -> str:
    """Remove ``` fences around JSON, if any."""
    s = s.strip()
    if s.startswith("```"):
        # Drop opening fence (possibly with language hint)
        s = s.split("\n", 1)[-1]
        if s.endswith("```"):
            s = s[: -3]
    return s.strip()
