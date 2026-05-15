# OSINT AGENT — HUMAN TARGET DOSSIER
> **Versione:** 1.0  
> **Scope:** Ricognizione passiva su target umano  
> **Target ID:** {{USERNAME}}

---

## ════ INPUT TARGET ════

```
NOME_COMPLETO   : {{NOME}} {{COGNOME}}
ALIAS           : {{USERNAME}}, {{GITHUB_USER}}, {{ALIAS}}
EMAIL           : luigi.savino.95@gmail.com, luigi.savino@guest.telecomitalia.it, luigi.savino@mail-bip.com, {{ALIAS}}@gmail.com
USERNAME        : {{USERNAME}}
TELEFONO        : null
CITTÀ           : {{CITTA}}
NAZIONALITÀ     : Italiana
AZIENDA_ATTUALE : {{AZIENDA}} / TIM (contractor)
RUOLO           : Software Developer (Python/TypeScript/Shell)
CONTESTO        : Indagine OSINT completa - ricostruzione profilo digitale, ricerca contatti (telefono), mappatura connessioni professionali e sociali
```

---

## ════ ISTRUZIONI GENERALI ALL'AGENTE ════

Sei un agente OSINT specializzato in human recon.
Il tuo obiettivo è costruire un dossier completo e strutturato sul target usando esclusivamente fonti pubbliche e tecniche passive.

Regole operative:
- Procedi in autonomia dalla fase 0 alla fase 6 senza interruzioni
- Salva ogni output nel database di persistenza dopo ogni tool eseguito
- Se un tool non è disponibile o fallisce: loga il fallimento, continua con il successivo
- Distingui sempre FATTO (trovato e verificato) da INFERENZA (dedotto)
- Non interrompere mai il flusso per errori non critici
- Al termine di ogni fase: aggiorna il DB e stampa un mini-summary a console
- NON usare instaloader (sempre bloccato 429). Usa curl Instagram API.
- NON installare nulla. Tutti i tool sono già installati.
- Usa proxychains4 -q per tool che richiedono proxy.

---

## ════ FASE 0 — PRE-ANALYSIS ════

### 0.1 Identity Hypothesis
Varianti username da testare:
- luigi.savino, {{USERNAME}}ino, l.savino, lsavino, savino.luigi, savinoluigi
- {{USERNAME}}, {{ALIAS}}, luigi_savino, luigi-savino
- {{USERNAME}}95, luigi95, luigis95
- luigi.savino.95

Varianti email da testare:
- luigi.savino@gmail.com, {{USERNAME}}ino@gmail.com, {{USERNAME}}@gmail.com
- luigi.savino.95@gmail.com (CONFERMATA), {{ALIAS}}@gmail.com (CONFERMATA)
- l.savino@gmail.com, luigi_savino@gmail.com
- luigi.savino@outlook.com, luigi.savino@yahoo.it, luigi.savino@libero.it
- luigi.savino@hotmail.com, luigi.savino@icloud.com, luigi.savino@protonmail.com
- luigi.savino@virgilio.it, luigi.savino@tiscali.it, luigi.savino@tim.it
- {{USERNAME}}@yahoo.com, {{ALIAS}}@yahoo.com, {{ALIAS}}@hotmail.com
- luigi.savino@telecomitalia.it, luigi.savino@bip-group.com

### 0.2 Platform Priority
Target è developer ~29 anni, {{CITTA}}, Italia:
- PRIORITÀ ALTA: LinkedIn, GitHub (confermato), Instagram (confermato), Facebook (confermato ID:{{FB_ID}})
- PRIORITÀ MEDIA: Twitter/X, Reddit, Stack Overflow, Telegram, WhatsApp
- PRIORITÀ BASSA: TikTok, Twitch, Discord, Medium, Dev.to
- SPECIFICI IT: PagineBianche, Registro Imprese, Infocamere, Albi professionali

### 0.3 Dati già confermati (NON ricontrollare, costruisci sopra questi)
- Instagram: @{{USERNAME}} (ID:{{IG_ID}}, Professional account Chef, 1721 followers, 114 posts)
- Facebook: ID {{FB_ID}} (linkato da Instagram bio, nome "{{NOME}} {{COGNOME}}")
- GitHub: {{GITHUB_USER}} (6 repos, {{CITTA}}, Python/TypeScript/Shell)
- GitHub alt: {{USERNAME}} (account vuoto)
- Email CONFERMATA: luigi.savino.95@gmail.com (4 repos GitHub)
- Email CONFERMATA: luigi.savino@guest.telecomitalia.it (repo hays_test)
- Email CONFERMATA: luigi.savino@mail-bip.com (repo soplaya_test)
- Email CONFERMATA: {{ALIAS}}@gmail.com (repo LuxBrowser)
- Org CONFERMATA: {{AZIENDA}}/TIM (email guest domain)
- Org CONFERMATA: BIP Consulting (email mail-bip.com)
- Location CONFERMATA: {{CITTA}} (GitHub profile)
- Nota: Dual identity Chef (Instagram) + Developer (GitHub). Nato circa 1995.

