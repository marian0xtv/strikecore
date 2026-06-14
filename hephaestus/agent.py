"""Hephaestus — the native StrikeCore toolsmith agent.

A full R&D run: GitHub discovery -> deep research (router reasoning) -> gap
analysis vs the live tool registry -> decide (integrate/fork/write) -> emit a
schema-validated run record. Untrusted upstream code is NEVER executed against
real targets and NEVER auto-registered: the run PAUSES with H1/H3 approval
requests surfaced in the run record (consumed by the CLI + dashboard).

All LLM work flows through the shared cost-aware router (GR3) using the
"hephaestus" routing profile: discovery/extraction -> Haiku, research -> Opus,
design + gap analysis -> Fable.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from governance.model_router import ModelPolicy
from hephaestus import discovery, run_record
from hephaestus.reporting import NullReporter, RunReporter

_HEPH_SYSTEM = (
    "You are Hephaestus, StrikeCore's OSINT toolsmith. Evaluate candidate tools, "
    "separate facts from recommendations, cite sources, and decide whether to "
    "integrate, fork, or write new — strictly per the Integration Contract. "
    "Never run untrusted upstream code against real targets."
)

# StrikeCore's standing OSINT capability gaps (from the Phase-1 gap map).
_KNOWN_GAPS = [
    "document", "threatint", "image", "italian-specific",
    "cloud", "crypto", "dark-web", "code-repo",
]
_REGISTRY_INDEX = Path.home() / ".strikecore" / "registry" / "index.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _first_line(text: str) -> str:
    return (text or "").strip().splitlines()[0][:200] if text else ""


class Hephaestus:
    """Native StrikeCore R&D agent. Construct with a ProviderRouter."""

    def __init__(self, router: Any) -> None:
        self.router = router

    def _covered_capabilities(self) -> list[str]:
        """Categories already covered, read from the live registry index."""
        try:
            idx = json.loads(_REGISTRY_INDEX.read_text(encoding="utf-8"))
            return sorted({t.get("category", "") for t in idx.get("tools", {}).values()
                           if t.get("category")})
        except Exception:
            return []

    async def _stream(self, rep, *, label: str, content: str,
                      task_type: str, dry_run: bool) -> str:
        """Stream one routed LLM call through the reporter; return full text."""
        model = self.router.resolve_model(task_type=task_type)
        rep.stream_start(label, model)
        chunks: list[str] = []
        async for delta in self.router.stream_chat(
            [{"role": "user", "content": content}],
            system=_HEPH_SYSTEM, task_type=task_type, dry_run=dry_run):
            chunks.append(delta)
            rep.stream_delta(delta)
        rep.stream_end()
        return "".join(chunks)

    async def run(
        self,
        focus_category: str,
        depth: int = 1,
        dry_run: bool = False,
        profile: str = "hephaestus",
        lethality: str = "balanced",
        reporter: RunReporter | None = None,
    ) -> dict:
        """Execute one R&D run and return the validated run record."""
        run_id = uuid.uuid4().hex[:12]
        started = _now()
        rep = reporter or NullReporter()

        # Apply the run's routing profile to the shared router (GR3).
        base = self.router.policy
        self.router.set_policy(ModelPolicy(
            mode=base.mode, pinned_model=base.pinned_model,
            profile=profile, lethality=lethality, overrides=dict(base.overrides),
        ))
        self.router.set_dry_run(dry_run)
        self.router.reset_log()

        # 1) Discovery (HTTP / offline fixture) — no LLM.
        rep.phase("discovery", focus_category)
        candidates = discovery.discover(focus_category, limit=max(3, depth * 2),
                                        dry_run=dry_run)
        for c in candidates:
            rep.info(f"{c['name']} — {c['url']} "
                     f"[{c.get('reliability','?')}{c.get('confidence','?')}]")

        # 2) Deep research — one routed streaming call per top candidate.
        rep.phase("research")
        research: list[dict] = []
        for c in candidates[: depth + 1]:
            text = await self._stream(
                rep, label=f"research: {c['name']}", task_type="hephaestus:research",
                dry_run=dry_run,
                content=(f"Summarize OSINT tool {c['name']} ({c['url']}). "
                         f"List capabilities (facts) then a recommendation."))
            claim = "capabilities reviewed" if dry_run else _first_line(text)
            research.append({"claim": f"{c['name']}: {claim}",
                             "source": c["url"], "kind": "fact"})

        # 3) Gap analysis — Fable tier (remapped to Opus on this account).
        rep.phase("gap")
        covered = self._covered_capabilities()
        gaps = [g for g in _KNOWN_GAPS if g not in covered]
        await self._stream(
            rep, label="gap analysis", task_type="hephaestus:gap", dry_run=dry_run,
            content=(f"Given covered={covered} and gaps={gaps}, assess where "
                     f"'{focus_category}' ranks and what to build."))
        gap_analysis = {"covered": covered, "gaps": gaps, "target_gap": focus_category}

        # 4) Decision — Fable tier (novel design).
        rep.phase("decision")
        decisions: list[dict] = []
        if candidates:
            top = candidates[0]
            await self._stream(
                rep, label=f"decide: {top['name']}", task_type="hephaestus:design",
                dry_run=dry_run,
                content=(f"Decide integrate/fork/write for {top['name']} to "
                         f"close the '{focus_category}' gap, per the contract."))
            decisions.append({
                "candidate": top["name"], "action": "integrate",
                "rationale": f"Best Admiralty score ({top['reliability']}{top['confidence']}) "
                             f"for the {focus_category} gap; wrap per Integration Contract.",
            })

        # 5) H1/H3 gates — ask the operator live; defer when non-interactive.
        rep.phase("gates")
        pending: list[dict] = []
        git_actions: list[dict] = []
        if decisions:
            cand = decisions[0]["candidate"]
            slug = re.sub(r"[^a-z0-9_-]+", "-", cand.lower()).strip("-") or "tool"
            gate_specs = [
                ("H1", f"{cand} is untrusted upstream code — needs the manual "
                       f"sandbox gate before any real-target run."),
                ("H3", f"{cand} ships gate_approved=false — will not be registered "
                       f"until the operator approves."),
            ]
            for gate, why in gate_specs:
                g = {"gate": gate, "candidate": cand, "reason": why}
                if rep.request_gate(g):
                    git_actions.append({
                        "action": f"gate_approved:{gate}",
                        "detail": f"operator approved {gate} live for {cand}"})
                    register_cmd = (f"python3 bin/sc-registry.py register tools/{slug}"
                                    f"  # build per the Integration Contract first")
                    rep.gate_result(g, True, register_cmd)
                else:
                    pending.append(g)
                    rep.gate_result(g, False, None)
        status = "paused" if pending else "completed"

        # 6) Assemble + validate the run record.
        cost = self.router.run_cost()
        record = {
            "schema_version": 1,
            "run_id": run_id,
            "started_at": started,
            "finished_at": _now(),
            "status": status,
            "params": {"focus_category": focus_category, "depth": int(depth),
                       "dry_run": bool(dry_run), "profile": profile,
                       "lethality": lethality},
            "candidates": candidates,
            "research": research,
            "gap_analysis": gap_analysis,
            "decisions": decisions,
            "git_actions": git_actions,
            "pending_approvals": pending,
            "routing": {"profile": cost["profile"], "policy": cost["policy"],
                        "lethality": lethality},
            "model_usage": run_record.model_usage_from_cost(cost),
            "totals": cost["totals"],
        }
        errors = run_record.validate(record)
        if errors:
            record["status"] = "error"
            record.setdefault("git_actions", []).append(
                {"action": "validation_error", "detail": "; ".join(errors[:5])})
        run_record.save(record)
        return record
