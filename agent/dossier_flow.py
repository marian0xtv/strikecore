"""Dossier-first flow — the public entry point for the Hermes-like loop.

    build_dossier(target, pir, ...)  →  Dossier (and persisted Postgres rows)

Pipeline:

    1.  Entity upsert + Dossier row created
    2.  Planner (LLM)               → Plan(steps[])
    3.  Executor                    → step outputs (parallel where deps allow)
    4.  Synthesis (intel_team Analyst, re-used) → final dossier dict
    5.  Critic                      → improvement records
    6.  Persist findings + dossier completion + cost

Returns a small Dossier-like dict suitable for serialisation by the CLI.
The full intel_team Dossier object (with to_markdown) is also returned in
``raw_dossier`` for the legacy renderers.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent import critic as critic_mod
from agent import db, executor as executor_mod, planner as planner_mod, trajectory
from agent.tool_gateway import default_gateway
from agent.types import RunContext, StepKind

logger = logging.getLogger("agent.dossier_flow")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def build_dossier(
    *,
    router: Any,
    target: str,
    pir: str,
    operator_notes: str = "",
    constraints: dict | None = None,
    investigation_store: Any = None,
    operator_user: str = "atlas",
) -> dict[str, Any]:
    """Run the full Hermes-style pipeline and return the dossier dict + ids."""
    constraints = constraints or {}
    pir_id = f"pir-{uuid4().hex[:12]}"
    session_id = pir_id
    trajectory_path = session_id

    # Live Control Room telemetry (best-effort; never breaks the pipeline).
    try:
        from core import agent_events
        agent_events.install_router(router)
        _rid = agent_events.start_run("dossier_flow", "cli",
                                      {"target": target, "pir": pir[:160]})
    except Exception:  # noqa: BLE001
        agent_events = None  # type: ignore[assignment]
        _rid = None

    def _ev(event_type: str, **f):
        if agent_events is not None:
            agent_events.emit(event_type, run_id=_rid, **f)

    # 1. Entity + Dossier
    target_entity_id = db.upsert_entity("person", target, display_name=target)
    dossier_id = db.create_dossier(target_entity_id or 0, pir,
                                   operator_user=operator_user, constraints=constraints)
    top_run_id = db.start_agent_run(
        dossier_id=dossier_id, role="planner", agent_name="agent.dossier_flow",
        input_payload={"target": target, "pir": pir, "constraints": constraints},
    )

    trajectory.open_session(session_id, pir_id=pir_id, target=target, operator_notes=operator_notes)

    ctx = RunContext(
        pir_id=pir_id, target=target, dossier_id=dossier_id,
        target_entity_id=target_entity_id, agent_run_id=top_run_id,
        constraints=constraints, operator_notes=operator_notes,
        trajectory_path=trajectory_path,
    )
    db.emit_trace(top_run_id, "flow.start", {
        "target": target, "dossier_id": dossier_id, "pir_id": pir_id,
        "constraints": constraints,
    })

    started = time.monotonic()
    db.update_dossier(dossier_id, status="planning")

    # We need a PIR object the intel_team specialists can consume — reuse their dataclass
    pir_obj = _make_pir_obj(pir_id=pir_id, target=target, pir=pir, constraints=constraints)

    gateway = default_gateway()

    # 2. Planner
    _ev("phase", phase="planning", detail="building plan")
    plan = await planner_mod.plan(router=router, ctx=ctx, pir=pir, gateway=gateway)
    _ev("info", detail=f"plan: {len(plan.steps)} step(s)")
    trajectory.append(session_id, "assistant",
                      {"event": "plan_emitted", "rationale": plan.rationale,
                       "n_steps": len(plan.steps),
                       "steps": [{"id": s.id, "tool": s.tool_name} for s in plan.steps]})

    # 3. Executor
    _ev("phase", phase="collection", detail=f"{len(plan.steps)} step(s)")
    db.update_dossier(dossier_id, status="collecting")
    step_results = await executor_mod.execute(
        router=router, ctx=ctx, plan=plan, gateway=gateway,
        pir_obj=pir_obj, investigation_store=investigation_store,
    )

    # 4. Synthesis — extract whichever step ran the analyst (synthesis:* family)
    _ev("phase", phase="synthesis", detail="extracting dossier")
    db.update_dossier(dossier_id, status="synthesizing")
    raw_dossier: dict[str, Any] | None = None
    for sid, res in step_results.items():
        if not res.success or not isinstance(res.output, dict):
            continue
        if "dossier" in res.output:
            raw_dossier = res.output["dossier"]
            break

    # 5. Persist findings from raw_dossier
    findings_persisted = 0
    if raw_dossier:
        for domain, items in (raw_dossier.get("findings_by_domain") or {}).items():
            for it in items or []:
                if not isinstance(it, dict):
                    continue
                fid = db.insert_finding(
                    dossier_id=dossier_id, domain=domain,
                    ftype=str(it.get("type", "other")),
                    value=str(it.get("value", "")),
                    confidence=float(it.get("confidence", 0.5) or 0.5),
                    notes=str(it.get("notes", "")) or None,
                )
                if fid is not None:
                    findings_persisted += 1

    # Aggregate spend from token_ledger
    dossier_cost = _dossier_cost(dossier_id)

    # 6. Critic
    _ev("phase", phase="critic", detail="reviewing dossier")
    critic_out = await critic_mod.critique(
        router=router, ctx=ctx, plan_obj=plan, step_results=step_results,
        dossier=raw_dossier, dossier_cost_micros=dossier_cost,
    )

    # Finalise dossier row
    bluf = ""
    if raw_dossier:
        bluf = str(raw_dossier.get("bluf", ""))[:8000]
    db.update_dossier(
        dossier_id,
        status="completed" if raw_dossier else "failed",
        bluf=bluf, summary_json=raw_dossier or {},
        completed_at=_now(), cost_micros=dossier_cost,
    )
    db.finish_agent_run(top_run_id, status="completed",
                        output={"findings_persisted": findings_persisted,
                                "dossier_cost_micros": dossier_cost,
                                "improvements": {k: len(v) for k, v in critic_out.items()}},
                        cost_micros=dossier_cost)
    db.emit_trace(top_run_id, "flow.completed",
                  {"dossier_id": dossier_id, "findings_persisted": findings_persisted,
                   "cost_micros": dossier_cost,
                   "duration_s": round(time.monotonic() - started, 2)})

    trajectory.close_session(session_id, dossier_id=dossier_id, cost_micros=dossier_cost)

    _ev("decision", detail=f"dossier {dossier_id}: {findings_persisted} finding(s)")
    if agent_events is not None:
        agent_events.end_run("completed" if raw_dossier else "failed", run_id=_rid)

    return {
        "dossier_id": dossier_id,
        "pir_id": pir_id,
        "target": target,
        "plan_id": plan.id,
        "n_steps_planned": len(plan.steps),
        "n_steps_succeeded": sum(1 for r in step_results.values() if r.success),
        "findings_persisted": findings_persisted,
        "cost_micros": dossier_cost,
        "cost_usd": round(dossier_cost / 1_000_000.0, 4),
        "improvements": {k: len(v) for k, v in critic_out.items()},
        "raw_dossier": raw_dossier,
        "trajectory_path": str(trajectory.Path.home() / ".strikecore/trajectories" / f"{session_id}.jsonl")
        if False else f"~/.strikecore/trajectories/{session_id}.jsonl",
    }


def _dossier_cost(dossier_id: int) -> int:
    try:
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(SUM(cost_usd_micros), 0)::bigint
                FROM token_ledger
                WHERE dossier_id = %s OR agent_run_id IN (
                    SELECT id FROM agent_run WHERE dossier_id = %s
                )
                """,
                (dossier_id, dossier_id),
            )
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


def _make_pir_obj(*, pir_id: str, target: str, pir: str, constraints: dict) -> Any:
    """Reuse intel_team.PIR for downstream specialist compatibility."""
    try:
        from intel_team.types import PIR
        return PIR(id=pir_id, question=pir, target=target, constraints=constraints or {})
    except Exception:
        # Tolerant stub if intel_team isn't importable for some reason
        class _Stub:
            pass
        s = _Stub()
        s.id = pir_id
        s.question = pir
        s.target = target
        s.constraints = constraints
        s.domains_hint = []
        return s
