"""StrikeCore tool/dossier job queue — Redis Streams + consumer group.

The thin FastAPI backend ENQUEUES jobs here; the Kali toolbox worker
(``toolbox/worker.py``) CLAIMS, runs, and ACKs them. Live traces do NOT flow
through this queue — they stay on the existing Postgres LISTEN/NOTIFY channel
(``/ws/traces``). This queue only carries job lifecycle.

Reliability (decision I2):
- ``XADD`` with ``MAXLEN ~`` so the stream can't grow unbounded.
- A consumer group gives at-least-once delivery: a worker that dies after
  claiming but before ``XACK`` leaves the entry PENDING, and another worker
  reclaims it via ``XAUTOCLAIM``.
- Poison messages (repeatedly failing) are dead-lettered to ``JOBS_DEAD`` so
  they don't reclaim-loop forever.

The Redis job keyspace MUST run under ``noeviction`` (see docker-compose.yml) —
``allkeys-lru`` would silently evict in-flight job entries.
"""

from __future__ import annotations

import json
import os
from typing import Any

import redis

JOBS_STREAM = "strikecore:jobs"
JOBS_DEAD = "strikecore:jobs:dead"
GROUP = "workers"
MAXLEN = int(os.environ.get("STRIKECORE_JOBS_MAXLEN", "10000"))
MAX_DELIVERIES = int(os.environ.get("STRIKECORE_JOBS_MAX_DELIVERIES", "3"))


def client() -> "redis.Redis":
    """Connect using REDIS_* env. ``decode_responses`` so payloads are str.

    socket_keepalive + health_check_interval keep a long-lived worker connection
    from going stale (the periodic blocking XREADGROUP otherwise risks a
    server-side read timeout on an idle socket).
    """
    return redis.Redis(
        host=os.environ.get("REDIS_HOST", "127.0.0.1"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        password=os.environ.get("REDIS_PASSWORD") or None,
        decode_responses=True,
        socket_keepalive=True,
        health_check_interval=30,
    )


def ensure_group(r: "redis.Redis") -> None:
    """Create the consumer group + stream if absent (idempotent)."""
    try:
        r.xgroup_create(JOBS_STREAM, GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def enqueue(r: "redis.Redis", job: dict[str, Any]) -> str:
    """XADD a job (single ``payload`` field holding JSON). Returns the entry id."""
    return r.xadd(JOBS_STREAM, {"payload": json.dumps(job)}, maxlen=MAXLEN, approximate=True)


def _decode(fields: dict[str, str]) -> dict[str, Any]:
    try:
        return json.loads(fields.get("payload", "{}"))
    except Exception:
        return {"_raw": fields}


def claim(r: "redis.Redis", consumer: str, block_ms: int = 5000, count: int = 1):
    """Claim new (never-delivered) entries. Returns list of (id, job_dict)."""
    resp = r.xreadgroup(GROUP, consumer, {JOBS_STREAM: ">"}, count=count, block=block_ms)
    out = []
    for _stream, entries in resp or []:
        for msg_id, fields in entries:
            out.append((msg_id, _decode(fields)))
    return out


def reclaim_stale(r: "redis.Redis", consumer: str, min_idle_ms: int = 600_000, count: int = 10):
    """XAUTOCLAIM entries idle longer than ``min_idle_ms`` (dead/stuck worker).
    Returns list of (id, job_dict). Poison entries (delivered > MAX_DELIVERIES)
    are dead-lettered and acked instead of being handed back."""
    out = []
    res = r.xautoclaim(JOBS_STREAM, GROUP, consumer, min_idle_time=min_idle_ms, count=count)
    # redis-py >=4.2 returns (cursor, entries, deleted); older returns (cursor, entries).
    entries = res[1] if isinstance(res, (list, tuple)) and len(res) >= 2 else []
    for msg_id, fields in entries:
        job = _decode(fields)
        pending = r.xpending_range(JOBS_STREAM, GROUP, min=msg_id, max=msg_id, count=1)
        delivered = pending[0]["times_delivered"] if pending else 1
        if delivered > MAX_DELIVERIES:
            dead_letter(r, msg_id, job, reason=f"exceeded {MAX_DELIVERIES} deliveries")
            continue
        out.append((msg_id, job))
    return out


def ack(r: "redis.Redis", msg_id: str) -> None:
    r.xack(JOBS_STREAM, GROUP, msg_id)


def dead_letter(r: "redis.Redis", msg_id: str, job: dict[str, Any], reason: str) -> None:
    """Move a poison entry to the dead-letter stream and ack the original."""
    r.xadd(JOBS_DEAD, {"payload": json.dumps({"job": job, "reason": reason, "orig_id": msg_id})},
           maxlen=MAXLEN, approximate=True)
    r.xack(JOBS_STREAM, GROUP, msg_id)
