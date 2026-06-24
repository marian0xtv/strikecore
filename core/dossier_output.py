"""Unified dossier output capture (the ``dossieroutputs/`` mirror).

Every dossier-producing path in StrikeCore — the console ``dossier`` command, the
``intel-team`` orchestrator, and the ``agent-dossier`` flow — writes a uniform
per-run folder here:

    ~/strikecore-data/dossieroutputs/<UTC>_<source>_<target>/
        dossier.json   complete structured record (the dossier / store snapshot)
        output.log     the ENTIRE captured run transcript
        meta.json      target, source, pir/task, timestamps, sibling report paths
        dossier.md     human-readable markdown (when the path produces one)

This folder is the single source Hephaestus reads for its dossier-mode
autoimprove pass (``hephaestus run --fetch-from-outputs``). Capture is additive
and failure-isolated: a write/IO error here must never break a dossier run.

Stdlib only. ASCII house style (CLAUDE.md section 12).
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

OUTPUT_DIR = Path.home() / "strikecore-data" / "dossieroutputs"

# Sources allowed to write here (kept loose; used only for the folder name).
SOURCES = ("console", "intel_team", "agent_dossier")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe(name: str, limit: int = 80) -> str:
    """Sanitize a target/source for use in a path segment (intel-team idiom)."""
    s = "".join(c if c.isalnum() or c in "._-" else "_" for c in (name or "")).strip("_")
    return (s or "unknown")[:limit]


def new_run_dir(target: str, source: str) -> Path:
    """Create and return ``OUTPUT_DIR/<UTC>_<source>_<target>/``."""
    run_dir = OUTPUT_DIR / f"{_utc_stamp()}_{_safe(source, 20)}_{_safe(target)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_run(
    run_dir: Path,
    *,
    meta: dict[str, Any],
    dossier_json: dict[str, Any],
    transcript: str,
    markdown: str | None = None,
) -> dict[str, Path]:
    """Write the four artifacts into ``run_dir``. Never raises (best-effort)."""
    written: dict[str, Path] = {}
    full_meta = {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **meta,
    }
    artifacts: list[tuple[str, str]] = [
        ("dossier.json", json.dumps(dossier_json, ensure_ascii=False, indent=2, default=str)),
        ("output.log", transcript or ""),
        ("meta.json", json.dumps(full_meta, ensure_ascii=False, indent=2, default=str)),
    ]
    if markdown is not None:
        artifacts.append(("dossier.md", markdown))
    for name, body in artifacts:
        try:
            path = run_dir / name
            path.write_text(body, encoding="utf-8")
            written[name] = path
        except OSError:
            continue
    return written


def iter_runs(limit: int | None = None) -> list[dict[str, Any]]:
    """Newest-first captured runs. Each entry: {dir, meta, dossier, log_path}.

    ``dossier``/``meta`` are parsed JSON (``{}`` if missing/corrupt); ``log_path``
    points at ``output.log`` (read lazily by callers — it can be large).
    """
    if not OUTPUT_DIR.exists():
        return []
    dirs = sorted(
        (p for p in OUTPUT_DIR.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if limit is not None:
        dirs = dirs[:limit]
    out: list[dict[str, Any]] = []
    for d in dirs:
        out.append({
            "dir": d,
            "meta": _load_json(d / "meta.json"),
            "dossier": _load_json(d / "dossier.json"),
            "log_path": d / "output.log",
        })
    return out


def _load_json(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


# --------------------------------------------------------------------------
# Capture helpers
# --------------------------------------------------------------------------

class _Tee:
    """Write-through to a real stream while accumulating into a buffer."""

    def __init__(self, real: Any, buf: io.StringIO) -> None:
        self._real = real
        self._buf = buf

    def write(self, s: str) -> int:
        try:
            self._real.write(s)
        except Exception:
            pass
        self._buf.write(s)
        return len(s)

    def flush(self) -> None:
        try:
            self._real.flush()
        except Exception:
            pass

    def __getattr__(self, name: str) -> Any:  # isatty, encoding, fileno, ...
        return getattr(self._real, name)


@contextmanager
def tee_stdout() -> Iterator[io.StringIO]:
    """Tee ``sys.stdout`` into a buffer for the duration. Yields the buffer.

    Used by the ``bin/`` dossier scripts (they emit via ``print``): output still
    reaches the terminal and is mirrored into the returned buffer.
    """
    buf = io.StringIO()
    real = sys.stdout
    sys.stdout = _Tee(real, buf)  # type: ignore[assignment]
    try:
        yield buf
    finally:
        sys.stdout = real


@contextmanager
def record_console(console: Any) -> Iterator[dict[str, str]]:
    """Record a Rich ``console`` while keeping its live display intact.

    Yields a dict whose ``text`` key is populated with the captured transcript on
    exit (``console.export_text(clear=True)``). Restores the prior ``record``
    flag. Failure-isolated: any error leaves ``text`` empty.
    """
    holder = {"text": ""}
    prev = getattr(console, "record", False)
    try:
        console.record = True
    except Exception:
        yield holder
        return
    try:
        yield holder
    finally:
        try:
            holder["text"] = console.export_text(clear=True)
        except Exception:
            holder["text"] = ""
        try:
            console.record = prev
        except Exception:
            pass
