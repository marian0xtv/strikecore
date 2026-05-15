# StrikeCore — Stack & Re-Engineering Decision Record

**Date:** 2026-05-15
**Operator:** atlas
**Build agent:** Claude (Opus 4.7 1M, via SSH to atlas@10.0.0.1)
**Plan reference:** `/root/.claude/plans/streamed-mapping-parrot.md` (operator-local)
**Implementation log:** `.claude-implementation.log` (this repo, git-ignored)

---

## 1. What StrikeCore Actually Is (Verified 2026-05-15)

StrikeCore is an **operational** OSINT/offensive-intelligence Python platform with:

- **9 574 LOC** across 23 `core/` modules (executor, fp_filter, nlp_engine, investigation_store,
  tool_registry, provider_router, proxy_manager, troubleshoot_agent, graph_engine,
  report_builder, photo_forensics, geoint_apis, ip_logger, contact_validator, …)
- **11 specialist agents** under `agents/` (binary, bugbounty, cloud, ctf, geoint,
  github_scanner, osint, recon, socint, webapp, …)
- **19+ CLI tools** under `bin/` (deep_lookup, contact_finder, email_hunter, phone_lookup,
  ig-* family, breach_free, breach_lookup, graph_generator, health_check, self_audit, …)
- **Nuxt frontend** under `frontend/` (pages/db, pages/investigations, pages/gateway,
  pages/tracking, stores, composables, components)
- **Active audit chain**: daily JSONL in `~/.strikecore/audit/` since 2026-03-22
- **Real investigation history**: 36 dossiers under `~/strikecore-data/`
- **157+ OSINT binaries** in `~/.local/bin/` plus system tools (nmap, masscan, sqlmap,
  msfconsole, hydra, john, hashcat, exiftool, …)
- **Multi-provider AI**: anthropic / openrouter / ollama / vllm / lmstudio / custom

StrikeCore is *not* a greenfield project. The original re-engineering plan assumed a
broken skeleton based on a stale local mirror — recon corrected that picture.

## 2. Engineering Problems Identified

| # | Problem | Severity |
|---|---|---|
| 1 | Project root is a Python venv (`pyvenv.cfg`, `bin/python3`, `lib/python3.13/site-packages`) — source mixed with binaries | High |
| 2 | Two nested venvs (`./strikecore/`, `./strikecore-env/`) — confusing, only one used | Medium |
| 3 | `~30` investigation `<target>.txt` files at project root (PII at risk of being committed) | High |
| 4 | Anthropic API key stored cleartext in `~/.strikecore/config.toml` | **Critical** |
| 5 | No git, no commits, no history | High |
| 6 | `.gitignore` was the venv default `*` (catastrophic for any future git use) | High |
| 7 | No `pyproject.toml`, no `uv.lock`, just a 12-line `requirements.txt` | Medium |
| 8 | No tests | Medium |
| 9 | No formalised multi-agent **intel team** — agents exist as 11 separate classes with no orchestrator, no PIR router, no quality gate | High (this is the genuine gstack-embedded deliverable) |

## 3. Stack Decisions (binding)

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ (current runtime is 3.13) | Existing 9 574 LOC + 157 OSINT bins are Python; switching is unjustifiable |
| Pkg manager | `uv` (additively — existing venvs remain functional) | Modern, deterministic, gstack-aligned. Coexists with the venv-in-root |
| Build config | `pyproject.toml` | Replaces ad-hoc `requirements.txt` as authoritative dependency declaration. requirements.txt kept as compatibility |
| Source layout | **Keep current top-level layout** (cli/, core/, agents/, bin/, …) | "DO NOT restructure" doctrine in `CLAUDE.md` is honoured. Repository discipline added via git/.gitignore, not file moves |
| Secrets | `.env` (chmod 600, git-ignored) + `.env.example` (committed) | Settings.py already supports env-var override layer. Migration is additive |
| Secret inventory | `.secrets-inventory.md` (fingerprints only, chmod 600, git-ignored) | Auditable trail without exposing values |
| Version control | git, branch `main`, local user `atlas <atlas@strikecore.local>` | Per-repo identity, NOT global, per operator brief |
| Tests / lint | pytest + ruff + mypy (dev extras) | Engineering gates for new code (intel_team), retrofittable to legacy core |
| Intel-team layer | NEW `intel_team/` package — PIR-router → 7 domain specialists → audit (red cell) → analyst | The genuine gstack-embedded deliverable |
| LLM tiering | Opus 4.7 (analyst, ACH synth) / Sonnet 4.6 (specialists) / Haiku 4.5 (FP filter / dedup) | Cost-balanced per Anthropic SDK guidance |
| Prompt caching | Enabled per `claude-api` skill | Mandatory for fan-out efficiency |
| Frontend | **Keep existing Nuxt** under `frontend/` — out of scope this iteration | Already deployed; risk-vs-value rejects refactor now |
| DB | **Keep JSON store** (`investigation_store.py`) for this iteration | Working; Postgres+pgvector deferred to optional `[db]` extras |
| Containers | **Defer docker-compose** for now — Tor / Postgres / Redis stay native or unused until needed | Reduces blast radius this iteration |
| Service supervision | **Defer systemd unit** until intel_team is verified | Same rationale |

