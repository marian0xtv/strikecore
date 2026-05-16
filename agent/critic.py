"""Critic — post-run evaluation, writes Improvement records.

Runs after the Executor + Synthesis steps. Reads the run's trace + the
synthesized dossier + the token_ledger spend for the dossier, and writes
``improvement`` rows along two dimensions:

  * ``quality``     — was the dossier defensible? gaps surfaced honestly?
  * ``efficiency``  — was the spend justified? was a cheaper tier missed?

The improver (Phase D) consolidates these into policy patches once
``evidence_count >= 5`` per (target_component, description).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agent import db
from agent.types import RunContext

logger = logging.getLogger("agent.critic")


_SYSTEM_PROMPT = """You are the StrikeCore Critic — post-run reviewer for a Hermes-like \
multi-agent OSINT loop. You receive the *plan*, *step outputs*, *synthesized dossier*, \
and *token spend* for one investigation. You produce structured improvement records the \
Improver consolidates into policy patches.

Output ONE JSON object with this shape:

{
  "quality": [
    {
      "target_component": "planner.system_prompt" | "specialist:socint" | "synthesis:analyst" | ...,
      "description": "short, repeatable defect or strength",
      "patch": {"action": "trim|expand|rewrite|reroute", "details": "..."}
    }
  ],
  "efficiency": [
    {
      "target_component": "router.task[specialist:socint]",
      "description": "token spend N for simple null-input task — Haiku would have sufficed",
      "patch": {"action": "downgrade_tier", "from": "claude-sonnet-4-6", "to": "claude-haiku-4-5-20251001"}
    }
  ],
  "reliability": [
    {"target_component": "executor.retry", "description": "...", "patch": {...}}
  ]
}

RULES
1. STRICT JSON only — no prose, no code fences.
2. Be SPECIFIC. "Spend too high" is useless; "specialist:socint used Sonnet for a 200-token \
   no-evidence task, Haiku tier in model_routing.alt_chain would have produced equivalent output" is useful.
3. Each ``target_component`` MUST match a real component name the Improver can patch \
   (planner.system_prompt, router.task[<task_type>], specialist:<domain>, executor.retry, \
   prompt_cache.<scope>).
4. Empty arrays are fine — only emit improvements when you have evidence.
5. Never emit ``safety`` items in this version; reserved for Phase D.
"""


async def critique(
    *,
    router: Any,
    ctx: RunContext,
    plan_obj: Any,
    step_results: dict[str, Any],
    dossier: dict[str, Any] | None,
    dossier_cost_micros: int,
) -> dict[str, list[dict]]:
    """Run the Critic, persist any improvement records, return them for the dossier."""
    critic_run_id = db.start_agent_run(
        dossier_id=ctx.dossier_id, role="critic", agent_name="agent.critic",
        parent_run_id=ctx.agent_run_id,
        input_payload={"plan_id": getattr(plan_obj, "id", ""), "dossier_cost_micros": dossier_cost_micros},
    )
    db.emit_trace(critic_run_id, "critic.start",
                  {"n_steps": len(step_results), "cost_micros": dossier_cost_micros})

    summary = {
        "target": ctx.target,
        "pir_id": ctx.pir_id,
        "dossier_cost_micros": dossier_cost_micros,
        "plan": {
            "rationale": getattr(plan_obj, "rationale", ""),
            "steps": [
                {"id": s.id, "tool": s.tool_name, "task_type": s.task_type,
                 "kind": s.kind.value, "dependencies": s.dependencies}
                for s in getattr(plan_obj, "steps", []) or []
            ],
        },
        "step_outcomes": [
            {"step_id": sid, "success": r.success, "duration_ms": r.duration_ms,
             "error": r.error,
             "output_kind": "dict" if isinstance(r.output, dict) else type(r.output).__name__}
            for sid, r in step_results.items()
        ],
        "dossier_excerpt": _excerpt_dossier(dossier),
    }

    out: dict[str, list[dict]] = {"quality": [], "efficiency": [], "reliability": []}
    try:
        response = await router.chat(
            messages=[{"role": "user", "content": json.dumps(summary, indent=2, default=str)}],
            system=_SYSTEM_PROMPT,
        )
        content = getattr(response, "content", str(response))
        parsed = _safe_parse(content)
        if parsed is not None:
            for cat in ("quality", "efficiency", "reliability"):
                for item in parsed.get(cat, []) or []:
                    if not isinstance(item, dict):
                        continue
                    out[cat].append(item)
    except Exception as exc:  # noqa: BLE001
        logger.warning("critic LLM call failed: %s", exc)
        db.emit_trace(critic_run_id, "critic.llm_failed", {"error": str(exc)}, level="warn")

    # Persist improvement records (bumps evidence_count on existing ones)
    persisted = 0
    for cat, items in out.items():
        for item in items:
            target_component = str(item.get("target_component", "")).strip()
            desc = str(item.get("description", "")).strip()
            if not target_component or not desc:
                continue
            db.write_improvement(
                agent_run_id=critic_run_id, category=cat,
                target_component=target_component, description=desc,
                patch=dict(item.get("patch", {})),
            )
            persisted += 1

    db.finish_agent_run(critic_run_id, status="completed",
                        output={"persisted": persisted, **{k: len(v) for k, v in out.items()}})
    db.emit_trace(critic_run_id, "critic.completed",
                  {"persisted": persisted, **{k: len(v) for k, v in out.items()}})
    return out


def _excerpt_dossier(dossier: dict | None) -> dict:
    if not isinstance(dossier, dict):
        return {"present": False}
    return {
        "present": True,
        "bluf": dossier.get("bluf", "")[:600],
        "key_judgments_count": len(dossier.get("key_judgments", [])),
        "intelligence_gaps_count": len(dossier.get("intelligence_gaps", [])),
        "recommended_actions_count": len(dossier.get("recommended_actions", [])),
    }


def _safe_parse(text: str) -> dict | None:
    import re
    s = re.sub(r"^```[a-zA-Z]*\s*", "", text, flags=re.M).strip()
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
