#!/usr/bin/env python3
"""
StrikeCore Contact Finder v2 — Find phone numbers and map social connections.
Now with integrated fp_filter validation on all phone/email extractions.

Multi-vector approach:
1. Name + City -> PagineBianche, Registro Imprese, Google
2. Email -> Google account recovery partial phone reveal
3. Email -> WhatsApp/Telegram presence check  
4. Facebook ID -> friend list + public phone
5. Instagram -> tagged people -> their public contacts
6. GitHub -> collaborators -> their emails
7. LinkedIn -> company colleagues
8. Truecaller reverse lookup
9. Breach databases for phone numbers
"""
import hashlib, json, os, re, subprocess, sys, time, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.fp_filter import validate_phone_number, quick_score_phone, quick_score_email, log_rejection

PATH = os.path.expanduser("~/.local/bin") + ":" + os.path.expanduser("~/go/bin") + ":/usr/local/go/bin:/usr/local/bin:" + os.environ.get("PATH", "")
ENV = {**os.environ, "PATH": PATH}

# Improved phone regex patterns
MOBILE_IT_RE = re.compile(r'(?:\+39\s?)?3[0-9]{2}[\s.\-]?\d{3}[\s.\-]?\d{4}')
FIXED_IT_RE = re.compile(r'(?:\+39\s?)?0[0-9]{1,3}[\s.\-]?\d{6,8}')
TEL_HREF_RE = re.compile(r'(?:tel|phone|href="tel:)[:\s"]*([+\d\s\-]{10,})')

# Anti-FP exclusion patterns
EXCLUDE_RE = [
    re.compile(r'\b\d{11}\b'),         # P.IVA
    re.compile(r'\d{2}/\d{2}/\d{4}'),  # Dates
    re.compile(r'\d{4}-\d{2}-\d{2}'),  # ISO dates
]


def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=ENV)
        return r.stdout.strip()
    except: return ""

def api(url, headers=None):
    try:
        req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read())
    except: return None

def dork(query):
    encoded = urllib.request.quote(query)
    return run(f'proxychains4 -q curl -s "https://html.duckduckgo.com/html/?q={encoded}" -H "User-Agent: Mozilla/5.0" 2>/dev/null', 15)


# ── Validated storage ──
phones = {}
connections = []
locations = []
target_name_global = ""

def add_phone(number, source, confidence="PROBABLE"):
    """Add phone only if it passes structural validation."""
    number = re.sub(r'[\s\-\(\)\.]', '', number)
    if len(number) < 10:
        return
    
    # Structural validation via phonenumbers
    val = validate_phone_number(number, expected_country="IT")
    if not val["valid"]:
        print(f"    [REJECTED] {number} — {val.get('rejection_reason', 'invalid')} [{source}]")
        log_rejection("phone", number, 10, [val.get('rejection_reason', 'invalid')])
        return
    
    # FP scoring
    normalized = val.get("e164", number)
    if normalized not in phones:
        phones[normalized] = {"sources": [], "confidence": confidence, "type": val.get("number_type", "unknown")}
    phones[normalized]["sources"].append(source)
    
    # Score with accumulated sources
    fp = quick_score_phone(normalized, phones[normalized]["sources"], target_name_global, country="IT")
    phones[normalized]["confidence"] = fp["confidence"]
    phones[normalized]["fp_score"] = fp["score"]
    
    if fp["action"] == "reject":
        print(f"    [REJECTED] {normalized} — FP score {fp['score']}/10 [{source}]")
        del phones[normalized]
        return
    
    print(f"    [{fp['confidence']}] PHONE: {normalized} [{source}] (type: {val.get('number_type', '?')})")

def add_conn(name, relation, platform="", contact=""):
    connections.append({"name": name, "relation": relation, "platform": platform, "contact": contact})
    if contact:
        print(f"    CONNECTION: {name} ({relation}) — {contact}")
    else:
        print(f"    CONNECTION: {name} ({relation})")

