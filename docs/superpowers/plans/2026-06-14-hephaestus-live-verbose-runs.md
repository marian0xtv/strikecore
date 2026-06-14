# Hephaestus Live-Verbose Interactive Runs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `hephaestus run` stream every phase live (with token-by-token LLM output) and let the operator approve H1/H3 gates interactively mid-run, in both the console and the CLI.

**Architecture:** Inject a `RunReporter` into the agent (keeps the agent surface-agnostic). Make the router's `stream_chat` routing- and cost-aware so streamed calls keep the run record correct. The agent emits phase/stream events and asks the reporter to approve each gate; approving completes the run and prints the `sc-registry register` command, deferring records it pending (today's behavior). Non-TTY auto-defers.

**Tech Stack:** Python 3.13, asyncio async generators, stdlib-only reporter, pytest.

**Anchors verified from the codebase:**
- `core/provider_router.py`: `chat()` resolves model via `self.policy.resolve(task_type)` then applies `_UNAVAILABLE_MODEL_SUBSTITUTIONS` (Fable→Opus); records cost via `_record_call`/`estimate_cost_micros`; `_dry_run_response` estimates tokens (`len(text)//4`, out=200). `stream_chat` (lines ~503) currently ignores task_type/model, records no cost — **no external callers** (safe to change its signature). `set_dry_run`, `reset_log`, `run_cost` exist.
- `hephaestus/agent.py:run(focus_category, depth, dry_run, profile, lethality)` — 6 phases; uses `await self.router.chat(...)`; gates appended to `pending`; `status = "paused" if pending else "completed"`.
- `hephaestus/cli_core.py:run_pass(*, focus, depth, dry_run, profile, lethality)`.
- `bin/hephaestus.py:cmd_run` and `cli/shell.py:_cmd_hephaestus` "run" branch call `cli_core.run_pass`.
- House style: **ASCII only, no emojis** in formatted output (per §12 / prior review).

Run tests with: `cd /root/strikecore && .venv/bin/python -m pytest tests/ -q` (use `.venv`; it has anthropic/pydantic/flask). Plain `python3` works too for non-Flask tests.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `hephaestus/reporting.py` | `RunReporter` base + `NullReporter` (silent default) + `StreamReporter` (live, TTY-gated gates) | **Create** |
| `core/provider_router.py` | `stream_chat` made routing/cost-aware + `resolve_model()` helper | **Modify** |
| `providers/anthropic_provider.py` | `stream_chat` accepts optional `model` | **Modify** |
| `hephaestus/agent.py` | `run(..., reporter=NullReporter())`: emit events, stream LLM calls, live gates | **Modify** |
| `hephaestus/cli_core.py` | `run_pass(..., reporter=None)` | **Modify** |
| `bin/hephaestus.py` | `cmd_run` passes a `StreamReporter` | **Modify** |
| `cli/shell.py` | `_cmd_hephaestus` "run" passes a `StreamReporter` | **Modify** |
| `CLAUDE.md`, `docs/HEPHAESTUS.md`, `docs/HEPHAESTUS_CHANGES.md` | document live-verbose runs | **Modify** |
| `tests/test_hephaestus_reporting.py` | reporter unit tests | **Create** |
| `tests/test_router_stream.py` | routed/cost-aware streaming test | **Create** |
| `tests/test_hephaestus_agent_run.py` | agent run events + approve/defer paths | **Create** |

---

## Task 1: Reporter seam — `hephaestus/reporting.py`