---

## ════ FASE 1 — USERNAME & SOCIAL ENUMERATION ════

### 1.1 Username Sweep
Esegui per le varianti principali NON ancora testate:
```bash
sherlock luigi.savino --print-found --timeout 10
sherlock {{ALIAS}} --print-found --timeout 10
sherlock luigi_savino --print-found --timeout 10
maigret {{ALIAS}} --timeout 8 --no-color
```

Per ogni profilo trovato salva in DB:
- URL, username, stato (attivo/inattivo/privato), bio, foto profilo URL
- Follower count, data creazione, ultimo post

### 1.2 Email Sweep
Esegui su email NON ancora verificate:
```bash
holehe luigi.savino@gmail.com --no-color --no-clear
holehe {{USERNAME}}@gmail.com --no-color --no-clear
holehe luigi.savino@outlook.com --no-color --no-clear
holehe luigi.savino@yahoo.it --no-color --no-clear
holehe luigi.savino@libero.it --no-color --no-clear
holehe {{ALIAS}}@yahoo.com --no-color --no-clear
holehe {{ALIAS}}@hotmail.com --no-color --no-clear
h8mail -t luigi.savino.95@gmail.com
h8mail -t {{ALIAS}}@gmail.com
h8mail -t luigi.savino@guest.telecomitalia.it
mosint luigi.savino.95@gmail.com
mosint {{ALIAS}}@gmail.com
```

---

## ════ FASE 2 — PROFESSIONAL RECON ════

### 2.1 LinkedIn
Google dorks:
```
site:linkedin.com/in "{{NOME}} {{COGNOME}}"
site:linkedin.com/in "{{NOME}} {{COGNOME}}" "{{CITTA}}"
site:linkedin.com/in "{{NOME}} {{COGNOME}}" "{{AZIENDA}}" OR "TIM" OR "BIP"
"{{NOME}} {{COGNOME}}" "developer" OR "sviluppatore" site:linkedin.com
```

### 2.2 GitHub Deep Mining
```bash
# Commit email mining (già fatto, conferma risultati)
curl -s "https://api.github.com/users/{{GITHUB_USER}}/events/public" | jq '.[].payload.commits[]?.author.email' | sort -u | grep -v noreply

# Secret leak scan nei repo
for repo in hays_test soplaya_test {{GITHUB_USER}} LuxBrowser internet_speed_test; do
  curl -s "https://api.github.com/repos/{{GITHUB_USER}}/$repo/contents" | jq -r '.[].name'
done

# Analisi orari commit per timezone
curl -s "https://api.github.com/repos/{{GITHUB_USER}}/LuxBrowser/commits?per_page=30" | jq '.[].commit.author.date' | sort

# Follower e following per social graph
curl -s "https://api.github.com/users/{{GITHUB_USER}}/followers" | jq '.[].login'
curl -s "https://api.github.com/users/{{GITHUB_USER}}/following" | jq '.[].login'

# Organizzazioni
curl -s "https://api.github.com/users/{{GITHUB_USER}}/orgs" | jq '.[].login'
```

### 2.3 Corporate & Public Records (Italia)
Google dorks:
```
"{{NOME}} {{COGNOME}}" "{{CITTA}}" filetype:pdf
"{{NOME}} {{COGNOME}}" "curriculum vitae" OR "cv"
"{{NOME}} {{COGNOME}}" site:registroimprese.it
"{{NOME}} {{COGNOME}}" "partita iva" OR "P.IVA"
"{{NOME}} {{COGNOME}}" "{{AZIENDA}}" OR "TIM"
"{{NOME}} {{COGNOME}}" "BIP" OR "bip-group"
"{{NOME}} {{COGNOME}}" site:slideshare.net OR site:speakerdeck.com
"{{NOME}} {{COGNOME}}" site:researchgate.net OR site:academia.edu
"{{NOME}} {{COGNOME}}" site:stackoverflow.com OR site:dev.to
"{{NOME}} {{COGNOME}}" "chef" "{{CITTA}}"
```

---

## ════ FASE 3 — SOCIAL MEDIA DEEP DIVE ════

