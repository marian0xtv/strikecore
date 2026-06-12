#!/usr/bin/env python3
"""hephaestus — CLI for the native StrikeCore toolsmith agent (Phase 5).

Subcommands (argparse, mirrors bin/sc-registry.py):
    run     --focus CAT [--depth N] [--dry-run] [--profile P] [--lethality L]
    status                       list past runs (newest first) + cost
    report  [run_id]             print a run report (latest if omitted)
    approve <run_id> <H1|H3>     approve a pending sandbox gate for a run

Every LLM call routes through the shared cost-aware router (GR3). H1/H3 gates
pause the run and are surfaced here + in the dashboard + the console command.
Logic lives in hephaestus/cli_core.py (shared with cli/shell.py).

Exit codes: 0 ok · 1 not-found · 2 usage · 3 internal.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hephaestus import cli_core  # noqa: E402

EXIT_OK, EXIT_NOTFOUND, EXIT_USAGE, EXIT_INTERNAL = 0, 1, 2, 3


def cmd_run(args) -> int:
    try:
        rec = cli_core.run_pass(focus=args.focus, depth=args.depth,
                                dry_run=args.dry_run, profile=args.profile,
                                lethality=args.lethality)
    except Exception as exc:  # noqa: BLE001
        print(f"hephaestus run failed: {exc}", file=sys.stderr)
        return EXIT_INTERNAL
    for line in cli_core.summary_lines(rec):
        print(line)
    print(f"\nrun record: {cli_core.run_record_path(rec['run_id'])}")
    return EXIT_OK


def cmd_status(args) -> int:
    runs = cli_core.list_runs()
    if not runs:
        print("(no Hephaestus runs yet)")
        return EXIT_OK
    for r in runs:
        print(f"{r['run_id']}  {r['status']:<10} {r['params']['focus_category']:<16} "
              f"{cli_core.fmt_usd(r['totals']['cost_usd_micros'])}  {r['started_at']}")
    return EXIT_OK


def cmd_report(args) -> int:
    rec = cli_core.get_run(args.run_id)
    if rec is None:
        target = args.run_id or "(latest)"
        print(f"no such run: {target}", file=sys.stderr)
        return EXIT_NOTFOUND
    for line in cli_core.summary_lines(rec) + cli_core.decision_lines(rec):
        print(line)
    return EXIT_OK


def cmd_approve(args) -> int:
    res = cli_core.approve_gate(args.run_id, args.gate)
    if not res["ok"]:
        print(res["error"], file=sys.stderr)
        return EXIT_NOTFOUND
    print(f"approved {args.gate} for run {args.run_id}; "
          f"{res['remaining']} gate(s) still pending.")
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
