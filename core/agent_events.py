"""Unified live agent event bus (file-based, cross-process).

Every StrikeCore agent run — Hephaestus, intel_team, the Hermes dossier_flow, and
the console NLP engine — emits lifecycle / phase / cost events here so the Control
Room (the `controlroom` CLI htop view + the dashboards) can show live activity and
per-agent metrics in real time.

File-based JSONL to match the existing audit idiom and keep agents free of any DB
dependency (Postgres stays optional). Two artifacts:

    ~/.strikecore/events/<YYYY-MM-DD>.jsonl   append-only event log (one JSON/line)
    ~/.strikecore/events/active/<run_id>.json per-run heartbeat (rolling state)

Design rules (like core/dossier_output.py): best-effort and **failure-isolated** —
telemetry must never raise into, or break, an agent run.

This module is the SINGLE reader implementation imported by the CLI and BOTH
dashboards (`control_room_state`, `run_detail`). ASCII house style (CLAUDE.md s.12).
"""

from __future__ import annotations

import contextvars
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

EVENTS_DIR = Path.home() / ".strikecore" / "events"
ACTIVE_DIR = EVENTS_DIR / "active"

EVENT_TYPES = (
    "run_start", "phase", "info", "stream_start", "stream_delta", "stream_end",
    "llm_call", "gate_request", "gate_result", "decision", "finding", "run_end",
)

# How long without a heartbeat update before a "running" run is considered stale.
STALE_SECONDS = 30

# Current run id for the executing context — lets the router on_call handler and
# nested code auto-tag events without threading run_id through every call.
current_run: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "agent_events_current_run", default=None)


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _now_epoch() -> float:
    return time.time()


def _today_log() -> Path:
    return EVENTS_DIR / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


# --------------------------------------------------------------------------
# Writer
# --------------------------------------------------------------------------
def _heartbeat_path(run_id: str) -> Path:
    return ACTIVE_DIR / f"{run_id}.json"