### 3.1 Instagram (dati già noti, approfondisci)
```bash
# API diretta (NO instaloader)
curl -s "https://i.instagram.com/api/v1/users/web_profile_info/?username={{USERNAME}}" \
  -H "User-Agent: Instagram 275.0.0.27.98 Android" \
  -H "X-IG-App-ID: 936619743392459" | jq .
```
- Analizza bio per link, email, telefono nascosti
- Nota persone taggate e menzioni ricorrenti

### 3.2 Facebook (ID: {{FB_ID}})
```bash
proxychains4 -q curl -sL "https://mbasic.facebook.com/profile.php?id={{FB_ID}}" \
  -H "User-Agent: Mozilla/5.0 (Linux; Android 12)"
```
- Estrai amici visibili, check-in, gruppi pubblici, timeline

### 3.3 Phone OSINT (MULTI-VECTOR — ALL TOOLS)

#### Step 1: Automated contact finder (run FIRST)
```bash
python3 /home/atlas/argus-intelligence/strikecore/bin/contact_finder.py "{{NOME}} {{COGNOME}}" "{{CITTA}}" {{EMAILS}} {{FB_ID}} {{USERNAME}} {{GITHUB_USER}}
```

#### Step 2: Truecaller lookup
```bash
truecallerjs -s -e {{EMAIL}} --json
truecallerjs -s --phone +39NUMBER --json
```

#### Step 3: Messaging apps
```bash
wa-osint {{EMAIL}}
ghostintel  # multi-probe
owltrack PHONE
```

#### Step 4: Phone-specific tools
```bash
phoneinfoga scan -n "+39NUMBER"
python3 /home/atlas/argus-intelligence/strikecore/bin/phone_lookup.py +39NUMBER
ignorant 39 NUMBER
```

#### Step 5: Google dorks (Italian patterns)
```
"{{NOME}} {{COGNOME}}" "+39" OR "339" OR "338" OR "340" OR "347"
"{{NOME}} {{COGNOME}}" "telefono" OR "cellulare" site:paginebianche.it
"{{NOME}} {{COGNOME}}" "P.IVA" site:registroimprese.it
```

### 3.4 Phone OSINT Legacy
```bash
# Se trovi un numero, esegui:
python3 /home/atlas/argus-intelligence/strikecore/bin/phone_lookup.py NUMERO

# Google dork per numero
# "{{NOME}} {{COGNOME}}" "+39" OR "339" OR "338" OR "340" OR "347" OR "333" OR "328"
# "{{NOME}} {{COGNOME}}" "telefono" OR "cellulare" OR "tel:"
# "{{NOME}} {{COGNOME}}" "{{CITTA}}" "chef" "telefono"
# "{{NOME}} {{COGNOME}}" site:paginebianche.it
```

### 3.4 Telegram check
```bash
proxychains4 -q curl -sL "https://t.me/{{USERNAME}}" -H "User-Agent: Mozilla/5.0" | grep "tgme_page"
proxychains4 -q curl -sL "https://t.me/{{ALIAS}}" -H "User-Agent: Mozilla/5.0" | grep "tgme_page"
proxychains4 -q curl -sL "https://t.me/{{USERNAME}}ino" -H "User-Agent: Mozilla/5.0" | grep "tgme_page"
```

### 3.5 Wayback Machine
```bash
curl -s "https://web.archive.org/web/timemap/json?url=instagram.com/{{USERNAME}}&limit=10" | jq .
curl -s "https://web.archive.org/web/timemap/json?url=github.com/{{GITHUB_USER}}&limit=10" | jq .
```

### 3.5 SOCIAL CONNECTION MAPPING
For each confirmed profile, map the target's connections:

**Instagram**:
```bash
curl -s "https://i.instagram.com/api/v1/users/web_profile_info/?username={{USERNAME}}" -H "User-Agent: Instagram 275.0.0.27.98 Android" -H "X-IG-App-ID: 936619743392459" | jq '.data.user.edge_owner_to_timeline_media.edges[].node.edge_media_to_caption.edges[].node.text' | grep -oP '@[a-zA-Z0-9_.]+'
```

**Facebook**: `proxychains4 -q curl -sL "https://mbasic.facebook.com/profile.php?id={{FB_ID}}&v=friends"`
**GitHub**: `curl -s "https://api.github.com/users/{{GITHUB_USER}}/followers" | jq '.[].login'`

**DaProfiler**: `daprofiler -n "{{NOME}} {{COGNOME}}"`

