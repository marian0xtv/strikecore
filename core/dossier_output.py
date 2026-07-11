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
import re
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


def finalize_dashboard_artifacts(
    store: Any,
    *,
    dossier_json: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Produce the dashboard-facing artifacts EVERY dossier must have.

    This is the single, path-agnostic enforcer of the "finished dossier" standard
    so it holds categorically across all three dossier paths (console ``dossier``,
    ``bin/intel-team.py``, ``bin/agent-dossier.py``):

        * ``~/strikecore-data/reports/<tid>_report.{md,html}``  -> Report tab
        * ``~/strikecore-data/reports/graphs/<tid>_graph.html`` -> Graph tab
        * populated ``store.locations``                         -> GeoMap

    Driven by the live ``InvestigationStore`` (``store``) because the dashboard
    target view is keyed on ``store.target_id``. When ``dossier_json`` carries a
    structured ``locations`` list (top-level or under ``investigation_store``),
    those are harvested into the store first so the GeoMap populates regardless
    of the collection path.

    Idempotent and fully failure-isolated: a failure here must never break a
    dossier run. Returns the paths written (and any per-step error strings).
    Heavy deps (``report_builder``/``graph_engine`` pull in networkx/pyvis) are
    imported lazily so this module stays cheap and dependency-free to import.
    """
    result: dict[str, str] = {}
    if store is None:
        return result

    # 1) Harvest structured locations from the dossier payload into the store,
    #    so paths that carry locations in their dict (but not yet in the store)
    #    still get a populated GeoMap. Purely structured — never free-text.
    try:
        _harvest_locations(store, dossier_json)
    except Exception:  # noqa: BLE001
        pass

    # 2) Snapshot the store and render the operator-facing report + graph.
    try:
        data = store.data
        tid = data.get("target_id")
    except Exception:  # noqa: BLE001
        return result
    if not tid:
        return result

    # Gap-filling, NOT overwriting: the console dossier agent often writes a
    # richer <tid>_dossier.md and <tid>_graph.html (with connections/orgs the
    # store does not capture). We only synthesize the store-derived artifact
    # when the agent's is absent, so the standard is guaranteed present without
    # ever downgrading the agent's output.
    try:
        from core.report_builder import save_report, REPORTS_DIR as _RD
        if (_RD / f"{tid}_dossier.md").exists():
            result["report_skipped"] = "agent dossier.md present"
        else:
            md_path, html_path = save_report(data, tid)
            result["report_md"] = str(md_path)
            result["report_html"] = str(html_path)
    except Exception as exc:  # noqa: BLE001
        result["report_error"] = str(exc)

    try:
        from core.graph_engine import build_graph, GRAPHS_DIR as _GD
        if (_GD / f"{tid}_graph.html").exists():
            result["graph_skipped"] = "agent graph present"
        else:
            _graph, graph_path = build_graph(data)
            result["graph_html"] = str(graph_path)
    except Exception as exc:  # noqa: BLE001
        result["graph_error"] = str(exc)

    return result


def _harvest_locations(store: Any, dossier_json: dict[str, Any] | None) -> None:
    """Copy any STRUCTURED locations from ``dossier_json`` into ``store``.

    Reads only explicit ``locations`` lists (top-level and under an embedded
    ``investigation_store`` snapshot) — dict entries ``{name, source, confidence}``
    or bare strings. Never parses free text (no geocoding false positives).
    ``store.add_location`` de-duplicates and auto-persists.
    """
    if not isinstance(dossier_json, dict):
        return
    buckets = [dossier_json.get("locations")]
    inv = dossier_json.get("investigation_store")
    if isinstance(inv, dict):
        buckets.append(inv.get("locations"))
    for locs in buckets:
        if not isinstance(locs, list):
            continue
        for entry in locs:
            if isinstance(entry, dict):
                name = entry.get("name")
                source = entry.get("source", "") or "dossier"
                confidence = entry.get("confidence", "PROBABLE") or "PROBABLE"
            elif isinstance(entry, str):
                name, source, confidence = entry, "dossier", "PROBABLE"
            else:
                continue
            if isinstance(name, str):
                name = name.strip()
                if 1 < len(name) <= 60:
                    store.add_location(name, source=source, confidence=confidence)


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


# ANSI escape sequences (Rich emits these when the real stream is a TTY); we
# strip them so output.log is clean plaintext for Hephaestus ingestion.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "")


@contextmanager
def tee_streams() -> Iterator[dict[str, str]]:
    """Tee BOTH ``sys.stdout`` and ``sys.stderr`` into one buffer for the run.

    This is the robust, console-instance-agnostic capture: every default Rich
    ``Console()`` (there are several — ``cli/shell.py`` and ``core/nlp_engine.py``
    each hold their own) resolves ``sys.stdout`` at write time, so replacing the
    streams captures ALL of them plus raw ``print`` in one chronological
    transcript. Yields a holder dict whose ``text`` key is filled with the
    ANSI-stripped transcript on exit. Failure-isolated: any error restores the
    real streams and leaves whatever was captured.

    Caveat: a ``logging.StreamHandler`` that bound ``sys.stderr`` at import time
    holds a direct reference and bypasses this tee; only writes that resolve the
    current ``sys.stdout``/``sys.stderr`` at emit time are captured. Dossier
    output is Rich/``print``, so this is not a gap in practice.

    Use this (not ``record_console``) for dossier capture — ``record_console``
    only sees the single console instance it is handed, which is why the console
    ``dossier`` path was writing empty logs.
    """
    holder = {"text": ""}
    buf = io.StringIO()
    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout = _Tee(real_out, buf)  # type: ignore[assignment]
    sys.stderr = _Tee(real_err, buf)  # type: ignore[assignment]
    try:
        yield holder
    finally:
        sys.stdout = real_out
        sys.stderr = real_err
        try:
            holder["text"] = _strip_ansi(buf.getvalue())
        except Exception:
            holder["text"] = ""


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
