# Hephaestus Native Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Hephaestus a first-class StrikeCore console command, enforce Hephaestus-mediated tool integration at the registry (GR5), and embed a Hephaestus page in the legacy Flask dashboard.

**Architecture:** Extract the `run/status/report/approve` logic out of `bin/hephaestus.py` into a shared `hephaestus/cli_core.py`; both the CLI and a new `_cmd_hephaestus` console command call it. Add a provenance gate to `bin/sc-registry.py:cmd_register`. Add a read-only `/hephaestus` route to `osint_agent/dashboard/app.py`. All LLM calls keep flowing through the GR3 router under the `hephaestus` profile.

**Tech Stack:** Python 3.13, asyncio, argparse, prompt_toolkit (completer), Rich (console), Flask (legacy dashboard), pytest.

**Decisions locked from the spec + codebase recon:**
- The manifest field is **top-level `added_by`** (not `provenance.added_by`); `provenance.first_party` is a sub-field. GR5 keys off `added_by`.
- `cf-validate` already has `added_by: "hephaestus"` and the runtime index is currently empty — the gate breaks nothing existing.
- GR5 allows a registration if: `added_by` starts with `hephaestus` **OR** the tool is already in the index (grandfather) **OR** `--operator-override "<reason>"` is supplied (audited). Everything else is REFUSED.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `hephaestus/cli_core.py` | Single source of truth for run/status/report/approve logic + formatting; no `print`/`sys.exit`/argparse | **Create** |
| `bin/hephaestus.py` | Thin argparse + exit-code CLI over `cli_core` | **Modify** |
| `cli/shell.py` | `_cmd_hephaestus` command, dispatch entry, `_ALL_COMMANDS`, `_COMMAND_HELP`, completer | **Modify** |
| `bin/sc-registry.py` | GR5 provenance gate in `cmd_register` + `--operator-override` arg + `cmd_index` Namespace fix | **Modify** |
| `osint_agent/dashboard/app.py` | Read-only `/hephaestus` route + nav entry | **Modify** |
| `CLAUDE.md` | §14 GR5 + console command prose | **Modify** |
| `docs/HEPHAESTUS.md` | Console invocation as primary path | **Modify** |
| `docs/HEPHAESTUS_CHANGES.md` | Changelog entry | **Modify** |
| `tests/test_hephaestus_cli_core.py` | cli_core unit tests | **Create** |
| `tests/test_hephaestus_console.py` | console command dispatch tests | **Create** |
| `tests/test_registry_gr5.py` | GR5 gate tests | **Create** |
| `tests/test_dashboard_hephaestus.py` | dashboard route smoke test | **Create** |

Run all tests with: `cd /root/strikecore && python3 -m pytest tests/ -q`

---

## Task 1: Shared CLI core — `hephaestus/cli_core.py`

**Files:**
- Create: `hephaestus/cli_core.py`
- Test: `tests/test_hephaestus_cli_core.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hephaestus_cli_core.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/strikecore && python3 -m pytest tests/test_hephaestus_cli_core.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'hephaestus.cli_core'`

- [ ] **Step 3: Write `hephaestus/cli_core.py`**

