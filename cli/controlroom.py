"""StrikeCore Control Room — an htop-style live view of all agents.

Reads the unified live event bus (``core.agent_events``) and renders, refreshing
~1s:

  - a header of aggregate metrics (active agents, calls, cost, calls/min, gates),
  - an htop-like sortable table of recent/active runs (one row per agent run),
  - a drill-down detail pane for the selected run (deep for Hephaestus: phase
    timeline, research, detected gaps/fixes, pending H1/H3 gates, cost).

The interactive UI uses Textual. The data-model builders (``build_state`` /
``render_detail``) are pure and importable without a TTY, so they're unit-tested
directly and reused by a non-interactive snapshot fallback. ASCII house style.
"""

from __future__ import annotations

from typing import Any

from core import agent_events

_STATUS_STYLE = {
    "running": "bold green",
    "paused": "yellow",
    "completed": "cyan",
    "error": "bold red",
    "failed": "red",
    "stale": "magenta",
    "cancelled": "dim",
}

_SORTS = ("recent", "cost", "agent", "status")


# --------------------------------------------------------------------------
# Pure data-model helpers (TTY-free; unit-tested + reused by the snapshot)
# --------------------------------------------------------------------------
def build_state(recent_limit: int = 50, sort: str = "recent",
                active_only: bool = False) -> dict[str, Any]:
    """Aggregates + ordered run rows for the control room (single source)."""
    state = agent_events.control_room_state(recent_limit)
    runs = state["runs"]
    if active_only:
        runs = [r for r in runs if r.get("is_active")]
    if sort == "cost":
        runs.sort(key=lambda r: r.get("cost_micros", 0), reverse=True)
    elif sort == "agent":
        runs.sort(key=lambda r: (r.get("agent", ""), -r.get("started_epoch", 0)))
    elif sort == "status":
        runs.sort(key=lambda r: r.get("effective_status", ""))
    else:  # recent
        runs.sort(key=lambda r: r.get("last_seen", 0), reverse=True)
    state["runs"] = runs
    return state


def _fmt_elapsed(seconds: float) -> str:
    s = int(seconds or 0)
    return f"{s // 60:02d}:{s % 60:02d}"


def _fmt_usd(micros: int) -> str:
    return f"${(micros or 0) / 1_000_000:.4f}"


def render_header(agg: dict[str, Any]):
    from rich.text import Text
    models = ", ".join(f"{m.split('-')[1] if '-' in m else m}:{n}"
                       for m, n in (agg.get("models_in_use") or {}).items()) or "-"
    t = Text()
    t.append("  active ", style="dim"); t.append(str(agg["active_agents"]), style="bold green")
    t.append("   runs ", style="dim"); t.append(str(agg["total_runs"]), style="bold")
    t.append("   calls ", style="dim"); t.append(str(agg["llm_calls"]), style="bold")
    t.append("   calls/min ", style="dim"); t.append(str(agg["calls_per_min"]), style="bold cyan")
    t.append("   cost ", style="dim"); t.append(_fmt_usd(agg["cost_micros"]), style="bold yellow")
    t.append("   gates ", style="dim")
    t.append(str(agg["pending_gates"]),
             style="bold red" if agg["pending_gates"] else "dim")
    t.append(f"   models {models}", style="dim")
    return t


def render_detail(run_id: str | None):
    """Rich renderable describing one run; deep for Hephaestus."""
    from rich.table import Table
    from rich.text import Text
    from rich.console import Group

    if not run_id:
        return Text("Select a run to see details.", style="dim")
    detail = agent_events.run_detail(run_id)
    run = detail["run"]
    if run.get("missing"):
        return Text(f"No data for run {run_id}", style="dim")

    params = run.get("params", {}) or {}
    head = Text()
    head.append(f"{run.get('agent','?')} ", style="bold")
    head.append(f"[{run.get('surface','?')}]  ", style="dim")
    st = run.get("effective_status", "?")
    head.append(st, style=_STATUS_STYLE.get(st, "white"))
    head.append(f"   {_fmt_elapsed(run.get('elapsed_seconds',0))}", style="dim")
    head.append(f"   {run.get('calls',0)} call(s)  ", style="dim")
    head.append(_fmt_usd(run.get("cost_micros", 0)), style="yellow")
    if params:
        head.append("\n  params: " + ", ".join(f"{k}={v}" for k, v in params.items()),
                    style="dim")
    if run.get("pending_gates"):
        head.append("\n  PENDING GATES: " + ", ".join(run["pending_gates"]),
                    style="bold red")

    tl = Table(title="timeline", show_header=True, header_style="bold",
               expand=True, padding=(0, 1))
    tl.add_column("time", style="dim", no_wrap=True)
    tl.add_column("event", style="cyan", no_wrap=True)
    tl.add_column("detail", overflow="fold")
    for e in detail["timeline"][-40:]:
        ts = str(e.get("ts", ""))[11:19]
        etype = e.get("event_type", "")
        d = e.get("detail", "")
        if etype == "llm_call":
            d = f"{e.get('model','')}  {_fmt_usd(e.get('cost_micros',0))}"
        elif etype == "gate_request":
            d = f"GATE {e.get('gate','')}: {d}"
        tl.add_row(ts, etype, str(d)[:120])
    return Group(head, Text(""), tl)