**Files:** Create `hephaestus/reporting.py`; Test `tests/test_hephaestus_reporting.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hephaestus_reporting.py
import io
from hephaestus.reporting import RunReporter, NullReporter, StreamReporter


class _FakeIn:
    def __init__(self, line="", tty=True):
        self._line, self._tty = line, tty
    def isatty(self): return self._tty
    def readline(self): return self._line


def test_null_reporter_defers_gates():
    r = NullReporter()
    assert r.request_gate({"gate": "H1", "reason": "x"}) is False
    # no-op methods don't raise
    r.phase("discovery"); r.info("x"); r.stream_start("l", "m")
    r.stream_delta("t"); r.stream_end(); r.gate_result({"gate": "H1"}, False, None)


def test_stream_reporter_writes_phases_and_streams():
    out = io.StringIO()
    r = StreamReporter(out=out, in_=_FakeIn())
    r.phase("discovery", "voip")
    r.stream_start("research: x", "claude-opus-4-8")
    r.stream_delta("hello")
    r.stream_end()
    text = out.getvalue()
    assert "DISCOVERY" in text and "voip" in text
    assert "claude-opus-4-8" in text and "hello" in text


def test_stream_reporter_approves_on_tty_yes():
    r = StreamReporter(out=io.StringIO(), in_=_FakeIn(line="y\n", tty=True))
    assert r.request_gate({"gate": "H1", "reason": "x"}) is True


def test_stream_reporter_defers_on_tty_no():
    r = StreamReporter(out=io.StringIO(), in_=_FakeIn(line="n\n", tty=True))
    assert r.request_gate({"gate": "H1", "reason": "x"}) is False


def test_stream_reporter_defers_when_not_tty():
    out = io.StringIO()
    r = StreamReporter(out=out, in_=_FakeIn(line="y\n", tty=False))
    assert r.request_gate({"gate": "H3", "reason": "x"}) is False
    assert "non-interactive" in out.getvalue().lower()


def test_gate_result_prints_register_cmd_on_approve():
    out = io.StringIO()
    r = StreamReporter(out=out, in_=_FakeIn())
    r.gate_result({"gate": "H3"}, True, "python3 bin/sc-registry.py register tools/foo")
    assert "sc-registry.py register tools/foo" in out.getvalue()
```

- [ ] **Step 2: Run, verify FAIL**

`cd /root/strikecore && .venv/bin/python -m pytest tests/test_hephaestus_reporting.py -q`
Expected: `ModuleNotFoundError: No module named 'hephaestus.reporting'`

- [ ] **Step 3: Create `hephaestus/reporting.py`**

```python
"""Operator-facing run reporters for Hephaestus.

The agent is surface-agnostic: it emits run events to an injected RunReporter
instead of printing. NullReporter (the default) is silent and defers every gate
— preserving programmatic/test behavior. StreamReporter renders live phase
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
```

- [ ] **Step 4: Run, verify PASS**

`cd /root/strikecore && .venv/bin/python -m pytest tests/test_hephaestus_reporting.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd /root/strikecore
git add hephaestus/reporting.py tests/test_hephaestus_reporting.py
git commit -m "feat(hephaestus): RunReporter seam (Null + Stream, TTY-gated gates)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Routing/cost-aware streaming — `core/provider_router.py` + provider

**Files:** Modify `core/provider_router.py`, `providers/anthropic_provider.py`; Test `tests/test_router_stream.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_router_stream.py
import asyncio
from core.provider_router import ProviderRouter
from governance.model_router import ModelPolicy


class FakeSettings:
    def get(self, k, d=None):
        return {"ai.active_provider": "anthropic",
                "ai.fallback_chain": ["anthropic"],
                "ai.anthropic": {}}.get(k, d)


def test_stream_chat_dry_run_records_routed_cost():
    async def main():
        r = ProviderRouter(FakeSettings())
        r.set_dry_run(True)
        r.set_policy(ModelPolicy(profile="hephaestus"))
        r.reset_log()
        chunks = []
        async for delta in r.stream_chat(
            [{"role": "user", "content": "x" * 4000}],
            system="s", task_type="hephaestus:gap"):
            chunks.append(delta)
        assert "".join(chunks)               # produced content
        rec = r.call_log[-1]
        # hephaestus:gap -> fable tier, remapped to opus on this account
        assert rec.model == "claude-opus-4-8", rec.model
        assert rec.cost_micros > 0
        assert rec.task_type == "hephaestus:gap"
    asyncio.run(main())


