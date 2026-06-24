"""Tests for the Hephaestus dossier-mode autoimprove pass (--fetch-from-outputs)."""

import asyncio

import core.dossier_output as do
import hephaestus.agent as agent_mod
from hephaestus.agent import Hephaestus
from hephaestus import run_record
from core.provider_router import ProviderRouter


class FakeSettings:
    def get(self, k, d=None):
        return {"ai.active_provider": "anthropic",
                "ai.fallback_chain": ["anthropic"],
                "ai.anthropic": {}}.get(k, d)


def _seed_outputs(do_dir):
    """One intel_team-style dossier with a single-source 0.9 finding (doctrine flag)."""
    d = do.new_run_dir("alice", "intel_team")
    do.write_run(
        d,
        meta={"source": "intel_team", "target": "alice", "pir_id": "PIR-1"},
        dossier_json={
            "target": "alice",
            "bluf": "BLUF present",
            "key_judgments": [{"judgment": "j", "confidence": 0.9}],
            "findings_by_domain": {
                "socint": [{"value": "x", "confidence": 0.9, "independent_sources": 1}],
            },
        },
        transcript="phase ok\nholehe: rate limited error\n",
    )


def _run(tmp_path, monkeypatch):
    monkeypatch.setattr(do, "OUTPUT_DIR", tmp_path / "outputs")
    monkeypatch.setattr(agent_mod, "_IMPROVE_DIR", tmp_path / "improvements")
    _seed_outputs(do)
    r = ProviderRouter(FakeSettings())
    r.set_dry_run(True)
    return asyncio.run(Hephaestus(r).run(
        fetch_from_outputs=True, outputs_limit=10, dry_run=True))


def test_fetch_from_outputs_emits_valid_dossier_gap_analysis(tmp_path, monkeypatch):
    rec = _run(tmp_path, monkeypatch)
    assert rec["status"] != "error", rec.get("git_actions")
    assert run_record.validate(rec) == []
    assert rec["params"]["fetch_from_outputs"] is True

    dga = rec.get("dossier_gap_analysis")
    assert dga is not None
    assert dga["outputs_considered"] == 1
    cats = {g["category"] for g in dga["gaps"]}
    # single-source 0.9 finding -> doctrine flag; missing domains -> coverage gaps
    assert "confidence-doctrine" in cats
    assert any(c.startswith("domain-coverage:") for c in cats)
    # tool-failure detected from the transcript ("rate limited error")
    assert "tool-failure" in cats
    # improvement plan artifact written
    assert (tmp_path / "improvements").exists()


def test_no_outputs_finishes_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(do, "OUTPUT_DIR", tmp_path / "empty")
    monkeypatch.setattr(agent_mod, "_IMPROVE_DIR", tmp_path / "improvements")
    r = ProviderRouter(FakeSettings())
    r.set_dry_run(True)
    rec = asyncio.run(Hephaestus(r).run(fetch_from_outputs=True, dry_run=True))
    assert rec["status"] != "error"
    assert run_record.validate(rec) == []
    assert rec["dossier_gap_analysis"]["outputs_considered"] == 0
    assert rec["dossier_gap_analysis"]["gaps"] == []