```python
"""Shared core for the Hephaestus surfaces (CLI + console command).

Pure logic + formatting — no argparse, no sys.exit, no print. Both
bin/hephaestus.py and cli/shell.py:_cmd_hephaestus call into here so the
run/status/report/approve behaviour lives in exactly one place. All LLM calls
flow through the GR3 cost-aware router under the 'hephaestus' profile.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hephaestus import run_record
from hephaestus.agent import Hephaestus

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


def build_router(dry_run: bool):
    from core.provider_router import ProviderRouter
    try:
        from config.settings import get_settings
        return ProviderRouter(get_settings())
    except Exception:
        return ProviderRouter(_MiniSettings(dry_run))


def fmt_usd(micros: int) -> str:
    return f"${micros / 1_000_000:.4f}"


def audit(event: str, run_id: str, payload: dict) -> None:
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


def summary_lines(rec: dict) -> list[str]:
    """Render a run record to plain text lines (surface-agnostic)."""
    out = [
        f"run {rec['run_id']}  status={rec['status']}  "
        f"focus={rec['params']['focus_category']}  "
        f"profile={rec['routing']['profile']} lethality={rec['routing']['lethality']}"
        f"{' (dry-run)' if rec['params']['dry_run'] else ''}",
        f"  candidates: {len(rec['candidates'])}  "
        f"decisions: {len(rec['decisions'])}  "
        f"pending gates: {len(rec['pending_approvals'])}",
        "  model usage / cost:",
    ]
    for u in sorted(rec["model_usage"], key=lambda r: -r["cost_micros"]):
        out.append(f"    {u['task_type']:<22} -> {u['model']:<18} "
                   f"{u['calls']:>2} call(s)  {fmt_usd(u['cost_micros'])}  [{u.get('reason','')}]")
    t = rec["totals"]
    out.append(f"  TOTAL: {t['calls']} call(s)  {fmt_usd(t['cost_usd_micros'])}")
    for p in rec["pending_approvals"]:
        out.append(f"  PENDING {p['gate']}: {p['reason']}")
    return out


def decision_lines(rec: dict) -> list[str]:
    if not rec.get("decisions"):
        return []
    out = ["  decisions:"]
    for d in rec["decisions"]:
        out.append(f"    {d['action']:<10} {d['candidate']}  - {d['rationale']}")
    return out


def run_pass(*, focus: str, depth: int, dry_run: bool,
             profile: str, lethality: str) -> dict[str, Any]:
    """Execute one R&D pass and return the run record. Raises on agent error."""
    router = build_router(dry_run)
    agent = Hephaestus(router)
    rec = asyncio.run(agent.run(
        focus_category=focus, depth=depth, dry_run=dry_run,
        profile=profile, lethality=lethality))
    audit("run", rec["run_id"], {"status": rec["status"],
                                 "cost_micros": rec["totals"]["cost_usd_micros"]})
    return rec


def list_runs() -> list[dict]:
    """Parsed run records (order as run_record.list_runs)."""
    out: list[dict] = []
    for p in run_record.list_runs():
        try:
            out.append(json.loads(p.read_text()))
        except Exception:
            continue
    return out


def get_run(run_id: str | None) -> dict | None:
    """Specific run by id, or the most recent if run_id is None."""
    if run_id:
        path = run_record.RUNS_DIR / f"{run_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())
    runs = run_record.list_runs()
    return json.loads(runs[0].read_text()) if runs else None


def run_record_path(run_id: str) -> Path:
    return run_record.RUNS_DIR / f"{run_id}.json"


def approve_gate(run_id: str, gate: str) -> dict[str, Any]:
    """Clear a pending H1/H3 gate. Returns {ok, error, remaining}."""
    path = run_record.RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        return {"ok": False, "error": f"no such run: {run_id}", "remaining": 0}
    rec = json.loads(path.read_text())
    remaining = [p for p in rec["pending_approvals"] if p["gate"] != gate]
    approved = [p for p in rec["pending_approvals"] if p["gate"] == gate]
    if not approved:
        return {"ok": False, "error": f"no pending {gate} gate on run {run_id}",
                "remaining": len(remaining)}
    rec["pending_approvals"] = remaining
    rec.setdefault("git_actions", []).append(
        {"action": f"gate_approved:{gate}",
         "detail": f"operator approved {gate} for {approved[0].get('candidate','')}"})
    if not remaining:
        rec["status"] = "completed"
    run_record.save(rec)
    audit("approve", run_id, {"gate": gate})
    return {"ok": True, "error": None, "remaining": len(remaining)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/strikecore && python3 -m pytest tests/test_hephaestus_cli_core.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
cd /root/strikecore
git add hephaestus/cli_core.py tests/test_hephaestus_cli_core.py
git commit -m "feat(hephaestus): shared cli_core for run/status/report/approve

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Refactor `bin/hephaestus.py` onto `cli_core`

**Files:**
- Modify: `bin/hephaestus.py` (replace the duplicated helpers + cmd bodies with cli_core calls; keep argparse + exit codes)
- Test: reuse existing behavior via a CLI smoke test in `tests/test_hephaestus_console.py` (Task 3) — here just verify no regression manually.

- [ ] **Step 1: Replace the body of `bin/hephaestus.py`**

Keep the module docstring (lines 1–14) and the `sys.path` shim (lines 26–28). Replace everything from the imports through `cmd_approve` with cli_core-backed commands. New file body:

```python
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
```

- [ ] **Step 2: Verify the CLI still runs (dry-run smoke)**

Run: `cd /root/strikecore && python3 bin/hephaestus.py status; echo "exit=$?"`
Expected: prints existing runs or `(no Hephaestus runs yet)`, `exit=0`. No traceback.

- [ ] **Step 3: Commit**

```bash
cd /root/strikecore
git add bin/hephaestus.py
git commit -m "refactor(hephaestus): bin CLI now delegates to cli_core (no behavior change)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Native console command `hephaestus`

