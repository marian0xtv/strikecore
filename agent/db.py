"""Lightweight Postgres helpers for the agent core.

Centralises connection management + the recurring write patterns
(``agent_run``, ``subagent_invocation``, ``trace``, ``improvement``,
``dossier``). All writes are autocommit — Phase B does not need transactions
larger than a single insert.

Failures are LOGGED but RE-RAISED — unlike the Token Ledger (observability),
these tables are correctness-critical (the dossier_id we get back must be
the same one we render against).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator, Optional

import psycopg2
from psycopg2.extras import Json, RealDictCursor

logger = logging.getLogger("agent.db")


def dsn() -> str:
    return (
        f"host={os.environ.get('POSTGRES_HOST', '127.0.0.1')}"
        f" port={os.environ.get('POSTGRES_PORT', '5433')}"
        f" dbname={os.environ.get('POSTGRES_DB', 'strikecore')}"
        f" user={os.environ.get('POSTGRES_USER', 'strikecore')}"
        f" password={os.environ.get('POSTGRES_PASSWORD', '')}"
        f" application_name=strikecore-agent"
    )


_CONN: Optional[psycopg2.extensions.connection] = None


def conn() -> psycopg2.extensions.connection:
    global _CONN
    if _CONN is None or _CONN.closed:
        _CONN = psycopg2.connect(dsn())
        _CONN.autocommit = True
    return _CONN


@contextmanager
def cursor(dict_rows: bool = False) -> Iterator[Any]:
    cur = conn().cursor(cursor_factory=RealDictCursor if dict_rows else None)
    try:
        yield cur
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Entity / Dossier
# ---------------------------------------------------------------------------


def upsert_entity(kind: str, canonical_value: str, display_name: str | None = None) -> int | None:
    if not canonical_value or not str(canonical_value).strip():
        return None
    fp = hashlib.sha256(f"{kind}:{canonical_value.strip().lower()}".encode("utf-8")).hexdigest()
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO entity (kind, canonical_value, fingerprint_sha256, display_name)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (fingerprint_sha256) DO UPDATE SET updated_at = NOW()
            RETURNING id
            """,
            (kind, canonical_value.strip(), fp, display_name),
        )
        return cur.fetchone()[0]


def create_dossier(target_entity_id: int, pir: str, operator_user: str = "atlas",
                   constraints: dict | None = None) -> int:
    with cursor() as cur:
        cur.execute("SELECT id FROM app_user WHERE username = %s", (operator_user,))
        row = cur.fetchone()
        op_id = row[0] if row else None
        cur.execute(
            """
            INSERT INTO dossier (target_entity_id, pir_question, status, operator_id, constraints)
            VALUES (%s, %s, 'planning', %s, %s)
            RETURNING id
            """,
            (target_entity_id, pir, op_id, Json(constraints or {})),
        )
        return cur.fetchone()[0]


def update_dossier(dossier_id: int, **fields: Any) -> None:
    """Set arbitrary columns on dossier (status, bluf, summary_*, completed_at, cost_micros, …)."""
    if not fields:
        return
    cols = []
    vals: list[Any] = []
    for k, v in fields.items():
        cols.append(f"{k} = %s")
        vals.append(Json(v) if isinstance(v, (dict, list)) else v)
    vals.append(dossier_id)
    with cursor() as cur:
        cur.execute(f"UPDATE dossier SET {', '.join(cols)} WHERE id = %s", vals)


