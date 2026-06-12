# Platform Cost-Aware LLM Router + Native Hephaestus Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline, autonomous per automode).

**Goal:** Make every StrikeCore LLM call flow through one cost-aware router that picks the cheapest model meeting the quality bar (per-mode profiles incl. a dossier "lethality" profile), expose it via `/model`, and build Hephaestus as a native StrikeCore agent (no Claude Code dependency) that consumes the router, emits a schema-validated run record, and surfaces in CLI + dashboard.

**Architecture:** The single chokepoint `ProviderRouter.chat()` gains a `task_type` hint and an in-memory cost ledger; a new `governance/model_router.py` resolves `(task_type, profile, lethality, pins, overrides) → (model_id, reason)` from config-defined profiles; `AnthropicProvider.chat` gains a per-call `model=` override. Callers pass their `task_type`. A `dry_run` mode lets us verify routing+cost without spending credits or needing Postgres. Hephaestus lives in a native `hephaestus/` package + `bin/hephaestus.py` CLI.

**Tech Stack:** Python 3.13 stdlib + existing governance/providers; FastAPI (`web/backend/app.py`); React/Vite/Tailwind (`web/frontend`); config via `config/settings.py`.

---

## Grounding facts (Phase 1 — do not re-derive)

- Chokepoint: `core/provider_router.py:239 chat(messages,tools,system)`. Callers pass only those 3 args today.
- `AnthropicProvider.chat` (`providers/anthropic_provider.py:171`) → `_build_request:244` sets `kwargs["model"]=self._model:257`; `_effective_max_tokens` hardcodes `self._model:156`. `switch_model` is a no-op for Anthropic.
- `ProviderResponse` (`providers/base.py:17`) has `input_tokens,output_tokens,model,provider,raw`. Cache tokens only in `raw["usage"]`.
- Cost engine: `governance/token_ledger.py:estimate_cost_micros(model,in,out,cr,cw)` using `governance/limits.py:_ANTHROPIC_MODELS` (ModelLimits: pricing_input/output_per_mtok). **fable-5 & opus-4-8 absent.**
- `token_ledger.log_llm_call(..., task_type=...)` already has a `task_type` param/column (unused).
- CLI: `cli/shell.py` `_commands` dict (1145), `_COMMAND_HELP` (82), `_ALL_COMMANDS` (60); `settings.set()` then `settings.save()` to persist. `bin/sc-registry.py:313` = the argparse-subparser idiom.
- Dossier: `bin/agent-dossier.py:99` builds router; `agent/dossier_flow.py:build_dossier`; steps carry `task_type` (`specialist:socint|webint|geoint|socialint|audit|analyst`); `intel_team/agents/base.py:139 call_llm` is the specialist LLM surface (has `self.config.model_tier`, `.domain`); `planner.py:141`, `critic.py:106` call router directly.
- Dashboard: `web/backend/app.py` bare `@app.get`; `web/frontend/src/{App.tsx,components/Sidebar.tsx,pages/*,lib/api.ts}`; Tailwind classes `.card/.card-header/.badge*`; react-query `api<T>()`.
- Verified model ids (confirm via claude-api skill before hardcoding): Haiku 4.5 `claude-haiku-4-5` ($1/$5), Opus 4.8 `claude-opus-4-8` ($5/$25), Fable 5 `claude-fable-5` ($10/$50). Fable: thinking always-on, no temperature/top_p/top_k, no prefill.

---

## File Structure

| Path | Responsibility |
|---|---|
| `governance/model_router.py` (new) | `RoutingProfile`, `ModelPolicy`, `resolve()` — the cost-aware decision logic + profiles (default/hephaestus/dossier) + lethality |
| `governance/limits.py` (mod) | add ModelLimits rows: `claude-fable-5`, `claude-opus-4-8`, `claude-haiku-4-5` |
| `core/provider_router.py` (mod) | `chat(...,*,task_type,model,dry_run)`; resolve model via ModelPolicy; in-memory `call_log` + cost; dry-run synthetic response |
| `providers/anthropic_provider.py` (mod) | `chat(...,*,model,task_type)`; `_build_request(model=)`; Fable param-restriction handling |
| `providers/base.py` (mod) | widen `chat` signature; add `cached_read_tokens/cache_write_tokens` to `ProviderResponse` |
| `config/defaults.toml` (mod) | `[ai.model_policy]` mode/profile/lethality/pinned_model/overrides |
| `intel_team/agents/base.py`, `agent/planner.py`, `agent/critic.py`, `core/nlp_engine.py`, `core/agent.py` (mod) | pass `task_type` into `chat` |
| `cli/shell.py` (mod) | `/model` slash command (show/pin/auto/phase/profile/lethality/cost) + help + completion |
| `schema/hephaestus.run_record.schema.json` (new) | run-record contract (routing/model_usage/totals) |
| `hephaestus/{__init__,agent,discovery,run_record}.py` (new) | native R&D agent consuming the router |
| `bin/hephaestus.py` (new) | CLI: run/status/report/approve |
| `web/backend/app.py` (mod) | `/api/hephaestus/runs`, `/api/tokens/by-mode` |
| `web/frontend/src/pages/Hephaestus.tsx` (new) + App.tsx/Sidebar.tsx/lib/api.ts (mod) | dashboard section |
| `docs/HEPHAESTUS_CHANGES.md` (new), `CLAUDE.md` (mod) | docs/doctrine |