**Files:**
- Modify: `cli/shell.py` — add `_cmd_hephaestus`, register in `_commands` (both `hephaestus` and `/hephaestus`), add to `_ALL_COMMANDS` and `_COMMAND_HELP`, add completer sub-command hints.
- Test: `tests/test_hephaestus_console.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hephaestus_console.py
import importlib
import pytest
from cli import shell as shell_mod
from hephaestus import cli_core


def _bare_shell():
    # Avoid heavy __init__ (settings/NLP); we only test the command method.
    return shell_mod.StrikeCoreShell.__new__(shell_mod.StrikeCoreShell)


def test_command_registered():
    assert "hephaestus" in shell_mod.StrikeCoreShell._commands
    assert "/hephaestus" in shell_mod.StrikeCoreShell._commands
    assert "hephaestus" in shell_mod._ALL_COMMANDS


def test_help_table_has_hephaestus():
    cmds = {row[0] for row in shell_mod._COMMAND_HELP}
    assert "hephaestus" in cmds


def test_status_subcommand_lists_runs(monkeypatch, capsys):
    monkeypatch.setattr(cli_core, "list_runs", lambda: [
        {"run_id": "heph-1", "status": "completed",
         "params": {"focus_category": "voip"},
         "totals": {"cost_usd_micros": 1200},
         "started_at": "2026-06-12T00:00:00+00:00",
         "pending_approvals": []}
    ])
    sh = _bare_shell()
    sh._cmd_hephaestus(["status"])
    out = capsys.readouterr().out
    assert "heph-1" in out and "voip" in out


def test_run_subcommand_requires_focus(monkeypatch, capsys):
    sh = _bare_shell()
    sh._cmd_hephaestus(["run"])  # missing --focus
    out = capsys.readouterr().out
    assert "focus" in out.lower()


def test_approve_reports_error(monkeypatch, capsys):
    monkeypatch.setattr(cli_core, "approve_gate",
                        lambda rid, gate: {"ok": False, "error": "no such run: x", "remaining": 0})
    sh = _bare_shell()
    sh._cmd_hephaestus(["approve", "x", "H1"])
    out = capsys.readouterr().out
    assert "no such run" in out
```

Note: the command writes via Rich `console`; `capsys` captures it because Rich's module-level `console` writes to stdout.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/strikecore && python3 -m pytest tests/test_hephaestus_console.py -q`
Expected: FAIL — `KeyError`/`AssertionError` (`hephaestus` not in `_commands`) and `AttributeError: _cmd_hephaestus`.

- [ ] **Step 3: Add `hephaestus` to `_ALL_COMMANDS`**

In `cli/shell.py`, in the `_ALL_COMMANDS` list (around line 60), add `"hephaestus"` after `"/model"`:

```python
    "model",
    "/model",
    "hephaestus",
    "tools",
```

- [ ] **Step 4: Add help rows to `_COMMAND_HELP`**

In `cli/shell.py`, in `_COMMAND_HELP` (around line 83), after the `/model` rows and before `("tools", ...)`, add:

```python
    ("hephaestus", "", "Toolsmith status + pending sandbox gates (alias /hephaestus)"),
    ("hephaestus", "run --focus <cat>", "Run a discovery/research/decide pass [--depth N --dry-run --lethality L]"),
    ("hephaestus", "report [run_id]", "Print a run report (latest if omitted)"),
    ("hephaestus", "approve <run_id> <H1|H3>", "Clear a pending sandbox gate"),
```

- [ ] **Step 5: Add the `_cmd_hephaestus` method**

In `cli/shell.py`, add this method next to `_cmd_model_router` (anywhere in the `StrikeCoreShell` class body before the `_commands` dict). It hand-parses the token list (consistent with other shell commands) and renders via `console`:

