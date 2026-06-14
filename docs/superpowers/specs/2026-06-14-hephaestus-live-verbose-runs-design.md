# Design — Live-verbose, interactive Hephaestus runs

**Date:** 2026-06-14
**Status:** Approved (design); pending implementation plan
**Author:** atlas / StrikeCore

## 1. Problem

A Hephaestus run today executes its six phases **silently** and returns only a
summary at the end (`hephaestus/agent.py:run()`). H1/H3 sandbox gates are
recorded as `pending_approvals` and the run returns `status="paused"`; the
operator approves them **afterward** via the `hephaestus approve` command. There
is no live feedback and no in-run interaction.

The operator wants:

1. **Full live verbosity** — every phase (discovery → research → gap → decision
   → gates → done) visible as it happens, "prompt style," including **live token
   streaming** of the LLM output.
2. **Live approval** — approve H1/H3 gates **during** the run, while the verbose
   output flows, instead of deferring to a post-hoc command.
3. **Always on**, in both the console and the `bin/hephaestus.py` CLI.

## 2. Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Verbosity depth | Phases + per-call model/cost + **live token streaming** of LLM output |
| Live approval action | Mark gate approved, run completes, **print the exact `sc-registry register …` command** — no auto-registration of unbuilt tools |
| Default vs flag | **Always verbose everywhere** (console + CLI) |
| Streamed-call cost | **Estimated** tokens (same estimator the dry-run path uses); documented caveat |
| Non-TTY gate | **Auto-defer to pending** (run = paused); stream output still flows |

## 3. Goals / Non-goals

**Goals**
- A reporter seam that lets the agent emit live phase + token-stream events
  without coupling it to a console.
- Routing- and cost-aware streaming so the run record stays correct.
- Live, TTY-gated gate approval with safe non-interactive fallback.

**Non-goals**
- No auto-registration / scaffolding of tools on approval (operator builds the
  tool, then runs the printed `sc-registry register` command).
- No exact streamed-token usage capture (estimation only this pass).
- No change to the GR5 gate, the run-record schema shape, or the `approve`
  command (it still clears any deferred gates).

## 4. Architecture

### 4.1 Reporter seam — `hephaestus/reporting.py` (new)

The agent is surface-agnostic and has no Claude-Code/Rich runtime dependency
(§14). Keep it that way by **injecting a reporter** rather than wiring output
into the agent. Stdlib-only module:

```python
class RunReporter:
    """No-op base. Subclasses render run events to an operator surface."""
    def phase(self, name: str, detail: str = "") -> None: ...
    def info(self, message: str) -> None: ...
    def stream_start(self, label: str, model: str) -> None: ...
    def stream_delta(self, text: str) -> None: ...
    def stream_end(self) -> None: ...
    def request_gate(self, gate: dict) -> bool:  # True = approve now, False = defer
        return False
    def gate_result(self, gate: dict, approved: bool, register_cmd: str | None) -> None: ...

class NullReporter(RunReporter):
    """Silent; defers all gates. The default — preserves programmatic/test behavior."""

class StreamReporter(RunReporter):
    """Live phases + token streaming to a text stream (default sys.stdout).
    request_gate() prompts 'Approve <gate>? [y/N]' ONLY when the input stream
    is a TTY; otherwise returns False (defer)."""
    def __init__(self, out=sys.stdout, in_=sys.stdin): ...
```

- `StreamReporter.request_gate` reads `self._in.isatty()`; non-TTY → defer.
  Interactive → read a line, approve on `y`/`yes` (case-insensitive).
- `stream_delta` writes without a trailing newline and flushes, so tokens appear
  as they arrive.

### 4.2 Agent — `hephaestus/agent.py`

`run(...)` gains `reporter: RunReporter = NullReporter()`. Behavior per phase:

- **discovery:** `reporter.phase("discovery", focus)`, then `reporter.info` per
  candidate (`name — url — Admiralty score`).
- **research / gap / decision:** for each LLM call, wrap with
  `stream_start(label, model)` / stream the deltas / `stream_end()`. The model
  label is `self.router.policy.resolve(task_type)[0]` mapped through the same
  substitution the router applies, shown for transparency.