def _load_heartbeat(run_id: str) -> dict[str, Any]:
    try:
        return json.loads(_heartbeat_path(run_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_heartbeat(hb: dict[str, Any]) -> None:
    try:
        ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
        _heartbeat_path(hb["run_id"]).write_text(
            json.dumps(hb, ensure_ascii=False, default=str), encoding="utf-8")
    except (OSError, KeyError):
        pass


def _append_event(event: dict[str, Any]) -> None:
    try:
        EVENTS_DIR.mkdir(parents=True, exist_ok=True)
        with _today_log().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def start_run(agent: str, surface: str = "cli",
              params: dict[str, Any] | None = None,
              run_id: str | None = None) -> str:
    """Begin a run: write a run_start event + a heartbeat, set the context var.

    Returns the run_id (generated if not supplied). Never raises.
    """
    rid = run_id or new_run_id()
    try:
        hb = {
            "run_id": rid, "agent": agent, "surface": surface,
            "params": params or {}, "status": "running", "phase": "",
            "started_at": _now_iso(), "started_epoch": _now_epoch(),
            "last_seen": _now_epoch(), "pid": os.getpid(),
            "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_micros": 0,
            "pending_gates": [], "last_detail": "",
        }
        _save_heartbeat(hb)
        emit("run_start", run_id=rid, agent=agent, surface=surface,
             detail=json.dumps(params or {}, default=str)[:300])
    except Exception:  # noqa: BLE001 — telemetry never breaks a run
        pass
    try:
        current_run.set(rid)
    except Exception:  # noqa: BLE001
        pass
    return rid


def set_phase(phase: str, run_id: str | None = None) -> None:
    emit("phase", run_id=run_id, phase=phase, detail=phase)


def emit(event_type: str, run_id: str | None = None, **fields: Any) -> None:
    """Append one event and fold it into the run's heartbeat. Never raises."""
    try:
        rid = run_id or current_run.get()
        if not rid:
            return
        event = {
            "ts": _now_iso(), "ts_epoch": _now_epoch(), "run_id": rid,
            "event_type": event_type,
        }
        for k, v in fields.items():
            if v is not None:
                event[k] = v
        _append_event(event)
        _update_heartbeat(rid, event_type, fields)
    except Exception:  # noqa: BLE001
        pass


def _update_heartbeat(rid: str, event_type: str, fields: dict[str, Any]) -> None:
    hb = _load_heartbeat(rid)
    if not hb:
        hb = {"run_id": rid, "agent": fields.get("agent", "?"),
              "surface": fields.get("surface", "cli"), "status": "running",
              "started_at": _now_iso(), "started_epoch": _now_epoch(),
              "calls": 0, "input_tokens": 0, "output_tokens": 0,
              "cost_micros": 0, "pending_gates": [], "phase": "",
              "last_detail": ""}
    hb["last_seen"] = _now_epoch()
    if event_type == "phase" and fields.get("phase"):
        hb["phase"] = fields["phase"]
    if fields.get("detail"):
        hb["last_detail"] = str(fields["detail"])[:200]
    if event_type == "llm_call":
        hb["calls"] = int(hb.get("calls", 0)) + 1
        hb["input_tokens"] = int(hb.get("input_tokens", 0)) + int(fields.get("input_tokens", 0) or 0)
        hb["output_tokens"] = int(hb.get("output_tokens", 0)) + int(fields.get("output_tokens", 0) or 0)
        hb["cost_micros"] = int(hb.get("cost_micros", 0)) + int(fields.get("cost_micros", 0) or 0)
        if fields.get("model"):
            hb["last_model"] = fields["model"]
    if event_type == "gate_request":
        gates = list(hb.get("pending_gates", []))
        gates.append(fields.get("gate", "?"))
        hb["pending_gates"] = gates
    if event_type == "gate_result" and fields.get("approved"):
        hb["pending_gates"] = [g for g in hb.get("pending_gates", [])
                               if g != fields.get("gate")]
    _save_heartbeat(hb)


def end_run(status: str = "completed", run_id: str | None = None,
            detail: str = "") -> None:
    """Finish a run: mark the heartbeat + write a run_end event. Never raises."""
    try:
        rid = run_id or current_run.get()
        if not rid:
            return
        hb = _load_heartbeat(rid)
        if hb:
            hb["status"] = status
            hb["last_seen"] = _now_epoch()
            hb["ended_at"] = _now_iso()
            _save_heartbeat(hb)
        emit("run_end", run_id=rid, status=status, detail=detail)
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            if current_run.get() == (run_id or current_run.get()):
                current_run.set(None)
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------
# Router cost hook (auto-captures cost for every agent)
# --------------------------------------------------------------------------
def record_call(call: Any) -> None:
    """Default ProviderRouter.on_call handler: emit an llm_call for current_run."""
    try:
        if current_run.get() is None:
            return
        emit("llm_call",
             task_type=getattr(call, "task_type", ""),
             model=getattr(call, "model", ""),
             input_tokens=getattr(call, "input_tokens", 0),
             output_tokens=getattr(call, "output_tokens", 0),
             cost_micros=getattr(call, "cost_micros", 0),
             dry_run=getattr(call, "dry_run", False),
             detail=f"{getattr(call, 'task_type', '')} -> {getattr(call, 'model', '')}")
    except Exception:  # noqa: BLE001
        pass


def install_router(router: Any) -> None:
    """Wire the bus's cost handler into a ProviderRouter (best-effort)."""
    try:
        router.on_call = record_call
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------
# Reader (used by the CLI + both dashboards)
# --------------------------------------------------------------------------
def _iter_heartbeats() -> list[dict[str, Any]]:
    if not ACTIVE_DIR.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in ACTIVE_DIR.glob("*.json"):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def _annotate(hb: dict[str, Any]) -> dict[str, Any]:
    now = _now_epoch()
    last = float(hb.get("last_seen", 0) or 0)
    started = float(hb.get("started_epoch", last) or last)
    status = hb.get("status", "running")
    is_stale = status == "running" and (now - last) > STALE_SECONDS
    return {
        **hb,
        "elapsed_seconds": round(max(0.0, now - started), 1),
        "is_active": status == "running" and not is_stale,
        "is_stale": is_stale,
        "effective_status": "stale" if is_stale else status,
        "cost_usd": round(int(hb.get("cost_micros", 0)) / 1_000_000, 6),
        "pending_gate_count": len(hb.get("pending_gates", []) or []),
    }


def active_runs(stale_seconds: int = STALE_SECONDS) -> list[dict[str, Any]]:
    runs = [_annotate(hb) for hb in _iter_heartbeats()]
    runs = [r for r in runs if r["is_active"]]
    return sorted(runs, key=lambda r: r.get("started_epoch", 0), reverse=True)


def recent_runs(limit: int = 50) -> list[dict[str, Any]]:
    runs = [_annotate(hb) for hb in _iter_heartbeats()]
    runs.sort(key=lambda r: r.get("last_seen", 0), reverse=True)
    return runs[:limit]


def _iter_log_lines() -> Iterable[dict[str, Any]]:
    # Today + yesterday cover any run spanning midnight.
    for day_off in (0, 1):
        d = datetime.now(timezone.utc)
        path = EVENTS_DIR / f"{d:%Y-%m-%d}.jsonl" if day_off == 0 else None
        if day_off == 1:
            from datetime import timedelta
            path = EVENTS_DIR / f"{(d - timedelta(days=1)):%Y-%m-%d}.jsonl"
        if not path or not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
        except OSError:
            continue


def run_timeline(run_id: str, limit: int = 500) -> list[dict[str, Any]]:
    """Chronological events for one run (newest log scanned)."""
    evts = [e for e in _iter_log_lines() if e.get("run_id") == run_id]
    evts.sort(key=lambda e: e.get("ts_epoch", 0))
    return evts[-limit:]


def tail(since_epoch: float = 0.0, limit: int = 500) -> list[dict[str, Any]]:
    evts = [e for e in _iter_log_lines() if float(e.get("ts_epoch", 0)) > since_epoch]
    evts.sort(key=lambda e: e.get("ts_epoch", 0))
    return evts[-limit:]


def aggregates() -> dict[str, Any]:
    """Top-line metrics for the control-room header."""
    runs = [_annotate(hb) for hb in _iter_heartbeats()]
    active = [r for r in runs if r["is_active"]]
    calls = tokens_in = tokens_out = cost = 0
    models: dict[str, int] = {}
    gates = 0
    for r in runs:
        calls += int(r.get("calls", 0))
        tokens_in += int(r.get("input_tokens", 0))
        tokens_out += int(r.get("output_tokens", 0))
        cost += int(r.get("cost_micros", 0))
        gates += r["pending_gate_count"]
        m = r.get("last_model")
        if m:
            models[m] = models.get(m, 0) + 1
    # calls/min over the last 60s of the event log
    cutoff = _now_epoch() - 60
    recent_calls = sum(1 for e in _iter_log_lines()
                       if e.get("event_type") == "llm_call"
                       and float(e.get("ts_epoch", 0)) > cutoff)
    return {
        "active_agents": len(active),
        "total_runs": len(runs),
        "llm_calls": calls,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "cost_micros": cost,
        "cost_usd": round(cost / 1_000_000, 6),
        "calls_per_min": recent_calls,
        "models_in_use": models,
        "pending_gates": gates,
    }


def control_room_state(recent_limit: int = 50) -> dict[str, Any]:
    """The full control-room payload: aggregates + run rows. One impl for all surfaces."""
    return {
        "generated_at": _now_iso(),
        "aggregates": aggregates(),
        "runs": recent_runs(recent_limit),
    }


def run_detail(run_id: str) -> dict[str, Any]:
    """Drill-down payload for one run: heartbeat + full timeline."""
    hb = _load_heartbeat(run_id)
    return {
        "run": _annotate(hb) if hb else {"run_id": run_id, "missing": True},
        "timeline": run_timeline(run_id),
    }


def prune(max_age_seconds: int = 86_400) -> int:
    """Remove ended heartbeats older than max_age. Returns count removed."""
    removed = 0
    now = _now_epoch()
    for hb in _iter_heartbeats():
        if hb.get("status") == "running":
            continue
        if (now - float(hb.get("last_seen", 0) or 0)) > max_age_seconds:
            try:
                _heartbeat_path(hb["run_id"]).unlink()
                removed += 1
            except (OSError, KeyError):
                continue
    return removed
