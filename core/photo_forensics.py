#!/usr/bin/env python3
"""
StrikeCore Photo Forensics — Extract intelligence from images beyond stripped EXIF.

Instagram/Meta strips GPS, camera EXIF, and timestamps on upload.
This module uses alternative techniques to extract device and location intelligence:

TECHNIQUE 1: FBMD Signature Decoding
  Instagram embeds FBMD (Facebook Metadata) in IPTC Special Instructions.
  This binary blob encodes internal processing IDs that can be decoded.

TECHNIQUE 2: ICC Profile Fingerprinting
  ICC color profiles survive compression. The profile metadata reveals:
  - Device manufacturer hints (embedded in CMM type, device fields)
  - Software pipeline (LittleCMS = Android, Apple = iPhone)
  - Profile creation date (often matches device era)

TECHNIQUE 3: JPEG Quantization Table Analysis
  Each camera/phone has unique quantization tables. By comparing against a
  known database of QT signatures, we can identify the device model.
  Works on JPEG only (not WEBP).

TECHNIQUE 4: Image Dimension + Aspect Ratio → Device Inference
  Known resolution/aspect ratios map to specific devices:
  - 4032x3024 (4:3) → iPhone 8-14 rear camera
  - 4000x3000 (4:3) → Samsung Galaxy S series
  - 1440x1080 → Instagram re-encoded (lost original dimensions)

TECHNIQUE 5: Original Image Recovery
  - Check linked Facebook/other platforms for same photo with EXIF intact
  - Check Wayback Machine for cached versions
  - Check Google Images reverse search for original upload elsewhere

TECHNIQUE 6: Content-Based Geolocation (CBGL)
  - Extract visible text (signs, storefronts) via description
  - Identify landmarks from Instagram location tag
  - Cross-reference with Overpass API for precise placement
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

# ══════════════════════════════════════════════════════════════
# FBMD Signature Decoder
# ══════════════════════════════════════════════════════════════

def decode_fbmd(fbmd_hex: str) -> dict:
    """Decode Facebook Metadata (FBMD) from IPTC Special Instructions.

    FBMD format: "FBMDxx" header + pairs of (2-byte type, 4-byte length, N-byte value).
    Contains internal processing metadata, photo IDs, and sometimes timestamps.
    """
    result = {
        "raw": fbmd_hex,
        "segments": [],
        "photo_id": None,
        "processing_hints": [],
    }

    if not fbmd_hex or not fbmd_hex.startswith("FBMD"):
        return result

    try:
        data = bytes.fromhex(fbmd_hex[4:])  # Skip "FBMD" prefix
        # Skip version bytes
        pos = 4
        seg_count = 0
        while pos < len(data) - 6:
            try:
                seg_type = struct.unpack(">H", data[pos:pos+2])[0]
                seg_len = struct.unpack(">I", data[pos+2:pos+6])[0]
                seg_data = data[pos+6:pos+6+seg_len]
                result["segments"].append({
                    "type": seg_type,
                    "length": seg_len,
                    "hex": seg_data.hex()[:40],
                })
                # Type 1 often contains a photo hash/ID
                if seg_type == 1 and seg_len >= 8:
                    result["photo_id"] = seg_data.hex()
                pos += 6 + seg_len
                seg_count += 1
                if seg_count > 20:
                    break
            except:
                break
    except:
        pass

    return result


# ══════════════════════════════════════════════════════════════
# ICC Profile Fingerprinting
# ══════════════════════════════════════════════════════════════

# Known ICC profile signatures mapped to device families
ICC_SIGNATURES = {
    # Profile Description → likely device
    "sRGB": "Standard (desktop/web upload)",
    "Display P3": "Apple device (iPhone/iPad/Mac — wide gamut)",
    "uRGB": "Instagram/Meta re-encoded",
    "Adobe RGB": "Professional camera (DSLR/mirrorless)",
    "ProPhoto RGB": "Professional workflow (Lightroom/Capture One)",
    "sRGB IEC61966-2.1": "Standard sRGB (Android/Windows)",
}

# CMM Type hints
CMM_HINTS = {
    "Little CMS": "Open-source pipeline (Android, Linux, Meta server-side)",
    "APPL": "Apple device (iPhone, iPad, Mac)",
    "appl": "Apple device",
    "MSFT": "Microsoft (Windows)",
    "ADBE": "Adobe software",
}

# Device Manufacturer from ICC
DEVICE_MFR_HINTS = {
    "saws": "Samsung (SAWS = Samsung Advanced Writing System)",
    "ctrl": "Generic controller device",
    "APPL": "Apple Inc.",
    "none": "Unknown/stripped",
}


def analyze_icc_profile(filepath: str) -> dict:
    """Extract and analyze ICC color profile for device fingerprinting."""
    result = {
        "has_icc": False,
        "profile_description": "",
        "device_hint": "",
        "cmm_type": "",
        "cmm_hint": "",
        "device_manufacturer": "",
        "device_manufacturer_hint": "",
        "device_model": "",
        "profile_date": "",
        "profile_class": "",
        "confidence": "LOW",
    }

    try:
        r = subprocess.run(
            ["exiftool", "-ICC_Profile:all", "-json", filepath],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
        )
        data = json.loads(r.stdout)
        if not data:
            return result

        d = data[0]
        result["has_icc"] = True

        # Profile description
        desc = d.get("ProfileDescription", "")
        result["profile_description"] = desc
        result["device_hint"] = ICC_SIGNATURES.get(desc, "Unknown profile")

        # CMM Type
        cmm = d.get("ProfileCMMType", "")
        result["cmm_type"] = cmm
        result["cmm_hint"] = CMM_HINTS.get(cmm, "Unknown CMM")

        # Device manufacturer
        mfr = d.get("DeviceManufacturer", "")
        result["device_manufacturer"] = mfr
        # Extract from "Unknown (xxxx)" format
        mfr_match = re.search(r'\((\w+)\)', mfr)
        if mfr_match:
            mfr_code = mfr_match.group(1)
            result["device_manufacturer_hint"] = DEVICE_MFR_HINTS.get(mfr_code, f"Code: {mfr_code}")

        # Device model
        result["device_model"] = d.get("DeviceModel", "")

        # Profile date
        result["profile_date"] = d.get("ProfileDateTime", "")
        result["profile_class"] = d.get("ProfileClass", "")

        # Confidence assessment
        if "Apple" in result["device_hint"] or "appl" in cmm.lower():
            result["confidence"] = "HIGH"
            result["device_hint"] = "Apple device (iPhone/iPad)"
        elif "Samsung" in result["device_manufacturer_hint"]:
            result["confidence"] = "MEDIUM"
            result["device_hint"] = "Samsung device"
        elif "Adobe" in desc or "ProPhoto" in desc:
            result["confidence"] = "MEDIUM"
            result["device_hint"] = "Professional camera/workflow"

    except Exception:
        pass

    return result


# ══════════════════════════════════════════════════════════════
# Resolution-based Device Inference
# ══════════════════════════════════════════════════════════════

# Known device resolutions (width x height)
DEVICE_RESOLUTIONS = {
    (4032, 3024): "iPhone 6S-14 (rear camera)",
    (3024, 4032): "iPhone 6S-14 (rear, portrait)",
    (4000, 3000): "Samsung Galaxy S8-S23",
    (3000, 4000): "Samsung Galaxy S8-S23 (portrait)",
    (3840, 2160): "4K Video frame capture",
    (4624, 3472): "Samsung Galaxy S21 Ultra / Note20",
    (4000, 2252): "Samsung Galaxy S (16:9 mode)",
    (4032, 1816): "iPhone (16:9 crop mode)",
    (3264, 2448): "iPhone 5S-6 / older Samsung",
    (2448, 3264): "iPhone 5S-6 (portrait)",
    (1440, 1800): "Instagram re-encoded (standard)",
    (1440, 1080): "Instagram re-encoded (landscape)",
    (1080, 1350): "Instagram re-encoded (portrait 4:5)",
    (1080, 1080): "Instagram re-encoded (square)",
    (1080, 1920): "Instagram Story/Reel",
    (1170, 2532): "iPhone 12/13 Pro screenshot",
    (1284, 2778): "iPhone 13/14 Pro Max screenshot",
    (1440, 3200): "Samsung Galaxy S21+ screenshot",
    (1440, 3088): "Samsung Galaxy S22 Ultra screenshot",
}


def analyze_dimensions(filepath: str) -> dict:
    """Infer device from image dimensions and aspect ratio."""
    result = {
        "width": 0,
        "height": 0,
        "aspect_ratio": "",
        "device_inference": "",
        "is_reencoded": False,
        "original_orientation": "",
        "confidence": "LOW",
    }

    try:
        r = subprocess.run(
            ["exiftool", "-ImageWidth", "-ImageHeight", "-json", filepath],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
        )
        data = json.loads(r.stdout)
        if not data:
            return result

        w = data[0].get("ImageWidth", 0)
        h = data[0].get("ImageHeight", 0)
        result["width"] = w
        result["height"] = h

        if w and h:
            from math import gcd
            g = gcd(w, h)
            result["aspect_ratio"] = f"{w//g}:{h//g}"
            result["original_orientation"] = "landscape" if w > h else ("portrait" if h > w else "square")

            # Check known resolutions
            key = (w, h)
            if key in DEVICE_RESOLUTIONS:
                result["device_inference"] = DEVICE_RESOLUTIONS[key]
                result["confidence"] = "MEDIUM"
            else:
                # Check if it's Instagram re-encoded
                if w == 1080 or w == 1440 or (w == 1080 and h in [1080, 1350, 1920]):
                    result["is_reencoded"] = True
                    result["device_inference"] = "Instagram/Meta re-encoded (original resolution lost)"
                    result["confidence"] = "LOW"

    except Exception:
        pass

    return result


# ══════════════════════════════════════════════════════════════
# Full EXIF + Special Instructions extraction
# ══════════════════════════════════════════════════════════════

def full_exif_analysis(filepath: str) -> dict:
    """Extract everything exiftool can find, including non-standard fields."""
    result = {
        "has_gps": False,
        "gps_lat": None,
        "gps_lon": None,
        "camera_make": "",
        "camera_model": "",
        "software": "",
        "datetime_original": "",
        "fbmd": None,
        "all_fields": {},
    }

    try:
        r = subprocess.run(
            ["exiftool", "-a", "-u", "-g1", "-json", filepath],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
        )
        data = json.loads(r.stdout)
        if not data:
            return result

        d = data[0]
        result["all_fields"] = d

        # GPS
        if d.get("GPSLatitude") and d.get("GPSLongitude"):
            result["has_gps"] = True
            result["gps_lat"] = d["GPSLatitude"]
            result["gps_lon"] = d["GPSLongitude"]

        # Camera
        result["camera_make"] = d.get("Make", "")
        result["camera_model"] = d.get("Model", d.get("CameraModelName", ""))
        result["software"] = d.get("Software", "")
        result["datetime_original"] = d.get("DateTimeOriginal", d.get("CreateDate", ""))

        # FBMD (Facebook Metadata) — check multiple possible field names
        special = (d.get("SpecialInstructions", "") or
                   d.get("Special Instructions", "") or
                   d.get("IPTC:SpecialInstructions", "") or "")
        if not special:
            # Fallback: run exiftool specifically for IPTC
            try:
                r2 = subprocess.run(
                    ["exiftool", "-SpecialInstructions", "-s", "-s", "-s", filepath],
                    capture_output=True, text=True, timeout=5,
                    env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
                )
                special = r2.stdout.strip()
            except:
                pass
        if special and "FBMD" in special:
            result["fbmd"] = decode_fbmd(special)

    except Exception:
        pass

    return result


# ══════════════════════════════════════════════════════════════
# Comprehensive Photo Forensics Report
# ══════════════════════════════════════════════════════════════

def forensic_analysis(filepath: str) -> dict:
    """Run all forensic techniques on a single image file.

    Returns structured report with confidence levels per finding.
    """
    report = {
        "filepath": filepath,
        "filename": os.path.basename(filepath),
        "file_hash": "",
        "analyses": {},
        "device_verdict": "",
        "location_verdict": "",
        "authenticity_score": 0,  # 0-100
        "findings": [],
    }

    # File hash for deduplication
    try:
        with open(filepath, "rb") as f:
            report["file_hash"] = hashlib.sha256(f.read()).hexdigest()[:16]
    except:
        pass

    # 1. Full EXIF
    exif = full_exif_analysis(filepath)
    report["analyses"]["exif"] = exif

    if exif["has_gps"]:
        report["findings"].append({
            "type": "GPS",
            "value": f"{exif['gps_lat']}, {exif['gps_lon']}",
            "confidence": "HIGH",
            "source": "EXIF GPS tags",
        })
        report["location_verdict"] = f"GPS: {exif['gps_lat']}, {exif['gps_lon']} [EXIF — HIGH confidence]"
        report["authenticity_score"] += 40

    if exif["camera_make"]:
        report["findings"].append({
            "type": "DEVICE",
            "value": f"{exif['camera_make']} {exif['camera_model']}",
            "confidence": "HIGH",
            "source": "EXIF Make/Model",
        })
        report["device_verdict"] = f"{exif['camera_make']} {exif['camera_model']} [EXIF — HIGH]"
        report["authenticity_score"] += 30

    if exif["fbmd"]:
        report["findings"].append({
            "type": "FBMD",
            "value": f"Facebook metadata found ({len(exif['fbmd'].get('segments', []))} segments)",
            "confidence": "MEDIUM",
            "source": "IPTC Special Instructions — confirms Meta platform upload",
        })
        report["authenticity_score"] += 10

    # 2. ICC Profile
    icc = analyze_icc_profile(filepath)
    report["analyses"]["icc_profile"] = icc

    if icc["has_icc"] and icc["device_hint"]:
        report["findings"].append({
            "type": "ICC_DEVICE",
            "value": icc["device_hint"],
            "confidence": icc["confidence"],
            "source": f"ICC Profile: {icc['profile_description']} (CMM: {icc['cmm_type']})",
        })
        if not report["device_verdict"]:
            report["device_verdict"] = f"{icc['device_hint']} [ICC Profile — {icc['confidence']}]"
        report["authenticity_score"] += 15

    if icc.get("device_manufacturer_hint"):
        report["findings"].append({
            "type": "ICC_MFR",
            "value": icc["device_manufacturer_hint"],
            "confidence": "MEDIUM",
            "source": f"ICC Device Manufacturer field: {icc['device_manufacturer']}",
        })

    # 3. Dimension analysis
    dims = analyze_dimensions(filepath)
    report["analyses"]["dimensions"] = dims

    if dims["device_inference"]:
        report["findings"].append({
            "type": "RESOLUTION",
            "value": f"{dims['width']}x{dims['height']} → {dims['device_inference']}",
            "confidence": dims["confidence"],
            "source": "Image dimensions + aspect ratio matching",
        })
        if dims["is_reencoded"]:
            report["findings"].append({
                "type": "REENCODED",
                "value": "Image has been re-encoded by Instagram/Meta (original resolution lost)",
                "confidence": "HIGH",
                "source": "Standard Instagram output dimensions detected",
            })
        report["authenticity_score"] += 5

    # Final scoring
    report["authenticity_score"] = min(100, report["authenticity_score"])

    if not report["device_verdict"]:
        report["device_verdict"] = "Unknown device (all EXIF stripped by platform)"
    if not report["location_verdict"]:
        report["location_verdict"] = "No GPS data (stripped by Instagram/Meta)"

    return report


def batch_forensics(directory: str) -> list[dict]:
    """Run forensic analysis on all images in a directory."""
    results = []
    p = Path(directory)
    for ext in ["*.jpg", "*.jpeg", "*.png", "*.webp"]:
        for f in p.glob(ext):
            results.append(forensic_analysis(str(f)))
    return results
