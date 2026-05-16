"""Backend Postgres helpers — synchronous psycopg2 + an async LISTEN bridge.

Reuses connection parameters from environment (.env loaded by app.py).
Returns RealDictRow (jsonable dicts) for trivial pydantic compatibility.
The LISTEN bridge runs a dedicated async-friendly polling loop on its own
connection, pushing parsed payloads to the supplied asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import select
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg2
import psycopg2.extensions
from psycopg2.extras import RealDictCursor, Json  # noqa: F401

log = logging.getLogger("web.backend.db")


def _dsn() -> str:
    return (
        f"host={os.environ.get('POSTGRES_HOST', '127.0.0.1')}"
        f" port={os.environ.get('POSTGRES_PORT', '5433')}"
        f" dbname={os.environ.get('POSTGRES_DB', 'strikecore')}"
        f" user={os.environ.get('POSTGRES_USER', 'strikecore')}"
        f" password={os.environ.get('POSTGRES_PASSWORD', '')}"
        f" application_name=strikecore-web"
    )


# Lazy module-level connection for synchronous reads (FastAPI runs each endpoint
# in a threadpool by default, so a single autocommit conn is fine for dev scale).
_CONN: psycopg2.extensions.connection | None = None


def _conn() -> psycopg2.extensions.connection:
    global _CONN
    if _CONN is None or _CONN.closed:
        _CONN = psycopg2.connect(_dsn())
        _CONN.autocommit = True
    return _CONN


@contextmanager
def cursor() -> Iterator[Any]:
    c = _conn().cursor(cursor_factory=RealDictCursor)
    try:
        yield c
    finally:
        c.close()


def fetch_all(sql: str, params: tuple | list | None = None) -> list[dict[str, Any]]:
    try:
        with cursor() as cur:
            cur.execute(sql, params or [])
            rows = cur.fetchall()
            return [_serialise(dict(r)) for r in rows]
    except psycopg2.Error as exc:
        log.warning("fetch_all failed: %s\nSQL=%s", exc, sql)
        # Reset on error
        global _CONN
        try:
            _conn().close()
        except Exception:
            pass
        _CONN = None
        raise


def fetch_one(sql: str, params: tuple | list | None = None) -> dict[str, Any] | None:
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


def pool_ping() -> bool:
    try:
        with cursor() as cur:
            cur.execute("SELECT 1")
            return cur.fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        log.warning("pool_ping failed: %s", exc)
        return False


def _serialise(obj: Any) -> Any:
    """Coerce psycopg2/JSON/datetime types to JSON-serialisable forms."""
    if isinstance(obj, dict):
        return {k: _serialise(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialise(v) for v in obj]
    # psycopg2 returns datetime/Decimal/date already JSON-serialisable via FastAPI,
    # but JSONB columns come back as already-parsed dicts. memoryview / bytes:
    if isinstance(obj, (bytes, bytearray, memoryview)):
        try:
            return bytes(obj).decode("utf-8")
        except UnicodeDecodeError:
            return bytes(obj).hex()
    return obj


# ---------------------------------------------------------------------------
# LISTEN/NOTIFY bridge for live trace streaming
# ---------------------------------------------------------------------------


async def listen_traces(queue: asyncio.Queue[str]) -> None:
    """Open a dedicated Postgres connection, LISTEN on 'trace_channel', push to queue.

    Uses a thread-poll bridge: we wait on the connection's fileno via
    ``asyncio.get_running_loop().run_in_executor`` so we never block the event loop.
    """
    loop = asyncio.get_running_loop()

    def _connect() -> psycopg2.extensions.connection:
        c = psycopg2.connect(_dsn())
        c.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        with c.cursor() as cur:
            cur.execute("LISTEN trace_channel")
        return c

    conn = await loop.run_in_executor(None, _connect)
    fd = conn.fileno()

    log.info("LISTEN trace_channel on fd=%d", fd)
    try:
        while True:
            # Wait until something arrives on the socket — non-blocking via select
            await loop.run_in_executor(None, _wait_for_notify, conn, fd, 5.0)
            conn.poll()
            while conn.notifies:
                n = conn.notifies.pop(0)
                try:
                    payload = json.loads(n.payload)
                except Exception:
                    payload = {"raw": n.payload}
                msg = json.dumps({"event": "trace", "channel": n.channel, "payload": payload}, default=str)
                if queue.full():
                    try:
                        queue.get_nowait()  # drop oldest
                    except asyncio.QueueEmpty:
                        pass
                await queue.put(msg)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("listen_traces loop crashed: %s", exc)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _wait_for_notify(conn: psycopg2.extensions.connection, fd: int, timeout: float) -> None:
    """Block (in executor) on the connection socket until readable or timeout."""
    try:
        select.select([fd], [], [], timeout)
    except OSError:
        # Connection went away; let caller handle
        pass