```python
    def _cmd_hephaestus(self, args: List[str]) -> None:
        """hephaestus — native StrikeCore toolsmith (alias /hephaestus).

        hephaestus                          show recent runs + pending gates
        hephaestus run --focus <cat> [--depth N] [--dry-run] [--lethality L]
        hephaestus status                   list past runs + cost
        hephaestus report [run_id]          run report (latest if omitted)
        hephaestus approve <run_id> <H1|H3> clear a pending sandbox gate
        """
        from hephaestus import cli_core

        sub = args[0].lower() if args else "status"

        if sub in ("status", "show", ""):
            runs = cli_core.list_runs()
            if not runs:
                console.print(f"[{THEME['muted']}](no Hephaestus runs yet) — "
                              f"try: hephaestus run --focus <category>[/{THEME['muted']}]")
                return
            console.print(f"[{THEME['accent']}]Hephaestus runs[/{THEME['accent']}]")
            for r in runs:
                console.print(f"  {r['run_id']}  {r['status']:<10} "
                              f"{r['params']['focus_category']:<16} "
                              f"{cli_core.fmt_usd(r['totals']['cost_usd_micros'])}  {r['started_at']}")
            pending = [(r["run_id"], p) for r in runs for p in r.get("pending_approvals", [])]
            for rid, p in pending:
                console.print(f"  [{THEME['warning']}]PENDING {p['gate']} on {rid}: "
                              f"{p['reason']}  →  hephaestus approve {rid} {p['gate']}[/{THEME['warning']}]")
            return

        if sub == "run":
            focus = self._flag_value(args, "--focus")
            if not focus:
                console.print(f"[{THEME['warning']}]Usage: hephaestus run --focus <category> "
                              f"[--depth N] [--dry-run] [--lethality economy|balanced|max][/{THEME['warning']}]")
                return
            depth = int(self._flag_value(args, "--depth") or 1)
            dry_run = "--dry-run" in args
            lethality = self._flag_value(args, "--lethality") or "balanced"
            console.print(f"[{THEME['muted']}]Hephaestus: focus={focus} depth={depth} "
                          f"lethality={lethality}{' (dry-run)' if dry_run else ''} …[/{THEME['muted']}]")
            try:
                rec = cli_core.run_pass(focus=focus, depth=depth, dry_run=dry_run,
                                        profile="hephaestus", lethality=lethality)
            except Exception as exc:  # noqa: BLE001
                console.print(f"[{THEME['error']}]hephaestus run failed: {exc}[/{THEME['error']}]")
                return
            for line in cli_core.summary_lines(rec):
                console.print(line)
            console.print(f"[{THEME['muted']}]run record: "
                          f"{cli_core.run_record_path(rec['run_id'])}[/{THEME['muted']}]")
            return

        if sub == "report":
            run_id = args[1] if len(args) > 1 else None
            rec = cli_core.get_run(run_id)
            if rec is None:
                console.print(f"[{THEME['warning']}]no such run: {run_id or '(latest)'}[/{THEME['warning']}]")
                return
            for line in cli_core.summary_lines(rec) + cli_core.decision_lines(rec):
                console.print(line)
            return

        if sub == "approve":
            if len(args) < 3 or args[2] not in ("H1", "H3"):
                console.print(f"[{THEME['warning']}]Usage: hephaestus approve <run_id> <H1|H3>[/{THEME['warning']}]")
                return
            res = cli_core.approve_gate(args[1], args[2])
            if not res["ok"]:
                console.print(f"[{THEME['warning']}]{res['error']}[/{THEME['warning']}]")
                return
            console.print(f"[{THEME['success']}]approved {args[2]} for run {args[1]}; "
                          f"{res['remaining']} gate(s) still pending.[/{THEME['success']}]")
            return

        console.print(f"[{THEME['warning']}]Unknown: hephaestus {sub}. "
                      f"Try: status | run | report | approve[/{THEME['warning']}]")

    @staticmethod
    def _flag_value(args: List[str], flag: str) -> str | None:
        """Return the token following `flag` in args, or None."""
        if flag in args:
            i = args.index(flag)
            if i + 1 < len(args):
                return args[i + 1]
        return None
```

- [ ] **Step 6: Register in the `_commands` dispatch table**

In `cli/shell.py` `_commands` dict (around line 1248), add both keys after `"/model": _cmd_model_router,`:

```python
        "/model": _cmd_model_router,
        "hephaestus": _cmd_hephaestus,
        "/hephaestus": _cmd_hephaestus,
```

- [ ] **Step 7: Add completer sub-command hints**

In `cli/shell.py` `StrikeCoreCompleter.get_completions`, after the `elif cmd == "model" ...` block (around line 180), add:

```python
        elif cmd in ("hephaestus", "/hephaestus") and word_count == 2:
            for sub in ("run", "status", "report", "approve"):
                if sub.startswith(prefix):
                    yield Completion(sub, start_position=start_pos)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd /root/strikecore && python3 -m pytest tests/test_hephaestus_console.py -q`
