"""Strikecore FastAPI app — entry point for the Hermes-style dashboard backend.

Run:
    PYTHONPATH=/argus-intelligence/strikecore \\
    /argus-intelligence/strikecore/strikecore/bin/python3 -m uvicorn \\
    web.backend.app:app --host 127.0.0.1 --port 8765
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# Ensure project root on path (so 'agent', 'governance', 'intel_team', 'core' are importable)
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _load_dotenv(p: Path) -> None:
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv(_ROOT / ".env")

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from web.backend.db import (  # noqa: E402
    fetch_one,
    fetch_all,
    listen_traces,
    pool_ping,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("web.backend")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("Strikecore backend starting (postgres ping: %s)", pool_ping())
    # Pre-warm the ToolGateway (Phase B autodiscovery) so /api/agents is instant
    try:
        from agent.tool_gateway import default_gateway
        default_gateway()
        log.info("ToolGateway autodiscovered")
    except Exception as exc:  # noqa: BLE001
        log.warning("ToolGateway unavailable: %s", exc)
    yield
    log.info("Strikecore backend shutting down")


app = FastAPI(
    title="Strikecore API",
    version="0.3.0",
    description="Hermes-like agent dashboard backend (Phase C).",
    lifespan=lifespan,
)

# Wide CORS during dev; tighten in prod (single-operator, behind Caddy)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/api/health", tags=["meta"])
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": app.version,
        "postgres": pool_ping(),
    }


# ---------------------------------------------------------------------------
# Agents (subagent registry)
# ---------------------------------------------------------------------------


@app.get("/api/agents", tags=["agents"])
def list_agents(family: str | None = None) -> list[dict[str, Any]]:
    from agent.tool_gateway import default_gateway
    gw = default_gateway()
    tools = gw.list(family) if family else gw.list()
    out = []
    for t in tools:
        out.append({
            "name": t.name,
            "family": t.family,
            "domain": t.domain,
            "description": t.description,
            "cost_estimate_micros": t.cost_estimate_micros,
            "metadata": t.metadata,
        })
    return out


# ---------------------------------------------------------------------------
# Dossiers
# ---------------------------------------------------------------------------


@app.get("/api/dossiers", tags=["dossiers"])
def list_dossiers(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT d.id, d.pir_question, d.status, d.created_at, d.completed_at,
               d.cost_micros, d.bluf,
               e.kind AS target_kind, e.canonical_value AS target,
               (SELECT COUNT(*) FROM dossier_finding f WHERE f.dossier_id = d.id) AS finding_count,
               (SELECT COUNT(*) FROM agent_run r WHERE r.dossier_id = d.id) AS run_count
        FROM dossier d
        LEFT JOIN entity e ON e.id = d.target_entity_id
    """
    params: list[Any] = []
    if status:
        sql += " WHERE d.status = %s"
        params.append(status)
    sql += " ORDER BY d.created_at DESC LIMIT %s OFFSET %s"
    params += [limit, offset]
    return fetch_all(sql, params)


