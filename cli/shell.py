"""Interactive REPL shell for StrikeCore.

Provides a Prompt Toolkit-powered command-line interface with tab
completion, persistent history, a dynamic bottom toolbar, and routing
for all StrikeCore commands including AI-driven assessment sessions.
"""

from __future__ import annotations

import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion, WordCompleter, merge_completers
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style as PTStyle
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cli.banner import display_banner
from cli.renderer import (
    THEME,
    StatusBar,
    create_status_bar,
    render_agent_status,
    render_provider_status,
    render_table,
)
from config.settings import Settings, get_settings
from core.nlp_engine import NaturalLanguageEngine

__all__ = ["run_shell"]

console = Console()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HISTORY_DIR = Path.home() / ".strikecore"
_HISTORY_FILE = _HISTORY_DIR / "history"

_AGENT_NAMES = ("recon", "webapp", "bugbounty", "ctf", "cloud", "binary", "osint", "socint", "geoint")

_ALL_COMMANDS = [
    "help",
    "scan",
    "agent",
    "provider",
    "models",
    "model",
    "/model",
    "hephaestus",
    "/hephaestus",
    "controlroom",
    "/controlroom",
    "monitor",
    "tools",
    "processes",
    "kill",
    "logs",
    "report",
    "cache",
    "config",
    "telegram",
    "status",
    "gpu",
    "clear",
    "exit",
    "quit",
]

_COMMAND_HELP: List[Tuple[str, str, str]] = [
    ("help", "", "Show this help table"),
    ("scan", "<target>", "Start an AI-driven security assessment"),
    ("agent", "<name> <target>", "Run a specific agent (recon, webapp, bugbounty, ctf, cloud, binary, osint)"),
    ("provider", "", "Show active provider info"),
    ("provider", "switch <name>", "Switch active AI provider"),
    ("provider", "list", "List all configured providers with status"),
    ("models", "", "List available models for the active provider"),
    ("model", "switch <name>", "Switch model on active provider"),
    ("/model", "", "Show cost-aware router policy (mode/profile/lethality/overrides)"),
    ("/model", "fable|opus|haiku", "Pin a model globally; /model auto to re-enable routing"),
    ("/model", "profile <name>", "Switch routing profile (default|hephaestus|dossier)"),
    ("/model", "lethality <lvl>", "Dossier lethality (economy|balanced|max)"),
    ("/model", "<phase> <model>", "Per-step model override; /model cost shows run cost"),
    ("hephaestus", "", "Toolsmith status + pending sandbox gates (alias /hephaestus)"),
    ("hephaestus", "run --focus <cat>", "Run a discovery/research/decide pass [--depth N --dry-run --lethality L]"),
    ("hephaestus", "report [run_id]", "Print a run report (latest if omitted)"),
    ("hephaestus", "approve <run_id> <H1|H3>", "Clear a pending sandbox gate"),
    ("controlroom", "", "htop-style live control room for all agents (alias /controlroom, monitor)"),
    ("controlroom", "--once", "Print a one-shot control-room snapshot (no TUI)"),
    ("tools", "", "List all security tools with install status"),
    ("processes", "", "Show background processes"),
    ("kill", "<pid>", "Kill a background process"),
    ("logs", "", "Show recent log entries"),
    ("report", "<session_id>", "Generate a report for a session"),
    ("cache", "", "Show cache statistics"),
    ("config", "", "Show / edit configuration"),
    ("telegram", "", "Send the latest report to Telegram"),
    ("status", "", "System health, API usage, GPU memory"),
    ("gpu", "", "GPU information"),
    ("clear", "", "Clear the screen"),
    ("dossier", "Nome Cognome [urls] [task]", "OSINT dossier + natural language task on a person"),
    ("report", "", "Generate report + graph for current investigation"),
    ("dashboard", "[port]", "Launch web dashboard (default :5000)"),
    ("investigate", "<target>", "Open/create persistent investigation for a target"),
    ("upload", "<filepath>", "Upload document to current investigation RAG"),
    ("search", "<query>", "Search across all stored intelligence"),
    ("install", "github <url>", "Install a tool from GitHub repo"),
    ("install", "socint / geoint", "Install all SOCINT or GEOINT tools"),
    ("install", "list", "List all installable tools"),
    ("clear-chat", "", "Clear AI conversation history"),
    ("exit / quit", "", "Graceful shutdown"),
    ("", "", ""),
    ("[Natural Language]", "<any text>", "Talk to AI in any language — it interprets and executes"),
]

# Prompt Toolkit style matching the StrikeCore colour theme
_PT_STYLE = PTStyle.from_dict(
    {
        "prompt": "#ff4444 bold",
        "operator": "#00cccc",
        "provider": "#cc44cc bold",
        "session": "#888888",
        "bottom-toolbar": "bg:#1a1a2e #aaaaaa",
        "bottom-toolbar.text": "#cccccc",
    }
)

# ---------------------------------------------------------------------------
# Completer
# ---------------------------------------------------------------------------


class StrikeCoreCompleter(Completer):
    """Context-aware completer for the StrikeCore shell."""

    def __init__(self, shell: "StrikeCoreShell") -> None:
        self._shell = shell

    def get_completions(self, document, complete_event):  # type: ignore[override]
        text = document.text_before_cursor.lstrip()
        words = text.split()
        word_count = len(words)

        # Completing the first word (the command)
        if word_count == 0 or (word_count == 1 and not text.endswith(" ")):
            prefix = words[0] if words else ""
            for cmd in _ALL_COMMANDS:
                if cmd.startswith(prefix):
                    yield Completion(cmd, start_position=-len(prefix))
            return

        cmd = words[0].lower()
        prefix = words[-1] if not text.endswith(" ") else ""
        start_pos = -len(prefix)

        if cmd == "agent" and word_count <= 2:
            for name in _AGENT_NAMES:
                if name.startswith(prefix):
                    yield Completion(name, start_position=start_pos)

        elif cmd == "provider":
            if word_count == 2 and not text.endswith(" "):
                for sub in ("switch", "list"):
                    if sub.startswith(prefix):
                        yield Completion(sub, start_position=start_pos)
            elif word_count >= 2 and words[1] == "switch":
                for pname in self._shell.configured_providers:
                    if pname.startswith(prefix):
                        yield Completion(pname, start_position=start_pos)

        elif cmd == "model" and word_count == 2:
            if "switch".startswith(prefix):
                yield Completion("switch", start_position=start_pos)

        elif cmd in ("hephaestus", "/hephaestus") and word_count == 2:
            for sub in ("run", "status", "report", "approve"):
                if sub.startswith(prefix):
                    yield Completion(sub, start_position=start_pos)

        elif cmd == "kill" and word_count == 2:
            for pid in self._shell.background_pids:
                pid_str = str(pid)
                if pid_str.startswith(prefix):
                    yield Completion(pid_str, start_position=start_pos)


# ---------------------------------------------------------------------------
# Session tracking
# ---------------------------------------------------------------------------


class SessionManager:
    """Lightweight session bookkeeper."""

    def __init__(self) -> None:
        self.session_id: str = self._generate_id()
        self.started_at: datetime = datetime.now()
        self.command_count: int = 0

    @staticmethod
    def _generate_id() -> str:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        short_uuid = uuid.uuid4().hex[:6]
        return f"sc-{ts}-{short_uuid}"

    def new_session(self) -> str:
        self.session_id = self._generate_id()
        self.started_at = datetime.now()
        self.command_count = 0
        return self.session_id


