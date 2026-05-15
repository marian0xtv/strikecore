#!/usr/bin/env python3
"""
StrikeCore Breach Aggregator — FREE tier services only.
Queries every free breach/leak database available for phone numbers.
"""
import json, os, re, subprocess, sys, time, urllib.request, urllib.parse, urllib.error, hashlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

TARGET_NAME = "Luigi Savino"
EMAILS = ["luigi.savino.95@gmail.com", "luxdj95@gmail.com", "luigi.savino@guest.telecomitalia.it", "luigi.savino@mail-bip.com"]
USERNAMES = ["luigisav", "LuigiSavino", "luxdj95", "luigi.savino"]
FB_ID = "1439591776"
PHONE_CANDIDATES = []  # Will be populated if we find any

def req(url, headers=None, data=None, timeout=15):
    hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    if headers:
        hdrs.update(headers)
    r = urllib.request.Request(url, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read()), e.code
        except:
            return {"error": str(e)}, e.code
    except Exception as e:
        return {"error": str(e)}, 0

def run(cmd, t=20):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
        return r.stdout.strip()
    except:
        return ""

print("=" * 65)
print("  STRIKECORE BREACH AGGREGATOR — ALL FREE SERVICES")
print("  Target: Luigi Savino")
print("=" * 65)

# ═══════════════════════════════════════════════════
# 1. HAVE I BEEN PWNED (free — searches by email AND phone)
# ═══════════════════════════════════════════════════
print("\n[1] HAVE I BEEN PWNED")
for email in EMAILS[:2]:
    print(f"  {email}: ", end="", flush=True)
    data, status = req(f"https://haveibeenpwned.com/unifiedsearch/{urllib.parse.quote(email)}")
    if status == 200 and isinstance(data, dict):
        breaches = [b.get("Name","") for b in data.get("Breaches", [])]
        if breaches:
            print(f"BREACHED in: {', '.join(breaches[:8])}")
            if "Facebook" in breaches:
                print(f"    *** FACEBOOK BREACH CONFIRMED — phone likely in dump ***")
        else:
            print("clean")
    elif status == 404:
        print("not found")
    else:
        print(f"status {status}")
    time.sleep(1.5)

# Also try by phone candidates from earlier dorking
print(f"  Checking FB ID as phone prefix search...")
data, status = req(f"https://haveibeenpwned.com/unifiedsearch/{urllib.parse.quote(FB_ID)}")
print(f"  FB ID {FB_ID}: status {status}")
time.sleep(1.5)

# ═══════════════════════════════════════════════════
# 2. XPOSEDORNOT (free API, no auth needed)
# ═══════════════════════════════════════════════════
print("\n[2] XPOSEDORNOT (free API)")
for email in EMAILS[:3]:
    print(f"  {email}: ", end="", flush=True)
    data, status = req(f"https://api.xposedornot.com/v1/check-email/{urllib.parse.quote(email)}")
    if status == 200:
        breaches = data.get("breaches", [])
        if isinstance(breaches, list) and breaches:
            print(f"EXPOSED in {len(breaches)} breaches")
            for b in breaches[:5]:
                if isinstance(b, dict):
                    print(f"    {b.get('breach', b.get('name', str(b)))}")
                else:
                    print(f"    {b}")
        elif isinstance(data, dict) and data.get("ExposedBreaches"):
            exposed = data["ExposedBreaches"]
            if isinstance(exposed, dict):
                blist = exposed.get("breaches_details", [])
                print(f"EXPOSED in {len(blist)} breaches")
                for b in blist[:5]:
                    print(f"    {b.get('breach', '?')} — data: {b.get('xposed_data', '?')}")
            else:
                print(f"exposed: {str(exposed)[:100]}")
        else:
            print(f"clean or no data")
    else:
        print(f"status {status}")
    time.sleep(1)

# ═══════════════════════════════════════════════════
# 3. INTELLIGENCE SECURITY (free tier)
# ═══════════════════════════════════════════════════
print("\n[3] INTELLIGENCE SECURITY (intelligencesecurity.io)")
for email in EMAILS[:2]:
    print(f"  {email}: ", end="", flush=True)
    data, status = req(
        f"https://api.intelligencesecurity.io/v1/search?query={urllib.parse.quote(email)}",
        headers={"Accept": "application/json"}
    )
    if status == 200 and isinstance(data, dict):
        results = data.get("results", data.get("data", []))
        if results:
            print(f"{len(results)} results")
            for r_item in (results[:5] if isinstance(results, list) else []):
                phone = r_item.get("phone", "")
                if phone:
                    PHONE_CANDIDATES.append(phone)
                    print(f"    *** PHONE: {phone} ***")
                else:
                    print(f"    {str(r_item)[:100]}")
        else:
            print("no results")
    else:
        print(f"status {status}: {str(data)[:80]}")
    time.sleep(1)

