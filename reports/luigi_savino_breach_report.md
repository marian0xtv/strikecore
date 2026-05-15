# Intelligence Report — Luigi Savino
## Breach & Phone Recon — 27 Aprile 2026

### Target
- **Nome**: Luigi Savino
- **IG**: @luigisav (ID: 284908554)
- **FB**: ID 1439591776
- **Email confermate**: luigi.savino.95@gmail.com, luxdj95@gmail.com, luigi.savino@guest.telecomitalia.it, luigi.savino@mail-bip.com
- **Alias**: luxdj95, LuigiSavino
- **Org**: TIM/Telecom Italia (contractor), BIP Consulting
- **Location**: Roma

---

### Breach con PHONE NUMBER confermato (via XposedOrNot)

| Breach | Email | Dati esposti |
|--------|-------|-------------|
| **Instagram (2026-01)** | luigi.savino.95@gmail.com | Email, Username, Nomi, Geo, **Phone** |
| **Twitter-Scraped** | luxdj95@gmail.com | Username, Email, Nomi, Geo, Photo, **Phone** |
| **VerificationsIO** | luxdj95@gmail.com | Email, Nomi, DOB, Gender, Geo, **Phone**, Indirizzi |

### Tutti i breach noti

**luigi.savino.95@gmail.com** (HIBP: 3 breach)
- LuminPDF, PDL, Instagram (2026-01)

**luxdj95@gmail.com** (HIBP: 19 breach, 2 pastes)
- BTSec, RiverCityMedia, ExploitIn, 8tracks, Pemiblanc, Collection1, MyHeritage, VerificationsIO
- Twitter-Scraped, Mathway, Canva, Deezer, DuelingNetwork, Gatehub, BitcoinSecurity

### HudsonRock Stealer Log — CRITICAL

- **Data**: 2 marzo 2022
- **Stealer**: RedLine
- **Computer**: Luigi — Windows 10 Home x64
- **Malware path**: C:\Users\Luigi\Desktop\FileSetups.exe
- **Antivirus**: Windows Defender (non ha bloccato)
- **IP**: 95.239.x.x (Fastweb Italia residenziale)
- **Servizi compromessi**: 14
- **Login parziali**: l\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*@gmail.com, l\*\*\*\*\*\*v
- **Password parziali**: S\*\*\*\*\*\*\*\*\*9, L\*\*\*\*\*\*\*?

### Servizi Holehe confermati

**luigi.savino.95@gmail.com**: Eventbrite, Freelancer, Office365
**luxdj95@gmail.com**: Eventbrite, Firefox, Gravatar, Spotify, Twitter, WordPress, Xvideos

### Connessioni (GitHub)
- Javier Godoy (@gaulatti) — mutual follow
- Alessandro (@alepipe, @alemari7284) — followers
- Vittorio Ciampi (@gianfrizio) — follower
- @liz_leo17 — Instagram tagged

### Profili confermati (Sherlock)
luigisavino trovato su 24 piattaforme: Blogspot, Cults3D, DeviantArt, Disqus, Docker Hub, Flipboard, HackMD, Medium, NitroType, Replit, Reverbnation, Roblox, Scratch, Snapchat, TikTok, Trello, YouTube, Pinterest, Mastodon, FurAffinity

### Status Phone
- **CONFERMATO**: il telefono esiste in almeno 3 breach database
- **NON ESTRATTO**: servono credenziali premium (Dehashed Search o HudsonRock Premium)
- **Vettori esauriti**: dorking, reset oracle (IG/FB/Google), Truecaller, PagineBianche, Telegram, breach free tier

### Prossimi passi
1. HudsonRock Premium — 14 servizi compromessi dal stealer (include probabilmente telefono)
2. Dehashed Search Access — query diretta su Instagram/Twitter/VerificationsIO breach
3. IG Contact Sync — serve account verificato con telefono reale

### File e tool creati in questa sessione
- core/fp_filter.py — FP filter v2 con phonenumbers + scoring avanzato
- core/contact_validator.py — Validatore centralizzato
- core/reset_oracle.py — Password Reset Oracle Chain
- core/number_enumerator.py — IG Contact Sync reverse lookup
- bin/phone_lookup.py — Phone lookup v2 con FP filter
- bin/email_hunter.py — Email hunter v2 con tier system
- bin/contact_finder.py — Contact finder v2 con FP filter
- bin/deep_lookup.py — Patchato con FP filter
- bin/phone_recon.py — Argus orchestrator
- bin/ig_contact_sync.py — IG Contact Sync enumeration
- bin/breach_lookup.py — Dehashed/SnusBase/LeakPeek client
- bin/breach_free.py — Free breach aggregator (10 servizi)
- bin/breach_free_v2.py — Free breach aggregator v2 (completo)
- agents/github_scanner_agent.py — GitHub Scanner sub-agent
- reports/luigi_savino_graph.html — Social graph interattivo (45 nodi, 49 archi)
