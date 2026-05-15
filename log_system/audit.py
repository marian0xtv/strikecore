"""
Audit trail for StrikeCore.

Every significant action -- command execution, tool invocation, AI
interaction, provider switch, and finding -- is logged as a structured
JSON-lines entry under ``~/.strikecore/audit/``.  One file is created per
calendar day (``YYYY-MM-DD.jsonl``).

Usage::

    from log_system.audit import audit

    audit.log_event("COMMAND_EXEC", {"command": "nmap -sV target"})
    events = audit.get_events(session_id="abc123")
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_AUDIT_DIR = Path.home() / ".strikecore" / "audit"

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


class EventType(str, Enum):
    """Recognised audit event types."""

    COMMAND_EXEC = "COMMAND_EXEC"
    TOOL_CALL = "TOOL_CALL"
    AI_REQUEST = "AI_REQUEST"
    AI_RESPONSE = "AI_RESPONSE"
    PROVIDER_SWITCH = "PROVIDER_SWITCH"
    FINDING = "FINDING"
    SESSION_START = "SESSION_START"
    SESSION_END = "SESSION_END"


# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------


@dataclass
class AuditEntry:
    """Single audit-trail record.

    Attributes
    ----------
    timestamp : str
        ISO-8601 UTC timestamp.
    session_id : str
        Unique session identifier.
    event_type : str
        One of :class:`EventType` values.
    details : dict
        Arbitrary key/value payload describing the event.
    operator : str
        Human operator or system identity responsible for the event.
    """

    timestamp: str
    session_id: str
    event_type: str
    details: Dict[str, Any] = field(default_factory=dict)
    operator: str = "system"


# ---------------------------------------------------------------------------
# AuditLogger
# ---------------------------------------------------------------------------


class AuditLogger:
    """Thread-safe audit logger backed by daily JSON-lines files."""

    def __init__(self, audit_dir: Optional[Path] = None) -> None:
        self._audit_dir = audit_dir or _AUDIT_DIR
        self._lock = threading.Lock()
        self._session_id: str = ""
        self._operator: str = "system"

    # -- Configuration -------------------------------------------------------

    def set_session(self, session_id: str, operator: str = "system") -> None:
        """Bind a session id and operator name to all subsequent entries."""
        self._session_id = session_id
        self._operator = operator

    # -- Writing -------------------------------------------------------------

    def log_event(
        self,
        event_type: str,
        details: Optional[Dict[str, Any]] = None,
        *,
        session_id: Optional[str] = None,
        operator: Optional[str] = None,
    ) -> AuditEntry:
        """Create and persist an audit entry.

        Parameters
        ----------
        event_type:
            Must match one of :class:`EventType` values.
        details:
            Arbitrary payload.  Large values (e.g. full AI responses) should
            be truncated by the caller.
        session_id:
            Override the default session id for this entry.
        operator:
            Override the default operator for this entry.

        Returns
        -------
        AuditEntry
            The persisted entry.
        """
        # Validate event type
        try:
            EventType(event_type)
        except ValueError:
            pass  # Allow custom event types; canonical ones are just guidance.

        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=session_id or self._session_id,
            event_type=event_type,
            details=details or {},
            operator=operator or self._operator,
        )

        self._write(entry)
        return entry

    def _write(self, entry: AuditEntry) -> None:
        """Append *entry* as a single JSON line to today's audit file."""
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()  # YYYY-MM-DD
        path = self._audit_dir / f"{today}.jsonl"

        line = json.dumps(asdict(entry), default=str, ensure_ascii=False) + "\n"

        with self._lock:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)

    # -- Reading / querying --------------------------------------------------

    def get_events(
        self,
        *,
        session_id: Optional[str] = None,
        date_filter: Optional[date] = None,
        event_type: Optional[str] = None,
    ) -> List[AuditEntry]:
        """Retrieve audit entries, optionally filtered.

        Parameters
        ----------
        session_id:
            Return only entries belonging to this session.
        date_filter:
            Return entries from this specific date.  When *None*, all
            available days are scanned.
        event_type:
            Return only entries of this type.

        Returns
        -------
        list[AuditEntry]
            Matching entries in chronological order.
        """
        self._audit_dir.mkdir(parents=True, exist_ok=True)

        if date_filter is not None:
            files = [self._audit_dir / f"{date_filter.isoformat()}.jsonl"]
        else:
            files = sorted(self._audit_dir.glob("*.jsonl"))

        entries: List[AuditEntry] = []
        for path in files:
            if not path.exists():
                continue
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    entry = AuditEntry(**data)
                    if session_id and entry.session_id != session_id:
                        continue
                    if event_type and entry.event_type != event_type:
                        continue
                    entries.append(entry)

        return entries

    # -- Export --------------------------------------------------------------

    def export_audit(
        self,
        fmt: str = "json",
        *,
        session_id: Optional[str] = None,
        date_filter: Optional[date] = None,
    ) -> str:
        """Export audit entries as a formatted string.

        Parameters
        ----------
        fmt:
            ``'json'`` (default) returns a JSON array.  ``'csv'`` returns
            comma-separated values.  ``'text'`` returns a human-readable
            plain-text summary.
        session_id:
            Optional session filter.
        date_filter:
            Optional date filter.

        Returns
        -------
        str
            The serialised audit data.
        """
        entries = self.get_events(session_id=session_id, date_filter=date_filter)
        records = [asdict(e) for e in entries]

        if fmt == "json":
            return json.dumps(records, indent=2, default=str, ensure_ascii=False)

        if fmt == "csv":
            if not records:
                return "timestamp,session_id,event_type,operator,details\n"
            lines = ["timestamp,session_id,event_type,operator,details"]
            for r in records:
                detail_str = json.dumps(r["details"], ensure_ascii=False)
                # Escape double-quotes for CSV
                detail_str = detail_str.replace('"', '""')
                lines.append(
                    f'{r["timestamp"]},{r["session_id"]},'
                    f'{r["event_type"]},{r["operator"]},"{detail_str}"'
                )
            return "\n".join(lines) + "\n"

        if fmt == "text":
            if not records:
                return "No audit entries found.\n"
            lines: List[str] = []
            for r in records:
                lines.append(
                    f'[{r["timestamp"]}] {r["event_type"]} '
                    f'session={r["session_id"]} operator={r["operator"]} '
                    f'details={json.dumps(r["details"], ensure_ascii=False)}'
                )
            return "\n".join(lines) + "\n"

        raise ValueError(f"Unsupported export format: {fmt!r}")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

audit = AuditLogger()
"""Module-level :class:`AuditLogger` instance.

Import and use directly::

    from log_system.audit import audit
    audit.log_event("TOOL_CALL", {"tool": "nmap", "args": "-sV host"})
"""