## 4. gstack Methodology — How Applied

**External (engineering driver):**
- Plan → review → implement → audit gates (this document is the audit artefact)
- Every decision logged in `.claude-implementation.log` (git-ignored)
- Backups before any move (`.backup/<UTC>/`)
- Pre-commit leak scans for Anthropic / AWS / OpenSSH / GitHub PAT secret patterns

**Embedded (intel_team module — to be built in Phase 4):**
- `intel_team/orchestrator.py` — PIR intake, domain classification, parallel dispatch
- `intel_team/pir_router.py` — domain classifier (Sonnet)
- `intel_team/quality_gate.py` — wraps existing `core/fp_filter.py`; enforces ≥2-source rule
- 7 domain specialists in `intel_team/agents/` (SOCINT, GEOINT, TECHINT, WEBINT, THREATINT, CROSSDB, REDTEAM) — each a constrained-tool Sonnet sub-agent
- `intel_team/agents/audit.py` — red cell / devil's advocate
- `intel_team/agents/analyst.py` — Opus, performs ACH + Key Assumptions Check, produces final dossier
- `intel_team/prompts/*.md` — system prompts per specialist
- Wraps existing `agents/*_agent.py` classes (does NOT replace them)

## 5. What Is Being Changed

| Action | Reversible? |
|---|---|
| Created `.backup/20260515T231443Z/` with 9 critical files + 37 investigation .txt | n/a (additive) |
| Wrote proper `.gitignore` (137 lines) replacing default `*` | yes (backup of original kept) |
| Moved 36 investigation `<target>.txt` files from project root to `~/strikecore-data/dossiers_legacy/` | yes (full mv, no delete) |
| Generated `.env` (chmod 600) with migrated `ANTHROPIC_API_KEY` + freshly-generated POSTGRES / REDIS / TOR / JWT / AUTH secrets | n/a (additive) |
| Generated `.env.example` (committed) and `.secrets-inventory.md` (git-ignored) | n/a (additive) |
| `git init -b main`, per-repo identity `atlas <atlas@strikecore.local>` | yes (rm -rf .git) |
| Wrote `pyproject.toml` (replaces requirements.txt as source-of-truth; requirements.txt kept for compat) | yes (additive) |
| Wrote this `STACK_DECISION.md` | n/a (additive) |

## 6. What Is NOT Being Changed (Doctrine Preservation)

- `NL_SYSTEM_PROMPT` in `core/nlp_engine.py` — preserved verbatim
- `ALLOWED_BINARIES` in `core/executor.py` — preserved
- JSON schema in `core/investigation_store.py` — preserved (additive Postgres layer is optional `[db]` extra)
- `config/settings.py` singleton pattern + env-override map — preserved
- 14 data categories — preserved
- Existing 11 `agents/*_agent.py` files — preserved (intel_team wraps them)
- `~/.strikecore/config.toml` — **not yet cleaned** of the Anthropic key (env overrides it; operator should remove after rotation)
- `frontend/` Nuxt app — preserved
- Both nested venvs (`./strikecore/`, `./strikecore-env/`) — preserved (the running `strikecore.sh` uses `./strikecore/bin/python3`)

## 7. Operator Action Required

1. **🚨 ROTATE the Anthropic API key.** Fingerprint `FAAA_sha256:f4f0ff48` was inspected via `cat` during recon and is therefore considered compromised. Generate a new key at `console.anthropic.com`, paste into `.env` line `ANTHROPIC_API_KEY=...`, then `chmod 600 .env`.
2. After rotation, remove the cleartext value from `~/.strikecore/config.toml` (`[ai.anthropic].api_key = ""`). The env-override layer will then become the sole source.
3. Optionally, run `sudo` to allow Phase 5 docker-compose installation if Postgres/Redis are wanted (deferred for now).

## 8. Risks Accepted This Iteration

- **No frontend changes** — existing Nuxt frontend may not yet integrate with the new intel_team module. Wiring deferred to a future iteration.
- **No live tool installs** — `install_tools.sh` and `install_osint_mega.sh` are unchanged; new specialists call existing wrappers.
- **No Postgres migration** — investigation_store stays on JSON. pgvector dedup is a future capability.
- **Tests are scaffolding-level** — Phase 6 will add smoke tests, not a full coverage suite.
- **Single-operator deployment** — no multi-tenant auth, no production hardening beyond reasonable defaults.
