"""ASCII art banner and system compatibility checks for StrikeCore.

Provides a visually striking startup banner rendered through Rich and a
comprehensive system diagnostics routine that validates the runtime
environment before an assessment session begins.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Tuple

import psutil
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

__all__ = ["display_banner", "run_system_checks"]

VERSION = "v1.0.0"

console = Console()

# ---------------------------------------------------------------------------
# ASCII art
# ---------------------------------------------------------------------------

_BANNER_ART = r"""
 ███████╗████████╗██████╗ ██╗██╗  ██╗███████╗ ██████╗ ██████╗ ██████╗ ███████╗
 ██╔════╝╚══██╔══╝██╔══██╗██║██║ ██╔╝██╔════╝██╔════╝██╔═══██╗██╔══██╗██╔════╝
 ███████╗   ██║   ██████╔╝██║█████╔╝ █████╗  ██║     ██║   ██║██████╔╝█████╗
 ╚════██║   ██║   ██╔══██╗██║██╔═██╗ ██╔══╝  ██║     ██║   ██║██╔══██╗██╔══╝
 ███████║   ██║   ██║  ██║██║██║  ██╗███████╗╚██████╗╚██████╔╝██║  ██║███████╗
 ╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝
"""

_TAGLINE = "AI-Driven Offensive Security Assessment Framework"

# ---------------------------------------------------------------------------
# Banner display
# ---------------------------------------------------------------------------


def display_banner() -> None:
    """Render the StrikeCore ASCII art banner to the terminal."""
    banner_text = Text(_BANNER_ART, style="bold red")
    tagline = Text(f"{_TAGLINE}\n{VERSION}", style="bright_white", justify="center")

    banner_group = Text()
    banner_group.append_text(banner_text)
    banner_group.append("\n")
    banner_group.append_text(tagline)

    panel = Panel(
        Align.center(banner_group),
        border_style="bright_red",
        padding=(1, 2),
        subtitle=f"[dim]{VERSION}[/dim]",
        subtitle_align="right",
    )
    console.print()
    console.print(panel)
    console.print()


# ---------------------------------------------------------------------------
# System checks
# ---------------------------------------------------------------------------

# Minimum requirements
_MIN_PYTHON = (3, 10)
_MIN_RAM_GB = 4.0
_MIN_CORES = 2

# Security tools to look for on PATH
_SECURITY_TOOLS: List[Tuple[str, str]] = [
    ("nmap", "Network scanner"),
    ("masscan", "Fast port scanner"),
    ("nikto", "Web server scanner"),
    ("sqlmap", "SQL injection tool"),
    ("ffuf", "Web fuzzer"),
    ("gobuster", "Directory brute-forcer"),
    ("nuclei", "Vulnerability scanner"),
    ("subfinder", "Subdomain discovery"),
    ("httpx", "HTTP probe toolkit"),
    ("amass", "Attack surface mapper"),
    ("wpscan", "WordPress scanner"),
    ("hydra", "Login brute-forcer"),
    ("john", "Password cracker"),
    ("hashcat", "GPU password cracker"),
    ("metasploit-framework", "Exploitation framework"),
    ("burpsuite", "Web app proxy"),
    ("wireshark", "Packet analyser"),
    ("testssl.sh", "TLS/SSL tester"),
    ("whatweb", "Web fingerprinter"),
    ("dirsearch", "Web path scanner"),
]

# Alternate binary names (some tools install under different names)
_TOOL_ALIASES: Dict[str, List[str]] = {
    "metasploit-framework": ["msfconsole", "msfvenom"],
    "burpsuite": ["burpsuite", "BurpSuiteCommunity", "BurpSuitePro"],
    "testssl.sh": ["testssl.sh", "testssl"],
    "wireshark": ["wireshark", "tshark"],
}


def _check_binary(name: str) -> bool:
    """Return True if *name* (or any of its known aliases) is on PATH."""
    candidates = _TOOL_ALIASES.get(name, [name])
    return any(shutil.which(c) is not None for c in candidates)


def _cmd_output(cmd: List[str], timeout: int = 5) -> str | None:
    """Run a command and return stripped stdout, or None on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _detect_gpu() -> Dict[str, Any]:
    """Attempt to detect NVIDIA or AMD GPUs."""
    info: Dict[str, Any] = {
        "detected": False,
        "vendor": None,
        "name": None,
        "memory_mb": None,
        "driver": None,
    }

    # Try NVIDIA first
    nvidia_out = _cmd_output(
        ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"]
    )
    if nvidia_out:
        parts = [p.strip() for p in nvidia_out.split("\n")[0].split(",")]
        info["detected"] = True
        info["vendor"] = "NVIDIA"
        if len(parts) >= 1:
            info["name"] = parts[0]
        if len(parts) >= 2:
            try:
                info["memory_mb"] = int(float(parts[1]))
            except ValueError:
                pass
        if len(parts) >= 3:
            info["driver"] = parts[2]
        return info

    # Try AMD ROCm
    rocm_out = _cmd_output(["rocm-smi", "--showproductname"])
    if rocm_out:
        info["detected"] = True
        info["vendor"] = "AMD"
        for line in rocm_out.splitlines():
            if "GPU" in line or "Card" in line:
                info["name"] = line.strip()
                break
        return info

    return info


