#!/usr/bin/env python3
"""Migrate the legacy SQLite store (~/strikecore-data/strikecore.db) into Postgres.

Idempotent: re-runnable, dedup'd by ``fingerprint_sha256`` UNIQUE constraints.
Backs up the source SQLite file before the first run.

Mapping (10 SQLite tables → Postgres):
    targets         → entity(kind=person)         + dossier
    emails          → entity(kind=email)          + dossier_finding(domain=webint,  type=email)
    phones          → entity(kind=phone)          + dossier_finding(domain=crossdb, type=phone)
    profiles        → entity(kind=handle)         + dossier_finding(domain=socint,  type=profile_url)
    organizations   → entity(kind=org)            + dossier_finding(domain=webint,  type=org)
    locations       →                              dossier_finding(domain=geoint,   type=location)
    connections     →                              dossier_finding(domain=socialint,type=connection)
    evidence        → source                     (+ finding_source link by tool)
    documents       → source(tool_name='document')
    phase_log       → trace

Run:
    POSTGRES_PASSWORD=... ./strikecore/bin/python3 db/migrate_from_sqlite.py
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import Json, execute_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("migrate_from_sqlite")

SQLITE_PATH = Path(os.environ.get(
    "STRIKECORE_SQLITE",
    "/home/atlas/strikecore-data/strikecore.db",
))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fp_entity(kind: str, canonical_value: str) -> str:
    return hashlib.sha256(f"{kind}:{canonical_value.strip().lower()}".encode("utf-8")).hexdigest()


def fp_finding(dossier_id: int, domain: str, ftype: str, value: str) -> str:
    payload = f"{dossier_id}:{domain}:{ftype}:{value.strip().lower()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def pg_dsn() -> str:
    return (
        f"host={os.environ.get('POSTGRES_HOST', '127.0.0.1')}"
        f" port={os.environ.get('POSTGRES_PORT', '5433')}"
        f" dbname={os.environ.get('POSTGRES_DB', 'strikecore')}"
        f" user={os.environ.get('POSTGRES_USER', 'strikecore')}"
        f" password={os.environ['POSTGRES_PASSWORD']}"
    )


def upsert_entity(pg, kind: str, canonical_value: str, display_name: str | None = None) -> int | None:
    """Upsert into entity, return id."""
    canonical = (canonical_value or "").strip()
    if not canonical:
        return None
    fp = fp_entity(kind, canonical)
    with pg.cursor() as cur:
        cur.execute(
            """
            INSERT INTO entity (kind, canonical_value, fingerprint_sha256, display_name)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (fingerprint_sha256) DO UPDATE
                SET updated_at = NOW()
            RETURNING id
            """,
            (kind, canonical, fp, display_name),
        )
        return cur.fetchone()[0]


def upsert_dossier(pg, target_entity_id: int, pir: str) -> int:
    """Create or fetch the dossier for this target+pir."""
    with pg.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM dossier
            WHERE target_entity_id = %s AND pir_question = %s
            ORDER BY created_at DESC LIMIT 1
            """,
            (target_entity_id, pir),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            """
            INSERT INTO dossier (target_entity_id, pir_question, status, summary_markdown)
            VALUES (%s, %s, 'completed', %s)
            RETURNING id
            """,
            (target_entity_id, pir, "(migrated from SQLite legacy store)"),
        )
        return cur.fetchone()[0]


