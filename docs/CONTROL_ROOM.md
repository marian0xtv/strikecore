# Control Room — live agent visibility (CLI + dashboards)

> An htop-style, real-time view of **every StrikeCore agent in flight**, with the
> right per-agent metrics and a **deep drill-down on Hephaestus** (research → gaps
> → fixes → H1/H3 gates). Available in the console (Textual TUI) and embedded in
> **both** dashboards.

## Architecture — one unified event bus

`core/agent_events.py` is the single source of truth: a file-based, cross-process
event bus (no DB dependency), matching the audit JSONL idiom.

| Artifact | Purpose |
|---|---|
| `~/.strikecore/events/<YYYY-MM-DD>.jsonl` | append-only event log (one JSON/line) |
| `~/.strikecore/events/active/<run_id>.json` | per-run heartbeat (rolling totals) |

- API: `start_run(agent, surface, params) -> run_id`, `set_phase`, `emit(type, **f)`,
  `end_run(status)`, with a `contextvars` `current_run` for auto-tagging.
- Reader (used by the CLI **and** both dashboards — one implementation):
  `control_room_state()`, `run_detail(run_id)`, `active_runs()`, `recent_runs()`,
  `aggregates()`.
- **Automatic cost capture:** `ProviderRouter.on_call` fires per LLM call;
  `agent_events.install_router(router)` wires it so spend for *every* agent flows to
  the bus tagged with the current run. GR3 routing is untouched.
- Best-effort + failure-isolated: telemetry can never break an agent run. The bus is
  **separate** from the §3.8 audit/chain-of-custody log.

A run is "active" while its heartbeat `status == running` and `last_seen` < 30s;
older running heartbeats show as `stale`.

## Instrumented agents

| Agent | Surface field | Events |
|---|---|---|
| Hephaestus | console/cli | deep: phase (discovery/research/gap/decision/gates or dossier-improve), stream summaries, gaps/fixes, gate_request/result, cost |
| intel_team | cli | routing → specialists → quality_gate → audit → synthesis, per-domain findings |
| dossier_flow (Hermes) | cli | planning → collection → synthesis → critic, findings |
| console NLP engine | console | reasoning → collection (per-tool), cost |

Hephaestus composes a `MultiReporter([EventBusReporter, StreamReporter])`
(`hephaestus/reporting.py`) so a run streams to the bus **and** stdout regardless of
surface; `hephaestus/cli_core.py:run_pass` wraps it in `start_run`/`end_run`.

## CLI — `controlroom`

```
controlroom            # interactive Textual TUI (q quit · s sort · f active-only · r refresh)
controlroom --once     # one-shot snapshot (no TUI; also used when stdout is not a TTY)
```

Aliases: `/controlroom`, `monitor`. Layout: header aggregates (active agents, calls,
calls/min, cost, pending gates, models in use) · sortable agent table · drill-down
detail pane (deep for Hephaestus). Requires `textual` (added to `pyproject.toml` /
`requirements.txt`); without it, `controlroom` prints the snapshot.

## Dashboards (both)

One shared backend reader feeds both UIs:

- **FastAPI** (`web/backend/app.py`): `GET /api/control-room/state`,
  `GET /api/control-room/run/{run_id}`.
- **React** (`web/frontend/src/pages/ControlRoom.tsx`, nav + route added): polls
  `state` every 2s, htop-like table + Hephaestus drill-down.
- **Flask** (`osint_agent/dashboard/app.py`): `/control-room` page (2s polling) +
  `/api/control-room/state` + `/api/control-room/run/<id>`.

## Quick verification

```bash
# 1. unit tests
python3 -m pytest tests/test_agent_events.py tests/test_control_room.py -q

# 2. live: run a Hephaestus pass, watch it in another shell
hephaestus run --fetch-from-outputs --dry-run    # terminal A
controlroom                                       # terminal B (or: controlroom --once)

# 3. dashboards
curl -s :8765/api/control-room/state | jq .aggregates      # React/FastAPI
curl -s :5000/api/control-room/state | jq .aggregates      # Flask
```
