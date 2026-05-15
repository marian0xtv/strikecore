#!/usr/bin/env python3
"""
StrikeCore Deep Lookup v2 — Advanced contact discovery.

Focus: Actually finding phone numbers and deep social connections.

Key vectors:
1. Instagram API → full profile + FB ID + business contacts
2. GitHub commit mining → confirmed emails
3. Facebook ID → search in known breach datasets
4. Google account recovery → partial phone reveal
5. Email-to-phone correlation via forgot-password probes
6. LinkedIn discovery from confirmed emails
7. Telegram/WhatsApp presence check
8. Italian registries (Registro Imprese, PagineBianche)
9. Deep social graph from followers/following
10. Breach database correlation for phone numbers
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error

# Add project root for core imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.fp_filter import validate_phone_number, quick_score_phone, quick_score_email, log_rejection

# Improved phone regex
MOBILE_IT_RE = re.compile(r'(?:\+39\s?)?3[0-9]{2}[\s.\-]?\d{3}[\s.\-]?\d{4}')
EXCLUDE_RE = [re.compile(r'\d{11}'), re.compile(r'\d{2}/\d{2}/\d{4}')]

PATH = os.path.expanduser("~/.local/bin") + ":" + os.path.expanduser("~/go/bin") + ":/usr/local/go/bin:" + os.environ.get("PATH", "")
ENV = {**os.environ, "PATH": PATH}

R = {"emails": {}, "phones": {}, "profiles": {}, "names": set(), "locations": set(), 
     "orgs": set(), "social_graph": [], "timeline": [], "devices": set()}

def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=ENV)
        return r.stdout.strip()
    except:
        return ""

def api(url, headers=None):
    try:
        req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read())
    except:
        return None

def dork(query, engine="ddg"):
    """Search via DuckDuckGo HTML and extract all text."""
    encoded = urllib.request.quote(query)
    raw = run(f'proxychains4 -q curl -s "https://html.duckduckgo.com/html/?q={encoded}" -H "User-Agent: Mozilla/5.0" 2>/dev/null', 15)
    return raw

def add_email(email, source, conf="PROBABLE"):
    email = email.lower().strip()
    if not email or "@" not in email or "noreply" in email or "users.noreply" in email:
        return
    is_github = "git:" in source or "github" in source.lower()
    is_breach = "breach" in source.lower() or "h8mail" in source.lower()
    if email not in R["emails"]:
        R["emails"][email] = {"sources": [], "confidence": conf, "from_github": is_github, "from_breach": is_breach}
    R["emails"][email]["sources"].append(source)
    if is_github: R["emails"][email]["from_github"] = True
    if is_breach: R["emails"][email]["from_breach"] = True
    if conf == "CONFIRMED": R["emails"][email]["confidence"] = "CONFIRMED"
    # FP scoring
    target_name = ' '.join(R["names"]) if R["names"] else None
    fp = quick_score_email(email, R["emails"][email]["sources"], target_name,
                           from_github=R["emails"][email].get("from_github", False),
                           from_breach=R["emails"][email].get("from_breach", False))
    R["emails"][email]["fp_score"] = fp["score"]
    if fp["action"] == "reject":
        print(f"    [REJECTED EMAIL] {email} — FP:{fp['score']}/10 [{source}]")
        del R["emails"][email]
        return
    R["emails"][email]["confidence"] = fp["confidence"]

def add_phone(phone, source, conf="PROBABLE"):
    phone = re.sub(r'[^\d+]', '', phone)
    if not phone or len(phone) < 10:
        return
    # Structural validation
    val = validate_phone_number(phone, expected_country="IT")
    if not val["valid"]:
        print(f"    [REJECTED PHONE] {phone} — {val.get('rejection_reason', 'invalid')} [{source}]")
        log_rejection("phone", phone, 10, [val.get('rejection_reason', 'invalid')])
        return
    normalized = val.get("e164", phone)
    if normalized not in R["phones"]:
        R["phones"][normalized] = {"sources": [], "confidence": conf, "type": val.get("number_type", "unknown")}
    R["phones"][normalized]["sources"].append(source)
    # FP scoring
    target_name = ' '.join(R["names"]) if R["names"] else None
    fp = quick_score_phone(normalized, R["phones"][normalized]["sources"], target_name, country="IT")
    R["phones"][normalized]["fp_score"] = fp["score"]
    R["phones"][normalized]["confidence"] = fp["confidence"]
    if fp["action"] == "reject":
        print(f"    [REJECTED PHONE] {normalized} — FP:{fp['score']}/10 [{source}]")
        del R["phones"][normalized]
        return
    if conf == "CONFIRMED": R["phones"][normalized]["confidence"] = "CONFIRMED"

def add_profile(platform, url, conf="CONFIRMED", notes=""):
    R["profiles"][platform] = {"url": url, "confidence": conf, "notes": notes}

def step(n, name):
    print(f"\n{'─'*60}")
    print(f"  PHASE {n}: {name}")
    print(f"{'─'*60}")

# ═══════════════════════════════════════════════════════════
# PHASE 1: Instagram full extraction
# ═══════════════════════════════════════════════════════════
def phase1_instagram(username):
    step(1, "INSTAGRAM INTELLIGENCE")
    
    # Try direct first, then proxy
    data = api(
        f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}",
        {"User-Agent": "Instagram 275.0.0.27.98 Android", "X-IG-App-ID": "936619743392459"}
    )
    if not data or not data.get("data", {}).get("user"):
        raw = run(f'proxychains4 -q curl -s "https://i.instagram.com/api/v1/users/web_profile_info/?username={username}" '
                  f'-H "User-Agent: Instagram 275.0.0.27.98 Android" -H "X-IG-App-ID: 936619743392459"', 20)
        try: data = json.loads(raw)
        except: data = None

    if not data or not data.get("data", {}).get("user"):
        print("  ✘ Instagram API unreachable")
        return {}

    u = data["data"]["user"]
    info = {
        "id": u.get("id", ""),
        "full_name": u.get("full_name", ""),
        "bio": u.get("biography", ""),
        "category": u.get("category_name", ""),
        "is_pro": u.get("is_professional_account", False),
        "followers": u.get("edge_followed_by", {}).get("count", 0),
        "following": u.get("edge_follow", {}).get("count", 0),
        "posts": u.get("edge_owner_to_timeline_media", {}).get("count", 0),
        "pic_url": u.get("profile_pic_url_hd", ""),
        "fb_id": "",
    }

    # Extract Facebook ID from bio link
    fb = u.get("fb_profile_biolink", {})
    if fb and fb.get("url"):
        info["fb_url"] = fb["url"]
        fb_id_match = re.search(r'id=(\d+)', fb["url"])
        if fb_id_match:
            info["fb_id"] = fb_id_match.group(1)
        add_profile("Facebook", fb["url"], "CONFIRMED", f"Linked from Instagram. FB ID: {info.get('fb_id', 'N/A')}")

    # Contact fields
    for field in ["business_email", "public_email"]:
        v = u.get(field)
        if v: add_email(v, "instagram_api", "CONFIRMED")
    for field in ["business_phone_number", "public_phone_number", "contact_phone_number"]:
        v = u.get(field)
        if v: add_phone(v, "instagram_api", "CONFIRMED")

    # Bio parsing
    bio = info["bio"]
    for e in re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', bio):
        add_email(e, "instagram_bio", "CONFIRMED")
    for p in re.findall(r'\+?\d[\d\s.-]{8,}', bio):
        add_phone(p, "instagram_bio", "CONFIRMED")

    if info["full_name"]: R["names"].add(info["full_name"])
    add_profile("Instagram", f"https://instagram.com/{username}", "CONFIRMED",
                f"{info['followers']} followers, {info['posts']} posts, {info['category'] or 'N/A'}")

    # Download profile pic for EXIF
    if info["pic_url"]:
        run(f'curl -sL "{info["pic_url"]}" -o /tmp/target_pic.jpg 2>/dev/null', 10)
        exif = run('exiftool -GPS* -Make -Model -Software /tmp/target_pic.jpg 2>/dev/null', 5)
        if exif and "GPS" in exif:
            print(f"  ✔ EXIF GPS found in profile pic!")
            print(f"    {exif}")
        elif exif:
            for line in exif.strip().split('\n'):
                if 'Make' in line or 'Model' in line:
                    R["devices"].add(line.split(':',1)[1].strip())

    for k, v in info.items():
        if v and k not in ("pic_url",): print(f"  {k}: {v}")

    return info

# ═══════════════════════════════════════════════════════════
# PHASE 2: GitHub commit mining
# ═══════════════════════════════════════════════════════════
def phase2_github(usernames):
    step(2, "GITHUB COMMIT MINING")
    
    for username in usernames:
        ud = api(f"https://api.github.com/users/{username}")
        if not ud or "login" not in ud:
            print(f"  ✘ No GitHub user: {username}")
            continue
        
        print(f"  ✔ {ud.get('name', 'N/A')} | {ud.get('location', 'N/A')} | repos: {ud.get('public_repos', 0)}")
        if ud.get("name"): R["names"].add(ud["name"])
        if ud.get("location"): R["locations"].add(ud["location"])
        if ud.get("email"): add_email(ud["email"], "github_profile", "CONFIRMED")
        if ud.get("company"): R["orgs"].add(ud["company"].strip().lstrip("@"))
        if ud.get("blog"): add_profile("Website", ud["blog"], "PROBABLE")
        add_profile(f"GitHub ({username})", f"https://github.com/{username}", "CONFIRMED", f"{ud.get('public_repos',0)} repos")

        # Mine commits
        repos = api(f"https://api.github.com/users/{username}/repos?per_page=10&sort=pushed") or []
        seen_emails = set()
        for repo in repos[:8]:
            rn = repo.get("full_name", "")
            commits = api(f"https://api.github.com/repos/{rn}/commits?per_page=10") or []
            for c in commits:
                email = c.get("commit", {}).get("author", {}).get("email", "")
                name = c.get("commit", {}).get("author", {}).get("name", "")
                if email and email not in seen_emails:
                    seen_emails.add(email)
                    if "noreply" not in email:
                        add_email(email, f"git:{rn}", "CONFIRMED")
                        print(f"    COMMIT: {email} ({name}) [{rn}]")
                        if name: R["names"].add(name)
            time.sleep(0.3)

        # Orgs
        orgs = api(f"https://api.github.com/users/{username}/orgs") or []
        for o in orgs:
            R["orgs"].add(o.get("login", ""))
            print(f"    ORG: {o.get('login', '')}")

        # Social graph: followers/following
        followers = api(f"https://api.github.com/users/{username}/followers?per_page=10") or []
        for f_user in followers[:5]:
            R["social_graph"].append({"name": f_user.get("login"), "relation": "GitHub follower", "url": f_user.get("html_url")})

        following = api(f"https://api.github.com/users/{username}/following?per_page=10") or []
        for f_user in following[:5]:
            R["social_graph"].append({"name": f_user.get("login"), "relation": "GitHub following", "url": f_user.get("html_url")})

# ═══════════════════════════════════════════════════════════
# PHASE 3: Email → Phone correlation
# ═══════════════════════════════════════════════════════════
def phase3_email_to_phone():
    step(3, "EMAIL → PHONE CORRELATION")
    
    confirmed_emails = [e for e, d in R["emails"].items() if d["confidence"] == "CONFIRMED"]
    if not confirmed_emails:
        print("  ✘ No confirmed emails to correlate")
        return

    for email in confirmed_emails[:5]:
        print(f"\n  Probing: {email}")
        
        # 3a. Google forgot-password (reveals partial phone)
        print(f"    [Google recovery] ", end="", flush=True)
        raw = run(f'proxychains4 -q curl -sL "https://accounts.google.com/signin/v2/challenge/selection?flowName=GlifWebSignIn&Email={email}" '
                  f'-H "User-Agent: Mozilla/5.0" 2>/dev/null | head -c 5000', 15)
        phone_partial = re.findall(r'\*{2,}\s*\d{2,4}', raw)
        if phone_partial:
            print(f"PARTIAL PHONE: {''.join(phone_partial)}")
        else:
            print("no partial revealed")

        # 3b. h8mail breach search
        print(f"    [h8mail breaches] ", end="", flush=True)
        h8out = run(f'h8mail -t {email} 2>&1 | grep -v "^$" | grep -v "\\[\\*\\]" | head -20', 30)
        phones_in_breach = re.findall(r'\+?\d[\d\s]{9,}', h8out)
        for p in phones_in_breach:
            add_phone(p, f"breach:{email}", "PROBABLE")
            print(f"BREACH PHONE: {p}")
        if not phones_in_breach:
            # Check for any leaked data
            passwords = re.findall(r'password\s*[:=]\s*(\S+)', h8out, re.IGNORECASE)
            if passwords:
                print(f"leaked passwords found (not showing)")
            else:
                print("no breach data")
        
        # 3c. EmailRep
        print(f"    [EmailRep] ", end="", flush=True)
        rep = api(f"https://emailrep.io/{email}", {"User-Agent": "StrikeCore/1.0"})
        if rep and rep.get("reputation") != "none":
            details = rep.get("details", {})
            print(f"reputation={rep.get('reputation')}, profiles={details.get('profiles', [])}, "
                  f"data_breach={details.get('data_breach', False)}, "
                  f"malicious_activity={details.get('malicious_activity', False)}")
            if details.get("profiles"):
                for p in details["profiles"]:
                    if p not in R["profiles"]:
                        add_profile(p.title(), f"(discovered via emailrep for {email})", "PROBABLE", f"Email: {email}")
                        print(f"      NEW PROFILE: {p}")
        else:
            print("no data")

        time.sleep(1)

# ═══════════════════════════════════════════════════════════
# PHASE 4: Facebook ID intelligence
# ═══════════════════════════════════════════════════════════
def phase4_facebook(fb_id, name):
    step(4, "FACEBOOK ID INTELLIGENCE")
    
    if not fb_id:
        print("  ✘ No Facebook ID available")
        return

    print(f"  Facebook ID: {fb_id}")
    
    # 4a. Search breach databases for this FB ID
    print(f"  [Breach DB search] ", end="", flush=True)
    raw = dork(f'"{fb_id}" "phone" OR "telefono" OR "+39" filetype:txt OR filetype:csv')
    phones = re.findall(r'\+?39\d{9,10}|\+?\d{11,13}', raw)
    for p in phones:
        add_phone(p, f"facebook_breach:{fb_id}", "PROBABLE")
        print(f"PHONE: {p}")
    if not phones:
        print("no direct hit")

    # 4b. Facebook profile page scraping
    print(f"  [Facebook profile] ", end="", flush=True)
    raw = run(f'proxychains4 -q curl -sL "https://mbasic.facebook.com/profile.php?id={fb_id}" '
              f'-H "User-Agent: Mozilla/5.0 (Linux; Android 12)" 2>/dev/null | head -c 10000', 15)
    
    # Extract name from title
    title = re.search(r'<title>([^<]+)</title>', raw)
    if title and title.group(1) not in ("Facebook", "Log in", "Aanmelden"):
        fb_name = title.group(1).strip()
        if "Facebook" not in fb_name and "log" not in fb_name.lower():
            R["names"].add(fb_name)
            print(f"NAME: {fb_name}")
    else:
        print("page requires login")

    # 4c. DuckDuckGo search for FB profile data
    print(f"  [Search engine] ", end="", flush=True)
    if name:
        raw = dork(f'site:facebook.com "{name}" "{fb_id}" OR "phone" OR "email" OR "telefono"')
        phones = re.findall(r'\+?39\d{9,10}', raw)
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', raw)
        for p in phones: add_phone(p, "facebook_search", "PROBABLE"); print(f"PHONE: {p}")
        for e in emails: 
            if any(n in e.lower() for n in name.lower().split()):
                add_email(e, "facebook_search", "PROBABLE"); print(f"EMAIL: {e}")
        if not phones and not emails:
            print("no contact data found")
    else:
        print("skipped (no name)")

# ═══════════════════════════════════════════════════════════
# PHASE 5: LinkedIn discovery
# ═══════════════════════════════════════════════════════════
def phase5_linkedin(name, emails):
    step(5, "LINKEDIN DISCOVERY")
    
    if not name:
        print("  ✘ No name for LinkedIn search")
        return
    
    # Search by name
    raw = dork(f'site:linkedin.com/in "{name}"')
    linkedin_urls = re.findall(r'linkedin\.com/in/([a-zA-Z0-9_-]+)', raw)
    
    if linkedin_urls:
        for slug in list(set(linkedin_urls))[:3]:
            url = f"https://linkedin.com/in/{slug}"
            add_profile("LinkedIn", url, "PROBABLE", f"Search: '{name}'")
            print(f"  ✔ LinkedIn: {url}")
    else:
        # Try with email
        for email in list(emails.keys())[:3]:
            raw = dork(f'site:linkedin.com "{email}"')
            urls = re.findall(r'linkedin\.com/in/([a-zA-Z0-9_-]+)', raw)
            for slug in urls[:2]:
                url = f"https://linkedin.com/in/{slug}"
                add_profile("LinkedIn", url, "PROBABLE", f"Email: {email}")
                print(f"  ✔ LinkedIn: {url}")
            time.sleep(1)
    
    if not linkedin_urls:
        # Try crosslinked
        parts = name.split()
        if len(parts) >= 2:
            for org in list(R["orgs"])[:2]:
                print(f"  [CrossLinked] searching {org}...")
                raw = run(f'crosslinked -f "{{first}}.{{last}}@{org.lower()}.com" "{org}" 2>&1 | head -20', 30)
                if name.lower().split()[1] in raw.lower():
                    print(f"    Found mention in {org}")

# ═══════════════════════════════════════════════════════════
# PHASE 6: Phone discovery via multiple vectors  
# ═══════════════════════════════════════════════════════════
def phase6_phone_hunt(name, username):
    step(6, "PHONE NUMBER DISCOVERY")
    
    if not name:
        print("  ✘ No name available")
        return

    first = name.split()[0] if name else ""
    last = name.split()[-1] if name and " " in name else ""
    
    # 6a. PagineBianche (Italy)
    if last:
        print(f"  [PagineBianche] ", end="", flush=True)
        raw = run(f'proxychains4 -q curl -sL "https://www.paginebianche.it/ricerca?qs={first}+{last}&dession=true" '
                  f'-H "User-Agent: Mozilla/5.0" 2>/dev/null', 15)
        phones_pb = re.findall(r'(?:tel|phone|href="tel:)[\s:]*(\+?[\d\s-]{10,})', raw)
        names_pb = re.findall(r'vcard-nome[^>]*>([^<]+)', raw)
        for p in phones_pb:
            add_phone(p, "paginebianche", "PROBABLE")
            print(f"PHONE: {p.strip()}")
        for n in names_pb[:3]:
            print(f"  NAME: {n.strip()}")
        if not phones_pb: print("no results")
    
    # 6b. Infocamere / Registro Imprese (for professionals)
    print(f"  [Registro Imprese] ", end="", flush=True)
    raw = dork(f'site:registroimprese.it OR site:infoimprese.it "{name}"')
    piva = re.findall(r'\b\d{11}\b', raw)
    if piva:
        print(f"P.IVA candidates: {', '.join(piva[:3])}")
        for p in piva[:2]:
            raw2 = dork(f'"{p}" "telefono" OR "phone" OR "+39"')
            phones_ri = re.findall(r'\+?39[\s]?\d{3}[\s.-]?\d{6,7}', raw2)
            for ph in phones_ri:
                add_phone(ph, f"registro_imprese:PIVA_{p}", "PROBABLE")
                print(f"    PHONE via P.IVA: {ph}")
    else:
        print("no P.IVA found")
    
    # 6c. Truecaller/Tellows/Chi-chiama reverse search (if we have any phone leads)
    # 6d. Google dork for phone numbers
    print(f"  [Google dork phone] ", end="", flush=True)
    queries = [
        f'"{name}" "+39" OR "339" OR "338" OR "340" OR "347" OR "333" OR "328" OR "320"',
        f'"{name}" "telefono" OR "cellulare" OR "tel:" OR "phone"',
        f'"{username}" "phone" OR "+39" OR "whatsapp" OR "telegram"',
    ]
    for q in queries:
        raw = dork(q)
        phones = re.findall(r'\+?39[\s.-]?3\d{2}[\s.-]?\d{3}[\s.-]?\d{4}', raw)
        phones += re.findall(r'3[0-9]{2}[\s.-]?\d{3}[\s.-]?\d{4}', raw)
        for p in phones:
            clean = re.sub(r'[\s.-]', '', p)
            if len(clean) >= 10:
                add_phone(clean, "google_dork", "UNVERIFIED")
                print(f"PHONE: {p}")
        time.sleep(2)
    if not R["phones"]:
        print("no numbers found")

# ═══════════════════════════════════════════════════════════
# PHASE 7: Telegram/WhatsApp/Signal check
# ═══════════════════════════════════════════════════════════
def phase7_messaging(username, emails):
    step(7, "MESSAGING APPS CHECK")
    
    # Telegram username check
    print(f"  [Telegram] @{username}: ", end="", flush=True)
    raw = run(f'proxychains4 -q curl -sL "https://t.me/{username}" -H "User-Agent: Mozilla/5.0" 2>/dev/null | head -c 3000', 10)
    if "tgme_page_title" in raw or "tgme_page_description" in raw:
        tg_name = re.search(r'tgme_page_title[^>]*>([^<]+)', raw)
        add_profile("Telegram", f"https://t.me/{username}", "PROBABLE", tg_name.group(1) if tg_name else "")
        print(f"FOUND! {tg_name.group(1) if tg_name else ''}")
    else:
        print("not found")

    # Check other username variations
    for alt in [username.replace("_", ""), username + "1", username.replace("hhh", "h")]:
        if alt != username:
            raw = run(f'proxychains4 -q curl -sL "https://t.me/{alt}" -H "User-Agent: Mozilla/5.0" 2>/dev/null | head -c 3000', 10)
            if "tgme_page_title" in raw:
                tg_name = re.search(r'tgme_page_title[^>]*>([^<]+)', raw)
                add_profile("Telegram", f"https://t.me/{alt}", "PROBABLE", tg_name.group(1) if tg_name else "")
                print(f"  [Telegram] @{alt}: FOUND!")

# ═══════════════════════════════════════════════════════════
# PHASE 8: Deep social connections
# ═══════════════════════════════════════════════════════════
def phase8_social_graph(username, name):
    step(8, "SOCIAL GRAPH ANALYSIS")
    
    # Search for the person in various contexts
    if name:
        contexts = [
            (f'"{name}" "chef" OR "ristorante" OR "cucina"', "Professional network"),
            (f'"{name}" "Roma" "developer" OR "sviluppatore" OR "programmer"', "Tech network"),
            (f'"{name}" "linkedin" OR "github" OR "twitter"', "Cross-platform"),
        ]
        for query, context in contexts:
            raw = dork(query)
            # Extract associated names
            names = re.findall(r'(?:con|with|and|e)\s+([A-Z][a-z]+ [A-Z][a-z]+)', raw)
            for n in names[:3]:
                if n.lower() != name.lower():
                    R["social_graph"].append({"name": n, "relation": context})
                    print(f"  CONNECTION: {n} ({context})")
            time.sleep(2)

# ═══════════════════════════════════════════════════════════
# PHASE 9: Wayback Machine historical data
# ═══════════════════════════════════════════════════════════
def phase9_wayback(username, emails):
    step(9, "HISTORICAL DATA (Wayback Machine)")
    
    urls_to_check = [
        f"https://www.instagram.com/{username}/",
        f"https://github.com/{username}",
    ]
    
    for url in urls_to_check:
        print(f"  [Wayback] {url}: ", end="", flush=True)
        data = api(f"https://web.archive.org/web/timemap/json?url={url}&limit=5&output=json")
        if data and len(data) > 1:
            print(f"{len(data)-1} snapshots")
            for snapshot in data[1:3]:  # Check first 2 snapshots
                ts = snapshot[1] if len(snapshot) > 1 else ""
                wb_url = f"https://web.archive.org/web/{ts}/{url}"
                raw = run(f'curl -sL "{wb_url}" -H "User-Agent: Mozilla/5.0" 2>/dev/null | head -c 10000', 15)
                # Look for emails/phones in old versions
                old_emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', raw)
                old_phones = re.findall(r'\+?\d[\d\s.-]{9,}', raw)
                for e in old_emails:
                    if "noreply" not in e and "example" not in e:
                        add_email(e, f"wayback:{ts}", "PROBABLE")
                        print(f"    OLD EMAIL ({ts}): {e}")
                for p in old_phones:
                    if len(re.sub(r'\D', '', p)) >= 10:
                        add_phone(p, f"wayback:{ts}", "UNVERIFIED")
                        print(f"    OLD PHONE ({ts}): {p}")
                time.sleep(1)
        else:
            print("no snapshots")

# ═══════════════════════════════════════════════════════════
# FINAL: Generate dossier + graph data
# ═══════════════════════════════════════════════════════════
def compile_dossier(ig_info, username):
    print(f"\n{'═'*70}")
    print(f"  DOSSIER: {' / '.join(R['names']) or username}")
    print(f"{'═'*70}")
    
    print(f"\n  IDENTITÀ")
    print(f"    Nomi: {', '.join(R['names']) or 'N/A'}")
    print(f"    Username: {username}")
    print(f"    Locations: {', '.join(R['locations']) or 'N/A'}")
    print(f"    Organizations: {', '.join(R['orgs']) or 'N/A'}")
    if R["devices"]:
        print(f"    Devices: {', '.join(R['devices'])}")
    
    print(f"\n  EMAIL ({len(R['emails'])})")
    for email, d in sorted(R["emails"].items(), key=lambda x: (0 if x[1]["confidence"]=="CONFIRMED" else 1)):
        sources = ', '.join(set(d["sources"]))
        print(f"    [{d['confidence']}] {email}")
        print(f"             via: {sources}")
    
    print(f"\n  TELEFONO ({len(R['phones'])})")
    if R["phones"]:
        for phone, d in R["phones"].items():
            sources = ', '.join(set(d["sources"]))
            print(f"    [{d['confidence']}] {phone}")
            print(f"             via: {sources}")
    else:
        print(f"    Nessun numero trovato")
    
    print(f"\n  PROFILI ({len(R['profiles'])})")
    for platform, d in R["profiles"].items():
        print(f"    [{d['confidence']}] {platform}: {d['url']}")
        if d["notes"]: print(f"             {d['notes']}")
    
    print(f"\n  SOCIAL GRAPH ({len(R['social_graph'])})")
    for conn in R["social_graph"][:10]:
        print(f"    {conn['name']} — {conn['relation']}")
    
    # Generate graph JSON
    graph_data = {
        "target": ' / '.join(R['names']) or username,
        "aliases": list(set([username] + [u for u in [ig_info.get("id", "")] if u])),
        "emails": [{"email": e, "source": ', '.join(set(d["sources"])), "confidence": d["confidence"]} 
                   for e, d in R["emails"].items()],
        "phones": [{"number": p, "carrier": ', '.join(set(d["sources"]))} for p, d in R["phones"].items()],
        "profiles": [{"platform": p, "url": d["url"]} for p, d in R["profiles"].items()],
        "organizations": [{"name": o, "role": ""} for o in R["orgs"]],
        "locations": list(R["locations"]),
        "connections": [{"name": c["name"], "relation": c["relation"]} for c in R["social_graph"][:15]],
    }
    
    graph_json_path = "/tmp/dossier_graph_data.json"
    with open(graph_json_path, 'w') as f:
        json.dump(graph_data, f, indent=2)
    
    target_slug = username.replace(" ", "_")
    graph_html = f"/home/atlas/strikecore-data/{target_slug}_graph.html"
    
    # Generate graph
    graph_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graph_generator.py")
    if os.path.exists(graph_script):
        run(f'python3 {graph_script} {graph_html} --data {graph_json_path}', 10)
        print(f"\n  GRAPH: {graph_html}")
    
    print(f"\n{'═'*70}")

# ═══════════════════════════════════════════════════════════
def main():
    if len(sys.argv) < 2:
        print("Usage: deep_lookup_v2.py USERNAME [GITHUB_USER1] [GITHUB_USER2]")
        sys.exit(1)

    username = sys.argv[1]
    github_users = sys.argv[2:] if len(sys.argv) > 2 else [username]

    print(f"╔══════════════════════════════════════════════════════╗")
    print(f"║  StrikeCore Deep Lookup v2 — {username:<25}║")
    print(f"║  {time.strftime('%Y-%m-%d %H:%M:%S'):<52}║")
    print(f"╚══════════════════════════════════════════════════════╝")

    ig_info = phase1_instagram(username)
    name = ig_info.get("full_name", "") if ig_info else ""
    fb_id = ig_info.get("fb_id", "") if ig_info else ""

    phase2_github(github_users)
    phase3_email_to_phone()
    phase4_facebook(fb_id, name)
    phase5_linkedin(name, R["emails"])
    phase6_phone_hunt(name, username)
    phase7_messaging(username, R["emails"])
    phase8_social_graph(username, name)
    phase9_wayback(username, list(R["emails"].keys()))
    compile_dossier(ig_info or {}, username)

if __name__ == "__main__":
    main()