def snapshot_text() -> str:
    """One-shot Rich rendering (for non-TTY / `--once` use)."""
    from rich.console import Console
    from rich.table import Table
    state = build_state()
    con = Console(record=True, width=140)
    con.print(render_header(state["aggregates"]))
    tbl = Table(show_header=True, header_style="bold", expand=True)
    for col in ("run", "agent", "surf", "status", "phase", "elapsed",
                "calls", "tok(i/o)", "cost", "gates", "detail"):
        tbl.add_column(col, overflow="fold")
    for r in state["runs"]:
        st = r.get("effective_status", "?")
        tbl.add_row(
            r.get("run_id", "")[:8], r.get("agent", ""), r.get("surface", ""),
            f"[{_STATUS_STYLE.get(st,'white')}]{st}[/]", r.get("phase", ""),
            _fmt_elapsed(r.get("elapsed_seconds", 0)), str(r.get("calls", 0)),
            f"{r.get('input_tokens',0)}/{r.get('output_tokens',0)}",
            _fmt_usd(r.get("cost_micros", 0)), str(r.get("pending_gate_count", 0)),
            str(r.get("last_detail", ""))[:60])
    con.print(tbl)
    return con.export_text()


# --------------------------------------------------------------------------
# Textual app
# --------------------------------------------------------------------------
def _build_app():
    """Construct the Textual App class lazily (textual is an optional dep)."""
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, VerticalScroll
    from textual.widgets import Header, Footer, DataTable, Static

    _COLS = ("run", "agent", "surf", "status", "phase", "elapsed",
             "calls", "tok(i/o)", "cost", "gates", "detail")

    class ControlRoomApp(App):
        CSS = """
        #metrics { height: 1; padding: 0 1; }
        #body { height: 1fr; }
        DataTable { width: 2fr; }
        #detail { width: 1fr; border-left: solid grey; padding: 0 1; }
        """
        BINDINGS = [
            ("q", "quit", "Quit"),
            ("s", "cycle_sort", "Sort"),
            ("f", "toggle_active", "Active-only"),
            ("r", "refresh_now", "Refresh"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self.sort = "recent"
            self.active_only = False
            self.selected: str | None = None

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Static(id="metrics")
            with Horizontal(id="body"):
                yield DataTable(id="runs", cursor_type="row", zebra_stripes=True)
                with VerticalScroll(id="detailbox"):
                    yield Static(id="detail")
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one("#runs", DataTable)
            table.add_columns(*_COLS)
            self.refresh_data()
            self.set_interval(1.0, self.refresh_data)

        def _title(self) -> str:
            return (f"StrikeCore Control Room  -  sort:{self.sort}"
                    f"{'  active-only' if self.active_only else ''}")

        def refresh_data(self) -> None:
            from rich.text import Text
            state = build_state(sort=self.sort, active_only=self.active_only)
            self.title = self._title()
            self.query_one("#metrics", Static).update(render_header(state["aggregates"]))
            table = self.query_one("#runs", DataTable)
            prev = self.selected
            table.clear()
            first_key = None
            for r in state["runs"]:
                rid = r.get("run_id", "")
                if first_key is None:
                    first_key = rid
                st = r.get("effective_status", "?")
                table.add_row(
                    rid[:8], r.get("agent", ""), r.get("surface", ""),
                    Text(st, style=_STATUS_STYLE.get(st, "white")),
                    r.get("phase", ""), _fmt_elapsed(r.get("elapsed_seconds", 0)),
                    str(r.get("calls", 0)),
                    f"{r.get('input_tokens',0)}/{r.get('output_tokens',0)}",
                    _fmt_usd(r.get("cost_micros", 0)),
                    str(r.get("pending_gate_count", 0)),
                    str(r.get("last_detail", ""))[:50], key=rid)
            if prev is None:
                self.selected = first_key
            self._update_detail()

        def _update_detail(self) -> None:
            self.query_one("#detail", Static).update(render_detail(self.selected))

        def on_data_table_row_highlighted(self, event) -> None:
            self.selected = str(event.row_key.value) if event.row_key else None
            self._update_detail()

        def action_cycle_sort(self) -> None:
            self.sort = _SORTS[(_SORTS.index(self.sort) + 1) % len(_SORTS)]
            self.refresh_data()

        def action_toggle_active(self) -> None:
            self.active_only = not self.active_only
            self.refresh_data()

        def action_refresh_now(self) -> None:
            self.refresh_data()

    return ControlRoomApp


def run() -> int:
    """Launch the interactive control room (falls back to a snapshot if no TTY/textual)."""
    try:
        App = _build_app()
    except Exception as exc:  # textual missing
        print("Textual not available (" + str(exc) + ").\n"
              "Install with: pip install textual\n\nSnapshot:\n")
        print(snapshot_text())
        return 0
    App().run()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
