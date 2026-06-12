#!/usr/bin/env bash
# install.sh — TEMPLATE installer (mirrors bin/install-daprofiler.sh).
#
# For an upstream tool: clone (pinned), venv, pip install, then symlink the
# wrapper. For a first-party/offline tool, drop the clone/venv and use
# install_method=symlink-only (see tools/cf-validate/install.sh).
#
# Usage: bash tools/<name>/install.sh [--upgrade]

set -euo pipefail

TOOL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
WRAPPER_SRC="${TOOL_DIR}/sc-__TOOLNAME__.py"
WRAPPER_DST="${BIN_DIR}/sc-__TOOLNAME__"

# --- upstream (replace with the pinned repo + commit from tool.manifest.json) -
# REPO_URL="https://github.com/__OWNER__/__REPO__.git"
# PINNED_COMMIT="__GIT_SHA__"
# INSTALL_DIR="${HOME}/.local/share/__TOOLNAME__"
# if [ ! -d "${INSTALL_DIR}/.git" ]; then
#     git clone "${REPO_URL}" "${INSTALL_DIR}"
# fi
# git -C "${INSTALL_DIR}" checkout "${PINNED_COMMIT}"
# python3 -m venv "${INSTALL_DIR}/.venv"
# "${INSTALL_DIR}/.venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

mkdir -p "${BIN_DIR}"
chmod +x "${WRAPPER_SRC}"
ln -sf "${WRAPPER_SRC}" "${WRAPPER_DST}"
echo "[__TOOLNAME__] Wrapper linked: ${WRAPPER_DST}"

echo "[__TOOLNAME__] Running self-test..."
python3 "${WRAPPER_SRC}" --selftest --json >/dev/null \
    && echo "[__TOOLNAME__] Self-test PASSED." \
    || { echo "[__TOOLNAME__] Self-test FAILED — not registering."; exit 1; }