# ---------------------------------------------------------------------------
# Shell core
# ---------------------------------------------------------------------------


class StrikeCoreShell:
    """Main interactive REPL for StrikeCore."""

    def __init__(self) -> None:
        self.settings: Settings = get_settings()
        self.session = SessionManager()
        self.status_bar: StatusBar = create_status_bar()
        self.background_processes: Dict[int, Dict[str, Any]] = {}
        self._running = True

        # Read provider info from settings
        self._active_provider: str = self.settings.get("ai.active_provider", "none") or "none"
        self._active_model: str = self._resolve_active_model()

        self.status_bar.provider = self._active_provider
        self.status_bar.model = self._active_model

        # Natural language AI engine
        self._nlp = NaturalLanguageEngine(self.settings)

        # Ensure history directory exists
        _HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    # -- Properties -----------------------------------------------------------

    @property
    def configured_providers(self) -> List[str]:
        provider_keys = ["anthropic", "openrouter", "ollama", "vllm", "lmstudio", "custom"]
        configured = []
        for key in provider_keys:
            section = self.settings.get(f"ai.{key}")
            if isinstance(section, dict) and section:
                configured.append(key)
        return configured

    @property
    def background_pids(self) -> List[int]:
        return list(self.background_processes.keys())

    # -- Helpers --------------------------------------------------------------

    def _resolve_active_model(self) -> str:
        provider = self._active_provider
        model = self.settings.get(f"ai.{provider}.model", "")
        return model or "default"

    def _build_prompt(self) -> str:
        hostname = socket.gethostname()
        operator = self.settings.get("operator.name", "operator") or "operator"
        prov_model = f"{self._active_provider}:{self._active_model}"
        sid = self.session.session_id
        return (
            f"[STRIKECORE]"
            f"[{operator}@{hostname}]"
            f"[{prov_model}]"
            f"[{sid}]> "
        )

    def _toolbar_callback(self) -> str:
        return self.status_bar.format_toolbar()

    # -- Command dispatch -----------------------------------------------------

    def _dispatch(self, line: str) -> None:
        """Parse and dispatch a single command line."""
        line = line.strip()
        if not line:
            return

        self.session.command_count += 1
        parts = line.split()
        cmd = parts[0].lower()
        args = parts[1:]

        handler = self._commands.get(cmd)
        if handler:
            try:
                handler(self, args)
            except KeyboardInterrupt:
                console.print("\n[dim]Command interrupted.[/dim]")
            except Exception as exc:
                console.print(f"[{THEME['error']}]Error: {exc}[/{THEME['error']}]")
        else:
            # Route to AI natural language engine
            try:
                self._nlp.process(line)
                self.status_bar.last_tool = "ai:chat"
            except KeyboardInterrupt:
                console.print("\n[dim]AI request cancelled.[/dim]")
            except Exception as exc:
                console.print(f"[bold red]AI error:[/bold red] {exc}")

    # -- Command implementations ----------------------------------------------

    def _cmd_help(self, args: List[str]) -> None:
        table = Table(
            title="StrikeCore Commands",
            title_style="bold bright_white",
            border_style="bright_cyan",
            show_lines=True,
            padding=(0, 1),
        )
        table.add_column("Command", style="bold bright_green", min_width=14)
        table.add_column("Arguments", style="cyan", min_width=18)
        table.add_column("Description", style="white")

        for cmd, cmd_args, desc in _COMMAND_HELP:
            table.add_row(cmd, cmd_args, desc)

        console.print(table)
        console.print()

    def _cmd_scan(self, args: List[str]) -> None:
        if not args:
            console.print(f"[{THEME['warning']}]Usage: scan <target>[/{THEME['warning']}]")
            return

        target = " ".join(args)
        console.print(
            Panel(
                f"[bold bright_white]Starting AI-driven assessment of:[/bold bright_white] [cyan]{target}[/cyan]\n\n"
                f"[dim]Session: {self.session.session_id}[/dim]\n"
                f"[dim]Provider: {self._active_provider}:{self._active_model}[/dim]",
                title="[bright_green]Scan Initiated[/bright_green]",
                border_style="bright_green",
                padding=(1, 2),
            )
        )
        self.status_bar.last_tool = f"scan:{target}"
        self.status_bar.active_processes += 1

        # Route to agent loop -- in production this calls the orchestrator.
        # For now we display the handoff message.
        console.print(
            f"[dim]Dispatching to AI agent loop... "
            f"(orchestrator integration point: "
            f"strikecore.core.orchestrator.run_assessment(target={target!r}, "
            f"session_id={self.session.session_id!r}))[/dim]"
        )
        console.print()

    def _cmd_agent(self, args: List[str]) -> None:
        if len(args) < 2:
            console.print(f"[{THEME['warning']}]Usage: agent <name> <target>[/{THEME['warning']}]")
            console.print(f"[dim]Available agents: {', '.join(_AGENT_NAMES)}[/dim]")
            return

        agent_name = args[0].lower()
        target = " ".join(args[1:])

        if agent_name not in _AGENT_NAMES:
            console.print(f"[{THEME['error']}]Unknown agent: {agent_name}[/{THEME['error']}]")
            console.print(f"[dim]Available: {', '.join(_AGENT_NAMES)}[/dim]")
            return

        render_agent_status(
            agent_name,
            "running",
            details={"target": target, "session": self.session.session_id},
        )
        self.status_bar.last_tool = f"agent:{agent_name}"
        self.status_bar.active_processes += 1

        console.print(
            f"[dim]Dispatching to {agent_name} agent... "
            f"(integration point: strikecore.agents.{agent_name}.run(target={target!r}))[/dim]"
        )
        console.print()

    def _cmd_provider(self, args: List[str]) -> None:
        if not args:
            # Show active provider info
            provider_info = {
                "provider": self._active_provider,
                "model": self._active_model,
                "status": "healthy",
                "fallback_chain": self.settings.get("ai.fallback_chain", []),
            }
            render_provider_status(provider_info)
            return

        subcmd = args[0].lower()

        if subcmd == "list":
            headers = ["Provider", "Status", "Model", "Active"]
            rows = []
            for pname in ["anthropic", "openrouter", "ollama", "vllm", "lmstudio", "custom"]:
                section = self.settings.get(f"ai.{pname}")
                if isinstance(section, dict) and section:
                    model = section.get("model", "N/A")
                    is_active = "\u2714" if pname == self._active_provider else ""
                    rows.append([pname, "configured", model, is_active])
                else:
                    rows.append([pname, "not configured", "-", ""])
            render_table(headers, rows, title="Configured Providers")

        elif subcmd == "switch" and len(args) >= 2:
            new_provider = args[1].lower()
            section = self.settings.get(f"ai.{new_provider}")
            if not isinstance(section, dict) or not section:
                console.print(f"[{THEME['error']}]Provider '{new_provider}' is not configured.[/{THEME['error']}]")
                return
            self._active_provider = new_provider
            self._active_model = section.get("model", "default")
            self.settings.set("ai.active_provider", new_provider)
            self.status_bar.provider = self._active_provider
            self.status_bar.model = self._active_model
            console.print(f"[{THEME['success']}]Switched to {new_provider}:{self._active_model}[/{THEME['success']}]")
        else:
            console.print(f"[{THEME['warning']}]Usage: provider [list|switch <name>][/{THEME['warning']}]")

    def _cmd_models(self, args: List[str]) -> None:
        console.print(f"[bright_white]Models for provider:[/bright_white] [bold cyan]{self._active_provider}[/bold cyan]\n")

        section = self.settings.get(f"ai.{self._active_provider}", {})
        if not isinstance(section, dict):
            section = {}

        current_model = section.get("model", "N/A")
        console.print(f"  [bright_white]Active model:[/bright_white] [cyan]{current_model}[/cyan]")

        # For local providers, try to list available models
        if self._active_provider == "ollama":
            try:
                import httpx
                resp = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
                if resp.status_code == 200:
                    models = [m["name"] for m in resp.json().get("models", [])]
                    if models:
                        console.print(f"\n  [bright_white]Available models ({len(models)}):[/bright_white]")
                        for m in models:
                            marker = " [bold green]<-- active[/bold green]" if m == current_model else ""
                            console.print(f"    - [cyan]{m}[/cyan]{marker}")
            except Exception:
                console.print("  [dim]Could not query Ollama for model list.[/dim]")

        elif self._active_provider in ("vllm", "lmstudio"):
            base_url = section.get("base_url", "")
            if base_url:
                try:
                    import httpx
                    resp = httpx.get(f"{base_url.rstrip('/')}/v1/models", timeout=5.0)
                    if resp.status_code == 200:
                        models = [m["id"] for m in resp.json().get("data", [])]
                        if models:
                            console.print(f"\n  [bright_white]Available models ({len(models)}):[/bright_white]")
                            for m in models:
                                marker = " [bold green]<-- active[/bold green]" if m == current_model else ""
                                console.print(f"    - [cyan]{m}[/cyan]{marker}")
                except Exception:
                    console.print(f"  [dim]Could not query {self._active_provider} for model list.[/dim]")

        elif self._active_provider == "anthropic":
            known = [
                "claude-opus-4-20250514",
                "claude-sonnet-4-20250514",
                "claude-3.5-haiku-20241022",
                "claude-3-5-sonnet-20241022",
            ]
            console.print(f"\n  [bright_white]Known models:[/bright_white]")
            for m in known:
                marker = " [bold green]<-- active[/bold green]" if m == current_model else ""
                console.print(f"    - [cyan]{m}[/cyan]{marker}")

        elif self._active_provider == "openrouter":
            console.print(f"\n  [dim]OpenRouter supports 200+ models. Visit https://openrouter.ai/models[/dim]")

        console.print()

    def _cmd_model(self, args: List[str]) -> None:
        if len(args) < 2 or args[0].lower() != "switch":
            console.print(f"[{THEME['warning']}]Usage: model switch <name>[/{THEME['warning']}]")
            return
        new_model = args[1]
        self.settings.set(f"ai.{self._active_provider}.model", new_model)
        self._active_model = new_model
        self.status_bar.model = new_model
        console.print(f"[{THEME['success']}]Model switched to {new_model}[/{THEME['success']}]")

    def _cmd_model_router(self, args: List[str]) -> None:
        """/model — control the cost-aware LLM router (GR3). Persisted to config.

        /model                     show active policy
        /model <fable|opus|haiku|id>   pin a model globally
        /model auto                re-enable cost-aware routing
        /model profile <name>      switch routing profile (default|hephaestus|dossier)
        /model lethality <lvl>     dossier lethality (economy|balanced|max)
        /model <phase> <model>     per-step override (e.g. /model planner fable)
        /model clear <phase>       remove a per-step override
        /model cost                estimated cost of the current/last run
        """
        from governance.model_router import (
            FRIENDLY_TO_ID, policy_from_settings, resolve_model_name,
        )

        def persist():
            try:
                self.settings.save()
            except Exception:
                pass

        sub = args[0].lower() if args else "show"

        if sub in ("show", ""):
            p = policy_from_settings(self.settings)
            console.print(f"[{THEME['accent']}]LLM router policy[/{THEME['accent']}]")
            console.print(f"  mode      : {p.mode}")
            console.print(f"  pinned    : {p.pinned_model or '-'}")
            console.print(f"  profile   : {p.profile}")
            console.print(f"  lethality : {p.lethality}  (dossier)")
            console.print(f"  overrides : {p.overrides or '{}'}")
            return

        if sub == "auto":
            self.settings.set("ai.model_policy.mode", "auto")
            persist()
            console.print(f"[{THEME['success']}]Router: cost-aware auto mode[/{THEME['success']}]")
            return

        if sub == "profile":
            if len(args) < 2 or args[1] not in ("default", "hephaestus", "dossier"):
                console.print(f"[{THEME['warning']}]Usage: /model profile <default|hephaestus|dossier>[/{THEME['warning']}]")
                return
            self.settings.set("ai.model_policy.profile", args[1]); persist()
            console.print(f"[{THEME['success']}]Routing profile: {args[1]}[/{THEME['success']}]")
            return

        if sub == "lethality":
            if len(args) < 2 or args[1] not in ("economy", "balanced", "max"):
                console.print(f"[{THEME['warning']}]Usage: /model lethality <economy|balanced|max>[/{THEME['warning']}]")
                return
            self.settings.set("ai.model_policy.lethality", args[1]); persist()
            console.print(f"[{THEME['success']}]Dossier lethality: {args[1]}[/{THEME['success']}]")
            return

        if sub == "clear":
            if len(args) < 2:
                console.print(f"[{THEME['warning']}]Usage: /model clear <phase>[/{THEME['warning']}]")
                return
            ov = dict(policy_from_settings(self.settings).overrides)
            ov.pop(args[1], None)
            self.settings.set("ai.model_policy.overrides", ov); persist()
            console.print(f"[{THEME['success']}]Cleared override for {args[1]}[/{THEME['success']}]")
            return

        if sub == "cost":
            router = getattr(getattr(self, "_nlp", None), "_router", None)
            if router is not None and getattr(router, "call_log", None):
                rc = router.run_cost()
                t = rc["totals"]
                console.print(f"[{THEME['accent']}]Run cost[/{THEME['accent']}] "
                              f"{t['calls']} call(s)  ${t['cost_usd_micros']/1_000_000:.4f}")
                for m, info in rc["by_model"].items():
                    console.print(f"  {m:<18} {info['calls']:>2} call(s)  "
                                  f"${info['cost_micros']/1_000_000:.4f}")
            else:
                console.print(f"[{THEME['muted']}]No active run yet — run a query, dossier, or hephaestus run first.[/{THEME['muted']}]")
            return

        # pin a model globally  (/model fable|opus|haiku|<id>)
        if len(args) == 1:
            mid = resolve_model_name(args[0])
            self.settings.set("ai.model_policy.mode", "pinned")
            self.settings.set("ai.model_policy.pinned_model", mid)
            persist()
            console.print(f"[{THEME['success']}]Pinned model: {mid}[/{THEME['success']}]")
            return

        # per-step override  (/model <phase> <model>)
        phase, model = args[0], resolve_model_name(args[1])
        ov = dict(policy_from_settings(self.settings).overrides)
        ov[phase] = model
        self.settings.set("ai.model_policy.overrides", ov); persist()
        console.print(f"[{THEME['success']}]Override: {phase} -> {model}[/{THEME['success']}]")

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
                              f"{p['reason']}  ->  hephaestus approve {rid} {p['gate']}[/{THEME['warning']}]")
            return

        if sub == "run":
            fetch_from_outputs = "--fetch-from-outputs" in args
            focus = self._flag_value(args, "--focus")
            if not focus and not fetch_from_outputs:
                console.print(f"[{THEME['warning']}]Usage: hephaestus run --focus <category> "
                              f"[--depth N] [--dry-run] [--lethality economy|balanced|max]\n"
                              f"   or: hephaestus run --fetch-from-outputs [--outputs-limit N]"
                              f"[/{THEME['warning']}]")
                return
            focus = focus or "dossier-mode"
            depth = int(self._flag_value(args, "--depth") or 1)
            outputs_limit = int(self._flag_value(args, "--outputs-limit") or 10)
            dry_run = "--dry-run" in args
            lethality = self._flag_value(args, "--lethality") or "balanced"
            console.print(f"[{THEME['muted']}]Hephaestus: focus={focus} depth={depth} "
                          f"lethality={lethality}"
                          f"{' fetch-from-outputs' if fetch_from_outputs else ''}"
                          f"{' (dry-run)' if dry_run else ''} ...[/{THEME['muted']}]")
            from hephaestus.reporting import StreamReporter
            try:
                rec = cli_core.run_pass(focus=focus, depth=depth, dry_run=dry_run,
                                        profile="hephaestus", lethality=lethality,
                                        fetch_from_outputs=fetch_from_outputs,
                                        outputs_limit=outputs_limit,
                                        reporter=StreamReporter())
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

    def _cmd_tools(self, args: List[str]) -> None:
        # Comprehensive security tools list
        tools_list = [
            ("nmap", "Network", "Port scanning and service detection"),
            ("masscan", "Network", "High-speed port scanner"),
            ("zmap", "Network", "Internet-wide scanner"),
            ("unicornscan", "Network", "Async TCP/UDP scanner"),
            ("nikto", "Web", "Web server scanner"),
            ("sqlmap", "Web", "SQL injection automation"),
            ("ffuf", "Web", "Fast web fuzzer"),
            ("gobuster", "Web", "Directory/DNS brute-forcer"),
            ("dirb", "Web", "Web content scanner"),
            ("dirsearch", "Web", "Web path brute-forcer"),
            ("wpscan", "Web", "WordPress scanner"),
            ("nuclei", "Vuln", "Template-based vuln scanner"),
            ("subfinder", "Recon", "Subdomain discovery"),
            ("amass", "Recon", "Attack surface mapping"),
            ("httpx", "Recon", "HTTP probing toolkit"),
            ("whatweb", "Recon", "Web fingerprinting"),
            ("wafw00f", "Recon", "WAF detection"),
            ("theHarvester", "OSINT", "Email/domain harvester"),
            ("shodan", "OSINT", "Internet device search"),
            ("censys", "OSINT", "Internet-wide scanning"),
            ("recon-ng", "OSINT", "Web reconnaissance framework"),
            ("maltego", "OSINT", "Visual link analysis"),
            ("hydra", "Auth", "Network login brute-forcer"),
            ("medusa", "Auth", "Parallel login brute-forcer"),
            ("john", "Crypto", "Password hash cracker"),
            ("hashcat", "Crypto", "GPU password cracker"),
            ("hashid", "Crypto", "Hash type identifier"),
            ("testssl.sh", "TLS", "TLS/SSL tester"),
            ("sslscan", "TLS", "SSL/TLS scanner"),
            ("sslyze", "TLS", "SSL/TLS analyser"),
            ("metasploit", "Exploit", "Exploitation framework"),
            ("searchsploit", "Exploit", "Exploit database search"),
            ("msfvenom", "Exploit", "Payload generator"),
            ("burpsuite", "Proxy", "Web application proxy"),
            ("mitmproxy", "Proxy", "Interactive HTTPS proxy"),
            ("wireshark", "Capture", "Packet analyser"),
            ("tcpdump", "Capture", "Command-line packet capture"),
            ("responder", "Internal", "LLMNR/NBT-NS poisoner"),
            ("crackmapexec", "Internal", "Network pentesting suite"),
            ("impacket", "Internal", "Network protocol toolkit"),
            ("bloodhound", "AD", "Active Directory analyser"),
            ("kerbrute", "AD", "Kerberos brute-forcer"),
            ("enum4linux", "Enum", "Windows/Samba enumerator"),
            ("smbclient", "Enum", "SMB client"),
            ("snmpwalk", "Enum", "SNMP tree walker"),
            ("fierce", "DNS", "DNS reconnaissance"),
            ("dnsrecon", "DNS", "DNS enumeration"),
            ("dig", "DNS", "DNS lookup utility"),
            ("whois", "DNS", "Domain registration lookup"),
            ("binwalk", "Binary", "Firmware analysis"),
            ("radare2", "Binary", "Reverse engineering framework"),
            ("ghidra", "Binary", "Software reverse engineering"),
            ("gdb", "Binary", "GNU debugger"),
            ("ltrace", "Binary", "Library call tracer"),
            ("strace", "Binary", "System call tracer"),
            ("aircrack-ng", "Wireless", "WiFi security auditing"),
            ("kismet", "Wireless", "Wireless network detector"),
            ("wifite", "Wireless", "Automated WiFi auditor"),
            ("ansible", "Cloud", "Infrastructure automation"),
            ("terraform", "Cloud", "Infrastructure as code"),
            ("aws", "Cloud", "AWS CLI"),
            ("gcloud", "Cloud", "Google Cloud CLI"),
            ("az", "Cloud", "Azure CLI"),
            ("kubectl", "Cloud", "Kubernetes CLI"),
            ("docker", "Container", "Container runtime"),
            ("trivy", "Container", "Container vulnerability scanner"),
            ("grype", "Container", "Container image scanner"),
            ("git", "Util", "Version control"),
            ("curl", "Util", "HTTP client"),
            ("wget", "Util", "File downloader"),
            ("jq", "Util", "JSON processor"),
            ("python3", "Util", "Python interpreter"),
            ("go", "Util", "Go compiler"),
            ("proxychains", "Util", "Proxy chaining"),
            ("tor", "Util", "Anonymity network"),
            ("socat", "Util", "Socket relay"),
            ("netcat", "Util", "Network utility"),
        ]

        table = Table(
            title=f"Security Tools ({len(tools_list)})",
            title_style="bold bright_white",
            border_style="bright_cyan",
            show_lines=False,
            padding=(0, 1),
        )
        table.add_column("Tool", style="bright_white", min_width=16)
        table.add_column("Category", style="magenta", min_width=10, justify="center")
        table.add_column("Status", justify="center", min_width=12)
        table.add_column("Description", style="dim")

        installed_count = 0
        for tool_name, category, desc in tools_list:
            # Try common alternate names
            found = shutil.which(tool_name) is not None
            if not found and tool_name == "metasploit":
                found = shutil.which("msfconsole") is not None
            if not found and tool_name == "netcat":
                found = shutil.which("nc") is not None
            if not found and tool_name == "testssl.sh":
                found = shutil.which("testssl") is not None

            if found:
                installed_count += 1
                status = "[bold green]\u2714 Installed[/bold green]"
            else:
                status = "[dim]\u2718 Missing[/dim]"
            table.add_row(tool_name, category, status, desc)

        console.print(table)
        console.print(f"\n  [bright_white]{installed_count}/{len(tools_list)}[/bright_white] tools installed\n")

    def _cmd_processes(self, args: List[str]) -> None:
        if not self.background_processes:
            console.print("[dim]No background processes running.[/dim]")
            return
        headers = ["PID", "Type", "Target", "Started", "Status"]
        rows = []
        for pid, info in self.background_processes.items():
            rows.append([
                str(pid),
                info.get("type", "unknown"),
                info.get("target", "N/A"),
                info.get("started", "N/A"),
                info.get("status", "running"),
            ])
        render_table(headers, rows, title="Background Processes")

    def _cmd_kill(self, args: List[str]) -> None:
        if not args:
            console.print(f"[{THEME['warning']}]Usage: kill <pid>[/{THEME['warning']}]")
            return
        try:
            pid = int(args[0])
        except ValueError:
            console.print(f"[{THEME['error']}]Invalid PID: {args[0]}[/{THEME['error']}]")
            return

        if pid in self.background_processes:
            del self.background_processes[pid]
            self.status_bar.active_processes = max(0, self.status_bar.active_processes - 1)
            console.print(f"[{THEME['success']}]Process {pid} terminated.[/{THEME['success']}]")
        else:
            # Try system process
            try:
                os.kill(pid, signal.SIGTERM)
                console.print(f"[{THEME['success']}]Sent SIGTERM to PID {pid}.[/{THEME['success']}]")
            except ProcessLookupError:
                console.print(f"[{THEME['error']}]No such process: {pid}[/{THEME['error']}]")
            except PermissionError:
                console.print(f"[{THEME['error']}]Permission denied for PID {pid}.[/{THEME['error']}]")

    def _cmd_logs(self, args: List[str]) -> None:
        log_dir = Path.home() / ".strikecore" / "logs"
        if not log_dir.exists():
            console.print("[dim]No log directory found (~/.strikecore/logs/).[/dim]")
            return

        log_files = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not log_files:
            console.print("[dim]No log files found.[/dim]")
            return

        latest = log_files[0]
        console.print(f"[bright_white]Latest log:[/bright_white] [cyan]{latest.name}[/cyan]\n")

        try:
            lines = latest.read_text().splitlines()[-30:]
            for line in lines:
                if "ERROR" in line:
                    console.print(f"[red]{line}[/red]")
                elif "WARNING" in line:
                    console.print(f"[yellow]{line}[/yellow]")
                elif "DEBUG" in line:
                    console.print(f"[dim]{line}[/dim]")
                else:
                    console.print(line)
        except Exception as exc:
            console.print(f"[{THEME['error']}]Could not read log: {exc}[/{THEME['error']}]")
        console.print()

    def _cmd_report(self, args: List[str]) -> None:
        session_id = args[0] if args else self.session.session_id
        console.print(
            Panel(
                f"[bright_white]Generating report for session:[/bright_white] [cyan]{session_id}[/cyan]\n\n"
                f"[dim]Integration point: strikecore.core.reporting.generate(session_id={session_id!r})[/dim]",
                title="[bright_cyan]Report Generation[/bright_cyan]",
                border_style="bright_cyan",
                padding=(1, 2),
            )
        )
        self.status_bar.last_tool = "report"

    def _cmd_cache(self, args: List[str]) -> None:
        cache_dir = Path.home() / ".strikecore" / "cache"
        if cache_dir.exists():
            files = list(cache_dir.rglob("*"))
            file_count = sum(1 for f in files if f.is_file())
            total_size = sum(f.stat().st_size for f in files if f.is_file())
            size_mb = total_size / (1024 * 1024)
        else:
            file_count = 0
            size_mb = 0.0

        headers = ["Metric", "Value"]
        rows = [
            ["Cache directory", str(cache_dir)],
            ["Cached entries", str(file_count)],
            ["Total size", f"{size_mb:.2f} MB"],
            ["Status", "Active" if cache_dir.exists() else "Not initialized"],
        ]
        render_table(headers, rows, title="Cache Statistics")

    def _cmd_config(self, args: List[str]) -> None:
        config_file = Path.home() / ".strikecore" / "config.toml"
        if config_file.exists():
            console.print(f"[bright_white]Configuration file:[/bright_white] [cyan]{config_file}[/cyan]\n")
            try:
                import toml as toml_lib
                cfg = toml_lib.load(config_file)
                # Mask sensitive values
                display = _mask_secrets(cfg)
                for section, values in display.items():
                    console.print(f"[bold bright_white][{section}][/bold bright_white]")
                    if isinstance(values, dict):
                        for k, v in values.items():
                            if isinstance(v, dict):
                                console.print(f"  [{k}]")
                                for sk, sv in v.items():
                                    console.print(f"    {sk} = [cyan]{sv}[/cyan]")
                            else:
                                console.print(f"  {k} = [cyan]{v}[/cyan]")
                    else:
                        console.print(f"  {values}")
                    console.print()
            except Exception as exc:
                console.print(f"[{THEME['error']}]Could not parse config: {exc}[/{THEME['error']}]")
        else:
            console.print("[dim]No configuration file found. Run onboarding first.[/dim]")

    def _cmd_telegram(self, args: List[str]) -> None:
        enabled = self.settings.get("telegram.enabled", False)
        if not enabled:
            console.print(f"[{THEME['warning']}]Telegram is not configured. Run onboarding or edit config.[/{THEME['warning']}]")
            return
        console.print(
            f"[dim]Integration point: strikecore.messaging.telegram.send_report("
            f"session_id={self.session.session_id!r})[/dim]"
        )
        self.status_bar.last_tool = "telegram"

    def _cmd_status(self, args: List[str]) -> None:
        import psutil

        table = Table(
            title="System Status",
            title_style="bold bright_white",
            border_style="bright_cyan",
            show_lines=True,
            padding=(0, 2),
        )
        table.add_column("Metric", style="bright_white", min_width=20)
        table.add_column("Value", style="cyan")

        # System
        mem = psutil.virtual_memory()
        cpu_pct = psutil.cpu_percent(interval=0.5)
        table.add_row("CPU Usage", f"{cpu_pct:.1f}%")
        table.add_row("RAM Usage", f"{mem.percent:.1f}% ({mem.used / (1024**3):.1f} / {mem.total / (1024**3):.1f} GB)")
        table.add_row("Active Provider", f"{self._active_provider}:{self._active_model}")
        table.add_row("Session ID", self.session.session_id)
        table.add_row("Session Duration", self.status_bar.session_elapsed)
        table.add_row("Commands Run", str(self.session.command_count))
        table.add_row("Background Processes", str(len(self.background_processes)))

        # GPU memory if available
        gpu_mem = _get_gpu_memory()
        if gpu_mem:
            table.add_row("GPU Memory", gpu_mem)

        console.print(table)
        console.print()

    def _cmd_gpu(self, args: List[str]) -> None:
        # Try nvidia-smi
        try:
            result = subprocess.run(
                ["nvidia-smi"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                console.print(Panel(result.stdout, title="[bright_green]nvidia-smi[/bright_green]", border_style="green"))
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Try rocm-smi
        try:
            result = subprocess.run(
                ["rocm-smi"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                console.print(Panel(result.stdout, title="[bright_green]rocm-smi[/bright_green]", border_style="green"))
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        console.print("[dim]No GPU detected (nvidia-smi and rocm-smi not available).[/dim]")

    def _cmd_clear(self, args: List[str]) -> None:
        console.clear()

    def _cmd_install(self, args: List[str]) -> None:
        """Install tools from GitHub or by name."""
        if not args:
            console.print("[bold bright_white]Usage:[/bold bright_white]")
            console.print("  [cyan]install github <repo_url>[/cyan]     Clone and install a GitHub tool")
            console.print("  [cyan]install tool <name>[/cyan]           Install a tool via install_tools.sh")
            console.print("  [cyan]install socint[/cyan]                Install all SOCINT tools")
            console.print("  [cyan]install geoint[/cyan]                Install all GEOINT tools")
            console.print("  [cyan]install list[/cyan]                  List installable tools")
            return

        subcmd = args[0].lower()

        if subcmd == "github" and len(args) >= 2:
            repo_url = args[1]
            # Normalize URL
            if not repo_url.startswith("http"):
                repo_url = f"https://github.com/{repo_url}"
            repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
            dest = Path.home() / ".local" / "share" / repo_name

            console.print(f"[cyan]Cloning {repo_url}...[/cyan]")
            try:
                if dest.exists():
                    result = subprocess.run(["git", "-C", str(dest), "pull"], capture_output=True, text=True, timeout=60)
                    console.print(f"[green]Updated existing clone at {dest}[/green]")
                else:
                    result = subprocess.run(["git", "clone", "--depth", "1", repo_url, str(dest)], capture_output=True, text=True, timeout=120)
                    if result.returncode != 0:
                        console.print(f"[red]Clone failed:[/red] {result.stderr}")
                        return
                    console.print(f"[green]Cloned to {dest}[/green]")

                # Auto-detect and install dependencies
                if (dest / "requirements.txt").exists():
                    console.print("[cyan]Installing Python dependencies...[/cyan]")
                    venv_path = dest / ".venv"
                    subprocess.run(["python3", "-m", "venv", str(venv_path)], capture_output=True, timeout=30)
                    subprocess.run([str(venv_path / "bin" / "pip"), "install", "-r", str(dest / "requirements.txt")], capture_output=True, text=True, timeout=120)

                if (dest / "setup.py").exists() or (dest / "pyproject.toml").exists():
                    console.print("[cyan]Installing package...[/cyan]")
                    venv_path = dest / ".venv"
                    if not venv_path.exists():
                        subprocess.run(["python3", "-m", "venv", str(venv_path)], capture_output=True, timeout=30)
                    subprocess.run([str(venv_path / "bin" / "pip"), "install", str(dest)], capture_output=True, text=True, timeout=120)

                if (dest / "Makefile").exists():
                    console.print(f"[dim]Makefile found — run 'make' in {dest} if needed[/dim]")

                if (dest / "go.mod").exists():
                    console.print("[cyan]Building Go project...[/cyan]")
                    subprocess.run(["go", "build", "-o", str(Path.home() / ".local" / "bin" / repo_name), "."], cwd=str(dest), capture_output=True, text=True, timeout=120)

                # Create wrapper if main script found
                for script in [f"{repo_name}.py", "main.py", f"{repo_name}"]:
                    candidate = dest / script
                    if candidate.exists():
                        wrapper = Path.home() / ".local" / "bin" / repo_name
                        if not wrapper.exists():
                            if script.endswith(".py"):
                                venv_py = dest / ".venv" / "bin" / "python3"
                                py = str(venv_py) if venv_py.exists() else "python3"
                                wrapper.write_text(f"#!/bin/bash\ncd {dest} && {py} {script} \"$@\"\n")
                            else:
                                wrapper.write_text(f"#!/bin/bash\ncd {dest} && ./{script} \"$@\"\n")
                            wrapper.chmod(0o755)
                            console.print(f"[green]Wrapper created: {wrapper}[/green]")
                        break

                console.print(f"[bold green]\u2714 {repo_name} installed at {dest}[/bold green]")

            except subprocess.TimeoutExpired:
                console.print("[red]Operation timed out[/red]")
            except Exception as exc:
                console.print(f"[red]Error: {exc}[/red]")

        elif subcmd == "tool" and len(args) >= 2:
            tool_name = args[1]
            console.print(f"[cyan]Installing {tool_name}...[/cyan]")
            result = subprocess.run(
                ["/home/atlas/strikecore/install_tools.sh", "--only", tool_name],
                capture_output=False, text=True, timeout=300,
            )

        elif subcmd in ("socint", "geoint"):
            console.print(f"[cyan]Installing all {subcmd.upper()} tools...[/cyan]")
            result = subprocess.run(
                ["/home/atlas/strikecore/install_tools.sh", "--category", subcmd],
                capture_output=False, text=True, timeout=600,
            )

        elif subcmd == "list":
            result = subprocess.run(
                ["/home/atlas/strikecore/install_tools.sh", "--list"],
                capture_output=False, text=True, timeout=30,
            )

        else:
            console.print(f"[yellow]Unknown install subcommand: {subcmd}[/yellow]")

    def _cmd_dossier(self, args: list) -> None:
        """Build a full OSINT dossier on a person.
        
        Usage:
            dossier Luigi Savino
            dossier Luigi Savino https://instagram.com/luigisav
            dossier Mario Rossi linkedin.com/in/mariorossi facebook.com/mario
        """
        import re as _re
        from pathlib import Path
        
        if not args:
            console.print("[bold]Usage:[/bold]")
            console.print("  [cyan]dossier Nome Cognome[/cyan]")
            console.print("  [cyan]dossier Nome Cognome https://instagram.com/user[/cyan]")
            console.print("  [cyan]dossier Nome Cognome linkedin.com/in/user facebook.com/user[/cyan]")
            console.print("[dim]You can add any social URL or username as reference.[/dim]")
            return
        
        # Parse: separate name, URLs, and natural language task
        name_parts = []
        references = []
        task_parts = []
        name_done = False
        
        for arg in args:
            # URLs and social references
            if any(x in arg.lower() for x in ["http", ".com", ".it", ".org", ".net", "instagram", "facebook", "linkedin", "github", "twitter", "t.me", "tiktok"]):
                references.append(arg)
                name_done = True
            elif arg.startswith("@"):
                references.append(arg)
                name_done = True
            # Capitalized words at the start = name parts
            elif not name_done and arg[0:1].isupper() and len(arg) > 1 and not any(c in arg for c in ".,;:!?"):
                name_parts.append(arg)
            # Everything else = natural language task
            else:
                name_done = True
                task_parts.append(arg)
        
        natural_task = " ".join(task_parts).strip()
        
        full_name = " ".join(name_parts)
        if not full_name:
            console.print("[red]Please provide at least a name.[/red]")
            return
        
        # Extract usernames from URLs
        usernames = []
        platforms = {}
        for ref in references:
            # Instagram
            m = _re.search(r'instagram\.com/([a-zA-Z0-9_.]+)', ref)
            if m: 
                usernames.append(m.group(1))
                platforms["Instagram"] = ref if ref.startswith("http") else "https://www.instagram.com/" + m.group(1)
            # Facebook
            m = _re.search(r'facebook\.com/([a-zA-Z0-9_.]+|profile\.php\?id=\d+)', ref)
            if m:
                platforms["Facebook"] = ref if ref.startswith("http") else "https://www.facebook.com/" + m.group(1)
            # LinkedIn
            m = _re.search(r'linkedin\.com/in/([a-zA-Z0-9_-]+)', ref)
            if m:
                usernames.append(m.group(1))
                platforms["LinkedIn"] = ref if ref.startswith("http") else "https://www.linkedin.com/in/" + m.group(1)
            # GitHub
            m = _re.search(r'github\.com/([a-zA-Z0-9_-]+)', ref)
            if m:
                usernames.append(m.group(1))
                platforms["GitHub"] = ref if ref.startswith("http") else "https://github.com/" + m.group(1)
            # Twitter
            m = _re.search(r'(?:twitter|x)\.com/([a-zA-Z0-9_]+)', ref)
            if m:
                usernames.append(m.group(1))
                platforms["Twitter"] = ref
            # Telegram
            m = _re.search(r't\.me/([a-zA-Z0-9_]+)', ref)
            if m:
                usernames.append(m.group(1))
                platforms["Telegram"] = ref
            # @ username
            if ref.startswith("@"):
                usernames.append(ref.lstrip("@"))
        
        # Generate target ID
        target_id = full_name.lower().replace(" ", "_")
        first = name_parts[0].lower() if name_parts else ""
        last = name_parts[-1].lower() if len(name_parts) > 1 else ""
        
        # Auto-generate username variants
        variants = list(set(usernames))
        if first and last:
            for v in [f"{first}{last}", f"{first}.{last}", f"{first}_{last}", f"{last}{first}", f"{first[0]}{last}", f"{first}{last[0]}"]:
                if v not in variants:
                    variants.append(v)
        
        # Display what we parsed
        console.print()
        console.print(Panel(
            f"[bold bright_white]Target:[/bold bright_white] {full_name}\n"
            + f"[bold bright_white]ID:[/bold bright_white] {target_id}\n"
            + (f"[bold bright_white]References:[/bold bright_white] {', '.join(references)}\n" if references else "")
            + (f"[bold bright_white]Usernames:[/bold bright_white] {', '.join(variants[:8])}\n" if variants else "")
            + (f"[bold bright_white]Platforms:[/bold bright_white] {', '.join(platforms.keys())}\n" if platforms else "")
            + (f"[bold bright_yellow]Task:[/bold bright_yellow] {natural_task}\n" if natural_task else ""),
            title="[bright_red]DOSSIER INVESTIGATION[/bright_red]",
            border_style="bright_red",
            padding=(1, 2),
        ))
        
        # Set investigation target
        self._nlp.set_target(target_id)
        
        # Pre-populate store with known data
        if self._nlp._store:
            self._nlp._store.add_name(full_name)
            for u in variants:
                self._nlp._store.add_username(u)
            for plat, url in platforms.items():
                self._nlp._store.add_profile(plat, url, "CONFIRMED", "Provided by operator")
        
        # Build the investigation prompt
        refs_text = ""
        if references:
            refs_text = "\nReference fornite dall'operatore:\n" + "\n".join(f"- {r}" for r in references)
        
        platforms_text = ""
        if platforms:
            platforms_text = "\nProfili confermati:\n" + "\n".join(f"- {p}: {u}" for p, u in platforms.items())
        
        # Build prompt with optional natural language task
        if natural_task:
            # Operator gave a specific task — prioritize it
            prompt = (
                f"Target: {full_name}. "
                f"Username: {', '.join(variants[:10])}. "
                f"{refs_text}{platforms_text}\n\n"
                f"TASK SPECIFICO DELL'OPERATORE:\n{natural_task}\n\n"
                f"Esegui questo task usando i tool OSINT disponibili. "
                f"Concentrati su quello che l'operatore ha chiesto."
            )
        else:
            # Full automatic dossier
            prompt = (
                f"Esegui un dossier OSINT completo su {full_name}. "
                f"Username da testare: {', '.join(variants[:10])}. "
                f"{refs_text}{platforms_text}\n\n"
                f"Procedi autonomamente con tutte le fasi:\n"
                f"1. Usa deep_lookup.py come primo comando: python3 /home/atlas/argus-intelligence/strikecore/bin/deep_lookup.py {variants[0] if variants else target_id}"
                + (f" {variants[1]}" if len(variants) > 1 else "") + "\n"
                f"2. Poi sherlock e maigret sulle varianti username\n"
                f"3. holehe + h8mail sulle email trovate\n"
                f"4. Google dorking per telefono e LinkedIn\n"
                f"5. Al termine genera report e grafo\n\n"
                f"Ricorda: NON installare nulla, NON usare instaloader, usa sudo per nmap."
            )
        
        console.print("[bright_cyan]Avvio investigazione...[/bright_cyan]")

        # Capture the ENTIRE run transcript + a structured JSON snapshot into the
        # unified dossieroutputs/ mirror (best-effort; never breaks the run).
        try:
            from core import dossier_output
        except Exception:  # noqa: BLE001
            dossier_output = None  # type: ignore[assignment]

        if dossier_output is None:
            self._nlp.process(prompt)
            return

        from datetime import datetime, timezone
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with dossier_output.record_console(console) as cap:
            self._nlp.process(prompt)
        finished = datetime.now(timezone.utc).isoformat(timespec="seconds")

        try:
            store_data = dict(self._nlp._store.data) if self._nlp._store else {}
            dossier_json = {
                "source": "console",
                "target": full_name,
                "target_id": target_id,
                "references": references,
                "usernames": variants,
                "platforms": platforms,
                "task": natural_task,
                "started_at": started,
                "finished_at": finished,
                "investigation_store": store_data,
            }
            run_dir = dossier_output.new_run_dir(target_id, "console")
            written = dossier_output.write_run(
                run_dir,
                meta={
                    "source": "console",
                    "target": full_name,
                    "target_id": target_id,
                    "task": natural_task,
                    "started_at": started,
                    "finished_at": finished,
                    "references": references,
                },
                dossier_json=dossier_json,
                transcript=cap.get("text", ""),
            )
            console.print(f"[dim]dossier output saved: {run_dir}[/dim]")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[dim]dossier output capture skipped: {exc}[/dim]")


    def _cmd_report_gen(self, args: list) -> None:
        """Generate report + graph for current investigation."""
        if not self._nlp._store:
            console.print("[yellow]No active investigation. Use: investigate <target>[/yellow]")
            return
        target_id = self._nlp._store.target_id
        store_data = self._nlp._store.data
        
        try:
            from core.report_builder import save_report
            md_path, html_path = save_report(store_data, target_id)
            console.print(f"[green]Report saved:[/green] {html_path}")
        except Exception as e:
            console.print(f"[red]Report error: {e}[/red]")
        
        try:
            from core.graph_engine import build_graph
            G, graph_path = build_graph(store_data)
            console.print(f"[green]Graph saved:[/green] {graph_path} ({len(G.nodes)} nodes, {len(G.edges)} edges)")
        except Exception as e:
            console.print(f"[red]Graph error: {e}[/red]")

    def _cmd_controlroom(self, args: list) -> None:
        """Launch the htop-style live agent control room (Textual TUI).

        Usage:
            controlroom            interactive TUI (q quit, s sort, f active-only)
            controlroom --once     one-shot snapshot (no TUI)
        """
        from cli import controlroom
        if "--once" in args or not sys.stdin.isatty():
            console.print(controlroom.snapshot_text())
            return
        try:
            controlroom.run()
        except KeyboardInterrupt:
            console.print("[dim]Control room closed.[/dim]")

    def _cmd_dashboard(self, args: list) -> None:
        """Launch the web dashboard."""
        port = int(args[0]) if args else 5000
        console.print(f"[bright_cyan]Dashboard: http://0.0.0.0:{port}[/bright_cyan]")
        console.print("[dim]Press Ctrl+C to stop[/dim]")
        import subprocess as _sp
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        py = os.path.join(project_root, "strikecore", "bin", "python3")
        dash = os.path.join(project_root, "osint_agent", "dashboard", "app.py")
        try:
            _sp.run([py, dash], cwd=project_root)
        except KeyboardInterrupt:
            console.print("[dim]Dashboard stopped.[/dim]")


    def _cmd_investigate(self, args: list) -> None:
        """Open/create a persistent investigation for a target."""
        if not args:
            console.print("[yellow]Usage: investigate <target_id>[/yellow]")
            console.print("[dim]Example: investigate luigisav[/dim]")
            return
        target = args[0]
        self._nlp.set_target(target)

    def _cmd_upload(self, args: list) -> None:
        """Upload a document to the current investigation."""
        if not args:
            console.print("[yellow]Usage: upload <filepath>[/yellow]")
            return
        self._nlp.upload_document(" ".join(args))

    def _cmd_search(self, args: list) -> None:
        """Search across stored intelligence."""
        if not args:
            console.print("[yellow]Usage: search <query>[/yellow]")
            return
        self._nlp.search(" ".join(args))

    def _cmd_history_clear(self, args: List[str]) -> None:
        """Clear AI conversation history."""
        self._nlp.clear_history()

    def _cmd_exit(self, args: List[str]) -> None:
        self._running = False

    # Command dispatch table
    _commands: Dict[str, Callable[["StrikeCoreShell", List[str]], None]] = {
        "help": _cmd_help,
        "scan": _cmd_scan,
        "agent": _cmd_agent,
        "provider": _cmd_provider,
        "models": _cmd_models,
        "model": _cmd_model,
        "/model": _cmd_model_router,
        "hephaestus": _cmd_hephaestus,
        "/hephaestus": _cmd_hephaestus,
        "controlroom": _cmd_controlroom,
        "/controlroom": _cmd_controlroom,
        "monitor": _cmd_controlroom,
        "tools": _cmd_tools,
        "processes": _cmd_processes,
        "kill": _cmd_kill,
        "logs": _cmd_logs,
        "report": _cmd_report,
        "cache": _cmd_cache,
        "config": _cmd_config,
        "telegram": _cmd_telegram,
        "status": _cmd_status,
        "gpu": _cmd_gpu,
        "clear": _cmd_clear,
        "dossier": _cmd_dossier,
        "report": _cmd_report_gen,
        "dashboard": _cmd_dashboard,
        "investigate": _cmd_investigate,
        "upload": _cmd_upload,
        "search": _cmd_search,
        "install": _cmd_install,
        "clear-chat": _cmd_history_clear,
        "exit": _cmd_exit,
        "quit": _cmd_exit,
    }

    # -- Main loop ------------------------------------------------------------

    def run(self) -> None:
        """Start the interactive REPL loop."""
        display_banner()

        console.print(
            f"  [dim]Session:[/dim]  [cyan]{self.session.session_id}[/cyan]"
        )
        console.print(
            f"  [dim]Provider:[/dim] [bold magenta]{self._active_provider}:{self._active_model}[/bold magenta]"
        )
        console.print(
            f"  [dim]Type [bold]help[/bold] for available commands.[/dim]\n"
        )

        session = PromptSession(
            history=FileHistory(str(_HISTORY_FILE)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=StrikeCoreCompleter(self),
            style=_PT_STYLE,
            bottom_toolbar=self._toolbar_callback,
            mouse_support=False,
        )

        while self._running:
            try:
                prompt_str = self._build_prompt()
                line = session.prompt(prompt_str)
                self._dispatch(line)
            except KeyboardInterrupt:
                console.print("\n[dim]Press Ctrl+C again or type 'exit' to quit.[/dim]")
                try:
                    line = session.prompt(prompt_str)
                    if line.strip().lower() in ("exit", "quit"):
                        break
                    self._dispatch(line)
                except KeyboardInterrupt:
                    break
            except EOFError:
                break

        self._shutdown()

    def _shutdown(self) -> None:
        """Graceful shutdown routine."""
        console.print()
        if self.background_processes:
            console.print(
                f"[{THEME['warning']}]Cleaning up {len(self.background_processes)} background process(es)...[/{THEME['warning']}]"
            )
            self.background_processes.clear()

        console.print(
            Panel(
                f"[bright_white]Session [cyan]{self.session.session_id}[/cyan] ended.[/bright_white]\n"
                f"[dim]Duration: {self.status_bar.session_elapsed}  |  Commands: {self.session.command_count}[/dim]",
                border_style="bright_red",
                padding=(1, 2),
            )
        )
        # Self-audit: score tool performance for this session
        try:
            from bin.self_audit import SelfAudit
            sa = SelfAudit(session_id=self.session.session_id)
            sa.run()
        except Exception:
            pass  # best-effort, never block shutdown

        console.print("[dim]Goodbye.[/dim]\n")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _mask_secrets(data: dict, _depth: int = 0) -> dict:
    """Return a copy of *data* with API keys / tokens partially masked."""
    masked = {}
    secret_keys = {"api_key", "bot_token", "twilio_token", "twilio_sid", "auth_token", "password", "secret"}
    for k, v in data.items():
        if isinstance(v, dict):
            masked[k] = _mask_secrets(v, _depth + 1)
        elif k in secret_keys and isinstance(v, str) and len(v) > 8:
            masked[k] = v[:4] + "*" * (len(v) - 8) + v[-4:]
        else:
            masked[k] = v
    return masked


def _get_gpu_memory() -> str | None:
    """Return a human-readable GPU memory usage string, or None."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(",")
            if len(parts) == 2:
                used = int(parts[0].strip())
                total = int(parts[1].strip())
                pct = (used / total * 100) if total > 0 else 0
                return f"{used} / {total} MB ({pct:.1f}%)"
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_shell() -> None:
    """Create and start the interactive StrikeCore shell."""
    shell = StrikeCoreShell()
    shell.run()


if __name__ == "__main__":
    run_shell()