@app.get("/api/dossiers/{dossier_id}", tags=["dossiers"])
def get_dossier(dossier_id: int) -> dict[str, Any]:
    d = fetch_one(
        """
        SELECT d.*, e.kind AS target_kind, e.canonical_value AS target,
               e.display_name AS target_display_name
        FROM dossier d LEFT JOIN entity e ON e.id = d.target_entity_id
        WHERE d.id = %s
        """,
        (dossier_id,),
    )
    if not d:
        raise HTTPException(status_code=404, detail="dossier not found")
    findings = fetch_all(
        "SELECT * FROM dossier_finding WHERE dossier_id = %s ORDER BY confidence DESC, id",
        (dossier_id,),
    )
    runs = fetch_all(
        "SELECT id, role, agent_name, status, started_at, ended_at, cost_micros "
        "FROM agent_run WHERE dossier_id = %s ORDER BY id",
        (dossier_id,),
    )
    improvements = fetch_all(
        """
        SELECT i.* FROM improvement i
        WHERE i.agent_run_id IN (SELECT id FROM agent_run WHERE dossier_id = %s)
        ORDER BY i.created_at DESC LIMIT 50
        """,
        (dossier_id,),
    )
    cost = fetch_one(
        """
        SELECT COALESCE(SUM(cost_usd_micros),0) AS cost_micros,
               SUM(input_tokens) AS input_tokens,
               SUM(output_tokens) AS output_tokens,
               SUM(cached_tokens) AS cached_tokens,
               COUNT(*) AS llm_calls
        FROM token_ledger
        WHERE dossier_id = %s
           OR agent_run_id IN (SELECT id FROM agent_run WHERE dossier_id = %s)
        """,
        (dossier_id, dossier_id),
    ) or {}
    return {
        "dossier": d,
        "findings": findings,
        "runs": runs,
        "improvements": improvements,
        "cost": cost,
    }


# ---------------------------------------------------------------------------
# Runs / Traces
# ---------------------------------------------------------------------------


