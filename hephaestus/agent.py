"""Hephaestus — the native StrikeCore toolsmith agent.

Two run modes, both ending in a schema-validated run record:

1. **Discovery R&D** (default): GitHub discovery -> deep research (router
   reasoning) -> gap analysis vs the live tool registry -> decide
   (integrate/fork/write).

2. **Dossier autoimprove** (``--fetch-from-outputs``): ingest the captured
   dossier outputs (``~/strikecore-data/dossieroutputs/`` via
   ``core.dossier_output``) -> detect gaps in dossier mode -> research ->
   propose fixes. Tool/code changes raise H1/H3 gates; prompt/flow/config
   enhancements are written to an improvement-plan artifact and surfaced,
   never auto-applied (GR5; NL_SYSTEM_PROMPT stays preserved, CLAUDE.md section 10).

Untrusted upstream code is NEVER executed against real targets and NEVER
auto-registered: the run PAUSES with H1/H3 approval requests surfaced in the run
record (consumed by the CLI + dashboard).

All LLM work flows through the shared cost-aware router (GR3) using the
"hephaestus" routing profile: discovery/extraction -> Haiku, research -> Opus,
design + gap analysis (incl. dossier_gap) -> Fable.
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

_DOSSIER_SYSTEM = (
    "You are Hephaestus running a dossier-mode autoimprove pass. You are given a "
    "digest of StrikeCore's recent dossier outputs AND evidence extracted from the "
    "COMPLETE verbose run transcripts. Assess where dossier mode is "
    "weakest (coverage gaps, low-confidence/doctrine violations, tool failures, "
    "empty sections), prioritise the gaps, and recommend concrete improvements. "
    "Distinguish gaps that need a NEW TOOL from gaps that need a prompt/flow/config "
    "change. Never propose rewriting the preserved NL_SYSTEM_PROMPT."
)

# Map step of the dossier-log map-reduce: cheap per-fragment extraction (Haiku).
_LOG_MAP_SYSTEM = (
    "You are Hephaestus reading a fragment of a StrikeCore dossier run transcript. "
    "Extract only what is present, terse and factual: tools invoked, "
    "failures/errors (quote the marker), findings produced, empty/aborted sections, "
    "and any coverage gap the run reveals. No preamble, no recommendations."
)

# Bounds for reading the COMPLETE output.log on the GR3 bulk tier. Map cost is
# bounded per run (<= _MAX_LOG_CHARS / _LOG_CHUNK Haiku calls); total cost scales
# with the operator-chosen ``outputs_limit`` window, not the log size.
_LOG_CHUNK = 24_000          # chars per map-window sent to the bulk model
_MAX_LOG_CHARS = 240_000     # per-run ceiling (head+tail kept beyond this)
_MAX_LOG_EVIDENCE = 16_000   # combined per-run evidence fed into the reduce call

# StrikeCore's standing OSINT capability gaps (from the Phase-1 gap map).
_KNOWN_GAPS = [
    "document", "threatint", "image", "italian-specific",
    "cloud", "crypto", "dark-web", "code-repo",
]
# Domains a well-formed person/entity dossier is generally expected to touch.
_EXPECTED_DOMAINS = ["socint", "socialint", "geoint", "webint", "techint", "threatint"]

_REGISTRY_INDEX = Path.home() / ".strikecore" / "registry" / "index.json"
_IMPROVE_DIR = Path.home() / ".strikecore" / "hephaestus" / "improvements"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _first_line(text: str) -> str:
    return (text or "").strip().splitlines()[0][:200] if text else ""


def _parse_json_obj(content: str) -> dict | None:
    """Tolerant JSON-object parse (strips fences / surrounding prose)."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*", "", text).strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    if not text.startswith("{"):
        first, last = text.find("{"), text.rfind("}")
        if first != -1 and last > first:
            text = text[first:last + 1]
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


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

    async def _stream(self, rep, *, label: str, content: str, task_type: str,
                      dry_run: bool, system: str = _HEPH_SYSTEM) -> str:
        """Stream one routed LLM call through the reporter; return full text."""
        model = self.router.resolve_model(task_type=task_type)
        rep.stream_start(label, model)
        chunks: list[str] = []
        async for delta in self.router.stream_chat(
            [{"role": "user", "content": content}],
            system=system, task_type=task_type, dry_run=dry_run):
            chunks.append(delta)
            rep.stream_delta(delta)
        rep.stream_end()
        return "".join(chunks)

    # ------------------------------------------------------------------
    # H1/H3 gates (shared by both modes)
    # ------------------------------------------------------------------
    def _gate_decisions(self, rep, decisions: list[dict]) -> tuple[list[dict], list[dict]]:
        """Raise H1/H3 gates for each code/tool-touching decision.

        Returns (pending_approvals, git_actions). Live approval records a
        git_action and prints the register command; deferral -> pending.
        """
        pending: list[dict] = []
        git_actions: list[dict] = []
        for d in decisions:
            if d.get("action") not in ("integrate", "fork", "write"):
                continue
            cand = d["candidate"]
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
        return pending, git_actions

    # ------------------------------------------------------------------
    # Dossier-log map step: read the COMPLETE transcripts (GR3 bulk tier)
    # ------------------------------------------------------------------
    async def _summarize_logs(self, rep, runs: list[dict], dry_run: bool) -> list[dict]:
        """Map each run's ENTIRE output.log to compact evidence via a cheap
        routed call, chunking large logs. Returns per-run
        ``{run, log_chars, summary}`` (empty summary when the log is empty).

        This is what makes Hephaestus actually READ the complete verbose dossier
        output: every transcript is ingested (chunked map -> Haiku), then the
        combined evidence feeds the reduce-tier gap analysis.
        """
        summaries: list[dict] = []
        for r in runs:
            name = r["dir"].name if r.get("dir") is not None else "?"
            try:
                log = r["log_path"].read_text(encoding="utf-8", errors="ignore")
            except OSError:
                log = ""
            log = log.strip()
            if not log:
                summaries.append({"run": name, "log_chars": 0, "summary": ""})
                continue
            clipped = log
            if len(clipped) > _MAX_LOG_CHARS:
                half = _MAX_LOG_CHARS // 2
                clipped = (clipped[:half]
                           + "\n...[log truncated for length; head+tail kept]...\n"
                           + clipped[-half:])
            chunks = [clipped[i:i + _LOG_CHUNK]
                      for i in range(0, len(clipped), _LOG_CHUNK)]
            partials: list[str] = []
            for ci, ch in enumerate(chunks):
                if dry_run:
                    partials.append("log reviewed")
                    continue
                text = await self._stream(
                    rep, label=f"log map: {name} [{ci + 1}/{len(chunks)}]",
                    task_type="hephaestus:extract", dry_run=dry_run,
                    system=_LOG_MAP_SYSTEM,
                    content=("Extract evidence from this dossier-run transcript "
                             "fragment:\n\n" + ch))
                partials.append(text.strip())
            summary = "\n".join(p for p in partials if p)
            summaries.append({"run": name, "log_chars": len(log),
                              "summary": summary[:2000]})
        return summaries

    async def run(
        self,
        focus_category: str = "dossier-mode",
        depth: int = 1,
        dry_run: bool = False,
        profile: str = "hephaestus",
        lethality: str = "balanced",
        reporter: RunReporter | None = None,
        fetch_from_outputs: bool = False,
        outputs_limit: int = 10,
        run_id: str | None = None,
    ) -> dict:
        """Execute one R&D run and return the validated run record."""
        run_id = run_id or uuid.uuid4().hex[:12]
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

        # Mode dispatch -> per-mode record pieces.
        if fetch_from_outputs:
            pieces = await self._collect_dossier_improve(
                rep, run_id, focus_category, depth, dry_run, outputs_limit)
        else:
            pieces = await self._collect_discovery(rep, focus_category, depth, dry_run)

        # H1/H3 gates over any code/tool decision.
        rep.phase("gates")
        pending, git_actions = self._gate_decisions(rep, pieces["decisions"])
        status = "paused" if pending else "completed"

        # Assemble + validate the run record.
        cost = self.router.run_cost()
        record = {
            "schema_version": 1,
            "run_id": run_id,
            "started_at": started,
            "finished_at": _now(),
            "status": status,
            "params": {"focus_category": focus_category, "depth": int(depth),
                       "dry_run": bool(dry_run), "profile": profile,
                       "lethality": lethality,
                       "fetch_from_outputs": bool(fetch_from_outputs),
                       "outputs_limit": int(outputs_limit)},
            "candidates": pieces["candidates"],
            "research": pieces["research"],
            "gap_analysis": pieces["gap_analysis"],
            "decisions": pieces["decisions"],
            "git_actions": git_actions,
            "pending_approvals": pending,
            "routing": {"profile": cost["profile"], "policy": cost["policy"],
                        "lethality": lethality},
            "model_usage": run_record.model_usage_from_cost(cost),
            "totals": cost["totals"],
        }
        if pieces.get("dossier_gap_analysis") is not None:
            record["dossier_gap_analysis"] = pieces["dossier_gap_analysis"]

        errors = run_record.validate(record)
        if errors:
            record["status"] = "error"
            record.setdefault("git_actions", []).append(
                {"action": "validation_error", "detail": "; ".join(errors[:5])})
        run_record.save(record)
        return record

    # ------------------------------------------------------------------
    # Mode 1: discovery R&D
    # ------------------------------------------------------------------
    async def _collect_discovery(self, rep, focus_category, depth, dry_run) -> dict:
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
        return {"candidates": candidates, "research": research,
                "gap_analysis": gap_analysis, "decisions": decisions}

    # ------------------------------------------------------------------
    # Mode 2: dossier autoimprove (--fetch-from-outputs)
    # ------------------------------------------------------------------
    async def _collect_dossier_improve(self, rep, run_id, focus_category, depth,
                                       dry_run, outputs_limit) -> dict:
        from core import dossier_output

        # 1) Ingest captured dossier outputs.
        rep.phase("ingest", "dossieroutputs")
        runs = dossier_output.iter_runs(outputs_limit)
        rep.info(f"{len(runs)} dossier output(s) considered "
                 f"(dir: {dossier_output.OUTPUT_DIR})")

        # Deterministic heuristic gaps (backbone; independent of the LLM).
        heuristic_gaps = _heuristic_dossier_gaps(runs)
        digest = _digest_outputs(runs)

        # 1b) Map step — read the COMPLETE verbose transcripts (GR3 bulk tier).
        rep.phase("dossier-logs", "reading full transcripts")
        log_summaries = await self._summarize_logs(rep, runs, dry_run)
        log_evidence = _format_log_evidence(log_summaries)
        n_read = sum(1 for s in log_summaries if s["log_chars"])
        rep.info(f"ingested {n_read}/{len(runs)} transcript(s) "
                 f"({sum(s['log_chars'] for s in log_summaries)} chars total)")

        # 2) Dossier gap analysis — routed Fable call (assessment / prioritisation),
        #    now grounded in the full-transcript evidence, not just the digest.
        rep.phase("dossier-gap")
        assessment = ""
        if runs:
            assessment = await self._stream(
                rep, label="dossier gap analysis", task_type="hephaestus:dossier_gap",
                dry_run=dry_run, system=_DOSSIER_SYSTEM,
                content=(
                    "Here is a digest of recent StrikeCore dossier outputs plus "
                    "evidence extracted from their COMPLETE verbose transcripts. "
                    "Assess and prioritise the gaps and recommend fixes. If you "
                    "respond as JSON, use {\"gaps\":[{\"category\",\"severity\","
                    "\"evidence\",\"proposed_fix_kind\",\"proposed_fix\"}]}.\n\n"
                    + digest + log_evidence))
        else:
            rep.info("no dossier outputs found — nothing to improve yet")

        # Merge LLM-parsed gaps (if any) on top of the heuristic backbone.
        gaps = list(heuristic_gaps)
        parsed = _parse_json_obj(assessment)
        if parsed and isinstance(parsed.get("gaps"), list):
            for g in parsed["gaps"]:
                norm = _normalise_gap(g)
                if norm and norm["category"] not in {x["category"] for x in gaps}:
                    gaps.append(norm)

        if gaps:
            rep.info("detected " + str(len(gaps)) + " gap(s): "
                     + ", ".join(f"{g['category']}[{g['severity']}/{g['proposed_fix_kind']}]"
                                 for g in gaps[:6]))

        # 3) Research — routed call per top gap; discovery for tool-kind gaps.
        rep.phase("research")
        research: list[dict] = []
        candidates: list[dict] = []
        for g in gaps[: depth + 1]:
            text = await self._stream(
                rep, label=f"research: {g['category']}", task_type="hephaestus:research",
                dry_run=dry_run,
                content=(f"How should StrikeCore close this dossier-mode gap? "
                         f"category={g['category']} severity={g['severity']} "
                         f"evidence={g.get('evidence','')}. Give concrete steps."))
            claim = "improvement reviewed" if dry_run else _first_line(text)
            research.append({"claim": f"{g['category']}: {claim}",
                             "source": "dossieroutputs", "kind": "recommendation"})
            if g["proposed_fix_kind"] == "tool":
                for c in discovery.discover(g["category"], limit=2, dry_run=dry_run):
                    if c["name"] not in {x["name"] for x in candidates}:
                        candidates.append(c)

        # 4) Decision — tool gaps -> gated build decisions; others -> proposals only.
        rep.phase("decision")
        decisions: list[dict] = []
        for g in gaps:
            if g["proposed_fix_kind"] != "tool":
                continue
            cand = next((c["name"] for c in candidates), None) or f"{g['category']}-collector"
            decisions.append({
                "candidate": cand, "action": "write",
                "rationale": (f"Close dossier-mode gap '{g['category']}' "
                              f"({g['severity']}): {g.get('proposed_fix','build a collector')}"),
            })

        if decisions:
            rep.info(f"proposed {len(decisions)} gated tool fix(es); "
                     f"{sum(1 for g in gaps if g['proposed_fix_kind'] != 'tool')} "
                     f"prompt/flow/config proposal(s) for review")

        # 5) Write the improvement-plan artifact (human-readable; surfaced, not applied).
        plan_path = _write_improvement_plan(run_id, gaps, assessment, len(runs))

        gap_analysis = {
            "covered": sorted({d for r in runs for d in _domains_of(r)}),
            "gaps": [g["category"] for g in gaps],
            "target_gap": focus_category,
        }
        dossier_gap_analysis = {
            "outputs_considered": len(runs),
            "improvement_plan_path": str(plan_path),
            "gaps": gaps,
            "log_ingestion": log_summaries,
        }
        return {"candidates": candidates, "research": research,
                "gap_analysis": gap_analysis, "decisions": decisions,
                "dossier_gap_analysis": dossier_gap_analysis}


