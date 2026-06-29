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


_CONN: psycopg2.extensions.connection | None = None


def _conn() -> psycopg2.extensions.connection:
    global _CONN
    if _CONN is None or _CONN.closed:
        _CONN = connect()
    return _CONN


@contextmanager
def cursor(dict_rows: bool = True) -> Iterator[Any]:
    """Yield a cursor on the cached connection. Resets the connection on error
    so a dropped socket (container restart) self-heals on the next call."""
    global _CONN
    factory = RealDictCursor if dict_rows else None
    try:
        c = _conn().cursor(cursor_factory=factory)
    except psycopg2.Error:
        _CONN = None
        c = _conn().cursor(cursor_factory=factory)
    try:
        yield c
    except psycopg2.Error:
        try:
            _conn().close()
        except Exception:
            pass
        _CONN = None
        raise
    finally:
        try:
            c.close()
        except Exception:
            pass