Expected: PASS (5 passed)

- [ ] **Step 9: Commit**

```bash
cd /root/strikecore
git add cli/shell.py tests/test_hephaestus_console.py
git commit -m "feat(cli): native 'hephaestus' console command (alias /hephaestus)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: GR5 — Hephaestus-mediated registration gate

**Files:**
- Modify: `bin/sc-registry.py` — `cmd_register` provenance gate, `--operator-override` arg, `cmd_index` Namespace fix.
- Test: `tests/test_registry_gr5.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_registry_gr5.py
import json
import importlib
import pytest

reg = importlib.import_module("bin.sc-registry") if False else None
# bin/sc-registry.py is not importable by module name (hyphen); load by path.
import importlib.util
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("sc_registry", _REPO / "bin" / "sc-registry.py")
sc_registry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc_registry)


def _manifest(name, added_by):
    return {
        "name": name, "version": "0.1.0", "category": "socint",
        "capabilities": ["x"], "entrypoint": "sc-x.py",
        "provenance": {"upstream_url": "https://example/x", "pinned_commit": "abc1234"},
        "added_by": added_by, "gate_approved": True,
        "io": {"input_schema": "schema/io.envelope.schema.json",
               "output_envelope": "schema/io.envelope.schema.json"},
    }


def _write_tool(tmp_path, name, added_by):
    d = tmp_path / name
    d.mkdir()
    (d / "tool.manifest.json").write_text(json.dumps(_manifest(name, added_by)))
    return d


def _args(target, override=None, force_pending=False):
    import argparse
    return argparse.Namespace(target=str(target), operator_override=override,
                              force_pending=force_pending)


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(sc_registry, "_INDEX_PATH", tmp_path / "index.json", raising=False)
    monkeypatch.setattr(sc_registry, "_AUDIT_DIR", tmp_path / "audit", raising=False)
    # bypass strict schema validation; we test the GR5 gate, not the schema
    monkeypatch.setattr(sc_registry, "_validate_manifest", lambda m: [])


