#!/usr/bin/env bash
# test_selftest.sh — offline conformance test for cf-validate.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="${HERE}/../sc-cf-validate.py"

fail() { echo "FAIL: $1" >&2; exit 1; }

# 1) --selftest must exit 0 and report no errors
out="$(python3 "${WRAPPER}" --selftest --json)" || fail "--selftest exit != 0"
echo "${out}" | python3 -c 'import json,sys; e=json.load(sys.stdin); assert e["audit"]["selftest"] is True; assert e["errors"]==[], e["errors"]' || fail "selftest envelope bad"

# 2) a known-good CF validates (exit 0)
python3 "${WRAPPER}" RSSMRA85T10A562S >/dev/null || fail "known-good CF rejected"

# 3) a known-bad CF is rejected (exit 1)
if python3 "${WRAPPER}" RSSMRA85T10A562X >/dev/null; then
    fail "known-bad CF accepted"
fi

# 4) usage error on no argument (exit 2)
python3 "${WRAPPER}" >/dev/null 2>&1 && fail "missing-arg should be usage error" || true

echo "PASS: cf-validate self-test"
