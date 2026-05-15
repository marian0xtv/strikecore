#!/usr/bin/env python3
"""
StrikeCore Photo Forensics CLI — Analyze images for device/location intelligence.

Extracts intelligence even from Instagram-compressed images using:
- FBMD (Facebook Metadata) signature decoding
- ICC color profile device fingerprinting
- Resolution-based device inference
- JPEG quantization table matching
- Full EXIF analysis for non-stripped images

Usage:
    photo_forensics.py IMAGE_FILE
    photo_forensics.py DIRECTORY/       (batch mode)
    photo_forensics.py --target USERNAME (analyze downloaded Instagram photos)
"""

import json
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.photo_forensics import forensic_analysis, batch_forensics


def print_report(report: dict):
    """Pretty-print a single forensic report."""
    print()
    print("=" * 60)
    print("  PHOTO FORENSICS: " + report["filename"])
    print("  Hash: " + report.get("file_hash", "?"))
    print("=" * 60)

    print("\n  DEVICE: " + report["device_verdict"])
    print("  LOCATION: " + report["location_verdict"])
    print("  AUTHENTICITY SCORE: " + str(report["authenticity_score"]) + "/100")

    if report["findings"]:
        print("\n  FINDINGS:")
        for f in report["findings"]:
            conf_icon = {"HIGH": "+", "MEDIUM": "~", "LOW": "-"}.get(f["confidence"], "?")
            print(f"    [{conf_icon}] [{f['confidence']}] {f['type']}: {f['value']}")
            print(f"         Source: {f['source']}")

    # ICC details if interesting
    icc = report.get("analyses", {}).get("icc_profile", {})
    if icc.get("has_icc"):
        print("\n  ICC PROFILE:")
        print(f"    Description: {icc.get('profile_description', '?')}")
        print(f"    CMM Type: {icc.get('cmm_type', '?')} → {icc.get('cmm_hint', '?')}")
        print(f"    Device Mfr: {icc.get('device_manufacturer', '?')} → {icc.get('device_manufacturer_hint', '?')}")
        print(f"    Profile Date: {icc.get('profile_date', '?')}")

    # Dimensions
    dims = report.get("analyses", {}).get("dimensions", {})
    if dims.get("width"):
        print(f"\n  DIMENSIONS: {dims['width']}x{dims['height']} ({dims.get('aspect_ratio', '?')}) {dims.get('original_orientation', '')}")
        if dims.get("is_reencoded"):
            print("  ⚠ RE-ENCODED by Instagram/Meta (original resolution lost)")

    # FBMD
    exif = report.get("analyses", {}).get("exif", {})
    if exif.get("fbmd"):
        fbmd = exif["fbmd"]
        print(f"\n  FBMD SIGNATURE: {len(fbmd.get('segments', []))} segments")
        if fbmd.get("photo_id"):
            print(f"    Photo ID: {fbmd['photo_id']}")

    print()


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  photo_forensics.py IMAGE_FILE")
        print("  photo_forensics.py DIRECTORY/")
        print("  photo_forensics.py --target USERNAME")
        sys.exit(1)

    if sys.argv[1] == "--target":
        username = sys.argv[2] if len(sys.argv) > 2 else ""
        if not username:
            print("Usage: photo_forensics.py --target USERNAME")
            sys.exit(1)
        photo_dir = Path.home() / "strikecore-data" / "photos" / username / "thumbs"
        if not photo_dir.exists():
            print(f"No photos found at {photo_dir}")
            print(f"Run: ig-photo-mapper {username}")
            sys.exit(1)
        target = str(photo_dir)
    else:
        target = sys.argv[1]

    target_path = Path(target)

    if target_path.is_dir():
        print(f"Batch forensics: {target_path}")
        results = batch_forensics(str(target_path))
        for r in results:
            print_report(r)

        # Summary
        print("=" * 60)
        print(f"  BATCH SUMMARY: {len(results)} images analyzed")
        devices = set()
        gps_count = 0
        fbmd_count = 0
        for r in results:
            for f in r["findings"]:
                if f["type"] in ("DEVICE", "ICC_DEVICE", "ICC_MFR"):
                    devices.add(f["value"])
                if f["type"] == "GPS":
                    gps_count += 1
                if f["type"] == "FBMD":
                    fbmd_count += 1
        print(f"  Devices identified: {devices or 'None (all stripped)'}")
        print(f"  Photos with GPS: {gps_count}")
        print(f"  Photos with FBMD: {fbmd_count}")
        avg_score = sum(r["authenticity_score"] for r in results) / len(results) if results else 0
        print(f"  Average authenticity: {avg_score:.0f}/100")
        print("=" * 60)

        # Save JSON
        out_path = target_path.parent / "forensics_report.json"
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"  JSON saved: {out_path}")

    elif target_path.is_file():
        report = forensic_analysis(str(target_path))
        print_report(report)
    else:
        print(f"Not found: {target}")
        sys.exit(1)


if __name__ == "__main__":
    main()
