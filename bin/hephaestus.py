#!/usr/bin/env python3
"""hephaestus — CLI for the native StrikeCore toolsmith agent (Phase 5).

Subcommands (argparse, mirrors bin/sc-registry.py):
    run     --focus CAT [--depth N] [--dry-run] [--profile P] [--lethality L]
    status                       list past runs (newest first) + cost
    report  [run_id]             print a run report (latest if omitted)
    approve <run_id> <H1|H3>     approve a pending sandbox gate for a run

Every LLM call routes through the shared cost-aware router (GR3). H1/H3 gates
pause the run and are surfaced here + in the dashboard.

Exit codes: 0 ok · 1 not-found · 2 usage · 3 internal.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hephaestus import run_record  # noqa: E402
from hephaestus.agent import Hephaestus  # noqa: E402

EXIT_OK, EXIT_NOTFOUND, EXIT_USAGE, EXIT_INTERNAL = 0, 1, 2, 3
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


def _build_router(dry_run: bool):
    from core.provider_router import ProviderRouter
    try:
        from config.settings import get_settings
        return ProviderRouter(get_settings())
    except Exception:
        return ProviderRouter(_MiniSettings(dry_run))


def _fmt_usd(micros: int) -> str:
    return f"${micros / 1_000_000:.4f}"


def _audit(event: str, run_id: str, payload: dict) -> None:
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


def _print_summary(rec: dict) -> None:
    print(f"run {rec['run_id']}  status={rec['status']}  "
          f"focus={rec['params']['focus_category']}  "
          f"profile={rec['routing']['profile']} lethality={rec['routing']['lethality']}"
          f"{' (dry-run)' if rec['params']['dry_run'] else ''}")
    print(f"  candidates: {len(rec['candidates'])}  "
          f"decisions: {len(rec['decisions'])}  "
          f"pending gates: {len(rec['pending_approvals'])}")
    print("  model usage / cost:")
    for u in sorted(rec["model_usage"], key=lambda r: -r["cost_micros"]):
        print(f"    {u['task_type']:<22} -> {u['model']:<18} "
              f"{u['calls']:>2} call(s)  {_fmt_usd(u['cost_micros'])}  [{u.get('reason','')}]")
    t = rec["totals"]
    print(f"  TOTAL: {t['calls']} call(s)  {_fmt_usd(t['cost_usd_micros'])}")
    for p in rec["pending_approvals"]:
        print(f"  ⏸  {p['gate']} PENDING: {p['reason']}")


def cmd_run(args) -> int:
    router = _build_router(args.dry_run)
    agent = Hephaestus(router)
    try:
        rec = asyncio.run(agent.run(
            focus_category=args.focus, depth=args.depth, dry_run=args.dry_run,
            profile=args.profile, lethality=args.lethality))
    except Exception as exc:  # noqa: BLE001
        print(f"hephaestus run failed: {exc}", file=sys.stderr)
        return EXIT_INTERNAL
    _audit("run", rec["run_id"], {"status": rec["status"],
                                  "cost_micros": rec["totals"]["cost_usd_micros"]})
    _print_summary(rec)
    print(f"\nrun record: {run_record.RUNS_DIR / (rec['run_id'] + '.json')}")
    return EXIT_OK


def cmd_status(args) -> int:
    runs = run_record.list_runs()
    if not runs:
        print("(no Hephaestus runs yet)")
        return EXIT_OK
    for p in runs:
        try:
            r = json.loads(p.read_text())
            print(f"{r['run_id']}  {r['status']:<10} {r['params']['focus_category']:<16} "
                  f"{_fmt_usd(r['totals']['cost_usd_micros'])}  {r['started_at']}")
        except Exception:
            continue
    return EXIT_OK


def cmd_report(args) -> int:
    runs = run_record.list_runs()
    if args.run_id:
        path = run_record.RUNS_DIR / f"{args.run_id}.json"
        if not path.exists():
            print(f"no such run: {args.run_id}", file=sys.stderr)
            return EXIT_NOTFOUND
    elif runs:
        path = runs[0]
    else:
        print("(no runs)", file=sys.stderr)
        return EXIT_NOTFOUND
    rec = json.loads(path.read_text())
    _print_summary(rec)
    if rec["decisions"]:
        print("  decisions:")
        for d in rec["decisions"]:
            print(f"    {d['action']:<10} {d['candidate']}  — {d['rationale']}")
    return EXIT_OK


def cmd_approve(args) -> int:
    path = run_record.RUNS_DIR / f"{args.run_id}.json"
    if not path.exists():
        print(f"no such run: {args.run_id}", file=sys.stderr)
        return EXIT_NOTFOUND
    rec = json.loads(path.read_text())
    remaining = [p for p in rec["pending_approvals"] if p["gate"] != args.gate]
    approved = [p for p in rec["pending_approvals"] if p["gate"] == args.gate]
    if not approved:
        print(f"no pending {args.gate} gate on run {args.run_id}", file=sys.stderr)
        return EXIT_NOTFOUND
    rec["pending_approvals"] = remaining
    rec.setdefault("git_actions", []).append(
        {"action": f"gate_approved:{args.gate}",
         "detail": f"operator approved {args.gate} for {approved[0].get('candidate','')}"})
    if not remaining:
        rec["status"] = "completed"
    run_record.save(rec)
    _audit("approve", args.run_id, {"gate": args.gate})
    print(f"approved {args.gate} for run {args.run_id}; "
          f"{len(remaining)} gate(s) still pending.")
    return EXIT_OK


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="hephaestus",
                                description="StrikeCore toolsmith agent CLI.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="run an R&D discovery/research/decide pass")
    pr.add_argument("--focus", required=True, help="OSINT gap category to target")
    pr.add_argument("--depth", type=int, default=1)
    pr.add_argument("--dry-run", action="store_true",
                    help="no real API calls / no real targets; routing+cost offline")
    pr.add_argument("--profile", default="hephaestus")
    pr.add_argument("--lethality", default="balanced",
                    choices=["economy", "balanced", "max"])
    pr.set_defaults(func=cmd_run)

    ps = sub.add_parser("status", help="list past runs")
    ps.set_defaults(func=cmd_status)

    prep = sub.add_parser("report", help="print a run report (latest if no id)")
    prep.add_argument("run_id", nargs="?")
    prep.set_defaults(func=cmd_report)

    pa = sub.add_parser("approve", help="approve a pending sandbox gate")
    pa.add_argument("run_id")
    pa.add_argument("gate", choices=["H1", "H3"])
    pa.set_defaults(func=cmd_approve)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