def insert_finding(pg, dossier_id: int, domain: str, ftype: str, value: str,
                   confidence: float | None, related_entity_id: int | None, notes: str | None) -> int | None:
    if not value or not str(value).strip():
        return None
    fp = fp_finding(dossier_id, domain, ftype, str(value))
    with pg.cursor() as cur:
        cur.execute(
            """
            INSERT INTO dossier_finding
                (dossier_id, domain, finding_type, value, related_entity_id, confidence, notes, fingerprint_sha256)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (fingerprint_sha256) DO NOTHING
            RETURNING id
            """,
            (dossier_id, domain, ftype, str(value), related_entity_id,
             float(confidence) if confidence is not None else 0.5, notes, fp),
        )
        row = cur.fetchone()
        return row[0] if row else None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def migrate(sqlite_path: Path) -> dict[str, int]:
    if not sqlite_path.is_file():
        log.warning("SQLite file %s not present — nothing to migrate", sqlite_path)
        return {}

    # Backup
    backup_dir = Path("/home/atlas/argus-intelligence/strikecore/.backup") / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-sqlite-pre-migration"
    )
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sqlite_path, backup_dir / sqlite_path.name)
    log.info("Backup → %s", backup_dir / sqlite_path.name)

    sqlite = sqlite3.connect(str(sqlite_path))
    sqlite.row_factory = sqlite3.Row
    pg = psycopg2.connect(pg_dsn())
    pg.autocommit = False

    stats: dict[str, int] = {
        "targets_entities": 0, "dossiers": 0,
        "emails": 0, "phones": 0, "profiles": 0,
        "organizations": 0, "locations": 0, "connections": 0,
        "evidence_sources": 0, "documents_sources": 0, "phase_log_traces": 0,
    }

    try:
        cur = sqlite.cursor()
        # ---- 1. targets → entity(person) + dossier ----
        target_map: dict[int, dict[str, int]] = {}  # sqlite_target_id → {entity_id, dossier_id}

        try:
            cur.execute("SELECT * FROM targets")
        except sqlite3.OperationalError:
            log.warning("No 'targets' table in SQLite — skipping")
            cur = None

        if cur:
            for row in cur.fetchall():
                # SQLite schema: targets(id TEXT PRIMARY KEY, display_name TEXT,
                # created_at, updated_at, notes TEXT). Children FK ``target_id``
                # references ``targets.id`` (TEXT). Defensive against missing cols.
                keys = set(row.keys())
                rid = row["id"]
                disp = (row["display_name"] if "display_name" in keys and row["display_name"]
                        else (row["name"] if "name" in keys and row["name"] else rid))
                # ``notes`` in SQLite is sometimes a JSON blob {"usernames":[...]} —
                # don't promote that to PIR text; fall back to a generic PIR.
                notes_raw = row["notes"] if ("notes" in keys and row["notes"]) else ""
                pir = (
                    notes_raw
                    if (notes_raw and not notes_raw.lstrip().startswith("{"))
                    else f"Investigation: {disp}"
                )
                ent = upsert_entity(pg, "person", str(rid), display_name=disp)
                if ent is None:
                    continue
                dos = upsert_dossier(pg, ent, pir)
                target_map[rid] = {"entity_id": ent, "dossier_id": dos}
                stats["targets_entities"] += 1
                stats["dossiers"] += 1

        # ---- 2. emails → entity(email) + finding ----
        def _migrate_per_target(table: str, kind_for_entity: str | None,
                                domain: str, finding_type: str,
                                value_col: str, extra_cols: tuple[str, ...] = ()) -> None:
            try:
                cur2 = sqlite.cursor()
                cur2.execute(f"SELECT * FROM {table}")
            except sqlite3.OperationalError:
                log.warning("No '%s' table — skipping", table)
                return
            for r in cur2.fetchall():
                tid = r["target_id"] if "target_id" in r.keys() else None
                if tid not in target_map:
                    continue
                val = r[value_col]
                if val is None or not str(val).strip():
                    continue
                related = None
                if kind_for_entity:
                    related = upsert_entity(pg, kind_for_entity, str(val))
                notes_bits = []
                for c in extra_cols:
                    if c in r.keys() and r[c]:
                        notes_bits.append(f"{c}={r[c]}")
                notes = "; ".join(notes_bits) if notes_bits else None
                conf = r["confidence"] if "confidence" in r.keys() else None
                if isinstance(conf, str):
                    conf = {"CONFIRMED": 0.9, "PROBABLE": 0.75, "UNVERIFIED": 0.55, "WEAK": 0.3}.get(conf.upper(), 0.5)
                fid = insert_finding(pg, target_map[tid]["dossier_id"], domain, finding_type,
                                     str(val), conf, related, notes)
                if fid:
                    stats[table] = stats.get(table, 0) + 1

        _migrate_per_target("emails",        "email",  "webint",    "email",        "email",
                            extra_cols=("sources",))
        _migrate_per_target("phones",        "phone",  "crossdb",   "phone",        "phone",
                            extra_cols=("carrier", "location", "sources"))
        _migrate_per_target("profiles",      "handle", "socint",    "profile_url",  "url",
                            extra_cols=("platform", "verified_at"))
        _migrate_per_target("organizations", "org",    "webint",    "org",          "name",
                            extra_cols=("role",))
        _migrate_per_target("locations",     None,     "geoint",    "location",     "name",
                            extra_cols=("source",))
        _migrate_per_target("connections",   None,     "socialint", "connection",   "name",
                            extra_cols=("relation", "platform", "url"))

        # ---- 3. evidence → source(tool_name=<tool>) ----
        try:
            cur3 = sqlite.cursor()
            cur3.execute("SELECT * FROM evidence")
            for r in cur3.fetchall():
                tool = r["tool"] if "tool" in r.keys() else "legacy"
                out = r["output"] if "output" in r.keys() else None
                content_hash = hashlib.sha256((out or "").encode("utf-8")).hexdigest() if out else None
                with pg.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO source (tool_name, upstream, content_sha256, raw_payload)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (tool, tool.split("-")[0] if tool else "legacy", content_hash, Json({"output": out})),
                    )
                stats["evidence_sources"] += 1
        except sqlite3.OperationalError:
            log.warning("No 'evidence' table — skipping")

        # ---- 4. documents → source(tool='document') ----
        try:
            cur4 = sqlite.cursor()
            cur4.execute("SELECT * FROM documents")
            for r in cur4.fetchall():
                fname = r["filename"] if "filename" in r.keys() else "unknown"
                content = r["content"] if "content" in r.keys() else ""
                content_hash = hashlib.sha256((content or "").encode("utf-8")).hexdigest()
                with pg.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO source (tool_name, upstream, content_sha256, raw_payload)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        ("document", "filesystem", content_hash,
                         Json({"filename": fname, "summary": r["summary"] if "summary" in r.keys() else None})),
                    )
                stats["documents_sources"] += 1
        except sqlite3.OperationalError:
            log.warning("No 'documents' table — skipping")

        # ---- 5. phase_log → trace ----
        try:
            cur5 = sqlite.cursor()
            cur5.execute("SELECT * FROM phase_log")
            for r in cur5.fetchall():
                tid = r["target_id"] if "target_id" in r.keys() else None
                if tid not in target_map:
                    continue
                ev = r["phase"] if "phase" in r.keys() else "phase"
                tool_list = r["tools"] if "tools" in r.keys() else None
                findings_n = r["findings"] if "findings" in r.keys() else 0
                payload = {"phase": ev, "tools": tool_list, "findings": findings_n,
                           "migrated_from_sqlite": True, "dossier_id": target_map[tid]["dossier_id"]}
                payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
                with pg.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO trace (event, level, payload, hash_sha256)
                        VALUES (%s, 'info', %s, %s)
                        """,
                        (f"legacy.phase_log.{ev}", Json(payload), payload_hash),
                    )
                stats["phase_log_traces"] += 1
        except sqlite3.OperationalError:
            log.warning("No 'phase_log' table — skipping")

        pg.commit()
    except Exception:
        pg.rollback()
        raise
    finally:
        sqlite.close()
        pg.close()

    return stats


if __name__ == "__main__":
    if "POSTGRES_PASSWORD" not in os.environ:
        log.error("POSTGRES_PASSWORD not set — source .env first")
        sys.exit(2)
    res = migrate(SQLITE_PATH)
    log.info("Migration stats: %s", json.dumps(res, indent=2))
    print(json.dumps({"migrated_from": str(SQLITE_PATH), "stats": res}, indent=2))
