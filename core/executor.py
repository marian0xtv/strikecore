"""
Shell command executor with live output streaming for StrikeCore.

Provides async execution of security tool commands with live Rich console
streaming, timeout handling (SIGTERM then SIGKILL), command sanitisation
against an allowlist of known tool binaries, and a persistent audit trail.
"""

from __future__ import annotations

import asyncio
import warnings
warnings.filterwarnings("ignore", message=".*Event loop is closed.*")
warnings.filterwarnings("ignore", category=ResourceWarning)
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AUDIT_DIR = Path.home() / ".strikecore" / "audit"
_KILL_GRACE_SECONDS = 5  # time between SIGTERM and SIGKILL

# Allowed binaries -- security tools plus common shell utilities the AI
# may legitimately compose into pipelines.
ALLOWED_BINARIES: frozenset[str] = frozenset({
    # -- Security tools --
    "nmap", "masscan", "rustscan", "subfinder", "amass", "httpx", "nuclei",
    "nikto", "gobuster", "ffuf", "feroxbuster", "sqlmap", "zaproxy",
    "john", "hashcat", "hydra", "aircrack-ng", "airodump-ng", "aireplay-ng",
    "airmon-ng", "reaver", "wifite", "kismet",
    "wireshark", "tshark", "tcpdump", "hping3", "netcat", "nc", "ncat",
    "binwalk", "gdb", "radare2", "r2", "ghidraRun", "objdump", "readelf",
    "strace", "ltrace", "ropper", "checksec",
    "volatility", "vol.py", "vol3", "autopsy", "foremost", "bulk_extractor",
    "exiftool", "steghide", "yara", "clamscan", "clamav",
    "rkhunter", "chkrootkit", "lynis",
    "docker", "kubectl", "trivy", "grype", "dive", "hadolint",
    "kube-hunter", "kube-bench",
    "shodan", "theHarvester", "theharvester", "recon-ng", "maltego",
    "spiderfoot", "sherlock", "holehe", "photon",
    "enum4linux", "smbclient", "crackmapexec", "cme", "nxc",
    "bloodhound", "evil-winrm",
    "impacket-smbserver", "impacket-psexec", "impacket-wmiexec",
    "impacket-smbexec", "impacket-atexec", "impacket-dcomexec",
    "impacket-secretsdump", "impacket-getTGT", "impacket-getST",
    "impacket-getNPUsers", "impacket-getADUsers",
    "responder", "bettercap", "ettercap", "arpspoof",
    "wfuzz", "arjun", "paramspider", "gau", "waybackurls",
    "dirsearch", "whatweb", "wappalyzer", "wafw00f",
    "testssl.sh", "testssl", "sslscan",
    "dnsrecon", "fierce", "knockpy", "sublist3r", "dnsenum",
    "xsstrike", "dalfox", "commix", "tplmap", "ssrfmap", "nosqlmap",
    "jwt_tool", "cewl", "crunch", "ophcrack",
    "medusa", "patator", "crowbar", "ncrack",
    "pacu", "prowler", "scout", "cloudfox", "enumerate-iam",
    "aws", "gcloud", "az",
    "trufflehog", "gitleaks", "semgrep", "bandit", "snyk",
    "retire", "dependency-check",
    "linpeas.sh", "linpeas", "winpeas", "winPEASany.exe", "pspy",
    "pwncat",
    "chisel", "ligolo-ng", "socat", "proxychains", "tor", "anonsurf",
    "msfconsole", "msfvenom", "searchsploit",
    "afl-fuzz", "honggfuzz", "radamsa",
    "apktool", "jadx", "frida", "objection", "drozer", "mobsf", "adb",
    "setoolkit", "gophish", "king-phisher", "evilginx2", "beef-xss",
    "openssl", "gpg", "hashid", "hash-identifier", "rsatool",
    "katana", "gospider", "hakrawler", "wpscan", "joomscan", "droopescan",
    "caido", "naabu",
    "netdiscover", "nbtscan", "snmpwalk", "onesixtyone", "dmitry", "p0f",
    "arp-scan", "fluxion", "fern-wifi-cracker",
    "assetfinder", "censys",
    # -- SOCINT / Social Intelligence --
    "sherlock", "maigret", "whatsmyname", "holehe", "h8mail",
    "ghunt", "phoneinfoga", "social-analyzer", "socialscan",
    "gallery-dl", "yt-dlp", "instaloader", "snscrape",
    "twint", "osintgram", "toutatis", "ignorant",
    "blackbird", "nexfil", "userrecon", "mosint",
    "mr-holmes", "seekr", "yesitsme", "tookie-osint", "findme",
    "zehef", "eyes", "quidam", "daprofiler", "owltrack",
    "onionsearch", "pryingdeep", "twayback", "photon",
    "pip-intel", "sigit", "ominis-osint", "webextractor",
    # -- GEOINT / Geospatial Intelligence --
    "exiftool", "mat2", "metagoofil", "traceroute", "mtr",
    "geoiplookup", "mmdbinspect", "metadetective",
    # -- RECON / Advanced --
    "katana", "naabu", "hakrawler", "gospider", "dnstwist",
    "xurlfind3r", "reconftw", "bbot", "spiderfoot", "osmedeus",
    "web-check", "trape", "robofinder",
    # -- Common shell utilities --
    "cat", "head", "tail", "grep", "egrep", "fgrep", "rg",
    "awk", "sed", "sort", "uniq", "wc", "cut", "tr", "tee",
    "xargs", "find", "ls", "pwd", "echo", "printf", "mkdir", "mktemp",
    "cp", "mv", "rm", "chmod", "chown", "touch",
    "base64", "xxd", "hexdump", "od",
    "python3", "python", "perl", "ruby", "php",
    "bash", "sh", "env", "which", "command", "type",
    "id", "whoami", "hostname", "uname", "date", "uptime",
    "ip", "ifconfig", "netstat", "ss", "arp",
    "ping", "traceroute", "mtr", "dig", "host", "nslookup", "whois",
    "curl", "wget",
    "file", "strings",
    "tar", "gzip", "gunzip", "bzip2", "unzip", "zip", "7z",
    "jq", "yq", "csvtool",
    "go", "rustc", "cargo", "gcc", "g++", "make", "cmake",
    "ROPgadget",
    "dd", "nft", "iptables", "fls", "icat", "mmls",
})