# ----------------------------------------------------------------------
# Dossier-output analysis helpers (deterministic)
# ----------------------------------------------------------------------
_FAILURE_RE = re.compile(r"(error|failed|not found|timed out|traceback|rate.?limit)", re.I)


def _domains_of(run: dict) -> list[str]:
    """Domains that produced findings in this captured dossier output."""
    dj = run.get("dossier") or {}
    fbd = dj.get("findings_by_domain")
    if isinstance(fbd, dict):
        return [k for k, v in fbd.items() if v]
    raw = dj.get("raw_dossier") or {}
    if isinstance(raw.get("findings_by_domain"), dict):
        return [k for k, v in raw["findings_by_domain"].items() if v]
    return []


def _normalise_gap(g: Any) -> dict | None:
    if not isinstance(g, dict) or not g.get("category"):
        return None
    sev = str(g.get("severity", "medium")).lower()
    if sev not in ("low", "medium", "high"):
        sev = "medium"
    kind = str(g.get("proposed_fix_kind", "prompt/flow"))
    if kind not in ("tool", "prompt/flow", "config"):
        kind = "prompt/flow"
    return {
        "category": str(g["category"])[:80],
        "severity": sev,
        "evidence": str(g.get("evidence", ""))[:400],
        "proposed_fix_kind": kind,
        "proposed_fix": str(g.get("proposed_fix", ""))[:400],
    }


