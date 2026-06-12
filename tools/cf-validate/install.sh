#!/usr/bin/env bash
# install.sh — install sc-cf-validate into StrikeCore (mirrors install-daprofiler.sh).
#
# cf-validate is offline & first-party, so there is no upstream clone or venv:
# install_method = symlink-only. The wrapper is symlinked onto PATH.
#
# Usage: bash tools/cf-validate/install.sh

set -euo pipefail

TOOL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
WRAPPER_SRC="${TOOL_DIR}/sc-cf-validate.py"
WRAPPER_DST="${BIN_DIR}/sc-cf-validate"

echo "[cf-validate] Installing..."

if [ ! -f "${WRAPPER_SRC}" ]; then
    echo "[cf-validate] ERROR: wrapper not found at ${WRAPPER_SRC}"
    exit 1
fi

mkdir -p "${BIN_DIR}"
chmod +x "${WRAPPER_SRC}"
ln -sf "${WRAPPER_SRC}" "${WRAPPER_DST}"
echo "[cf-validate] Wrapper linked: ${WRAPPER_DST}"

# Self-test gate (offline, no real targets) ----------------------------------
echo "[cf-validate] Running self-test..."
if python3 "${WRAPPER_SRC}" --selftest --json >/dev/null; then
    echo "[cf-validate] Self-test PASSED."
else
    echo "[cf-validate] ERROR: self-test FAILED — not registering."
    exit 1
fi

if command -v sc-cf-validate >/dev/null 2>&1; then
    echo "[cf-validate] OK — sc-cf-validate is on PATH."
else
    echo "[cf-validate] NOTE: add ${BIN_DIR} to PATH:"
    echo '    export PATH="$HOME/.local/bin:$PATH"'
fi

echo ""
echo "cf-validate installed. Usage:"
echo "  sc-cf-validate RSSMRA85T10A562S"
echo "  sc-cf-validate --json RSSMRA85T10A562S"
