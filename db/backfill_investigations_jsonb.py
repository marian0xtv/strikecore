#!/usr/bin/env python3
"""One-time backfill: legacy file store -> investigation JSONB table.

Loads each ``~/strikecore-data/investigations/*.json`` into the new
``investigation(target_id, data)`` JSONB table (decision I1 / task T4).
Idempotent via ``ON CONFLICT``. Run with PG env set (inside the backend or
toolbox container, or on the host):

    POSTGRES_HOST=... POSTGRES_PASSWORD=... python3 db/backfill_investigations_jsonb.py

This is the lossless JSONB swap — it does NOT normalize into entity/dossier/
finding (that's the separate, deferred migrate_from_json.py path).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import pg  # noqa: E402
from psycopg2.extras import Json  # noqa: E402


def main() -> int:
    store = Path(os.environ.get(
        "STRIKECORE_INVESTIGATIONS",
        str(Path.home() / "strikecore-data" / "investigations"),
    ))
    if not store.is_dir():
        print(f"no investigations dir at {store} — nothing to backfill")
        return 0

    n = 0
    with pg.cursor() as cur:
        for f in sorted(store.glob("*.json")):
            try:
                data = json.loads(f.read_text())
            except Exception as exc:  # noqa: BLE001
                print(f"skip {f.name}: {exc}")
                continue
            target_id = data.get("target_id") or f.stem
            cur.execute(
                "INSERT INTO investigation (target_id, data, updated) "
                "VALUES (%s, %s, NOW()) "
                "ON CONFLICT (target_id) DO UPDATE SET data = EXCLUDED.data, updated = NOW()",
                (target_id, Json(data)),
            )
            n += 1
    print(f"backfilled {n} investigations into Postgres")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