def test_resolve_model_applies_substitution():
    r = ProviderRouter(FakeSettings())
    r.set_policy(ModelPolicy(profile="hephaestus"))
    assert r.resolve_model("hephaestus:gap") == "claude-opus-4-8"
    assert r.resolve_model("hephaestus:discovery") == "claude-haiku-4-5"
```

- [ ] **Step 2: Run, verify FAIL**

`cd /root/strikecore && .venv/bin/python -m pytest tests/test_router_stream.py -q`
Expected: FAIL — `AttributeError: 'ProviderRouter' object has no attribute 'resolve_model'` and/or stream_chat doesn't record cost / wrong model.

- [ ] **Step 3: Add `resolve_model()` and rewrite `stream_chat` in `core/provider_router.py`**

First add a public resolver (place it right after the `set_policy` method, near line ~192):

```python
    def resolve_model(self, task_type: str | None = None,
                      model: str | None = None) -> str:
        """The concrete model id this router would call for a task_type/model,
        after applying account-availability substitutions (e.g. Fable->Opus)."""
        if model:
            chosen = resolve_model_name(model)
        else:
            chosen, _ = self.policy.resolve(task_type)
        return _UNAVAILABLE_MODEL_SUBSTITUTIONS.get(chosen, chosen)
```

Then REPLACE the entire existing `stream_chat` method (the one with the
`Streaming does **not** use the fallback chain ...` docstring) with:

```python
    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        *,
        task_type: str | None = None,
        model: str | None = None,
        dry_run: bool | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream a routed, cost-recorded chat completion.

        Resolves the model from the cost-aware policy (applying availability
        substitutions), yields text deltas, and records an estimated CallRecord
        when the stream completes so run_cost()/model_usage stay populated.
        Falls back to non-streaming chat() (which records exact cost) if the
        provider cannot stream or fails before any token is emitted.
        """
        # 1) resolve model + reason (mirror chat()), apply substitution
        if model:
            chosen, reason = resolve_model_name(model), f"explicit:{resolve_model_name(model)}"
        else:
            chosen, reason = self.policy.resolve(task_type)
        substitute = _UNAVAILABLE_MODEL_SUBSTITUTIONS.get(chosen)
        if substitute:
            reason = f"{reason} (unavailable:{chosen}->{substitute})"
            chosen = substitute

        # 2) dry-run short-circuit: synthetic content, recorded estimated cost
        use_dry = self._dry_run if dry_run is None else dry_run
        if use_dry:
            resp = self._dry_run_response(messages, system, chosen, reason, task_type)
            yield resp.content
            return

        chain = self._ordered_chain()
        last_error: Exception | None = None

        for name in chain:
            provider = self._providers.get(name)
            if provider is None:
                continue
            if not hasattr(provider, "stream_chat"):
                # provider can't stream -> routed non-streaming fallback
                resp = await self.chat(messages, tools, system,
                                       task_type=task_type, model=chosen, dry_run=False)
                yield resp.content
                return

            stats = self._stats.setdefault(name, ProviderStats())
            start = time.monotonic()
            effective_tools = tools if provider.supports_tools() else None
            accumulated: list[str] = []
            try:
                try:
                    agen = provider.stream_chat(messages, effective_tools, system, model=chosen)
                except TypeError:
                    # provider not yet updated for the per-call model knob
                    agen = provider.stream_chat(messages, effective_tools, system)
                async for chunk in agen:
                    accumulated.append(chunk)
                    yield chunk

                latency = time.monotonic() - start
                stats.total_requests += 1
                stats.total_latency += latency
                stats.last_request_at = time.time()
                self._record_stream_call(messages, system, "".join(accumulated),
                                         chosen, reason, task_type, latency, name)
                return  # success

            except Exception as exc:
                stats.total_errors += 1
                stats.last_error = str(exc)
                last_error = exc
                if not accumulated:
                    # nothing emitted yet -> safe to fall back to chat()
                    resp = await self.chat(messages, tools, system,
                                           task_type=task_type, model=chosen, dry_run=False)
                    yield resp.content
                    return
                raise  # partial output already emitted; cannot safely retry

        raise ConnectionError(
            f"All providers failed for streaming. Last error: {last_error}"
        )

    def _record_stream_call(self, messages: list[dict[str, Any]], system: str | None,
                            output_text: str, model: str, reason: str,
                            task_type: str | None, latency: float,
                            provider_name: str) -> None:
        """Record an estimated CallRecord for a completed streamed call."""
        text = (system or "")
        for m in messages or []:
            c = m.get("content", "")
            text += c if isinstance(c, str) else str(c)
        in_tokens = max(1, len(text) // 4)
        out_tokens = max(1, len(output_text) // 4)
        try:
            cost = estimate_cost_micros(model, in_tokens, out_tokens)
        except Exception:  # noqa: BLE001
            cost = 0
        self.call_log.append(CallRecord(
            task_type=task_type or "", model=model, routing_reason=reason,
            input_tokens=in_tokens, output_tokens=out_tokens,
            cost_micros=cost, dry_run=False,
        ))
        try:
            log_llm_call(
                provider=provider_name, model=model,
                input_tokens=in_tokens, output_tokens=out_tokens,
                cached_tokens=0, cache_write_tokens=0,
                latency_ms=int(latency * 1000), task_type=task_type,
            )
        except Exception:  # noqa: BLE001
            pass
```

- [ ] **Step 4: Add the `model` param to the provider's `stream_chat` in `providers/anthropic_provider.py`**

Change the signature (line ~225) and pass model into `_build_request`:

```python
    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Yield partial content deltas as they arrive."""
        kwargs, extra_headers = self._build_request(messages, tools, system)
        if model:
            kwargs["model"] = model
