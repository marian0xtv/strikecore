"""
API integrations manager for StrikeCore SOCINT/GEOINT.

Manages API keys and provides helper methods for external intelligence APIs.
Configure keys in ~/.strikecore/config.toml under [apis].
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API registry — add new APIs here
# ---------------------------------------------------------------------------

API_CATALOG: list[dict[str, str]] = [
    # SOCINT APIs
    {"name": "hunter_io", "env": "HUNTER_API_KEY", "config_key": "apis.hunter_io", "url": "https://hunter.io", "desc": "Email finder and verifier"},
    {"name": "haveibeenpwned", "env": "HIBP_API_KEY", "config_key": "apis.haveibeenpwned", "url": "https://haveibeenpwned.com/API/v3", "desc": "Breach database lookup"},
    {"name": "dehashed", "env": "DEHASHED_API_KEY", "config_key": "apis.dehashed", "url": "https://dehashed.com", "desc": "Breach data search engine"},
    {"name": "intelx", "env": "INTELX_API_KEY", "config_key": "apis.intelx", "url": "https://intelx.io", "desc": "Intelligence X search"},
    {"name": "fullcontact", "env": "FULLCONTACT_API_KEY", "config_key": "apis.fullcontact", "url": "https://fullcontact.com", "desc": "Person/company enrichment"},
    {"name": "pipl", "env": "PIPL_API_KEY", "config_key": "apis.pipl", "url": "https://pipl.com", "desc": "People search engine"},
    {"name": "emailrep", "env": "EMAILREP_API_KEY", "config_key": "apis.emailrep", "url": "https://emailrep.io", "desc": "Email reputation scoring"},
    {"name": "numverify", "env": "NUMVERIFY_API_KEY", "config_key": "apis.numverify", "url": "https://numverify.com", "desc": "Phone number validation"},
    {"name": "twilio", "env": "TWILIO_API_KEY", "config_key": "apis.twilio", "url": "https://twilio.com", "desc": "Phone carrier lookup"},
    {"name": "social_links", "env": "SOCIALLINKS_API_KEY", "config_key": "apis.social_links", "url": "https://sociallinks.io", "desc": "Social media intelligence"},
    # GEOINT APIs
    {"name": "ipinfo", "env": "IPINFO_TOKEN", "config_key": "apis.ipinfo", "url": "https://ipinfo.io", "desc": "IP geolocation and ASN data"},
    {"name": "ipgeolocation", "env": "IPGEO_API_KEY", "config_key": "apis.ipgeolocation", "url": "https://ipgeolocation.io", "desc": "IP geolocation with timezone"},
    {"name": "shodan", "env": "SHODAN_API_KEY", "config_key": "apis.shodan", "url": "https://shodan.io", "desc": "Internet device search"},
    {"name": "censys", "env": "CENSYS_API_ID", "config_key": "apis.censys_id", "url": "https://censys.io", "desc": "Internet-wide scanning"},
    {"name": "wigle", "env": "WIGLE_API_KEY", "config_key": "apis.wigle", "url": "https://wigle.net", "desc": "WiFi network geolocation"},
    {"name": "opencellid", "env": "OPENCELLID_API_KEY", "config_key": "apis.opencellid", "url": "https://opencellid.org", "desc": "Cell tower geolocation"},
    {"name": "google_maps", "env": "GOOGLE_MAPS_API_KEY", "config_key": "apis.google_maps", "url": "https://maps.googleapis.com", "desc": "Google Maps geocoding/places"},
    {"name": "maxmind", "env": "MAXMIND_LICENSE_KEY", "config_key": "apis.maxmind", "url": "https://maxmind.com", "desc": "GeoIP2 database"},
    # General OSINT APIs
    {"name": "virustotal", "env": "VT_API_KEY", "config_key": "apis.virustotal", "url": "https://virustotal.com", "desc": "File/URL/IP analysis"},
    {"name": "abuseipdb", "env": "ABUSEIPDB_API_KEY", "config_key": "apis.abuseipdb", "url": "https://abuseipdb.com", "desc": "IP abuse reporting/checking"},
    {"name": "greynoise", "env": "GREYNOISE_API_KEY", "config_key": "apis.greynoise", "url": "https://greynoise.io", "desc": "Internet background noise"},
    {"name": "urlscan", "env": "URLSCAN_API_KEY", "config_key": "apis.urlscan", "url": "https://urlscan.io", "desc": "URL scanning and analysis"},
    {"name": "securitytrails", "env": "SECURITYTRAILS_API_KEY", "config_key": "apis.securitytrails", "url": "https://securitytrails.com", "desc": "DNS/domain intelligence"},
    {"name": "binaryedge", "env": "BINARYEDGE_API_KEY", "config_key": "apis.binaryedge", "url": "https://binaryedge.io", "desc": "Internet scanning platform"},
    {"name": "spyse", "env": "SPYSE_API_KEY", "config_key": "apis.spyse", "url": "https://spyse.com", "desc": "Cybersecurity search engine"},
]


class APIManager:
    """Manages API keys and provides quick-call methods."""

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings
        self._keys: Dict[str, str] = {}
        self._load_keys()

    def _load_keys(self) -> None:
        """Load API keys from settings and environment variables."""
        for api in API_CATALOG:
            # Try environment variable first
            key = os.environ.get(api["env"], "")
            # Fall back to config file
            if not key and self._settings:
                key = self._settings.get(api["config_key"], "") or ""
            if key:
                self._keys[api["name"]] = key

    def get_key(self, api_name: str) -> str:
        """Return the API key for a given service, or empty string."""
        return self._keys.get(api_name, "")

    def has_key(self, api_name: str) -> bool:
        return bool(self._keys.get(api_name))

    def list_apis(self) -> list[dict[str, Any]]:
        """Return all APIs with their configuration status."""
        result = []
        for api in API_CATALOG:
            result.append({
                "name": api["name"],
                "url": api["url"],
                "desc": api["desc"],
                "configured": self.has_key(api["name"]),
                "env_var": api["env"],
                "config_key": api["config_key"],
            })
        return result

    # -- Quick API calls --------------------------------------------------

    async def ipinfo_lookup(self, ip: str) -> Dict[str, Any]:
        """Lookup IP geolocation via ipinfo.io."""
        token = self.get_key("ipinfo")
        url = f"https://ipinfo.io/{ip}/json"
        params = {"token": token} if token else {}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            return resp.json()

    async def ip_api_lookup(self, ip: str) -> Dict[str, Any]:
        """Free IP geolocation via ip-api.com (no key needed)."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"http://ip-api.com/json/{ip}")
            return resp.json()

    async def abuseipdb_check(self, ip: str) -> Dict[str, Any]:
        """Check IP reputation via AbuseIPDB."""
        key = self.get_key("abuseipdb")
        if not key:
            return {"error": "ABUSEIPDB_API_KEY not configured"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.abuseipdb.com/api/v2/check",
                params={"ipAddress": ip, "maxAgeInDays": 90},
                headers={"Key": key, "Accept": "application/json"},
            )
            return resp.json()

    async def emailrep_check(self, email: str) -> Dict[str, Any]:
        """Check email reputation via EmailRep.io."""
        key = self.get_key("emailrep")
        headers = {"User-Agent": "StrikeCore/1.0"}
        if key:
            headers["Key"] = key
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"https://emailrep.io/{email}", headers=headers)
            return resp.json()

    async def hibp_check(self, email: str) -> list[Dict[str, Any]]:
        """Check email in Have I Been Pwned breaches."""
        key = self.get_key("haveibeenpwned")
        if not key:
            return [{"error": "HIBP_API_KEY not configured"}]
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}",
                headers={"hibp-api-key": key, "User-Agent": "StrikeCore/1.0"},
                params={"truncateResponse": "false"},
            )
            if resp.status_code == 404:
                return []
            return resp.json()

    async def virustotal_lookup(self, ioc: str, ioc_type: str = "ip") -> Dict[str, Any]:
        """Lookup IOC on VirusTotal."""
        key = self.get_key("virustotal")
        if not key:
            return {"error": "VT_API_KEY not configured"}
        type_map = {"ip": "ip_addresses", "domain": "domains", "url": "urls", "hash": "files"}
        endpoint = type_map.get(ioc_type, "ip_addresses")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://www.virustotal.com/api/v3/{endpoint}/{ioc}",
                headers={"x-apikey": key},
            )
            return resp.json()

    async def wigle_search(self, ssid: str = "", lat: float = 0, lon: float = 0, radius: float = 0.01) -> Dict[str, Any]:
        """Search WiFi networks on WiGLE."""
        key = self.get_key("wigle")
        if not key:
            return {"error": "WIGLE_API_KEY not configured"}
        params: Dict[str, Any] = {}
        if ssid:
            params["ssid"] = ssid
        if lat and lon:
            params.update({"latrange1": lat - radius, "latrange2": lat + radius, "longrange1": lon - radius, "longrange2": lon + radius})
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.wigle.net/api/v2/network/search",
                params=params,
                headers={"Authorization": f"Basic {key}"},
            )
            return resp.json()

    async def hunter_search(self, domain: str) -> Dict[str, Any]:
        """Find email addresses for a domain via Hunter.io."""
        key = self.get_key("hunter_io")
        if not key:
            return {"error": "HUNTER_API_KEY not configured"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.hunter.io/v2/domain-search",
                params={"domain": domain, "api_key": key},
            )
            return resp.json()

    async def numverify_lookup(self, phone: str) -> Dict[str, Any]:
        """Validate and lookup phone number via NumVerify."""
        key = self.get_key("numverify")
        if not key:
            return {"error": "NUMVERIFY_API_KEY not configured"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "http://apilayer.net/api/validate",
                params={"access_key": key, "number": phone},
            )
            return resp.json()
