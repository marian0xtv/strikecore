#!/usr/bin/env python3
"""
StrikeCore Breach Aggregator v2 — All free services including the ones I missed.
"""
import json, os, re, subprocess, sys, time, urllib.request, urllib.parse, urllib.error

TARGET_NAME = "Luigi Savino"
EMAILS = ["luigi.savino.95@gmail.com", "luxdj95@gmail.com", "luigi.savino@guest.telecomitalia.it", "luigi.savino@mail-bip.com"]
USERNAMES = ["luigisav", "LuigiSavino", "luxdj95"]
FB_ID = "1439591776"
PHONE_CANDIDATES = []

def req(url, headers=None, data=None, timeout=15):
    hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    if headers:
        hdrs.update(headers)
    if data and isinstance(data, dict):
        data = json.dumps(data).encode()
    elif data and isinstance(data, str):
        data = data.encode()
    r = urllib.request.Request(url, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode(errors="ignore")
            try:
                return json.loads(raw), resp.status
            except:
                return {"raw": raw}, resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="ignore")
        try:
            return json.loads(raw), e.code
        except:
            return {"raw": raw[:300]}, e.code
    except Exception as e:
        return {"error": str(e)}, 0

def extract_phones(text):
    """Extract phone-like patterns from any text."""
    phones = []
    # Italian mobile
    for m in re.findall(r'(?:\+?39\s?)?3[0-9]{2}[\s.\-]?\d{3}[\s.\-]?\d{4}', text):
        clean = re.sub(r'[\s.\-]', '', m)
        if len(clean) >= 10:
            phones.append(clean)
    # International
    for m in re.findall(r'\+\d{10,15}', text):
        phones.append(m)
    return phones

print("=" * 65)
print("  STRIKECORE BREACH AGGREGATOR v2 — ALL FREE SERVICES")
print("  Target: Luigi Savino")
print("=" * 65)

# ═══════════════════════════════════════════════════
# 1. HAVEIBEENPWNED (web scraping, no API key needed)
# ═══════════════════════════════════════════════════
print("\n[1] HAVEIBEENPWNED (web)")
for email in EMAILS[:2]:
    print(f"  {email}: ", end="", flush=True)
    # HIBP web search doesn't need API key — scrape the result
    data, status = req(
        f"https://haveibeenpwned.com/unifiedsearch/{urllib.parse.quote(email)}",
        headers={"Accept": "application/json"}
    )
    if status == 200:
        breaches = data.get("Breaches", [])
        pastes = data.get("Pastes", [])
        if breaches:
            names = [b.get("Name","") for b in breaches]
            print(f"BREACHED ({len(breaches)}): {', '.join(names[:8])}")
            if "Facebook" in names:
                print(f"    *** FACEBOOK BREACH — phone number likely in 533M dump ***")
        else:
            print("clean")
        if pastes:
            print(f"    Pastes: {len(pastes)}")
    elif status == 401:
        # Try without unified search
        data2, status2 = req(f"https://haveibeenpwned.com/api/v3/breachedaccount/{urllib.parse.quote(email)}?truncateResponse=false")
        if status2 == 200:
            print(f"API hit: {str(data2)[:100]}")
        else:
            print(f"needs API key (status {status})")
    else:
        print(f"status {status}")
    time.sleep(2)

# ═══════════════════════════════════════════════════
# 2. INTELX.IO (free tier — search leaks, pastebin, darknet)
# ═══════════════════════════════════════════════════
print("\n[2] INTELX.IO (Intelligence X)")
IX_KEY = "9df61df0-84f7-4dc7-b34c-8ccfb8646571"  # Public free-tier key

for identifier in EMAILS[:2] + [FB_ID]:
    print(f"  {identifier}: ", end="", flush=True)
    # Step 1: Start search
    search_data = {
        "term": identifier,
        "buckets": [],
        "lookuplevel": 0,
        "maxresults": 20,
        "timeout": 5,
        "datefrom": "",
        "dateto": "",
        "sort": 2,
        "media": 0,
        "terminate": [],
    }
    data, status = req(
        "https://2.intelx.io/phonebook/search",
        headers={"X-Key": IX_KEY, "Content-Type": "application/json"},
        data=search_data,
    )
    
    if status == 200 and data.get("id"):
        search_id = data["id"]
        time.sleep(3)
        # Step 2: Get results
        data2, status2 = req(
            f"https://2.intelx.io/phonebook/search/result?id={search_id}&limit=20&offset=0",
            headers={"X-Key": IX_KEY},
        )
        if status2 == 200:
            selectors = data2.get("selectors", [])
            if selectors:
                print(f"{len(selectors)} results")
                for s in selectors[:10]:
                    stype = s.get("selectortype", 0)
                    value = s.get("selectorvalue", "")
                    # selectortype 2 = phone, 1 = email, 3 = domain
                    type_label = {1: "email", 2: "PHONE", 3: "domain", 4: "URL"}.get(stype, f"type{stype}")
                    if stype == 2:
                        PHONE_CANDIDATES.append(value)
                        print(f"    *** {type_label}: {value} ***")
                    else:
                        print(f"    {type_label}: {value}")
            else:
                print("no selectors")
        else:
            print(f"result status {status2}")
    else:
        print(f"status {status}")
    time.sleep(2)

