"""Shared core for the Hephaestus surfaces (CLI + console command).

Pure logic + formatting — no argparse, no sys.exit, no print. Both
bin/hephaestus.py and cli/shell.py:_cmd_hephaestus call into here so the
run/status/report/approve behaviour lives in exactly one place. All LLM calls
flow through the GR3 cost-aware router under the 'hephaestus' profile.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hephaestus import run_record
from hephaestus.agent import Hephaestus

_AUDIT_DIR = Path.home() / ".strikecore" / "audit"


class _MiniSettings:
    """Fallback settings when the full config singleton is unavailable."""

    def __init__(self, dry_run: bool = False) -> None:
        self._d = {
            "ai.active_provider": "anthropic",
            "ai.fallback_chain": ["anthropic"],
            "ai.anthropic": {},
            "ai.model_policy.dry_run": dry_run,
            "ai.model_policy.profile": "hephaestus",
        }

    def get(self, key, default=None):
        return self._d.get(key, default)


def build_router(dry_run: bool):
    from core.provider_router import ProviderRouter
    try:
        from config.settings import get_settings
        return ProviderRouter(get_settings())
    except Exception:
        return ProviderRouter(_MiniSettings(dry_run))


def fmt_usd(micros: int) -> str:
    return f"${micros / 1_000_000:.4f}"


def audit(event: str, run_id: str, payload: dict) -> None:
    try:
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "component": "hephaestus", "event": event, "run_id": run_id, **payload}
        entry["hash"] = hashlib.sha256(
            json.dumps(entry, sort_keys=True, default=str).encode()).hexdigest()
        path = _AUDIT_DIR / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except OSError:
        pass


def summary_lines(rec: dict) -> list[str]:
    """Render a run record to plain text lines (surface-agnostic)."""
    out = [
        f"run {rec['run_id']}  status={rec['status']}  "
        f"focus={rec['params']['focus_category']}  "
        f"profile={rec['routing']['profile']} lethality={rec['routing']['lethality']}"
        f"{' (dry-run)' if rec['params']['dry_run'] else ''}",
        f"  candidates: {len(rec['candidates'])}  "
        f"decisions: {len(rec['decisions'])}  "
        f"pending gates: {len(rec['pending_approvals'])}",
        "  model usage / cost:",
    ]
    for u in sorted(rec["model_usage"], key=lambda r: -r["cost_micros"]):
        out.append(f"    {u['task_type']:<22} -> {u['model']:<18} "
                   f"{u['calls']:>2} call(s)  {fmt_usd(u['cost_micros'])}  [{u.get('reason','')}]")
    t = rec["totals"]
    out.append(f"  TOTAL: {t['calls']} call(s)  {fmt_usd(t['cost_usd_micros'])}")
    dga = rec.get("dossier_gap_analysis")
    if dga:
        out.append(f"  dossier gaps: {len(dga.get('gaps', []))} from "
                   f"{dga.get('outputs_considered', 0)} output(s)  "
                   f"-> plan: {dga.get('improvement_plan_path', '')}")
        li = dga.get("log_ingestion") or []
        if li:
            read = sum(1 for s in li if s.get("log_chars"))
            chars = sum(s.get("log_chars", 0) for s in li)
            out.append(f"  log ingestion: read {read}/{len(li)} transcript(s), "
                       f"{chars} chars total")
    for p in rec["pending_approvals"]:
        out.append(f"  PENDING {p['gate']}: {p['reason']}")
    for p in rec.get("rejected_approvals", []):
        note = f" ({p['note']})" if p.get("note") else ""
        out.append(f"  REJECTED {p['gate']}: {p.get('candidate','')}{note}")
    return out


def decision_lines(rec: dict) -> list[str]:
    if not rec.get("decisions"):
        return []
    out = ["  decisions:"]
    for d in rec["decisions"]:
        out.append(f"    {d['action']:<10} {d['candidate']}  - {d['rationale']}")
    return out


def run_pass(*, focus: str, depth: int, dry_run: bool,
             profile: str, lethality: str, reporter=None,
             fetch_from_outputs: bool = False,
             outputs_limit: int = 10, surface: str = "cli") -> dict[str, Any]:
    """Execute one R&D pass and return the run record. Raises on agent error.

    Every pass streams to the live event bus (core.agent_events) regardless of
    surface, so the Control Room sees it; the optional ``reporter`` (e.g. a
    StreamReporter) is composed on top for live stdout.
    """
    from hephaestus.reporting import NullReporter, EventBusReporter, MultiReporter
    from core import agent_events

    router = build_router(dry_run)
    agent_events.install_router(router)
    agent = Hephaestus(router)

    run_id = agent_events.start_run("hephaestus", surface, params={
        "focus": focus, "depth": depth, "dry_run": dry_run, "lethality": lethality,
        "fetch_from_outputs": fetch_from_outputs, "outputs_limit": outputs_limit})
    final_reporter = MultiReporter([EventBusReporter(run_id),
                                    reporter or NullReporter()])
    try:
        rec = asyncio.run(agent.run(
            focus_category=focus, depth=depth, dry_run=dry_run,
            profile=profile, lethality=lethality,
            fetch_from_outputs=fetch_from_outputs, outputs_limit=outputs_limit,
            reporter=final_reporter, run_id=run_id))
    except Exception:
        agent_events.end_run("error", run_id=run_id)
        raise
    agent_events.end_run(rec.get("status", "completed"), run_id=run_id)
    audit("run", rec["run_id"], {"status": rec["status"],
                                 "cost_micros": rec["totals"]["cost_usd_micros"]})
    return rec


def list_runs() -> list[dict]:
    """Parsed run records (order as run_record.list_runs)."""
    out: list[dict] = []
    for p in run_record.list_runs():
        try:
            out.append(json.loads(p.read_text()))
        except Exception:
            continue
    return out


def run_record_path(run_id: str) -> Path:
    return run_record.RUNS_DIR / f"{run_id}.json"


def get_run(run_id: str | None) -> dict | None:
    """Specific run by id, or the most recent if run_id is None."""
    if run_id:
        path = run_record_path(run_id)
        if not path.exists():
            return None
        return json.loads(path.read_text())
    runs = run_record.list_runs()
    return json.loads(runs[0].read_text()) if runs else None


def approve_gate(run_id: str, gate: str) -> dict[str, Any]:
    """Clear a pending H1/H3 gate. Returns {ok, error, remaining}."""
    path = run_record_path(run_id)
    if not path.exists():
        return {"ok": False, "error": f"no such run: {run_id}", "remaining": 0}
    rec = json.loads(path.read_text())
    remaining = [p for p in rec["pending_approvals"] if p["gate"] != gate]
    approved = [p for p in rec["pending_approvals"] if p["gate"] == gate]
    if not approved:
        return {"ok": False, "error": f"no pending {gate} gate on run {run_id}",
                "remaining": len(remaining)}
    rec["pending_approvals"] = remaining
    rec.setdefault("git_actions", []).append(
        {"action": f"gate_approved:{gate}",
         "detail": f"operator approved {gate} for {approved[0].get('candidate','')}"})
    if not remaining:
        rec["status"] = "completed"
    run_record.save(rec)
    audit("approve", run_id, {"gate": gate})
    return {"ok": True, "error": None, "remaining": len(remaining)}


def reject_gate(run_id: str, gate: str, reason: str = "") -> dict[str, Any]:
    """Reject a pending H1/H3 gate (first-class, distinct from deferral).

    Moves the gate out of ``pending_approvals`` into ``rejected_approvals`` with
    the operator's reason, records a ``gate_rejected`` git_action, and writes the
    decision to the SHA-256 audit chain. Returns {ok, error, remaining}.
    """
    path = run_record_path(run_id)
    if not path.exists():
        return {"ok": False, "error": f"no such run: {run_id}", "remaining": 0}
    rec = json.loads(path.read_text())
    remaining = [p for p in rec["pending_approvals"] if p["gate"] != gate]
    rejected = [p for p in rec["pending_approvals"] if p["gate"] == gate]
    if not rejected:
        return {"ok": False, "error": f"no pending {gate} gate on run {run_id}",
                "remaining": len(remaining)}
    rec["pending_approvals"] = remaining
    note = (reason or "").strip()[:400]
    rej_list = rec.setdefault("rejected_approvals", [])
    for p in rejected:
        rej_list.append({
            "gate": gate,
            "reason": p.get("reason", ""),
            "candidate": p.get("candidate", ""),
            "note": note,
            "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
    rec.setdefault("git_actions", []).append(
        {"action": f"gate_rejected:{gate}",
         "detail": f"operator rejected {gate} for {rejected[0].get('candidate','')}"
                   + (f": {note}" if note else "")})
    if not remaining:
        rec["status"] = "completed"
    run_record.save(rec)
    audit("reject", run_id, {"gate": gate, "reason": note})
    return {"ok": True, "error": None, "remaining": len(remaining)}
