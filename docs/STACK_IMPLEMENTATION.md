# StrikeCore — Stack Implementation Guide

> Documento operativo completo della re-ingegnerizzazione 2026-05-15/16.
> Complementa `STACK_DECISION.md` (rationale & trade-off) con i dettagli implementativi.

---

## 1. Cos'è strikecore, dove vive

**strikecore** è una **piattaforma OSINT / offensive-intelligence Python** con un **modulo intel-team multi-agente embedded** (ispirato a gstack) per produzione di dossier in stile Palantir-Maven.

| Voce | Valore |
|------|--------|
| Host autoritativo | `atlas@10.0.0.1` (Ubuntu 24.04.4 LTS) |
| Path del codice | `/home/atlas/argus-intelligence/strikecore/` |
| Runtime config | `~/.strikecore/` (config.toml, audit/, logs/, ig_session) |
| Output investigazioni | `~/strikecore-data/` (investigations/, reports/, dossiers_legacy/) |
| Tool OSINT installati | `~/.local/bin/` (157+ binaries) + system tools (nmap, masscan, sqlmap, msfconsole, hydra, john, hashcat, exiftool, …) |
| Accesso da operator | SSH `atlas@10.0.0.1` via WireGuard. Key auth: `/root/.ssh/strikecore_ed25519` |

---

## 2. Git: come e dove vedere il lavoro

### 2.1 Stato del repository

Il repository git **vive solo localmente sul server `atlas`**. Nessun remote (GitHub, GitLab, ecc.) è configurato — la re-ingegnerizzazione ha solo `git init`-ato il working tree esistente, **NON pubblicato** nulla all'esterno.

```bash
ssh atlas
cd /argus-intelligence/strikecore
git remote -v                  # vuoto (nessun remote)
git branch -a                  # solo 'main' locale
git config --local user.name   # atlas
git config --local user.email  # atlas@strikecore.local
```

### 2.2 Vedere i commit

Tutti i comandi sotto si lanciano in `atlas:/argus-intelligence/strikecore`:

```bash
# Lista commit
git log --oneline

# Cosa è cambiato in un commit specifico (es. il fix del provider)
git show 281c5a6 --stat
git show 281c5a6                   # diff completo

# Cosa è cambiato in un file
git log --oneline -- providers/anthropic_provider.py
git blame intel_team/agents/socint.py

# Tutti i file toccati dalla re-ingegnerizzazione
git log --name-only --oneline ba2e5cd..HEAD

# Statistiche
git log --shortstat --oneline ba2e5cd..HEAD | tail -3
```

### 2.3 Storia attuale (8 commit su `main`)

| Hash | Tipo | Messaggio |
|------|------|-----------|
| `9e0a9e2` | fix   | `pir_router must not propagate phantom "missing target" error` |
| `e5150eb` | fix   | `SOCIALINT prompt — empty-input & source discipline` |
| `8ff1cdb` | feat  | `WEBINT, GEOINT, SOCIALINT specialists + base refactor` |
| `281c5a6` | fix   | `AnthropicProvider must read model/max_tokens from config dict` |
| `7ce6698` | docs  | `CLAUDE.md: reflect realised state after 2026-05-15 re-engineering` |
| `e238d2b` | fix   | `intel_team base.py — match ProviderRouter.chat signature (no max_tokens kwarg)` |
| `f59c574` | feat  | `embedded multi-agent intelligence team (gstack-embedded)` |
| `ba2e5cd` | chore | `baseline import of operational strikecore v1.0 into git` |

Ogni commit ha un trailer `Co-Authored-By: Claude Opus 4.7 (1M context)`.

### 2.4 Se vuoi pubblicare il repo (futuro, opzionale)

```bash
# 1. Crea il repo vuoto su GitHub (tramite UI o gh CLI)
gh auth login
gh repo create argus-intelligence/strikecore --private

# 2. Aggiungi il remote e pusha
git remote add origin git@github.com:argus-intelligence/strikecore.git
git push -u origin main
```

**Prima di pushare**, verifica un'ultima volta che secrets siano fuori:

```bash
git ls-files | xargs grep -lE '(sk-ant-api03-|sk-proj-|AKIA[A-Z0-9]{16}|-----BEGIN .* PRIVATE KEY)' 2>/dev/null
# (deve essere vuoto)
```

### 2.5 Backup operativi (separati da git)

Snapshot di file critici prima di ogni modifica sono in `.backup/<UTC-timestamp>/` (git-ignored). Esempio:

```bash
ls .backup/20260515T231443Z/
# config.toml, twilio.env, main.py, strikecore.sh, requirements.txt,
# CLAUDE.md, DOCUMENTATION.md, install_tools.sh, install_osint_mega.sh,
# .gitignore, pyvenv.cfg, investigations_txt/(37 file <target>.txt),
# config.toml.pre-model-update, anthropic_provider.py.original
```

---

## 3. Architettura completa

### 3.1 Albero del progetto

```
/argus-intelligence/strikecore/
├── main.py                         # entrypoint REPL
├── strikecore.sh                   # launcher (esegue ./strikecore/bin/python3 main.py)
├── pyproject.toml                  # uv-managed (NEW 2026-05-15)
├── requirements.txt                # kept for compat
├── docker-compose.yml              # NOT YET — deferred
├── alembic/                        # NOT YET — deferred (db extras)
├── .env                            # secrets (chmod 600, git-ignored)        NEW
├── .env.example                    # template committato                      NEW
├── .secrets-inventory.md           # fingerprint manifest (git-ignored)       NEW
├── .gitignore                      # 137 righe                                NEW
├── .backup/<UTC>/                  # snapshot pre-modifica                    NEW
├── .claude-implementation.log      # audit trail della re-ingegnerizzazione   NEW
├── CLAUDE.md                       # doctrine + architecture (riscritto)
├── STACK_DECISION.md               # decision record                          NEW
├── DOCUMENTATION.md                # technical docs originale
├── docs/
│   └── STACK_IMPLEMENTATION.md     # questo documento                         NEW
│
├── cli/                            # REPL legacy
│   ├── shell.py                    # 55 KB, 22+ comandi, prompt_toolkit
│   ├── banner.py
│   ├── onboarding.py
│   └── renderer.py
│
├── core/                           # 23 moduli, 9 574 LOC
│   ├── nlp_engine.py               # 832 — NL_SYSTEM_PROMPT preservato
│   ├── tool_registry.py            # 1 689 — 150+ tool con schema Anthropic
│   ├── executor.py                 # 577  — async subprocess, ALLOWED_BINARIES, JSONL audit
│   ├── fp_filter.py                # 574  — FP scoring, libphonenumbers, IT patterns
│   ├── reset_oracle.py             # 640
│   ├── agent.py                    # 521
│   ├── ip_logger.py                # 544
│   ├── photo_forensics.py          # 474
│   ├── investigation_store.py      # 468  — JSON per target, 14 categorie, ConfidenceScore
│   ├── provider_router.py          # 425  — anthropic/openrouter/ollama/vllm/lmstudio/custom
│   ├── process_manager.py          # 387
│   ├── cache.py                    # 378
│   ├── geoint_apis.py              # 349
│   ├── number_enumerator.py        # 290
│   ├── report_builder.py           # 274
│   ├── contact_validator.py        # 264
│   ├── troubleshoot_agent.py       # 215
│   ├── email_tracker.py            # 198
│   ├── database.py                 # 169
│   ├── proxy_manager.py            # 161
│   ├── graph_engine.py             # 145
│   └── __init__.py
│
├── agents/                         # 11 specialist storici (pre-intel_team)
│   ├── binary_agent.py
│   ├── bugbounty_agent.py
│   ├── cloud_agent.py
│   ├── ctf_agent.py
│   ├── geoint_agent.py
│   ├── github_scanner_agent.py
│   ├── osint_agent.py
│   ├── recon_agent.py
│   ├── socint_agent.py
│   └── webapp_agent.py
│
├── bin/                            # 20+ script CLI + intel-team
│   ├── intel-team.py               # CLI multi-agente Palantir-style          NEW
│   ├── deep_lookup.py
│   ├── contact_finder.py
│   ├── email_hunter.py
│   ├── phone_lookup.py
│   ├── ig-* family
│   ├── breach_free.py / breach_free_v2.py / breach_lookup.py
│   ├── argus_v2.py
│   ├── call-sniffer.py
│   ├── graph_generator.py
│   ├── geoint_report.py
│   ├── photo_forensics.py
│   ├── health_check.py
│   ├── self_audit.py
│   └── sc-argus.py
│
├── intel_team/                     # ★ MODULO NUOVO — multi-agente embedded   NEW
│   ├── __init__.py                 # public API
│   ├── types.py                    # PIR, Source, Finding, AgentReport, Dossier
│   ├── orchestrator.py             # pipeline end-to-end + audit JSONL chain
│   ├── pir_router.py               # PIR → domini (fast tier)
│   ├── quality_gate.py             # FP filter + ≥2-source rule
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py                 # BaseSpecialist + helpers condivisi
│   │   ├── socint.py               # account discovery
│   │   ├── socialint.py            # social-graph analysis             NEW
│   │   ├── geoint.py               # geospatial / image / temporal     NEW
│   │   ├── webint.py               # exposed data / breach / dorking   NEW
│   │   ├── audit.py                # red cell / devil's advocate
│   │   └── analyst.py              # synthesiser (Opus tier)
│   └── prompts/
│       ├── pir_router.md
│       ├── socint.md
│       ├── socialint.md            # NEW
│       ├── geoint.md               # NEW
│       ├── webint.md               # NEW
│       ├── audit.md
│       └── analyst.md
│
├── intelligence/                   # CVE manager, decision engine, vuln correlator
├── messaging/
├── log_system/
├── osint_agent/                    # dashboard, parsers, tools
├── prompts/                        # dossier templates (storici)
├── providers/                      # LLM provider classes
│   ├── anthropic_provider.py       # ★ FIXATO per leggere model da config
│   ├── openrouter_provider.py
│   ├── ollama_provider.py
│   ├── vllm_provider.py
│   ├── lmstudio_provider.py
│   ├── generic_openai.py
│   └── base.py
├── voip/
├── reports/
├── config/
│   ├── defaults.toml
│   └── settings.py                 # Singleton + env-override map
├── frontend/                       # Nuxt 3 (deployato, non integrato con intel_team)
├── strikecore/                     # venv nidificato (lo usa strikecore.sh)
└── strikecore-env/                 # venv nidificato secondario
```