- **gates:** `reporter.phase("gates", …)`. For each candidate gate (H1, H3):
  `approved = reporter.request_gate(gate)`.
  - **approved:** append `git_actions += {"action": "gate_approved:<gate>",
    "detail": "operator approved <gate> live for <candidate>"}`; do NOT add to
    pending; call `reporter.gate_result(gate, True, register_cmd)` where
    `register_cmd = f"python3 bin/sc-registry.py register tools/{slug} "
    f"# build per the Integration Contract first"`.
  - **deferred:** append to `pending` (today's behavior);
    `reporter.gate_result(gate, False, None)`.
- **status:** `completed` if `pending` empty, else `paused`. (Unchanged logic,
  now driven by live decisions.)

The LLM calls switch from `await self.router.chat(...)` to consuming the routed
streaming generator (4.3), accumulating the full text for the existing
`research[].claim` extraction (`_first_line`).

### 4.3 Routing- & cost-aware streaming — `core/provider_router.py`

`stream_chat` today ignores `task_type`/`model`, records no cost, and skips the
Fable→Opus substitution. Replace its body so it mirrors `chat()`'s resolution:

1. Resolve `chosen, reason` from `model` or `self.policy.resolve(task_type)`,
   then apply `_UNAVAILABLE_MODEL_SUBSTITUTIONS` (the Fable→Opus remap).
2. **Dry-run:** yield the synthetic dry-run content (one chunk) and record the
   same estimated `CallRecord` the dry-run `chat()` path records.
3. **Real:** call `provider.stream_chat(messages, tools, system, model=chosen)`,
   accumulate text, yield each delta. After the stream completes, record a
   `CallRecord` with **estimated** tokens (input estimated from messages+system,
   output from the accumulated text) via the existing `estimate_cost_micros`,
   so `run_cost()` / `model_usage` stay populated.
4. **Fallback:** if the provider has no `stream_chat` or it raises before the
   first chunk, fall back to `chat(...)` (routed + cost-recorded) and yield its
   full content as a single chunk.

Signature gains `task_type: str | None = None`, `model: str | None = None`,
`dry_run: bool | None = None` to match `chat()`.

### 4.4 Provider — `providers/anthropic_provider.py`

`stream_chat` gains an optional `model: str | None = None`, threaded into
`_build_request` so the routed model (not the provider default) is used. Other
providers without a model-aware `stream_chat` trigger the router's `chat()`
fallback.

### 4.5 Wiring

- `hephaestus/cli_core.py`: `run_pass(..., reporter: RunReporter | None = None)`
  → defaults to `NullReporter()`. Passes it to `agent.run`.
- `bin/hephaestus.py` and `cli/shell.py`: construct `StreamReporter(sys.stdout,
  sys.stdin)` and pass it (always verbose). The end-of-run `summary_lines`
  output is unchanged.

## 5. Data flow

```
hephaestus run --focus X   (console or CLI)
  → StreamReporter(stdout, stdin)
  → cli_core.run_pass(..., reporter)
    → agent.run(..., reporter)
        discovery  → reporter.phase/info
        research   → router.stream_chat(task_type=hephaestus:research) → reporter.stream_*  (Opus)
        gap        → router.stream_chat(task_type=hephaestus:gap)       → reporter.stream_*  (fable→opus)
        decision   → router.stream_chat(task_type=hephaestus:design)    → reporter.stream_*  (fable→opus)
        gates      → reporter.request_gate(H1) / request_gate(H3)
                       approve → git_actions + print register cmd
                       defer   → pending_approvals
        assemble   → run_record (cost from streamed CallRecords)
  → summary_lines printed
```

## 6. Error handling

- **Non-TTY** (cron/pipe): `request_gate` returns False → gates defer to pending,
  run = paused, output still streams. Operator clears via `hephaestus approve`.
- **Streaming/provider failure:** router falls back to `chat()` before any token
  is emitted; if a stream dies mid-output, the call surfaces the error to the
  agent's existing try path and the run still assembles (status may be `error`).
- **Reporter exceptions** must never abort a run: `StreamReporter` methods are
  defensive (best-effort writes); a write error degrades to silent, not a crash.
- **Operator EOF / Ctrl-D at the prompt:** treated as "defer" (False).

## 7. Testing

- `tests/test_hephaestus_reporting.py`: `NullReporter.request_gate` → False;
  `StreamReporter` with a fake non-TTY input defers; with a fake TTY input
  returning "y" approves; `stream_delta` writes without newline + flushes;
  captured output contains phase banners.
- `tests/test_hephaestus_agent_run.py`: run the agent (dry-run) with a recording
  fake reporter — assert phase events fire in order; **approve path** (reporter
  approves) → `git_actions` has `gate_approved:H1/H3`, `pending_approvals` empty,
  status `completed`; **defer path** (NullReporter) → pending populated, status
  `paused`.
- `tests/test_router_stream.py`: `stream_chat(task_type="hephaestus:gap",
  dry_run=True)` yields content, records a `CallRecord` with the substituted
  model (`claude-opus-4-8`) and `cost_micros > 0`.
- Extend `tests/test_router_chat.py` only if needed; existing assertions
  unaffected (chat() path unchanged).

## 8. Backward compatibility

- `NullReporter` default keeps every programmatic caller (and the existing test
  suite) green; `chat()` is unchanged.
- Run-record schema is unchanged (still `pending_approvals`, `git_actions`,
  `model_usage`, `totals`). Live approval simply produces a record with
  `gate_approved:*` git_actions and fewer/zero pending entries.
- The `approve` command and the dashboard `/hephaestus` page keep working for
  any deferred gates.

## 9. Out of scope / future

- Exact streamed-token usage (vs estimate).
- Auto-scaffolding + registration of tools on approval.
- Streaming for the intel-team / dossier surfaces (this spec is Hephaestus-only).