# ═══════════════════════════════════════════════════
# 4. OSINTLEAK (free starter — email + username)
# ═══════════════════════════════════════════════════
print("\n[4] OSINTLEAK (osintleak.com)")
for identifier in EMAILS[:2] + USERNAMES[:2]:
    print(f"  {identifier}: ", end="", flush=True)
    data, status = req(
        f"https://osintleak.com/api/v1/search?query={urllib.parse.quote(identifier)}",
        headers={"Accept": "application/json"}
    )
    if status == 200 and isinstance(data, dict):
        results = data.get("results", data.get("data", []))
        if results:
            print(f"HIT — {len(results) if isinstance(results, list) else 'data'}")
            if isinstance(results, list):
                for item in results[:3]:
                    phone = item.get("phone", "") or item.get("phone_number", "")
                    if phone:
                        PHONE_CANDIDATES.append(phone)
                        print(f"    *** PHONE: {phone} ***")
        else:
            print("no data")
    else:
        print(f"status {status}")
    time.sleep(1)

# ═══════════════════════════════════════════════════
# 5. LEAKCHECK (free public API)
# ═══════════════════════════════════════════════════
print("\n[5] LEAKCHECK (leakcheck.io)")
for email in EMAILS[:2]:
    print(f"  {email}: ", end="", flush=True)
    data, status = req(f"https://leakcheck.io/api/public?check={urllib.parse.quote(email)}")
    if status == 200 and isinstance(data, dict):
        found = data.get("found", 0)
        sources = data.get("sources", [])
        if found:
            print(f"FOUND in {found} source(s): {sources}")
            for s in (data.get("result", []) if isinstance(data.get("result"), list) else []):
                phone = s.get("phone", "")
                if phone:
                    PHONE_CANDIDATES.append(phone)
                    print(f"    *** PHONE: {phone} ***")
        else:
            print("not found")
    else:
        print(f"status {status}")
    time.sleep(1)

# ═══════════════════════════════════════════════════
# 6. OATHNET (free 10 lookups/day)
# ═══════════════════════════════════════════════════
print("\n[6] OATHNET (oathnet.org)")
for email in EMAILS[:2]:
    print(f"  {email}: ", end="", flush=True)
    data, status = req(
        f"https://api.oathnet.org/v1/search?query={urllib.parse.quote(email)}&type=email",
        headers={"Accept": "application/json"}
    )
    if status == 200:
        if isinstance(data, dict) and (data.get("results") or data.get("data")):
            results = data.get("results", data.get("data", []))
            print(f"HIT")
            if isinstance(results, list):
                for item in results[:5]:
                    phone = item.get("phone", "") or item.get("phone_number", "")
                    if phone:
                        PHONE_CANDIDATES.append(phone)
                        print(f"    *** PHONE: {phone} ***")
        else:
            print(f"no data")
    else:
        print(f"status {status}")
    time.sleep(1)

# ═══════════════════════════════════════════════════
# 7. HUDSONROCK CAVALIER (free stealer log search)
# ═══════════════════════════════════════════════════
print("\n[7] HUDSONROCK CAVALIER (stealers)")
for email in EMAILS:
    print(f"  {email}: ", end="", flush=True)
    data, status = req(f"https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-email?email={urllib.parse.quote(email)}")
    if status == 200 and isinstance(data, dict):
        stealers = data.get("stealers", [])
        if stealers:
            print(f"{len(stealers)} stealer(s)")
            for s in stealers[:3]:
                print(f"    Date: {s.get('date_compromised','')} | PC: {s.get('computer_name','')} | IP: {s.get('ip','')}")
                # Check all fields for phone
                for k, v in s.items():
                    if isinstance(v, str) and re.match(r'^\+?\d{10,15}$', v.replace(" ","")):
                        PHONE_CANDIDATES.append(v)
                        print(f"    *** PHONE in field '{k}': {v} ***")
            # Check top_passwords for phone patterns
            for pwd in data.get("top_passwords", []):
                if re.match(r'^\+?\d{10,15}$', str(pwd).replace(" ","")):
                    PHONE_CANDIDATES.append(str(pwd))
                    print(f"    *** PHONE in passwords: {pwd} ***")
        else:
            print("clean")
    else:
        print(f"status {status}")
    time.sleep(1)

