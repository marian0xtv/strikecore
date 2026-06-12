# Platform LLM Router + Native Hephaestus — Change Log & Operator Guide

Everything added/modified for (1) the **platform-wide cost-aware LLM router** and
(2) the **native Hephaestus** StrikeCore agent. Dates: 2026-06-12.

> **Reconciliation:** an earlier pass added a *Claude Code* dev-time subagent at
> `.claude/agents/hephaestus.md`. That remains as a dev-time helper. The
> **runtime** Hephaestus described here is a native StrikeCore Python agent
> (`hephaestus/`) with **no Claude Code dependency** — it consumes the router.

---

## 1. The cost-aware LLM router (GR3)

**One shared service.** Every StrikeCore LLM call already funnels through
`core/provider_router.py:ProviderRouter.chat()`. That chokepoint is now
cost-aware: it picks the cheapest model that meets the quality bar for the call's
*task_type*, records cost per call, and supports an offline dry-run.

### Files

| File | Change |
|---|---|
| `governance/model_router.py` *(new)* | `ModelPolicy`, `RoutingProfile`, profiles (default/hephaestus/dossier), dossier **lethality**, `resolve(task_type) -> (model_id, reason)`. Pure stdlib, unit-tested. |
| `governance/limits.py` | Added `ModelLimits` (pricing) for `claude-fable-5` ($10/$50), `claude-opus-4-8` ($5/$25), `claude-haiku-4-5` ($1/$5) — verified via the claude-api skill. |
| `core/provider_router.py` | `chat(..., *, task_type, model, dry_run)`; resolves model via `self.policy`; in-memory `call_log` + `run_cost()`; `_dry_run_response`; `set_policy/set_dry_run/reset_log`. `rich` made optional (headless). |
| `providers/base.py` | `ProviderResponse` += `cached_read_tokens/cache_write_tokens/task_type/routing_reason`; `chat` signature widened with `*, model, task_type`. |
| `providers/anthropic_provider.py` | `chat`/`_build_request`/`_effective_max_tokens` accept a per-call `model` override; `task_type` threaded to the token ledger; surfaces cache tokens. (Builder sends no `temperature`/`thinking.budget_tokens`, so the override is safe for Fable 5 / Opus 4.8.) |
| `governance/token_ledger.py` | `psycopg2` made optional (best-effort DB logging; cost still computed via `estimate_cost_micros`). `task_type` now populated. |
| `config/defaults.toml` | New `[ai.model_policy]` block (mode/pinned_model/profile/lethality/dry_run + `[ai.model_policy.overrides]`). |

### Refactored call sites (now pass `task_type`)

| Call site | task_type |
|---|---|
| `intel_team/agents/base.py:call_llm` | `specialist:<domain>` (or `config.task_type`) |
| `agent/planner.py` | `planner` |
| `agent/critic.py` | `critic` |
| `core/nlp_engine.py` | `orchestration` |
| `core/agent.py` (native + JSON fallback) | `agent_step` |

No direct/hardcoded model calls remain — every LLM call is cost-routed.

### Base routing policy ("auto")

- **Bulk** (tool calls, extraction, normalization, classification, summarization,
  bulk collection, extraction specialists socint/webint/geoint/socialint) → **Haiku 4.5**.
- **Reasoning / planning** (planner, critic, orchestration, agent steps,
  `specialist:audit`) → **Opus 4.8**.
- **Heaviest reasoning** (`specialist:analyst` / `synthesis:analyst` — ACH +
  final dossier narrative) → **Fable 5**.

### Per-mode profiles (config-named)

- **default** — the base auto policy above.
- **hephaestus** — discovery/extraction → Haiku; research → Opus; gap analysis +
  design → Fable.
- **dossier** — the **"lethality"** profile. Bulk collection/extraction/
  normalization/formatting → Haiku always; analysis steps escalate by level:

| Step | economy | balanced (default) | max |
|---|---|---|---|
| `specialist:analyst` (ACH + narrative) | Opus | **Fable** | **Fable** |
| `specialist:audit` (hypothesis gen) | Opus | Opus | **Fable** |
| `planner` | Opus | Opus | **Fable** |
| `critic` | Haiku | Opus | **Fable** |
| bulk specialists | Haiku | Haiku | Haiku |

Measured dry-run cost (7-step pipeline): economy ≈ $0.029, balanced ≈ $0.042,
max ≈ $0.064 — quality goes where it matters, cost stays controlled.

---

## 2. `/model` command (in-session, persisted)

