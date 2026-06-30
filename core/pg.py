"""Shared Postgres connection helper (psycopg2).

Single source of truth for the StrikeCore DSN so ``core/``, ``web/`` and
``db/`` all resolve the same connection parameters from the environment. In
compose ``POSTGRES_HOST`` is the ``postgres`` service; on the host it defaults
to ``127.0.0.1``.

A single autocommit connection is cached and reused (dev / single-operator
scale, mirroring ``web/backend/db.py``). Postgres is the authoritative state
plane after the JSONB swap — callers that need a fresh, isolated connection
(migrations, the LISTEN bridge) should call :func:`connect` directly.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg2
import psycopg2.extensions
from psycopg2.extras import RealDictCursor

log = logging.getLogger("core.pg")


def dsn() -> str:
    return (
        f"host={os.environ.get('POSTGRES_HOST', '127.0.0.1')}"
        f" port={os.environ.get('POSTGRES_PORT', '5433')}"
        f" dbname={os.environ.get('POSTGRES_DB', 'strikecore')}"
        f" user={os.environ.get('POSTGRES_USER', 'strikecore')}"
        f" password={os.environ.get('POSTGRES_PASSWORD', '')}"
        f" application_name={os.environ.get('PG_APPLICATION_NAME', 'strikecore')}"
    )


def connect() -> psycopg2.extensions.connection:
    """Open a fresh autocommit connection. Caller owns its lifecycle."""
    conn = psycopg2.connect(dsn())
    conn.autocommit = True
    return conn


# Thread-local cached connection: psycopg2 connections are NOT thread-safe, and
# the Flask dashboard + FastAPI threadpool serve requests on multiple threads.
# Each thread gets its own connection so concurrent requests don't corrupt a
# shared one (the bug where the dashboard list silently returned []).
_local = threading.local()


def _conn() -> psycopg2.extensions.connection:
    c = getattr(_local, "conn", None)
    if c is None or c.closed:
        c = connect()
        _local.conn = c
    return c


@contextmanager
def cursor(dict_rows: bool = True) -> Iterator[Any]:
    """Yield a cursor on this thread's cached connection. Resets the connection
    on error so a dropped socket (container restart) self-heals on next call."""
    factory = RealDictCursor if dict_rows else None
    try:
        c = _conn().cursor(cursor_factory=factory)
    except psycopg2.Error:
        _local.conn = None
        c = _conn().cursor(cursor_factory=factory)
    try:
        yield c
    except psycopg2.Error:
        try:
            _conn().close()
        except Exception:
            pass
        _local.conn = None
        raise
    finally:
        try:
            c.close()
        except Exception:
            pass