def _heuristic_dossier_gaps(runs: list[dict]) -> list[dict]:
    """Deterministic gaps from captured outputs (the LLM only refines these)."""
    gaps: list[dict] = []
    if not runs:
        return gaps

    # a) Domain-coverage gaps: expected domains absent across all runs.
    seen = {d for r in runs for d in _domains_of(r)}
    for dom in _EXPECTED_DOMAINS:
        if dom not in seen:
            gaps.append({
                "category": f"domain-coverage:{dom}",
                "severity": "high" if dom in ("socint", "webint") else "medium",
                "evidence": f"No {dom} findings across {len(runs)} dossier output(s).",
                "proposed_fix_kind": "tool",
                "proposed_fix": f"Add/strengthen a {dom} collector so dossier mode covers it.",
            })

    # b) Confidence-doctrine flags: >0.7 confidence on a single source.
    doctrine_hits = 0
    for r in runs:
        for f in _iter_findings(r):
            conf = _as_float(f.get("confidence"))
            srcs = f.get("independent_sources")
            if srcs is None:
                srcs = len(f.get("sources", []) or [])
            if conf > 0.7 and (srcs or 0) < 2:
                doctrine_hits += 1
    if doctrine_hits:
        gaps.append({
            "category": "confidence-doctrine",
            "severity": "high",
            "evidence": f"{doctrine_hits} finding(s) exceed 0.7 confidence on a single source (CLAUDE.md section 2.4).",
            "proposed_fix_kind": "prompt/flow",
            "proposed_fix": "Tighten cross-validation before confidence is assigned in dossier synthesis.",
        })

    # c) Tool-failure signals from the captured transcripts.
    failing = 0
    for r in runs:
        try:
            log = r["log_path"].read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(_FAILURE_RE.search(line) for line in log.splitlines()):
            failing += 1
    if failing:
        gaps.append({
            "category": "tool-failure",
            "severity": "medium",
            "evidence": f"Failure/error markers in {failing}/{len(runs)} dossier transcript(s).",
            "proposed_fix_kind": "config",
            "proposed_fix": "Review failing tools (wrappers/keys/proxy) flagged in output.log.",
        })

    # d) Empty-section gap: dossiers missing BLUF / key judgments.
    empties = 0
    for r in runs:
        dj = r.get("dossier") or {}
        raw = dj.get("raw_dossier") if isinstance(dj.get("raw_dossier"), dict) else dj
        if not (raw.get("bluf") or raw.get("key_judgments")):
            empties += 1
    if empties:
        gaps.append({
            "category": "empty-sections",
            "severity": "medium",
            "evidence": f"{empties}/{len(runs)} dossier(s) missing BLUF or key judgments.",
            "proposed_fix_kind": "prompt/flow",
            "proposed_fix": "Ensure synthesis always emits BLUF + key judgments, even on sparse data.",
        })
    return gaps


