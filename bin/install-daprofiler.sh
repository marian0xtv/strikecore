#!/usr/bin/env bash
# install-daprofiler.sh — Install DaProfiler and wire it into StrikeCore.
#
# What this does:
#   1. Clones DaProfiler to ~/.local/share/DaProfiler
#   2. Creates a Python venv and installs its dependencies
#   3. Symlinks bin/sc-daprofiler.py → ~/.local/bin/sc-daprofiler
#
# Usage:
#   bash bin/install-daprofiler.sh [--upgrade]

set -euo pipefail

REPO_URL="https://github.com/daprofiler/DaProfiler.git"
INSTALL_DIR="${HOME}/.local/share/DaProfiler"
BIN_DIR="${HOME}/.local/bin"
WRAPPER_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/sc-daprofiler.py"
WRAPPER_DST="${BIN_DIR}/sc-daprofiler"
UPGRADE="${1:-}"

echo "[sc-daprofiler] Installing DaProfiler..."

# -- Clone or update ----------------------------------------------------------
if [ -d "${INSTALL_DIR}/.git" ]; then
    if [ "${UPGRADE}" = "--upgrade" ]; then
        echo "[sc-daprofiler] Updating existing clone..."
        git -C "${INSTALL_DIR}" pull --ff-only || echo "[sc-daprofiler] WARNING: git pull failed (archived repo?), continuing."
    else
        echo "[sc-daprofiler] DaProfiler already cloned at ${INSTALL_DIR} (use --upgrade to refresh)."
    fi
else
    echo "[sc-daprofiler] Cloning DaProfiler..."
    git clone --depth 1 "${REPO_URL}" "${INSTALL_DIR}"
fi

# -- Python venv --------------------------------------------------------------
VENV="${INSTALL_DIR}/.venv"
if [ ! -d "${VENV}" ]; then
    echo "[sc-daprofiler] Creating venv at ${VENV}..."
    python3 -m venv "${VENV}"
fi

echo "[sc-daprofiler] Installing Python dependencies..."
"${VENV}/bin/pip" install --quiet --upgrade pip

REQ="${INSTALL_DIR}/requirements.txt"
if [ -f "${REQ}" ]; then
    "${VENV}/bin/pip" install --quiet -r "${REQ}" || {
        echo "[sc-daprofiler] WARNING: some dependencies failed — face-recognition/dlib may need libcmake."
        echo "[sc-daprofiler] Core OSINT features (email/social) will still work."
    }
else
    echo "[sc-daprofiler] WARNING: requirements.txt not found at ${INSTALL_DIR}."
fi

# -- Symlink wrapper ----------------------------------------------------------
mkdir -p "${BIN_DIR}"
if [ ! -f "${WRAPPER_SRC}" ]; then
    echo "[sc-daprofiler] ERROR: wrapper not found at ${WRAPPER_SRC}"
    exit 1
fi

ln -sf "${WRAPPER_SRC}" "${WRAPPER_DST}"
chmod +x "${WRAPPER_SRC}"
echo "[sc-daprofiler] Wrapper linked: ${WRAPPER_DST}"

# -- Verify -------------------------------------------------------------------
if command -v sc-daprofiler >/dev/null 2>&1; then
    echo "[sc-daprofiler] OK — sc-daprofiler is on PATH."
else
    echo "[sc-daprofiler] NOTE: add ${BIN_DIR} to your PATH if not already there:"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

echo ""
echo "DaProfiler installed. Usage:"
echo "  sc-daprofiler -f \"Mario\" -l \"Rossi\""
echo "  sc-daprofiler -f \"Mario\" -l \"Rossi\" -c \"Acme SpA\" -loc \"Roma\""
echo ""
echo "Note: DaProfiler requires Firefox (geckodriver) for Selenium modules."
echo "Note: LinkedIn credential setup → edit:"
echo "  ${INSTALL_DIR}/modules/social_medias/linkedin_search.py"
