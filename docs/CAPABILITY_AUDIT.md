# Toolbox per-tool capability audit (task T10 — run before finalizing the toolbox)

The toolbox container ships `cap_add: [NET_RAW, NET_ADMIN]` on the bridge net by
default. That covers most tools. This audit pins which tools need MORE than that
(host networking / L2 access), because those would have to split out into a
privileged, `network_mode: host` service like the VoIP/Asterisk one — which can
move the topology. **Decide this before treating the toolbox image as final.**

How to read the allowlist: `core/executor.py` → `ALLOWED_BINARIES` (333 unique
entries; ~157 are actual OSINT tools installed on disk, the rest are shell/system
builtins already present in the base image).

## Buckets

| Bucket | Needs | Example tools | Container handling |
|--------|-------|---------------|--------------------|
| Plain HTTP/DNS clients | nothing special | sherlock, holehe, theHarvester, sqlmap, nikto, whatweb, curl, dnsrecon, subfinder, httpx | bridge net, no caps |
| Raw-socket scanners | `NET_RAW` (+`NET_ADMIN`) | nmap (`-sS`/`-sU`), masscan, hping3, naabu | bridge net + caps (current default) — **verify** |
| Layer-2 / sniffing / MITM | host network + `NET_RAW`/`NET_ADMIN` | responder, bettercap, ettercap, arpspoof, arp-scan, netdiscover, tcpdump/tshark | **likely needs `network_mode: host`** — split out like voip |
| Wireless | host net + special device access | aircrack-ng, airodump-ng, wifite, reaver, kismet | host + device passthrough; probably out of scope for a LAN box |
| Tor-routed | proxychains → tor container | holehe, sherlock, maigret, gallery-dl, h8mail, etc. (see `RATE_LIMITED_TOOLS`) | bridge net (already wired) |

## Action
1. Walk `ALLOWED_BINARIES`; tag each installed tool into a bucket above.
2. If the L2/sniffing bucket has tools you actually use, decide:
   - run the whole toolbox `network_mode: host` (simplest, less isolation), OR
   - add a second privileged `toolbox-hostnet` service for just those tools and
     route those jobs there.
3. Record the decision here and update `docker-compose.yml` accordingly.

Until this is done, raw-socket scans work (caps are present) but L2/MITM tools
will fail silently on the bridge net — that's the gap this audit closes.