def test_hephaestus_originated_registers(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    d = _write_tool(tmp_path, "tool-h", "hephaestus")
    rc = sc_registry.cmd_register(_args(d))
    assert rc == sc_registry.EXIT_OK
    assert "REGISTERED" in capsys.readouterr().out


def test_non_hephaestus_refused(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    d = _write_tool(tmp_path, "tool-o", "operator")
    rc = sc_registry.cmd_register(_args(d))
    assert rc == sc_registry.EXIT_NOTFOUND
    err = capsys.readouterr().err
    assert "GR5" in err or "hephaestus" in err.lower()


def test_operator_override_registers_and_audits(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    events = []
    monkeypatch.setattr(sc_registry, "_audit",
                        lambda ev, name, payload: events.append((ev, name, payload)))
    d = _write_tool(tmp_path, "tool-o2", "operator")
    rc = sc_registry.cmd_register(_args(d, override="manual first-party import"))
    assert rc == sc_registry.EXIT_OK
    assert any(ev == "register_override" for ev, _, _ in events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/strikecore && python3 -m pytest tests/test_registry_gr5.py -q`
Expected: FAIL — `test_non_hephaestus_refused` fails (currently registers; rc==EXIT_OK) and `--operator-override`/`operator_override` attr missing.

- [ ] **Step 3: Add the GR5 gate to `cmd_register`**

In `bin/sc-registry.py`, in `cmd_register` (lines 222–256), insert the gate **after** the existing `gate_approved` refusal block and **before** `pending = not gate`. Replace:

```python
    pending = not gate  # registered but inactive
    index = _load_index()
    entry = _entry_from_manifest(manifest, mp, pending)
```

with:

```python
    # GR5 — Hephaestus-mediated integration. New tools must originate from a
    # Hephaestus run unless the operator explicitly overrides (audited).
    index = _load_index()
    already_registered = manifest["name"] in index.get("tools", {})
    added_by = str(manifest.get("added_by", "")).strip().lower()
    heph_originated = added_by.startswith("hephaestus")
    override = getattr(args, "operator_override", None)
    if not heph_originated and not already_registered and not override:
        print(
            f"REFUSED: {manifest['name']} violates GR5 (Hephaestus-mediated "
            f"integration): added_by={added_by or '∅'} is not a Hephaestus run. "
            f"Run it through the toolsmith (console: hephaestus run --focus <cat>) "
            f"or re-run with --operator-override \"<reason>\".",
            file=sys.stderr,
        )
        _audit("register_refused", manifest["name"],
               {"reason": "gr5_not_hephaestus_originated", "added_by": added_by})
        return EXIT_NOTFOUND
    if override and not heph_originated and not already_registered:
        _audit("register_override", manifest["name"],
               {"reason": str(override), "added_by": added_by})

    pending = not gate  # registered but inactive
    entry = _entry_from_manifest(manifest, mp, pending)
```

- [ ] **Step 4: Add the `--operator-override` arg + fix `cmd_index` Namespace**

In `bin/sc-registry.py` `main()`, in the `register` sub-parser (around line 323), add the argument:

```python
    sr.add_argument("target")
    sr.add_argument("--force-pending", action="store_true",
                    help="record a gate_approved=false tool as inactive/pending")
    sr.add_argument("--operator-override", default=None, metavar="REASON",
                    help="GR5 escape hatch: register a non-Hephaestus-originated "
                         "tool; REASON is written to the audit chain")
    sr.set_defaults(func=cmd_register)
```

In `cmd_index` (around line 300), update the Namespace so re-scan registrations carry the attr:

```python
        ns = argparse.Namespace(target=str(child), force_pending=False,
                                operator_override=None)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /root/strikecore && python3 -m pytest tests/test_registry_gr5.py -q`
Expected: PASS (3 passed)

- [ ] **Step 6: Verify the reference tool still registers (real manifest, real schema)**

Run: `cd /root/strikecore && python3 bin/sc-registry.py register tools/cf-validate; echo "exit=$?"`
Expected: `REGISTERED: cf-validate ...`, `exit=0` (cf-validate is `added_by: hephaestus`).
Then deregister to leave the index clean: `python3 bin/sc-registry.py deregister cf-validate`

- [ ] **Step 7: Commit**

```bash
cd /root/strikecore
git add bin/sc-registry.py tests/test_registry_gr5.py
git commit -m "feat(registry): GR5 Hephaestus-mediated integration gate (+ --operator-override)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Embed Hephaestus page in the legacy dashboard

**Files:**
- Modify: `osint_agent/dashboard/app.py` — add `active_hephaestus` to `_render`, a nav entry in `SIDEBAR`, and a `/hephaestus` route.
- Test: `tests/test_dashboard_hephaestus.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dashboard_hephaestus.py
import importlib.util
from pathlib import Path
import pytest

_REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "sc_dashboard", _REPO / "osint_agent" / "dashboard" / "app.py")
dash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dash)


@pytest.fixture
def client():
    dash.app.config["TESTING"] = True
    return dash.app.test_client()


def test_hephaestus_route_ok_when_empty(client, monkeypatch, tmp_path):
    monkeypatch.setattr(dash, "_HEPH_RUNS_DIR", tmp_path / "empty", raising=False)
    resp = client.get("/hephaestus")
    assert resp.status_code == 200
    assert b"Hephaestus" in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/strikecore && python3 -m pytest tests/test_dashboard_hephaestus.py -q`
Expected: FAIL — 404 (route not defined) so `b"Hephaestus"` assertion / status 200 fails.

- [ ] **Step 3: Add `active_hephaestus` to `_render`**

In `osint_agent/dashboard/app.py` `_render` (around line 254), add a key to the `SIDEBAR %` dict alongside the others:

```python
        "active_voip": _a("voip"),
        "active_hephaestus": _a("hephaestus"),
```

- [ ] **Step 4: Add a nav entry to `SIDEBAR`**

In `osint_agent/dashboard/app.py`, in the `SIDEBAR` template, after the GEOINT `<a>` block (the one with `%(active_geoint)s`, around line 144–148) add a Toolsmith section + link:

```html
    <div class="nav-section" style="margin-top:24px">Toolsmith</div>
    <a href="/hephaestus" class="nav-item %(active_hephaestus)s">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z"/></svg>
      Hephaestus</a>
```

- [ ] **Step 5: Add the `/hephaestus` route**

In `osint_agent/dashboard/app.py`, add a module-level constant near the other `*_DIR` constants (after `AUDIT_DIR`):

```python
_HEPH_RUNS_DIR = Path.home() / ".strikecore" / "hephaestus" / "runs"
```

Then add the route (place it next to `agents_view`, e.g. after the `/agents` route ends, around line 604):

```python
@app.route('/hephaestus')
def hephaestus_view():
    """Read-only Hephaestus toolsmith view — reads run-record JSON directly."""
    runs = []
    if _HEPH_RUNS_DIR.is_dir():
        files = sorted(_HEPH_RUNS_DIR.glob("*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:20]
        for f in files:
            try:
                runs.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                continue

    pending = [(r["run_id"], p) for r in runs for p in r.get("pending_approvals", [])]

    pending_html = ""
    if pending:
        rows = ""
        for rid, p in pending:
            rows += (f'<div class="glass-bright p-3 mb-2 border border-yellow-500/30">'
                     f'<span class="text-yellow-400 font-mono text-xs">{p["gate"]}</span> '
                     f'<span class="text-gray-300 text-xs">on {rid} — {p.get("reason","")}</span>'
                     f'<div class="text-[10px] text-gray-500 mt-1">clear with: '
                     f'<span class="text-cyan-400">hephaestus approve {rid} {p["gate"]}</span></div></div>')
        pending_html = (f'<h2 class="text-sm font-semibold text-yellow-400 mb-2">'
                        f'Pending sandbox gates ({len(pending)})</h2>{rows}')

    if not runs:
        body = ('<div class="glass-bright p-6 text-gray-400 text-sm">'
                'No Hephaestus runs yet. Start one from the console: '
                '<span class="text-cyan-400">hephaestus run --focus &lt;category&gt;</span>.</div>')
    else:
        cards = ""
        for r in runs:
            t = r.get("totals", {})
            usd = f"${t.get('cost_usd_micros', 0) / 1_000_000:.4f}"
            decs = "".join(
                f'<div class="text-[10px] text-gray-400">{d.get("action","")} '
                f'<span class="text-gray-300">{d.get("candidate","")}</span> — {d.get("rationale","")}</div>'
                for d in r.get("decisions", []))
            cards += (
                f'<div class="glass-bright p-4 mb-3">'
                f'<div class="flex items-center justify-between mb-1">'
                f'<span class="text-white font-semibold text-sm">{r["run_id"]}</span>'
                f'<span class="text-[10px] text-gray-500">{r.get("started_at","")}</span></div>'
                f'<div class="text-[10px] text-gray-400 mb-2">'
                f'status <span class="text-gray-200">{r.get("status","")}</span> · '
                f'focus <span class="text-gray-200">{r.get("params",{}).get("focus_category","")}</span> · '
                f'candidates {len(r.get("candidates",[]))} · cost {usd}</div>{decs}</div>')
        body = f'<div class="grid grid-cols-1 lg:grid-cols-2 gap-4"><div>{pending_html}</div><div>{cards}</div></div>'

    content = f'''
    <h1 class="text-xl font-bold text-white mb-1">Hephaestus — Toolsmith</h1>
    <p class="text-xs text-gray-500 mb-6">Native R&amp;D agent · run records read-only · approvals via console/CLI</p>
    {body}
    '''
    return _render("Hephaestus", content, "hephaestus")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /root/strikecore && python3 -m pytest tests/test_dashboard_hephaestus.py -q`
Expected: PASS (1 passed)

- [ ] **Step 7: Commit**

```bash
cd /root/strikecore
git add osint_agent/dashboard/app.py tests/test_dashboard_hephaestus.py
git commit -m "feat(dashboard): embed read-only Hephaestus page in legacy dashboard

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Documentation — GR5 + console command

**Files:**
- Modify: `CLAUDE.md`, `docs/HEPHAESTUS.md`, `docs/HEPHAESTUS_CHANGES.md`

- [ ] **Step 1: Add GR5 + console command to CLAUDE.md §14**

In `CLAUDE.md`, in §14, after the "Hephaestus is a native StrikeCore agent" paragraph, add:

```markdown
### Hephaestus is a mandatory native console command

The StrikeCore console (`cli/shell.py`) exposes **`hephaestus`** (alias
`/hephaestus`) as a first-class command — the mandated interactive path:

- `hephaestus` / `hephaestus status` — recent runs + pending H1/H3 gates
- `hephaestus run --focus <cat> [--depth N] [--dry-run] [--lethality L]`
- `hephaestus report [run_id]`
- `hephaestus approve <run_id> <H1|H3>`

It shares `hephaestus/cli_core.py` with `bin/hephaestus.py` (the CLI remains the
scripting/cron path). All LLM calls route through the GR3 router (`hephaestus`
profile). The legacy dashboard (`osint_agent/dashboard/app.py`) now embeds a
read-only **/hephaestus** page (parity with the `web/` React dashboard).

### GR5 — Hephaestus-mediated integration is MANDATORY

Tool integration MUST be Hephaestus-mediated. `bin/sc-registry.py register`
(the single chokepoint — the `post-receive` hook calls it too) **refuses** any
tool whose `added_by` is not a Hephaestus run, unless the operator passes
`--operator-override "<reason>"`, which is written to the SHA-256 audit chain.
Tools already in the index are grandfathered. This makes the toolsmith the
default path for every new collection capability and keeps an evidence trail
for the exceptions (§7 chain-of-custody).
```

- [ ] **Step 2: Add the console command to docs/HEPHAESTUS.md**

In `docs/HEPHAESTUS.md`, add a section near the top documenting the console command as the primary interactive path and the CLI as the scripting path (mirror the four sub-commands from Step 1).

Run: `cd /root/strikecore && grep -n "Invocation\|## " docs/HEPHAESTUS.md | head` to find the right insertion point, then add:

```markdown
## Invocation

**Console (primary, interactive):** inside the StrikeCore shell —
`hephaestus` · `hephaestus run --focus <cat>` · `hephaestus report [run_id]` ·
`hephaestus approve <run_id> <H1|H3>`. Alias: `/hephaestus`.

**CLI (scripting / cron):** `python3 bin/hephaestus.py run --focus <cat> …`.
Both share `hephaestus/cli_core.py`.
```

- [ ] **Step 3: Append a changelog entry to docs/HEPHAESTUS_CHANGES.md**

Append to `docs/HEPHAESTUS_CHANGES.md`:

```markdown
## 2026-06-12 — Native console command + GR5 + legacy-dashboard embed

- `hephaestus` / `/hephaestus` is now a first-class console command
  (`cli/shell.py`), backed by the new shared `hephaestus/cli_core.py`.
  `bin/hephaestus.py` refactored to delegate to it (no behavior change).
- **GR5 — Hephaestus-mediated integration:** `bin/sc-registry.py register`
  refuses non-Hephaestus-originated tools unless `--operator-override "<reason>"`
  (audited). Existing index entries grandfathered.
- Legacy dashboard (`osint_agent/dashboard/app.py`) gains a read-only
  `/hephaestus` page + nav entry (parity with the `web/` React dashboard).
```

- [ ] **Step 4: Commit**

```bash
cd /root/strikecore
git add CLAUDE.md docs/HEPHAESTUS.md docs/HEPHAESTUS_CHANGES.md
git commit -m "docs(hephaestus): GR5 + native console command + dashboard embed

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Full verification + push to atlas

- [ ] **Step 1: Run the whole new test set**

Run: `cd /root/strikecore && python3 -m pytest tests/test_hephaestus_cli_core.py tests/test_hephaestus_console.py tests/test_registry_gr5.py tests/test_dashboard_hephaestus.py -q`
Expected: all PASS (14 tests).

- [ ] **Step 2: Sanity-check the broader suite didn't regress**

Run: `cd /root/strikecore && python3 -m pytest tests/ -q`
Expected: no new failures vs. baseline (record any pre-existing failures unrelated to this change).

- [ ] **Step 3: Manual console smoke (optional but recommended)**

Run the shell, then: `hephaestus`, `hephaestus run --focus voip --dry-run`, `hephaestus status`, `hephaestus report`. Confirm output renders and a run record appears.

- [ ] **Step 4: Push to atlas**

```bash
cd /root/strikecore && git push origin main
```
Expected: push succeeds (sshpass auth already configured in repo `core.sshCommand`). The `post-receive` hook reports tool changes only if any `tools/` changed (none here) — docs/code only.

---

## Self-Review (completed during planning)

- **Spec coverage:** §3.1 cli_core → Task 1; §3.2 console command → Task 3; §3.3 GR5 gate → Task 4; §3.4 dashboard embed → Task 5; §3.5 docs → Task 6; testing §6 → Tasks 1/3/4/5/7. All covered.
- **Placeholder scan:** none — every code/step block is concrete.
- **Type consistency:** `cli_core` function names (`run_pass`, `list_runs`, `get_run`, `approve_gate`, `summary_lines`, `decision_lines`, `fmt_usd`, `run_record_path`, `audit`) are used identically in Tasks 2 and 3. GR5 reads top-level `added_by` (verified against the real manifest). `_flag_value` is defined in Task 3 Step 5 and used in the same method.
- **Deviation from spec noted:** the spec text said `provenance.added_by`; the real schema field is **top-level `added_by`** — the plan uses the correct field.
```
