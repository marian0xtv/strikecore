#!/usr/bin/env python3
"""
StrikeCore IP Logger — Tracking pixel and link shortener with geolocation.

Creates trackable links that log visitor IP, User-Agent, and timestamp.
When a target clicks the link or loads the tracking pixel, their IP is captured
and geolocated automatically.

Methods:
1. Tracking pixel — 1x1 transparent GIF served from our Flask server
2. Redirect link — short URL that redirects to real destination after logging
3. Canary page — hosted page with embedded tracking resources

All logged data stored in ~/strikecore-data/ip_logs/{tracking_id}.json

LEGAL NOTE: This logs publicly available connection metadata (IP address)
when a user voluntarily loads a resource. Same mechanism as web analytics,
email open tracking, and ad tracking pixels. The operator is responsible
for compliance with applicable laws.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

def _data_home() -> Path:
    """Resolve the data home for StrikeCore artifacts.

    Honors ``SUDO_USER`` so tools that must run under ``sudo`` (e.g.
    ``sudo call-sniffer``, which needs raw-capture privileges) still write to
    the invoking operator's home instead of ``/root``. Without this, a
    successful capture lands in ``/root/strikecore-data`` and the dashboard
    (running as the operator) never sees it.
    """
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        try:
            import pwd
            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except (KeyError, ImportError):
            pass
    return Path.home()


LOG_DIR = _data_home() / "strikecore-data" / "ip_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── Shared exclude lists (server/infrastructure IPs to filter out) ──

EXCLUDE_V4_PREFIXES = (
    # Private / reserved
    "10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.",
    "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.",
    "172.29.", "172.30.", "172.31.", "192.168.", "127.", "0.0.0.", "255.",
    "169.254.",
    # Meta / Facebook / WhatsApp / Instagram relay servers
    "31.13.", "157.240.", "179.60.192.", "185.89.218.", "185.89.219.",
    "69.63.", "69.171.", "66.220.", "204.15.20.",
    "129.134.25.", "129.134.26.", "129.134.27.", "129.134.28.",
    "129.134.29.", "129.134.30.", "129.134.31.",
    "163.70.", "163.77.",
    # Telegram
    "91.108.4.", "91.108.6.", "91.108.8.", "91.108.12.", "91.108.16.",
    "91.108.20.", "91.108.56.", "149.154.16", "149.154.17",
    # Google STUN/TURN
    "74.125.", "142.250.", "142.251.", "172.217.", "173.194.", "216.58.",
    "64.233.", "108.177.", "209.85.",
    # Cloudflare TURN
    "104.16.", "104.17.", "104.18.", "104.19.", "104.20.", "104.21.",
    "104.22.", "104.23.", "104.24.", "104.25.",
    "172.67.", "173.245.", "103.21.", "103.22.", "103.31.",
    "141.101.", "108.162.", "190.93.", "188.114.", "197.234.", "198.41.",
    # Amazon / AWS
    "44.248.", "44.244.", "44.238.", "34.214.", "18.237.", "52.94.", "54.239.",
    "3.5.", "13.32.", "13.33.", "13.35.", "13.224.", "13.225.", "13.226.",
    # Microsoft / Azure TURN
    "13.64.", "13.65.", "13.66.", "13.67.", "13.68.", "13.69.", "13.70.",
    "20.33.", "20.36.", "20.37.", "20.38.", "20.39.", "20.40.",
    "52.96.", "52.97.", "52.98.", "52.99.", "52.100.", "52.101.",
    # Twilio TURN
    "34.203.", "54.172.",
)

EXCLUDE_V6_PREFIXES = (
    "2a03:2880:",   # Meta
    "2620:0:1c",    # Facebook
    "2001:67c:4e8:", # Telegram
    "2607:f8b0:",   # Google
    "2400:cb00:",   # Cloudflare
    "fe80:", "::1", "fd",
)


def is_excluded(ip: str) -> bool:
    """Check if an IP belongs to infrastructure/server ranges."""
    if ":" in ip:
        return any(ip.startswith(p) for p in EXCLUDE_V6_PREFIXES)
    return any(ip.startswith(p) for p in EXCLUDE_V4_PREFIXES)


def get_local_ips() -> set[str]:
    """Return set of local IPs on this machine."""
    local = {"127.0.0.1", "::1", "0.0.0.0"}
    try:
        import subprocess
        out = subprocess.check_output(["ip", "-o", "addr", "show"], text=True)
        for line in out.split("\n"):
            m = re.search(r"inet6?\s+([^\s/]+)", line)
            if m:
                local.add(m.group(1))
    except Exception:
        pass
    return local


def geolocate_full(ip: str) -> dict:
    """Multi-API geolocation + Nominatim reverse geocode.

    Chain:
    1. ip-api.com → city, ISP, mobile, proxy, lat/lon
    2. ipwho.is → cross-validate, fill gaps
    3. ipinfo.io → VPN/Tor detection, hostname, company
    4. Nominatim reverse geocode → street address from coords
    """
    geo = _geolocate_ip(ip)

    # Nominatim reverse geocode for street-level detail
    if geo.get("lat") and geo.get("lon"):
        try:
            rg = json.loads(urllib.request.urlopen(
                f"https://nominatim.openstreetmap.org/reverse?"
                f"lat={geo['lat']}&lon={geo['lon']}&format=json&addressdetails=1",
                timeout=5
            ).read())
            addr = rg.get("address", {})
            geo["address"] = rg.get("display_name", "")
            geo["road"] = addr.get("road", "")
            geo["house_number"] = addr.get("house_number", "")
            geo["suburb"] = addr.get("suburb") or addr.get("neighbourhood", "")
            geo["postcode"] = addr.get("postcode", "")
            geo["municipality"] = (addr.get("municipality")
                                   or addr.get("town")
                                   or addr.get("village", ""))
        except Exception:
            pass

    return geo


def generate_tracking_id(target_label: str = "") -> str:
    """Generate a unique tracking ID."""
    raw = f"{target_label}-{time.time()}-{os.getpid()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _geolocate_ip(ip: str) -> dict:
    """Multi-API IP geolocation with fallback chain.

    Queries up to 3 free APIs for maximum accuracy and cross-validation:
    1. ip-api.com (primary — detailed fields, mobile/proxy detection)
    2. ipwho.is (fallback — good accuracy, different data source)
    3. ipinfo.io (fallback — ASN, company, privacy detection)

    Returns merged geo dict with best available data.
    """
    geo = {}

    # --- Primary: ip-api.com ---
    try:
        data = json.loads(urllib.request.urlopen(
            f"http://ip-api.com/json/{ip}?fields=66846719", timeout=5
        ).read())
        if data.get("status") == "success":
            geo = {
                "country": data.get("country", ""),
                "country_code": data.get("countryCode", ""),
                "region": data.get("regionName", ""),
                "city": data.get("city", ""),
                "zip": data.get("zip", ""),
                "lat": data.get("lat", 0),
                "lon": data.get("lon", 0),
                "isp": data.get("isp", ""),
                "org": data.get("org", ""),
                "as": data.get("as", ""),
                "as_name": data.get("asname", ""),
                "mobile": data.get("mobile", False),
                "proxy": data.get("proxy", False),
                "hosting": data.get("hosting", False),
                "timezone": data.get("timezone", ""),
                "district": data.get("district", ""),
                "source": "ip-api",
            }
    except Exception:
        pass

    # --- Fallback 1: ipwho.is (different data source, better for some regions) ---
    if not geo.get("city"):
        try:
            data = json.loads(urllib.request.urlopen(
                f"https://ipwho.is/{ip}", timeout=5
            ).read())
            if data.get("success"):
                geo = {
                    "country": data.get("country", geo.get("country", "")),
                    "country_code": data.get("country_code", ""),
                    "region": data.get("region", ""),
                    "city": data.get("city", ""),
                    "lat": data.get("latitude", 0),
                    "lon": data.get("longitude", 0),
                    "isp": data.get("connection", {}).get("isp", ""),
                    "org": data.get("connection", {}).get("org", ""),
                    "as": f"AS{data.get('connection', {}).get('asn', '')}",
                    "timezone": data.get("timezone", {}).get("id", ""),
                    "source": "ipwho.is",
                }
        except Exception:
            pass

    # --- Fallback 2: ipinfo.io (enrichment — company, privacy, ASN detail) ---
    try:
        data = json.loads(urllib.request.urlopen(
            f"https://ipinfo.io/{ip}/json", timeout=5
        ).read())
        # Enrich with ipinfo data where missing
        if not geo.get("org") and data.get("org"):
            geo["org"] = data["org"]
        if data.get("company"):
            geo["company"] = data["company"].get("name", "")
            geo["company_type"] = data["company"].get("type", "")
        if data.get("privacy"):
            geo["vpn"] = data["privacy"].get("vpn", False)
            geo["tor"] = data["privacy"].get("tor", False)
            geo["relay"] = data["privacy"].get("relay", False)
        if data.get("hostname"):
            geo["hostname"] = data["hostname"]
        # ipinfo gives "loc" as "lat,lon" — use as fallback
        if not geo.get("lat") and data.get("loc"):
            parts = data["loc"].split(",")
            if len(parts) == 2:
                geo["lat"] = float(parts[0])
                geo["lon"] = float(parts[1])
        if not geo.get("city") and data.get("city"):
            geo["city"] = data["city"]
            geo["region"] = data.get("region", "")
            geo["country"] = data.get("country", "")
    except Exception:
        pass

    if not geo:
        geo = {"error": "geolocation failed"}

    return geo


def _parse_device(user_agent: str) -> dict:
    """Extract device, OS, browser, and app info from User-Agent."""
    ua = user_agent.lower()
    info = {}

    # Device type
    if "iphone" in ua:
        info["device"] = "iPhone"
        info["os"] = "iOS"
        m = re.search(r"iphone os (\d+[_\d]*)", ua)
        if m:
            info["os_version"] = m.group(1).replace("_", ".")
    elif "ipad" in ua:
        info["device"] = "iPad"
        info["os"] = "iPadOS"
    elif "android" in ua:
        info["device"] = "Android"
        info["os"] = "Android"
        m = re.search(r"android (\d+[\.\d]*)", ua)
        if m:
            info["os_version"] = m.group(1)
        # Extract device model (after ";" before "Build" or ")")
        m = re.search(r";\s*([^;)]+?)(?:\s*build|[)])", ua)
        if m:
            info["device_model"] = m.group(1).strip()
    elif "windows" in ua:
        info["device"] = "Windows"
        info["os"] = "Windows"
        m = re.search(r"windows nt (\d+\.\d+)", ua)
        if m:
            nt_map = {"10.0": "10/11", "6.3": "8.1", "6.2": "8", "6.1": "7"}
            info["os_version"] = nt_map.get(m.group(1), m.group(1))
    elif "macintosh" in ua or "mac os" in ua:
        info["device"] = "Mac"
        info["os"] = "macOS"
        m = re.search(r"mac os x (\d+[_\d]*)", ua)
        if m:
            info["os_version"] = m.group(1).replace("_", ".")
    elif "linux" in ua:
        info["device"] = "Linux"
        info["os"] = "Linux"
    else:
        info["device"] = "Unknown"

    # In-app browser detection (critical for social tracking)
    if "instagram" in ua:
        info["browser"] = "Instagram In-App"
        info["from_instagram"] = True
        info["from_facebook"] = False
    elif "fbav" in ua or "fban" in ua:
        info["browser"] = "Facebook In-App"
        info["from_instagram"] = False
        info["from_facebook"] = True
    elif "whatsapp" in ua:
        info["browser"] = "WhatsApp In-App"
        info["from_instagram"] = False
        info["from_facebook"] = False
    elif "telegram" in ua:
        info["browser"] = "Telegram In-App"
        info["from_instagram"] = False
        info["from_facebook"] = False
    else:
        info["from_instagram"] = False
        info["from_facebook"] = False
        # Standard browsers
        if "crios" in ua or "crmo" in ua:
            info["browser"] = "Chrome Mobile"
        elif "chrome" in ua and "edg" not in ua:
            info["browser"] = "Chrome"
        elif "safari" in ua and "chrome" not in ua:
            info["browser"] = "Safari"
        elif "firefox" in ua or "fxios" in ua:
            info["browser"] = "Firefox"
        elif "edg" in ua:
            info["browser"] = "Edge"
        elif "opera" in ua or "opr" in ua:
            info["browser"] = "Opera"

    # Screen size hint from UA (some Android browsers include it)
    m = re.search(r"(\d{3,4})x(\d{3,4})", ua)
    if m:
        info["screen_hint"] = f"{m.group(1)}x{m.group(2)}"

    return info


def log_hit(tracking_id: str, ip: str, user_agent: str, referer: str = "",
            extra: dict | None = None) -> dict:
    """Log a tracking hit with IP, UA, multi-API geolocation, and device fingerprint."""
    hit = {
        "tracking_id": tracking_id,
        "timestamp": datetime.now().isoformat(),
        "ip": ip,
        "user_agent": user_agent,
        "referer": referer,
    }

    # Multi-API geolocation
    hit["geo"] = _geolocate_ip(ip)

    # Device/browser/OS parsing
    device_info = _parse_device(user_agent)
    hit.update(device_info)

    if extra:
        hit.update(extra)

    # Save to log file
    log_path = LOG_DIR / f"{tracking_id}.json"
    existing = []
    if log_path.exists():
        try:
            existing = json.loads(log_path.read_text())
        except Exception:
            pass

    existing.append(hit)
    log_path.write_text(json.dumps(existing, indent=2, default=str))

    return hit


def log_device_fingerprint(tracking_id: str, ip: str, fingerprint: dict) -> dict:
    """Log a device fingerprint sent by the browser JS.

    The fingerprint dict may include:
    - canvas_hash, webgl_renderer, webgl_vendor
    - screen_w, screen_h, color_depth, pixel_ratio
    - timezone, language, languages, platform
    - cpu_cores, ram_gb, gpu
    - battery_level, battery_charging
    - touch_points, connection_type, connection_downlink
    - do_not_track, cookies_enabled, local_storage
    """
    log_path = LOG_DIR / f"{tracking_id}_fingerprints.json"
    existing = []
    if log_path.exists():
        try:
            existing = json.loads(log_path.read_text())
        except Exception:
            pass

    entry = {
        "timestamp": datetime.now().isoformat(),
        "ip": ip,
        **fingerprint,
    }
    existing.append(entry)
    log_path.write_text(json.dumps(existing, indent=2, default=str))
    return entry


def get_best_location(tracking_id: str) -> dict:
    """Get the best known location for a tracker, merging IP geo + GPS.

    Priority:
    1. Browser GPS (accuracy 5-30m) — from geo_hit entries
    2. IP geolocation (accuracy 1-50km) — from regular hits

    Returns: {lat, lon, accuracy_m, source, city, country, timestamp}
    """
    hits = get_hits(tracking_id)
    if not hits:
        return {}

    # Look for GPS-precision hits first
    best_gps = None
    for h in reversed(hits):  # most recent first
        if h.get("gps_lat") and h.get("gps_lon"):
            lat, lon = h["gps_lat"], h["gps_lon"]
            if lat != 0 and lon != 0:
                acc = h.get("gps_accuracy_m", 999)
                if best_gps is None or acc < best_gps.get("accuracy_m", 999):
                    best_gps = {
                        "lat": lat, "lon": lon,
                        "accuracy_m": acc,
                        "source": h.get("geo_source", "gps"),
                        "timestamp": h.get("timestamp", ""),
                    }

    if best_gps and best_gps["accuracy_m"] < 500:
        # Enrich GPS with reverse geocode
        try:
            data = json.loads(urllib.request.urlopen(
                f"https://nominatim.openstreetmap.org/reverse?lat={best_gps['lat']}&lon={best_gps['lon']}&format=json",
                timeout=5
            ).read())
            addr = data.get("address", {})
            best_gps["address"] = data.get("display_name", "")
            best_gps["city"] = addr.get("city") or addr.get("town") or addr.get("village", "")
            best_gps["suburb"] = addr.get("suburb") or addr.get("neighbourhood", "")
            best_gps["road"] = addr.get("road", "")
            best_gps["postcode"] = addr.get("postcode", "")
            best_gps["country"] = addr.get("country", "")
        except Exception:
            pass
        return best_gps

    # Fall back to best IP geolocation from real_device hits
    for h in reversed(hits):
        if h.get("hit_type") == "real_device" and h.get("geo", {}).get("lat"):
            geo = h["geo"]
            return {
                "lat": geo["lat"], "lon": geo["lon"],
                "accuracy_m": 25000,  # ~25km for IP geo
                "source": "ip_geolocation",
                "city": geo.get("city", ""),
                "country": geo.get("country", ""),
                "isp": geo.get("isp", ""),
                "timestamp": h.get("timestamp", ""),
            }

    # Any hit with geo
    for h in reversed(hits):
        geo = h.get("geo", {})
        if geo.get("lat"):
            return {
                "lat": geo["lat"], "lon": geo["lon"],
                "accuracy_m": 50000,
                "source": "ip_geolocation",
                "city": geo.get("city", ""),
                "country": geo.get("country", ""),
                "timestamp": h.get("timestamp", ""),
            }

    return {}


def get_hits(tracking_id: str) -> list[dict]:
    """Retrieve all hits for a tracking ID."""
    log_path = LOG_DIR / f"{tracking_id}.json"
    if log_path.exists():
        try:
            return json.loads(log_path.read_text())
        except Exception:
            pass
    return []


def get_fingerprints(tracking_id: str) -> list[dict]:
    """Retrieve device fingerprints for a tracking ID."""
    log_path = LOG_DIR / f"{tracking_id}_fingerprints.json"
    if log_path.exists():
        try:
            return json.loads(log_path.read_text())
        except Exception:
            pass
    return []


def create_canary_domain(tracking_id: str, base_domain: str = "") -> str:
    """Generate a unique subdomain canary.

    When resolved, the DNS query itself reveals the target's DNS resolver IP.
    Use with a domain you control that has a wildcard DNS record + NS logging.

    Example: if base_domain = "probe.yourdomain.com"
    Returns: "a8fed1.probe.yourdomain.com"

    Setup needed: configure your DNS to log all queries for *.probe.yourdomain.com
    Tools: dnstap, passivedns, or Cloudflare DNS analytics.
    """
    return f"{tracking_id}.{base_domain}" if base_domain else f"{tracking_id}.probe.local"


def list_trackers() -> list[dict]:
    """List all tracking IDs with hit counts, GPS status, and device stats."""
    trackers = []
    for f in LOG_DIR.glob("*.json"):
        if f.stem.endswith("_meta") or f.stem.endswith("_fingerprints"):
            continue
        try:
            hits = json.loads(f.read_text())
            real_hits = [h for h in hits if h.get("hit_type") == "real_device"]
            has_gps = any(h.get("gps_lat") and h["gps_lat"] != 0 for h in hits)
            has_fingerprint = (LOG_DIR / f"{f.stem}_fingerprints.json").exists()

            # Get label from meta
            meta_path = LOG_DIR / f"{f.stem}_meta.json"
            label = ""
            if meta_path.exists():
                try:
                    label = json.loads(meta_path.read_text()).get("label", "")
                except Exception:
                    pass

            trackers.append({
                "id": f.stem,
                "label": label,
                "hits": len(hits),
                "real_hits": len(real_hits),
                "last_hit": hits[-1]["timestamp"] if hits else "",
                "ips": list(set(h["ip"] for h in hits)),
                "unique_real_ips": list(set(h["ip"] for h in real_hits)),
                "has_gps": has_gps,
                "has_fingerprint": has_fingerprint,
                "devices": list(set(h.get("device", "?") for h in real_hits)),
            })
        except Exception:
            pass
    return sorted(trackers, key=lambda x: x.get("last_hit", ""), reverse=True)
