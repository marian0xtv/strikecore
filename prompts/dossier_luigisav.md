# OSINT AGENT — HUMAN TARGET DOSSIER
> **Versione:** 1.0  
> **Scope:** Ricognizione passiva su target umano  
> **Target ID:** luigisav

---

## ════ INPUT TARGET ════

```
NOME_COMPLETO   : Luigi Savino
ALIAS           : luigisav, LuigiSavino, luxdj95
EMAIL           : luigi.savino.95@gmail.com, luigi.savino@guest.telecomitalia.it, luigi.savino@mail-bip.com, luxdj95@gmail.com
USERNAME        : luigisav
TELEFONO        : null
CITTÀ           : Roma
NAZIONALITÀ     : Italiana
AZIENDA_ATTUALE : Telecom Italia / TIM (contractor)
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
- luigi.savino, luigisavino, l.savino, lsavino, savino.luigi, savinoluigi
- luigisav, luxdj95, luigi_savino, luigi-savino
- luigisav95, luigi95, luigis95
- luigi.savino.95

Varianti email da testare:
- luigi.savino@gmail.com, luigisavino@gmail.com, luigisav@gmail.com
- luigi.savino.95@gmail.com (CONFERMATA), luxdj95@gmail.com (CONFERMATA)
- l.savino@gmail.com, luigi_savino@gmail.com
- luigi.savino@outlook.com, luigi.savino@yahoo.it, luigi.savino@libero.it
- luigi.savino@hotmail.com, luigi.savino@icloud.com, luigi.savino@protonmail.com
- luigi.savino@virgilio.it, luigi.savino@tiscali.it, luigi.savino@tim.it
- luigisav@yahoo.com, luxdj95@yahoo.com, luxdj95@hotmail.com
- luigi.savino@telecomitalia.it, luigi.savino@bip-group.com

### 0.2 Platform Priority
Target è developer ~29 anni, Roma, Italia:
- PRIORITÀ ALTA: LinkedIn, GitHub (confermato), Instagram (confermato), Facebook (confermato ID:1439591776)
- PRIORITÀ MEDIA: Twitter/X, Reddit, Stack Overflow, Telegram, WhatsApp
- PRIORITÀ BASSA: TikTok, Twitch, Discord, Medium, Dev.to
- SPECIFICI IT: PagineBianche, Registro Imprese, Infocamere, Albi professionali

### 0.3 Dati già confermati (NON ricontrollare, costruisci sopra questi)
- Instagram: @luigisav (ID:284908554, Professional account Chef, 1721 followers, 114 posts)
- Facebook: ID 1439591776 (linkato da Instagram bio, nome "Luigi Savino")
- GitHub: LuigiSavino (6 repos, Roma, Python/TypeScript/Shell)
- GitHub alt: luigisav (account vuoto)
- Email CONFERMATA: luigi.savino.95@gmail.com (4 repos GitHub)
- Email CONFERMATA: luigi.savino@guest.telecomitalia.it (repo hays_test)
- Email CONFERMATA: luigi.savino@mail-bip.com (repo soplaya_test)
- Email CONFERMATA: luxdj95@gmail.com (repo LuxBrowser)
- Org CONFERMATA: Telecom Italia/TIM (email guest domain)
- Org CONFERMATA: BIP Consulting (email mail-bip.com)
- Location CONFERMATA: Roma (GitHub profile)
- Nota: Dual identity Chef (Instagram) + Developer (GitHub). Nato circa 1995.

---

## ════ FASE 1 — USERNAME & SOCIAL ENUMERATION ════

### 1.1 Username Sweep
Esegui per le varianti principali NON ancora testate:
```bash
sherlock luigi.savino --print-found --timeout 10
sherlock luxdj95 --print-found --timeout 10
sherlock luigi_savino --print-found --timeout 10
maigret luxdj95 --timeout 8 --no-color
```

Per ogni profilo trovato salva in DB:
- URL, username, stato (attivo/inattivo/privato), bio, foto profilo URL
- Follower count, data creazione, ultimo post

### 1.2 Email Sweep
Esegui su email NON ancora verificate:
```bash
holehe luigi.savino@gmail.com --no-color --no-clear
holehe luigisav@gmail.com --no-color --no-clear
holehe luigi.savino@outlook.com --no-color --no-clear
holehe luigi.savino@yahoo.it --no-color --no-clear
holehe luigi.savino@libero.it --no-color --no-clear
holehe luxdj95@yahoo.com --no-color --no-clear
holehe luxdj95@hotmail.com --no-color --no-clear
h8mail -t luigi.savino.95@gmail.com
h8mail -t luxdj95@gmail.com
h8mail -t luigi.savino@guest.telecomitalia.it
mosint luigi.savino.95@gmail.com
mosint luxdj95@gmail.com
```

---

## ════ FASE 2 — PROFESSIONAL RECON ════

### 2.1 LinkedIn
Google dorks:
```
site:linkedin.com/in "Luigi Savino"
site:linkedin.com/in "Luigi Savino" "Roma"
site:linkedin.com/in "Luigi Savino" "Telecom Italia" OR "TIM" OR "BIP"
"Luigi Savino" "developer" OR "sviluppatore" site:linkedin.com
```

### 2.2 GitHub Deep Mining
```bash
# Commit email mining (già fatto, conferma risultati)
curl -s "https://api.github.com/users/LuigiSavino/events/public" | jq '.[].payload.commits[]?.author.email' | sort -u | grep -v noreply

# Secret leak scan nei repo
for repo in hays_test soplaya_test LuigiSavino LuxBrowser internet_speed_test; do
  curl -s "https://api.github.com/repos/LuigiSavino/$repo/contents" | jq -r '.[].name'
done

