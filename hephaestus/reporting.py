"""Operator-facing run reporters for Hephaestus.

The agent is surface-agnostic: it emits run events to an injected RunReporter
instead of printing. NullReporter (the default) is silent and defers every gate
-- preserving programmatic/test behavior. StreamReporter renders live phase
banners + token streaming to a text stream and prompts for gate approval, but
only when its input stream is a TTY (otherwise it defers, so cron/pipes still
work). ASCII only, no emojis (house style, see CLAUDE.md section 12).
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
        except (KeyboardInterrupt, Exception):
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


class EventBusReporter(RunReporter):
    """Forwards Hephaestus run events to the live event bus (core.agent_events).

    Silent on its own (it never prompts and always defers gates -> returns False);
    compose it with a StreamReporter via MultiReporter to keep live stdout AND feed
    the Control Room. Per-token deltas are buffered and summarised on stream_end to
    keep the event log compact.
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._buf: list[str] = []

    def _emit(self, event_type: str, **fields) -> None:
        try:
            from core import agent_events
            agent_events.emit(event_type, run_id=self.run_id, **fields)
        except Exception:  # never let telemetry break a run
            pass

    def phase(self, name: str, detail: str = "") -> None:
        self._emit("phase", phase=name, detail=(detail or name))

    def info(self, message: str) -> None:
        self._emit("info", detail=message)

    def stream_start(self, label: str, model: str) -> None:
        self._buf = []
        self._emit("stream_start", model=model, detail=label)

    def stream_delta(self, text: str) -> None:
        # buffer only; cost lands via the router on_call hook, summary on end
        self._buf.append(text)

    def stream_end(self) -> None:
        summary = "".join(self._buf).strip().replace("\n", " ")[:160]
        self._buf = []
        self._emit("stream_end", detail=summary)

    def request_gate(self, gate: dict) -> bool:
        self._emit("gate_request", gate=gate.get("gate", "?"),
                   detail=gate.get("reason", ""))
        return False  # never approves; defers to a prompting reporter

    def gate_result(self, gate: dict, approved: bool,
                    register_cmd: str | None) -> None:
        self._emit("gate_result", gate=gate.get("gate", "?"), approved=approved,
                   detail=(register_cmd or ""))


class MultiReporter(RunReporter):
    """Fan-out reporter: forwards every hook to each child reporter in order.

    request_gate returns True if ANY child approves; children are called in list
    order, so place the EventBusReporter FIRST (emit the pending gate) and a
    prompting StreamReporter AFTER it (which blocks on the operator).
    """

    def __init__(self, reporters) -> None:
        self._rs = [r for r in reporters if r is not None]

    def _fan(self, method: str, *args) -> None:
        for r in self._rs:
            try:
                getattr(r, method)(*args)
            except Exception:  # one reporter must not break the others
                pass

    def phase(self, name: str, detail: str = "") -> None:
        self._fan("phase", name, detail)

    def info(self, message: str) -> None:
        self._fan("info", message)

    def stream_start(self, label: str, model: str) -> None:
        self._fan("stream_start", label, model)

    def stream_delta(self, text: str) -> None:
        self._fan("stream_delta", text)

    def stream_end(self) -> None:
        self._fan("stream_end")

    def gate_result(self, gate: dict, approved: bool,
                    register_cmd: str | None) -> None:
        self._fan("gate_result", gate, approved, register_cmd)

    def request_gate(self, gate: dict) -> bool:
        approved = False
        for r in self._rs:
            try:
                if r.request_gate(gate):
                    approved = True
            except Exception:
                pass
        return approved
