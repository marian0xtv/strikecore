"""Rich rendering utilities for the StrikeCore terminal UI.

Provides a consistent visual language across the entire application --
vulnerability cards, tool execution panels, progress bars, tables,
agent/provider status indicators, and a persistent bottom status bar.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text

__all__ = [
    "render_vulnerability",
    "render_tool_execution",
    "render_progress",
    "render_table",
    "render_agent_status",
    "render_provider_status",
    "create_status_bar",
    "THEME",
]

console = Console()

# ---------------------------------------------------------------------------
# Colour theme
# ---------------------------------------------------------------------------

THEME = {
    # Severity colours
    "critical": "bold white on red",
    "high": "bold bright_red",
    "medium": "bold yellow",
    "low": "bold green",
    "info": "bold bright_blue",
    # Severity border colours (for panels)
    "critical_border": "bright_red",
    "high_border": "red",
    "medium_border": "yellow",
    "low_border": "green",
    "info_border": "bright_blue",
    # UI elements
    "header": "bold bright_white",
    "subheader": "bold cyan",
    "label": "bright_white",
    "value": "cyan",
    "muted": "dim white",
    "success": "bold green",
    "error": "bold red",
    "warning": "bold yellow",
    "accent": "bold magenta",
    # Status
    "running": "bold bright_green",
    "idle": "dim green",
    "failed": "bold red",
    "pending": "bold yellow",
    "disabled": "dim white",
}

_SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")


def _severity_style(severity: str) -> str:
    """Return the theme style for a severity level."""
    key = severity.lower()
    return THEME.get(key, THEME["info"])


def _severity_border(severity: str) -> str:
    """Return the border colour for a severity level."""
    key = f"{severity.lower()}_border"
    return THEME.get(key, THEME["info_border"])


def _severity_label(severity: str) -> str:
    """Return a padded, uppercased severity tag."""
    return f" {severity.upper()} "


# ---------------------------------------------------------------------------
# Vulnerability card
# ---------------------------------------------------------------------------


def render_vulnerability(vuln_data: Dict[str, Any]) -> None:
    """Display a coloured vulnerability card panel.

    Expected keys in *vuln_data*:

    - ``severity``: critical | high | medium | low | info
    - ``title``: short title
    - ``description``: longer description (optional)
    - ``cvss``: CVSS score (optional)
    - ``cve``: CVE identifier (optional)
    - ``affected``: affected component (optional)
    - ``evidence``: evidence / proof string (optional)
    - ``remediation``: fix recommendation (optional)
    - ``references``: list of URLs (optional)
    - ``tool``: tool that found it (optional)
    """
    severity = vuln_data.get("severity", "info").lower()
    title = vuln_data.get("title", "Untitled Finding")
    style = _severity_style(severity)
    border = _severity_border(severity)

    # Header line
    sev_tag = Text(_severity_label(severity), style=style)
    header = Text()
    header.append_text(sev_tag)
    header.append(f"  {title}", style=THEME["header"])

    # Build body rows
    body_parts: List[Text] = []

    if vuln_data.get("cve"):
        row = Text()
        row.append("CVE:          ", style=THEME["label"])
        row.append(str(vuln_data["cve"]), style=THEME["value"])
        body_parts.append(row)

    if vuln_data.get("cvss") is not None:
        row = Text()
        row.append("CVSS:         ", style=THEME["label"])
        score = float(vuln_data["cvss"])
        score_style = THEME["critical"] if score >= 9 else (
            THEME["high"] if score >= 7 else (
                THEME["medium"] if score >= 4 else THEME["low"]
            )
        )
        row.append(f"{score:.1f}", style=score_style)
        body_parts.append(row)

    if vuln_data.get("affected"):
        row = Text()
        row.append("Affected:     ", style=THEME["label"])
        row.append(str(vuln_data["affected"]), style=THEME["value"])
        body_parts.append(row)

    if vuln_data.get("tool"):
        row = Text()
        row.append("Found by:     ", style=THEME["label"])
        row.append(str(vuln_data["tool"]), style=THEME["accent"])
        body_parts.append(row)

    if vuln_data.get("description"):
        body_parts.append(Text())
        row = Text()
        row.append("Description:\n", style=THEME["subheader"])
        row.append(str(vuln_data["description"]), style=THEME["muted"])
        body_parts.append(row)

    if vuln_data.get("evidence"):
        body_parts.append(Text())
        row = Text()
        row.append("Evidence:\n", style=THEME["subheader"])
        row.append(str(vuln_data["evidence"]), style="dim cyan")
        body_parts.append(row)

    if vuln_data.get("remediation"):
        body_parts.append(Text())
        row = Text()
        row.append("Remediation:\n", style=THEME["subheader"])
        row.append(str(vuln_data["remediation"]), style=THEME["success"])
        body_parts.append(row)

    if vuln_data.get("references"):
        body_parts.append(Text())
        row = Text()
        row.append("References:\n", style=THEME["subheader"])
        for ref in vuln_data["references"]:
            row.append(f"  - {ref}\n", style="underline bright_blue")
        body_parts.append(row)

    # Combine
    body = Text("\n").join(body_parts) if body_parts else Text("No additional details.")
    content = Group(header, Text(), body)

    panel = Panel(
        content,
        border_style=border,
        title=f"[{border}]Vulnerability Finding[/{border}]",
        title_align="left",
        subtitle=f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
        subtitle_align="right",
        padding=(1, 2),
    )
    console.print(panel)
    console.print()


# ---------------------------------------------------------------------------
# Tool execution panel
# ---------------------------------------------------------------------------


def render_tool_execution(
    tool_name: str,
    params: Dict[str, Any],
    output: str,
    *,
    success: bool = True,
    duration: float | None = None,
) -> None:
    """Display a bordered panel showing a tool invocation and its output."""
    status_icon = "\u2714" if success else "\u2718"
    status_style = THEME["success"] if success else THEME["error"]

    # Header
    header = Text()
    header.append(f" {status_icon} ", style=status_style)
    header.append(tool_name, style="bold bright_white")
    if duration is not None:
        header.append(f"  ({duration:.2f}s)", style=THEME["muted"])

    # Parameters
    params_text = Text()
    params_text.append("Parameters:\n", style=THEME["subheader"])
    if params:
        for k, v in params.items():
            params_text.append(f"  {k}: ", style=THEME["label"])
            params_text.append(f"{v}\n", style=THEME["value"])
    else:
        params_text.append("  (none)\n", style=THEME["muted"])

    # Output (truncate very long output)
    max_output_lines = 50
    output_lines = output.splitlines()
    truncated = len(output_lines) > max_output_lines
    display_output = "\n".join(output_lines[:max_output_lines])
    if truncated:
        display_output += f"\n... ({len(output_lines) - max_output_lines} more lines)"

    output_text = Text()
    output_text.append("Output:\n", style=THEME["subheader"])
    output_text.append(display_output, style="white")

    content = Group(header, Text(), params_text, output_text)

    border = "green" if success else "red"
    panel = Panel(
        content,
        border_style=border,
        title=f"[{border}]Tool Execution[/{border}]",
        title_align="left",
        padding=(1, 2),
    )
    console.print(panel)
    console.print()


# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------


def render_progress(task: str, total: int) -> Progress:
    """Create and return a Rich Progress bar for *task* with *total* steps.

    Usage::

        progress = render_progress("Scanning ports", 65535)
        with progress:
            task_id = progress.task_ids[0]
            for port in range(1, 65536):
                # ... do work ...
                progress.advance(task_id)
    """
    progress = Progress(
        SpinnerColumn("dots", style="bright_cyan"),
        TextColumn("[bold bright_white]{task.description}"),
        BarColumn(bar_width=40, style="cyan", complete_style="bright_green", finished_style="green"),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    )
    progress.add_task(task, total=total)
    return progress


# ---------------------------------------------------------------------------
# Styled table
# ---------------------------------------------------------------------------


def render_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    title: str | None = None,
    caption: str | None = None,
    show_lines: bool = False,
) -> None:
    """Render a styled table to the console."""
    table = Table(
        title=title,
        title_style=THEME["header"],
        caption=caption,
        caption_style=THEME["muted"],
        border_style="bright_cyan",
        header_style="bold bright_white on grey23",
        show_lines=show_lines,
        padding=(0, 1),
    )
    for i, header in enumerate(headers):
        justify = "left" if i == 0 else "center"
        table.add_column(header, justify=justify, style=THEME["value"])

    for row in rows:
        table.add_row(*(str(cell) for cell in row))

    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# Agent status panel
# ---------------------------------------------------------------------------


def render_agent_status(agent_name: str, status: str, *, details: Dict[str, Any] | None = None) -> None:
    """Display a compact agent status panel.

    *status* should be one of: running, idle, failed, pending, disabled.
    """
    status_lower = status.lower()
    style = THEME.get(status_lower, THEME["muted"])

    icons = {
        "running": "\u25b6",
        "idle": "\u25cf",
        "failed": "\u2718",
        "pending": "\u25cb",
        "disabled": "\u25cb",
    }
    icon = icons.get(status_lower, "\u25cf")

    header = Text()
    header.append(f" {icon} ", style=style)
    header.append(agent_name, style="bold bright_white")
    header.append(f"  [{status.upper()}]", style=style)

    parts = [header]

    if details:
        info = Text()
        for k, v in details.items():
            info.append(f"  {k}: ", style=THEME["label"])
            info.append(f"{v}\n", style=THEME["value"])
        parts.append(info)

    border = {
        "running": "bright_green",
        "idle": "green",
        "failed": "red",
        "pending": "yellow",
        "disabled": "dim white",
    }.get(status_lower, "cyan")

    panel = Panel(
        Group(*parts),
        border_style=border,
        padding=(0, 2),
    )
    console.print(panel)


# ---------------------------------------------------------------------------
# Provider status panel
# ---------------------------------------------------------------------------


def render_provider_status(provider_info: Dict[str, Any]) -> None:
    """Display provider health information.

    Expected keys:

    - ``provider``: provider name
    - ``model``: active model name
    - ``status``: healthy | degraded | offline
    - ``latency_ms``: last measured latency in milliseconds (optional)
    - ``total_tokens``: tokens used this session (optional)
    - ``cost_usd``: estimated cost in USD (optional)
    - ``fallback_chain``: list of fallback provider names (optional)
    """
    provider = provider_info.get("provider", "unknown")
    model = provider_info.get("model", "unknown")
    status = provider_info.get("status", "unknown").lower()
    latency = provider_info.get("latency_ms")

    status_style_map = {
        "healthy": THEME["success"],
        "degraded": THEME["warning"],
        "offline": THEME["error"],
    }
    status_style = status_style_map.get(status, THEME["muted"])

    status_icons = {
        "healthy": "\u2714",
        "degraded": "\u26a0",
        "offline": "\u2718",
    }
    icon = status_icons.get(status, "?")

    table = Table(show_header=False, border_style="cyan", padding=(0, 2), expand=True)
    table.add_column("Key", style=THEME["label"], min_width=16)
    table.add_column("Value", style=THEME["value"])

    table.add_row("Provider", f"[bold]{provider}[/bold]")
    table.add_row("Model", model)
    table.add_row("Status", f"[{status_style}]{icon} {status.upper()}[/{status_style}]")

    if latency is not None:
        latency_style = (
            THEME["success"] if latency < 200 else (THEME["warning"] if latency < 1000 else THEME["error"])
        )
        table.add_row("Latency", f"[{latency_style}]{latency:.0f}ms[/{latency_style}]")

    if provider_info.get("total_tokens") is not None:
        table.add_row("Tokens (session)", f"{provider_info['total_tokens']:,}")

    if provider_info.get("cost_usd") is not None:
        table.add_row("Est. Cost", f"${provider_info['cost_usd']:.4f}")

    if provider_info.get("fallback_chain"):
        chain_str = " -> ".join(provider_info["fallback_chain"])
        table.add_row("Fallback Chain", chain_str)

    border = {"healthy": "green", "degraded": "yellow", "offline": "red"}.get(status, "cyan")
    panel = Panel(
        table,
        title=f"[{border}]Provider Health[/{border}]",
        title_align="left",
        border_style=border,
        padding=(1, 1),
    )
    console.print(panel)
    console.print()


# ---------------------------------------------------------------------------
# Status bar
# ---------------------------------------------------------------------------


class StatusBar:
    """Persistent bottom status bar state container.

    This holds the mutable state that the prompt_toolkit bottom toolbar
    callback reads from.  Update attributes freely; the toolbar re-renders
    on every keypress.
    """

    def __init__(self) -> None:
        self.active_processes: int = 0
        self.session_start: datetime = datetime.now()
        self.provider: str = "none"
        self.model: str = "none"
        self.last_tool: str = "none"

    @property
    def session_elapsed(self) -> str:
        delta = datetime.now() - self.session_start
        total_seconds = int(delta.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def format_rich(self) -> str:
        """Return a Rich-markup string suitable for console.print."""
        return (
            f"[dim]Procs:[/dim] [{THEME['value']}]{self.active_processes}[/{THEME['value']}]  "
            f"[dim]Session:[/dim] [{THEME['value']}]{self.session_elapsed}[/{THEME['value']}]  "
            f"[dim]Provider:[/dim] [{THEME['accent']}]{self.provider}:{self.model}[/{THEME['accent']}]  "
            f"[dim]Last tool:[/dim] [{THEME['value']}]{self.last_tool}[/{THEME['value']}]"
        )

    def format_toolbar(self) -> str:
        """Return a plain-text string for use in a prompt_toolkit toolbar."""
        return (
            f" Procs: {self.active_processes}  |  "
            f"Session: {self.session_elapsed}  |  "
            f"Provider: {self.provider}:{self.model}  |  "
            f"Last tool: {self.last_tool} "
        )


def create_status_bar() -> StatusBar:
    """Create and return a new :class:`StatusBar` instance."""
    return StatusBar()
