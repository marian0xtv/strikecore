"""Audit / Red-Cell agent — devil's advocate against specialist findings.

The audit agent runs AFTER the Quality Gate has filtered/capped specialist
reports. It does not produce findings; it produces *challenges* to existing
findings. Its output is consumed by the Analyst, which may downgrade
confidences or drop findings entirely based on the challenges.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from intel_team.agents.base import AgentConfig, BaseSpecialist
from intel_team.agents.socint import _safe_parse_json  # re-use the robust JSON parser
from intel_team.types import AgentReport, Domain, PIR

logger = logging.getLogger("intel_team.agents.audit")


class AuditAgent(BaseSpecialist):
    """Red cell — challenges specialist findings before they reach the analyst."""

    config = AgentConfig(
        name="audit_red_cell",
        domain=Domain.AUDIT,
        system_prompt_file="audit.md",
        model_tier="specialist",
        max_tokens=6000,
        temperature=0.0,
    )

    async def analyze(self, pir: PIR, context: dict[str, Any]) -> AgentReport:
        """Return an AgentReport whose ``devils_advocate_notes`` carry the challenges.

        ``context`` must contain ``specialist_reports`` (list of AgentReport
        dicts, already passed through the Quality Gate) and ``store_summary``.
        """
        report = self._new_report(pir)
        specialist_reports = context.get("specialist_reports", [])
        if not specialist_reports:
            report.gaps.append("audit: no specialist reports supplied")
            return report

        payload = {
            "pir": {
                "id": pir.id,
                "question": pir.question,
                "target": pir.target,
                "constraints": pir.constraints,
            },
            "investigation_store_summary": context.get("store_summary", ""),
            "specialist_reports": specialist_reports,
        }

        try:
            content, latency = await self._timed_call(
                "Challenge the specialist reports below per your system prompt. "
                "Return ONLY the JSON object.\n\n"
                + json.dumps(payload, indent=2, ensure_ascii=False, default=str)
            )
            report.latency_seconds = latency
        except Exception as exc:  # noqa: BLE001
            logger.error("Audit LLM call failed: %s", exc, exc_info=True)
            report.error = f"LLM error: {exc}"
            return report

        parsed = _safe_parse_json(content)
        if parsed is None:
            report.error = "Audit agent returned unparseable JSON"
            return report

        # Encode each challenge as a line in devils_advocate_notes (Analyst reads this).
        for ch in parsed.get("challenges", []):
            if not isinstance(ch, dict):
                continue
            severity = str(ch.get("severity", "low")).lower()
            try:
                delta = float(ch.get("confidence_delta", 0.0))
            except (TypeError, ValueError):
                delta = 0.0
            note = (
                f"[{severity.upper()}] "
                f"type={ch.get('finding_type', '?')} "
                f"value={ch.get('finding_value', '')!r} "
                f"action={ch.get('recommended_action', 'note')} "
                f"Δconf={delta:+.2f} "
                f"— {ch.get('challenge', '')}"
            )
            report.devils_advocate_notes.append(note)

        for h in parsed.get("overlooked_hypotheses", []):
            report.devils_advocate_notes.append(f"[HYPOTHESIS] {h}")

        for p in parsed.get("process_concerns", []):
            report.devils_advocate_notes.append(f"[PROCESS] {p}")

        verdict = parsed.get("verdict_summary", "")
        if verdict:
            report.devils_advocate_notes.append(f"[VERDICT] {verdict}")

        return report