---

## Task 1: Model pricing + the routing policy core (testable, no I/O)
- Add `claude-fable-5` (10/50), `claude-opus-4-8` (5/25), `claude-haiku-4-5` (1/5) ModelLimits to `governance/limits.py` (verify via claude-api skill first).
- New `governance/model_router.py`: friendly-name map (`fable/opus/haiku`→ids); `TIER_MODEL={haiku,opus,fable}`; `RoutingProfile(name, step_map: dict[task_type_prefix→tier], default_tier, escalate)`; built-ins `default/hephaestus/dossier`; `DOSSIER` lethality (economy/balanced/max) escalating analysis tiers; `ModelPolicy(mode, pinned_model, profile, lethality, overrides)`; `resolve(task_type)->(model_id, reason)` precedence: pinned > per-phase override > profile/lethality map > base auto rule.
- **Test** `tests/test_model_router.py`: pinned wins; dossier+max routes `specialist:analyst`→fable, `specialist:audit`→opus, `specialist:socint`→haiku; auto routes `tool_call`→haiku, `planner`→opus; unknown→default_tier. `python3 -m pytest tests/test_model_router.py -q` → PASS.
- Commit `feat(router): cost-aware model routing policy + fable/opus pricing`.

## Task 2: Thread model override + telemetry through the provider/router
- `providers/base.py`: `ProviderResponse` += `cached_read_tokens=0,cache_write_tokens=0`; `chat` abstract signature += `*, model=None, task_type=None`.
- `anthropic_provider.py`: `chat(...,*,model=None,task_type=None)`; `_build_request(...,model=None)` uses `model or self._model` and `_effective_max_tokens(model or self._model)`; if model startswith `claude-fable` strip temperature/top_p/top_k & prefill; pass `task_type` to `_gov_log`.
- `core/provider_router.py`: `chat(...,*,task_type=None,model=None,dry_run=False)`; resolve `chosen,reason = self.policy.resolve(task_type)` unless `model` given; if `dry_run` return synthetic `ProviderResponse` with token estimate (len-based) — no network; record every call to `self.call_log:list[CallRecord]` with `{model,task_type,reason,in,out,cost_micros}` via `estimate_cost_micros`; expose `self.policy` (ModelPolicy from settings) + `run_cost()`/`reset_log()`.
- **Test** `tests/test_router_chat.py`: `dry_run=True` chat with `task_type="specialist:analyst"` under dossier/max → `call_log[-1].model=="claude-fable-5"`, cost>0; `task_type="specialist:socint"`→haiku. PASS.
- Commit `feat(router): per-call model override + in-memory cost ledger + dry-run`.

## Task 3: Refactor all call sites to pass task_type (remove implicit single-model)
- `intel_team/agents/base.py:139`: `self.router.chat(..., task_type=self.config.task_type or f"specialist:{self.config.domain.value}")`.
- `agent/planner.py:141` → `task_type="planner"`; `agent/critic.py:106` → `task_type="critic"`; `core/nlp_engine.py:353` → `task_type="orchestration"`; `core/agent.py:199,259` → `task_type="agent_step"`.
- **Verify** grep: every `router.chat(`/`self.router.chat(` call passes `task_type=` (except the provider-level dispatch). `python3 -c "import ast..."` or grep check.
- Commit `refactor(llm): route every call site through the cost-aware router with task_type`.

## Task 4: `/model` slash command + config persistence
- `cli/shell.py`: `_cmd_model_slash(self,args)` (branch show/pin/auto/`<phase> <m>`/profile/lethality/cost), writing `ai.model_policy.*` via `settings.set`+`settings.save`; `cost` reads `self._router.run_cost()` if a router is attached else last-run file. Register `"/model"` in `_commands`; add `_COMMAND_HELP` row + `_ALL_COMMANDS` entry + completer branch.
- **Test** `tests/test_model_cmd.py`: drive `_cmd_model_slash` with a fake shell (stub settings) for `pin fable`, `auto`, `profile dossier`, `lethality max`, asserting `ai.model_policy` keys set + save called. PASS.
- Commit `feat(cli): /model in-session command (pin/auto/profile/lethality/cost), persisted`.

