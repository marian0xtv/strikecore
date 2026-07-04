#!/bin/sh
# Toolbox entrypoint — point proxychains at the tor container's *numeric* IP.
#
# proxychains-ng refuses a hostname for the first proxy in the chain (the first
# hop must be reached directly; it can't resolve its own DNS through itself), so
# a bare "socks5 tor 9050" errors with "proxy tor has invalid value or is not
# numeric". The tor container's IP is assigned by Docker and can change on every
# recreation, so we resolve it at start and rewrite the ProxyList in place.
#
# We rewrite via a temp file + redirect (not `sed -i`): the container runs as a
# non-root user that can write the 0666 config file but NOT create the temp file
# `sed -i` needs in root-owned /etc.
set -e

CONF=/etc/proxychains4.conf
TOR_IP=$(getent hosts "${TOR_HOST:-tor}" 2>/dev/null | awk '{print $1; exit}')

if [ -n "$TOR_IP" ] && [ -w "$CONF" ]; then
    tmp=$(mktemp)
    if sed -E "s/^socks5[[:space:]].*/socks5  ${TOR_IP}  ${TOR_SOCKS_PORT:-9050}/" "$CONF" > "$tmp"; then
        cat "$tmp" > "$CONF"
    fi
    rm -f "$tmp"
fi

exec "$@"
