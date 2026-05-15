#!/usr/bin/env python3
"""
StrikeCore Email Hunter v2 — Tiered email permutation + verification with FP filtering.

Changes from v1:
- Tier system: 24 priority emails checked first, rest only if tier 1 has hits
- Replaced Gravatar check with email-validator (syntax + MX)
- Integrated fp_filter scoring on all results
- Added confidence labels to output
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.fp_filter import validate_email_address, quick_score_email, log_rejection

ENV_PATH = os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")


def run_cmd(cmd, timeout=45):
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PATH": ENV_PATH}
        )
        return r.stdout.strip()
    except Exception as e:
        return f"ERROR: {e}"


def check_holehe(email):
    """Check email with holehe, return list of services where registered."""
    raw = run_cmd(f"holehe {email} --no-color --no-clear 2>&1", 45)
    if raw.startswith("ERROR"):
        return []
    found = [l.strip() for l in raw.split("\n") if "[+]" in l]
    return found


def check_emailrep(email):
    """Check email reputation via free API."""
    raw = run_cmd(f'curl -s "https://emailrep.io/{email}" -H "User-Agent: StrikeCore"', 10)
    try:
        data = json.loads(raw)
        if data.get("reputation") and data["reputation"] != "none":
            return data
    except Exception:
        pass
    return None


def check_mx_valid(email):
    """Check if email has valid MX using email-validator library."""
    result = validate_email_address(email)
    return result.get("valid", False), result.get("has_mx", False)


def main():
    if len(sys.argv) < 3:
        print("Usage: email_hunter.py FIRSTNAME LASTNAME [USERNAME]")
        print("Example: email_hunter.py luigi savino luigisav")
        sys.exit(1)

    first = sys.argv[1].lower()
    last = sys.argv[2].lower()
    user = sys.argv[3].lower() if len(sys.argv) > 3 else f"{first}{last}"
    target_name = f"{first} {last}"

    # ── TIER SYSTEM ──
    # Tier 1 domains: most common, check always
    tier1_domains = ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com"]
    # Tier 2 domains: check only if tier 1 has results
    tier2_domains = ["icloud.com", "protonmail.com", "libero.it", "virgilio.it",
                     "tim.it", "fastwebnet.it", "tiscali.it", "alice.it"]
    
    # Tier 1 patterns: most likely real
    tier1_patterns = [
        f"{first}.{last}", f"{first}{last}", f"{last}.{first}",
        f"{first[0]}.{last}", f"{user}", f"{first}.{last[0]}",
    ]
    # Tier 2 patterns: less likely
    tier2_patterns = [
        f"{last}{first}", f"{first[0]}{last}",
        f"{first}_{last}", f"{last}_{first}",
        f"{first}.{last}1", f"{first}{last}1",
    ]

    tier1_emails = list(dict.fromkeys(f"{p}@{d}" for p in tier1_patterns for d in tier1_domains))
    tier2_emails = list(dict.fromkeys(f"{p}@{d}" for p in (tier1_patterns + tier2_patterns) for d in tier2_domains))
    # Remove duplicates from tier2 that are in tier1
    tier2_emails = [e for e in tier2_emails if e not in tier1_emails]

    print(f"[*] Email Hunter v2: {first.title()} {last.title()}")
    print(f"[*] Username: {user}")
    print(f"[*] Tier 1: {len(tier1_emails)} emails (priority)")
    print(f"[*] Tier 2: {len(tier2_emails)} emails (extended)")
    print()

    results = []
    tier1_hits = 0

    # ── PHASE 1: MX Validation (fast, filters out invalid domains) ──
    print("[Phase 1] Email syntax + MX validation...")
    valid_tier1 = []
    for email in tier1_emails:
        is_valid, has_mx = check_mx_valid(email)
        if is_valid:
            valid_tier1.append((email, has_mx))
        else:
            pass  # silently skip invalid
    print(f"  {len(valid_tier1)}/{len(tier1_emails)} tier 1 emails have valid syntax/domain")

    # ── PHASE 2: EmailRep check (top patterns, gmail only) ──
    print("\n[Phase 2] EmailRep reputation check...")
    top_emails = [f"{p}@gmail.com" for p in tier1_patterns[:4]]
    for email in top_emails:
        rep = check_emailrep(email)
        if rep and rep.get("reputation") not in ("none", None):
            service_count = len(rep.get("details", {}).get("profiles", []))
            fp = quick_score_email(email, ["emailrep"], target_name, service_count=service_count)
            print(f"  [{fp['confidence']}] {email} — reputation: {rep.get('reputation')}, profiles: {rep.get('details', {}).get('profiles', 'N/A')}")
            results.append({"email": email, "source": "emailrep", "services": [f"reputation:{rep.get('reputation')}"], "fp": fp})
            tier1_hits += 1
        time.sleep(1)

    # ── PHASE 3: Holehe check (tier 1 first) ──
    print("\n[Phase 3] Holehe registration check (Tier 1)...")
    for i, (email, has_mx) in enumerate(valid_tier1):
        services = check_holehe(email)
        real_services = [s for s in services if not s.startswith("ERROR")]
        
        service_count = len(real_services)
        fp = quick_score_email(email, ["holehe"], target_name, service_count=service_count)
        
        if real_services:
            print(f"  [{fp['confidence']}] {email} — registered on: {', '.join(real_services[:5])}")
            results.append({"email": email, "source": "holehe", "services": real_services, "fp": fp})
            tier1_hits += 1
        elif fp["score"] < 6:
            # Valid domain but no services — still track if MX is good
            if has_mx:
                print(f"  [{fp['confidence']}] {email} — valid MX, no registrations found")
        
        if i % 3 == 2:
            print(f"  ... checked {i+1}/{len(valid_tier1)}")
        time.sleep(2)

    # ── PHASE 4: Tier 2 (only if tier 1 had hits) ──
    if tier1_hits > 0:
        print(f"\n[Phase 4] Tier 2 extended check ({len(tier2_emails)} emails)...")
        valid_tier2 = []
        for email in tier2_emails:
            is_valid, has_mx = check_mx_valid(email)
            if is_valid and has_mx:
                valid_tier2.append(email)
        
        print(f"  {len(valid_tier2)}/{len(tier2_emails)} tier 2 emails have valid MX")
        
        for i, email in enumerate(valid_tier2[:12]):  # Cap at 12 to avoid slowness
            services = check_holehe(email)
            real_services = [s for s in services if not s.startswith("ERROR")]
            
            if real_services:
                fp = quick_score_email(email, ["holehe"], target_name, service_count=len(real_services))
                print(f"  [{fp['confidence']}] {email} — registered on: {', '.join(real_services[:5])}")
                results.append({"email": email, "source": "holehe", "services": real_services, "fp": fp})
            time.sleep(2)
    else:
        print("\n[Phase 4] Skipping tier 2 — no tier 1 hits")

    # ── SUMMARY ──
    print("\n" + "="*60)
    print("EMAIL HUNTER RESULTS")
    print("="*60)
    
    if results:
        # Sort by FP score (lowest = most confident)
        results.sort(key=lambda r: r.get("fp", {}).get("score", 10))
        
        seen = set()
        included = 0
        flagged = 0
        rejected = 0
        
        for r in results:
            if r["email"] not in seen:
                seen.add(r["email"])
                fp = r.get("fp", {})
                conf = fp.get("confidence", "UNKNOWN")
                score = fp.get("score", "?")
                action = fp.get("action", "include")
                
                if action == "reject":
                    rejected += 1
                    print(f"\n  REJECTED: {r['email']} (FP score: {score}/10)")
                    for reason in fp.get("reasons", []):
                        print(f"    {reason}")
                elif action == "flag":
                    flagged += 1
                    print(f"\n  REVIEW: {r['email']} [{conf}] (FP score: {score}/10)")
                    print(f"  Source: {r['source']}")
                    print(f"  Services: {', '.join(r['services'][:8])}")
                else:
                    included += 1
                    print(f"\n  [{conf}] {r['email']} (FP score: {score}/10)")
                    print(f"  Source: {r['source']}")
                    print(f"  Services: {', '.join(r['services'][:8])}")
        
        print(f"\n  Summary: {included} included, {flagged} flagged, {rejected} rejected")
    else:
        print("  No confirmed emails found.")
        print("  Try: check GitHub commits, breach databases, or Google dorking.")
    print("="*60)

if __name__ == "__main__":
    main()
