#!/usr/bin/env python3
"""
StrikeCore Phone Lookup v2 — Multi-vector phone number intelligence with FP filtering.

Vectors:
1. phoneinfoga scan
2. NumVerify API (carrier, line type, location)
3. Veriphone.io (free validation)
4. Google dorking reverse lookup
5. Truecaller/Sync.me web search
6. Social media registration check (ignorant)
7. Caller ID services
8. Italian directories (Pagine Bianche) — IT only

All results pass through fp_filter for false positive scoring.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error

# Add project root to path for core imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.fp_filter import validate_phone_number, quick_score_phone, log_rejection

PATH = os.path.expanduser("~/.local/bin") + ":" + os.path.expanduser("~/go/bin") + ":/usr/local/go/bin:" + os.environ.get("PATH", "")
ENV = {**os.environ, "PATH": PATH}

# ── Improved regex patterns ──
# Mobile IT: 3xx xxx xxxx (with or without +39)
MOBILE_IT_RE = re.compile(r'(?:\+39\s?)?3[0-9]{2}[\s.\-]?\d{3}[\s.\-]?\d{4}')
# Fixed IT: 0xx xxxxxxx
FIXED_IT_RE = re.compile(r'(?:\+39\s?)?0[0-9]{1,3}[\s.\-]?\d{6,8}')
# Generic international
INTL_RE = re.compile(r'\+[1-9]\d{1,2}[\s.\-]?\d{3,4}[\s.\-]?\d{3,4}[\s.\-]?\d{0,4}')

# Anti-FP: patterns to EXCLUDE from phone extraction
EXCLUDE_RE = [
    re.compile(r'\b\d{11}\b'),         # P.IVA (11 digits standalone)
    re.compile(r'\b\d{16}\b'),         # CF numerico / carte
    re.compile(r'\d{2}/\d{2}/\d{4}'),  # Date dd/mm/yyyy
    re.compile(r'\d{4}-\d{2}-\d{2}'),  # Date yyyy-mm-dd
    re.compile(r'ID[:\s]?\d+'),          # IDs
]


def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=ENV)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except Exception as e:
        return "", str(e), -1

def api_get(url, headers=None):
    try:
        req = urllib.request.Request(url, headers=headers or {"User-Agent": "StrikeCore/2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except:
        return None

def step(name):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

def extract_phones_from_html(html, source_label="web"):
    """Extract phone numbers from HTML with anti-FP filtering."""
    found = []
    
    # Check exclusions first — remove date/ID patterns
    clean_html = html
    for exc in EXCLUDE_RE:
        clean_html = exc.sub('', clean_html)
    
    # Extract mobile IT
    for m in MOBILE_IT_RE.findall(clean_html):
        clean = re.sub(r'[\s.\-]', '', m)
        if len(clean) >= 10:
            found.append((clean, source_label))
    
    # Extract fixed IT
    for m in FIXED_IT_RE.findall(clean_html):
        clean = re.sub(r'[\s.\-]', '', m)
        if len(clean) >= 10:
            found.append((clean, source_label))
    
    # Extract international
    for m in INTL_RE.findall(clean_html):
        clean = re.sub(r'[\s.\-]', '', m)
        if len(clean) >= 10:
            found.append((clean, source_label))
    
    return found


def main():
    if len(sys.argv) < 2:
        print("Usage: phone_lookup.py PHONE_NUMBER [TARGET_NAME]")
        print("Example: phone_lookup.py +393401234567 'Mario Rossi'")
        print("         phone_lookup.py 3401234567 (assumes +39 Italy)")
        sys.exit(1)

    phone = sys.argv[1].strip()
    target_name = sys.argv[2] if len(sys.argv) > 2 else None
    
    # Normalize
    phone_clean = re.sub(r'[\s\-\(\)\.]+', '', phone)
    if not phone_clean.startswith('+'):
        if phone_clean.startswith('00'):
            phone_clean = '+' + phone_clean[2:]
        elif len(phone_clean) == 10 and phone_clean.startswith('3'):
            phone_clean = '+39' + phone_clean
        else:
            phone_clean = '+39' + phone_clean
    
    # Extract country code
    cc_match = re.match(r'\+(\d{1,3})', phone_clean)
    country_code = cc_match.group(1) if cc_match else "39"
    national = phone_clean[len(country_code)+1:]
    
    # ── INITIAL VALIDATION ──
    print(f"[*] StrikeCore Phone Lookup v2")
    print(f"[*] Target: {phone_clean}")
    print(f"[*] Country code: +{country_code}")
    print(f"[*] National: {national}")
    if target_name:
        print(f"[*] Target name: {target_name}")
    print(f"[*] Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Validate the input number first
    phone_val = validate_phone_number(phone_clean, expected_country="IT" if country_code == "39" else "")
    print(f"\n[*] Structural validation: valid={phone_val['valid']}, type={phone_val.get('number_type', '?')}, carrier={phone_val.get('carrier', '?')}")
    if not phone_val['valid']:
        print(f"[!] WARNING: Input number is structurally invalid: {phone_val.get('rejection_reason')}")
        print(f"[!] Continuing lookup anyway...")

    results = {
        "phone": phone_clean,
        "carrier": phone_val.get("carrier"),
        "type": phone_val.get("number_type"),
        "location": None,
        "country": phone_val.get("country"),
        "names": [],
        "emails": [],
        "social": [],
        "services": [],
        "fp_score": None,
        "fp_confidence": None,
    }

    all_sources = []

    # ��─ STEP 1: PhoneInfoga ──
    step("1. PhoneInfoga scan")
    stdout, stderr, rc = run(f'phoneinfoga scan -n "{phone_clean}" 2>&1', 30)
    if rc == 0 and stdout:
        print(stdout[:2000])
        carrier_m = re.search(r'Carrier:\s*(.+)', stdout)
        if carrier_m:
            results["carrier"] = results["carrier"] or carrier_m.group(1).strip()
        country_m = re.search(r'Country:\s*(.+)', stdout)
        if country_m:
            results["country"] = results["country"] or country_m.group(1).strip()
        type_m = re.search(r'Line type:\s*(.+)', stdout)
        if type_m:
            results["type"] = results["type"] or type_m.group(1).strip()
        all_sources.append("phoneinfoga")
    else:
        print(f"  phoneinfoga failed: {stderr[:200]}")

    # ── STEP 2: Free API lookups ──
    step("2. Free API lookups")
    
    numverify_key = os.environ.get("NUMVERIFY_API_KEY", "")
    if numverify_key:
        data = api_get(f"http://apilayer.net/api/validate?access_key={numverify_key}&number={phone_clean}")
        if data and data.get("valid"):
            print(f"  NumVerify: valid={data.get('valid')}, carrier={data.get('carrier')}, type={data.get('line_type')}, location={data.get('location')}")
            results["carrier"] = results["carrier"] or data.get("carrier")
            results["type"] = results["type"] or data.get("line_type")
            results["location"] = data.get("location")
            results["country"] = results["country"] or data.get("country_name")
            all_sources.append("numverify")

    data = api_get(f"https://api.veriphone.io/v2/verify?phone={phone_clean}")
    if data and data.get("phone_valid"):
        print(f"  Veriphone: valid={data.get('phone_valid')}, carrier={data.get('carrier')}, type={data.get('phone_type')}")
        results["carrier"] = results["carrier"] or data.get("carrier")
        results["type"] = results["type"] or data.get("phone_type")
        results["country"] = results["country"] or data.get("country")
        all_sources.append("veriphone")

    # ── STEP 3: Google reverse lookup ���─
    step("3. Google/DuckDuckGo reverse lookup")
    
    queries = [
        f'"{phone_clean}"',
        f'"{national}" "+{country_code}"',
        f'"{phone_clean}" email OR mail OR name OR nome',
        f'site:facebook.com "{national}"',
        f'site:linkedin.com "{national}"',
        f'site:truecaller.com "{national}"',
    ]
    if country_code == "39":
        queries.append(f'site:paginebianche.it "{national}"')
    
    for q in queries:
        if not q:
            continue
        encoded = urllib.request.quote(q)
        stdout, _, _ = run(f'proxychains4 -q curl -s "https://html.duckduckgo.com/html/?q={encoded}" -H "User-Agent: Mozilla/5.0" 2>/dev/null', 15)
        
        # Extract names (improved pattern)
        names = re.findall(r'(?:name|nome|intestato)\s*(?:a|:)\s*([A-Z][a-z]+ [A-Z][a-z]+)', stdout)
        for n in names:
            if n not in results["names"]:
                results["names"].append(n)
                print(f"  NAME FOUND: {n}")
        
        # Extract emails
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', stdout)
        for e in emails:
            if e not in results["emails"] and "noreply" not in e.lower():
                results["emails"].append(e)
                print(f"  EMAIL FOUND: {e}")
        
        if stdout:
            all_sources.append("google_dork")
        
        time.sleep(2)

    # ── STEP 4: Social media registration check ──
    step("4. Social media registration check")
    
    stdout, _, rc = run(f'ignorant {country_code} {national} --no-color --no-clear 2>&1', 30)
    if rc == 0 and stdout:
        services = re.findall(r'\[\+\]\s*(.+)', stdout)
        for s in services:
            results["services"].append(s.strip())
            print(f"  REGISTERED: {s.strip()}")
            all_sources.append(f"ignorant:{s.strip()}")
        if not services:
            used = [l for l in stdout.split('\n') if '[+]' in l or 'used' in l.lower()]
            for u in used:
                print(f"  {u.strip()}")
    
    # ── STEP 5: Caller ID services ──
    step("5. Caller ID web search")
    
    callerid_sites = [
        f"https://www.truecaller.com/search/it/{national}",
        f"https://www.sync.me/search/?number=%2B{country_code}{national}",
        f"https://www.tellows.it/num/{phone_clean.replace('+', '')}",
    ]
    if country_code == "39":
        callerid_sites.append(f"https://chi-chiama.it/numero/{national}")
    
    for url in callerid_sites:
        site = url.split('/')[2]
        stdout, _, _ = run(f'proxychains4 -q curl -sL "{url}" -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)" 2>/dev/null | head -c 5000', 15)
        
        if stdout:
            name_patterns = [
                r'class="[^"]*caller[^"]*name[^"]*"[^>]*>([^<]+)',
                r'"name"\s*:\s*"([^"]+)"',
                r'(?:intestato|belongs to|owned by)\s+([A-Z][a-z]+ [A-Z][a-z]+)',
            ]
            for pat in name_patterns:
                match = re.search(pat, stdout, re.IGNORECASE)
                if match:
                    name = match.group(1).strip()
                    skip = ["Truecaller", "Sync.me", "Tellows", "Chi Chiama", "Search", "Home"]
                    if len(name) > 3 and name not in skip:
                        results["names"].append(name)
                        print(f"  [{site}] NAME: {name}")
                        all_sources.append(f"callerid:{site}")
                        break
        time.sleep(2)

    # ── STEP 6: Italian specific (Pagine Bianche) ──
    if country_code == "39":
        step("6. Pagine Bianche (Italy)")
        stdout, _, _ = run(f'proxychains4 -q curl -sL "https://www.paginebianche.it/ricerca?qs={national}&dession=true" -H "User-Agent: Mozilla/5.0" 2>/dev/null | head -c 10000', 15)
        if stdout:
            names_pb = re.findall(r'class="[^"]*name[^"]*"[^>]*>([^<]+)', stdout)
            for n in names_pb[:3]:
                n = n.strip()
                if len(n) > 3:
                    results["names"].append(n)
                    print(f"  PagineBianche NAME: {n}")
                    all_sources.append("paginebianche")

    # ── FP SCORING ──
    step("FP ANALYSIS")
    
    fp_result = quick_score_phone(
        number=phone_clean,
        sources=list(set(all_sources)),
        target_name=target_name,
        country="IT" if country_code == "39" else "",
    )
    
    results["fp_score"] = fp_result["score"]
    results["fp_confidence"] = fp_result["confidence"]
    
    print(f"  FP Score: {fp_result['score']}/10")
    print(f"  Confidence: {fp_result['confidence']}")
    print(f"  Action: {fp_result['action']}")
    print(f"  Sources ({len(set(all_sources))}): {', '.join(set(all_sources))}")
    for reason in fp_result["reasons"]:
        print(f"    {reason}")

    # ── FINAL REPORT ──
    print("\n" + "="*70)
    print(f"  PHONE LOOKUP REPORT [{fp_result['confidence']}]")
    print("="*70)
    print(f"\n  Phone: {phone_clean}")
    print(f"  Carrier: {results['carrier'] or 'Unknown'}")
    print(f"  Type: {results['type'] or 'Unknown'}")
    print(f"  Country: {results['country'] or 'Unknown'}")
    print(f"  Location: {results['location'] or 'Unknown'}")
    print(f"  FP Score: {fp_result['score']}/10 ({fp_result['confidence']})")
    
    if results["names"]:
        print(f"\n  Names associated:")
        for n in set(results["names"]):
            print(f"    - {n}")
    
    if results["emails"]:
        print(f"\n  Emails found:")
        for e in results["emails"]:
            print(f"    - {e}")
    
    if results["services"]:
        print(f"\n  Registered services:")
        for s in results["services"]:
            print(f"    - {s}")
    
    if fp_result["action"] == "reject":
        print(f"\n  ⚠ WARNING: This number scored {fp_result['score']}/10 — likely FALSE POSITIVE")
    elif fp_result["action"] == "flag":
        print(f"\n  ⚠ REVIEW: This number scored {fp_result['score']}/10 — needs analyst verification")
    
    print("="*70)

if __name__ == "__main__":
    main()
