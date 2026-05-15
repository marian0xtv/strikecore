# StrikeCore v1.0 — Technical Documentation

**AI-Driven Offensive Security & OSINT Assessment Platform**  
Classification: INTERNAL — Authorized Personnel Only  
Version: 1.0.0 | Last Updated: 2026-03-22

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Installation & Setup](#3-installation--setup)
4. [Configuration](#4-configuration)
5. [Shell Commands Reference](#5-shell-commands-reference)
6. [AI Providers](#6-ai-providers)
7. [Social Media Authentication](#7-social-media-authentication)
8. [OSINT Scripts](#8-osint-scripts)
9. [Tool Wrappers](#9-tool-wrappers)
10. [Investigation System](#10-investigation-system)
11. [Database](#11-database)
12. [Report Builder & Graph Engine](#12-report-builder--graph-engine)
13. [Web Dashboard](#13-web-dashboard)
14. [Proxy & Anti-Rate-Limit System](#14-proxy--anti-rate-limit-system)
15. [Troubleshoot Agent](#15-troubleshoot-agent)
16. [Dossier Prompts](#16-dossier-prompts)
17. [Sub-Agents](#17-sub-agents)
18. [Installed Tools Inventory](#18-installed-tools-inventory)
19. [API Integrations](#19-api-integrations)
20. [File Reference](#20-file-reference)

---

## 1. Overview

StrikeCore is a Linux-native AI-powered security assessment and OSINT investigation platform. It provides:

- **Natural language interface** — speak in any language, the AI interprets and executes
- **117+ security/OSINT tools** integrated and orchestrated by AI
- **8-phase automated investigation workflow** for person/target dossiers
- **Persistent investigation database** (SQLite) with RAG document search
- **Interactive intelligence graph** generation (pyvis + networkx)
- **Web dashboard** (Flask) for viewing investigations, graphs, and reports
- **Proxy rotation** (Tor) with automatic rate-limit detection and retry
- **Auto-troubleshooting** — when tools fail, alternatives are proposed automatically
- **Multi-provider AI** — Anthropic Claude, Ollama (local), OpenRouter, custom endpoints

### Launch

```bash
cd /home/atlas/argus-intelligence/strikecore
./strikecore.sh
```

Or directly:
```bash
./strikecore/bin/python3 main.py
```

---

## 2. Architecture

```
strikecore/
├── main.py                          # Entry point
├── strikecore.sh                    # Launcher script (uses correct Python venv)
│
├── cli/
│   ├── shell.py                     # Interactive REPL shell (prompt_toolkit)
│   ├── banner.py                    # ASCII banner + system checks
│   ├── onboarding.py                # First-run setup wizard
│   └── renderer.py                  # Rich UI components (tables, panels, progress)
│
├── core/
│   ├── nlp_engine.py                # AI natural language processor (system prompt, phases)
│   ├── executor.py                  # Async command executor with live output
│   ├── provider_router.py           # Multi-provider AI router with fallback chain
│   ├── investigation_store.py       # JSON-based persistent per-target intelligence store
│   ├── database.py                  # SQLite database for dashboard/web access
│   ├── proxy_manager.py             # Tor proxy rotation + rate-limit detection
│   ├── troubleshoot_agent.py        # Auto-diagnosis and fix for tool failures
│   ├── report_builder.py            # Markdown + HTML report generator
│   ├── graph_engine.py              # pyvis + networkx intelligence graph builder
│   ├── agent.py                     # Core AI agent loop (tool-calling)
│   ├── tool_registry.py             # 150+ security tool definitions with JSON schemas
│   ├── cache.py                     # LRU result cache with TTL
│   └── process_manager.py           # Background process tracker
│
├── bin/                             # Custom investigation scripts
│   ├── deep_lookup.py               # 9-phase automated OSINT investigator
│   ├── contact_finder.py            # 9-phase phone + social connection finder
│   ├── email_hunter.py              # Email permutation + Gravatar/Holehe/EmailRep check
│   ├── phone_lookup.py              # Reverse phone number intelligence
│   └── graph_generator.py           # Interactive HTML graph generator (vis.js)
│
├── agents/                          # Specialized sub-agents
│   ├── recon_agent.py               # Reconnaissance
│   ├── webapp_agent.py              # Web application testing
│   ├── bugbounty_agent.py           # Bug bounty hunting
│   ├── ctf_agent.py                 # CTF challenge solving
│   ├── cloud_agent.py               # Cloud security assessment
│   ├── binary_agent.py              # Binary analysis
│   ├── osint_agent.py               # General OSINT
│   ├── socint_agent.py              # Social Intelligence (SOCINT)
│   └── geoint_agent.py              # Geospatial Intelligence (GEOINT)
│
├── providers/                       # AI provider implementations
│   ├── anthropic_provider.py        # Anthropic Claude API
│   ├── ollama_provider.py           # Ollama local models
│   ├── openrouter_provider.py       # OpenRouter multi-model
│   ├── vllm_provider.py             # vLLM self-hosted
│   ├── lmstudio_provider.py         # LM Studio local
│   └── generic_openai.py            # Any OpenAI-compatible endpoint
│
├── intelligence/
│   ├── api_integrations.py          # 25+ API manager (Shodan, HIBP, VirusTotal, etc.)
│   ├── decision_engine.py           # Target analysis + agent recommendation
│   ├── cve_manager.py               # CVE lookup and caching
│   └── vuln_correlator.py           # Vulnerability deduplication and scoring
│
├── osint_agent/
│   └── dashboard/
│       └── app.py                   # Flask web dashboard
│
├── prompts/                         # Dossier prompt templates
│   ├── dossier_template.md          # Generic template with {{placeholders}}
│   └── dossier_luigisav.md          # Example: Luigi Savino investigation
│
├── config/
│   ├── settings.py                  # Settings loader (TOML + env vars)
│   └── defaults.toml                # Default configuration values
│
├── log_system/                      # Logging subsystem
│   ├── logger.py                    # Loguru structured logging
│   ├── audit.py                     # JSON-lines audit trail
│   └── reporter.py                  # Session report generator
│
├── messaging/                       # Notification integrations
│   ├── telegram_bot.py              # Telegram alerts
│   └── whatsapp_bot.py              # WhatsApp via Twilio
│
├── install_tools.sh                 # Security tools installer (apt/pip/go/git)
└── install_osint_mega.sh            # 70+ OSINT tools mega installer
```

---

## 3. Installation & Setup

### Prerequisites
- Ubuntu 22.04+ / Debian 12+
- Python 3.12+
- 8GB+ RAM (32GB recommended for local AI models)
- Internet access for API calls and tool downloads

### Quick Start

```bash
# Clone or copy the project
cd /home/atlas/argus-intelligence/strikecore

# Install all security tools
./install_tools.sh

# Install OSINT-specific tools
./install_osint_mega.sh

# Run onboarding
./strikecore.sh --setup

# Launch
./strikecore.sh
```

### Install Scripts

| Script | Tools | Method |
|--------|-------|--------|
| `install_tools.sh` | 80+ security tools | apt, pip, go, git, script |
| `install_osint_mega.sh` | 40+ OSINT-specific tools from GitHub | pip, go, git clone |

Usage:
```bash
./install_tools.sh --list              # Show all tools and status
./install_tools.sh --category web      # Install only web tools
./install_tools.sh --only nmap,sqlmap  # Install specific tools
./install_tools.sh --dry-run           # Preview without installing
```

---

## 4. Configuration

### Main Config File: `~/.strikecore/config.toml`

```toml
# ── AI Provider ──
[ai]
active_provider = "anthropic"           # anthropic | ollama | openrouter | custom
fallback_chain = ["anthropic", "ollama"]

[ai.anthropic]
api_key = "sk-ant-api03-..."
model = "claude-sonnet-4-20250514"
max_tokens = 8192

[ai.ollama]
base_url = "http://localhost:11434"
model = "qwen3.5:9b"

[ai.openrouter]
api_key = ""
model = "anthropic/claude-sonnet-4-5"

[ai.custom]
base_url = "http://10.0.0.3:8088/v1"   # Claude Bridge or any OpenAI-compatible
api_key = "local"
model = "claude-code"

# ── Operator ──
[operator]
name = "atlas"
workdir = "/home/atlas/strikecore-data"
verbosity = 4                           # 1=quiet, 2=normal, 3=verbose, 4=debug

# ── Notifications ──
[telegram]
enabled = false
bot_token = ""
chat_id = ""

# ── API Keys (25+ integrations) ──
[apis]
# GEOINT
ipinfo = ""                             # https://ipinfo.io/signup
shodan = ""                             # https://account.shodan.io
censys_id = ""                          # https://search.censys.io/account/api
wigle = ""                              # https://wigle.net/account
opencellid = ""                         # https://opencellid.org/register
google_maps = ""                        # https://console.cloud.google.com/apis

# SOCINT
hunter_io = ""                          # https://hunter.io/api-keys
haveibeenpwned = ""                     # https://haveibeenpwned.com/API/Key
emailrep = ""                           # https://emailrep.io/key
numverify = ""                          # https://numverify.com/dashboard

# GENERAL
virustotal = ""                         # https://www.virustotal.com/gui/my-apikey
abuseipdb = ""                          # https://www.abuseipdb.com/account/api
greynoise = ""                          # https://viz.greynoise.io/account/api-key
securitytrails = ""                     # https://securitytrails.com/app/account
```

### Config File Locations

| File | Purpose |
|------|---------|
| `~/.strikecore/config.toml` | Main configuration |
| `~/.strikecore/ig_session` | Instagram session ID cookie |
| `~/.strikecore/fb_token` | Facebook Graph API token |
| `~/.mosint.yaml` | Mosint tool configuration |
| `~/.strikecore/history` | Shell command history |
| `~/.strikecore/logs/` | Application logs |
| `~/.strikecore/audit/` | Audit trail (JSONL) |

---

## 5. Shell Commands Reference

| Command | Arguments | Description |
|---------|-----------|-------------|
| `help` | | Show all available commands |
| `dossier` | `Name Surname [urls] [task]` | Build OSINT dossier with optional natural language task |
| `investigate` | `<target_id>` | Open/create persistent investigation |
| `report` | | Generate HTML report + intelligence graph for active investigation |
| `dashboard` | `[port]` | Launch web dashboard (default :5000) |
| `search` | `<query>` | Search across all stored intelligence |
| `upload` | `<filepath>` | Upload document to investigation RAG store |
| `scan` | `<target>` | Start AI-driven security assessment |
| `agent` | `<name> <target>` | Run specific agent (recon, webapp, socint, geoint, etc.) |
| `provider` | | Show active provider info |
| `provider` | `switch <name>` | Switch AI provider (anthropic, ollama, custom) |
| `provider` | `list` | List all configured providers |
| `models` | | List available models for active provider |
| `tools` | | List all security tools with install status |
| `install` | `github <url>` | Install a tool from GitHub repo |
| `install` | `socint` / `geoint` | Install all SOCINT or GEOINT tools |
| `status` | | System health, API usage, GPU info |
| `clear-chat` | | Clear AI conversation history |
| `clear` | | Clear screen |
| `exit` / `quit` | | Shutdown |

### Dossier Command Examples

```bash
# Full automatic dossier
dossier Luigi Savino instagram.com/luigisav

# With natural language task
dossier Luigi Savino instagram.com/luigisav find his phone number
dossier Luigi Savino github.com/LuigiSavino analyze commits for email addresses
dossier Mario Rossi search LinkedIn and phone directories in Milan

# Natural language without specific references
dossier Anna Bianchi build a complete profile starting from anna.bianchi@gmail.com
```

### Natural Language (any text that isn't a command)

```bash
# Anything typed that isn't a built-in command goes to the AI:
cerca l'username "john_doe" su tutti i social
geolocalizza l'IP 185.23.45.67
analizza il numero +393401234567
```

---

## 6. AI Providers

### Switching Providers

```bash
# From StrikeCore shell:
provider switch anthropic     # Anthropic Claude API (needs credits)
provider switch ollama        # Local model via Ollama (free, unlimited)
provider switch custom        # Custom endpoint (Claude Bridge or other)
provider list                 # Show all configured providers
```

### Anthropic Claude
- Config: `[ai.anthropic]` in config.toml
- Requires: `api_key`
- Models: `claude-sonnet-4-20250514`, `claude-opus-4-20250514`

### Ollama (Local)
- Config: `[ai.ollama]` in config.toml
- No API key needed, runs locally
- Available models on server: `qwen3.5:9b`, `qwen2.5:7b`
- Install more: `ollama pull llama3.1:8b`

### Claude Bridge (proxies through local Claude Code CLI)
- Run on local machine: `python3 claude_bridge.py`
- Config: `[ai.custom]` with `base_url = "http://10.0.0.3:8088/v1"`
- Uses your Claude Code session auth

### OpenRouter
- Config: `[ai.openrouter]` with API key
- 200+ models available

---

## 7. Social Media Authentication

### Instagram Session ID

Required for deep Instagram lookups without rate limiting.

**Setup:**
1. Login to Instagram in Firefox with a throwaway account
2. Press F12 → **Storage** → **Cookies** → `instagram.com`
3. Copy the `sessionid` value
4. Save on server:
```bash
echo "YOUR_SESSION_ID" > ~/.strikecore/ig_session
chmod 600 ~/.strikecore/ig_session
```

**Usage:**
```bash
ig-auth-lookup USERNAME          # Authenticated lookup
ig-lookup USERNAME               # Unauthenticated (may get 429)
```

**Data returned with auth:** full_name, biography, id, business_email, business_phone_number, contact_phone_number, connected_fb_page, follower/following counts, profile_pic_url, is_private, is_verified, category_name, highlight_reel_count.

### Facebook Token

**Setup:**
1. Go to `https://developers.facebook.com/tools/explorer/`
2. Login and generate a User Access Token
3. Save:
```bash
echo "YOUR_TOKEN" > ~/.strikecore/fb_token
chmod 600 ~/.strikecore/fb_token
```

**Usage:**
```bash
fb-lookup FB_ID_OR_USERNAME      # With token: full Graph API
fb-lookup 1439591776             # Without token: basic mbasic.facebook.com scrape
```

### Session Renewal

Instagram sessions expire or get `challenge_required` errors. To renew:
1. Go to instagram.com in browser, complete any verification
2. Re-copy the new `sessionid` cookie
3. Update: `echo "NEW_SESSION" > ~/.strikecore/ig_session`

---

## 8. OSINT Scripts

### `bin/deep_lookup.py` — Automated Deep OSINT Investigation

9-phase automated investigator that chains multiple tools.

```bash
python3 bin/deep_lookup.py USERNAME [GITHUB_USER]
# Example:
python3 bin/deep_lookup.py luigisav LuigiSavino
```

**Phases:**
1. Instagram API extraction (profile data, bio, links)
2. GitHub commit mining (emails from commit history)
3. Email-to-phone correlation (breach databases, Google recovery)
4. Facebook ID intelligence (breach search, profile scrape)
5. LinkedIn discovery (Google dorking, CrossLinked)
6. Phone hunting (PagineBianche, Registro Imprese, dorking)
7. Messaging apps (Telegram, WhatsApp presence check)
8. Social graph analysis (GitHub followers, context search)
9. Wayback Machine historical data

**Output:** Structured report + JSON for graph generation.

### `bin/contact_finder.py` — Phone & Social Connection Finder

```bash
python3 bin/contact_finder.py "Full Name" "City" [email1] [email2] [fb_id] [ig_user] [gh_user]
# Example:
python3 bin/contact_finder.py "Luigi Savino" "Roma" luigi.savino.95@gmail.com 1439591776 luigisav LuigiSavino
```

**9 phases:** PagineBianche, P.IVA/Registro Imprese, email→phone breach correlation, WhatsApp/Telegram check, Facebook friends, Instagram tagged people + locations, GitHub collaborator network, LinkedIn dorking, Truecaller verification.

### `bin/email_hunter.py` — Email Permutation & Verification

```bash
python3 bin/email_hunter.py FIRSTNAME LASTNAME [USERNAME]
# Example:
python3 bin/email_hunter.py luigi savino luigisav
```

**3 phases:** Gravatar check (instant), EmailRep reputation, Holehe registration check. Generates 100+ email permutations across 12 domains.

### `bin/phone_lookup.py` — Reverse Phone Number Intelligence

```bash
python3 bin/phone_lookup.py PHONE_NUMBER
# Example:
python3 bin/phone_lookup.py +393379669189
```

**6 phases:** PhoneInfoga scan, free API lookups (Veriphone), Google/DuckDuckGo reverse search, social media registration check (ignorant), caller ID web search (Truecaller/Tellows), PagineBianche (Italy).

### `bin/graph_generator.py` — Interactive Intelligence Graph

```bash
# From JSON file:
python3 bin/graph_generator.py output.html --data input.json

# From CLI flags:
python3 bin/graph_generator.py output.html \
  --target "Luigi Savino" \
  --emails "e1@gmail.com,e2@company.com" \
  --usernames "user1,user2" \
  --platforms "Instagram,GitHub" \
  --connections "Person1,Person2" \
  --orgs "Company1,Company2" \
  --locations "Rome,Italy"

# From stdin:
echo '{"target":"Name","emails":[...]}' | python3 bin/graph_generator.py output.html
```

Generates interactive HTML graph with vis.js. Nodes colored by type, edges labeled with relationship type.

---

## 9. Tool Wrappers

Non-interactive wrappers for problematic tools. Located in `~/.local/bin/`.

| Wrapper | Replaces | Purpose |
|---------|----------|---------|
| `ig-lookup USERNAME` | instaloader (429 blocked) | Instagram profile via direct API curl |
| `ig-auth-lookup USERNAME` | — | Authenticated Instagram API (needs session) |
| `fb-lookup FB_ID` | — | Facebook Graph API or mbasic scrape |
| `wa-check PHONE` | wa-osint (interactive menu, hangs) | Phone validation via phonenumbers library |
| `sc-nuclei URL [category]` | nuclei (wrong template path) | Nuclei with auto-detected templates. Categories: exposures, cves, tech, misconfig, osint, all |
| `sc-holehe EMAIL` | holehe (noisy output) | Clean output showing only REGISTERED services |
| `sc-emailrep EMAIL1 [EMAIL2]` | inline python3 -c (error-prone) | EmailRep lookup with structured output |

---

## 10. Investigation System

### Persistent Investigation Store

Each target gets a JSON file in `~/strikecore-data/investigations/` that accumulates all findings across sessions.

```bash
# Open/create investigation
investigate luigisav

# Search stored intelligence
search gmail

# Upload document to RAG
upload /path/to/document.txt
```

**Data stored per target:**
- Identity (names, usernames, DOB, nationality)
- Emails (with sources, confidence, first_seen)
- Phones (with carrier, location, sources)
- Profiles (platform, URL, confidence, notes)
- Organizations (name, role, source)
- Locations, Social graph, Breaches
- Documents (RAG searchable)
- Raw evidence, Phase log, Notes

### Context Injection

When an investigation is active, ALL previously confirmed findings are injected into the AI context at every request with the instruction:

> "DO NOT contradict these. Build upon them."

This prevents the AI from losing or contradicting previous results across sessions.

### Auto-Extraction

After every tool execution, the system automatically extracts and persists:
- Email addresses (filtered: must contain target name/username keywords)
- Phone numbers (filtered: blacklist of test numbers, US prefixes excluded for Italian targets)
- Social profile URLs (filtered: no tool homepages, minimum slug length)

---

## 11. Database

### SQLite Database: `~/strikecore-data/strikecore.db`

Auto-synced from JSON investigation store after every tool execution.

**Tables:**
- `targets` — id, display_name, created_at, updated_at, notes
- `emails` — target_id, email, confidence, sources, notes, first_seen
- `phones` — target_id, phone, confidence, carrier, location, sources
- `profiles` — target_id, platform, url, confidence, notes
- `organizations` — target_id, name, role, source
- `locations` — target_id, name, source, confidence
- `connections` — target_id, name, relation, platform, url
- `evidence` — target_id, tool, output, timestamp
- `documents` — target_id, filename, content, summary
- `phase_log` — target_id, phase, tools_used, findings_count, timestamp

### Web Access

```
http://10.0.0.1:5000/db                    # Database overview
http://10.0.0.1:5000/db/table/emails       # Browse emails table
http://10.0.0.1:5000/db/table/phones       # Browse phones table
http://10.0.0.1:5000/target/ID/manage      # CRUD: delete entries, reset investigation
http://10.0.0.1:5000/api/findings/ID       # JSON API
```

### Direct SQLite Access

```bash
sqlite3 ~/strikecore-data/strikecore.db "SELECT email, confidence FROM emails WHERE target_id='luigi_savino'"
```

---

## 12. Report Builder & Graph Engine

### Report Generation

```bash
# From StrikeCore shell (requires active investigation):
report
```

Generates both Markdown and HTML reports in `~/strikecore-data/reports/`.

**Report sections:**
1. Executive Summary
2. Target Profile (identity table)
3. Digital Footprint (emails, phones, profiles tables)
4. Organizational Intelligence
5. Human Intelligence (social graph)
6. Investigation Timeline
7. Recommendations
8. Raw Evidence (collapsible)

### Graph Engine

Uses **pyvis + networkx** for interactive intelligence graphs.

**Node types and colors:**
- 🔴 Target (red, large)
- 🔵 Email (blue, green border if CONFIRMED)
- 🟣 Phone (purple)
- 🟢 Profile (green)
- 🟠 Organization (orange, diamond shape)
- 🔵 Location (cyan, triangle)
- 🟡 Alias (yellow)
- 🩷 Person/Connection (pink)

**Edge properties:** labeled with relationship type, weighted by confidence, ForceAtlas2 layout.

Output: `~/strikecore-data/reports/graphs/TARGET_graph.html`

---

## 13. Web Dashboard

Flask application accessible at `http://10.0.0.1:5000`.

### Launch

```bash
# From StrikeCore shell:
dashboard

# Or directly:
./strikecore/bin/python3 osint_agent/dashboard/app.py
```

### Routes

| Route | Description |
|-------|-------------|
| `GET /` | List all investigations with finding counts |
| `GET /target/<id>` | Target overview: stats, emails, profiles, graph, report |
| `GET /target/<id>/manage` | CRUD interface: delete individual entries, reset investigation |
| `GET /target/<id>/graph` | Interactive graph (full screen) |
| `GET /target/<id>/report` | HTML formatted report |
| `GET /db` | Database overview with table stats |
| `GET /db/table/<name>` | Browse any table (200 row limit) |
| `GET /api/findings/<id>` | JSON API for all investigation data |
| `GET /api/graph/<id>` | Graph JSON for D3.js rendering |
| `DELETE /delete/<table>/<id>` | Delete a specific row |
| `GET /target/<id>/reset` | Delete ALL data for a target |

### Firewall

Port 5000 is open on the WireGuard VPN interface (`wg0`):
```bash
sudo ufw allow in on wg0 to any port 5000
```

---

## 14. Proxy & Anti-Rate-Limit System

### Tor Proxy

Tor runs as a system service with SOCKS5 on port 9050 and control port on 9051.

**Auto-proxy:** Tools in the rate-limited list are automatically routed through Tor via `proxychains4 -q`:
- holehe, sherlock, maigret, socialscan, social-analyzer, nexfil, blackbird
- h8mail, mosint, ghunt, eyes, toutatis, gallery-dl, curl (for APIs)

**Identity rotation:** On 429 errors, the system:
1. Detects rate-limiting in command output
2. Sends NEWNYM signal to Tor control port (new circuit/IP)
3. Retries the command with new exit IP
4. Max 2 retries per command

### Rate-Limit Detection

Output is scanned for: `429`, `Too Many Requests`, `rate limit`, `throttled`, `CAPTCHA`, `challenge_required`, `login_required`, `Retry-After`.

### Configuration

```bash
# Tor config: /etc/tor/torrc
ControlPort 9051
CookieAuthentication 1

# Proxychains config: /etc/proxychains4.conf
[ProxyList]
socks4 127.0.0.1 9050

# Sudo NOPASSWD for security tools: /etc/sudoers.d/strikecore-tools
atlas ALL=(ALL) NOPASSWD: /usr/bin/nmap, /usr/bin/masscan, /usr/sbin/tcpdump, ...
```

---

## 15. Troubleshoot Agent

`core/troubleshoot_agent.py` — automatically diagnoses tool failures and proposes fixes.

### Error → Fix Mapping

| Error Pattern | Diagnosis | Automatic Action |
|---------------|-----------|-----------------|
| `429 Too Many Requests` | Rate limit | Rotate Tor identity + retry via proxy |
| `challenge_required` | Auth needed | Switch to alternative tool |
| `command not found` | Missing tool | Use equivalent tool (maigret→sherlock) |
| `Permission denied` | Needs root | Add `sudo` prefix |
| `Connection refused` | Network error | Retry via Tor proxy |
| `SSL error` | Certificate issue | Add `-k` flag |

### Tool Fallback Chains

```
instaloader → ig-auth-lookup → ig-lookup → gallery-dl → Wayback Machine
sherlock → maigret → blackbird → nexfil
holehe → mosint → h8mail → emailrep API
socialscan → sherlock → blackbird
```

---

## 16. Dossier Prompts

Template files in `prompts/` directory for structured investigations.

### Template: `prompts/dossier_template.md`

Generic template with `{{PLACEHOLDERS}}` for:
- `{{NOME}}`, `{{COGNOME}}`, `{{USERNAME}}`, `{{CITTA}}`
- `{{AZIENDA}}`, `{{EMAIL}}`, `{{GITHUB_USER}}`
- `{{FB_ID}}`, `{{IG_ID}}`

### Creating a New Dossier Prompt

```bash
cp prompts/dossier_template.md prompts/dossier_mario_rossi.md
# Edit and replace {{placeholders}} with target data
```

### Investigation Phases in Template

0. Pre-analysis (username/email variant generation)
1. Username & social enumeration (sherlock, maigret, holehe, etc.)
2. Professional recon (LinkedIn, GitHub, corporate records)
3. Social media deep dive (Instagram, Facebook, phone OSINT)
4. Infrastructure recon (subfinder, nuclei, shodan)
5. Entity graph generation
6. Final dossier compilation

---

## 17. Sub-Agents

### Available Agents

| Agent | Command | Description |
|-------|---------|-------------|
| `recon` | `agent recon TARGET` | Reconnaissance and information gathering |
| `webapp` | `agent webapp URL` | Web application security testing |
| `bugbounty` | `agent bugbounty TARGET` | Bug bounty hunting workflow |
| `ctf` | `agent ctf TARGET` | CTF challenge solving |
| `cloud` | `agent cloud TARGET` | Cloud infrastructure security |
| `binary` | `agent binary FILE` | Binary analysis and reverse engineering |
| `osint` | `agent osint TARGET` | General OSINT operations |
| `socint` | `agent socint USERNAME` | Social Intelligence (8 techniques) |
| `geoint` | `agent geoint TARGET` | Geospatial Intelligence (9 techniques) |

### SOCINT Techniques

username_hunt, email_intel, phone_intel, social_scrape, breach_check, profile_analysis, face_search, identity_correlation

### GEOINT Techniques

ip_geolocation, image_exif, wifi_geolocation, cell_tower_lookup, domain_geo, network_trace, metadata_extraction, address_osint, infrastructure_map

---

## 18. Installed Tools Inventory

### Total: 117 tools

**SOCINT / Username & Identity (24):**
sherlock, maigret, holehe, h8mail, phoneinfoga, social-analyzer, nexfil, blackbird, socialscan, mosint, ignorant, toutatis, instaloader, gallery-dl, yt-dlp, ghunt, profil3r, findme, mr-holmes, seekr, yesitsme, tookie-osint, crosslinked, nqntnqnqmb

**Email Intelligence (7):**
emailfinder, zehef, eyes, quidam, daprofiler, onionsearch, twayback

**Phone (4):**
phoneinfoga, truecallerjs, owltrack, ghostintel

**Recon / Web (17):**
nmap, masscan, zmap, nikto, sqlmap, ffuf, gobuster, nuclei, subfinder, httpx, katana, naabu, hakrawler, gospider, dnstwist, xurlfind3r, theHarvester

**Web Analysis (7):**
whatweb, wafw00f, photon, metadetective, metagoofil, robofinder, webextractor

**Network / Infrastructure (12):**
shodan, censys, fierce, dnsrecon, whois, dig, testssl.sh, sslscan, sslyze, traceroute, mtr, geoiplookup

**Exploitation (6):**
msfconsole, searchsploit, hydra, medusa, john, hashcat

**Binary / Forensics (6):**
binwalk, r2 (radare2), gdb, strace, ltrace, exiftool

**Cloud / Container (6):**
aws, kubectl, trivy, grype, docker, aircrack-ng

**Frameworks (4):**
spiderfoot, bbot, reconftw, osmedeus

**Utilities (10):**
proxychains4, tor, socat, ncat, curl, wget, jq, mat2, tshark, tcpdump

---

## 19. API Integrations

Manager: `intelligence/api_integrations.py`

### Free APIs (no key needed)

| API | Endpoint | Data |
|-----|----------|------|
| EmailRep | `emailrep.io/EMAIL` | Reputation, profiles, breach status |
| ip-api | `ip-api.com/json/IP` | IP geolocation, ISP, ASN |
| ipinfo | `ipinfo.io/IP/json` | IP geo, company, abuse info |
| crt.sh | `crt.sh/?q=DOMAIN&output=json` | Certificate transparency |
| Wayback | `web.archive.org/web/timemap/json` | Historical snapshots |
| Nominatim | `nominatim.openstreetmap.org/reverse` | Reverse geocoding |
| BGPView | `api.bgpview.io/ip/IP` | ASN/BGP data |
| Veriphone | `api.veriphone.io/v2/verify` | Phone validation |

### Keyed APIs (configure in config.toml)

| API | Config Key | Free Tier |
|-----|-----------|-----------|
| Shodan | `apis.shodan` | 100 queries/month |
| VirusTotal | `apis.virustotal` | 500 req/day |
| AbuseIPDB | `apis.abuseipdb` | 1000 checks/day |
| HaveIBeenPwned | `apis.haveibeenpwned` | $3.50/month |
| Hunter.io | `apis.hunter_io` | 25 req/month |
| SecurityTrails | `apis.securitytrails` | 50 req/month |
| NumVerify | `apis.numverify` | 100 req/month |
| WiGLE | `apis.wigle` | Unlimited |
| Censys | `apis.censys_id` | 250 req/month |
| Google Maps | `apis.google_maps` | $200/month credits |

---

## 20. File Reference

### Data Directories

| Path | Contents |
|------|----------|
| `~/strikecore-data/` | Working directory for all output |
| `~/strikecore-data/investigations/` | JSON investigation stores (per target) |
| `~/strikecore-data/strikecore.db` | SQLite database |
| `~/strikecore-data/reports/` | Generated HTML/MD reports |
| `~/strikecore-data/reports/graphs/` | Intelligence graph HTML files |
| `~/.strikecore/config.toml` | Main configuration |
| `~/.strikecore/ig_session` | Instagram session ID |
| `~/.strikecore/fb_token` | Facebook API token |
| `~/.strikecore/logs/` | Application logs |
| `~/.strikecore/audit/` | Audit trail (JSONL per day) |
| `~/.strikecore/history` | Shell command history |

### Key Source Files

| File | Size | Purpose |
|------|------|---------|
| `cli/shell.py` | 55KB | Interactive shell with all commands |
| `core/nlp_engine.py` | 40KB | AI engine with 9.8KB system prompt |
| `core/tool_registry.py` | 75KB | 150+ tool definitions |
| `core/executor.py` | 21KB | Async command executor |
| `bin/deep_lookup.py` | 29KB | Automated OSINT investigator |
| `bin/contact_finder.py` | 13KB | Phone/connection finder |
| `core/investigation_store.py` | 12KB | Persistent intelligence store |
| `core/report_builder.py` | 10KB | Report generator |
| `core/graph_engine.py` | 6.5KB | Graph builder (pyvis+networkx) |

---

*Document generated for StrikeCore v1.0.0 — 2026-03-22*
*Classification: INTERNAL — Authorized Personnel Only*

---

# CHANGELOG — Updates v1.1.0 (2026-03-25)

## New Core Modules

### `core/fp_filter.py` — False Positive Filter
Numeric FP risk scoring (0-10) for all findings. Score ≥6: auto-reject. Score 4-5: flag. Score 0-3: include.

| Factor | Points |
|--------|--------|
| Single source, no corroboration | +3 |
| Disposable email domain | +3 |
| No cross-source validation | +2 |
| Generic identifier (admin, user123) | +2 |
| Account < 30 days old | +2 |
| No activity / No profile photo | +1 each |
| Corroborated (per source) | -1 |
| Bio matches target | -2 |

### `core/investigation_store.py` — Confidence Scoring Upgrade
`ConfidenceScore` class: 0.0-1.0 numeric alongside legacy CONFIRMED/PROBABLE/UNVERIFIED.

```python
ConfidenceScore.calculate(sources_count=3, corroborated=True)  # → 1.0
ConfidenceScore.to_legacy(0.85)  # → "CONFIRMED"
```

All adders now store `confidence_score` float. Backward compatible.

### `core/photo_forensics.py` — Photo Forensic Analysis
Extracts device intelligence from Instagram-compressed images.

| Technique | Extracts | Works on Instagram? |
|-----------|----------|-------------------|
| FBMD Signature | Facebook Metadata, photo ID | ✅ JPEG only |
| ICC Profile Fingerprint | Device manufacturer (Samsung/Apple) | ✅ WEBP too |
| Resolution Inference | Device from dimensions | ✅ |
| Full EXIF | GPS, camera, datetime | ❌ Stripped by IG |

### `core/geoint_apis.py` — GEOINT API Integrations
Free geospatial APIs: Overpass (OSM), Sentinel Hub (ESA), OpenSky Network, Nominatim, NASA FIRMS.

### `core/ip_logger.py` — IP Tracking & Probing
6 tracking methods:

| Method | Route | Trigger |
|--------|-------|---------|
| Redirect | `/t/{id}` | Click |
| Pixel | `/p/{id}.gif` | Image load |
| Canary | `/c/{id}` | Page visit |
| Link Preview | `/lp/{id}` | Zero-click: chat preview |
| OG Image | `/og/{id}.jpg` | Preview image load |
| **GPS Tracker** | `/gl/{id}` | Browser Geolocation API (**5-30m accuracy**) |

Detects: Instagram in-app browser, Facebook in-app, crawlers vs real users, WebRTC STUN IP leak.

---

## New Scripts

| Script | Command | Purpose |
|--------|---------|---------|
| `bin/health_check.py` | `python3 bin/health_check.py [--quick] [--json]` | Infrastructure health verification |
| `bin/self_audit.py` | `python3 bin/self_audit.py` | Session-end tool performance analysis |
| `bin/ig_photo_mapper.py` | `ig-photo-mapper USERNAME [max]` | Download IG photos with GPS for map |
| `bin/photo_forensics.py` | `photo-forensics --target USERNAME` | FBMD/ICC/resolution forensic analysis |
| `bin/geoint_report.py` | `geoint-report LAT LON` or `geoint-report "City"` | Geospatial intelligence report |

---

## Dashboard Upgrade — C2 Interface

Complete rewrite: glassmorphism design, Tailwind CSS + Alpine.js, JetBrains Mono font, 28+ routes.

### Key Pages

| Page | Route | Features |
|------|-------|----------|
| Command Center | `/` | Stats grid, CPU/RAM/Disk bars, recent investigations |
| Investigations | `/investigations` | All targets with badges and links |
| Target Detail | `/target/<id>` | Glassmorphism cards: emails, phones, profiles, connections, embedded graph |
| Unified GeoMap | `/target/<id>/map` | Photo pins (🔵EXIF 🟢Geotag) + location pins (🟡). Click → popup with thumbnail, location, tagged, caption |
| Sub-Agents | `/agents` | 9 agent cards with status and techniques |
| Infrastructure | `/infrastructure` | CPU/RAM/Disk/Network, 32-tool health, Docker containers, tool performance |
| IP Tracking | `/tunnel` | Tunnel Start/Stop/Restart, bait templates, tracker creation, GPS tracker, cloudflared log |
| Tracker Detail | `/tracking/<id>` | Hit log + geolocation map |
| GEOINT | `/geoint` | Coordinate lookup, geocoding, satellite/flight/maritime links |
| Tasks | `/tasks` | Execute commands from browser, quick-action cards |
| Database | `/db` | SQLite browser |

### IP Tracking — Bait Templates
8 pre-configured Instagram reel URLs for realistic link sharing:
🐈 Cats, 🐶 Dogs, 🍲 Cooking, ✈ Travel, 💪 Gym, 🍜 Food, 💡 Hacks, 🎨 Illusions

### GPS Tracker (`/gl/{id}`)
Instagram-lookalike loading page that uses browser `navigator.geolocation.getCurrentPosition()` for **exact GPS** (5-30m). Shows "Allow Location Access" button styled like Instagram. Redirects to real reel after capture.

---

## Cloudflared Tunnel

Integrated into dashboard at `/tunnel`.

**Dashboard:** Start/Stop/Restart buttons + auto-displayed public HTTPS URL

**Terminal:**
```bash
pgrep -a cloudflared                    # Check status
pkill cloudflared                       # Stop
nohup cloudflared tunnel --url http://localhost:5000 > /tmp/cloudflared.log 2>&1 &  # Start
grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cloudflared.log | tail -1   # Get URL
```

---

## Session Startup & Shutdown

### Startup (main.py)
1. Health check (quick mode) with Rich table
2. Last investigation context displayed
3. Stale investigations (>7 days) flagged

### Shutdown (cli/shell.py)
1. Self-audit runs: tool performance scored
2. `~/.strikecore/tool_performance.json` updated
3. Underperformers flagged

---

## Social Media Authentication

| File | Platform | How to get |
|------|----------|-----------|
| `~/.strikecore/ig_session` | Instagram | Firefox F12 → Storage → Cookies → sessionid |
| `~/.strikecore/fb_token` | Facebook | developers.facebook.com/tools/explorer/ |

Used by: `ig-auth-lookup`, `sc-toutatis`, `ig-social-circle`, `ig-photo-mapper`, `fb-lookup`

---

## WireGuard VPN

| Peer | IP |
|------|----|
| Server | 10.0.0.1 |
| Desktop | 10.0.0.2 |
| Laptop | 10.0.0.3 |
| Phone | 10.0.0.4 |

Phone QR code: `/home/mariello/wg_phone.png`

---

## New Data Directories

| Path | Contents |
|------|----------|
| `~/strikecore-data/photos/{user}/` | Downloaded IG photos + photo_markers.json |
| `~/strikecore-data/photos/{user}/thumbs/` | Thumbnails |
| `~/strikecore-data/photos/{user}/fullsize/` | Full resolution images |
| `~/strikecore-data/ip_logs/` | Tracking hit logs (JSON per tracker) |
| `~/.strikecore/tool_performance.json` | Lifetime tool stats |
| `~/.strikecore/false_positives.log` | Auto-rejected findings log |

---

*Document updated for StrikeCore v1.1.0 — 2026-03-25*
*Classification: INTERNAL — Authorized Personnel Only*
