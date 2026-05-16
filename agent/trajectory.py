"""ShareGPT-format JSONL trajectory writer.

Hermes Agent persists every conversation + tool invocation as JSONL records;
we mirror that pattern so the trajectories are interchangeable with the
upstream Hermes tooling. Records live at:

    ~/.strikecore/trajectories/<dossier_id_or_session>.jsonl

Each line is a self-contained JSON object — append-only, never rewrite.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("agent.trajectory")

_DIR = Path.home() / ".strikecore" / "trajectories"


def _path(session_id: str) -> Path:
    _DIR.mkdir(parents=True, exist_ok=True)
    return _DIR / f"{session_id}.jsonl"


def append(session_id: str, role: str, content: Any, **extra: Any) -> None:
    """Append a ShareGPT-style record to the trajectory file."""
    rec: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "role": role,                 # 'system' | 'user' | 'assistant' | 'tool' | 'event'
        "content": content,
    }
    rec.update(extra)
    try:
        with _path(session_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        logger.warning("trajectory append failed (%s): %s", session_id, exc)


def open_session(session_id: str, pir_id: str, target: str, operator_notes: str = "") -> None:
    """Write the opening 'session' marker."""
    append(session_id, "event", "session_open", pir_id=pir_id, target=target,
           operator_notes=operator_notes)


def close_session(session_id: str, dossier_id: int | None, cost_micros: int) -> None:
    append(session_id, "event", "session_close", dossier_id=dossier_id, cost_micros=cost_micros)
