#!/usr/bin/env bash
# test_selftest.sh — TEMPLATE conformance test. Rename the wrapper reference.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="${HERE}/../sc-TEMPLATE.py"   # <-- rename to sc-<name>.py

out="$(python3 "${WRAPPER}" --selftest --json)" || { echo "FAIL selftest" >&2; exit 1; }
echo "${out}" | python3 -c 'import json,sys; e=json.load(sys.stdin); assert e["audit"]["selftest"] is True; assert e["errors"]==[]' \
    || { echo "FAIL selftest envelope" >&2; exit 1; }
echo "PASS: template self-test"
