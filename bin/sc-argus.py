#!/usr/bin/env python3
"""
StrikeCore Argus Wrapper — Non-interactive 134-module OSINT recon.

Usage:
    sc-argus TARGET                        Run all OSINT-relevant modules
    sc-argus TARGET --module 5             Run specific module by number
    sc-argus TARGET --category network     Run all network modules
    sc-argus TARGET --category web         Run all web modules
    sc-argus TARGET --category security    Run all security modules
    sc-argus TARGET --list                 List all 134 modules
    sc-argus TARGET --modules 1,3,5,10     Run specific modules
"""

import os
import subprocess
import sys
import time

ARGUS_DIR = os.path.expanduser("~/.local/share/argus")
ARGUS_PY = os.path.join(ARGUS_DIR, ".venv", "bin", "python3")
RESULTS_DIR = os.path.join(ARGUS_DIR, "results")

# Key OSINT modules (curated for person/domain recon)
OSINT_MODULES = {
    "network": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    "web": [53, 54, 55, 56, 57, 58, 59, 60, 61, 62],
    "security": [103, 104, 105, 106, 107, 108, 109, 110, 111],
    "quick": [1, 3, 5, 8, 53, 103, 105],  # Fast modules for quick recon
}

# Module name mapping (key ones)
MODULE_NAMES = {
    1: "Associated Hosts",
    2: "ASN Lookup",
    3: "DNS Records",
    5: "WHOIS Lookup",
    8: "Reverse DNS",
    10: "Port Scan",
    13: "Traceroute",
    53: "Web Crawling",
    55: "SSL Certificate",
    57: "Technology Stack",
    103: "Censys Lookup",
    105: "Shodan Lookup",
    107: "Subdomain Enumeration",
    110: "Certificate Transparency",
    111: "Breached Credentials",
}


def run_argus(target, modules=None, timeout_per_module=60):
    """Run Argus modules on a target non-interactively."""
    if modules is None:
        modules = OSINT_MODULES["quick"]

    results = []

    for mod_num in modules:
        mod_name = MODULE_NAMES.get(mod_num, f"Module {mod_num}")
        print(f"\n{'='*50}")
        print(f"  [{mod_num}] {mod_name} → {target}")
        print(f"{'='*50}")

        # Build commands for Argus interactive CLI
        commands = f"use {mod_num}\nset target {target}\nrun\nexit\n"

        try:
            result = subprocess.run(
                [ARGUS_PY, "-m", "argus"],
                input=commands,
                capture_output=True,
                text=True,
                timeout=timeout_per_module,
                cwd=ARGUS_DIR,
                env={**os.environ, "TERM": "xterm", "PATH": os.environ.get("PATH", "")},
            )

            output = result.stdout
            # Clean ANSI codes
            import re
            output = re.sub(r'\x1b\[[0-9;]*m', '', output)
            # Remove banner/prompt noise
            lines = output.split('\n')
            clean_lines = [l for l in lines if l.strip() and
                          not l.startswith('Argus') and
                          not '╭' in l and not '╰' in l and
                          not '│' in l and not '█' in l and
                          not 'Version:' in l and not 'Coded by' in l and
                          not 'argus >' in l.lower() and
                          not 'Exiting' in l]

            clean_output = '\n'.join(clean_lines)

            if clean_output.strip():
                print(clean_output[:2000])
                results.append({
                    "module": mod_num,
                    "name": mod_name,
                    "target": target,
                    "output": clean_output[:3000],
                    "success": True,
                })
            else:
                print("  (no output)")
                results.append({"module": mod_num, "name": mod_name, "success": False})

        except subprocess.TimeoutExpired:
            print(f"  TIMEOUT ({timeout_per_module}s)")
            results.append({"module": mod_num, "name": mod_name, "success": False, "error": "timeout"})
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"module": mod_num, "name": mod_name, "success": False, "error": str(e)})

        time.sleep(1)

    # Summary
    ok = sum(1 for r in results if r.get("success"))
    print(f"\n{'='*50}")
    print(f"  ARGUS COMPLETE: {ok}/{len(results)} modules successful")
    print(f"  Results saved in: {RESULTS_DIR}/{target}/")
    print(f"{'='*50}")

    return results


def list_modules():
    """List all Argus modules."""
    commands = "modules\nexit\n"
    result = subprocess.run(
        [ARGUS_PY, "-m", "argus"],
        input=commands,
        capture_output=True,
        text=True,
        timeout=10,
        cwd=ARGUS_DIR,
        env={**os.environ, "TERM": "xterm"},
    )
    import re
    output = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout)
    for line in output.split('\n'):
        if line.strip() and any(c.isdigit() for c in line[:5]):
            print(line)


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  sc-argus TARGET                      Quick OSINT recon (7 key modules)")
        print("  sc-argus TARGET --all                 Run all 134 modules")
        print("  sc-argus TARGET --category network    Run network modules (1-52)")
        print("  sc-argus TARGET --category web        Run web modules (53-102)")
        print("  sc-argus TARGET --category security   Run security modules (103-134)")
        print("  sc-argus TARGET --modules 1,3,5       Run specific modules")
        print("  sc-argus TARGET --module 5             Run single module")
        print("  sc-argus --list                        List all modules")
        sys.exit(1)

    if sys.argv[1] == "--list":
        list_modules()
        sys.exit(0)

    target = sys.argv[1]
    modules = None

    if "--all" in sys.argv:
        modules = list(range(1, 135))
    elif "--category" in sys.argv:
        idx = sys.argv.index("--category")
        cat = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "quick"
        modules = OSINT_MODULES.get(cat, OSINT_MODULES["quick"])
    elif "--modules" in sys.argv:
        idx = sys.argv.index("--modules")
        modules = [int(x) for x in sys.argv[idx + 1].split(",")]
    elif "--module" in sys.argv:
        idx = sys.argv.index("--module")
        modules = [int(sys.argv[idx + 1])]

    print(f"[*] Argus OSINT Recon — Target: {target}")
    print(f"[*] Modules: {len(modules or OSINT_MODULES['quick'])}")
    run_argus(target, modules)


if __name__ == "__main__":
    main()
