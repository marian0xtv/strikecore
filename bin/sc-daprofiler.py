#!/usr/bin/env python3
"""sc-daprofiler — StrikeCore wrapper for DaProfiler.

Runs DaProfiler against a person target, normalises its output into the
StrikeCore OSINT JSON schema, and deliberately **omits phone numbers**
(CLAUDE.md §3.4 — phones come only from phone-specific tools).

Usage:
    sc-daprofiler -f "Mario" -l "Rossi"
    sc-daprofiler -f "Mario" -l "Rossi" -c "Acme SpA" -loc "Roma"
    sc-daprofiler "Mario Rossi"          # convenience: split on first space

Output (stdout, JSON):
    {
      "tool": "daprofiler",
      "target": "Mario Rossi",
      "timestamp": "...",
      "normalized": {
        "emails": [...],
        "social_profiles": [{"platform": "...", "url": "..."}],
        "addresses": [...],
        "org": "...",
        "photos": [...]
      },
      "raw": { ... }    # original DaProfiler JSON, phones_stripped=true
    }

Exit codes:
    0  success (JSON on stdout)
    1  DaProfiler execution error (JSON with error key on stdout)
    2  usage error
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

INSTALL_DIR = Path.home() / ".local" / "share" / "DaProfiler"
VENV_PYTHON = INSTALL_DIR / ".venv" / "bin" / "python3"
DAPROFILER_PY = INSTALL_DIR / "DaProfiler.py"

# Phone-related keys to strip from raw output (§3.4 doctrine)
_PHONE_KEYS = {"phone", "phones", "phone_numbers", "phone_number", "telephone", "tel"}


def _strip_phones(obj: object) -> object:
    """Recursively remove phone-related keys from a parsed JSON object."""
    if isinstance(obj, dict):
        return {
            k: _strip_phones(v)
            for k, v in obj.items()
            if k.lower() not in _PHONE_KEYS
        }
    if isinstance(obj, list):
        return [_strip_phones(i) for i in obj]
    return obj


def _normalise(raw: dict) -> dict:
    """Map DaProfiler raw output → StrikeCore normalised schema."""
    emails: list[str] = []
    social_profiles: list[dict] = []
    addresses: list[str] = []
    org: str = ""
    photos: list[str] = []

    # Emails
    for key in ("emails", "email", "email_addresses"):
        val = raw.get(key, [])
        if isinstance(val, list):
            emails.extend(str(e).strip() for e in val if e)
        elif isinstance(val, str) and val.strip():
            emails.append(val.strip())

    # Social profiles — DaProfiler may return a dict or a list
    for key in ("social_accounts", "social", "social_media", "profiles"):
        val = raw.get(key)
        if isinstance(val, dict):
            for platform, url in val.items():
                if url and isinstance(url, str) and url.startswith("http"):
                    social_profiles.append({"platform": str(platform), "url": url.strip()})
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    url = item.get("url") or item.get("link") or ""
                    platform = item.get("platform") or item.get("site") or "unknown"
                    if url and url.startswith("http"):
                        social_profiles.append({"platform": str(platform), "url": url.strip()})
                elif isinstance(item, str) and item.startswith("http"):
                    social_profiles.append({"platform": "unknown", "url": item.strip()})

    # Addresses
    for key in ("addresses", "address", "locations", "location"):
        val = raw.get(key, [])
        if isinstance(val, list):
            addresses.extend(str(a).strip() for a in val if a)
        elif isinstance(val, str) and val.strip():
            addresses.append(val.strip())

    # Organisation / employer
    for key in ("company", "employer", "job_info", "org", "organisation", "organization"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            org = val.strip()
            break
        if isinstance(val, dict):
            name = val.get("name") or val.get("company") or ""
            if isinstance(name, str) and name.strip():
                org = name.strip()
                break

    # Photos
    for key in ("photos", "images", "face_recognition", "face_matches"):
        val = raw.get(key, [])
        if isinstance(val, list):
            for item in val:
                url = item if isinstance(item, str) else (
                    item.get("url") or item.get("image") or item.get("photo") or ""
                    if isinstance(item, dict) else ""
                )
                if url and isinstance(url, str) and url.startswith("http"):
                    photos.append(url.strip())

    return {
        "emails": list(dict.fromkeys(emails)),           # deduplicated, order-preserving
        "social_profiles": social_profiles,
        "addresses": list(dict.fromkeys(addresses)),
        "org": org,
        "photos": list(dict.fromkeys(photos)),
    }


def _run_daprofiler(first: str, last: str, company: str, location: str) -> dict:
    """Execute DaProfiler and return parsed JSON output."""
    if not DAPROFILER_PY.exists():
        return {
            "error": f"DaProfiler not found at {DAPROFILER_PY}. Run: bash bin/install-daprofiler.sh",
            "tool": "daprofiler",
        }

    python_bin = str(VENV_PYTHON) if VENV_PYTHON.exists() else "python3"

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        out_path = tmp.name

    try:
        cmd = [
            python_bin, str(DAPROFILER_PY),
            "-f", first,
            "-l", last,
            "-o", out_path,
        ]
        if company:
            cmd += ["-c", company]
        if location:
            cmd += ["-loc", location]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(INSTALL_DIR),
        )

        if result.returncode != 0 and not Path(out_path).stat().st_size:
            return {
                "error": f"DaProfiler exited {result.returncode}: {result.stderr[:500]}",
                "stdout": result.stdout[:500],
            }

        raw_text = Path(out_path).read_text(encoding="utf-8", errors="replace")
        if not raw_text.strip():
            # Some DaProfiler versions print JSON to stdout rather than -o
            raw_text = result.stdout

        try:
            raw_json = json.loads(raw_text)
        except json.JSONDecodeError:
            # DaProfiler may write multiple JSON objects (one per module) — wrap them
            objects = []
            decoder = json.JSONDecoder()
            pos = 0
            raw_text_stripped = raw_text.strip()
            while pos < len(raw_text_stripped):
                try:
                    obj, idx = decoder.raw_decode(raw_text_stripped, pos)
                    objects.append(obj)
                    pos = idx
                    while pos < len(raw_text_stripped) and raw_text_stripped[pos] in " \n\r\t,":
                        pos += 1
                except json.JSONDecodeError:
                    break
            raw_json = objects[0] if len(objects) == 1 else {"results": objects} if objects else {}

        return raw_json if isinstance(raw_json, dict) else {"results": raw_json}

    except subprocess.TimeoutExpired:
        return {"error": "DaProfiler timed out after 300 seconds"}
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


def _build_output(target: str, raw: dict) -> dict:
    raw_clean = _strip_phones(raw)
    return {
        "tool": "daprofiler",
        "target": target,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "phones_stripped": True,
        "normalized": _normalise(raw),
        "raw": raw_clean,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="sc-daprofiler",
        description="StrikeCore wrapper for DaProfiler — person OSINT aggregator.",
        epilog='Example: sc-daprofiler -f "Mario" -l "Rossi" -c "Acme SpA"',
    )
    parser.add_argument("positional", nargs="?", help='Full name as single string e.g. "Mario Rossi"')
    parser.add_argument("-f", "--first", help="First name")
    parser.add_argument("-l", "--last", help="Last name")
    parser.add_argument("-c", "--company", default="", help="Company / employer filter")
    parser.add_argument("-loc", "--location", default="", help="Location filter")
    args = parser.parse_args()

    # Resolve first/last from positional or flags
    first = args.first or ""
    last = args.last or ""
    if not (first and last) and args.positional:
        parts = args.positional.strip().split(None, 1)
        if len(parts) == 2:
            first, last = parts
        else:
            first = parts[0]

    if not first or not last:
        parser.print_usage(sys.stderr)
        sys.stderr.write("sc-daprofiler: error: provide both first (-f) and last (-l) name\n")
        return 2

    target = f"{first} {last}"
    raw = _run_daprofiler(first, last, args.company, args.location)

    if "error" in raw and not raw.get("normalized"):
        output = _build_output(target, raw)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 1

    output = _build_output(target, raw)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