# Dangerous shell patterns that indicate injection attempts.  Pipes (|) and
# redirects (>, >>) are intentionally allowed because tool pipelines need them.
_DANGEROUS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\$\("),                 # $(command substitution)
    re.compile(r"`"),                     # backtick command substitution
    re.compile(r"\$\{[^}]*\}"),          # ${var} expansion (except simple)
    re.compile(r";\s*(rm|mkfs|dd)\s"),   # destructive chained commands
    re.compile(r"&&\s*(rm|mkfs|dd)\s"),  # destructive chained commands
    re.compile(r"\beval\s"),             # eval
    re.compile(r"\bexec\s"),             # exec
    re.compile(r"\bsource\s"),           # source
    re.compile(r"\b\.\s+/"),             # dot-sourcing
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    """Outcome of a single command execution."""

    stdout: str
    stderr: str
    return_code: int
    duration: float  # seconds
    command: str
    timed_out: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def succeeded(self) -> bool:
        """Return True when the process exited with code 0."""
        return self.return_code == 0

    @property
    def combined_output(self) -> str:
        """Concatenation of stdout and stderr."""
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(f"[STDERR]\n{self.stderr}")
        if self.timed_out:
            parts.append("[TIMED OUT]")
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "return_code": self.return_code,
            "duration": round(self.duration, 3),
            "timed_out": self.timed_out,
            "stdout_length": len(self.stdout),
            "stderr_length": len(self.stderr),
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Sanitisation helpers
# ---------------------------------------------------------------------------

def _extract_binary(cmd: str) -> str | None:
    """Extract the leading binary name from a command string.

    Handles ``sudo cmd ...``, ``env VAR=val cmd ...``, and absolute paths.
    """
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return None
    if not tokens:
        return None

    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        # Skip environment variable assignments (KEY=VALUE).
        if "=" in token and not token.startswith("-") and not token.startswith("/"):
            idx += 1
            continue
        # Skip sudo / env prefixes.
        if token in ("sudo", "env"):
            idx += 1
            continue
        break

    if idx >= len(tokens):
        return None
    return Path(tokens[idx]).name


def sanitize_command(
    cmd: str,
    allowlist: frozenset[str] | None = None,
) -> tuple[bool, str]:
    """Validate *cmd* against the binary allowlist and dangerous patterns.

    Returns ``(is_safe, reason)``.  When ``is_safe`` is True, *reason* is the
    empty string.
    """
    if allowlist is None:
        allowlist = ALLOWED_BINARIES

    binary = _extract_binary(cmd)
    if binary is None:
        return False, "Could not parse binary name from command"

    if binary not in allowlist:
        return False, f"Binary '{binary}' is not in the allowed tool list"

    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(cmd):
            return False, f"Command contains dangerous pattern: {pattern.pattern}"

    return True, ""


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def _log_audit(result: ExecutionResult) -> None:
    """Append an execution record to the daily JSONL audit log."""
    try:
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        audit_file = _AUDIT_DIR / f"{today}.jsonl"
        entry = result.to_dict()
        with open(audit_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except OSError:
        pass  # audit logging is best-effort


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

class Executor:
    """Async shell command executor with live Rich output streaming.

    Features:

    * Binary allowlist validation before execution.
    * Live stdout/stderr streaming to a Rich console.
    * Configurable timeout with graceful SIGTERM -> SIGKILL escalation.
    * Audit trail logging to ``~/.strikecore/audit/``.
    * Optional callback hook for external audit systems.

    Usage::

        executor = Executor()
        result = await executor.execute("nmap -sV 10.0.0.1")
        if result.succeeded():
            print(result.stdout)
    """

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self._audit_callback: Callable[..., Any] | None = None

    def set_audit_callback(self, callback: Callable[[str, dict[str, Any]], Any]) -> None:
        """Register an external audit callback ``(event_type, data)``."""
        self._audit_callback = callback

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_command(
        cmd: str,
        allowlist: frozenset[str] | None = None,
    ) -> tuple[bool, str]:
        """Public wrapper around :func:`sanitize_command`."""
        return sanitize_command(cmd, allowlist)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        cmd: str,
        timeout: int = 300,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        live_output: bool = True,
        validate: bool = True,
    ) -> ExecutionResult:
        """Execute *cmd* asynchronously with live output streaming.

        Parameters
        ----------
        cmd:
            Full shell command string.
        timeout:
            Maximum wall-clock seconds before the process is killed.
        cwd:
            Working directory for the subprocess.
        env:
            Additional environment variables (merged into current env).
        live_output:
            Stream stdout/stderr to the Rich console in real time.
        validate:
            Check the binary against the allowlist before running.

        Returns
        -------
        ExecutionResult
        """
        # -- Validate ---------------------------------------------------
        if validate:
            is_safe, reason = sanitize_command(cmd)
            if not is_safe:
                return ExecutionResult(
                    stdout="",
                    stderr=f"Command blocked: {reason}",
                    return_code=-1,
                    duration=0.0,
                    command=cmd,
                )

        # -- Environment -------------------------------------------------
        run_env = dict(os.environ)
        # Ensure user tool directories are always in PATH
        _extra_paths = [
            os.path.expanduser("~/.local/bin"),
            os.path.expanduser("~/go/bin"),
            "/usr/local/go/bin",
        ]
        _current = run_env.get("PATH", "")
        for p in _extra_paths:
            if p not in _current:
                _current = p + ":" + _current
        run_env["PATH"] = _current
        if env:
            run_env.update(env)

        # -- Display -----------------------------------------------------
        if live_output:
            self.console.print(
                Panel(
                    Text(cmd, style="bold green"),
                    title="[cyan]Executing[/cyan]",
                    border_style="dim",
                )
            )

        # -- Launch process ----------------------------------------------
        start = time.monotonic()
        timed_out = False
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=run_env,
                preexec_fn=os.setsid,
            )
        except Exception as exc:
            duration = time.monotonic() - start
            return ExecutionResult(
                stdout="",
                stderr=f"Failed to start process: {exc}",
                return_code=-1,
                duration=duration,
                command=cmd,
            )

        async def _read_stream(
            reader: asyncio.StreamReader,
            parts: list[str],
            *,
            is_stderr: bool = False,
        ) -> None:
            """Drain a stream line by line, optionally printing each line."""
            while True:
                line = await reader.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace")
                parts.append(decoded)
                if live_output:
                    style = "red" if is_stderr else "dim"
                    self.console.print(decoded.rstrip(), style=style)

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _read_stream(proc.stdout, stdout_parts),              # type: ignore[arg-type]
                    _read_stream(proc.stderr, stderr_parts, is_stderr=True),  # type: ignore[arg-type]
                    proc.wait(),
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            timed_out = True
            # Graceful SIGTERM to the whole process group.
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass

            # Wait briefly for a clean exit, then escalate to SIGKILL.
            try:
                await asyncio.wait_for(proc.wait(), timeout=_KILL_GRACE_SECONDS)
            except asyncio.TimeoutError:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    await proc.wait()
                except Exception:
                    pass

            if live_output:
                self.console.print(
                    f"[bold red]Process timed out after {timeout}s and was terminated.[/bold red]"
                )
        except Exception as exc:
            # Unexpected error during streaming -- kill the process.
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            duration = time.monotonic() - start
            return ExecutionResult(
                stdout="".join(stdout_parts),
                stderr=f"Execution error: {exc}\n{''.join(stderr_parts)}",
                return_code=-1,
                duration=duration,
                command=cmd,
            )

        duration = time.monotonic() - start
        return_code = proc.returncode if proc.returncode is not None else -1

        result = ExecutionResult(
            stdout="".join(stdout_parts),
            stderr="".join(stderr_parts),
            return_code=return_code,
            duration=duration,
            command=cmd,
            timed_out=timed_out,
        )

        # -- Audit -------------------------------------------------------
        _log_audit(result)
        if self._audit_callback:
            try:
                self._audit_callback("COMMAND_EXEC", result.to_dict())
            except Exception:
                pass  # audit is best-effort

        # -- Summary -----------------------------------------------------
        if live_output:
            status_style = "green" if result.succeeded() else "red"
            self.console.print(
                f"[{status_style}]Exit {return_code}[/{status_style}] in "
                f"[cyan]{duration:.2f}s[/cyan]"
            )

        return result

    # ------------------------------------------------------------------
    # Background execution (fire-and-forget with PID tracking)
    # ------------------------------------------------------------------

    async def execute_background(
        self,
        cmd: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        validate: bool = True,
    ) -> int:
        """Launch *cmd* in the background and return its PID.

        The caller is responsible for managing the process lifetime (see
        :class:`~strikecore.core.process_manager.ProcessManager`).
        """
        if validate:
            is_safe, reason = sanitize_command(cmd)
            if not is_safe:
                raise PermissionError(f"Command blocked: {reason}")

        run_env = dict(os.environ)
        # Ensure user tool directories are always in PATH
        _extra_paths = [
            os.path.expanduser("~/.local/bin"),
            os.path.expanduser("~/go/bin"),
            "/usr/local/go/bin",
        ]
        _current = run_env.get("PATH", "")
        for p in _extra_paths:
            if p not in _current:
                _current = p + ":" + _current
        run_env["PATH"] = _current
        if env:
            run_env.update(env)

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=run_env,
            preexec_fn=os.setsid,
        )
        return proc.pid

    # ------------------------------------------------------------------
    # Synchronous convenience wrapper
    # ------------------------------------------------------------------

    _loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def _get_loop(cls) -> asyncio.AbstractEventLoop:
        """Return a persistent event loop for sync execution."""
        if cls._loop is None or cls._loop.is_closed():
            cls._loop = asyncio.new_event_loop()
        return cls._loop

    def execute_sync(
        self,
        cmd: str,
        timeout: int = 300,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        live_output: bool = True,
        validate: bool = True,
    ) -> ExecutionResult:
        """Synchronous wrapper around :meth:`execute` for non-async callers."""
        loop = self._get_loop()
        return loop.run_until_complete(
            self.execute(
                cmd,
                timeout=timeout,
                cwd=cwd,
                env=env,
                live_output=live_output,
                validate=validate,
            )
        )
