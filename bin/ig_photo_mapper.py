#!/usr/bin/env python3
"""
StrikeCore Instagram Photo Mapper — Extract photos with geolocation for map display.

Fetches posts from Instagram feed API, extracts:
- Image URLs (thumbnail + full)
- Location name + GPS coordinates
- Tagged people
- Caption text
- Timestamp

Saves as JSON for dashboard map consumption + downloads thumbnails.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SESSION_PATH = Path.home() / ".strikecore" / "ig_session"
OUTPUT_DIR = Path.home() / "strikecore-data" / "photos"


def ig_api(endpoint: str, session: str) -> dict | None:
    """Call Instagram API with session cookie."""
    try:
        r = subprocess.run([
            "curl", "-s",
            "https://i.instagram.com/api/v1/" + endpoint,
            "-H", "User-Agent: Instagram 275.0.0.27.98 Android (30/11; 420dpi; 1080x2280; samsung; SM-G991B)",
            "-H", "X-IG-App-ID: 936619743392459",
            "-H", "Cookie: sessionid=" + session,
        ], capture_output=True, text=True, timeout=15)
        return json.loads(r.stdout)
    except Exception:
        return None


def download_thumb(url: str, path: Path) -> bool:
    """Download image thumbnail."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        data = urllib.request.urlopen(req, timeout=10).read()
        path.write_bytes(data)
        return True
    except Exception:
        return False


def extract_exif_gps(filepath: str) -> dict | None:
    """Extract GPS from downloaded image via exiftool."""
    try:
        r = subprocess.run(
            ["exiftool", "-GPS*", "-json", filepath],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
        )
        data = json.loads(r.stdout)
        if data and data[0].get("GPSLatitude"):
            return {
                "lat": data[0].get("GPSLatitude", ""),
                "lon": data[0].get("GPSLongitude", ""),
                "raw": data[0],
            }
    except Exception:
        pass
    return None


def main():
    if len(sys.argv) < 2:
        print("Usage: ig_photo_mapper.py USERNAME [max_posts]")
        sys.exit(1)

    username = sys.argv[1]
    max_posts = int(sys.argv[2]) if len(sys.argv) > 2 else 30

    if not SESSION_PATH.exists():
        print("ERROR: No Instagram session at " + str(SESSION_PATH))
        sys.exit(1)

    session = SESSION_PATH.read_text().strip()

    # Create output dirs
    target_dir = OUTPUT_DIR / username
    target_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir = target_dir / "thumbs"
    thumbs_dir.mkdir(exist_ok=True)

    print("=" * 60)
    print("  STRIKECORE INSTAGRAM PHOTO MAPPER")
    print("  Target: @" + username)
    print("=" * 60)

    # Get user ID
    profile = ig_api("users/web_profile_info/?username=" + username, session)
    if not profile:
        print("ERROR: Cannot fetch profile")
        sys.exit(1)

    user = profile.get("data", {}).get("user", {})
    user_id = user.get("id", "")
    if not user_id:
        print("ERROR: No user ID found")
        sys.exit(1)

    print("User ID: " + str(user_id))
    print("Fetching posts...")

    # Fetch feed
    all_posts = []
    next_id = ""
    while len(all_posts) < max_posts:
        endpoint = f"feed/user/{user_id}/?count=12"
        if next_id:
            endpoint += "&max_id=" + next_id
        data = ig_api(endpoint, session)
        if not data or "items" not in data:
            break
        items = data["items"]
        all_posts.extend(items)
        if not data.get("more_available"):
            break
        next_id = data.get("next_max_id", "")
        if not next_id:
            break
        time.sleep(1)

    print(f"Fetched {len(all_posts)} posts")

    # Process each post
    photo_markers = []

    for i, post in enumerate(all_posts[:max_posts]):
        post_id = post.get("pk", post.get("id", ""))
        ts = post.get("taken_at", 0)
        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "?"

        # Location
        loc = post.get("location")
        loc_name = loc.get("name", "") if loc else ""
        loc_lat = loc.get("lat") if loc else None
        loc_lng = loc.get("lng") if loc else None

        # Image URL
        img_url = ""
        thumb_url = ""
        if post.get("image_versions2"):
            candidates = post["image_versions2"].get("candidates", [])
            if candidates:
                # Full size = first candidate (largest)
                img_url = candidates[0].get("url", "")
                # Thumbnail = last candidate (smallest)
                thumb_url = candidates[-1].get("url", "") if len(candidates) > 1 else img_url
        elif post.get("carousel_media"):
            # Carousel: take first image
            first = post["carousel_media"][0]
            if first.get("image_versions2"):
                candidates = first["image_versions2"].get("candidates", [])
                if candidates:
                    img_url = candidates[0].get("url", "")
                    thumb_url = candidates[-1].get("url", "") if len(candidates) > 1 else img_url

        # Caption
        caption = ""
        cap_obj = post.get("caption")
        if cap_obj:
            caption = cap_obj.get("text", "")[:200]

        # Tagged people
        tagged = []
        for t in post.get("usertags", {}).get("in", []):
            u = t.get("user", {})
            tagged.append(u.get("username", ""))

        # Download thumbnail + check EXIF
        thumb_path = thumbs_dir / f"{post_id}.jpg"
        exif_gps = None
        if thumb_url and not thumb_path.exists():
            if download_thumb(thumb_url, thumb_path):
                exif_gps = extract_exif_gps(str(thumb_path))

        # Determine best coordinates
        best_lat = None
        best_lon = None
        geo_source = ""

        if exif_gps and exif_gps.get("lat"):
            # EXIF GPS is highest confidence
            best_lat = exif_gps["lat"]
            best_lon = exif_gps["lon"]
            geo_source = "EXIF"
        elif loc_lat and loc_lng:
            # Instagram geotag
            best_lat = float(loc_lat)
            best_lon = float(loc_lng)
            geo_source = "GEOTAG"

        marker = {
            "post_id": str(post_id),
            "date": dt,
            "location_name": loc_name,
            "lat": best_lat,
            "lon": best_lon,
            "geo_source": geo_source,
            "image_url": img_url,
            "thumb_url": thumb_url,
            "thumb_local": str(thumb_path) if thumb_path.exists() else "",
            "caption": caption,
            "tagged": tagged,
        }
        photo_markers.append(marker)

        if best_lat:
            print(f"  [{dt}] {loc_name} ({best_lat:.4f}, {best_lon:.4f}) [{geo_source}] tagged:{tagged}")
        elif loc_name:
            print(f"  [{dt}] {loc_name} (no coords) tagged:{tagged}")

    # Save markers JSON (for dashboard)
    markers_path = target_dir / "photo_markers.json"
    with open(markers_path, "w") as f:
        json.dump(photo_markers, f, indent=2, default=str)

    # Stats
    with_geo = sum(1 for m in photo_markers if m["lat"])
    with_loc_name = sum(1 for m in photo_markers if m["location_name"])
    with_tagged = sum(1 for m in photo_markers if m["tagged"])
    thumbs_downloaded = sum(1 for m in photo_markers if m["thumb_local"])

    print("\n" + "=" * 60)
    print(f"  RESULTS")
    print(f"  Posts processed: {len(photo_markers)}")
    print(f"  With GPS coordinates: {with_geo}")
    print(f"  With location name: {with_loc_name}")
    print(f"  With tagged people: {with_tagged}")
    print(f"  Thumbnails downloaded: {thumbs_downloaded}")
    print(f"  Markers JSON: {markers_path}")
    print(f"  Thumbnails: {thumbs_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
