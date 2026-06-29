#!/usr/bin/env python3
"""Migrate ~/strikecore-data/investigations/*.json files into Postgres.

Idempotent. Backs up each JSON file before the first migration. Walks each
file and routes its contents to the Postgres schema with dedup via
``fingerprint_sha256``.

The JSON files were inspected by the Phase-1 explore agent:
  dario.json (69 KB), giuseppe.json (93 KB),
  luigi_savino.json (32 KB), gaia_pagin.json (42 KB).

Shape per file (richer than the SQLite store):
  target_id, identity, emails[], phones[], profiles[], organizations[],
  locations[], connections[], evidence[], documents[], phase_log[],
  social_graph{...}, timeline[], devices[], breaches[],
  created, updated, notes, raw_evidence
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("migrate_from_json")

INVESTIGATIONS_DIR = Path(os.environ.get(
    "STRIKECORE_INVESTIGATIONS",
    str(Path.home() / "strikecore-data" / "investigations"),
))


def fp_entity(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}:{value.strip().lower()}".encode("utf-8")).hexdigest()


def fp_finding(dossier_id: int, domain: str, ftype: str, value: str) -> str:
    return hashlib.sha256(
        f"{dossier_id}:{domain}:{ftype}:{value.strip().lower()}".encode("utf-8")
    ).hexdigest()


def pg_dsn() -> str:
    return (
        f"host={os.environ.get('POSTGRES_HOST', '127.0.0.1')}"
        f" port={os.environ.get('POSTGRES_PORT', '5433')}"
        f" dbname={os.environ.get('POSTGRES_DB', 'strikecore')}"
        f" user={os.environ.get('POSTGRES_USER', 'strikecore')}"
        f" password={os.environ['POSTGRES_PASSWORD']}"
    )


def upsert_entity(pg, kind: str, value: str, display: str | None = None) -> int | None:
    if not value or not str(value).strip():
        return None
    fp = fp_entity(kind, str(value))
    with pg.cursor() as cur:
        cur.execute(
            """
            INSERT INTO entity (kind, canonical_value, fingerprint_sha256, display_name)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (fingerprint_sha256) DO UPDATE SET updated_at = NOW()
            RETURNING id
            """,
            (kind, str(value).strip(), fp, display),
        )
        return cur.fetchone()[0]


def upsert_dossier(pg, target_entity_id: int, target_label: str, summary_json: dict) -> int:
    pir = f"Migrated dossier — target {target_label}"
    with pg.cursor() as cur:
        cur.execute(
            "SELECT id FROM dossier WHERE target_entity_id = %s AND pir_question = %s ORDER BY created_at DESC LIMIT 1",
            (target_entity_id, pir),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            """
            INSERT INTO dossier
                (target_entity_id, pir_question, status, summary_markdown, summary_json)
            VALUES (%s, %s, 'completed', %s, %s)
            RETURNING id
            """,
            (target_entity_id, pir, "(migrated from JSON legacy store)", Json(summary_json)),
        )
        return cur.fetchone()[0]


def insert_finding(pg, dossier_id: int, domain: str, ftype: str, value: str,
                   related_entity_id: int | None = None,
                   confidence: float | None = None,
                   notes: str | None = None) -> int | None:
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
            (dossier_id, domain, ftype, str(value).strip(), related_entity_id,
             float(confidence) if confidence is not None else 0.6, notes, fp),
        )
        row = cur.fetchone()
        return row[0] if row else None


def _coerce_value(item: Any, *candidate_keys: str) -> str | None:
    """Return the first non-empty value from candidate keys, or the item itself if scalar."""
    if isinstance(item, str):
        return item if item.strip() else None
    if isinstance(item, dict):
        for k in candidate_keys:
            v = item.get(k)
            if v and isinstance(v, str) and v.strip():
                return v
    return None


def migrate_one(pg, path: Path) -> dict[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    stats: dict[str, int] = {k: 0 for k in (
        "entities", "findings_email", "findings_phone", "findings_profile",
        "findings_org", "findings_location", "findings_connection",
        "findings_device", "findings_breach", "sources_evidence", "sources_document",
        "traces_phase",
    )}

    target_id = data.get("target_id") or path.stem
    identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    display = identity.get("full_name") or identity.get("name") or target_id
    target_entity_id = upsert_entity(pg, "person", target_id, display=display)
    if target_entity_id is None:
        log.error("Could not upsert root entity for %s — skipping file", path.name)
        return stats
    stats["entities"] += 1

    dossier_id = upsert_dossier(pg, target_entity_id, target_id, summary_json={
        "target_id": target_id,
        "identity": identity,
        "created": data.get("created"),
        "updated": data.get("updated"),
        "notes": data.get("notes"),
    })

    # emails
    for it in data.get("emails", []) or []:
        v = _coerce_value(it, "email", "value")
        if not v: continue
        ent = upsert_entity(pg, "email", v)
        stats["entities"] += int(ent is not None)
        src_notes = "; ".join(it.get("sources", []) or []) if isinstance(it, dict) else None
        conf = it.get("confidence") if isinstance(it, dict) else None
        if isinstance(conf, str):
            conf = {"CONFIRMED": 0.9, "PROBABLE": 0.75, "UNVERIFIED": 0.55, "WEAK": 0.3}.get(conf.upper(), 0.6)
        if insert_finding(pg, dossier_id, "webint", "email", v, ent, conf, src_notes):
            stats["findings_email"] += 1

    # phones
    for it in data.get("phones", []) or []:
        v = _coerce_value(it, "phone", "number", "value")
        if not v: continue
        ent = upsert_entity(pg, "phone", v)
        stats["entities"] += int(ent is not None)
        notes_bits = []
        for c in ("carrier", "location"):
            if isinstance(it, dict) and it.get(c):
                notes_bits.append(f"{c}={it[c]}")
        notes = "; ".join(notes_bits) if notes_bits else None
        conf = it.get("confidence") if isinstance(it, dict) else None
        if isinstance(conf, str):
            conf = {"CONFIRMED": 0.9, "PROBABLE": 0.75, "UNVERIFIED": 0.55, "WEAK": 0.3}.get(conf.upper(), 0.6)
        if insert_finding(pg, dossier_id, "crossdb", "phone", v, ent, conf, notes):
            stats["findings_phone"] += 1

    # profiles
    for it in data.get("profiles", []) or []:
        url = _coerce_value(it, "url", "link")
        if not url: continue
        platform = it.get("platform") if isinstance(it, dict) else None
        notes = f"platform={platform}" if platform else None
        ent_value = url
        ent = upsert_entity(pg, "handle", ent_value)
        stats["entities"] += int(ent is not None)
        if insert_finding(pg, dossier_id, "socint", "profile_url", url, ent, None, notes):
            stats["findings_profile"] += 1

    # organizations
    for it in data.get("organizations", []) or []:
        v = _coerce_value(it, "name", "value")
        if not v: continue
        ent = upsert_entity(pg, "org", v)
        stats["entities"] += int(ent is not None)
        role = it.get("role") if isinstance(it, dict) else None
        if insert_finding(pg, dossier_id, "webint", "org", v, ent, None, f"role={role}" if role else None):
            stats["findings_org"] += 1

    # locations
    for it in data.get("locations", []) or []:
        v = _coerce_value(it, "name", "address", "value")
        if not v: continue
        if insert_finding(pg, dossier_id, "geoint", "location", v):
            stats["findings_location"] += 1

    # connections (social ties)
    for it in data.get("connections", []) or []:
        v = _coerce_value(it, "name", "handle", "value")
        if not v: continue
        rel = it.get("relation") if isinstance(it, dict) else None
        plat = it.get("platform") if isinstance(it, dict) else None
        notes_bits = []
        if rel:  notes_bits.append(f"relation={rel}")
        if plat: notes_bits.append(f"platform={plat}")
        if insert_finding(pg, dossier_id, "socialint", "connection", v,
                          notes="; ".join(notes_bits) if notes_bits else None):
            stats["findings_connection"] += 1

    # devices (TECHINT-ish)
    for it in data.get("devices", []) or []:
        v = _coerce_value(it, "model", "make", "name", "value")
        if not v: continue
        if insert_finding(pg, dossier_id, "geoint", "device_model", v):
            stats["findings_device"] += 1

    # breaches
    for it in data.get("breaches", []) or []:
        v = _coerce_value(it, "name", "breach", "value")
        if not v: continue
        if insert_finding(pg, dossier_id, "webint", "breach_record", v):
            stats["findings_breach"] += 1

    # evidence → source
    for it in data.get("evidence", []) or []:
        if not isinstance(it, dict): continue
        tool = it.get("tool") or "legacy"
        out  = it.get("output") or ""
        content_hash = hashlib.sha256(out.encode("utf-8")).hexdigest() if out else None
        with pg.cursor() as cur:
            cur.execute(
                "INSERT INTO source (tool_name, upstream, content_sha256, raw_payload) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (tool, tool.split("-")[0], content_hash, Json(it)),
            )
        stats["sources_evidence"] += 1

    # documents → source
    for it in data.get("documents", []) or []:
        if not isinstance(it, dict): continue
        content = it.get("content") or ""
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with pg.cursor() as cur:
            cur.execute(
                "INSERT INTO source (tool_name, upstream, content_sha256, raw_payload) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                ("document", "filesystem", content_hash, Json(it)),
            )
        stats["sources_document"] += 1

    # phase_log → trace
    for it in data.get("phase_log", []) or []:
        if not isinstance(it, dict): continue
        payload = {**it, "dossier_id": dossier_id, "migrated_from_json": path.name}
        h = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        with pg.cursor() as cur:
            cur.execute(
                "INSERT INTO trace (event, level, payload, hash_sha256) VALUES (%s, 'info', %s, %s)",
                (f"legacy.phase_log.{it.get('phase', 'unknown')}", Json(payload), h),
            )
        stats["traces_phase"] += 1

    return stats


def main() -> int:
    if "POSTGRES_PASSWORD" not in os.environ:
        log.error("POSTGRES_PASSWORD not set — source .env first")
        return 2
    if not INVESTIGATIONS_DIR.is_dir():
        log.warning("No investigations directory at %s", INVESTIGATIONS_DIR)
        return 0

    # Backup whole directory once per run
    backup_dir = Path(os.environ.get(
        "STRIKECORE_BACKUP_DIR", str(Path.home() / ".strikecore" / "backup")
    )) / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-json-pre-migration")
    backup_dir.mkdir(parents=True, exist_ok=True)
    for f in INVESTIGATIONS_DIR.glob("*.json"):
        shutil.copy2(f, backup_dir / f.name)
    log.info("Backup → %s", backup_dir)

    pg = psycopg2.connect(pg_dsn())
    pg.autocommit = False
    total: dict[str, int] = {}
    files_processed = 0
    try:
        for f in sorted(INVESTIGATIONS_DIR.glob("*.json")):
            log.info("Migrating %s", f.name)
            stats = migrate_one(pg, f)
            files_processed += 1
            for k, v in stats.items():
                total[k] = total.get(k, 0) + v
            pg.commit()
            log.info("  done: %s", stats)
    except Exception:
        pg.rollback()
        raise
    finally:
        pg.close()

    print(json.dumps({"files_processed": files_processed, "totals": total}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