### 3.6 LOCATION INTELLIGENCE
```bash
# Instagram post geolocations (from API)
# Facebook check-ins (mbasic)
# Google: "{{NOME}} {{COGNOME}}" "via" OR "piazza" "{{CITTA}}" site:eventbrite.com OR site:meetup.com
```

### 3.6 Reverse Image (foto profilo Instagram)
```bash
curl -sL "PROFILE_PIC_URL" -o /tmp/{{USERNAME}}_pic.jpg
exiftool -a -u -g1 /tmp/{{USERNAME}}_pic.jpg
```
Suggerisci URL per:
- TinEye: https://tineye.com/search?url=...
- Yandex: https://yandex.com/images/search?rpt=imageview&url=...
- Google Lens

---

## ════ FASE 4 — BEHAVIORAL ANALYSIS ════

Analizza tutti i dati raccolti e produci:

### 4.1 Temporal Pattern
- Orari commit GitHub → timezone e abitudini lavorative
- Pattern posting Instagram → orari sociali

### 4.2 Social Network Map
- Connessioni GitHub (followers/following)
- Facebook friends (se visibili)
- Colleghi {{AZIENDA}} e BIP identificati

### 4.3 Interest Profiling
- Chef + Developer = dual career
- Musica ({{ALIAS}} alias suggerisce interesse DJ/musica elettronica)
- Tecnologie: Python, TypeScript, Shell, browser development (LuxBrowser)

### 4.4 OPSEC Assessment
- Valuta: username unico vs compartimentato?
- Privacy settings coerenti?
- Dati sensibili esposti involontariamente?
- Email aziendali nei commit Git = OPSEC basso per ambito professionale

---

## ════ FASE 4b — INFRASTRUCTURE RECON ════

```bash
# Domain/IP analysis
subfinder -d {{DOMAIN}}
nuclei -u {{URL}}
naabu -host {{TARGET}}
xurlfind3r -d {{DOMAIN}}
shodan host {{IP}}
censys search {{TARGET}}

# Advanced frameworks (choose one)
# spiderfoot -s {{TARGET}}
# bbot -t {{TARGET}} -f safe
# reconftw -d {{DOMAIN}}
```

## ════ FASE 5 — ENTITY GRAPH ════

Genera il grafo con:
```bash
python3 /home/atlas/argus-intelligence/strikecore/bin/graph_generator.py \
  /home/atlas/strikecore-data/reports/graphs/{{USERNAME}}_full.html \
  --data /tmp/{{USERNAME}}_graph_data.json
```

Oppure usa il graph engine integrato.

---

## ════ FASE 6 — DOSSIER FINALE ════

Genera il report completo:
```bash
# Usa il report builder integrato dentro StrikeCore
# Comando nella shell: report
```

Il dossier deve includere TUTTE le sezioni:
- Executive Summary
- Identity Consolidation (tabella con confidence)
- Professional Profile (cronologia lavorativa, formazione)
- Digital Footprint Map (tutti i profili con stato)
- Breach & Exposure Report
- Behavioral Profile
- Social Network (persone collegate)
- Exposed Assets & Risks
- Contact Vectors (email/telefono con affidabilità)
- Entity Graph (link ai grafi HTML)
- Discovery Timeline
- Recommendations
- Raw Evidence Index

---

## ════ CONFIDENCE SCORING ════

| Score | Significato | Criterio |
|-------|-------------|----------|
| 90-100 | CONFERMATO | 3+ fonti indipendenti |
| 70-89 | PROBABILE | 2 fonti concordanti |
| 50-69 | POSSIBILE | 1 fonte affidabile |
| 30-49 | IPOTESI | Deduzione logica |
| 0-29 | SPECULATIVO | Assunzione non verificata |

---

## ════ CONSOLE OUTPUT ATTESO ════

```
════════════════════════════════════════════
  OSINT DOSSIER COMPLETATO
════════════════════════════════════════════
  Target         : {{NOME}} {{COGNOME}}
  Durata scan    : Xm Xs
  Tool OK/Totale : X/Y
────────────────────────────────────────────
  ENTITÀ TROVATE
  Email          : N
  Username       : N
  Organizzazioni : N
  Persone collegate: N
  Documenti      : N
  Breach         : N
────────────────────────────────────────────
  TOP 5 FINDING
  1. ...
  2. ...
  3. ...
  4. ...
  5. ...
────────────────────────────────────────────
  OUTPUT
  Report HTML    : ~/strikecore-data/reports/{{USERNAME}}_dossier.html
  Grafo completo : ~/strikecore-data/reports/graphs/{{USERNAME}}_full.html
  Dashboard      : http://10.0.0.1:5000/target/{{USERNAME}}
════════════════════════════════════════════
```