@app.get("/api/runs", tags=["runs"])
def list_runs(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    role: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT id, dossier_id, parent_run_id, role, agent_name, status,
               started_at, ended_at, cost_micros
        FROM agent_run
    """
    where: list[str] = []
    params: list[Any] = []
    if role:
        where.append("role = %s"); params.append(role)
    if status:
        where.append("status = %s"); params.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT %s OFFSET %s"
    params += [limit, offset]
    return fetch_all(sql, params)


@app.get("/api/runs/{run_id}", tags=["runs"])
def get_run(run_id: int) -> dict[str, Any]:
    run = fetch_one("SELECT * FROM agent_run WHERE id = %s", (run_id,))
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    invocations = fetch_all(
        "SELECT id, tool_name, started_at, ended_at, success, duration_ms, cost_micros, error_text "
        "FROM subagent_invocation WHERE agent_run_id = %s ORDER BY id",
        (run_id,),
    )
    traces = fetch_all(
        "SELECT id, ts, level, event, payload FROM trace WHERE agent_run_id = %s ORDER BY id LIMIT 500",
        (run_id,),
    )
    return {"run": run, "invocations": invocations, "traces": traces}


@app.get("/api/traces", tags=["runs"])
def list_traces(
    run_id: int | None = None,
    dossier_id: int | None = None,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if run_id is not None:
        where.append("t.agent_run_id = %s"); params.append(run_id)
    if dossier_id is not None:
        where.append("t.agent_run_id IN (SELECT id FROM agent_run WHERE dossier_id = %s)")
        params.append(dossier_id)
    sql = "SELECT t.id, t.ts, t.level, t.event, t.agent_run_id, t.payload FROM trace t"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t.id DESC LIMIT %s OFFSET %s"
    params += [limit, offset]
    return fetch_all(sql, params)


# ---------------------------------------------------------------------------
# Improvements
# ---------------------------------------------------------------------------


@app.get("/api/improvements", tags=["improvements"])
def list_improvements(
    category: str | None = None,
    applied: bool | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if category:
        where.append("category = %s"); params.append(category)
    if applied is not None:
        where.append("applied = %s"); params.append(applied)
    sql = ("SELECT id, agent_run_id, category, target_component, description, "
           "evidence_count, applied, applied_at, patch, created_at FROM improvement")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY evidence_count DESC, id DESC LIMIT %s OFFSET %s"
    params += [limit, offset]
    return fetch_all(sql, params)


# ---------------------------------------------------------------------------
# Token / cost dashboards
# ---------------------------------------------------------------------------


@app.get("/api/tokens/summary", tags=["tokens"])
def tokens_summary() -> dict[str, Any]:
    totals = fetch_one(
        """
        SELECT COUNT(*) AS calls,
               COALESCE(SUM(input_tokens),0)::bigint  AS input_tokens,
               COALESCE(SUM(output_tokens),0)::bigint AS output_tokens,
               COALESCE(SUM(cached_tokens),0)::bigint AS cached_tokens,
               COALESCE(SUM(cost_usd_micros),0)::bigint AS cost_micros
        FROM token_ledger
        """,
    ) or {}
    by_model = fetch_all(
        """
        SELECT model, COUNT(*) AS calls,
               SUM(input_tokens) AS input_tokens,
               SUM(output_tokens) AS output_tokens,
               SUM(cached_tokens) AS cached_tokens,
               SUM(cost_usd_micros) AS cost_micros
        FROM token_ledger GROUP BY model ORDER BY cost_micros DESC NULLS LAST
        """,
    )
    by_day = fetch_all(
        """
        SELECT date_trunc('day', ts)::date AS day,
               COUNT(*) AS calls,
               SUM(cost_usd_micros) AS cost_micros
        FROM token_ledger
        WHERE ts > NOW() - INTERVAL '30 days'
        GROUP BY 1 ORDER BY 1 DESC LIMIT 30
        """,
    )
    cache_rate = fetch_one(
        """
        SELECT CASE WHEN SUM(input_tokens) = 0 THEN 0
                    ELSE SUM(cached_tokens)::float / SUM(input_tokens + cached_tokens) END AS cache_hit_rate
        FROM token_ledger WHERE ts > NOW() - INTERVAL '7 days'
        """,
    ) or {}
    return {
        "totals": totals,
        "by_model": by_model,
        "by_day": by_day,
        "cache_hit_rate_7d": cache_rate.get("cache_hit_rate", 0.0),
    }


@app.get("/api/tokens/by-mode", tags=["tokens"])
def tokens_by_mode() -> dict[str, Any]:
    """Per task_type + model usage/cost — feeds the per-step model badges and the
    dossier-lethality cost view (the router records task_type on every call)."""
    try:
        rows = fetch_all(
            """
            SELECT COALESCE(task_type,'unknown') AS task_type, model,
                   COUNT(*) AS calls,
                   SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens,
                   SUM(cost_usd_micros) AS cost_micros
            FROM token_ledger
            GROUP BY task_type, model
            ORDER BY cost_micros DESC NULLS LAST
            """,
        )
    except Exception:
        rows = []
    return {"by_mode": rows}


# ---------------------------------------------------------------------------
# Hephaestus (toolsmith) — fed by the run records + registry index + audit
# ---------------------------------------------------------------------------


@app.get("/api/hephaestus/runs", tags=["hephaestus"])
def hephaestus_runs(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    """Newest-first Hephaestus run records (discovered tools, decisions, gaps,
    pending H1/H3 approvals, model usage + cost). No DB — reads run-record JSON."""
    runs_dir = Path.home() / ".strikecore" / "hephaestus" / "runs"
    runs: list[dict[str, Any]] = []
    if runs_dir.is_dir():
        files = sorted(runs_dir.glob("*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
        for f in files:
            try:
                runs.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                continue
    pending = [
        {"run_id": r["run_id"], **p}
        for r in runs for p in r.get("pending_approvals", [])
    ]
    return {"runs": runs, "latest": runs[0] if runs else None, "pending": pending}


# ---------------------------------------------------------------------------
# Control Room — live agent telemetry (shared file event bus, no DB)
# ---------------------------------------------------------------------------


@app.get("/api/control-room/state", tags=["control-room"])
def control_room_state(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    """Live aggregates + recent/active agent runs (core.agent_events bus)."""
    try:
        from core import agent_events
        return agent_events.control_room_state(limit)
    except Exception as exc:  # noqa: BLE001
        return {"aggregates": {}, "runs": [], "error": str(exc)}


@app.get("/api/control-room/run/{run_id}", tags=["control-room"])
def control_room_run(run_id: str) -> dict[str, Any]:
    """Drill-down: heartbeat + full event timeline for one run."""
    try:
        from core import agent_events
        return agent_events.run_detail(run_id)
    except Exception as exc:  # noqa: BLE001
        return {"run": {"run_id": run_id, "missing": True}, "timeline": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@app.get("/api/settings", tags=["settings"])
def get_settings_endpoint() -> dict[str, Any]:
    return {
        "model_routing": fetch_all("SELECT * FROM model_routing ORDER BY task_type"),
        "budget_bucket": fetch_all("SELECT * FROM budget_bucket ORDER BY name"),
        "schema_version": fetch_one("SELECT version, applied_at FROM schema_version ORDER BY applied_at DESC LIMIT 1"),
    }


class BudgetUpdate(BaseModel):
    cap_micros: int | None = Field(None, ge=0)
    soft_cap_pct: float | None = Field(None, ge=0.0, le=1.0)
    enabled: bool | None = None


@app.patch("/api/settings/budgets/{name}", tags=["settings"])
def update_budget(name: str, payload: BudgetUpdate) -> dict[str, Any]:
    sets: list[str] = []
    params: list[Any] = []
    for k, v in payload.model_dump(exclude_none=True).items():
        sets.append(f"{k} = %s"); params.append(v)
    if not sets:
        raise HTTPException(status_code=400, detail="no fields to update")
    sets.append("updated_at = NOW()")
    params.append(name)
    sql = f"UPDATE budget_bucket SET {', '.join(sets)} WHERE name = %s RETURNING *"
    row = fetch_one(sql, params)
    if not row:
        raise HTTPException(status_code=404, detail="budget not found")
    return row


# ---------------------------------------------------------------------------
# Console — submit a new dossier (background task)
# ---------------------------------------------------------------------------


class ConsoleSubmission(BaseModel):
    target: str = Field(..., min_length=1, max_length=400)
    pir: str = Field(..., min_length=1, max_length=4000)
    constraints: dict[str, Any] = Field(default_factory=dict)
    operator_notes: str = ""


@app.post("/api/console/dossier", tags=["console"], status_code=202)
async def submit_dossier(body: ConsoleSubmission) -> dict[str, Any]:
    """Kick off a dossier build in the background; return a tracking id."""
    from config.settings import get_settings
    from core.provider_router import ProviderRouter
    from agent.dossier_flow import build_dossier

    settings = get_settings()
    router = ProviderRouter(settings)

    async def _run() -> None:
        try:
            await build_dossier(
                router=router, target=body.target, pir=body.pir,
                operator_notes=body.operator_notes, constraints=body.constraints,
                investigation_store=None,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("background dossier failed: %s", exc)

    asyncio.create_task(_run())
    return {
        "accepted": True,
        "target": body.target,
        "message": "Dossier build started — watch /api/dossiers (latest row) and /ws/traces for live updates.",
    }


# ---------------------------------------------------------------------------
# WebSocket — live trace stream from Postgres LISTEN/NOTIFY
# ---------------------------------------------------------------------------


@app.websocket("/ws/traces")
async def ws_traces(ws: WebSocket) -> None:
    await ws.accept()
    log.info("WS /ws/traces connected from %s", ws.client)
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)

    listener_task = asyncio.create_task(listen_traces(queue))

    try:
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # Keep-alive ping
                await ws.send_text(json.dumps({"event": "ping"}))
                continue
            await ws.send_text(msg)
    except WebSocketDisconnect:
        log.info("WS /ws/traces disconnected")
    finally:
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Static fallback for the React build (Phase C frontend)
# ---------------------------------------------------------------------------


_DIST = _ROOT / "web" / "frontend" / "dist"
if _DIST.is_dir():
    from fastapi.staticfiles import StaticFiles  # noqa: E402

    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="frontend")
else:
    @app.get("/", include_in_schema=False)
    def root() -> JSONResponse:
        return JSONResponse({
            "service": "strikecore-backend",
            "version": app.version,
            "note": "Frontend not built yet. Run `pnpm build` in web/frontend/.",
            "api_docs": "/docs",
        })
