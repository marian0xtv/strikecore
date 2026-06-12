"""sctool — shared helpers for StrikeCore contract-conformant OSINT tools.

Every tool under tools/<name>/ uses this to:
  * build the standard I/O envelope (schema/io.envelope.schema.json),
  * attach per-result NATO Admiralty reliability + credibility,
  * expose the uniform CLI surface (--config / --selftest / --json),
  * run a no-real-targets self-test with consistent exit codes.

Pure standard library — no third-party imports — so it runs anywhere a
contract tool runs (including inside the post-receive hook environment).

Exit-code convention (shared by all tools):
    0   success
    1   tool-level failure (ran, but the operation failed / finding negative)
    2   usage error (bad args)
    3   internal/integration error (envelope could not be produced)

Admiralty Code (NATO STANAG):
    reliability: A completely reliable .. F cannot be judged
    credibility: 1 confirmed .. 6 cannot be judged
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

SCHEMA_VERSION = 1

# Exit codes
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_INTERNAL = 3

# NATO Admiralty reliability grades
RELIABILITY_A = "A"  # completely reliable
RELIABILITY_B = "B"  # usually reliable
RELIABILITY_C = "C"  # fairly reliable
RELIABILITY_D = "D"  # not usually reliable
RELIABILITY_E = "E"  # unreliable
RELIABILITY_F = "F"  # reliability cannot be judged
_VALID_RELIABILITY = {"A", "B", "C", "D", "E", "F"}

# NATO Admiralty credibility grades
CREDIBILITY_CONFIRMED = 1
CREDIBILITY_PROBABLE = 2
CREDIBILITY_POSSIBLE = 3
CREDIBILITY_DOUBTFUL = 4
CREDIBILITY_IMPROBABLE = 5
CREDIBILITY_CANNOT_JUDGE = 6


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    return uuid.uuid4().hex


def result(
    type: str,
    value: Any,
    reliability: str,
    confidence: int,
    sources: Iterable[str] | None = None,
) -> dict:
    """Build one envelope result with Admiralty scoring.

    Raises ValueError on out-of-range Admiralty grades so a malformed tool
    fails loudly rather than emitting an invalid envelope.
    """
    if reliability not in _VALID_RELIABILITY:
        raise ValueError(f"reliability must be one of A-F, got {reliability!r}")
    if not (1 <= int(confidence) <= 6):
        raise ValueError(f"confidence must be 1-6, got {confidence!r}")
    return {
        "type": str(type),
        "value": value,
        "reliability": reliability,
        "confidence": int(confidence),
        "sources": list(sources or []),
    }


def error(code: str, message: str, detail: str | None = None) -> dict:
    rec = {"code": str(code), "message": str(message)}
    if detail is not None:
        rec["detail"] = str(detail)
    return rec


def build_envelope(
    tool: str,
    tool_version: str,
    input_echo: dict | None,
    results: list[dict] | None,
    errors: list[dict] | None,
    run_id: str,
    selftest: bool,
    duration_ms: int,
    target: str | None = None,
) -> dict:
    """Assemble a schema/io.envelope.schema.json-conformant object."""
    audit: dict[str, Any] = {
        "run_id": run_id,
        "selftest": bool(selftest),
        "duration_ms": int(duration_ms),
    }
    if target is not None:
        audit["target"] = target
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": tool,
        "tool_version": tool_version,
        "timestamp": _now_iso(),
        "input": dict(input_echo or {}),
        "results": list(results or []),
        "errors": list(errors or []),
        "audit": audit,
    }


def base_argparser(prog: str, description: str) -> argparse.ArgumentParser:
    """Argparser pre-loaded with the uniform contract flags.

    Tools add their own domain flags on top of this.
    """
    p = argparse.ArgumentParser(prog=prog, description=description)
    p.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to a JSON/TOML config file (secrets via env, never hardcoded).",
    )
    p.add_argument(
        "--selftest",
        action="store_true",
        help="Run an offline health check that does NOT contact real targets, then exit.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit the JSON I/O envelope on stdout (default for machine consumption).",
    )
    return p


def emit(envelope: dict, as_json: bool = True) -> None:
    """Print the envelope. Always JSON to stdout (the contract output channel)."""
    sys.stdout.write(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n")


def run_selftest(
    tool: str,
    tool_version: str,
    check: Callable[[], tuple[bool, list[dict], list[dict]]],
) -> int:
    """Run a tool's offline self-test and emit a selftest envelope.

    `check` must return (ok, results, errors) and MUST NOT touch real targets.
    Returns EXIT_OK on pass, EXIT_FAIL on a failed check, EXIT_INTERNAL on crash.
    """
    run_id = new_run_id()
    start = time.monotonic()
    try:
        ok, results, errors = check()
    except Exception as exc:  # noqa: BLE001 - selftest must never propagate
        env = build_envelope(
            tool, tool_version, {"selftest": True}, [],
            [error("selftest_crash", "self-test raised", repr(exc))],
            run_id, True, int((time.monotonic() - start) * 1000),
        )
        emit(env)
        return EXIT_INTERNAL
    duration_ms = int((time.monotonic() - start) * 1000)
    env = build_envelope(
        tool, tool_version, {"selftest": True},
        results, errors, run_id, True, duration_ms,
    )
    emit(env)
    return EXIT_OK if ok else EXIT_FAIL