## Task 5: Run-record schema + native Hephaestus agent
- `schema/hephaestus.run_record.schema.json`: `{schema_version, run_id, started_at, finished_at, params{focus_category,depth,dry_run,profile}, candidates[]{name,url,stars,reliability,confidence,signal}, research[]{claim,source,kind}, gap_analysis{covered[],gaps[]}, decisions[]{candidate,action,rationale}, git_actions[], pending_approvals[]{gate,reason}, routing{profile,policy,lethality}, model_usage[]{task_type,model,calls,input_tokens,output_tokens,cost_micros,reason}, totals{calls,input_tokens,output_tokens,cost_usd_micros}}`.
- `hephaestus/discovery.py`: `github_search(topic, dry_run)` — live GitHub REST `search/repositories` via urllib (no auth, public) OR offline fixture when `dry_run`; returns candidates with quality signals + Admiralty scoring helper.
- `hephaestus/run_record.py`: builder + `validate()` (reuse `bin/sc-registry.py`'s schema-subset validator pattern, stdlib).
- `hephaestus/agent.py`: `class Hephaestus` `async run(focus_category, depth, dry_run, router)` → discover→(router reasoning, task_type `hephaestus:research`/`hephaestus:design`)→gap-analyze vs registry index→decide→emit+validate run record to `~/.strikecore/hephaestus/runs/<run_id>.json`; H1/H3 → append `pending_approvals` + write a `PENDING` marker, do NOT exec untrusted code or register un-gated tools.
- **Test** `tests/test_hephaestus_run.py`: `dry_run=True` run produces a record that `validate()`s OK, has `model_usage` rows (haiku for research-bulk, opus/fable for design) and `totals.cost_usd_micros>0`. PASS.
- Commit `feat(agent): native Hephaestus R&D agent + run-record schema`.

## Task 6: Hephaestus CLI `bin/hephaestus.py`
- argparse subparsers (copy `sc-registry.py`): `run --focus --depth --dry-run --profile`; `status`; `report [run_id]`; `approve <run_id> <gate>`. Exit 0/1/2/3.
- **Test**: `python3 bin/hephaestus.py run --dry-run --focus document` exits 0, prints run summary + cost; `status` lists runs; `report` prints latest.
- Commit `feat(cli): bin/hephaestus.py run/status/report/approve`.

## Task 7: Dashboard — backend endpoints + frontend section
- `web/backend/app.py`: `GET /api/hephaestus/runs` (read `~/.strikecore/hephaestus/runs/*.json` newest-first + registry index pending) and `GET /api/tokens/by-mode` (`GROUP BY task_type, model` on token_ledger).
- `web/frontend`: `pages/Hephaestus.tsx` (react-query → both endpoints; cards for candidates+Admiralty, pending-approval badges, decisions table, model-usage+cost chart, per-step model badges, dossier lethality+cost view); `App.tsx` route; `Sidebar.tsx` nav; `lib/api.ts` types.
- **Verify** backend: `python3 -c "import web.backend.app"` imports; hit endpoint logic via a tiny harness (no DB → returns file data / empty). Frontend: `tsc --noEmit` if toolchain present, else pattern-review (note: not build-run locally).
- Commit `feat(dashboard): Hephaestus section + per-mode cost telemetry`.

## Task 8: Hook conformance + docs + dry-run verification + push
- Confirm `post-receive` already installed on atlas (prior phase) and conforms; re-verify `bash -n` + resolved config (no real deploy).
- `docs/HEPHAESTUS_CHANGES.md`: router, refactored call sites, profiles+lethality, `/model`, CLI, dashboard, config keys, intelligence-cycle fit. Update `CLAUDE.md` §13 (router mandatory for all LLM calls; native Hephaestus; contract mandatory; GR1/GR2).
- **Dry-runs:** `bin/hephaestus.py run --dry-run` (show routing+cost) and a dossier dry-run harness routing analysis→fable/opus, bulk→haiku (print the call_log cost breakdown). Capture both as evidence.
- Commit + push all (hook fires; tools/ unchanged → "no tool changes").

---

## Self-review
- Spec coverage: Phase2 router+/model (T1–T4), Phase3 contract (already shipped last turn — confirm), Phase4 Hephaestus (T5), Phase5 CLI (T4,T6), Phase6 dashboard (T7), Phase7 hook (T8), Phase8 docs+dry-runs (T8). GR3 (all calls routed) = T3.
- Honesty notes: Postgres/live-API may be down → router `dry_run` + in-memory ledger make verification real without them; frontend is pattern-matched, not build-run locally (flagged). `.claude/agents/hephaestus.md` from last turn stays as a dev-time helper; the runtime agent is the new native `hephaestus/` package.
- Verify model ids/pricing via the claude-api skill before hardcoding (Task 1).
