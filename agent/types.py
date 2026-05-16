"""Shared dataclasses for the Hermes-like agent core."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StepKind(str, enum.Enum):
    """What the executor should do with a Step."""

    SPECIALIST = "specialist"   # call an intel_team specialist (e.g. socint, geoint)
    LEGACY_AGENT = "legacy"     # call agents/*_agent.py
    BINARY_TOOL = "binary"      # invoke a CLI from core/tool_registry.py via executor
    SYNTHESIS = "synthesis"     # intel_team.AnalystAgent — final dossier render
    MEMORY = "memory"           # write to memory_embedding / read context


@dataclass
class Step:
    """One unit of work in a Plan.

    The Planner emits a Plan composed of Steps. The Executor runs them
    honouring ``dependencies`` (other Step ids that must complete first).
    """

    id: str
    kind: StepKind
    tool_name: str                                 # registry key (e.g. 'specialist:socint')
    params: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    rationale: str = ""                            # planner's one-line justification
    expected_output_kind: str = "findings"         # findings / facts / urls / iocs / …
    retry_policy: dict[str, Any] = field(default_factory=lambda: {"max_attempts": 1, "backoff_s": 1.0})
    optional: bool = False                         # if True, executor failures don't abort the plan
    task_type: str = ""                            # for governance.model_router (e.g. 'specialist:socint')


@dataclass
class Plan:
    """The planner's output."""

    id: str = field(default_factory=lambda: f"plan-{uuid4().hex[:12]}")
    pir_id: str = ""
    target: str = ""
    rationale: str = ""
    steps: list[Step] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now_iso)


@dataclass
class StepResult:
    """The output of a single Step execution."""

    step_id: str
    success: bool
    output: Any = None
    error: str | None = None
    started_at: str = field(default_factory=_utc_now_iso)
    ended_at: str = ""
    duration_ms: int = 0
    subagent_invocation_id: int | None = None


@dataclass
class RunContext:
    """Mutable per-run state passed through the loop.

    Carries the Postgres ids needed to wire ``token_ledger`` /
    ``subagent_invocation`` / ``trace`` writes correctly, plus the shared
    in-memory results map.
    """

    pir_id: str
    target: str
    dossier_id: int | None = None
    target_entity_id: int | None = None
    agent_run_id: int | None = None                # the *currently active* run id
    started_at: str = field(default_factory=_utc_now_iso)
    constraints: dict[str, Any] = field(default_factory=dict)
    results: dict[str, StepResult] = field(default_factory=dict)
    operator_notes: str = ""
    trajectory_path: str = ""                      # filesystem path for JSONL trajectory
