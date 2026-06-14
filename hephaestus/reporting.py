"""Operator-facing run reporters for Hephaestus.

The agent is surface-agnostic: it emits run events to an injected RunReporter
instead of printing. NullReporter (the default) is silent and defers every gate
-- preserving programmatic/test behavior. StreamReporter renders live phase
banners + token streaming to a text stream and prompts for gate approval, but
only when its input stream is a TTY (otherwise it defers, so cron/pipes still
work). ASCII only, no emojis (house style, §12).
"""

from __future__ import annotations

import sys
from typing import Any, TextIO


class RunReporter:
    """No-op base. Subclasses render run events to an operator surface."""

    def phase(self, name: str, detail: str = "") -> None: ...
    def info(self, message: str) -> None: ...
    def stream_start(self, label: str, model: str) -> None: ...
    def stream_delta(self, text: str) -> None: ...
    def stream_end(self) -> None: ...
    def gate_result(self, gate: dict, approved: bool,
                    register_cmd: str | None) -> None: ...

    def request_gate(self, gate: dict) -> bool:
        """Return True to approve the gate now, False to defer to pending."""
        return False


class NullReporter(RunReporter):
    """Silent; defers all gates. Default for programmatic / test callers."""


class StreamReporter(RunReporter):
    """Live phases + token streaming to ``out``; TTY-gated gate prompts on ``in_``."""

    def __init__(self, out: TextIO | None = None, in_: Any | None = None) -> None:
        self._out = out if out is not None else sys.stdout
        self._in = in_ if in_ is not None else sys.stdin

    def _w(self, s: str) -> None:
        try:
            self._out.write(s)
            self._out.flush()
        except Exception:  # never let output break a run
            pass

    def phase(self, name: str, detail: str = "") -> None:
        suffix = f" -- {detail}" if detail else ""
        self._w(f"\n=== {name.upper()}{suffix} ===\n")

    def info(self, message: str) -> None:
        self._w(f"  {message}\n")

    def stream_start(self, label: str, model: str) -> None:
        self._w(f"\n  >> {label}  [{model}]\n    ")

    def stream_delta(self, text: str) -> None:
        # keep streamed text indented under the stream header
        self._w(text.replace("\n", "\n    "))

    def stream_end(self) -> None:
        self._w("\n")

    def request_gate(self, gate: dict) -> bool:
        prompt = (f"\n  GATE {gate.get('gate', '?')} -- {gate.get('reason', '')}\n"
                  f"  Approve now? [y/N] ")
        try:
            is_tty = bool(self._in.isatty())
        except Exception:
            is_tty = False
        if not is_tty:
            self._w(prompt + "(non-interactive: deferred)\n")
            return False
        self._w(prompt)
        try:
            answer = (self._in.readline() or "").strip().lower()
        except (EOFError, KeyboardInterrupt, Exception):
            return False
        return answer in ("y", "yes")

    def gate_result(self, gate: dict, approved: bool,
                    register_cmd: str | None) -> None:
        g = gate.get("gate", "?")
        if approved:
            self._w(f"    {g} APPROVED.\n")
            if register_cmd:
                self._w(f"    -> when the tool is built, register it with:\n"
                        f"       {register_cmd}\n")
        else:
            self._w(f"    {g} deferred -> pending "
                    f"(clear later: hephaestus approve <run_id> {g}).\n")
