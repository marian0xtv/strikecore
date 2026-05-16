"""Strikecore Hermes-like core agent loop (Phase B).

Pipeline:

    PIR  →  pir_router (existing intel_team.PIRRouter, re-used)
         →  planner (this package)         — Plan(steps[])
         →  executor (this package)        — async dispatch, persists Trace
         →  critic (this package)          — quality + efficiency review
         →  intel_team.AnalystAgent        — final synthesis (re-used)
         →  Dossier (persisted to Postgres + Markdown/JSON)

Persistence: every step writes to ``agent_run``, ``subagent_invocation``,
``trace``, ``token_ledger`` (Phase A schema). Tools are accessed via the
uniform :class:`ToolGateway` registry that walks ``intel_team/agents/`` and
``agents/*_agent.py`` and exposes them with the same interface.

This module is *additive*: ``bin/intel-team.py`` continues to work via the
legacy ``intel_team/orchestrator.py`` path; ``bin/agent-dossier.py`` is the
new Hermes-style entry point.
"""

from agent.dossier_flow import build_dossier
from agent.tool_gateway import Tool, ToolGateway, default_gateway
from agent.types import Plan, RunContext, Step, StepKind

__all__ = [
    "Plan",
    "RunContext",
    "Step",
    "StepKind",
    "Tool",
    "ToolGateway",
    "build_dossier",
    "default_gateway",
]
