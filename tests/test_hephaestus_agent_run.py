import asyncio
from hephaestus.agent import Hephaestus
from hephaestus.reporting import RunReporter
from core.provider_router import ProviderRouter
from governance.model_router import ModelPolicy


class FakeSettings:
    def get(self, k, d=None):
        return {"ai.active_provider": "anthropic",
                "ai.fallback_chain": ["anthropic"],
                "ai.anthropic": {}}.get(k, d)


class RecordingReporter(RunReporter):
    def __init__(self, approve=False):
        self.phases, self.gates, self.deltas = [], [], []
        self._approve = approve
    def phase(self, name, detail=""): self.phases.append(name)
    def stream_delta(self, text): self.deltas.append(text)
    def request_gate(self, gate): self.gates.append(gate["gate"]); return self._approve


def _run(reporter, approve=False):
    r = ProviderRouter(FakeSettings())
    r.set_dry_run(True)
    agent = Hephaestus(r)
    return asyncio.run(agent.run(focus_category="voip", depth=1, dry_run=True,
                                 reporter=reporter))


def test_run_emits_phases_and_streams():
    rep = RecordingReporter()
    rec = _run(rep)
    for p in ("discovery", "research", "gap", "decision", "gates"):
        assert p in rep.phases, (p, rep.phases)
    assert rep.deltas, "expected streamed deltas"


def test_default_reporter_defers_gates():
    r = ProviderRouter(FakeSettings()); r.set_dry_run(True)
    rec = asyncio.run(Hephaestus(r).run(focus_category="voip", dry_run=True))
    assert rec["status"] == "paused"
    assert len(rec["pending_approvals"]) == 2
    assert not [a for a in rec["git_actions"] if a["action"].startswith("gate_approved")]


def test_live_approval_completes_run_and_records_git_actions():
    rep = RecordingReporter(approve=True)
    rec = _run(rep, approve=True)
    assert rep.gates == ["H1", "H3"]
    assert rec["status"] == "completed"
    assert rec["pending_approvals"] == []
    approved = [a for a in rec["git_actions"] if a["action"].startswith("gate_approved")]
    assert {a["action"] for a in approved} == {"gate_approved:H1", "gate_approved:H3"}
