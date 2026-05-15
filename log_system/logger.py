"""
Structured logging for StrikeCore.

Configures loguru with JSON format for file output and Rich format for
console output.  Logs are written to ``~/.strikecore/logs/`` with automatic
rotation (10 MB per file, retained for 30 days).

Usage::

    from log_system.logger import log, setup_logging

    setup_logging(level="DEBUG", json_logs=True)
    log.info("Scan started", session_id="abc123", tool_name="nmap")
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_LOG_DIR = Path.home() / ".strikecore" / "logs"

# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _json_sink(message: Any) -> None:
    """Write serialized (JSON) log records to the active log file.

    loguru's ``serialize=True`` flag converts each record to JSON before it
    reaches the sink, so we simply write the pre-serialized string.
    """
    sys.stderr.write(message)


def _rich_format(record: Dict[str, Any]) -> str:
    """Build a Rich-friendly format string for console output.

    The format includes colour-coded level, timestamp, and any extra
    context fields that were bound to the logger.
    """
    # Collect context extras (ignore loguru internal keys)
    extras = {
        k: v
        for k, v in record["extra"].items()
        if k not in ("__builtins__",)
    }
    ctx = ""
    if extras:
        parts = [f"<dim>{k}</dim>=<cyan>{v}</cyan>" for k, v in extras.items()]
        ctx = " | " + " ".join(parts)

    return (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
        + ctx
        + "\n{exception}"
    )


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def setup_logging(
    level: str = "INFO",
    json_logs: bool = False,
) -> "logger":
    """Configure the module-level logger and return it.

    Parameters
    ----------
    level:
        Minimum log level (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``,
        ``CRITICAL``).
    json_logs:
        When *True*, file logs are written in JSON-lines format.  Console
        output always uses the Rich-friendly human-readable format.

    Returns
    -------
    loguru.Logger
        The configured logger instance (same object as the module-level
        ``log``).
    """
    level = level.upper()

    # Ensure the log directory exists.
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Remove any previously-installed handlers so setup is idempotent.
    logger.remove()

    # -- Console handler (always human-readable) ----------------------------
    logger.add(
        sys.stderr,
        level=level,
        format=_rich_format,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # -- File handler -------------------------------------------------------
    log_file = _LOG_DIR / "strikecore.log"

    if json_logs:
        logger.add(
            str(log_file),
            level=level,
            serialize=True,
            rotation="10 MB",
            retention="30 days",
            compression="gz",
            encoding="utf-8",
            enqueue=True,  # thread-safe
        )
    else:
        logger.add(
            str(log_file),
            level=level,
            format=(
                "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
                "{name}:{function}:{line} | {message} | {extra}"
            ),
            rotation="10 MB",
            retention="30 days",
            compression="gz",
            encoding="utf-8",
            enqueue=True,
        )

    logger.debug(
        "Logging initialised",
        level=level,
        json_logs=json_logs,
        log_dir=str(_LOG_DIR),
    )

    return logger


# ---------------------------------------------------------------------------
# Context binding helpers
# ---------------------------------------------------------------------------


def bind_context(
    *,
    session_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    provider: Optional[str] = None,
    tool_name: Optional[str] = None,
) -> "logger":
    """Return a logger with the given context fields bound.

    This is a convenience wrapper around ``logger.bind()``.  Only non-None
    values are attached so the log output stays clean.

    Usage::

        ctx_log = bind_context(session_id="abc", tool_name="nmap")
        ctx_log.info("Starting scan")
    """
    context: Dict[str, Any] = {}
    if session_id is not None:
        context["session_id"] = session_id
    if agent_name is not None:
        context["agent_name"] = agent_name
    if provider is not None:
        context["provider"] = provider
    if tool_name is not None:
        context["tool_name"] = tool_name
    return logger.bind(**context)


# ---------------------------------------------------------------------------
# Module-level convenience instance
# ---------------------------------------------------------------------------

log = logger
"""Module-level loguru logger instance.

Import this directly for quick logging::

    from log_system.logger import log
    log.info("something happened")

For structured context, use :func:`bind_context` or call
``log.bind(session_id=..., ...)`` directly.
"""