def run_system_checks() -> Dict[str, Any]:
    """Execute all system compatibility checks and return structured results.

    Returns a dict with keys for each check category plus a top-level
    ``all_passed`` boolean.  The dict is also rendered as a Rich table
    to the console.
    """
    results: Dict[str, Any] = {}

    # -- Python version -------------------------------------------------------
    py_ver = sys.version_info
    py_ok = py_ver >= _MIN_PYTHON
    results["python"] = {
        "label": "Python version",
        "value": f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}",
        "required": f">= {_MIN_PYTHON[0]}.{_MIN_PYTHON[1]}",
        "passed": py_ok,
    }

    # -- OS / Architecture ----------------------------------------------------
    os_name = platform.system()
    arch = platform.machine()
    results["os"] = {
        "label": "Operating system",
        "value": f"{os_name} {platform.release()} ({arch})",
        "required": "Linux / macOS / WSL",
        "passed": os_name in ("Linux", "Darwin") or "microsoft" in platform.release().lower(),
    }

    # -- RAM ------------------------------------------------------------------
    ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
    results["ram"] = {
        "label": "System RAM",
        "value": f"{ram_gb} GB",
        "required": f">= {_MIN_RAM_GB} GB",
        "passed": ram_gb >= _MIN_RAM_GB,
    }

    # -- CPU cores ------------------------------------------------------------
    cores = psutil.cpu_count(logical=True) or 0
    results["cpu"] = {
        "label": "CPU cores (logical)",
        "value": str(cores),
        "required": f">= {_MIN_CORES}",
        "passed": cores >= _MIN_CORES,
    }

    # -- GPU ------------------------------------------------------------------
    gpu = _detect_gpu()
    results["gpu"] = {
        "label": "GPU (CUDA/ROCm)",
        "value": (
            f"{gpu['vendor']} {gpu['name']}"
            + (f" ({gpu['memory_mb']} MB)" if gpu["memory_mb"] else "")
            if gpu["detected"]
            else "Not detected"
        ),
        "required": "Optional (speeds up hashcat/ML)",
        "passed": gpu["detected"],
        "optional": True,
    }
    results["gpu_detail"] = gpu

    # -- Docker ---------------------------------------------------------------
    docker_ok = _check_binary("docker")
    docker_ver = None
    if docker_ok:
        docker_ver = _cmd_output(["docker", "--version"])
    results["docker"] = {
        "label": "Docker",
        "value": docker_ver or ("Not found" if not docker_ok else "installed"),
        "required": "Recommended",
        "passed": docker_ok,
        "optional": True,
    }

    # -- Security tools -------------------------------------------------------
    tool_results: Dict[str, bool] = {}
    for tool_name, _desc in _SECURITY_TOOLS:
        tool_results[tool_name] = _check_binary(tool_name)
    installed_count = sum(1 for v in tool_results.values() if v)
    total_count = len(tool_results)
    results["security_tools"] = {
        "label": "Security tools",
        "value": f"{installed_count}/{total_count} detected",
        "required": "As many as possible",
        "passed": installed_count > 0,
        "optional": True,
        "details": tool_results,
    }

    # -- Aggregate pass/fail --------------------------------------------------
    critical = [v for k, v in results.items() if isinstance(v, dict) and "passed" in v and not v.get("optional")]
    results["all_critical_passed"] = all(c["passed"] for c in critical)
    results["all_passed"] = all(
        v["passed"] for v in results.values() if isinstance(v, dict) and "passed" in v
    )

    # -- Render table ---------------------------------------------------------
    _render_checks_table(results)

    return results


def _render_checks_table(results: Dict[str, Any]) -> None:
    """Render the system check results as a styled Rich table."""
    table = Table(
        title="System Compatibility Checks",
        title_style="bold bright_white",
        border_style="bright_cyan",
        show_lines=True,
        padding=(0, 1),
    )
    table.add_column("Check", style="bright_white", min_width=20)
    table.add_column("Status", justify="center", min_width=6)
    table.add_column("Detected", style="cyan", min_width=30)
    table.add_column("Requirement", style="dim", min_width=24)

    _PASS = "[bold green]\u2714[/bold green]"
    _FAIL = "[bold red]\u2718[/bold red]"
    _WARN = "[bold yellow]~[/bold yellow]"

    for key, value in results.items():
        if not isinstance(value, dict) or "label" not in value:
            continue

        passed = value["passed"]
        optional = value.get("optional", False)

        if passed:
            status = _PASS
        elif optional:
            status = _WARN
        else:
            status = _FAIL

        table.add_row(value["label"], status, str(value["value"]), value["required"])

    # Append individual security tools as a sub-section
    sec_tools = results.get("security_tools", {}).get("details", {})
    if sec_tools:
        table.add_section()
        for tool_name, found in sorted(sec_tools.items()):
            desc_map = dict(_SECURITY_TOOLS)
            desc = desc_map.get(tool_name, "")
            status = _PASS if found else _WARN
            table.add_row(
                f"  {tool_name}",
                status,
                f"{'Installed' if found else 'Not found'} - {desc}",
                "Optional",
            )

    console.print()
    console.print(table)
    console.print()

    # Summary line
    if results.get("all_critical_passed"):
        console.print(
            "[bold green]All critical checks passed.[/bold green] "
            "StrikeCore is ready to operate."
        )
    else:
        console.print(
            "[bold red]Some critical checks failed.[/bold red] "
            "Please resolve the issues above before proceeding."
        )
    console.print()