def _iter_findings(run: dict):
    dj = run.get("dossier") or {}
    raw = dj.get("raw_dossier") if isinstance(dj.get("raw_dossier"), dict) else dj
    fbd = raw.get("findings_by_domain")
    if isinstance(fbd, dict):
        for items in fbd.values():
            if isinstance(items, list):
                for f in items:
                    if isinstance(f, dict):
                        yield f


def _as_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _digest_outputs(runs: list[dict]) -> str:
    """Compact, bounded text digest of captured dossier outputs for the LLM.

    Covers the same run set as the log map step (all runs in the ``outputs_limit``
    window); the final ``[:6000]`` still bounds the digest length.
    """
    lines: list[str] = [f"dossier_outputs: {len(runs)}"]
    for r in runs:
        meta = r.get("meta") or {}
        domains = _domains_of(r)
        n_find = sum(1 for _ in _iter_findings(r))
        lines.append(
            f"- source={meta.get('source','?')} target={meta.get('target','?')} "
            f"domains={domains or '[]'} findings={n_find}")
    return "\n".join(lines)[:6000]


def _format_log_evidence(summaries: list[dict]) -> str:
    """Render per-run log evidence for the reduce-tier gap analysis call.

    Bounded to ``_MAX_LOG_EVIDENCE`` chars so the reduce call stays cost-aware
    even when many transcripts are ingested. Empty-log runs are omitted.
    """
    blocks: list[str] = []
    for s in summaries:
        if not s.get("summary"):
            continue
        blocks.append(f"[{s['run']}] ({s['log_chars']} chars)\n{s['summary']}")
    if not blocks:
        return ""
    body = "\n\n".join(blocks)[:_MAX_LOG_EVIDENCE]
    return ("\n\nPER-RUN LOG EVIDENCE (extracted from the COMPLETE transcripts):\n"
            + body)


