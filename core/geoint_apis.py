#!/usr/bin/env python3
"""
StrikeCore GEOINT API Integrations — Free/Open satellite, flight, maritime, infrastructure.

APIs:
1. Overpass (OpenStreetMap) — infrastructure near coordinates
2. Sentinel Hub (ESA) — satellite imagery metadata
3. ADSBexchange — unfiltered flight tracking
4. MarineTraffic — AIS vessel tracking
5. NASA Worldview — MODIS/VIIRS imagery links
6. Nominatim — reverse geocoding
"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
import urllib.parse
from typing import Any

logger = logging.getLogger(__name__)

TIMEOUT = 12
UA = "StrikeCore/1.0 GEOINT"


def _get(url: str, headers: dict | None = None) -> dict | list | None:
    """HTTP GET with timeout and error handling."""
    hdrs = {"User-Agent": UA}
    if headers:
        hdrs.update(headers)
    try:
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.warning("GEOINT API error: %s — %s", url[:80], e)
        return None


def _post(url: str, data: str, content_type: str = "application/json") -> dict | list | None:
    """HTTP POST."""
    try:
        req = urllib.request.Request(
            url,
            data=data.encode(),
            headers={"User-Agent": UA, "Content-Type": content_type},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.warning("GEOINT API POST error: %s — %s", url[:80], e)
        return None


# ══════════════════════════════════════════════════════════════
# 1. Overpass API (OpenStreetMap) — Infrastructure near coords
# ══════════════════════════════════════════════════════════════

def overpass_nearby(lat: float, lon: float, radius_m: int = 500, tags: str = "") -> list[dict]:
    """Query OpenStreetMap for infrastructure near coordinates.

    Args:
        lat, lon: Center point
        radius_m: Search radius in meters (default 500)
        tags: OSM tag filter (e.g. 'amenity=restaurant' or 'building')

    Returns:
        List of dicts: {name, type, lat, lon, tags}
    """
    tag_filter = f'["{tags.split("=")[0]}"="{tags.split("=")[1]}"]' if "=" in tags else f'["{tags}"]' if tags else ""

    query = f"""
    [out:json][timeout:10];
    (
      node{tag_filter}(around:{radius_m},{lat},{lon});
      way{tag_filter}(around:{radius_m},{lat},{lon});
    );
    out center tags 50;
    """

    data = _post(
        "https://overpass-api.de/api/interpreter",
        "data=" + urllib.parse.quote(query),
        "application/x-www-form-urlencoded",
    )

    if not data or "elements" not in data:
        return []

    results = []
    for el in data["elements"][:50]:
        tags_dict = el.get("tags", {})
        name = tags_dict.get("name", tags_dict.get("amenity", tags_dict.get("shop", "")))
        center = el.get("center", {})
        results.append({
            "name": name or "(unnamed)",
            "type": el.get("type", ""),
            "lat": center.get("lat", el.get("lat", 0)),
            "lon": center.get("lon", el.get("lon", 0)),
            "tags": tags_dict,
        })

    return results


def overpass_infrastructure(lat: float, lon: float, radius_m: int = 1000) -> dict:
    """Get comprehensive infrastructure summary near coordinates."""
    categories = {
        "restaurants": "amenity=restaurant",
        "cafes": "amenity=cafe",
        "bars": "amenity=bar",
        "banks": "amenity=bank",
        "hospitals": "amenity=hospital",
        "schools": "amenity=school",
        "hotels": "tourism=hotel",
        "shops": "shop",
        "offices": "office",
    }
    summary = {}
    for cat, tag in categories.items():
        results = overpass_nearby(lat, lon, radius_m, tag)
        summary[cat] = results
    return summary


# ══════════════════════════════════════════════════════════════
# 2. Sentinel Hub (ESA Copernicus) — Satellite imagery metadata
# ══════════════════════════════════════════════════════════════

def sentinel_search(lat: float, lon: float, date_from: str = "2024-01-01",
                    date_to: str = "2026-12-31", max_results: int = 5) -> list[dict]:
    """Search Copernicus Open Access Hub for Sentinel-2 imagery.

    Returns list of image metadata (no download — just metadata + preview URLs).
    Note: For actual downloads, registration at scihub.copernicus.eu is needed.
    """
    # Use the STAC catalog (free, no auth for search)
    bbox = f"{lon-0.05},{lat-0.05},{lon+0.05},{lat+0.05}"
    url = (
        f"https://catalogue.dataspace.copernicus.eu/odata/v1/Products?"
        f"$filter=Collection/Name eq 'SENTINEL-2' and "
        f"OData.CSC.Intersects(area=geography'SRID=4326;POINT({lon} {lat})') and "
        f"ContentDate/Start gt {date_from}T00:00:00.000Z and "
        f"ContentDate/Start lt {date_to}T00:00:00.000Z&"
        f"$top={max_results}&$orderby=ContentDate/Start desc"
    )

    data = _get(url)
    if not data or "value" not in data:
        return []

    results = []
    for item in data["value"][:max_results]:
        results.append({
            "name": item.get("Name", ""),
            "date": item.get("ContentDate", {}).get("Start", ""),
            "cloud_cover": item.get("S2_ProcessingLevel", ""),
            "id": item.get("Id", ""),
            "footprint": item.get("Footprint", ""),
        })

    return results


def sentinel_preview_url(lat: float, lon: float) -> str:
    """Generate a Sentinel Hub WMS preview URL for a location (visual)."""
    return (
        f"https://services.sentinel-hub.com/ogc/wms/1234?"
        f"SERVICE=WMS&REQUEST=GetMap&LAYERS=TRUE-COLOR&"
        f"BBOX={lon-0.01},{lat-0.01},{lon+0.01},{lat+0.01}&"
        f"WIDTH=512&HEIGHT=512&FORMAT=image/png&CRS=EPSG:4326"
    )


# ══════════════════════════════════════════════════════════════
# 3. ADSBexchange — Unfiltered flight tracking
# ══════════════════════════════════════════════════════════════

def adsb_nearby(lat: float, lon: float, radius_nm: int = 25) -> list[dict]:
    """Get aircraft near coordinates from ADSBexchange.

    Note: ADSBexchange v2 API requires a key ($10/mo for Rapid API).
    This uses the free public feed when available.
    """
    # Public API endpoint (may require RapidAPI key)
    url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{lat}/lon/{lon}/dist/{radius_nm}/"
    # Try without key first (public)
    data = _get(url)

    if not data or "ac" not in data:
        # Fallback: try opensky-network (truly free)
        return _opensky_nearby(lat, lon, radius_nm)

    results = []
    for ac in data.get("ac", [])[:20]:
        results.append({
            "callsign": (ac.get("flight") or "").strip(),
            "icao": ac.get("hex", ""),
            "altitude_ft": ac.get("alt_baro", ""),
            "speed_kts": ac.get("gs", ""),
            "heading": ac.get("track", ""),
            "lat": ac.get("lat", ""),
            "lon": ac.get("lon", ""),
            "type": ac.get("t", ""),
            "registration": ac.get("r", ""),
        })

    return results


def _opensky_nearby(lat: float, lon: float, radius_nm: int = 25) -> list[dict]:
    """Fallback: OpenSky Network free API."""
    # Convert NM to degree bbox (rough)
    d = radius_nm * 0.0166
    url = (
        f"https://opensky-network.org/api/states/all?"
        f"lamin={lat-d}&lomin={lon-d}&lamax={lat+d}&lomax={lon+d}"
    )
    data = _get(url)
    if not data or "states" not in data:
        return []

    results = []
    for s in (data.get("states") or [])[:20]:
        results.append({
            "callsign": (s[1] or "").strip() if len(s) > 1 else "",
            "icao": s[0] if s else "",
            "country": s[2] if len(s) > 2 else "",
            "lat": s[6] if len(s) > 6 else "",
            "lon": s[5] if len(s) > 5 else "",
            "altitude_m": s[7] if len(s) > 7 else "",
            "speed_ms": s[9] if len(s) > 9 else "",
            "on_ground": s[8] if len(s) > 8 else "",
        })

    return results


# ══════════════════════════════════════════════════════════════
# 4. MarineTraffic / AIS — Vessel tracking
# ══════════════════════════════════════════════════════════════

def marine_search_vessel(name: str) -> str:
    """Generate MarineTraffic search URL for a vessel name."""
    return f"https://www.marinetraffic.com/en/ais/index/search/all?keyword={urllib.parse.quote(name)}"


def marine_area(lat: float, lon: float) -> str:
    """Generate MarineTraffic URL for area view."""
    return f"https://www.marinetraffic.com/en/ais/home/centerx:{lon}/centery:{lat}/zoom:10"


# ══════════════════════════════════════════════════════════════
# 5. NASA Worldview — MODIS/VIIRS imagery links
# ══════════════════════════════════════════════════════════════

def nasa_worldview_url(lat: float, lon: float, date: str = "") -> str:
    """Generate NASA Worldview URL centered on coordinates."""
    d = date or "today"
    return (
        f"https://worldview.earthdata.nasa.gov/?v={lon-2},{lat-2},{lon+2},{lat+2}"
        f"&t={d}&l=VIIRS_SNPP_CorrectedReflectance_TrueColor,MODIS_Aqua_CorrectedReflectance_TrueColor"
    )


def nasa_firms_fires(lat: float, lon: float, days: int = 7) -> list[dict]:
    """Get active fire data from NASA FIRMS near coordinates."""
    url = (
        f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
        f"VIIRS_SNPP_NRT/{lon-1},{lat-1},{lon+1},{lat+1}/{days}"
    )
    # FIRMS requires MAP_KEY env var
    import os
    key = os.environ.get("NASA_FIRMS_KEY", "")
    if key:
        url = url.replace("/csv/", f"/csv/{key}/")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            lines = resp.read().decode().strip().split("\n")
            if len(lines) <= 1:
                return []
            headers = lines[0].split(",")
            results = []
            for line in lines[1:6]:
                vals = line.split(",")
                results.append(dict(zip(headers, vals)))
            return results
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════
# 6. Nominatim — Reverse geocoding (already used, formalized)
# ══════════════════════════════════════════════════════════════

def reverse_geocode(lat: float, lon: float) -> dict:
    """Reverse geocode coordinates to address."""
    data = _get(
        f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=18"
    )
    if not data:
        return {}
    return {
        "address": data.get("display_name", ""),
        "city": data.get("address", {}).get("city", data.get("address", {}).get("town", "")),
        "country": data.get("address", {}).get("country", ""),
        "postcode": data.get("address", {}).get("postcode", ""),
    }


def geocode(query: str) -> dict:
    """Forward geocode address/place name to coordinates."""
    data = _get(
        f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query)}&format=json&limit=1"
    )
    if not data or not isinstance(data, list) or len(data) == 0:
        return {}
    return {
        "lat": float(data[0].get("lat", 0)),
        "lon": float(data[0].get("lon", 0)),
        "name": data[0].get("display_name", ""),
    }


# ══════════════════════════════════════════════════════════════
# 7. Convenience: Full GEOINT report for coordinates
# ══════════════════════════════════════════════════════════════

def geoint_report(lat: float, lon: float) -> dict:
    """Generate comprehensive GEOINT report for a coordinate pair."""
    return {
        "coordinates": {"lat": lat, "lon": lon},
        "address": reverse_geocode(lat, lon),
        "nearby_restaurants": overpass_nearby(lat, lon, 500, "amenity=restaurant")[:5],
        "nearby_hotels": overpass_nearby(lat, lon, 1000, "tourism=hotel")[:5],
        "flights_overhead": _opensky_nearby(lat, lon, 15)[:5],
        "urls": {
            "google_maps": f"https://www.google.com/maps?q={lat},{lon}",
            "google_streetview": f"https://www.google.com/maps/@{lat},{lon},3a,75y,0h,90t",
            "nasa_worldview": nasa_worldview_url(lat, lon),
            "marine_traffic": marine_area(lat, lon),
            "sentinel_preview": sentinel_preview_url(lat, lon),
        },
    }
