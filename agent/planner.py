"""Planner — turns a PIR into a Plan(steps[]).

LLM-driven. Sees the available Tool catalogue (filtered to safe families)
and emits a JSON list of Steps the Executor can dispatch. Falls back to a
sane default plan when the LLM fails — *the dossier flow must never block
on planner failure*.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import uuid4

from agent import db
from agent.tool_gateway import ToolGateway
from agent.types import Plan, RunContext, Step, StepKind

logger = logging.getLogger("agent.planner")


_SYSTEM_PROMPT = """You are the StrikeCore Planner — the first stage of a Hermes-like \
multi-agent OSINT pipeline. You produce a JSON plan that the Executor will run.

You DO NOT execute tools. You DO NOT speculate about findings. You ONLY produce a JSON \
object with this exact shape:

{
  "rationale": "one-paragraph reasoning",
  "constraints": {"passive_only": true|false, "jurisdiction": "..."},
  "steps": [
    {
      "id": "s1",
      "kind": "specialist",
      "tool_name": "specialist:socint",
      "params": {"context_keys": ["store_summary", "operator_notes"]},
      "dependencies": [],
      "rationale": "one-line why",
      "task_type": "specialist:socint",
      "optional": false
    },
    ...
    {"id": "synth", "kind": "synthesis", "tool_name": "synthesis:analyst",
     "dependencies": ["s1","s2",...], "task_type": "specialist:analyst"}
  ]
}