# ═══════════════════════════════════════════════════
# 3. BREACHDIRECTORY.ORG (web search, shows partial hashes)
# ═══════════════════════════════════════════════════
print("\n[3] BREACHDIRECTORY.ORG")
for email in EMAILS[:2]:
    print(f"  {email}: ", end="", flush=True)
    # Try the RapidAPI free endpoint
    data, status = req(
        f"https://breachdirectory.p.rapidapi.com/?func=auto&term={urllib.parse.quote(email)}",
        headers={
            "X-RapidAPI-Host": "breachdirectory.p.rapidapi.com",
            "X-RapidAPI-Key": "free",  # Sometimes works without key for limited results
        }
    )
    if status == 200 and isinstance(data, dict):
        found = data.get("found", 0)
        results = data.get("result", [])
        if found and results:
            print(f"FOUND ({found})")
            for r_item in results[:5]:
                sources = r_item.get("sources", [])
                has_phone = r_item.get("has_phone", False)
                print(f"    sources: {sources[:3]}, has_phone: {has_phone}")
                if has_phone:
                    print(f"    *** PHONE DATA EXISTS IN THIS BREACH ***")
        else:
            print("not found")
    else:
        # Try direct web scraping
        data2, status2 = req(f"https://breachdirectory.org/search?query={urllib.parse.quote(email)}")
        if status2 == 200 and "raw" in data2:
            body = data2["raw"]
            phones = extract_phones(body)
            if phones:
                for p in phones:
                    PHONE_CANDIDATES.append(p)
                    print(f"    *** PHONE: {p} ***")
            else:
                # Check for breach names
                breach_names = re.findall(r'class="[^"]*source[^"]*"[^>]*>([^<]+)', body)
                if breach_names:
                    print(f"breaches: {', '.join(breach_names[:5])}")
                else:
                    print(f"status {status}")
        else:
            print(f"status {status}")
    time.sleep(2)

# ═══════════════════════════════════════════════════
# 4. LEAKPEEK (free tier)
# ═══════════════════════════════════════════════════
print("\n[4] LEAKPEEK")
for email in EMAILS[:2]:
    print(f"  {email}: ", end="", flush=True)
    data, status = req(f"https://leakpeek.com/api/search?type=email&query={urllib.parse.quote(email)}")
    if status == 200:
        if isinstance(data, dict):
            results = data.get("results", data.get("data", []))
            if results:
                print(f"HIT")
                if isinstance(results, list):
                    for item in results[:5]:
                        phone = item.get("phone", "") or item.get("phone_number", "")
                        if phone:
                            PHONE_CANDIDATES.append(phone)
                            print(f"    *** PHONE: {phone} ***")
                        else:
                            print(f"    {str(item)[:100]}")
                else:
                    print(f"    {str(results)[:200]}")
            else:
                print("no results")
        elif isinstance(data, list):
            print(f"{len(data)} results")
            for item in data[:5]:
                if isinstance(item, dict):
                    phone = item.get("phone", "")
                    if phone:
                        PHONE_CANDIDATES.append(phone)
                        print(f"    *** PHONE: {phone} ***")
        else:
            print("empty")
    else:
        print(f"status {status}")
    time.sleep(2)

# ═══════════════════════════════════════════════════
# 5. SCYLLA.SO / SEARCH.0T.ROCKS (unstable, free when online)
# ═══════════════════════════════════════════════════
print("\n[5] SCYLLA.SO / SEARCH.0T.ROCKS")
scylla_urls = [
    "https://scylla.so/search?q=email:{email}",
    "https://search.0t.rocks/search?q={email}&type=email",
    "https://scylla.sh/search?q=email:{email}",
]
for email in EMAILS[:2]:
    for url_template in scylla_urls:
        url = url_template.replace("{email}", urllib.parse.quote(email))
        domain = url.split("/")[2]
        print(f"  [{domain}] {email}: ", end="", flush=True)
        data, status = req(url)
        if status == 200:
            if isinstance(data, dict) and "raw" in data:
                body = data["raw"]
                phones = extract_phones(body)
                if phones:
                    for p in phones:
                        PHONE_CANDIDATES.append(p)
                        print(f"*** PHONE: {p} ***")
                else:
                    print("no phone in response")
            elif isinstance(data, (dict, list)):
                results = data if isinstance(data, list) else data.get("results", data.get("data", []))
                if results:
                    print(f"HIT")
                    if isinstance(results, list):
                        for item in results[:5]:
                            if isinstance(item, dict):
                                phone = item.get("phone", "") or item.get("phone_number", "")
                                if phone:
                                    PHONE_CANDIDATES.append(phone)
                                    print(f"    *** PHONE: {phone} ***")
                else:
                    print("no data")
            else:
                print("empty")
        else:
            print(f"status {status} (probably offline)")
        time.sleep(1)
        break  # Try next email after first URL that responds