```

(Insert the `if model: kwargs["model"] = model` line immediately after the
existing `kwargs, extra_headers = self._build_request(...)` line, before the
`backoff = ...` line. Leave the rest of the method unchanged.) Verify
`_build_request` returns a dict whose `"model"` key the API call uses; if it
already sets `kwargs["model"]`, the override after it wins.

- [ ] **Step 5: Run, verify PASS**

`cd /root/strikecore && .venv/bin/python -m pytest tests/test_router_stream.py -q`
Expected: 2 passed

- [ ] **Step 6: Confirm no regression to chat() path**

`cd /root/strikecore && .venv/bin/python tests/test_router_chat.py`
Expected: `ALL ROUTER CHAT (dry-run) TESTS PASSED`

- [ ] **Step 7: Commit**

```bash
cd /root/strikecore
git add core/provider_router.py providers/anthropic_provider.py tests/test_router_stream.py
git commit -m "feat(router): routing- & cost-aware stream_chat (+ resolve_model, provider model knob)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Agent emits events + streams + live gates — `hephaestus/agent.py`

**Files:** Modify `hephaestus/agent.py`; Test `tests/test_hephaestus_agent_run.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hephaestus_agent_run.py
import asyncio
from hephaestus.agent import Hephaestus
from hephaestus.reporting import RunReporter
from core.provider_router import ProviderRouter
from governance.model_router import ModelPolicy


class FakeSettings:
    def get(self, k, d=None):
        return {"ai.active_provider": "anthropic",
                "ai.fallback_chain": ["anthropic"],
                "ai.anthropic": {}}.get(k, d)


class RecordingReporter(RunReporter):
    def __init__(self, approve=False):
        self.phases, self.gates, self.deltas = [], [], []
        self._approve = approve
    def phase(self, name, detail=""): self.phases.append(name)
    def stream_delta(self, text): self.deltas.append(text)
    def request_gate(self, gate): self.gates.append(gate["gate"]); return self._approve


def _run(reporter, approve=False):
    r = ProviderRouter(FakeSettings())
    r.set_dry_run(True)
    agent = Hephaestus(r)
    return asyncio.run(agent.run(focus_category="voip", depth=1, dry_run=True,
                                 reporter=reporter))


def test_run_emits_phases_and_streams():
    rep = RecordingReporter()
    rec = _run(rep)
    for p in ("discovery", "research", "gap", "decision", "gates"):
        assert p in rep.phases, (p, rep.phases)
    assert rep.deltas, "expected streamed deltas"


def test_default_reporter_defers_gates():
    # No reporter -> NullReporter -> all gates deferred -> paused with pending.
    r = ProviderRouter(FakeSettings()); r.set_dry_run(True)
    rec = asyncio.run(Hephaestus(r).run(focus_category="voip", dry_run=True))
    assert rec["status"] == "paused"
    assert len(rec["pending_approvals"]) == 2
    assert not [a for a in rec["git_actions"] if a["action"].startswith("gate_approved")]


def test_live_approval_completes_run_and_records_git_actions():
    rep = RecordingReporter(approve=True)
    rec = _run(rep, approve=True)
    assert rep.gates == ["H1", "H3"]
    assert rec["status"] == "completed"
    assert rec["pending_approvals"] == []
    approved = [a for a in rec["git_actions"] if a["action"].startswith("gate_approved")]
    assert {a["action"] for a in approved} == {"gate_approved:H1", "gate_approved:H3"}
```

