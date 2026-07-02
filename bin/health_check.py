#!/usr/bin/env python3
"""StrikeCore Health Check — Pre-flight infrastructure and tool verification."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.table import Table

console = Console()

CRITICAL_TOOLS = [
    "sherlock", "maigret", "holehe", "h8mail", "phoneinfoga",
    "blackbird", "nexfil", "exiftool", "theHarvester",
    "nmap", "subfinder", "httpx", "nuclei",
    "socialscan", "mosint", "gallery-dl", "yt-dlp",
]

OPTIONAL_TOOLS = [
    "sqlmap", "nikto", "gobuster", "ffuf", "katana",
    "shodan", "censys", "crosslinked", "truecallerjs",
]


def _check_socket(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
        return True
    except (socket.error, OSError):
        return False


def _check_url(url: str, timeout: float = 3.0) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "StrikeCore-HealthCheck"})
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except Exception:
        return False


class HealthCheck:
    """Run all infrastructure checks and collect results."""

    def __init__(self, quick: bool = False):
        self.quick = quick
        self.results: list[dict] = []

    def _add(self, name: str, passed: bool, detail: str = "", critical: bool = False):
        self.results.append({
            "name": name, "passed": passed, "detail": detail, "critical": critical,
        })

    def check_tor(self):
        # Docker-aware: under compose, Tor lives in a sibling container reached
        # via TOR_HOST (e.g. "tor"), not localhost. Fall back to 127.0.0.1 for
        # bare-metal installs. Same for the SOCKS/Control ports.
        host = os.environ.get("TOR_HOST", "127.0.0.1")
        socks_port = int(os.environ.get("TOR_SOCKS_PORT", "9050"))
        ctrl_port = int(os.environ.get("TOR_CONTROL_PORT", "9051"))
        socks = _check_socket(host, socks_port)
        self._add(f"Tor SOCKS5 ({host}:{socks_port})", socks,
                   "Running" if socks else "Not running", critical=True)
        ctrl = _check_socket(host, ctrl_port)
        self._add(f"Tor Control ({host}:{ctrl_port})", ctrl,
                   "Accessible" if ctrl else "Not accessible")

    def check_tools(self):
        found = 0
        missing = []
        for tool in CRITICAL_TOOLS:
            if shutil.which(tool):
                found += 1
            else:
                missing.append(tool)
        total = len(CRITICAL_TOOLS)
        ok = found == total
        detail = f"{found}/{total}" + (f" missing: {', '.join(missing)}" if missing else "")
        self._add("Critical OSINT tools", ok, detail, critical=True)

        if not self.quick:
            found_opt = sum(1 for t in OPTIONAL_TOOLS if shutil.which(t))
            self._add("Optional tools", found_opt > 0,
                       f"{found_opt}/{len(OPTIONAL_TOOLS)}")

    def check_ig_session(self):
        path = Path.home() / ".strikecore" / "ig_session"
        exists = path.exists() and path.stat().st_size > 10
        self._add("Instagram session", exists,
                   "Configured" if exists else "Not set (~/.strikecore/ig_session)")

    def check_ollama(self):
        # Docker-aware: honor OLLAMA_HOST/OLLAMA_PORT when Ollama runs elsewhere
        # (sibling container or host gateway); default to localhost bare-metal.
        host = os.environ.get("OLLAMA_HOST", "127.0.0.1")
        port = int(os.environ.get("OLLAMA_PORT", "11434"))
        if self.quick:
            running = _check_socket(host, port)
            self._add("Ollama", running,
                       "Port open" if running else "Not running")
            return
        try:
            data = json.loads(
                urllib.request.urlopen(
                    f"http://{host}:{port}/api/tags", timeout=3
                ).read()
            )
            models = [m["name"] for m in data.get("models", [])]
            self._add("Ollama", bool(models),
                       f"Models: {', '.join(models[:3])}" if models else "No models loaded")
        except Exception:
            self._add("Ollama", False, "Not running")

    def check_api_keys(self):
        try:
            from config.settings import get_settings
            s = get_settings()
            keys_found = []
            for name, key_path in [
                ("Anthropic", "ai.anthropic.api_key"),
                ("Ollama", "ai.ollama.base_url"),
            ]:
                val = s.get(key_path, "")
                if val:
                    keys_found.append(name)
            ok = len(keys_found) > 0
            self._add("AI provider keys", ok,
                       f"Configured: {', '.join(keys_found)}" if ok else "No AI provider configured",
                       critical=True)
        except Exception as e:
            self._add("AI provider keys", False, str(e), critical=True)

    def check_disk(self):
        usage = shutil.disk_usage("/")
        free_gb = usage.free / (1024 ** 3)
        ok = free_gb > 5.0
        self._add("Disk space", ok, f"{free_gb:.1f} GB free")

    def run_all(self) -> list[dict]:
        self.results = []
        self.check_tor()
        self.check_tools()
        self.check_ig_session()
        self.check_ollama()
        self.check_api_keys()
        self.check_disk()
        return self.results

    def display(self):
        table = Table(
            title="StrikeCore Health Check",
            title_style="bold bright_white",
            border_style="bright_cyan",
            show_lines=True,
            padding=(0, 1),
        )
        table.add_column("Check", style="bright_white", min_width=24)
        table.add_column("Status", justify="center", min_width=6)
        table.add_column("Detail", style="dim", min_width=30)

        for r in self.results:
            if r["passed"]:
                status = "[bold green]\u2714[/bold green]"
            elif r.get("critical"):
                status = "[bold red]\u2718[/bold red]"
            else:
                status = "[bold yellow]~[/bold yellow]"
            table.add_row(r["name"], status, r["detail"])

        console.print()
        console.print(table)
        console.print()

        critical_fail = [r for r in self.results if not r["passed"] and r.get("critical")]
        if critical_fail:
            console.print("[bold red]Critical checks failed.[/bold red]")
        else:
            console.print("[bold green]All critical checks passed.[/bold green]")
        console.print()


def main():
    parser = argparse.ArgumentParser(description="StrikeCore infrastructure health check")
    parser.add_argument("--quick", action="store_true", help="Skip slow checks")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    hc = HealthCheck(quick=args.quick)
    results = hc.run_all()

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        hc.display()

    critical_ok = all(r["passed"] for r in results if r.get("critical"))
    sys.exit(0 if critical_ok else 1)


if __name__ == "__main__":
    main()
