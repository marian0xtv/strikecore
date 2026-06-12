# Design — Hephaestus as a mandatory native StrikeCore command + legacy-dashboard embed

**Date:** 2026-06-12
**Status:** Approved (design); pending implementation plan
**Author:** atlas / StrikeCore

## 1. Problem

Hephaestus (the native toolsmith agent, §13/§14) is today only reachable via the
standalone script `bin/hephaestus.py`. It is not a first-class StrikeCore console
command, and its dashboard view exists **only** in the new `web/` React dashboard —
not in the legacy `osint_agent/dashboard/app.py` that the console's `dashboard`
command actually launches.

Two requirements:

1. **Hephaestus must be a native, mandatory console command.** "Mandatory" =
   *enforced doctrine* (GR-style), not merely "available": tool integration into
   StrikeCore MUST be Hephaestus-mediated, enforced at a real chokepoint.
2. **The Hephaestus dashboard must be embedded in the (legacy) StrikeCore
   dashboard too**, achieving parity with the web dashboard that already has it.

## 2. Goals / Non-goals

**Goals**
- A native `hephaestus` console command (alias `/hephaestus`) wrapping
  `run / status / report / approve`, sharing logic with `bin/hephaestus.py`.
- A new doctrine rule **GR5 — Hephaestus-mediated integration**, enforced by the
  registry at registration time.
- A read-only Hephaestus page embedded in the legacy Flask dashboard.
- Docs + tests.

**Non-goals**
- No change to the GR3 router, the Integration Contract envelope/manifest *shape*
  (we add enforcement on an existing field, not new required schema fields).
- No rewrite of the web/ React dashboard (it already embeds Hephaestus).
- No retirement of `bin/hephaestus.py` (kept as a thin CLI over shared core).
- The legacy dashboard page is read-only; H1/H3 approvals are still actioned from
  the console/CLI.

## 3. Design

### 3.1 Shared CLI core — `hephaestus/cli_core.py`

Extract the `run / status / report / approve` bodies currently in
`bin/hephaestus.py` into a new module `hephaestus/cli_core.py` exposing plain
functions, e.g.:

```python
def run_pass(*, focus, depth, dry_run, profile, lethality, settings) -> dict   # returns run record
def list_runs() -> list[dict]
def get_report(run_id: str | None) -> str | None
def approve_gate(run_id: str, gate: str) -> dict
```

These return data / strings (no `print`, no `sys.exit`), so both callers can
format for their own surface. All LLM calls continue to flow through
`core/provider_router.py:ProviderRouter.chat()` under the `hephaestus` profile
(GR3). Exit-code / argparse handling stays in `bin/hephaestus.py`; Rich-console
formatting lives in the shell command.

`bin/hephaestus.py` is refactored to call `cli_core` (behavior unchanged for
existing callers / scripts / cron).

### 3.2 Native console command — `cli/shell.py`

Add `_cmd_hephaestus(self, args)` modeled on `_cmd_model_router`:

```
hephaestus                          # show recent runs + pending approvals (status)
hephaestus run --focus <CAT> [--depth N] [--dry-run] [--lethality economy|balanced|max]
hephaestus status                   # past runs, newest-first + cost
hephaestus report [run_id]          # full run report (latest if omitted)
hephaestus approve <run_id> <H1|H3> # clear a pending sandbox gate
```

- Register in the `_commands` dispatch table under both keys `"hephaestus"`
  (primary) and `"/hephaestus"` (alias).
- Add a help-line entry to the `/help` / command list table and to the
  `StrikeCoreCompleter`.
- Pending H1/H3 approvals are surfaced prominently (colored) in `status`, mirroring
  the dashboard.
- Argument parsing is a thin hand-roll (the command already receives a token list);
  unknown sub-command → usage message, like the other shell commands.

### 3.3 GR5 enforcement — registry provenance gate

**Rule (GR5):** A tool may only be **registered** into the StrikeCore index if its
integration is Hephaestus-mediated — i.e. `provenance.added_by` resolves to a
Hephaestus run (value `hephaestus` or a `hephaestus:<run_id>` reference). An
operator may bypass with an explicit, audited override.

**Mechanism** — in `bin/sc-registry.py:cmd_register` (the single chokepoint; the
`post-receive` hook calls this same path):

1. After manifest validation and the existing `gate_approved` check, evaluate the
   provenance origin:
   - **Hephaestus-originated** (`added_by` starts with `hephaestus`) → allowed.
   - **Otherwise** → `REFUSED` with a message pointing to the console
     (`hephaestus run --focus <CAT>`) **unless** `--operator-override "<reason>"`
     is supplied.
2. `--operator-override "<reason>"` allows the registration but writes an audit
   entry `register_override` with the reason, tool name, and `added_by`, into the
   SHA-256-chained audit (`_audit(...)`, already used by this file).