# Analisi orari commit per timezone
curl -s "https://api.github.com/repos/LuigiSavino/LuxBrowser/commits?per_page=30" | jq '.[].commit.author.date' | sort

# Follower e following per social graph
curl -s "https://api.github.com/users/LuigiSavino/followers" | jq '.[].login'
curl -s "https://api.github.com/users/LuigiSavino/following" | jq '.[].login'

# Organizzazioni
curl -s "https://api.github.com/users/LuigiSavino/orgs" | jq '.[].login'
```

### 2.3 Corporate & Public Records (Italia)
Google dorks:
```
"Luigi Savino" "Roma" filetype:pdf
"Luigi Savino" "curriculum vitae" OR "cv"
"Luigi Savino" site:registroimprese.it
"Luigi Savino" "partita iva" OR "P.IVA"
"Luigi Savino" "Telecom Italia" OR "TIM"
"Luigi Savino" "BIP" OR "bip-group"
"Luigi Savino" site:slideshare.net OR site:speakerdeck.com
"Luigi Savino" site:researchgate.net OR site:academia.edu
"Luigi Savino" site:stackoverflow.com OR site:dev.to
"Luigi Savino" "chef" "Roma"
```

---

## ════ FASE 3 — SOCIAL MEDIA DEEP DIVE ════

### 3.1 Instagram (dati già noti, approfondisci)
```bash
# API diretta (NO instaloader)
curl -s "https://i.instagram.com/api/v1/users/web_profile_info/?username=luigisav" \
  -H "User-Agent: Instagram 275.0.0.27.98 Android" \
  -H "X-IG-App-ID: 936619743392459" | jq .
```
- Analizza bio per link, email, telefono nascosti
- Nota persone taggate e menzioni ricorrenti

### 3.2 Facebook (ID: 1439591776)
```bash
proxychains4 -q curl -sL "https://mbasic.facebook.com/profile.php?id=1439591776" \
  -H "User-Agent: Mozilla/5.0 (Linux; Android 12)"
```
- Estrai amici visibili, check-in, gruppi pubblici, timeline

### 3.3 Phone OSINT (MULTI-VECTOR — RUN THIS FIRST)
```bash
python3 /home/atlas/argus-intelligence/strikecore/bin/contact_finder.py "Luigi Savino" "Roma" luigi.savino.95@gmail.com luxdj95@gmail.com luigi.savino@guest.telecomitalia.it 1439591776 luigisav LuigiSavino
```

Then supplement:
```bash
truecallerjs -s -e luigi.savino.95@gmail.com --json
truecallerjs -s -e luxdj95@gmail.com --json
wa-osint luigi.savino.95@gmail.com
wa-osint luxdj95@gmail.com
```

Google dorks:
```
"Luigi Savino" "+39" "Roma"
"Luigi Savino" "telefono" OR "cellulare" site:paginebianche.it
"Luigi Savino" "P.IVA" site:registroimprese.it
"Luigi Savino" "chef" "Roma" "contatti" OR "telefono"
"Luigi Savino" "Telecom Italia" "phone" OR "mobile" OR "cell"
```

### 3.4 Phone OSINT Legacy
```bash
# Se trovi un numero, esegui:
python3 /home/atlas/argus-intelligence/strikecore/bin/phone_lookup.py NUMERO

# Google dork per numero
# "Luigi Savino" "+39" OR "339" OR "338" OR "340" OR "347" OR "333" OR "328"
# "Luigi Savino" "telefono" OR "cellulare" OR "tel:"
# "Luigi Savino" "Roma" "chef" "telefono"
# "Luigi Savino" site:paginebianche.it
```

### 3.4 Telegram check
```bash
proxychains4 -q curl -sL "https://t.me/luigisav" -H "User-Agent: Mozilla/5.0" | grep "tgme_page"
proxychains4 -q curl -sL "https://t.me/luxdj95" -H "User-Agent: Mozilla/5.0" | grep "tgme_page"
proxychains4 -q curl -sL "https://t.me/luigisavino" -H "User-Agent: Mozilla/5.0" | grep "tgme_page"
```

### 3.5 Wayback Machine
```bash
curl -s "https://web.archive.org/web/timemap/json?url=instagram.com/luigisav&limit=10" | jq .
curl -s "https://web.archive.org/web/timemap/json?url=github.com/LuigiSavino&limit=10" | jq .
```

### 3.6 Reverse Image (foto profilo Instagram)
```bash
curl -sL "PROFILE_PIC_URL" -o /tmp/luigisav_pic.jpg
exiftool -a -u -g1 /tmp/luigisav_pic.jpg
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
- Colleghi Telecom Italia e BIP identificati

### 4.3 Interest Profiling
- Chef + Developer = dual career
- Musica (luxdj95 alias suggerisce interesse DJ/musica elettronica)
- Tecnologie: Python, TypeScript, Shell, browser development (LuxBrowser)

### 4.4 OPSEC Assessment
- Valuta: username unico vs compartimentato?
- Privacy settings coerenti?
- Dati sensibili esposti involontariamente?
- Email aziendali nei commit Git = OPSEC basso per ambito professionale

---

## ════ FASE 5 — ENTITY GRAPH ════

Genera il grafo con:
```bash
python3 /home/atlas/argus-intelligence/strikecore/bin/graph_generator.py \
  /home/atlas/strikecore-data/reports/graphs/luigisav_full.html \
  --data /tmp/luigisav_graph_data.json
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
  Target         : Luigi Savino
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
  Report HTML    : ~/strikecore-data/reports/luigisav_dossier.html
  Grafo completo : ~/strikecore-data/reports/graphs/luigisav_full.html
  Dashboard      : http://10.0.0.1:5000/target/luigisav
════════════════════════════════════════════
```