- [ ] **Step 2: Run, verify FAIL**

`cd /root/strikecore && .venv/bin/python -m pytest tests/test_hephaestus_agent_run.py -q`
Expected: FAIL — `run()` has no `reporter` kwarg / phases not emitted.

- [ ] **Step 3: Modify `hephaestus/agent.py`**

(a) Add imports at the top (after the existing `import uuid` / before `from pathlib`):
```python
import re
```
and extend the hephaestus import:
```python
from hephaestus import discovery, run_record
from hephaestus.reporting import NullReporter, RunReporter
```

(b) Change the `run` signature to accept a reporter:
```python
    async def run(
        self,
        focus_category: str,
        depth: int = 1,
        dry_run: bool = False,
        profile: str = "hephaestus",
        lethality: str = "balanced",
        reporter: RunReporter | None = None,
    ) -> dict:
```
and at the top of the body (after `started = _now()`):
```python
        rep = reporter or NullReporter()
```

(c) Add a small streaming helper as a method on `Hephaestus` (place it above `run`):
```python
    async def _stream(self, rep, *, label: str, content: str,
                      task_type: str, dry_run: bool) -> str:
        """Stream one routed LLM call through the reporter; return full text."""
        model = self.router.resolve_model(task_type=task_type)
        rep.stream_start(label, model)
        chunks: list[str] = []
        async for delta in self.router.stream_chat(
            [{"role": "user", "content": content}],
            system=_HEPH_SYSTEM, task_type=task_type, dry_run=dry_run):
            chunks.append(delta)
            rep.stream_delta(delta)
        rep.stream_end()
        return "".join(chunks)
```

(d) Replace phase 1 (discovery) to announce + list:
```python
        # 1) Discovery (HTTP / offline fixture) — no LLM.
        rep.phase("discovery", focus_category)
        candidates = discovery.discover(focus_category, limit=max(3, depth * 2),
                                        dry_run=dry_run)
        for c in candidates:
            rep.info(f"{c['name']} — {c['url']} "
                     f"[{c.get('reliability','?')}{c.get('confidence','?')}]")
```

