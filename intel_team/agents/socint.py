"""SOCINT specialist — social-media intelligence agent.

Operates over **already-collected** material (pre-existing investigation
store snapshot + recent tool outputs) and produces a structured AgentReport.

The agent does *not* execute tools — that is the orchestrator's job. The
agent reads what the operator already has, applies social-intelligence
tradecraft, and reports findings with explicit sources & confidence.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from intel_team.agents.base import AgentConfig, BaseSpecialist
from intel_team.types import (
    AgentReport,
    Credibility,
    Domain,
    Finding,
    PIR,
    Reliability,
    Source,
)

logger = logging.getLogger("intel_team.agents.socint")


class SOCINTSpecialist(BaseSpecialist):
    """Social-Media Intelligence specialist."""

    config = AgentConfig(
        name="socint_specialist",
        domain=Domain.SOCINT,
        system_prompt_file="socint.md",
        allowed_tool_categories=["socint"],
        model_tier="specialist",
        max_tokens=6000,
        temperature=0.15,
    )

    # Finding types this specialist may emit (filters LLM hallucination of types)
    _ALLOWED_TYPES = frozenset(
        {
            "username",
            "alias",
            "email",
            "display_name",
            "location",
            "org",
            "profile_url",
            "connection",
            "photo",
            "post_pattern",
            "other",
        }
    )

    # Finding types this specialist must REFUSE to emit (CLAUDE.md §3.4)
    _FORBIDDEN_TYPES = frozenset({"phone", "phone_number"})

    async def analyze(self, pir: PIR, context: dict[str, Any]) -> AgentReport:
        report = self._new_report(pir)

        try:
            content, latency = await self._timed_call(self._build_user_message(pir, context))
            report.latency_seconds = latency
        except Exception as exc:  # noqa: BLE001 — keep the pipeline alive
            logger.error("SOCINT LLM call failed: %s", exc, exc_info=True)
            report.error = f"LLM error: {exc}"
            return report

        parsed = _safe_parse_json(content)
        if parsed is None:
            report.error = "SOCINT specialist returned unparseable JSON"
            report.gaps.append("LLM output could not be parsed as JSON")
            return report

        # Findings
        for item in parsed.get("findings", []):
            f = self._coerce_finding(item)
            if f is None:
                report.rejected.append(
                    {
                        "type": item.get("finding_type", "unknown"),
                        "value": item.get("value", ""),
                        "reason": "rejected by SOCINT type/discipline check",
                        "domain": Domain.SOCINT.value,
                    }
                )
                continue
            report.add_finding(f)

        # Gaps / rejects from the model
        report.gaps.extend(str(g) for g in parsed.get("gaps", []))
        for r in parsed.get("rejected", []):
            report.rejected.append(
                {
                    "type": r.get("type", "unknown"),
                    "value": r.get("value", ""),
                    "reason": r.get("reason", ""),
                    "domain": Domain.SOCINT.value,
                }
            )

        return report

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_user_message(self, pir: PIR, context: dict[str, Any]) -> str:
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
            "Analyse the material below and produce a SOCINT report per the JSON "
            "schema in your system prompt. Return ONLY the JSON object.\n\n"
            + json.dumps(payload, indent=2, ensure_ascii=False)
        )

    def _coerce_finding(self, item: dict[str, Any]) -> Finding | None:
        ftype = str(item.get("finding_type", "")).strip().lower()
        if ftype in self._FORBIDDEN_TYPES:
            logger.warning("SOCINT refused to emit forbidden type %s", ftype)
            return None
        if ftype not in self._ALLOWED_TYPES:
            logger.debug("SOCINT remapping unknown type %r → 'other'", ftype)
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
            # No source = automatic rejection from this specialist
            return None

        return Finding(
            domain=Domain.SOCINT,
            finding_type=ftype,
            value=value,
            sources=sources,
            confidence=confidence,
            notes=str(item.get("notes", "")).strip(),
            pivot_hints=[str(p) for p in item.get("pivot_hints", [])],
        )


# ---------------------------------------------------------------------------
# Robust JSON parsing helper (shared with other specialists)
# ---------------------------------------------------------------------------


_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*", re.MULTILINE)


def _safe_parse_json(content: str) -> dict[str, Any] | None:
    """Strip code fences and parse — returns None if the result isn't an object."""
    text = _CODE_FENCE_RE.sub("", content).strip()
    if text.endswith("```"):
        text = text[: -3].strip()
    # If the model emits prose before/after the JSON, try to find the outermost object.
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
