"""
Background process tracker for StrikeCore.

Manages long-running security tool processes, storing their output in
in-memory ring buffers and providing lifecycle control (start / stop /
list / cleanup).  Registers an ``atexit`` handler to kill orphaned
processes when the interpreter shuts down.
"""

from __future__ import annotations

import asyncio
import atexit
import os
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from rich.console import Console
from rich.table import Table

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

_KILL_GRACE_SECONDS = 5
_MAX_BUFFER_LINES = 50_000  # per-process cap to bound memory


class ProcessStatus(str, Enum):
    """Lifecycle states for a tracked background process."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class ProcessInfo:
    """Metadata and output buffers for a single tracked process."""

    pid: int
    command: str
    start_time: float  # ``time.monotonic()`` at launch
    started_at: str  # ISO-8601 wall-clock timestamp
    status: ProcessStatus = ProcessStatus.RUNNING
    return_code: int | None = None
    output_buffer: list[str] = field(default_factory=list)
    error_buffer: list[str] = field(default_factory=list)
    _process: asyncio.subprocess.Process | None = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def elapsed(self) -> float:
        """Wall-clock seconds since the process was started."""
        return time.monotonic() - self.start_time

    @property
    def stdout(self) -> str:
        return "".join(self.output_buffer)

    @property
    def stderr(self) -> str:
        return "".join(self.error_buffer)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "command": self.command,
            "started_at": self.started_at,
            "status": self.status.value,
            "return_code": self.return_code,
            "elapsed_seconds": round(self.elapsed, 2),
            "stdout_lines": len(self.output_buffer),
            "stderr_lines": len(self.error_buffer),
        }


# ---------------------------------------------------------------------------
# Process Manager
# ---------------------------------------------------------------------------

class ProcessManager:
    """Track and manage background security-tool processes.

    Usage::

        pm = ProcessManager()
        info = await pm.start("nmap -sV 10.0.0.0/24 -oN scan.txt")
        pm.list_all()
        output = pm.get_output(info.pid)
        await pm.stop(info.pid)

    On interpreter shutdown, all processes that are still running are
    forcefully killed to avoid orphaned child processes.
    """

    def __init__(self, console: Console | None = None) -> None:
        self._processes: dict[int, ProcessInfo] = {}
        self._lock = asyncio.Lock()
        self._console = console or Console()
        atexit.register(self._sync_cleanup)

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------

    async def start(
        self,
        cmd: str,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ProcessInfo:
        """Launch *cmd* as a background process and return its :class:`ProcessInfo`.

        stdout and stderr are asynchronously drained into in-memory buffers
        accessible via :meth:`get_output`.
        """
        run_env: dict[str, str] | None = None
        if env:
            run_env = {**os.environ, **env}

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=run_env,
            preexec_fn=os.setsid,
        )

        info = ProcessInfo(
            pid=proc.pid,
            command=cmd,
            start_time=time.monotonic(),
            started_at=datetime.now(timezone.utc).isoformat(),
            _process=proc,
        )

        async with self._lock:
            self._processes[proc.pid] = info

        # Fire-and-forget drain tasks.
        asyncio.create_task(self._drain(proc.stdout, info.output_buffer))   # type: ignore[arg-type]
        asyncio.create_task(self._drain(proc.stderr, info.error_buffer))    # type: ignore[arg-type]
        asyncio.create_task(self._wait(proc, info))

        self._console.print(
            f"[green]Background process started:[/green] PID={proc.pid}  cmd={cmd}"
        )
        return info

    # ------------------------------------------------------------------
    # Stop
    # ------------------------------------------------------------------

    async def stop(self, pid: int, *, force: bool = False) -> bool:
        """Stop the process with the given *pid*.

        Sends SIGTERM first; if *force* is ``True`` or the process does not
        exit within a grace period, escalates to SIGKILL.

        Returns ``True`` if the process was found and signalled.
        """
        async with self._lock:
            info = self._processes.get(pid)
        if info is None:
            self._console.print(f"[red]No tracked process with PID {pid}[/red]")
            return False

        proc = info._process
        if proc is None or proc.returncode is not None:
            if info.status == ProcessStatus.RUNNING:
                info.status = ProcessStatus.COMPLETED
            return True

        # Send initial signal.
        try:
            sig = signal.SIGKILL if force else signal.SIGTERM
            os.killpg(os.getpgid(pid), sig)
        except ProcessLookupError:
            info.status = ProcessStatus.COMPLETED
            return True
        except PermissionError:
            info.status = ProcessStatus.ERROR
            return False

        # If SIGTERM, wait for graceful exit then escalate.
        if not force:
            try:
                await asyncio.wait_for(proc.wait(), timeout=_KILL_GRACE_SECONDS)
            except asyncio.TimeoutError:
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    await proc.wait()
                except Exception:
                    pass

        info.status = ProcessStatus.STOPPED
        info.return_code = proc.returncode
        self._console.print(f"[yellow]Process {pid} stopped.[/yellow]")
        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_all(self) -> list[ProcessInfo]:
        """Return info for all tracked processes (running and finished)."""
        self._refresh_statuses()
        return list(self._processes.values())

    def list_running(self) -> list[ProcessInfo]:
        """Return only currently running processes."""
        self._refresh_statuses()
        return [p for p in self._processes.values() if p.status == ProcessStatus.RUNNING]

    def get_info(self, pid: int) -> ProcessInfo | None:
        """Return process info for the given *pid*, or ``None``."""
        self._refresh_statuses()
        return self._processes.get(pid)

    def get_output(self, pid: int, *, tail: int | None = None) -> str | None:
        """Return captured stdout for *pid*.

        If *tail* is given, only the last *tail* lines are returned.
        """
        info = self._processes.get(pid)
        if info is None:
            return None
        lines = info.output_buffer
        if tail is not None:
            lines = lines[-tail:]
        return "".join(lines)

    def get_full_output(self, pid: int, *, tail: int | None = None) -> dict[str, str] | None:
        """Return both stdout and stderr for *pid* as a dict."""
        info = self._processes.get(pid)
        if info is None:
            return None
        stdout_lines = info.output_buffer
        stderr_lines = info.error_buffer
        if tail is not None:
            stdout_lines = stdout_lines[-tail:]
            stderr_lines = stderr_lines[-tail:]
        return {
            "stdout": "".join(stdout_lines),
            "stderr": "".join(stderr_lines),
        }

    @property
    def active_count(self) -> int:
        """Number of processes currently running."""
        self._refresh_statuses()
        return sum(1 for p in self._processes.values() if p.status == ProcessStatus.RUNNING)

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def print_table(self) -> None:
        """Render a Rich table of all tracked processes."""
        self._refresh_statuses()
        table = Table(title="Background Processes", show_lines=True)
        table.add_column("PID", style="cyan", justify="right")
        table.add_column("Command", style="white", max_width=60)
        table.add_column("Status", style="bold")
        table.add_column("Elapsed", style="yellow", justify="right")
        table.add_column("Exit Code", justify="right")
        table.add_column("Output Lines", justify="right")

        status_styles = {
            ProcessStatus.RUNNING: "green",
            ProcessStatus.COMPLETED: "blue",
            ProcessStatus.FAILED: "red",
            ProcessStatus.STOPPED: "yellow",
            ProcessStatus.ERROR: "bold red",
        }

        for info in self._processes.values():
            style = status_styles.get(info.status, "white")
            rc = str(info.return_code) if info.return_code is not None else "-"
            table.add_row(
                str(info.pid),
                info.command,
                f"[{style}]{info.status.value}[/{style}]",
                f"{info.elapsed:.1f}s",
                rc,
                str(len(info.output_buffer)),
            )

        self._console.print(table)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup(self) -> None:
        """Stop all running processes and clear tracking data."""
        running = self.list_running()
        for info in running:
            await self.stop(info.pid, force=True)
        async with self._lock:
            self._processes.clear()
        self._console.print("[dim]All background processes cleaned up.[/dim]")

    def _sync_cleanup(self) -> None:
        """Synchronous ``atexit`` handler to kill orphaned processes."""
        for info in list(self._processes.values()):
            if info._process and info._process.returncode is None:
                try:
                    os.killpg(os.getpgid(info.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _drain(
        self,
        reader: asyncio.StreamReader,
        buffer: list[str],
    ) -> None:
        """Read lines from *reader* into *buffer* until EOF."""
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace")
                buffer.append(decoded)
                # Trim to prevent unbounded memory growth.
                if len(buffer) > _MAX_BUFFER_LINES:
                    del buffer[: _MAX_BUFFER_LINES // 10]
        except Exception:
            pass  # stream closed

    async def _wait(
        self,
        process: asyncio.subprocess.Process,
        info: ProcessInfo,
    ) -> None:
        """Wait for *process* to finish and update its status."""
        try:
            return_code = await process.wait()
        except Exception:
            info.status = ProcessStatus.ERROR
            return
        info.return_code = return_code
        if info.status == ProcessStatus.RUNNING:
            info.status = (
                ProcessStatus.COMPLETED if return_code == 0 else ProcessStatus.FAILED
            )

    def _refresh_statuses(self) -> None:
        """Sync process status with actual OS state."""
        for info in self._processes.values():
            if info.status != ProcessStatus.RUNNING:
                continue
            proc = info._process
            if proc is not None and proc.returncode is not None:
                info.return_code = proc.returncode
                info.status = (
                    ProcessStatus.COMPLETED
                    if proc.returncode == 0
                    else ProcessStatus.FAILED
                )
            elif proc is None:
                # No subprocess handle -- check via OS signal.
                try:
                    os.kill(info.pid, 0)
                except ProcessLookupError:
                    info.status = ProcessStatus.COMPLETED
                except PermissionError:
                    pass  # still alive, just can't signal