def extract_phones_from_html(html, source_label):
    """Extract and validate phones from HTML content."""
    # Remove date/ID patterns first
    clean = html
    for exc in EXCLUDE_RE:
        clean = exc.sub('', clean)
    
    # Mobile IT
    for m in MOBILE_IT_RE.findall(clean):
        add_phone(m.strip(), source_label)
    
    # Tel href patterns
    for m in TEL_HREF_RE.findall(clean):
        add_phone(m.strip(), source_label)

def step(n, title):
    print(f"\n{'='*55}")
    print(f"  {n}. {title}")
    print(f"{'='*55}")

def main():
    global target_name_global
    
    if len(sys.argv) < 3:
        print("Usage: contact_finder.py 'Full Name' 'City' [email1] [email2] [fb_id] [ig_user] [gh_user]")
        print("Example: contact_finder.py 'Luigi Savino' 'Roma' luigi.savino.95@gmail.com 1439591776 luigisav LuigiSavino")
        sys.exit(1)
    
    name = sys.argv[1]
    city = sys.argv[2]
    target_name_global = name
    emails = [a for a in sys.argv[3:] if "@" in a]
    fb_id = next((a for a in sys.argv[3:] if a.isdigit() and len(a) > 5), "")
    ig_user = next((a for a in sys.argv[3:] if not "@" in a and not a.isdigit() and len(a) < 30), "")
    gh_user = sys.argv[-1] if len(sys.argv) > 6 else ""
    
    first = name.split()[0]
    last = name.split()[-1] if " " in name else ""
    
    print(f"[*] StrikeCore Contact Finder v2")
    print(f"[*] Target: {name} ({city})")
    print(f"[*] Emails: {', '.join(emails) or 'none'}")
    print(f"[*] FB ID: {fb_id or 'none'} | IG: {ig_user or 'none'} | GH: {gh_user or 'none'}")
    print(f"[*] FP Filter: ACTIVE (phonenumbers + scoring)")

    # ── 1. PagineBianche (Italian phone directory) ──
    step(1, "PAGINE BIANCHE + DIRECTORIES")
    for query in [f"{first}+{last}+{city}", f"{last}+{first}+{city}"]:
        raw = run(f'proxychains4 -q curl -sL "https://www.paginebianche.it/ricerca?qs={query}&dession=true" -H "User-Agent: Mozilla/5.0" 2>/dev/null', 15)
        extract_phones_from_html(raw, "paginebianche")
        names_found = re.findall(r'vcard-nome[^>]*>([^<]+)', raw)
        for n in names_found[:3]:
            if last.lower() in n.lower():
                print(f"    MATCH: {n.strip()}")
        time.sleep(2)
    
    # Italian number format dork
    raw = dork(f'"{name}" "{city}" "telefono" OR "tel:" OR "cellulare" OR "cell:"')
    extract_phones_from_html(raw, "google_dork_name")
    raw = dork(f'"{name}" "+39"')
    extract_phones_from_html(raw, "google_dork_+39")
    time.sleep(2)

    # ── 2. Registro Imprese / P.IVA ──
    step(2, "REGISTRO IMPRESE + P.IVA")
    raw = dork(f'"{name}" "partita iva" OR "P.IVA" OR "CF:" OR site:registroimprese.it')
    pivas = re.findall(r'\b\d{11}\b', raw)
    for piva in pivas[:3]:
        print(f"    P.IVA candidate: {piva}")
        raw2 = dork(f'"{piva}" "telefono" OR "tel" OR "+39" OR "fax"')
        extract_phones_from_html(raw2, f"piva:{piva}")
        time.sleep(2)

    # ── 3. Email -> Phone via breach + recovery ──
    step(3, "EMAIL -> PHONE CORRELATION")
    for email in emails[:4]:
        print(f"  Checking: {email}")
        raw = run(f'h8mail -t {email} 2>&1', 30)
        for p in re.findall(r'(?:\+?\d[\d\s-]{9,})', raw):
            clean = re.sub(r'\D', '', p)
            if 10 <= len(clean) <= 13:
                add_phone(p.strip(), f"h8mail_breach:{email}")
        
        raw = run(f'truecallerjs -s -e {email} --json 2>/dev/null', 10)
        if raw and "phones" in raw:
            try:
                data = json.loads(raw)
                for entry in data.get("data", []):
                    for ph in entry.get("phones", []):
                        add_phone(str(ph.get("e164Format", "")), f"truecaller:{email}")
            except: pass
        time.sleep(1)

    # ── 4. WhatsApp + Telegram check ──
    step(4, "MESSAGING APPS")
    if ig_user:
        for variant in [ig_user, ig_user.replace("_", ""), first.lower() + last.lower()]:
            raw = run(f'proxychains4 -q curl -sL "https://t.me/{variant}" -H "User-Agent: Mozilla/5.0" 2>/dev/null | head -c 3000', 10)
            if "tgme_page_title" in raw:
                tg_name = re.search(r'tgme_page_title[^>]*>([^<]+)', raw)
                n = tg_name.group(1).strip() if tg_name else variant
                add_conn(n, "Telegram account", "Telegram", f"@{variant}")
            time.sleep(1)
    
    if emails:
        raw = run(f'wa-osint {emails[0]} 2>/dev/null | head -20', 15)
        if raw and "phone" in raw.lower():
            for p in re.findall(r'\+?\d[\d\s-]{9,}', raw):
                add_phone(p.strip(), "whatsapp_osint")

    # ── 5. Facebook connections ──
    step(5, "FACEBOOK SOCIAL GRAPH")
    if fb_id:
        raw = run(f'proxychains4 -q curl -sL "https://mbasic.facebook.com/profile.php?id={fb_id}&v=friends" -H "User-Agent: Mozilla/5.0 (Linux; Android 12)" 2>/dev/null | head -c 15000', 15)
        friend_names = re.findall(r'<a[^>]*href="/([^"?]+)\?[^"]*"[^>]*>([^<]{3,30})</a>', raw)
        for slug, fname in friend_names[:10]:
            if fname and not any(x in fname.lower() for x in ["photo", "video", "like", "comment", "share", "facebook"]):
                add_conn(fname.strip(), "Facebook friend", "Facebook", f"fb.com/{slug}")
        
        raw = run(f'proxychains4 -q curl -sL "https://mbasic.facebook.com/profile.php?id={fb_id}&v=places" -H "User-Agent: Mozilla/5.0 (Linux; Android 12)" 2>/dev/null | head -c 10000', 15)
        places = re.findall(r'(?:checked in|was at|visited)\s+(?:at\s+)?([^<.]{3,40})', raw, re.IGNORECASE)
        for place in places[:5]:
            locations.append({"name": place.strip(), "source": "facebook_checkin"})
            print(f"    LOCATION: {place.strip()}")

    # ── 6. Instagram connections ──
    step(6, "INSTAGRAM SOCIAL GRAPH")
    if ig_user:
        data = api(
            f"https://i.instagram.com/api/v1/users/web_profile_info/?username={ig_user}",
            {"User-Agent": "Instagram 275.0.0.27.98 Android", "X-IG-App-ID": "936619743392459"}
        )
        if data and data.get("data", {}).get("user"):
            user = data["data"]["user"]
            bio = user.get("biography", "")
            mentions = re.findall(r'@([a-zA-Z0-9_.]+)', bio)
            for m in mentions:
                add_conn(m, "Instagram mention (bio)", "Instagram", f"@{m}")
            for link in user.get("bio_links", []):
                url = link.get("url", "")
                if url:
                    print(f"    BIO LINK: {url}")
            edge_tag = user.get("edge_owner_to_timeline_media", {})
            if edge_tag:
                for node in edge_tag.get("edges", [])[:5]:
                    caption = node.get("node", {}).get("edge_media_to_caption", {}).get("edges", [])
                    if caption:
                        text = caption[0].get("node", {}).get("text", "")
                        tagged = re.findall(r'@([a-zA-Z0-9_.]+)', text)
                        for t in tagged:
                            add_conn(t, "Instagram tagged", "Instagram", f"@{t}")
                    loc = node.get("node", {}).get("location")
                    if loc:
                        locations.append({"name": loc.get("name", ""), "source": "instagram_post"})
                        print(f"    POST LOCATION: {loc.get('name', '')}")

    # ── 7. GitHub collaborators ──
    step(7, "GITHUB NETWORK")
    for gu in [gh_user, ig_user]:
        if not gu: continue
        for endpoint in ["followers", "following"]:
            data = api(f"https://api.github.com/users/{gu}/{endpoint}?per_page=10")
            if data:
                for u in data[:5]:
                    login = u.get("login", "")
                    udata = api(f"https://api.github.com/users/{login}")
                    if udata:
                        email = udata.get("email", "")
                        loc = udata.get("location", "")
                        rel = f"GitHub {endpoint[:-1]}"
                        contact = email or ""
                        add_conn(udata.get("name", login), rel, "GitHub", contact)
                        if loc and city.lower() in loc.lower():
                            print(f"    SAME CITY: {login} ({loc})")
                    time.sleep(0.5)

    # ── 8. LinkedIn dork for phone ──
    step(8, "LINKEDIN + PROFESSIONAL PHONE")
    raw = dork(f'site:linkedin.com/in "{name}" "{city}"')
    linkedin_slugs = re.findall(r'linkedin\.com/in/([a-zA-Z0-9_-]+)', raw)
    for slug in linkedin_slugs[:3]:
        print(f"    LinkedIn: linkedin.com/in/{slug}")
        add_conn(name, "LinkedIn profile", "LinkedIn", f"linkedin.com/in/{slug}")
    
    raw = dork(f'"{name}" "@telecomitalia.it" OR "@tim.it" OR "@bip-group.com" "telefono" OR "phone" OR "mobile"')
    extract_phones_from_html(raw, "corporate_directory")
    time.sleep(2)

    # ── 9. Truecaller verification ──
    step(9, "TRUECALLER VERIFICATION")
    for phone in list(phones.keys())[:5]:
        raw = run(f'truecallerjs -s --phone {phone} --json 2>/dev/null', 10)
        if raw:
            try:
                data = json.loads(raw)
                for entry in data.get("data", []):
                    tc_name = entry.get("name", "")
                    if tc_name:
                        print(f"    Truecaller: {phone} -> {tc_name}")
                        if last.lower() in tc_name.lower():
                            phones[phone]["confidence"] = "CONFIRMED"
                            phones[phone]["sources"].append(f"truecaller_verified:{tc_name}")
            except: pass

    # ── REPORT ──
    print(f"\n{'='*55}")
    print(f"  CONTACT FINDER RESULTS (FP-FILTERED)")
    print(f"{'='*55}")
    print(f"\n  Target: {name} ({city})")
    
    # Re-score all phones with final accumulated sources
    print(f"\n  PHONES ({len(phones)}):")
    for p, info in sorted(phones.items(), key=lambda x: x[1].get("fp_score", 5)):
        fp = quick_score_phone(p, info["sources"], name, country="IT")
        conf = fp["confidence"]
        score = fp["score"]
        sources_str = ', '.join(set(info['sources']))
        print(f"    [{conf}] (FP:{score}/10) {p} — {sources_str}")
    
    print(f"\n  CONNECTIONS ({len(connections)}):")
    for c in connections:
        extra = f" [{c['contact']}]" if c['contact'] else ""
        print(f"    {c['name']} ({c['relation']}) {c['platform']}{extra}")
    
    print(f"\n  LOCATIONS ({len(locations)}):")
    for l in locations:
        print(f"    {l['name']} ({l['source']})")
    
    # Export JSON
    output = {
        "phones": [{"number": p, "sources": info["sources"], "confidence": info["confidence"], "fp_score": info.get("fp_score", "?")} for p, info in phones.items()],
        "connections": connections,
        "locations": locations,
    }
    out_path = "/tmp/contact_finder_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  JSON: {out_path}")
    print(f"{'='*55}")

if __name__ == "__main__":
    main()
