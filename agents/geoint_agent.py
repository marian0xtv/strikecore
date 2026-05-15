"""
GeoINTAgent - Geospatial Intelligence agent.

Performs geospatial intelligence operations including IP geolocation,
image EXIF/GPS extraction, WiFi network geolocation, cell tower lookup,
network infrastructure mapping, and metadata analysis.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class GeoFinding:
    """A single geospatial intelligence data point."""
    category: str
    source_tool: str
    latitude: float | None = None
    longitude: float | None = None
    accuracy_m: float | None = None
    address: str = ""
    country: str = ""
    city: str = ""
    isp: str = ""
    raw_data: dict[str, Any] = field(default_factory=dict)
    context: str = ""


class GeoINTAgent:
    """Geospatial Intelligence agent."""

    name: str = "GeoINTAgent"
    description: str = (
        "Performs comprehensive geospatial intelligence operations including "
        "IP geolocation via multiple providers, image EXIF/GPS extraction, "
        "WiFi network geolocation via WiGLE, cell tower lookups, network "
        "infrastructure mapping with traceroute, document metadata extraction, "
        "and satellite imagery correlation."
    )

    techniques = [
        "ip_geolocation",
        "image_exif",
        "wifi_geolocation",
        "cell_tower_lookup",
        "domain_geo",
        "network_trace",
        "metadata_extraction",
        "address_osint",
        "infrastructure_map",
    ]

    def __init__(self) -> None:
        self.findings: list[GeoFinding] = []

    @classmethod
    def get_all_techniques(cls) -> list[str]:
        return list(cls.techniques)

    def get_commands(self, target: str, technique: str | None = None) -> list[dict[str, str]]:
        """Return tool commands for a given target."""
        target_type = self._detect_target_type(target)
        commands: list[dict[str, str]] = []

        if technique:
            method = getattr(self, f"_cmd_{technique}", None)
            if method:
                commands.extend(method(target, target_type))
            return commands

        # Auto-select based on target type
        if target_type == "ip":
            commands.extend(self._cmd_ip_geolocation(target, target_type))
            commands.extend(self._cmd_network_trace(target, target_type))
        elif target_type == "domain":
            commands.extend(self._cmd_domain_geo(target, target_type))
            commands.extend(self._cmd_network_trace(target, target_type))
        elif target_type == "file":
            commands.extend(self._cmd_image_exif(target, target_type))
            commands.extend(self._cmd_metadata_extraction(target, target_type))
        elif target_type == "coords":
            commands.extend(self._cmd_address_osint(target, target_type))
        elif target_type == "address":
            commands.extend(self._cmd_address_osint(target, target_type))
        else:
            commands.extend(self._cmd_ip_geolocation(target, target_type))

        return commands

    def _detect_target_type(self, target: str) -> str:
        if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', target):
            return "ip"
        if re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9-]*\.)+[a-zA-Z]{2,}$', target):
            return "domain"
        if any(target.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.tiff', '.heic', '.pdf', '.docx']):
            return "file"
        if re.match(r'^-?\d+\.?\d*,\s*-?\d+\.?\d*$', target):
            return "coords"
        return "unknown"

    # -- Technique commands ------------------------------------------------

    def _cmd_ip_geolocation(self, target: str, ttype: str) -> list[dict[str, str]]:
        return [
            {"tool": "curl", "command": f'curl -s "https://ipinfo.io/{target}/json" | jq .', "description": "IP geolocation via ipinfo.io (city, region, org, coords)"},
            {"tool": "curl", "command": f'curl -s "http://ip-api.com/json/{target}?fields=66846719" | jq .', "description": "IP geolocation via ip-api.com (free, detailed)"},
            {"tool": "curl", "command": f'curl -s "https://ipwhois.app/json/{target}" | jq .', "description": "IP WHOIS with geolocation data"},
            {"tool": "geoiplookup", "command": f"geoiplookup {target}", "description": "Local MaxMind GeoIP database lookup"},
            {"tool": "shodan", "command": f"shodan host {target}", "description": "Shodan host info with geolocation and services"},
        ]

    def _cmd_image_exif(self, target: str, ttype: str) -> list[dict[str, str]]:
        return [
            {"tool": "exiftool", "command": f"exiftool -GPS* -DateTimeOriginal -Make -Model -Software {target}", "description": "Extract GPS coordinates and camera info from image"},
            {"tool": "exiftool", "command": f"exiftool -a -u -g1 {target}", "description": "Full EXIF dump grouped by category"},
            {"tool": "mat2", "command": f"mat2 --show {target}", "description": "Show all metadata (MAT2 analysis)"},
            {"tool": "exiftool", "command": f'exiftool -if "$GPSLatitude" -p "https://www.google.com/maps?q=$GPSLatitude,$GPSLongitude" {target}', "description": "Generate Google Maps link from GPS data"},
        ]

    def _cmd_wifi_geolocation(self, target: str, ttype: str) -> list[dict[str, str]]:
        return [
            {"tool": "curl", "command": f'curl -s "https://api.wigle.net/api/v2/network/search?ssid={target}" -H "Authorization: Basic $WIGLE_API_KEY" | jq .results[:5]', "description": "Search WiFi SSID location on WiGLE"},
            {"tool": "curl", "command": f'echo "Manual: Visit https://wigle.net/search?ssid={target} for WiFi geolocation map"', "description": "WiGLE web search for visual mapping"},
        ]

    def _cmd_cell_tower_lookup(self, target: str, ttype: str) -> list[dict[str, str]]:
        # target format: MCC,MNC,LAC,CID
        return [
            {"tool": "curl", "command": f'curl -s "https://opencellid.org/cell/get?key=$OPENCELLID_API_KEY&mcc={target}&format=json" | jq .', "description": "Cell tower geolocation via OpenCellID"},
            {"tool": "curl", "command": f'echo "Manual: Visit https://www.cellmapper.net for visual cell tower mapping"', "description": "CellMapper visual reference"},
        ]

    def _cmd_domain_geo(self, target: str, ttype: str) -> list[dict[str, str]]:
        return [
            {"tool": "dig", "command": f"dig +short {target} A", "description": "Resolve domain to IP addresses"},
            {"tool": "curl", "command": f'curl -s "https://ipinfo.io/$(dig +short {target} | head -1)/json" | jq .', "description": "Geolocate resolved IP of domain"},
            {"tool": "whois", "command": f"whois {target} | grep -iE 'country|city|state|address|registrant'", "description": "WHOIS registrant location data"},
            {"tool": "curl", "command": f'curl -s "https://dns.google/resolve?name={target}&type=A" | jq .', "description": "DNS resolution via Google DoH"},
            {"tool": "traceroute", "command": f"sudo traceroute -I -m 20 {target}", "description": "Trace network path to target"},
        ]

    def _cmd_network_trace(self, target: str, ttype: str) -> list[dict[str, str]]:
        return [
            {"tool": "traceroute", "command": f"sudo traceroute -I -m 25 {target}", "description": "ICMP traceroute to map network hops"},
            {"tool": "mtr", "command": f"mtr -r -c 10 --json {target}", "description": "MTR report with latency and loss per hop"},
            {"tool": "bash", "command": f'for hop in $(traceroute -n -m 20 {target} 2>/dev/null | awk \'{{print $2}}\' | grep -E "^[0-9]"); do echo -n "$hop -> "; curl -s "http://ip-api.com/json/$hop?fields=country,city,isp" | jq -r "[.country,.city,.isp]|join(\\", \\")"; done', "description": "Geolocate each hop in traceroute path"},
        ]

    def _cmd_metadata_extraction(self, target: str, ttype: str) -> list[dict[str, str]]:
        return [
            {"tool": "exiftool", "command": f"exiftool -a -u -g1 {target}", "description": "Full metadata extraction from file"},
            {"tool": "metagoofil", "command": f"metagoofil -d {target} -t pdf,doc,xls,ppt -l 50 -o /tmp/metagoofil-output", "description": "Extract metadata from domain documents"},
            {"tool": "mat2", "command": f"mat2 --show {target}", "description": "MAT2 metadata analysis"},
        ]

    def _cmd_address_osint(self, target: str, ttype: str) -> list[dict[str, str]]:
        coords = target.replace(" ", "")
        if "," in coords:
            lat, lon = coords.split(",", 1)
            return [
                {"tool": "curl", "command": f'curl -s "https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json" | jq .', "description": "Reverse geocode coordinates to address (OpenStreetMap)"},
                {"tool": "curl", "command": f'echo "Google Maps: https://www.google.com/maps?q={lat},{lon}"', "description": "Generate Google Maps link"},
                {"tool": "curl", "command": f'echo "Google Street View: https://www.google.com/maps/@{lat},{lon},3a,75y,0h,90t"', "description": "Generate Street View link"},
            ]
        # Target is an address string
        addr = target.replace(" ", "+")
        return [
            {"tool": "curl", "command": f'curl -s "https://nominatim.openstreetmap.org/search?q={addr}&format=json&limit=3" | jq .', "description": "Geocode address to coordinates (OpenStreetMap)"},
        ]

    def _cmd_infrastructure_map(self, target: str, ttype: str) -> list[dict[str, str]]:
        return [
            {"tool": "nmap", "command": f"sudo nmap -sn --traceroute {target}", "description": "Network discovery with traceroute"},
            {"tool": "curl", "command": f'curl -s "https://api.bgpview.io/ip/{target}" | jq .', "description": "BGP/ASN information for IP"},
            {"tool": "whois", "command": f"whois {target} | grep -iE 'netname|descr|country|org'", "description": "Network WHOIS data"},
        ]