3. **Grandfathering:** the gate applies only to *new* registrations. Tools already
   in the index (e.g. `cf-validate`, `daprofiler`) are unaffected; `index`
   (bulk re-scan) preserves existing entries and only newly-seen tools are gated.
4. `register_refused` audit entry is written on GR5 refusal (reusing the existing
   refusal-audit pattern).

This keeps "mandatory" honest: the *default* path is Hephaestus; the operator
escape hatch is explicit and leaves an evidence trail (consistent with §7
chain-of-custody and the "honest scope" tone of §13).

No new required manifest fields — we enforce on the **existing** `added_by`
provenance field, so existing tooling and the schema are unchanged.

### 3.4 Legacy dashboard embed — `osint_agent/dashboard/app.py`

- New Flask route `/hephaestus` rendering (read-only) from
  `~/.strikecore/hephaestus/runs/*.json`:
  - latest run summary (focus, depth, status, timestamp),
  - discovered tools + decisions + gaps,
  - **pending H1/H3 approvals** highlighted (with the console command to clear
    them),
  - model usage + cost (from the run record's `model_usage[]`).
- New nav entry in `SIDEBAR` under a "Toolsmith" section, with an
  `active_hephaestus` key threaded through `_render(...)` (add to the `status`
  dict and the `_a(...)` map).
- Pure server-rendered HTML via the existing `_render` helper + glassmorphism
  classes already in the template; no new JS framework. Reads JSON directly (no DB),
  matching how `web/backend/app.py:/api/hephaestus/runs` does it.

### 3.5 Docs

- **CLAUDE.md §14:** add the native `hephaestus` console command to the prose;
  add **GR5 — Hephaestus-mediated integration** alongside GR1/GR2/GR3, and note
  the legacy dashboard now embeds the Hephaestus page.
- **CLAUDE.md §10 / §13 "extending the toolset":** registration step now notes the
  GR5 gate and the `--operator-override` escape hatch.
- **docs/HEPHAESTUS.md:** document console invocation as the primary interactive
  path; CLI documented as the scripting path.
- **docs/HEPHAESTUS_CHANGES.md:** append a changelog entry.

## 4. Data flow

```
Operator (console)
  hephaestus run --focus X
    → cli/shell.py:_cmd_hephaestus
      → hephaestus/cli_core.run_pass()
        → hephaestus.agent.Hephaestus.run()  (router: hephaestus profile, GR3)
          → run record JSON in ~/.strikecore/hephaestus/runs/
            → surfaced in: console status, legacy /hephaestus page, web /api/hephaestus/runs

Tool registration (console / CLI / post-receive hook)
  sc-registry register tools/<name>
    → GR5 provenance gate
        added_by ~ hephaestus?  → ACTIVE/PENDING (existing gate_approved logic)
        else + --operator-override "<reason>" → register + audit(register_override)
        else → REFUSED + audit(register_refused)
```

## 5. Error handling

- Missing run record dir / empty → console + dashboard show "no runs yet"
  (no exception), matching the web endpoint's empty-list behavior.
- `approve` with unknown `run_id` or gate → non-zero result surfaced as a console
  warning; no crash.
- `run` LLM/router error → the agent's existing structural fallback applies; the
  console reports the failure and still records the run.
- Registry override without a reason string → usage error (override requires a
  non-empty reason).

## 6. Testing

- `tests/` console dispatch: `hephaestus run --dry-run` produces a run record;
  `status` / `report` / `approve` happy-path + unknown-id path.
- Registry GR5 gate: (a) Hephaestus-originated manifest registers; (b) non-Hephaestus
  manifest is REFUSED; (c) `--operator-override "reason"` registers and writes a
  `register_override` audit entry; (d) existing index entries are not disturbed by
  `index`.
- Dashboard: `/hephaestus` route returns 200 and renders with zero and ≥1 run
  records (Flask test client).
- `hephaestus/cli_core.py` unit coverage for `list_runs` / `get_report`.

## 7. Risks / mitigations

- **Wedging the `post-receive` hook** (it calls `register`): mitigated because
  Hephaestus-originated tools pass GR5 automatically, and gate_approved=false tools
  are already flagged-not-run today. Hook behavior for the normal Hephaestus flow is
  unchanged.
- **Breaking existing scripts** calling `bin/hephaestus.py`: mitigated by keeping the
  CLI and only refactoring its internals to `cli_core`.
- **Logic duplication** between CLI and console: mitigated by `cli_core` as the single
  source of truth.

## 8. Out of scope / future

- Making legacy-dashboard approvals actionable (currently console/CLI only).
- Migrating the console `dashboard` command from the legacy Flask app to the web/
  React dashboard (separate decision; both kept alive per operator choice).