def _write_improvement_plan(run_id: str, gaps: list[dict], assessment: str,
                            n_runs: int) -> Path:
    """Write the human-readable improvement plan artifact; return its path."""
    _IMPROVE_DIR.mkdir(parents=True, exist_ok=True)
    path = _IMPROVE_DIR / f"{run_id}.md"
    out = [
        f"# Hephaestus dossier-mode improvement plan — {run_id}",
        "",
        f"_Generated {_now()} from {n_runs} captured dossier output(s)._",
        "",
        "Proposals are SURFACED, not auto-applied. Tool/code changes go through "
        "the H1/H3 sandbox gate and `bin/sc-registry.py`; prompt/flow/config "
        "changes are for operator review (NL_SYSTEM_PROMPT stays preserved).",
        "",
        "## Detected gaps",
        "",
    ]
    if not gaps:
        out.append("_No gaps detected._")
    for g in gaps:
        out.append(f"### [{g['severity'].upper()}] {g['category']}  ({g['proposed_fix_kind']})")
        if g.get("evidence"):
            out.append(f"- evidence: {g['evidence']}")
        if g.get("proposed_fix"):
            out.append(f"- proposed fix: {g['proposed_fix']}")
        out.append("")
    if assessment.strip():
        out += ["## Analyst assessment", "", assessment.strip(), ""]
    try:
        path.write_text("\n".join(out), encoding="utf-8")
    except OSError:
        pass
    return path