def insert_finding(dossier_id: int, domain: str, ftype: str, value: str,
                   related_entity_id: int | None = None,
                   confidence: float = 0.5, notes: str | None = None) -> int | None:
    if not value or not str(value).strip():
        return None
    fp = hashlib.sha256(
        f"{dossier_id}:{domain}:{ftype}:{str(value).strip().lower()}".encode("utf-8")
    ).hexdigest()
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO dossier_finding
                (dossier_id, domain, finding_type, value, related_entity_id, confidence, notes, fingerprint_sha256)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (fingerprint_sha256) DO NOTHING
            RETURNING id
            """,
            (dossier_id, domain, ftype, str(value).strip(), related_entity_id, confidence, notes, fp),
        )
        row = cur.fetchone()
        return row[0] if row else None


# ---------------------------------------------------------------------------
# Agent run / Subagent invocation / Trace
# ---------------------------------------------------------------------------


def start_agent_run(dossier_id: int | None, role: str, agent_name: str,
                    parent_run_id: int | None = None, input_payload: dict | None = None) -> int:
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_run (dossier_id, parent_run_id, role, agent_name, status, input)
            VALUES (%s, %s, %s, %s, 'running', %s)
            RETURNING id
            """,
            (dossier_id, parent_run_id, role, agent_name, Json(input_payload or {})),
        )
        return cur.fetchone()[0]


def finish_agent_run(run_id: int, status: str, output: dict | None = None,
                     error_text: str | None = None, cost_micros: int = 0) -> None:
    with cursor() as cur:
        cur.execute(
            """
            UPDATE agent_run
            SET status = %s, ended_at = NOW(), output = %s, error_text = %s,
                cost_micros = cost_micros + %s
            WHERE id = %s
            """,
            (status, Json(output or {}), error_text, cost_micros, run_id),
        )


def record_subagent_invocation(agent_run_id: int, tool_name: str,
                               input_payload: dict, output_payload: dict | None,
                               success: bool, error_text: str | None,
                               duration_ms: int, cost_micros: int = 0,
                               input_hash: str | None = None) -> int:
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO subagent_invocation
                (agent_run_id, tool_name, input, output, ended_at, success, error_text, duration_ms, cost_micros, input_hash)
            VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (agent_run_id, tool_name, Json(input_payload), Json(output_payload or {}),
             success, error_text, duration_ms, cost_micros, input_hash),
        )
        return cur.fetchone()[0]


def emit_trace(agent_run_id: int | None, event: str, payload: dict | None = None,
               level: str = "info", subagent_inv_id: int | None = None) -> None:
    payload = payload or {}
    entry = {"event": event, "level": level, "payload": payload}
    h = hashlib.sha256(json.dumps(entry, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    try:
        with cursor() as cur:
            cur.execute(
                """
                INSERT INTO trace (agent_run_id, subagent_inv_id, level, event, payload, hash_sha256)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (agent_run_id, subagent_inv_id, level, event, Json(payload), h),
            )
    except Exception as exc:  # noqa: BLE001 — trace must not crash the loop
        logger.warning("trace insert failed: %s", exc)


# ---------------------------------------------------------------------------
# Improvement
# ---------------------------------------------------------------------------


def write_improvement(agent_run_id: int | None, category: str, target_component: str,
                      description: str, patch: dict | None = None,
                      patch_revert: dict | None = None) -> int | None:
    """Idempotent: same description on the same target_component bumps evidence_count."""
    try:
        with cursor() as cur:
            cur.execute(
                """
                SELECT id, evidence_count FROM improvement
                WHERE target_component = %s AND description = %s AND applied = FALSE
                ORDER BY id DESC LIMIT 1
                """,
                (target_component, description),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    "UPDATE improvement SET evidence_count = evidence_count + 1, updated_at = NOW() WHERE id = %s",
                    (row[0],),
                )
                return row[0]
            cur.execute(
                """
                INSERT INTO improvement (agent_run_id, category, target_component, description, patch, patch_revert)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (agent_run_id, category, target_component, description,
                 Json(patch or {}), Json(patch_revert or {})),
            )
            return cur.fetchone()[0]
    except Exception as exc:  # noqa: BLE001
        logger.warning("improvement insert failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Model routing read (Phase D adds writes/updates)
# ---------------------------------------------------------------------------


def get_model_for_task(task_type: str, fallback: str = "claude-sonnet-4-6") -> str:
    try:
        with cursor() as cur:
            cur.execute("SELECT preferred_model FROM model_routing WHERE task_type = %s", (task_type,))
            row = cur.fetchone()
            return row[0] if row else fallback
    except Exception:
        return fallback
