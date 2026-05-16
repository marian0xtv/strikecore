"""Executor — runs a Plan, honouring step dependencies, persisting Trace.

Uses ``asyncio.gather`` for steps whose dependencies are satisfied.
Dispatches via :class:`ToolGateway` and writes a ``subagent_invocation`` row
per call. The Critic later reads the dossier + trace + improvements.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

from agent import db, trajectory
from agent.tool_gateway import Tool, ToolGateway
from agent.types import Plan, RunContext, Step, StepKind, StepResult

logger = logging.getLogger("agent.executor")


def _input_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


async def execute(
    *,
    router: Any,
    ctx: RunContext,
    plan: Plan,
    gateway: ToolGateway,
    pir_obj: Any,
    investigation_store: Any = None,
) -> dict[str, StepResult]:
    """Execute *plan* and return the StepResult map.

    Results are also placed in ``ctx.results`` so the Synthesis step can pull
    aggregate input via dependency lookup.
    """
    exec_run_id = db.start_agent_run(
        dossier_id=ctx.dossier_id, role="executor", agent_name="agent.executor",
        parent_run_id=ctx.agent_run_id,
        input_payload={"plan_id": plan.id, "n_steps": len(plan.steps)},
    )
    db.emit_trace(exec_run_id, "executor.start", {"plan_id": plan.id, "n_steps": len(plan.steps)})

    pending = {s.id: s for s in plan.steps}
    cost_total_micros = 0

    while pending:
        ready = [
            s for s in pending.values()
            if all(dep in ctx.results for dep in s.dependencies)
        ]
        if not ready:
            # Deadlock: dependency on missing step. Mark remaining as skipped.
            for sid, s in list(pending.items()):
                ctx.results[sid] = StepResult(step_id=sid, success=False,
                                              error=f"unmet deps: {s.dependencies}")
                pending.pop(sid)
            break

        # Dispatch the ready batch in parallel
        coros = [
            _dispatch_step(
                router=router, ctx=ctx, step=s, gateway=gateway,
                pir_obj=pir_obj, investigation_store=investigation_store,
                executor_run_id=exec_run_id,
            )
            for s in ready
        ]
        results = await asyncio.gather(*coros, return_exceptions=False)

        for s, res in zip(ready, results):
            ctx.results[s.id] = res
            pending.pop(s.id)

    db.finish_agent_run(
        exec_run_id, status="completed",
        output={
            "step_count": len(plan.steps),
            "successes": sum(1 for r in ctx.results.values() if r.success),
            "failures": sum(1 for r in ctx.results.values() if not r.success),
        },
        cost_micros=cost_total_micros,
    )
    db.emit_trace(exec_run_id, "executor.completed",
                  {"successes": sum(1 for r in ctx.results.values() if r.success)})
    return ctx.results


async def _dispatch_step(
    *,
    router: Any,
    ctx: RunContext,
    step: Step,
    gateway: ToolGateway,
    pir_obj: Any,
    investigation_store: Any,
    executor_run_id: int,
) -> StepResult:
    tool = gateway.get(step.tool_name)
    started = time.monotonic()
    started_iso = ""

    if tool is None:
        msg = f"unknown tool: {step.tool_name}"
        db.emit_trace(executor_run_id, "step.unknown_tool",
                      {"step_id": step.id, "tool_name": step.tool_name}, level="error")
        trajectory.append(ctx.trajectory_path or ctx.pir_id, "tool",
                          {"step": step.id, "error": msg})
        return StepResult(step_id=step.id, success=False, error=msg)

    payload = _build_payload(step, ctx, pir_obj, investigation_store)
    inp_hash = _input_hash(payload)

    db.emit_trace(executor_run_id, "step.start",
                  {"step_id": step.id, "tool_name": tool.name, "family": tool.family,
                   "input_hash": inp_hash})
    trajectory.append(ctx.trajectory_path or ctx.pir_id, "tool",
                      {"step": step.id, "tool": tool.name, "kind": step.kind.value})

    # Retry policy
    max_attempts = max(1, int(step.retry_policy.get("max_attempts", 1)))
    backoff = float(step.retry_policy.get("backoff_s", 1.0))

    last_error: str | None = None
    output: Any = None

    for attempt in range(1, max_attempts + 1):
        try:
            if tool.family in ("specialist", "synthesis"):
                output = await tool.invoke(
                    router=router, pir=pir_obj,
                    context=payload.get("context", {}),
                    store=investigation_store,
                )
            elif tool.family == "legacy":
                output = await tool.invoke(target=ctx.target, agent_core=None)
            else:
                output = await tool.invoke(**payload)
            break
        except Exception as exc:  # noqa: BLE001 — caught for retry
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("step %s (%s) attempt %d/%d failed: %s",
                           step.id, tool.name, attempt, max_attempts, last_error)
            if attempt < max_attempts:
                await asyncio.sleep(backoff)
                backoff *= 2

    duration_ms = int((time.monotonic() - started) * 1000)
    success = output is not None and last_error is None

    inv_id = db.record_subagent_invocation(
        agent_run_id=executor_run_id, tool_name=tool.name,
        input_payload=payload, output_payload=output if isinstance(output, dict) else {"raw": output},
        success=success, error_text=last_error, duration_ms=duration_ms,
        input_hash=inp_hash,
    )

    db.emit_trace(executor_run_id,
                  "step.completed" if success else "step.failed",
                  {"step_id": step.id, "tool_name": tool.name, "duration_ms": duration_ms,
                   "error": last_error},
                  level="info" if success else "warn",
                  subagent_inv_id=inv_id)

    if step.optional and not success:
        # Optional failure is recorded but doesn't block the plan
        db.emit_trace(executor_run_id, "step.optional_skipped",
                      {"step_id": step.id}, level="info", subagent_inv_id=inv_id)
        return StepResult(step_id=step.id, success=True,
                          output={"skipped": True, "error": last_error},
                          ended_at="", duration_ms=duration_ms,
                          subagent_invocation_id=inv_id)

    return StepResult(
        step_id=step.id, success=success,
        output=output if success else None,
        error=last_error,
        ended_at="", duration_ms=duration_ms,
        subagent_invocation_id=inv_id,
    )


def _build_payload(step: Step, ctx: RunContext, pir_obj: Any, store: Any) -> dict[str, Any]:
    """Compose the input dict the tool's ``invoke`` will receive.

    For specialist/synthesis families: we assemble the context the existing
    intel_team agents expect (store_summary, recent_tool_outputs, prior reports).
    """
    base_context: dict[str, Any] = {
        "store_summary": _store_summary(store),
        "operator_notes": ctx.operator_notes,
        "tool_outputs": {},
    }

    # Pull outputs from declared dependencies into the context
    specialist_reports = []
    audit_reports = []
    for dep_id in step.dependencies:
        dep = ctx.results.get(dep_id)
        if not (dep and dep.success and isinstance(dep.output, dict)):
            continue
        if "devils_advocate_notes" in dep.output and dep.output.get("domain") == "audit":
            audit_reports.append(dep.output)
        elif "findings" in dep.output or "agent" in dep.output:
            specialist_reports.append(dep.output)
        base_context["tool_outputs"][dep_id] = dep.output

    base_context["specialist_reports"] = specialist_reports
    base_context["audit_reports"] = audit_reports

    return {"context": base_context, "step_params": dict(step.params)}


def _store_summary(store: Any) -> str:
    if store is None:
        return ""
    try:
        getter = getattr(store, "get_context_summary", None)
        return getter() if callable(getter) else ""
    except Exception:
        return ""