(e) Replace phase 2 (research) to stream:
```python
        # 2) Deep research — one routed streaming call per top candidate.
        rep.phase("research")
        research: list[dict] = []
        for c in candidates[: depth + 1]:
            text = await self._stream(
                rep, label=f"research: {c['name']}", task_type="hephaestus:research",
                dry_run=dry_run,
                content=(f"Summarize OSINT tool {c['name']} ({c['url']}). "
                         f"List capabilities (facts) then a recommendation."))
            claim = "capabilities reviewed" if dry_run else _first_line(text)
            research.append({"claim": f"{c['name']}: {claim}",
                             "source": c["url"], "kind": "fact"})
```

(f) Replace phase 3 (gap) to stream:
```python
        # 3) Gap analysis — Fable tier (remapped to Opus on this account).
        rep.phase("gap")
        covered = self._covered_capabilities()
        gaps = [g for g in _KNOWN_GAPS if g not in covered]
        await self._stream(
            rep, label="gap analysis", task_type="hephaestus:gap", dry_run=dry_run,
            content=(f"Given covered={covered} and gaps={gaps}, assess where "
                     f"'{focus_category}' ranks and what to build."))
        gap_analysis = {"covered": covered, "gaps": gaps, "target_gap": focus_category}
```

(g) Replace phase 4 (decision) to stream:
```python
        # 4) Decision — Fable tier (novel design).
        rep.phase("decision")
        decisions: list[dict] = []
        if candidates:
            top = candidates[0]
            await self._stream(
                rep, label=f"decide: {top['name']}", task_type="hephaestus:design",
                dry_run=dry_run,
                content=(f"Decide integrate/fork/write for {top['name']} to "
                         f"close the '{focus_category}' gap, per the contract."))
            decisions.append({
                "candidate": top["name"], "action": "integrate",
                "rationale": f"Best Admiralty score ({top['reliability']}{top['confidence']}) "
                             f"for the {focus_category} gap; wrap per Integration Contract.",
            })
```

(h) Replace phase 5 (gates) with the live-approval loop:
```python
        # 5) H1/H3 gates — ask the operator live; defer when non-interactive.
        rep.phase("gates")
        pending: list[dict] = []
        git_actions: list[dict] = []
        if decisions:
            cand = decisions[0]["candidate"]
            slug = re.sub(r"[^a-z0-9_-]+", "-", cand.lower()).strip("-") or "tool"
            gate_specs = [
                ("H1", f"{cand} is untrusted upstream code — needs the manual "
                       f"sandbox gate before any real-target run."),
                ("H3", f"{cand} ships gate_approved=false — will not be registered "
                       f"until the operator approves."),
            ]
            for gate, why in gate_specs:
                g = {"gate": gate, "candidate": cand, "reason": why}
                if rep.request_gate(g):
                    git_actions.append({
                        "action": f"gate_approved:{gate}",
                        "detail": f"operator approved {gate} live for {cand}"})
                    register_cmd = (f"python3 bin/sc-registry.py register tools/{slug}"
                                    f"  # build per the Integration Contract first")
                    rep.gate_result(g, True, register_cmd)
                else:
                    pending.append(g)
                    rep.gate_result(g, False, None)
        status = "paused" if pending else "completed"
```

Leave phase 6 (assemble/validate/save) unchanged — it already reads `pending`,
`git_actions`, `status`, and `self.router.run_cost()`.

- [ ] **Step 4: Run, verify PASS**

`cd /root/strikecore && .venv/bin/python -m pytest tests/test_hephaestus_agent_run.py -q`
Expected: 3 passed

- [ ] **Step 5: Confirm the cli_core tests still pass (agent.run signature is back-compatible)**

`cd /root/strikecore && .venv/bin/python -m pytest tests/test_hephaestus_cli_core.py -q`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
cd /root/strikecore
git add hephaestus/agent.py tests/test_hephaestus_agent_run.py
git commit -m "feat(hephaestus): agent streams phases + live H1/H3 gate approval

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Wire StreamReporter into cli_core, CLI, and console

**Files:** Modify `hephaestus/cli_core.py`, `bin/hephaestus.py`, `cli/shell.py`

