#!/usr/bin/env python3
"""StrikeCore Self-Audit — Session-end tool performance analysis.

Reads today's audit JSONL, scores each tool's performance, updates
persistent tool_performance.json, and flags underperformers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.table import Table

console = Console()

AUDIT_DIR = Path.home() / ".strikecore" / "audit"
PERF_FILE = Path.home() / ".strikecore" / "tool_performance.json"


class SelfAudit:
    """Analyze tool performance for the current session."""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id
        self.tool_stats: dict[str, dict] = defaultdict(
            lambda: {"calls": 0, "successes": 0, "failures": 0, "total_duration": 0.0}
        )

    def load_session_events(self) -> list[dict]:
        """Load today's audit JSONL entries."""
        today_file = AUDIT_DIR / f"{date.today().isoformat()}.jsonl"
        if not today_file.exists():
            return []
        events = []
        with open(today_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    events.append(entry)
                except json.JSONDecodeError:
                    continue
        return events

    def analyze(self, events: list[dict]) -> dict[str, dict]:
        """Score each tool from audit events."""
        for event in events:
            details = event.get("details", event)
            cmd = details.get("command", "")
            if not cmd:
                continue

            # Extract tool name from command
            parts = cmd.split()
            tool = parts[0] if parts else "unknown"
            if tool in ("sudo", "proxychains4", "timeout"):
                tool = parts[1] if len(parts) > 1 else tool
            tool = os.path.basename(tool)

            self.tool_stats[tool]["calls"] += 1
            duration = details.get("duration", 0.0)
            self.tool_stats[tool]["total_duration"] += duration

            rc = details.get("return_code", -1)
            if rc == 0:
                self.tool_stats[tool]["successes"] += 1
            else:
                self.tool_stats[tool]["failures"] += 1

        summary = {}
        for tool, stats in self.tool_stats.items():
            calls = stats["calls"]
            summary[tool] = {
                **stats,
                "success_rate": round(stats["successes"] / calls, 2) if calls else 0.0,
                "avg_duration": round(stats["total_duration"] / calls, 2) if calls else 0.0,
            }
        return summary

    def update_performance_file(self, session_summary: dict):
        """Merge session stats into persistent tool_performance.json."""
        existing: dict = {}
        if PERF_FILE.exists():
            try:
                existing = json.loads(PERF_FILE.read_text())
            except Exception:
                pass

        for tool, stats in session_summary.items():
            if tool.startswith("_"):
                continue
            if tool not in existing:
                existing[tool] = {
                    "total_calls": 0, "total_successes": 0,
                    "total_failures": 0, "sessions_used": 0,
                }
            existing[tool]["total_calls"] += stats["calls"]
            existing[tool]["total_successes"] += stats["successes"]
            existing[tool]["total_failures"] += stats["failures"]
            existing[tool]["sessions_used"] += 1
            tc = existing[tool]["total_calls"]
            existing[tool]["lifetime_success_rate"] = round(
                existing[tool]["total_successes"] / tc, 2
            ) if tc > 0 else 0.0

        existing["_last_updated"] = datetime.now().isoformat()
        PERF_FILE.parent.mkdir(parents=True, exist_ok=True)
        PERF_FILE.write_text(json.dumps(existing, indent=2))

    def identify_underperformers(self, summary: dict) -> list[str]:
        """Tools with <50% success rate and >=3 calls this session."""
        return [
            tool for tool, stats in summary.items()
            if stats["calls"] >= 3 and stats["success_rate"] < 0.5
        ]

    def display(self, summary: dict):
        """Render session summary as Rich table."""
        if not summary:
            console.print("[dim]No tool executions found in today's audit log.[/dim]")
            return

        table = Table(
            title="Session Tool Performance",
            title_style="bold bright_white",
            border_style="bright_cyan",
            show_lines=False,
            padding=(0, 1),
        )
        table.add_column("Tool", style="bright_white", min_width=16)
        table.add_column("Calls", justify="right", min_width=6)
        table.add_column("OK", justify="right", style="green", min_width=4)
        table.add_column("Fail", justify="right", style="red", min_width=4)
        table.add_column("Rate", justify="right", min_width=6)
        table.add_column("Avg(s)", justify="right", style="dim", min_width=7)

        for tool, stats in sorted(summary.items(), key=lambda x: -x[1]["calls"]):
            rate = stats["success_rate"]
            if rate >= 0.75:
                rate_str = f"[green]{rate:.0%}[/green]"
            elif rate >= 0.50:
                rate_str = f"[yellow]{rate:.0%}[/yellow]"
            else:
                rate_str = f"[red]{rate:.0%}[/red]"
            table.add_row(
                tool,
                str(stats["calls"]),
                str(stats["successes"]),
                str(stats["failures"]),
                rate_str,
                f"{stats['avg_duration']:.1f}",
            )

        console.print()
        console.print(table)

    def run(self):
        """Full audit: load events, analyze, display, persist."""
        events = self.load_session_events()
        if not events:
            console.print("[dim]Self-audit: no audit entries for today.[/dim]")
            return

        summary = self.analyze(events)
        self.display(summary)
        self.update_performance_file(summary)

        underperformers = self.identify_underperformers(summary)
        if underperformers:
            console.print(
                f"[yellow]Underperforming tools (< 50% success): "
                f"{', '.join(underperformers)}[/yellow]"
            )

        total_calls = sum(s["calls"] for s in summary.values())
        total_ok = sum(s["successes"] for s in summary.values())
        pct = round(total_ok / total_calls * 100, 1) if total_calls else 0
        console.print(
            f"[dim]Session total: {total_calls} tool calls, "
            f"{total_ok} successes ({pct}%)[/dim]"
        )


def main():
    parser = argparse.ArgumentParser(description="StrikeCore session self-audit")
    parser.add_argument("--session", type=str, default=None, help="Filter by session ID")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    audit = SelfAudit(session_id=args.session)
    events = audit.load_session_events()
    summary = audit.analyze(events)

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        audit.display(summary)
        audit.update_performance_file(summary)


if __name__ == "__main__":
    main()
