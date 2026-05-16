#!/bin/bash
# strikecore launcher — sources .env (chmod 600) so settings.py env-override
# layer can replace stale values in ~/.strikecore/config.toml without editing
# the toml. See docs/STACK_IMPLEMENTATION.md §8.
cd "$(dirname "$0")"
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi
exec ./strikecore/bin/python3 main.py "$@"
