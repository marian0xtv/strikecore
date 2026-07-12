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
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# --- Optional: load .env so ANTHROPIC_API_KEY override works ---------------
# Uses stdlib only to avoid a hard dependency on python-dotenv. Mirrors the
# pattern in bin/intel-team.py / bin/agent-dossier.py so the §8 .env workflow
# (settings.py env-override layer) works for the Hephaestus CLI too.

def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


_load_dotenv(_REPO_ROOT / ".env")

from hephaestus import cli_core  # noqa: E402

EXIT_OK, EXIT_NOTFOUND, EXIT_USAGE, EXIT_INTERNAL = 0, 1, 2, 3


def cmd_run(args) -> int:
    from hephaestus.reporting import StreamReporter
    if not args.fetch_from_outputs and not args.focus:
        print("hephaestus run: provide --focus <category> or --fetch-from-outputs",
              file=sys.stderr)
        return EXIT_USAGE
    focus = args.focus or "dossier-mode"
    try:
        rec = cli_core.run_pass(focus=focus, depth=args.depth,
                                dry_run=args.dry_run, profile=args.profile,
                                lethality=args.lethality,
                                fetch_from_outputs=args.fetch_from_outputs,
                                outputs_limit=args.outputs_limit,
                                reporter=StreamReporter())
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


def cmd_reject(args) -> int:
    res = cli_core.reject_gate(args.run_id, args.gate, args.reason or "")
    if not res["ok"]:
        print(res["error"], file=sys.stderr)
        return EXIT_NOTFOUND
    print(f"rejected {args.gate} for run {args.run_id}; "
          f"{res['remaining']} gate(s) still pending.")
    return EXIT_OK


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="hephaestus",
                                description="StrikeCore toolsmith agent CLI.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="run an R&D discovery/research/decide pass")
    pr.add_argument("--focus", help="OSINT gap category to target "
                    "(optional with --fetch-from-outputs)")
    pr.add_argument("--fetch-from-outputs", action="store_true",
                    help="dossier autoimprove: analyze captured dossier outputs, "
                         "detect gaps, research, and propose gated fixes")
    pr.add_argument("--outputs-limit", type=int, default=10,
                    help="max captured dossier outputs to consider (default 10)")
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

    prj = sub.add_parser("reject", help="reject a pending sandbox gate")
    prj.add_argument("run_id")
    prj.add_argument("gate", choices=["H1", "H3"])
    prj.add_argument("--reason", default="", help="operator reason (audited)")
    prj.set_defaults(func=cmd_reject)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
