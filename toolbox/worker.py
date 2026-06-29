#!/usr/bin/env python3
"""StrikeCore toolbox worker — Redis Streams consumer that runs OSINT jobs.

Runs INSIDE the Kali toolbox container (the only place the ~157 OSINT binaries
+ the full agent runtime live). The thin backend enqueues jobs; this worker
claims, validates, runs, and acks them.

Gate enforcement (decision I4 — the worker is authoritative, never trusts the
enqueuer):
- Every job re-runs ``sanitize_command`` + the ``ALLOWED_BINARIES`` allowlist
  (the real RUNTIME gate, already in core/executor.py). Raw OSINT binaries have
  no manifest, so the allowlist + sanitize IS their gate.
- ``tools/<name>`` registered scripts additionally must be ``gate_approved`` in
  the registry index (``~/.strikecore/registry/index.json``) — the DEPLOY-time
  H3 hard-stop, re-checked here at run time.

Job shapes (single JSON ``payload`` field on the stream):
  {"type": "dossier", "target": ..., "pir": ..., "operator_notes": ...,
   "constraints": {...}}
  {"type": "tool", "cmd": "<shell command>", "tool": "<registered name or ''>"}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sys
from pathlib import Path

# Project root on path (so core/, agent/, config/ import inside the container)
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import job_queue  # noqa: E402
from core.executor import Executor, sanitize_command  # noqa: E402

logging.basicConfig(level=os.environ.get("STRIKECORE_LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("toolbox.worker")

_REGISTRY_INDEX = Path.home() / ".strikecore" / "registry" / "index.json"


def _registry_gate_ok(tool_name: str) -> bool:
    """Re-check the deploy-time H3 gate for a REGISTERED tools/ script.

    Returns True if the tool is gate_approved in the registry index. A tool the
    enqueuer names but that is absent / not approved is rejected — the worker
    never trusts the enqueuer's claim.
    """
    if not tool_name:
        return True  # raw binary path; allowlist + sanitize is its gate
    try:
        index = json.loads(_REGISTRY_INDEX.read_text())
    except Exception:
        log.warning("registry index unreadable (%s) — rejecting registered tool %s",
                    _REGISTRY_INDEX, tool_name)
        return False
    entries = index.get("tools", index) if isinstance(index, dict) else {}
    entry = entries.get(tool_name) if isinstance(entries, dict) else None
    return bool(entry and entry.get("gate_approved") is True)


async def _run_tool(job: dict) -> None:
    cmd = (job.get("cmd") or "").strip()
    tool = job.get("tool") or ""
    if not cmd:
        raise ValueError("tool job missing 'cmd'")
    # Gate 1: registry H3 (registered scripts only)
    if not _registry_gate_ok(tool):
        raise PermissionError(f"tool '{tool}' is not gate_approved (H3) — refusing to run")
    # Gate 2: allowlist + dangerous-pattern sanitize (raw binaries + everything)
    is_safe, reason = sanitize_command(cmd)
    if not is_safe:
        raise PermissionError(f"command blocked by sanitize: {reason}")
    result = await Executor().execute(cmd, validate=True)
    log.info("tool job done rc=%s tool=%s", getattr(result, "return_code", "?"), tool or "raw")


async def _run_dossier(job: dict) -> None:
    from config.settings import get_settings
    from core.provider_router import ProviderRouter
    from agent.dossier_flow import build_dossier

    settings = get_settings()
    router = ProviderRouter(settings)
    await build_dossier(
        router=router,
        target=job["target"],
        pir=job.get("pir", ""),
        operator_notes=job.get("operator_notes", ""),
        constraints=job.get("constraints", {}) or {},
        investigation_store=None,
    )
    log.info("dossier job done target=%s", job.get("target"))


async def _dispatch(job: dict) -> None:
    kind = job.get("type")
    if kind == "dossier":
        await _run_dossier(job)
    elif kind == "tool":
        await _run_tool(job)
    else:
        raise ValueError(f"unknown job type: {kind!r}")


def main() -> int:
    consumer = f"{socket.gethostname()}-{os.getpid()}"
    r = job_queue.client()
    job_queue.ensure_group(r)
    log.info("toolbox worker up: consumer=%s stream=%s group=%s",
             consumer, job_queue.JOBS_STREAM, job_queue.GROUP)

    idle = 0
    while True:
        # Periodically reclaim entries abandoned by dead/stuck workers.
        if idle % 12 == 0:
            for msg_id, job in job_queue.reclaim_stale(r, consumer):
                _process(r, msg_id, job)
        batch = job_queue.claim(r, consumer, block_ms=5000)
        if not batch:
            idle += 1
            continue
        idle = 0
        for msg_id, job in batch:
            _process(r, msg_id, job)
    return 0


def _process(r: "job_queue.redis.Redis", msg_id: str, job: dict) -> None:
    try:
        asyncio.run(_dispatch(job))
        job_queue.ack(r, msg_id)
    except (PermissionError, ValueError) as exc:
        # Deterministic failure (bad/blocked job) — dead-letter, don't reclaim-loop.
        log.warning("job %s rejected: %s", msg_id, exc)
        job_queue.dead_letter(r, msg_id, job, reason=str(exc))
    except Exception as exc:  # noqa: BLE001
        # Transient failure — leave PENDING so XAUTOCLAIM retries; log loudly.
        log.exception("job %s failed (will be reclaimed): %s", msg_id, exc)


if __name__ == "__main__":
    raise SystemExit(main())
