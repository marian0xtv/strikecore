"""Tests for the unified live agent event bus (core/agent_events.py)."""

import core.agent_events as ev


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(ev, "ACTIVE_DIR", tmp_path / "events" / "active")
    ev.current_run.set(None)


def test_run_roundtrip(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    rid = ev.start_run("hephaestus", "cli", {"focus": "voip"})
    ev.set_phase("research")
    ev.emit("info", detail="found 3 candidates")
    ev.end_run("completed", run_id=rid)

    recent = ev.recent_runs()
    assert len(recent) == 1
    r = recent[0]
    assert r["agent"] == "hephaestus" and r["surface"] == "cli"
    assert r["effective_status"] == "completed"
    assert r["phase"] == "research"

    detail = ev.run_detail(rid)
    types = [e["event_type"] for e in detail["timeline"]]
    assert types[0] == "run_start" and "phase" in types and types[-1] == "run_end"


def test_llm_call_folds_into_heartbeat_and_aggregates(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    rid = ev.start_run("intel_team", "cli")

    class Call:
        task_type = "specialist:socint"; model = "claude-haiku-4-5"
        input_tokens = 100; output_tokens = 40; cost_micros = 1500; dry_run = False

    ev.current_run.set(rid)
    ev.record_call(Call())
    ev.record_call(Call())

    r = ev.run_detail(rid)["run"]
    assert r["calls"] == 2
    assert r["input_tokens"] == 200 and r["output_tokens"] == 80
    assert r["cost_micros"] == 3000

    agg = ev.aggregates()
    assert agg["llm_calls"] == 2
    assert agg["cost_micros"] == 3000
    assert agg["active_agents"] == 1  # still running


def test_gate_request_tracks_pending_then_clears(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    rid = ev.start_run("hephaestus", "console")
    ev.emit("gate_request", run_id=rid, gate="H1", detail="untrusted")
    ev.emit("gate_request", run_id=rid, gate="H3", detail="ungated")
    assert ev.run_detail(rid)["run"]["pending_gates"] == ["H1", "H3"]
    ev.emit("gate_result", run_id=rid, gate="H1", approved=True)
    assert ev.run_detail(rid)["run"]["pending_gates"] == ["H3"]
    assert ev.aggregates()["pending_gates"] == 1


def test_record_call_without_context_is_noop(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    ev.current_run.set(None)

    class Call:
        task_type = "x"; model = "m"; input_tokens = 1; output_tokens = 1
        cost_micros = 1; dry_run = True

    ev.record_call(Call())  # no current run -> nothing recorded
    assert ev.recent_runs() == []


def test_router_on_call_wiring(tmp_path, monkeypatch):
    """install_router + a real ProviderRouter._log_call emits an llm_call event."""
    _isolate(tmp_path, monkeypatch)
    from core.provider_router import ProviderRouter, CallRecord

    class FakeSettings:
        def get(self, k, d=None):
            return {"ai.active_provider": "anthropic",
                    "ai.fallback_chain": ["anthropic"], "ai.anthropic": {}}.get(k, d)

    router = ProviderRouter(FakeSettings())
    ev.install_router(router)
    rid = ev.start_run("dossier_flow", "cli")
    ev.current_run.set(rid)
    router._log_call(CallRecord(
        task_type="planner", model="claude-opus-4-8", routing_reason="r",
        input_tokens=10, output_tokens=5, cost_micros=999))

    r = ev.run_detail(rid)["run"]
    assert r["calls"] == 1 and r["cost_micros"] == 999
    assert router.call_log and router.call_log[-1].cost_micros == 999  # still ledgered


def test_stale_run_not_active(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    rid = ev.start_run("console", "console")
    # force an old last_seen
    hb = ev._load_heartbeat(rid)
    hb["last_seen"] = 0.0
    ev._save_heartbeat(hb)
    runs = ev.recent_runs()
    assert runs and runs[0]["effective_status"] == "stale"
    assert ev.active_runs() == []