- [ ] **Step 1: `hephaestus/cli_core.py` — thread the reporter through `run_pass`**

Change `run_pass` (keyword-only signature) to:
```python
def run_pass(*, focus: str, depth: int, dry_run: bool,
             profile: str, lethality: str, reporter=None) -> dict[str, Any]:
    """Execute one R&D pass and return the run record. Raises on agent error."""
    from hephaestus.reporting import NullReporter
    router = build_router(dry_run)
    agent = Hephaestus(router)
    rec = asyncio.run(agent.run(
        focus_category=focus, depth=depth, dry_run=dry_run,
        profile=profile, lethality=lethality,
        reporter=reporter or NullReporter()))
    audit("run", rec["run_id"], {"status": rec["status"],
                                 "cost_micros": rec["totals"]["cost_usd_micros"]})
    return rec
```

- [ ] **Step 2: `bin/hephaestus.py` — pass a StreamReporter (always verbose)**

In `cmd_run`, change the `cli_core.run_pass(...)` call to pass a reporter:
```python
def cmd_run(args) -> int:
    from hephaestus.reporting import StreamReporter
    try:
        rec = cli_core.run_pass(focus=args.focus, depth=args.depth,
                                dry_run=args.dry_run, profile=args.profile,
                                lethality=args.lethality,
                                reporter=StreamReporter())
    except Exception as exc:  # noqa: BLE001
        print(f"hephaestus run failed: {exc}", file=sys.stderr)
        return EXIT_INTERNAL
    for line in cli_core.summary_lines(rec):
        print(line)
    print(f"\nrun record: {cli_core.run_record_path(rec['run_id'])}")
    return EXIT_OK
```

- [ ] **Step 3: `cli/shell.py` — pass a StreamReporter in the `run` branch**

In `_cmd_hephaestus`, inside the `if sub == "run":` branch, change the
`cli_core.run_pass(...)` call to include the reporter:
```python
            from hephaestus.reporting import StreamReporter
            try:
                rec = cli_core.run_pass(focus=focus, depth=depth, dry_run=dry_run,
                                        profile="hephaestus", lethality=lethality,
                                        reporter=StreamReporter())
            except Exception as exc:  # noqa: BLE001
                console.print(f"[{THEME['error']}]hephaestus run failed: {exc}[/{THEME['error']}]")
                return
```
(Keep the surrounding lines — the pre-run "Hephaestus: focus=..." line and the
post-run `summary_lines` loop — unchanged.)

- [ ] **Step 4: Verify wiring end-to-end (dry-run shows live phases)**

```bash
cd /root/strikecore && .venv/bin/python bin/hephaestus.py run --focus voip --dry-run
```
Expected: live `=== DISCOVERY ===`, candidate lines, `>> research: ...` stream
blocks, `=== GATES ===` with a `GATE H1 ... (non-interactive: deferred)` line
(stdin is not a TTY under this capture), then the summary + `run record:` path.
Exit 0, no traceback.

- [ ] **Step 5: Confirm the console-command tests still pass**

`cd /root/strikecore && .venv/bin/python -m pytest tests/test_hephaestus_console.py -q`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
cd /root/strikecore
git add hephaestus/cli_core.py bin/hephaestus.py cli/shell.py
git commit -m "feat(hephaestus): always-verbose runs via StreamReporter (CLI + console)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Documentation

**Files:** Modify `CLAUDE.md`, `docs/HEPHAESTUS.md`, `docs/HEPHAESTUS_CHANGES.md`

- [ ] **Step 1: CLAUDE.md §14 — note live-verbose runs**