### 3.2 Flussi runtime

**Flusso A — REPL legacy** (immutato):

```
strikecore.sh
  → ./strikecore/bin/python3 main.py
      → cli/shell.py (StrikeCoreShell)
          → core/nlp_engine.py (NL_SYSTEM_PROMPT, 8-phase workflow)
              → core/executor.py
                  → 157+ OSINT binaries + system tools
```

**Flusso B — Intel Team (nuovo)**:

```
bin/intel-team.py --target X --pir "Q" --domains a,b,c
  → carica .env (stdlib-only)
  → ProviderRouter dalle settings (config.toml + env override)
  → intel_team.orchestrator.IntelTeam.investigate(PIR)
      ├─ pir_router.classify(PIR)              # 1 call fast tier
      ├─ asyncio.gather(specialists in parallel) # N call specialist tier
      ├─ quality_gate.apply(report) per ogni report
      ├─ audit_agent.analyze (red cell)        # 1 call specialist tier
      ├─ analyst.synthesize                    # 1 call analyst tier (Opus)
      └─ produce Dossier → MD + JSON in ~/strikecore-data/reports/intel_team/
  → JSONL audit chain SHA-256 in ~/.strikecore/audit/<YYYY-MM-DD>.jsonl
```

---

## 4. Modulo intel_team in dettaglio

### 4.1 Tipi (`intel_team/types.py`)

| Classe | Ruolo |
|--------|-------|
| `Domain`        | Enum: SOCINT, SOCIALINT, GEOINT, TECHINT, WEBINT, THREATINT, CROSSDB, REDTEAM, AUDIT, ANALYST, META |
| `Reliability`   | Enum NATO Admiralty A–F (A = completely reliable) |
| `Credibility`   | Enum NATO Admiralty 1–6 (1 = confirmed) |
| `PIR`           | Priority Intelligence Requirement: id, question, target, domains_hint, constraints |
| `Source`        | Provenienza di un finding: name, upstream, reference, reliability, credibility, fetched_at |
| `Finding`       | Singolo dato: domain, finding_type, value, sources, confidence (0.0-1.0), notes, pivot_hints |
| `AgentReport`   | Output di uno specialist: findings, gaps, rejected, devils_advocate_notes, confidence_summary, latency, error |
| `Dossier`       | Output finale: BLUF, key_judgments, ACH summary, key_assumptions, source_reliability_matrix, intelligence_gaps, recommended_actions, findings_by_domain, audit_trail. `to_markdown()` renderizza per l'operatore |

### 4.2 Quality Gate (`intel_team/quality_gate.py`)

Applicato a OGNI specialist report prima dell'audit:

1. Wraps `core/fp_filter.py` (NON profile URL, generic usernames, …).
2. Cap doctrinal: **confidence > 0.7 richiede ≥ 2 source independent** (CLAUDE.md §2.4 / §3.7).
3. Riassume in `confidence_summary` la distribuzione (`confirmed_>=0.9`, `probable_>=0.7`, `unverified_>=0.4`, `weak_<0.4`).
4. I finding rejected NON sono persi — vanno in `report.rejected` per audit trail.

### 4.3 Base specialist (`intel_team/agents/base.py`)

Estendere `BaseSpecialist` per creare un nuovo specialist. Helpers built-in:

| Metodo | Cosa fa |
|--------|---------|
| `system_prompt`          | Lazy-load del file Markdown da `intel_team/prompts/{name}.md` |
| `call_llm(user_message)` | Single LLM dispatch via `core.provider_router` |
| `_safe_parse_json(text)` | Strip code fence + estrae outermost `{...}` |
| `_coerce_finding(item)`  | Dict LLM → `Finding`, applica `_ALLOWED_TYPES`/`_FORBIDDEN_TYPES`, valida source presence, mappa NATO Admiralty |
| `_build_user_message(pir, ctx)` | Default user-msg builder; override per context fields domain-specific |
| `_standard_analyze(pir, ctx)` | Pipeline canonico: call → parse → coerce → AgentReport. Default per `analyze()` |

**Class vars di sicurezza:**

- `_ALLOWED_TYPES: frozenset[str]` (vuoto = accept all; non-vuoto = remap unknown a `"other"`)
- `_FORBIDDEN_TYPES: frozenset[str] = {"phone", "phone_number"}` (CLAUDE.md §3.4 — phone solo da phone-tool)

### 4.4 Specialist domain-specific

| Specialist | Domain | Tipi consentiti (highlights) | Context fields extra |
|---|---|---|---|
| `SOCINTSpecialist`     | SOCINT     | username, email, profile_url, alias, location, org, connection, photo | (default) |
| `SOCIALINTSpecialist`  | SOCIALINT  | connection, mutual_count, sockpuppet_cluster, alias_link, community, centrality_signal, ego_network_shape, relationship_type, interaction_pattern, tag_co_occurrence, comment_graph_edge, post_time_cluster, cross_platform_overlap | followers, following, mutuals, comment_threads, like_records, tag_records, post_timestamps, candidate_aliases |
| `GEOINTSpecialist`     | GEOINT     | gps_coords, country, city, address, venue, place_of_interest, timezone, movement_pattern, photo_location, visual_landmark, weather_signal, sun_angle_signal, device_make, device_model, ip_geolocation | exif_dumps, post_timestamps, claimed_locations |
| `WEBINTSpecialist`     | WEBINT     | email, breach_record, leaked_password_hash, credential_pair, document, document_author, document_revision, domain, subdomain, cert_san, archived_url, wayback_snapshot, google_dork_hit, github_commit, github_gist, exposed_endpoint, registry_record, ansa_article, comune_albo_pretorio, paginebianche_entry, exif_author | (default) |
| `AuditAgent`           | AUDIT      | (override `analyze`, produce challenge in `devils_advocate_notes`) | specialist_reports |
| `AnalystAgent`         | ANALYST    | (override `analyze`/`synthesize`, produce `Dossier`) | specialist_reports + audit_reports |
| `PIRRouter`            | META       | (override `classify`, produce `RoutingDecision`) | (PIR) |

### 4.5 Orchestrator (`intel_team/orchestrator.py`)

Pipeline:

```python
async def investigate(self, pir, *, tool_outputs=None, operator_notes=""):
    1. decision = await self.pir_router.classify(pir)
    2. specialist_reports = await self._dispatch_specialists(...)  # asyncio.gather
    3. for r in specialist_reports: self.quality_gate.apply(r)
    4. audit_report = await self.audit_agent.analyze(...)
    5. dossier = await self.analyst.synthesize(...)
    6. return dossier
```

**Audit chain** (`_audit`):

Ogni evento (`pir_routed`, `quality_gate_applied`, `audit_completed`, `dossier_produced`) appende un'entry a `~/.strikecore/audit/<YYYY-MM-DD>.jsonl`. Ogni entry ha campo `hash` = SHA-256 del JSON ordinato — chain-of-custody.

**Registry estendibile:**

