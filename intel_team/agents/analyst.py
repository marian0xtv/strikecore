"""Analyst — final dossier synthesiser (Opus tier).

Reads every specialist's AgentReport (post Quality-Gate), every Audit
challenge, and the investigation-store snapshot, and produces the Dossier
the operator sees.

Implements formal intel tradecraft:
- BLUF
- Key Judgments (with confidence and sources)
- Analysis of Competing Hypotheses (ACH)
- Key Assumptions Check
- Source Reliability Matrix (NATO Admiralty A1–F6)
- Intelligence Gaps
- Recommended Next Actions
"""

from __future__ import annotations

import json
import logging
from typing import Any

from intel_team.agents.base import AgentConfig, BaseSpecialist
from intel_team.agents.socint import _safe_parse_json
from intel_team.types import AgentReport, Domain, Dossier, PIR

logger = logging.getLogger("intel_team.agents.analyst")

# --- Phase B compatibility: agent.executor passes specialist/audit reports as
# already-dictified payloads (per tool_gateway). The analyst was written assuming
# AgentReport objects. These helpers tolerate both.
def _to_dict(r):
    if isinstance(r, dict):
        return r
    if hasattr(r, "to_dict"):
        return r.to_dict()
    return {"raw": repr(r)}

def _g(r, name, default=None):
    if isinstance(r, dict):
        return r.get(name, default)
    return getattr(r, name, default)



