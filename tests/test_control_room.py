"""Tests for the control-room data builders + Hephaestus EventBusReporter."""

import core.agent_events as ev


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(ev, "ACTIVE_DIR", tmp_path / "events" / "active")
    ev.current_run.set(None)


def test_build_state_and_snapshot(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from cli import controlroom as cr

    a = ev.start_run("hephaestus", "console", {"fetch_from_outputs": True})
    ev.emit("llm_call", run_id=a, model="claude-opus-4-8", cost_micros=5000,
            input_tokens=50, output_tokens=20)
    b = ev.start_run("intel_team", "cli", {"target": "alice"})
    ev.end_run("completed", run_id=b)

    st = cr.build_state(sort="cost")
    assert st["aggregates"]["llm_calls"] == 1
    assert st["aggregates"]["cost_micros"] == 5000
    # cost sort puts the hephaestus run (only one with cost) first
    assert st["runs"][0]["run_id"] == a

    # active-only filter drops the completed intel_team run
    active = cr.build_state(active_only=True)
    assert all(r["is_active"] for r in active["runs"])
    assert any(r["run_id"] == a for r in active["runs"])

    text = cr.snapshot_text()
    assert "hephaestus" in text and "intel_team" in text


def test_eventbus_reporter_maps_hooks(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from hephaestus.reporting import EventBusReporter, MultiReporter, NullReporter

    rid = ev.start_run("hephaestus", "cli")
    rep = MultiReporter([EventBusReporter(rid), NullReporter()])
    rep.phase("dossier-gap", "analyze")
    rep.info("detected 3 gap(s)")
    rep.stream_start("dossier gap analysis", "claude-opus-4-8")
    rep.stream_delta("some "); rep.stream_delta("text")
    rep.stream_end()
    assert rep.request_gate({"gate": "H1", "reason": "untrusted"}) is False
    rep.gate_result({"gate": "H1"}, False, None)

    detail = ev.run_detail(rid)
    types = [e["event_type"] for e in detail["timeline"]]
    for expected in ("phase", "info", "stream_start", "stream_end",
                     "gate_request", "gate_result"):
        assert expected in types, (expected, types)
    # gate_request with no approval leaves H1 pending on the heartbeat
    assert detail["run"]["pending_gates"] == ["H1"]


def test_hephaestus_run_streams_to_bus(tmp_path, monkeypatch):
    """A dry-run Hephaestus pass drives phases + cost into the bus end-to-end."""
    _isolate(tmp_path, monkeypatch)
    import asyncio
    from core.provider_router import ProviderRouter
    from hephaestus.agent import Hephaestus
    from hephaestus.reporting import EventBusReporter, MultiReporter, NullReporter

    class FakeSettings:
        def get(self, k, d=None):
            return {"ai.active_provider": "anthropic",
                    "ai.fallback_chain": ["anthropic"], "ai.anthropic": {}}.get(k, d)

    router = ProviderRouter(FakeSettings()); router.set_dry_run(True)
    ev.install_router(router)
    rid = ev.start_run("hephaestus", "cli", {"focus": "voip"})
    ev.current_run.set(rid)
    rep = MultiReporter([EventBusReporter(rid), NullReporter()])
    rec = asyncio.run(Hephaestus(router).run(
        focus_category="voip", dry_run=True, reporter=rep, run_id=rid))
    ev.end_run(rec["status"], run_id=rid)

    detail = ev.run_detail(rid)
    phases = {e.get("phase") for e in detail["timeline"] if e["event_type"] == "phase"}
    assert {"discovery", "research", "gap", "decision", "gates"} <= phases
    assert detail["run"]["calls"] >= 1  # router on_call captured dry-run cost
    assert rec["run_id"] == rid


def test_textual_app_constructs():
    import pytest
    pytest.importorskip("textual")
    from cli.controlroom import _build_app
    App = _build_app()
    assert App is not None  # class builds without error when textual is present


def test_multireporter_request_gate_or_semantics(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from hephaestus.reporting import MultiReporter, RunReporter

    class YesReporter(RunReporter):
        def request_gate(self, gate):
            return True

    class NoReporter(RunReporter):
        def request_gate(self, gate):
            return False

    assert MultiReporter([NoReporter(), YesReporter()]).request_gate({"gate": "H1"}) is True
    assert MultiReporter([NoReporter(), NoReporter()]).request_gate({"gate": "H1"}) is False
