# CLAUDE.md — StrikeCore OSINT Platform

> Auto-read by Claude Code on every session. Do NOT delete this file.

## Architecture

```
main.py → cli/shell.py (StrikeCoreShell REPL) → core/nlp_engine.py (NaturalLanguageEngine)
                                                  ↓
                                            core/executor.py (async subprocess)
                                                  ↓
                                            117+ OSINT tools on PATH
```

- **Config:** `~/.strikecore/config.toml` (TOML, loaded by `config/settings.py`)
- **Data:** `~/strikecore-data/investigations/` (JSON per target)
- **Database:** `~/strikecore-data/strikecore.db` (SQLite, synced from JSON)
- **Reports:** `~/strikecore-data/reports/` (HTML+MD)
- **Graphs:** `~/strikecore-data/reports/graphs/` (interactive HTML via pyvis)
- **Audit:** `~/.strikecore/audit/` (daily JSONL)
- **Logs:** `~/.strikecore/logs/`
- **Auth:** `~/.strikecore/ig_session` (Instagram), `~/.strikecore/fb_token` (Facebook)

## Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `core/nlp_engine.py` | ~820 | AI engine: system prompt, 8-phase workflow, auto-extraction, proxy wrapping, troubleshoot |
| `core/investigation_store.py` | ~300 | JSON per-target store: 14 data categories, adder methods, RAG search |
| `core/executor.py` | ~580 | Async command executor: 178-tool allowlist, live output, audit trail, stdin=DEVNULL |
| `core/database.py` | ~170 | SQLite sync layer: 10 tables, one-way JSON→SQLite via `import_from_json()` |
| `core/proxy_manager.py` | ~160 | Tor SOCKS5 rotation: NEWNYM signal, proxychains wrapping, rate-limit detection |
| `core/troubleshoot_agent.py` | ~220 | Error diagnosis: 8 patterns, 10 tool alternative chains, auto-fix |
| `core/graph_engine.py` | ~180 | pyvis+networkx: typed/colored nodes, confidence-weighted edges, ForceAtlas2 layout |
| `core/report_builder.py` | ~280 | Markdown+HTML reports: 9 sections, dark theme, collapsible evidence |
| `cli/shell.py` | ~1300 | REPL: 22+ commands, prompt_toolkit, NLP dispatch on unrecognized input |
| `bin/deep_lookup.py` | ~800 | 9-phase automated OSINT investigator |
| `bin/contact_finder.py` | ~400 | 9-phase phone + social connection finder |
| `bin/ig-social-circle.py` | ~300 | Instagram social profiler: followers/following/mutuals/comments/likes/tags |

## Operational Rules

1. **All 117 tools are INSTALLED.** Never `pip install`, `apt install`, or `git clone`.
2. **Use WRAPPERS** for problematic tools: `ig-auth-lookup`, `sc-toutatis`, `sc-holehe`, `sc-emailrep`, `wa-check`, `sc-nuclei`
3. **NEVER use:** `instaloader` (429 blocked), `wa-osint` (hangs), raw `holehe` (noisy), raw `nuclei` (wrong template path)
4. **Confidence scoring:** 0.0–1.0 numeric + legacy CONFIRMED/PROBABLE/UNVERIFIED mapping
5. **Cross-validate:** findings need ≥2 independent sources to exceed 0.7 confidence
6. **Proxy:** rate-limited tools auto-route through Tor (`proxychains4 -q`)
7. **sudo** for: `nmap -O/-A/-sS/-sU`, `masscan`, `tcpdump`, `traceroute`
8. **Italian targets:** also check paginebianche.it, registroimprese.it, infocamere.it
9. **Phone extraction:** ONLY from phone-specific tools (h8mail, phoneinfoga, contact_finder, wa-check, truecallerjs, ignorant, ghostintel). Never from Instagram/social API output.

## Tool Categories (117+)

- **SOCINT:** sherlock, maigret, holehe, h8mail, phoneinfoga, blackbird, nexfil, socialscan, mosint, social-analyzer, profil3r, crosslinked, nqntnqnqmb, truecallerjs
- **GEOINT:** exiftool, mat2, metagoofil, geoiplookup, metadetective
- **RECON:** nmap, masscan, subfinder, amass, httpx, nuclei, katana, naabu, hakrawler, gospider, dnstwist, xurlfind3r, theHarvester, whatweb, wafw00f
- **EXPLOIT:** msfconsole, searchsploit, hydra, john, hashcat, sqlmap
- **INFRA:** shodan, censys, trivy, grype, sslscan, sslyze, testssl.sh
- **Custom scripts:** `bin/deep_lookup.py`, `bin/contact_finder.py`, `bin/email_hunter.py`, `bin/phone_lookup.py`, `bin/ig-social-circle.py`, `bin/graph_generator.py`

## Sub-Agents (9)

recon, webapp, bugbounty, ctf, cloud, binary, osint, socint, geoint — in `agents/` directory.

## Session Startup

1. Health check runs automatically (quick mode)
2. Last investigation context displayed if exists
3. Stale investigations (>7 days) flagged

## DO NOT

- Rename directories or restructure the project
- Rewrite `NL_SYSTEM_PROMPT` in `core/nlp_engine.py` (battle-tested 8-phase workflow)
- Modify `ALLOWED_BINARIES` in `core/executor.py` without testing
- Change the JSON schema in `investigation_store.py` (backward compat with existing files)
- Remove or replace the existing `config/settings.py` singleton pattern