# Also search by username
for user in USERNAMES[:2]:
    print(f"  @{user}: ", end="", flush=True)
    data, status = req(f"https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-username?username={urllib.parse.quote(user)}")
    if status == 200 and isinstance(data, dict):
        stealers = data.get("stealers", [])
        if stealers:
            print(f"{len(stealers)} stealer(s)")
            for s in stealers[:3]:
                print(f"    {s.get('date_compromised','')} | {s.get('computer_name','')} | {s.get('ip','')}")
        else:
            print("clean")
    else:
        print(f"status {status}")
    time.sleep(1)

# ═══════════════════════════════════════════════════
# 8. BREACHDIRECTORY (free limited)
# ═══════════════════════════════════════════════════
print("\n[8] BREACHDIRECTORY")
for email in EMAILS[:2]:
    print(f"  {email}: ", end="", flush=True)
    data, status = req(
        f"https://breachdirectory.org/api/search?query={urllib.parse.quote(email)}&type=email",
        headers={"Accept": "application/json"}
    )
    if status == 200 and isinstance(data, dict):
        results = data.get("result", data.get("data", []))
        if results:
            print(f"HIT")
            if isinstance(results, list):
                for item in results[:5]:
                    phone = item.get("phone", "")
                    if phone:
                        PHONE_CANDIDATES.append(phone)
                        print(f"    *** PHONE: {phone} ***")
                    sources = item.get("sources", [])
                    if sources:
                        print(f"    sources: {sources[:3]}")
        else:
            print("no data")
    else:
        print(f"status {status}")
    time.sleep(1)

# ═══════════════════════════════════════════════════
# 9. H8MAIL (local tool — already installed)
# ═══════════════════════════════════════════════════
print("\n[9] H8MAIL (local breach search)")
for email in EMAILS[:2]:
    print(f"  {email}: ", end="", flush=True)
    raw = run(f"h8mail -t {email} 2>&1 | grep -v '^$' | grep -v '\\[\\*\\]' | head -20")
    if raw:
        lines = [l for l in raw.split('\n') if l.strip()]
        phones = re.findall(r'\+?\d{10,15}', raw)
        # Filter out credit card numbers
        real_phones = [p for p in phones if len(p) <= 13]
        if real_phones:
            for p in real_phones:
                PHONE_CANDIDATES.append(p)
                print(f"PHONE: {p}")
        elif lines:
            print(f"{len(lines)} lines")
            for l in lines[:3]:
                print(f"    {l.strip()[:100]}")
        else:
            print("no results")
    else:
        print("no output")
    time.sleep(1)

# ═══════════════════════════════════════════════════
# 10. EMAILREP.IO (free)
# ═══════════════════════════════════════════════════
print("\n[10] EMAILREP.IO")
for email in EMAILS[:2]:
    print(f"  {email}: ", end="", flush=True)
    data, status = req(f"https://emailrep.io/{urllib.parse.quote(email)}", headers={"User-Agent": "StrikeCore/2.0"})
    if status == 200 and isinstance(data, dict):
        rep = data.get("reputation", "")
        details = data.get("details", {})
        breach = details.get("data_breach", False)
        profiles = details.get("profiles", [])
        print(f"rep={rep}, breach={breach}, profiles={profiles}")
    else:
        print(f"status {status}")
    time.sleep(2)

# ═══════════════════════════════════════════════════
# FINAL REPORT
# ═══════════════════════════════════════════════════
print(f"\n{'='*65}")
print(f"  FINAL REPORT")
print(f"{'='*65}")

if PHONE_CANDIDATES:
    # Deduplicate and validate
    unique = list(set(PHONE_CANDIDATES))
    print(f"\n  PHONES FOUND: {len(unique)}")
    for p in unique:
        print(f"    {p}")
else:
    print(f"\n  No phone numbers found across all services.")
    print(f"  The target has minimal breach exposure.")

print(f"\n  Services queried: HIBP, XposedOrNot, IntelSecurity, OSINTLeak,")
print(f"    LeakCheck, OathNet, HudsonRock, BreachDirectory, h8mail, EmailRep")
print(f"{'='*65}")