In `CLAUDE.md` §14, in the "Hephaestus is a mandatory native console command"
subsection, after the bullet list of sub-commands, add:
```markdown

`hephaestus run` is **always verbose**: every phase (discovery → research → gap
→ decision → gates) streams live, including token-by-token LLM output, and H1/H3
gates are approved **interactively during the run** (TTY only; non-interactive
sessions auto-defer to `pending`, cleared later via `hephaestus approve`).
Approving live completes the run and prints the exact `sc-registry register`
command to use once the tool is built (no auto-registration of unbuilt tools).
Streamed-call cost is *estimated* (not exact provider usage).
```

- [ ] **Step 2: docs/HEPHAESTUS.md — extend the Invocation section**

After the existing `## Invocation` block, add:
```markdown
Runs stream live by default — phases, token output, and interactive H1/H3 gate
prompts. In a non-interactive shell (cron/pipe) gates auto-defer to `pending`.
```

- [ ] **Step 3: docs/HEPHAESTUS_CHANGES.md — append an entry**

Append:
```markdown
## 2026-06-14 — Live-verbose interactive runs

- `hephaestus run` now streams every phase live (token-by-token LLM output) via
  a new `RunReporter` seam (`hephaestus/reporting.py`: Null + Stream).
- H1/H3 gates are approved interactively mid-run (TTY-gated; non-interactive
  auto-defers to pending). Approving prints the `sc-registry register` command.
- `core/provider_router.py:stream_chat` is now routing- & cost-aware (resolves
  the policy model + Fable→Opus remap, records an estimated CallRecord);
  `providers/anthropic_provider.py:stream_chat` gained a `model` knob.
```

- [ ] **Step 4: Commit**

```bash
cd /root/strikecore
git add CLAUDE.md docs/HEPHAESTUS.md docs/HEPHAESTUS_CHANGES.md
git commit -m "docs(hephaestus): document live-verbose interactive runs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Full verification (no push)

- [ ] **Step 1: Run the whole suite under .venv**

`cd /root/strikecore && .venv/bin/python -m pytest tests/ -q`
Expected: all PASS (existing 15 + reporting 6 + router_stream 2 + agent_run 3 = 26), 0 failed.

- [ ] **Step 2: Run under bare system python3 (graceful skips)**

`cd /root/strikecore && python3 -m pytest tests/ -q`
Expected: dashboard test skipped (no flask); the rest pass. No new failures vs baseline.

- [ ] **Step 3: Live interactive smoke (manual, optional)**

In a real terminal: `python3 bin/hephaestus.py run --focus voip --dry-run`, and at
the `Approve now? [y/N]` prompt type `y` for H1 and `n` for H3 — confirm H1 prints
the register command + APPROVED, H3 defers to pending, and the final record shows
status `paused` with one pending gate. (Do NOT push — atlas push happens later.)

---

## Self-Review (completed during planning)

- **Spec coverage:** §4.1 reporter → Task 1; §4.3 routed/cost streaming + §4.4 provider knob → Task 2; §4.2 agent events/streaming/live gates → Task 3; §4.5 wiring (always verbose) → Task 4; §1–§2 docs → Task 5; §7 testing → Tasks 1/2/3 + Task 6. Non-TTY auto-defer (§2/§6) covered by Task 1 tests + Task 3 default-reporter test. Estimated cost (§2) covered by Task 2 test. All covered.
- **Placeholder scan:** none — every code/command block is concrete.
- **Type/name consistency:** `RunReporter` methods (`phase/info/stream_start/stream_delta/stream_end/request_gate/gate_result`) are defined in Task 1 and used identically in Tasks 1/3. `resolve_model` defined in Task 2, used in Task 3's `_stream`. `stream_chat(..., task_type=, model=, dry_run=)` signature defined in Task 2, called that way in Task 3. `run_pass(..., reporter=None)` defined in Task 4 Step 1, called with `reporter=StreamReporter()` in Task 4 Steps 2–3. Gate dict shape `{"gate","candidate","reason"}` consistent across agent + reporter.
- **Back-compat:** NullReporter default + unchanged `chat()` + unchanged run-record schema → existing tests stay green (verified as explicit steps in Tasks 3 & 4).
```
