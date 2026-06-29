#!/bin/sh
# Tor container entrypoint — generates a torrc with HashedControlPassword from
# the cleartext $TOR_CONTROL_PASSWORD at startup (cookie auth can't cross
# containers, decision I7), then execs tor. Binds Socks + Control to 0.0.0.0 so
# the toolbox/backend on the bridge net can reach them.
set -e

if [ -z "$TOR_CONTROL_PASSWORD" ]; then
    echo "tor-entrypoint: TOR_CONTROL_PASSWORD is required" >&2
    exit 1
fi

HASH="$(tor --hash-password "$TOR_CONTROL_PASSWORD" | tail -n 1)"

cat > /etc/tor/torrc <<EOF
User tor
DataDirectory /var/lib/tor
SocksPort 0.0.0.0:9050
ControlPort 0.0.0.0:9051
HashedControlPassword ${HASH}
EOF

mkdir -p /var/lib/tor
chown -R tor:tor /var/lib/tor 2>/dev/null || true

exec tor -f /etc/tor/torrc
