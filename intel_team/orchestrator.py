"""Orchestrator — end-to-end intel-team pipeline.

```
PIR → pir_router → specialists (parallel) → quality_gate → audit → analyst → Dossier
```

The orchestrator owns the dispatch logic, parallelism, error handling, and
the audit trail entry that ties everything to the PIR. It is the public
entry point used by ``bin/intel-team.py`` and (eventually) the existing
``cli/shell.py``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from intel_team.agents.analyst import AnalystAgent
from intel_team.agents.audit import AuditAgent
from intel_team.agents.base import BaseSpecialist
from intel_team.agents.geoint import GEOINTSpecialist
from intel_team.agents.socialint import SOCIALINTSpecialist
from intel_team.agents.socint import SOCINTSpecialist
from intel_team.agents.webint import WEBINTSpecialist
from intel_team.pir_router import PIRRouter, RoutingDecision
from intel_team.quality_gate import QualityGate
from intel_team.types import AgentReport, Domain, Dossier, PIR

logger = logging.getLogger("intel_team.orchestrator")


# ---------------------------------------------------------------------------
# Domain → specialist class registry. Add new specialists here when they ship.
# ---------------------------------------------------------------------------

SPECIALIST_REGISTRY: dict[Domain, type[BaseSpecialist]] = {
    Domain.SOCINT: SOCINTSpecialist,
    Domain.SOCIALINT: SOCIALINTSpecialist,
    Domain.GEOINT: GEOINTSpecialist,
    Domain.WEBINT: WEBINTSpecialist,
    # TECHINT, THREATINT, CROSSDB, REDTEAM specialists remain on the roadmap.
    # Until they ship, the orchestrator records them as gaps so the analyst
    # surfaces the missing coverage to the operator instead of silently
    # skipping the domain.
}


class IntelTeam:
    """The embedded intel team — public entry point.

    Parameters
    ----------
    router:
        ``core.provider_router.ProviderRouter`` instance.
    investigation_store:
        Optional ``core.investigation_store.InvestigationStore`` to consult.
    audit_dir:
        Optional override for the audit JSONL directory
        (default: ``~/.strikecore/audit``).
    """

    def __init__(
        self,
        router: Any,
        investigation_store: Any | None = None,
        audit_dir: Path | None = None,
    ) -> None:
        self.router = router
        self.store = investigation_store
        self.quality_gate = QualityGate()
        self.pir_router = PIRRouter(router, investigation_store)
        self.audit_agent = AuditAgent(router, investigation_store)
        self.analyst = AnalystAgent(router, investigation_store)
        self.audit_dir = Path(audit_dir) if audit_dir else Path.home() / ".strikecore" / "audit"

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def investigate(
        self,
        pir: PIR,
        *,
        tool_outputs: dict[str, Any] | None = None,
        operator_notes: str = "",
    ) -> Dossier:
        """Run the full pipeline and return a Dossier."""
        t0 = time.monotonic()
        store_summary = self._get_store_summary()

        # 1. Routing
        decision = await self.pir_router.classify(pir)
        self._audit("pir_routed", pir, {
            "primary": [d.value for d in decision.primary_domains],
            "secondary": [d.value for d in decision.secondary_domains],
            "constraints": decision.constraints,
            "latency_seconds": round(decision.latency_seconds, 2),
        })

        # 2. Dispatch specialists in parallel
        specialist_reports = await self._dispatch_specialists(
            pir,
            decision,
            store_summary=store_summary,
            tool_outputs=tool_outputs or {},
            operator_notes=operator_notes,
        )

        # 3. Quality gate (sequential — fast, mutates in place)
        for r in specialist_reports:
            self.quality_gate.apply(r)
        self._audit("quality_gate_applied", pir, {
            "reports": [
                {
                    "agent": r.agent,
                    "kept": len(r.findings),
                    "rejected": len(r.rejected),
                    "confidence_summary": r.confidence_summary,
                }
                for r in specialist_reports
            ]
        })

        # 4. Audit / red cell
        audit_report = await self.audit_agent.analyze(
            pir,
            {
                "specialist_reports": [r.to_dict() for r in specialist_reports],
                "store_summary": store_summary,
            },
        )
        self._audit("audit_completed", pir, {
            "notes": len(audit_report.devils_advocate_notes),
            "latency_seconds": round(audit_report.latency_seconds, 2),
        })

        # 5. Analyst synthesis
        dossier = await self.analyst.synthesize(
            pir,
            specialist_reports=specialist_reports,
            audit_reports=[audit_report],
            store_summary=store_summary,
            operator_notes=operator_notes,
        )
        dossier.audit_trail.append(
            f"intel_team.orchestrator: {len(specialist_reports)} specialist(s), "
            f"{len(audit_report.devils_advocate_notes)} audit note(s), "
            f"total_latency={time.monotonic() - t0:.1f}s"
        )

        self._audit("dossier_produced", pir, {
            "key_judgments": len(dossier.key_judgments),
            "gaps": len(dossier.intelligence_gaps),
            "actions": len(dossier.recommended_actions),
            "total_latency_seconds": round(time.monotonic() - t0, 2),
        })

        return dossier

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _dispatch_specialists(
        self,
        pir: PIR,
        decision: RoutingDecision,
        *,
        store_summary: str,
        tool_outputs: dict[str, Any],
        operator_notes: str,
    ) -> list[AgentReport]:
        context = {
            "store_summary": store_summary,
            "tool_outputs": tool_outputs,
            "operator_notes": operator_notes,
        }

        tasks: list[asyncio.Task[AgentReport]] = []
        skipped: list[Domain] = []

        for domain in decision.all_domains:
            cls = SPECIALIST_REGISTRY.get(domain)
            if cls is None:
                skipped.append(domain)
                continue
            specialist = cls(self.router, self.store)
            tasks.append(asyncio.create_task(self._safe_run(specialist, pir, context)))

        results: list[AgentReport] = []
        if tasks:
            results = await asyncio.gather(*tasks)

        # For domains we cannot serve yet, emit a placeholder report so the
        # analyst surfaces the gap rather than silently ignoring it.
        for d in skipped:
            placeholder = AgentReport(
                agent=f"{d.value}_specialist_placeholder",
                domain=d,
                pir_id=pir.id,
                model="n/a",
            )
            placeholder.gaps.append(
                f"{d.value.upper()} specialist not yet implemented in this iteration"
            )
            results.append(placeholder)

        return results

    async def _safe_run(
        self,
        specialist: BaseSpecialist,
        pir: PIR,
        context: dict[str, Any],
    ) -> AgentReport:
        """Run a specialist, capturing any exception into the report."""
        try:
            return await specialist.analyze(pir, context)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Specialist %s crashed", specialist.config.name)
            report = AgentReport(
                agent=specialist.config.name,
                domain=specialist.config.domain,
                pir_id=pir.id,
                model=specialist._effective_model_label(),  # noqa: SLF001
                error=f"unhandled exception: {exc}",
            )
            return report

    def _get_store_summary(self) -> str:
        if self.store is None:
            return ""
        try:
            getter = getattr(self.store, "get_context_summary", None)
            return getter() if callable(getter) else ""
        except Exception:  # noqa: BLE001
            return ""

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------

    def _audit(self, event: str, pir: PIR, payload: dict[str, Any]) -> None:
        """Append a JSONL audit entry. Failures here must not block the pipeline."""
        try:
            self.audit_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            path = self.audit_dir / f"{today}.jsonl"

            entry = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "component": "intel_team.orchestrator",
                "event": event,
                "pir_id": pir.id,
                "target": pir.target,
                **payload,
            }
            # Chain-of-custody artefact hash (deterministic over the entry minus 'hash' itself)
            entry["hash"] = hashlib.sha256(
                json.dumps(entry, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()

            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001 — audit must not break the pipeline
            logger.warning("Failed to write audit entry %s: %s", event, exc)