class AnalystAgent(BaseSpecialist):
    """Top-of-pipeline synthesiser. Uses the highest-quality model tier."""

    config = AgentConfig(
        name="analyst",
        domain=Domain.ANALYST,
        system_prompt_file="analyst.md",
        model_tier="analyst",
        max_tokens=8000,
        temperature=0.2,
    )

    async def synthesize(
        self,
        pir: PIR,
        *,
        specialist_reports: list[AgentReport],
        audit_reports: list[AgentReport],
        store_summary: str = "",
        operator_notes: str = "",
    ) -> Dossier:
        """Produce a :class:`Dossier`. Falls back to a structural dossier on LLM error."""
        payload = {
            "pir": {
                "id": pir.id,
                "question": pir.question,
                "target": pir.target,
                "constraints": pir.constraints,
            },
            "specialist_reports": [_to_dict(r) for r in specialist_reports],
            "audit_reports": [_to_dict(r) for r in audit_reports],
            "investigation_store_summary": store_summary,
            "operator_notes": operator_notes,
        }

        try:
            content, _latency = await self._timed_call(
                "Synthesise the dossier per your system prompt. "
                "Return ONLY the JSON object.\n\n"
                + json.dumps(payload, indent=2, ensure_ascii=False, default=str)
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Analyst LLM call failed: %s", exc, exc_info=True)
            return self._structural_fallback(pir, specialist_reports, audit_reports, error=str(exc))

        parsed = _safe_parse_json(content)
        if parsed is None:
            logger.error("Analyst returned unparseable JSON; structural fallback")
            return self._structural_fallback(
                pir, specialist_reports, audit_reports, error="unparseable JSON"
            )

        return self._build_dossier(pir, parsed, specialist_reports, audit_reports)

    # ------------------------------------------------------------------
    # BaseSpecialist contract — delegates to ``synthesize``
    # ------------------------------------------------------------------

    async def analyze(self, pir: PIR, context: dict[str, Any]) -> AgentReport:
        report = self._new_report(pir)
        try:
            dossier = await self.synthesize(
                pir,
                specialist_reports=context.get("specialist_reports", []),
                audit_reports=context.get("audit_reports", []),
                store_summary=context.get("store_summary", ""),
                operator_notes=context.get("operator_notes", ""),
            )
            # Store the dossier on the report for the orchestrator
            report.devils_advocate_notes.append("[DOSSIER]" + json.dumps(dossier.to_dict()))
        except Exception as exc:  # noqa: BLE001
            logger.error("Analyst.analyze failed: %s", exc, exc_info=True)
            report.error = f"Analyst error: {exc}"
        return report

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_dossier(
        self,
        pir: PIR,
        parsed: dict[str, Any],
        specialist_reports: list[AgentReport],
        audit_reports: list[AgentReport],
    ) -> Dossier:
        d = Dossier(target=pir.target, pir_id=pir.id, pir_question=pir.question)
        d.bluf = str(parsed.get("bluf", "")).strip()
        d.key_judgments = [
            {
                "judgment": str(kj.get("judgment", "")),
                "confidence": float(kj.get("confidence", 0.0) or 0.0),
                "sources": [str(s) for s in kj.get("sources", [])],
                "ach_rationale": str(kj.get("ach_rationale", "")),
            }
            for kj in parsed.get("key_judgments", [])
            if isinstance(kj, dict)
        ]
        d.ach_summary = str(parsed.get("ach_summary", "")).strip()
        d.key_assumptions = [str(a) for a in parsed.get("key_assumptions", [])]
        d.source_reliability_matrix = [
            {
                "name": str(s.get("name", "")),
                "upstream": str(s.get("upstream", "")),
                "reliability": str(s.get("reliability", "")),
                "credibility": str(s.get("credibility", "")),
                "admiralty": str(s.get("admiralty", "")),
            }
            for s in parsed.get("source_reliability_matrix", [])
            if isinstance(s, dict)
        ]
        d.intelligence_gaps = [str(g) for g in parsed.get("intelligence_gaps", [])]
        d.recommended_actions = [str(a) for a in parsed.get("recommended_actions", [])]
        d.findings_by_domain = {
            str(k): list(v) for k, v in parsed.get("findings_by_domain", {}).items() if isinstance(v, list)
        }
        d.agent_reports = [_to_dict(r) for r in specialist_reports]
        d.audit_trail = [
            f"audit:{_g(r, 'agent', '?')}:{len(_g(r, 'devils_advocate_notes', []) or [])} note(s)"
            for r in audit_reports
        ]
        return d

    def _structural_fallback(
        self,
        pir: PIR,
        specialist_reports: list[AgentReport],
        audit_reports: list[AgentReport],
        *,
        error: str = "",
    ) -> Dossier:
        """Build a deterministic dossier from the raw reports when the Analyst LLM fails.

        The dossier is correct but missing the narrative layer (no ACH text, no
        Key Assumptions). The operator can still review the findings.
        """
        d = Dossier(target=pir.target, pir_id=pir.id, pir_question=pir.question)
        d.bluf = (
            "Analyst LLM unavailable — structural dossier only. "
            "Review specialist findings directly."
            + (f" Error: {error}" if error else "")
        )

        # Surface all findings by domain
        by_domain: dict[str, list[dict[str, Any]]] = {}
        for r in specialist_reports:
            dom = _g(r, "domain", "unknown")
            key = getattr(dom, "value", dom) if dom else "unknown"
            bucket = by_domain.setdefault(key, [])
            for f in (_g(r, "findings", []) or []):
                d_item = f if isinstance(f, dict) else (f.to_dict() if hasattr(f, "to_dict") else {})
                bucket.append(
                    {
                        "type": d_item.get("type", ""),
                        "value": d_item.get("value", ""),
                        "confidence": d_item.get("confidence", 0.0),
                        "independent_sources": d_item.get("independent_sources", 0),
                        "notes": d_item.get("notes", ""),
                    }
                )
        d.findings_by_domain = by_domain

        # Promote the strongest single finding per domain to a Key Judgment
        for domain_key, items in by_domain.items():
            if not items:
                continue
            top = max(items, key=lambda x: x.get("confidence", 0.0))
            d.key_judgments.append(
                {
                    "judgment": f"{domain_key.upper()}: {top['type']}={top['value']}",
                    "confidence": top["confidence"],
                    "sources": [],
                    "ach_rationale": "structural fallback — highest-confidence finding for the domain",
                }
            )

        # Aggregate gaps and audit notes
        for r in specialist_reports:
            d.intelligence_gaps.extend(_g(r, "gaps", []) or [])
        for r in audit_reports:
            d.intelligence_gaps.extend(
                f"audit: {n}" for n in (_g(r, "devils_advocate_notes", []) or []) if "[VERDICT]" in str(n)
            )

        d.recommended_actions = [
            "Re-run the analyst once the LLM provider is reachable.",
            "Manually triage the highest-confidence findings above.",
        ]
        d.agent_reports = [_to_dict(r) for r in specialist_reports]
        d.audit_trail = [
            f"audit:{_g(r, 'agent', '?')}:{len(_g(r, 'devils_advocate_notes', []) or [])} note(s)"
            for r in audit_reports
        ]
        return d