RULES
1. Always include a synthesis step that depends on every prior step.
2. Pick from the available tools listed in the user message. NEVER invent tool names.
3. Prefer specialists over legacy agents when both cover the domain.
4. Respect the ``constraints.passive_only`` flag — never plan REDTEAM specialists when true.
5. Italian-language PIRs are normal — analyse them in Italian context but emit the JSON in English.
6. Output STRICT JSON. No markdown fences, no prose outside the object.
"""


_FENCE = re.compile(r"^```[a-zA-Z]*\s*", re.MULTILINE)


def _safe_parse_json(text: str) -> dict | None:
    s = _FENCE.sub("", text).strip()
    if s.endswith("```"):
        s = s[:-3].strip()
    if not s.startswith("{"):
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j > i:
            s = s[i : j + 1]
    try:
        out = json.loads(s)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


def _build_user_message(target: str, pir: str, constraints: dict, available_tools: list[dict]) -> str:
    return json.dumps(
        {
            "target": target,
            "pir_question": pir,
            "constraints": constraints,
            "available_tools": available_tools,
            "instructions": "Produce a Plan per the system prompt schema.",
        },
        indent=2, ensure_ascii=False,
    )


def _default_plan(pir_id: str, target: str) -> Plan:
    """Conservative fallback when the LLM planner fails."""
    return Plan(
        pir_id=pir_id, target=target,
        rationale="Default fallback plan — LLM planner unavailable",
        steps=[
            Step(id="s1", kind=StepKind.SPECIALIST, tool_name="specialist:socint",
                 task_type="specialist:socint",
                 rationale="Default: cover SOCINT for any target"),
            Step(id="s2", kind=StepKind.SPECIALIST, tool_name="specialist:webint",
                 task_type="specialist:webint",
                 rationale="Default: cover WEBINT for any target"),
            Step(id="audit", kind=StepKind.SPECIALIST, tool_name="specialist:audit",
                 dependencies=["s1", "s2"], task_type="specialist:audit",
                 rationale="Audit before synthesis"),
            Step(id="synth", kind=StepKind.SYNTHESIS, tool_name="synthesis:analyst",
                 dependencies=["s1", "s2", "audit"], task_type="specialist:analyst",
                 rationale="Final dossier synthesis"),
        ],
    )


async def plan(*, router: Any, ctx: RunContext, pir: str, gateway: ToolGateway) -> Plan:
    """Produce a Plan for *pir*; persist as an agent_run(role=planner)."""
    pir_id = ctx.pir_id
    target = ctx.target

    # Catalogue available tools (specialist + synthesis families — Phase B scope)
    available = []
    for t in gateway.list(family="specialist") + gateway.list(family="synthesis"):
        available.append({
            "name": t.name,
            "family": t.family,
            "domain": t.domain,
            "description": t.description,
            "cost_micros": t.cost_estimate_micros,
        })

    # Record planner run start
    planner_run_id = db.start_agent_run(
        dossier_id=ctx.dossier_id, role="planner", agent_name="agent.planner",
        parent_run_id=ctx.agent_run_id,
        input_payload={"pir": pir, "target": target, "constraints": ctx.constraints},
    )
    db.emit_trace(planner_run_id, "planner.start", {"pir_id": pir_id, "n_tools": len(available)})

    plan_obj: Plan
    try:
        user_msg = _build_user_message(target, pir, ctx.constraints, available)
        messages = [{"role": "user", "content": user_msg}]
        response = await router.chat(messages=messages, system=_SYSTEM_PROMPT,
                                     task_type="planner")
        content = getattr(response, "content", str(response))
        parsed = _safe_parse_json(content)
        if parsed is None:
            db.emit_trace(planner_run_id, "planner.parse_failed",
                          {"raw_head": content[:400] if content else ""}, level="warn")
            plan_obj = _default_plan(pir_id, target)
        else:
            plan_obj = _materialise_plan(parsed, pir_id=pir_id, target=target, gateway=gateway)
    except Exception as exc:  # noqa: BLE001
        logger.error("planner LLM call failed: %s", exc, exc_info=True)
        db.emit_trace(planner_run_id, "planner.llm_failed", {"error": str(exc)}, level="error")
        plan_obj = _default_plan(pir_id, target)

    db.finish_agent_run(
        planner_run_id, status="completed",
        output={"plan_id": plan_obj.id, "n_steps": len(plan_obj.steps),
                "rationale": plan_obj.rationale,
                "steps": [{"id": s.id, "tool": s.tool_name} for s in plan_obj.steps]},
    )
    db.emit_trace(planner_run_id, "planner.completed",
                  {"n_steps": len(plan_obj.steps), "plan_id": plan_obj.id})
    return plan_obj


def _materialise_plan(parsed: dict, *, pir_id: str, target: str, gateway: ToolGateway) -> Plan:
    """Convert the LLM's JSON into a typed Plan, dropping unknown tools."""
    p = Plan(
        pir_id=pir_id, target=target,
        rationale=str(parsed.get("rationale", "")).strip(),
        constraints=dict(parsed.get("constraints", {})),
    )
    seen_ids: set[str] = set()
    for raw in parsed.get("steps", []) or []:
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("id") or f"s{uuid4().hex[:6]}")
        if sid in seen_ids:
            sid = f"{sid}_{uuid4().hex[:4]}"
        seen_ids.add(sid)
        tool_name = str(raw.get("tool_name", "")).strip()
        if tool_name and tool_name not in gateway:
            logger.info("planner emitted unknown tool %r — dropping", tool_name)
            continue
        try:
            kind = StepKind(str(raw.get("kind", "specialist")).lower())
        except ValueError:
            kind = StepKind.SPECIALIST
        p.steps.append(Step(
            id=sid, kind=kind, tool_name=tool_name,
            params=dict(raw.get("params", {})),
            dependencies=[str(d) for d in raw.get("dependencies", [])],
            rationale=str(raw.get("rationale", "")),
            expected_output_kind=str(raw.get("expected_output_kind", "findings")),
            optional=bool(raw.get("optional", False)),
            task_type=str(raw.get("task_type", "")),
        ))

    if not p.steps:
        return _default_plan(pir_id, target)
    # Guarantee a synthesis step at the end
    if not any(s.kind == StepKind.SYNTHESIS for s in p.steps):
        deps = [s.id for s in p.steps]
        p.steps.append(Step(
            id="synth_auto", kind=StepKind.SYNTHESIS, tool_name="synthesis:analyst",
            dependencies=deps, task_type="specialist:analyst",
            rationale="Auto-appended synthesis step (planner did not emit one)",
        ))
    return p
