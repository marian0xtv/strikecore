"""
StrikeCore Database — SQLite persistent storage.

Migrates from JSON investigation store to SQLite for proper querying,
deletion, and web-based management.
"""
from __future__ import annotations
import json, os, sqlite3, time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path.home() / "strikecore-data" / "strikecore.db"

def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS targets (
        id TEXT PRIMARY KEY,
        display_name TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        notes TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS emails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_id TEXT NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
        email TEXT NOT NULL,
        confidence TEXT DEFAULT 'PROBABLE',
        sources TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        first_seen TEXT DEFAULT (datetime('now')),
        UNIQUE(target_id, email)
    );
    CREATE TABLE IF NOT EXISTS phones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_id TEXT NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
        phone TEXT NOT NULL,
        confidence TEXT DEFAULT 'PROBABLE',
        carrier TEXT DEFAULT '',
        location TEXT DEFAULT '',
        sources TEXT DEFAULT '',
        first_seen TEXT DEFAULT (datetime('now')),
        UNIQUE(target_id, phone)
    );
    CREATE TABLE IF NOT EXISTS profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_id TEXT NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
        platform TEXT NOT NULL,
        url TEXT NOT NULL,
        confidence TEXT DEFAULT 'CONFIRMED',
        notes TEXT DEFAULT '',
        verified_at TEXT DEFAULT (datetime('now')),
        UNIQUE(target_id, platform)
    );
    CREATE TABLE IF NOT EXISTS organizations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_id TEXT NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        role TEXT DEFAULT '',
        source TEXT DEFAULT '',
        UNIQUE(target_id, name)
    );
    CREATE TABLE IF NOT EXISTS locations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_id TEXT NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        source TEXT DEFAULT '',
        confidence TEXT DEFAULT 'PROBABLE'
    );
    CREATE TABLE IF NOT EXISTS connections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_id TEXT NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        relation TEXT DEFAULT '',
        platform TEXT DEFAULT '',
        url TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_id TEXT NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
        tool TEXT NOT NULL,
        output TEXT NOT NULL,
        timestamp TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_id TEXT NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
        filename TEXT NOT NULL,
        content TEXT NOT NULL,
        summary TEXT DEFAULT '',
        uploaded_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS phase_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_id TEXT NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
        phase TEXT NOT NULL,
        tools_used TEXT DEFAULT '',
        findings_count INTEGER DEFAULT 0,
        timestamp TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()
    conn.close()

def import_from_json(json_path: str):
    """Import a JSON investigation store into SQLite."""
    data = json.loads(Path(json_path).read_text())
    conn = get_db()
    tid = data.get("target_id", Path(json_path).stem)
    names = data.get("identity", {}).get("names", [])
    display = names[0] if names else tid
    
    conn.execute("INSERT OR REPLACE INTO targets (id, display_name, created_at, updated_at, notes) VALUES (?,?,?,?,?)",
                 (tid, display, data.get("created", ""), data.get("updated", ""),
                  json.dumps({"usernames": data.get("identity", {}).get("usernames", []),
                              "notes": data.get("notes", [])})))
    
    for email, info in data.get("emails", {}).items():
        conn.execute("INSERT OR REPLACE INTO emails (target_id, email, confidence, sources, first_seen) VALUES (?,?,?,?,?)",
                     (tid, email, info.get("confidence", ""), ",".join(info.get("sources", [])), info.get("first_seen", "")))
    
    for phone, info in data.get("phones", {}).items():
        conn.execute("INSERT OR REPLACE INTO phones (target_id, phone, confidence, carrier, location, sources) VALUES (?,?,?,?,?,?)",
                     (tid, phone, info.get("confidence", ""), info.get("carrier", ""), info.get("location", ""),
                      ",".join(info.get("sources", []))))
    
    for platform, info in data.get("profiles", {}).items():
        conn.execute("INSERT OR REPLACE INTO profiles (target_id, platform, url, confidence, notes) VALUES (?,?,?,?,?)",
                     (tid, platform, info.get("url", ""), info.get("confidence", ""), info.get("notes", "")))
    
    for name, info in data.get("organizations", {}).items():
        conn.execute("INSERT OR REPLACE INTO organizations (target_id, name, role, source) VALUES (?,?,?,?)",
                     (tid, name, info.get("role", ""), info.get("source", "")))
    
    for loc in data.get("locations", []):
        name = loc["name"] if isinstance(loc, dict) else loc
        conn.execute("INSERT OR IGNORE INTO locations (target_id, name, source) VALUES (?,?,?)",
                     (tid, name, loc.get("source", "") if isinstance(loc, dict) else ""))
    
    for conn_data in data.get("social_graph", []):
        conn.execute("INSERT OR IGNORE INTO connections (target_id, name, relation, platform, url) VALUES (?,?,?,?,?)",
                     (tid, conn_data.get("name", ""), conn_data.get("relation", ""),
                      conn_data.get("platform", ""), conn_data.get("url", "")))
    
    for tool, evidences in data.get("raw_evidence", {}).items():
        for ev in evidences:
            conn.execute("INSERT INTO evidence (target_id, tool, output, timestamp) VALUES (?,?,?,?)",
                         (tid, tool, ev.get("output", ""), ev.get("timestamp", "")))
    
    for phase in data.get("phase_log", []):
        conn.execute("INSERT INTO phase_log (target_id, phase, tools_used, findings_count, timestamp) VALUES (?,?,?,?,?)",
                     (tid, phase.get("phase", ""), ",".join(phase.get("tools_used", [])),
                      phase.get("findings_count", 0), phase.get("timestamp", "")))
    
    conn.commit()
    conn.close()
    return tid

# Initialize on import
init_db()
