#!/usr/bin/env python3
"""
StrikeCore GEOINT Report — Generate comprehensive geospatial intelligence for coordinates.

Usage:
    geoint_report.py LAT LON
    geoint_report.py 41.8902 12.4922
    geoint_report.py "Rome, Italy"     (geocodes first)
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.geoint_apis import (
    geoint_report, geocode, reverse_geocode,
    overpass_nearby, overpass_infrastructure,
    sentinel_search, _opensky_nearby, nasa_worldview_url,
)


def main():
    if len(sys.argv) < 2:
        print("Usage: geoint_report.py LAT LON")
        print("       geoint_report.py 'City, Country'")
        sys.exit(1)

    # Parse input
    if len(sys.argv) >= 3:
        try:
            lat = float(sys.argv[1])
            lon = float(sys.argv[2])
        except ValueError:
            query = " ".join(sys.argv[1:])
            result = geocode(query)
            if not result:
                print("ERROR: Could not geocode: " + query)
                sys.exit(1)
            lat, lon = result["lat"], result["lon"]
            print("Geocoded: " + result.get("name", "") + " -> " + str(lat) + ", " + str(lon))
    else:
        query = sys.argv[1]
        result = geocode(query)
        if not result:
            print("ERROR: Could not geocode: " + query)
            sys.exit(1)
        lat, lon = result["lat"], result["lon"]
        print("Geocoded: " + result.get("name", "") + " -> " + str(lat) + ", " + str(lon))

    print("\n" + "=" * 60)
    print("  STRIKECORE GEOINT REPORT")
    print("  Coordinates: " + str(lat) + ", " + str(lon))
    print("=" * 60)

    # Address
    addr = reverse_geocode(lat, lon)
    print("\n--- ADDRESS ---")
    print("  " + addr.get("address", "Unknown"))

    # Nearby infrastructure
    print("\n--- NEARBY INFRASTRUCTURE (500m) ---")
    for cat, tag in [("Restaurants", "amenity=restaurant"), ("Hotels", "tourism=hotel"),
                     ("Banks", "amenity=bank"), ("Hospitals", "amenity=hospital")]:
        results = overpass_nearby(lat, lon, 500, tag)
        if results:
            print("  " + cat + " (" + str(len(results)) + "):")
            for r in results[:3]:
                print("    - " + r["name"])

    # Flights overhead
    print("\n--- AIRCRAFT OVERHEAD ---")
    flights = _opensky_nearby(lat, lon, 15)
    if flights:
        for f in flights[:5]:
            print("  " + f.get("callsign", "?") + " | " + f.get("country", "") +
                  " | alt:" + str(f.get("altitude_m", "?")) + "m")
    else:
        print("  No aircraft detected")

    # Satellite imagery
    print("\n--- SENTINEL-2 IMAGERY ---")
    images = sentinel_search(lat, lon, max_results=3)
    if images:
        for img in images:
            print("  " + img.get("name", "")[:50] + " | " + img.get("date", "")[:10])
    else:
        print("  No recent imagery found")

    # URLs
    print("\n--- INTELLIGENCE LINKS ---")
    print("  Google Maps: https://www.google.com/maps?q=" + str(lat) + "," + str(lon))
    print("  Street View: https://www.google.com/maps/@" + str(lat) + "," + str(lon) + ",3a,75y,0h,90t")
    print("  NASA Worldview: " + nasa_worldview_url(lat, lon))
    print("  Marine Traffic: https://www.marinetraffic.com/en/ais/home/centerx:" + str(lon) + "/centery:" + str(lat) + "/zoom:10")

    # Full JSON
    print("\n--- FULL JSON REPORT ---")
    report = geoint_report(lat, lon)
    print(json.dumps(report, indent=2, default=str))

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