Added to `cli/shell.py` (registered as `/model` in the `_commands` dict; help +
completion updated). Writes `ai.model_policy.*` via `settings.set` **and**
`settings.save()` (so selections survive restarts):

```
/model                       show active policy
/model fable|opus|haiku|<id> pin a model globally
/model auto                  re-enable cost-aware routing
/model profile <name>        default | hephaestus | dossier
/model lethality <lvl>       economy | balanced | max  (dossier)
/model <phase> <model>       per-step override (e.g. /model planner fable)
/model clear <phase>         remove a per-step override
/model cost                  estimated cost of the current/last run
```

---

## 3. Native Hephaestus agent

`hephaestus/` package (no Claude Code dependency):

| File | Role |
|---|---|
| `hephaestus/agent.py` | `Hephaestus.run(focus, depth, dry_run, profile, lethality)`: GitHub discovery → research (router, Opus) → gap analysis vs the live registry (Fable) → decide (Fable) → emit a validated run record. **H1/H3 PAUSE** the run with approval requests. |
| `hephaestus/discovery.py` | GitHub REST search (stdlib urllib) + NATO Admiralty scoring; offline fixtures for dry-run. |
| `hephaestus/run_record.py` | Run-record builder + stdlib schema validator; saves to `~/.strikecore/hephaestus/runs/<id>.json`. |
| `schema/hephaestus.run_record.schema.json` | The run-record contract. Its `routing`/`model_usage`/`totals` sub-structures are the **canonical cost-telemetry shape reused by other modes** (dossier). |

It uses the **hephaestus** routing profile. Every run emits model usage + cost.

### Place in the intelligence cycle

Hephaestus sits in **Collection-tooling R&D**: it ensures every PIR can be
answered because the right vetted tool exists and is registered. It only acts
through the H1/H3 gates and Git (GR1).

---

## 4. CLI integration — `bin/hephaestus.py`

`run --focus CAT [--depth N] [--dry-run] [--profile P] [--lethality L]` ·
`status` · `report [run_id]` · `approve <run_id> <H1|H3>`. Mirrors
`bin/sc-registry.py` (argparse subparsers, exit codes 0/1/2/3). SHA-256 audit
line per run/approval.

---

## 5. Dashboard

`web/backend/app.py`:
- `GET /api/hephaestus/runs` — run records (discovered tools, decisions, gaps,
  pending H1/H3) from the run-record JSON (no DB).
- `GET /api/tokens/by-mode` — per `task_type`+`model` usage/cost from
  `token_ledger` (the per-step model badges + dossier cost view).

`web/frontend/src/pages/Hephaestus.tsx` (+ route in `App.tsx`, nav in
`Sidebar.tsx`, types in `lib/api.ts`): discovered tools with Admiralty badges,
pending-approval controls, decisions, **per-step model badges + routing reason +
cost**, and a **dossier-mode lethality cost view**. Matches the existing
Tailwind/react-query/recharts stack. *(Built on atlas where `node_modules` live;
not build-verified in the bare clone.)*

---

## 6. Config keys reference

```toml
[ai.model_policy]
mode = "auto"            # "auto" | "pinned"
pinned_model = ""        # fable|opus|haiku|<id> when pinned
profile = "default"      # default | hephaestus | dossier
lethality = "balanced"   # economy | balanced | max
dry_run = false          # true => no real API calls; routing+cost offline
[ai.model_policy.overrides]   # e.g. planner = "claude-fable-5"
```

Model ids (verified): `claude-fable-5`, `claude-opus-4-8`, `claude-haiku-4-5`.

---

## 7. Verification (safe dry-runs, no real targets / no DB / no spend)

```bash
python3 tests/test_model_router.py            # routing policy
/path/python tests/test_router_chat.py        # router dry-run + cost ledger
python3 tests/test_model_cmd.py               # /model settings round-trip
hephaestus run --dry-run --focus document --depth 2   # Hephaestus dry-run
python3 tests/dossier_dryrun.py               # dossier lethality routing + cost
```

All pass. The Hephaestus dry-run routes research→Opus, gap/design→Fable, and
PAUSES on H1/H3; the dossier dry-run routes analysis→Fable/Opus and bulk→Haiku
with cost scaling by lethality.

> **Note on `[1m]` / current session model:** this build runs on
> `claude-opus-4-8[1m]`; the router targets the bare ids `claude-fable-5` /
> `claude-opus-4-8` / `claude-haiku-4-5` (no suffix), per the claude-api skill.