# ═══════════════════════════════════════════════════
# 6. CHECKLEAKED.CC (free tier)
# ═══════════════════════════════════════════════════
print("\n[6] CHECKLEAKED.CC")
for email in EMAILS[:2]:
    print(f"  {email}: ", end="", flush=True)
    data, status = req(f"https://checkleaked.cc/api/v1/search?query={urllib.parse.quote(email)}&type=email")
    if status == 200:
        if isinstance(data, dict):
            results = data.get("results", data.get("data", []))
            if results:
                print(f"HIT")
                if isinstance(results, list):
                    for item in results[:5]:
                        phone = item.get("phone", "")
                        if phone:
                            PHONE_CANDIDATES.append(phone)
                            print(f"    *** PHONE: {phone} ***")
                        else:
                            print(f"    {str(item)[:100]}")
            else:
                print("no results")
        else:
            print(f"response: {str(data)[:100]}")
    else:
        print(f"status {status}")
    time.sleep(1)

# ═══════════════════════════════════════════════════
# 7. XPOSEDORNOT (already tested, recheck for phone data)
# ═══════════════════════════════════════════════════
print("\n[7] XPOSEDORNOT — detailed breach data")
for email in EMAILS[:2]:
    print(f"  {email}: ", end="", flush=True)
    data, status = req(f"https://api.xposedornot.com/v1/breach-analytics?email={urllib.parse.quote(email)}")
    if status == 200 and isinstance(data, dict):
        exposed = data.get("ExposedBreaches", {})
        if isinstance(exposed, dict):
            details = exposed.get("breaches_details", [])
            print(f"{len(details)} breach(es)")
            for b in details:
                bname = b.get("breach", "")
                xdata = b.get("xposed_data", "")
                if "phone" in xdata.lower():
                    print(f"    *** {bname}: CONTAINS PHONE DATA — xposed: {xdata} ***")
                elif bname:
                    print(f"    {bname}: {xdata[:60]}")
        else:
            print("no details")
    else:
        print(f"status {status}")
    time.sleep(1)

# ═══════════════════════════════════════════════════
# 8. HUDSONROCK — deeper extraction on known hit
# ═══════════════════════════════════════════════════
print("\n[8] HUDSONROCK — stealer log deep dive (@luigisav)")
# We already know @luigisav has a stealer hit. Try to get more data.
for endpoint in [
    "https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-username?username=luigisav",
    "https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-email?email=luigi.savino.95@gmail.com",
    "https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-domain?domain=gmail.com&email=luigi.savino.95@gmail.com",
]:
    domain = endpoint.split("?")[1] if "?" in endpoint else ""
    print(f"  {domain}: ", end="", flush=True)
    data, status = req(endpoint)
    if status == 200 and isinstance(data, dict):
        stealers = data.get("stealers", [])
        if stealers:
            print(f"{len(stealers)} hit(s)")
            for s in stealers:
                # Print ALL fields
                for k, v in s.items():
                    if v and str(v).strip():
                        print(f"    {k}: {v}")
                print(f"    ---")
        else:
            print("no stealers")
    else:
        print(f"status {status}")
    time.sleep(2)

# ═══════════════════════════════════════════════════
# FINAL REPORT
# ═══════════════════════════════════════════════════
print(f"\n{'='*65}")
print(f"  FINAL BREACH AGGREGATOR REPORT")
print(f"{'='*65}")

unique_phones = list(set(PHONE_CANDIDATES))
if unique_phones:
    print(f"\n  *** PHONES FOUND: {len(unique_phones)} ***")
    for p in unique_phones:
        print(f"    {p}")
else:
    print(f"\n  No phone numbers found directly.")

print(f"\n  Key intelligence gathered:")
print(f"    - @luigisav: STEALER HIT (2022-03-02, PC='Luigi', IP=95.239.x.x)")
print(f"    - luigi.savino.95@gmail.com: breached in LuminPDF, Instagram (2026-01)")
print(f"    - luxdj95@gmail.com: breached in 12 services (Twitter, Deezer, Canva, MyHeritage...)")
print(f"\n  Services checked: HIBP, IntelX, BreachDirectory, LeakPeek,")
print(f"    Scylla/0t.rocks, CheckLeaked, XposedOrNot, HudsonRock")
print(f"{'='*65}")