```python
SPECIALIST_REGISTRY: dict[Domain, type[BaseSpecialist]] = {
    Domain.SOCINT:    SOCINTSpecialist,
    Domain.SOCIALINT: SOCIALINTSpecialist,
    Domain.GEOINT:    GEOINTSpecialist,
    Domain.WEBINT:    WEBINTSpecialist,
    # TECHINT, THREATINT, CROSSDB, REDTEAM — roadmap
}
```

Aggiungere uno specialist = (a) nuova subclasse di `BaseSpecialist`, (b) nuovo prompt `intel_team/prompts/<dom>.md`, (c) entry in `SPECIALIST_REGISTRY`. Niente altre modifiche.

---

## 5. Provider LLM (`providers/anthropic_provider.py`)

| Provider | Endpoint | Stato |
|----------|----------|-------|
| anthropic   | api.anthropic.com    | ✓ attivo (`claude-sonnet-4-6` per default, configurabile) |
| openrouter  | openrouter.ai/api/v1 | placeholder (api_key vuota) |
| ollama      | localhost:11434      | nella fallback chain MA non running → timeout ~120s/call |
| vllm        | localhost:8000/v1    | placeholder |
| lmstudio    | localhost:1234/v1    | placeholder |
| custom      | 10.0.0.3:8088/v1     | api_key=`local`, model=`claude-code` |

**Bug fixato 2026-05-15 (`281c5a6`)**: `AnthropicProvider.__init__` ora legge `config["model"]` e `config["max_tokens"]` invece di usare solo i default hardcoded. Tutti i provider supportano fallback automatico via `ProviderRouter.chat()`.

**Modelli disponibili sull'account** (verificati via `/v1/models`):

- `claude-opus-4-7` (top-tier, per analyst)
- `claude-sonnet-4-6` (default, per specialist + router + audit)
- `claude-opus-4-6`
- `claude-haiku-4-5-20251001` (fast tier, ideale per pir_router future)
- `claude-sonnet-4-5-20250929`
- `claude-opus-4-5-20251101`
- `claude-opus-4-1-20250805`

---

## 6. Come si usa

### 6.1 REPL legacy

```bash
ssh atlas
cd /argus-intelligence/strikecore
./strikecore.sh                       # REPL StrikeCoreShell
./strikecore.sh --check               # health check
./strikecore.sh --version             # "StrikeCore v1.0.0"
./strikecore.sh --setup               # ri-esegui onboarding
./strikecore.sh --provider openrouter --model anthropic/claude-sonnet-4-5
```

### 6.2 Intel Team (one-shot, multi-agente)

```bash
cd /argus-intelligence/strikecore

# Esempio: investigazione su un username
./strikecore/bin/python3 ./bin/intel-team.py \
    --target alice123 \
    --pir "Verifica se alice123 è la stessa persona che usa alice.smith@example.com" \
    --domains socint,socialint,geoint,webint \
    --constraint passive_only=true

# Output:
#   ~/strikecore-data/reports/intel_team/<UTC>_alice123_pir-<id>.md
#   ~/strikecore-data/reports/intel_team/<UTC>_alice123_pir-<id>.json
#   audit entries in ~/.strikecore/audit/<YYYY-MM-DD>.jsonl

# Senza investigation store (per test puliti)
./strikecore/bin/python3 ./bin/intel-team.py --target X --pir "Q" --no-store

# Verbose
./strikecore/bin/python3 ./bin/intel-team.py --target X --pir "Q" --verbose
```

### 6.3 Audit chain ispezione

```bash
TODAY=$(date -u +%F)
jq -c 'select(.component=="intel_team.orchestrator")' ~/.strikecore/audit/$TODAY.jsonl
jq -c 'select(.pir_id=="pir-abc...")' ~/.strikecore/audit/$TODAY.jsonl
```

### 6.4 Verifica integrità repo

```bash
git status                                           # working tree clean?
git log --oneline                                    # storia commit
git ls-files | grep -E "\.env|secret"                # nessun secret tracked
git check-ignore -v .env .secrets-inventory.md       # ignorati correttamente?
```

---

## 7. Doctrine preservata (NON toccare)

CLAUDE.md §10 elenca le hard "DO NOT". Sono rispettate verbatim:

- ✓ `NL_SYSTEM_PROMPT` in `core/nlp_engine.py` immutato
- ✓ `ALLOWED_BINARIES` in `core/executor.py` immutato
- ✓ JSON schema in `core/investigation_store.py` immutato
- ✓ `config/settings.py` singleton immutato
- ✓ 14 categorie data store preservate
- ✓ 11 agent storici (`agents/*_agent.py`) preservati (NON sostituiti — intel_team li affianca)
- ✓ Frontend Nuxt preservato
- ✓ Entrambi i venv nidificati preservati (strikecore.sh continua a usare `./strikecore/bin/python3`)

---

## 8. Operator action items

### 8.1 🚨 Rotazione chiave Anthropic compromessa

**Fingerprint vecchia** `FAAA / f4f0ff48` — esposta in chiaro nell'output di recon. **Da revocare** su `console.anthropic.com`.

**Fingerprint nuova** `5QAA / 64414aad` — in uso (verificata via test 1-token su Haiku 4.5 + run E2E #4/#5 su Sonnet 4.6).

### 8.2 Pulizia residui

```bash
# Rimuovere la chiave cleartext da config.toml (la env override in .env già funziona):
sed -i 's|^api_key = "sk-ant-api03-.*"$|api_key = ""|' ~/.strikecore/config.toml
# Verifica:
grep -A1 '\[ai.anthropic\]' ~/.strikecore/config.toml | head -3
```

### 8.3 Ollama fallback

`~/.strikecore/config.toml` ha `[ai].fallback_chain = ["anthropic", "ollama"]`. Se Ollama non gira, ogni chiamata fallita su Anthropic aspetta ~120s prima di andare avanti. Opzioni:

```bash
# Opzione A — avvia ollama
sudo systemctl enable --now ollama   # o equivalente

# Opzione B — rimuovi ollama dalla chain
python3 -c "
import toml, pathlib
p = pathlib.Path.home() / '.strikecore/config.toml'
d = toml.load(p)
d['ai']['fallback_chain'] = ['anthropic']
p.write_text(toml.dumps(d))
"
```

---

## 9. Roadmap / debiti tecnici noti

| Voce | Stato | Note |
|------|-------|------|
| TECHINT specialist     | pending | infrastructure / DNS / certs / port fingerprinting |
| THREATINT specialist   | pending | CTI feeds, IOC enrichment |
| CROSSDB specialist     | pending | entity resolution cross-database |
| REDTEAM specialist     | pending | offensive recon (con scope authorisation) |
| Postgres + pgvector    | optional | `pip install .[db]` |
| Redis job queue        | optional | per investigazioni async lunghe |
| FastAPI dashboard      | optional | `pip install .[api]` |
| systemd unit / docker  | deferred | il REPL e l'intel-team CLI girano on-demand |
| Frontend ↔ intel_team  | future  | il frontend Nuxt esiste ma non chiama intel-team |
| pytest test suite      | future  | smoke test ad-hoc esistono; serve coverage formale |
| `agent_status` enum    | future  | l'analyst stesso (in E2E #5) ha raccomandato di aggiungerlo a `AgentReport` per distinguere `skipped` da `crash` |
| PIR-metadata schema    | future  | separare `pipeline_test_metadata` da `question` per evitare leak in dossier divulgabili |
| Investigation-store write gating  | future  | bloccare scritture da test runs in production store |

---

## 10. Indice rapido — dove cercare cosa

| Cerchi… | Vai a… |
|---------|--------|
| Cos'è strikecore                 | `CLAUDE.md` §1 + `DOCUMENTATION.md` |
| Perché le scelte di stack         | `STACK_DECISION.md` |
| Come usare l'intel-team           | qui §6.2 + `bin/intel-team.py --help` |
| Come estendere con un nuovo specialist | qui §4.5 + esempio in `intel_team/agents/socialint.py` |
| Prompt di un agente               | `intel_team/prompts/<dom>.md` |
| Inventario secrets                | `.secrets-inventory.md` (chmod 600, git-ignored) |
| Audit di un'investigazione        | `~/.strikecore/audit/<YYYY-MM-DD>.jsonl` |
| Dossier prodotti                  | `~/strikecore-data/reports/intel_team/` |
| Investigazioni JSON               | `~/strikecore-data/investigations/<target>.json` |
| Dossier legacy `<target>.txt`     | `~/strikecore-data/dossiers_legacy/` |
| Storia delle modifiche di build   | `.claude-implementation.log` (git-ignored, append-only) |
| Backup pre-modifica               | `.backup/<UTC-timestamp>/` |

---

**Fine documento.** Aggiornare quando arrivano nuovi specialist o si cambia stack runtime.
