import json
from pathlib import Path
import pytest
from hephaestus import cli_core, run_record


def _make_record(run_id="heph-test-1", status="completed", pending=None):
    return {
        "run_id": run_id,
        "status": status,
        "started_at": "2026-06-12T00:00:00+00:00",
        "params": {"focus_category": "voip", "depth": 1, "dry_run": True},
        "routing": {"profile": "hephaestus", "lethality": "balanced"},
        "candidates": [{"name": "toolA"}],
        "decisions": [{"action": "build", "candidate": "toolA", "rationale": "fills gap"}],
        "pending_approvals": pending or [],
        "model_usage": [
            {"task_type": "discovery", "model": "claude-haiku-4-5", "calls": 1,
             "cost_micros": 1200, "reason": "bulk"}
        ],
        "totals": {"calls": 1, "cost_usd_micros": 1200},
    }


def test_fmt_usd():
    assert cli_core.fmt_usd(1_000_000) == "$1.0000"


def test_summary_lines_contains_key_facts():
    lines = cli_core.summary_lines(_make_record())
    blob = "\n".join(lines)
    assert "heph-test-1" in blob
    assert "voip" in blob
    assert "TOTAL" in blob


def test_summary_lines_shows_pending_gate():
    rec = _make_record(pending=[{"gate": "H1", "reason": "untrusted upstream"}])
    blob = "\n".join(cli_core.summary_lines(rec))
    assert "H1" in blob and "PENDING" in blob


def test_list_and_get_run(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    monkeypatch.setattr(run_record, "RUNS_DIR", runs_dir)
    rec = _make_record()
    (runs_dir / f"{rec['run_id']}.json").write_text(json.dumps(rec))
    monkeypatch.setattr(run_record, "list_runs", lambda: list(runs_dir.glob("*.json")))
    got = cli_core.list_runs()
    assert got and got[0]["run_id"] == "heph-test-1"
    assert cli_core.get_run("heph-test-1")["status"] == "completed"
    assert cli_core.get_run("nope") is None


def test_approve_gate(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    monkeypatch.setattr(run_record, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(run_record, "save",
                         lambda rec: (runs_dir / f"{rec['run_id']}.json").write_text(json.dumps(rec)))
    monkeypatch.setattr(cli_core, "audit", lambda *a, **k: None)
    rec = _make_record(status="awaiting_gate",
                       pending=[{"gate": "H1", "reason": "x", "candidate": "toolA"}])
    (runs_dir / f"{rec['run_id']}.json").write_text(json.dumps(rec))
    res = cli_core.approve_gate("heph-test-1", "H1")
    assert res["ok"] is True and res["remaining"] == 0
    miss = cli_core.approve_gate("heph-test-1", "H3")
    assert miss["ok"] is False and "no pending" in miss["error"].lower()
