#!/usr/bin/env python3
"""
StrikeCore PCAP Analyzer v3 — Extract and rank all IPs from call traffic.

No aggressive filtering. Captures everything, scores intelligently:
  - Mobile carrier IPs ranked highest
  - Fixed residential ranked second
  - Hosting/CDN/known infra ranked lowest
  - Only private/local IPs excluded
"""

import json, os, re, subprocess, sys, urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from core.ip_logger import LOG_DIR, log_hit

PRIVATE = ("10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.",
           "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.",
           "172.29.", "172.30.", "172.31.", "192.168.", "127.", "0.", "255.", "169.254.")


def _priv(ip):
    return any(ip.startswith(p) for p in PRIVATE)


def _geo(ip):
    try:
        d = json.loads(urllib.request.urlopen(
            f"http://ip-api.com/json/{ip}?fields=66846719", timeout=5).read())
        if d.get("status") == "success":
            return {k: d.get(v, "") for k, v in [
                ("country","country"),("country_code","countryCode"),("region","regionName"),
                ("city","city"),("zip","zip"),("lat","lat"),("lon","lon"),("isp","isp"),
                ("org","org"),("as","as"),("as_name","asname"),("mobile","mobile"),
                ("proxy","proxy"),("hosting","hosting"),("timezone","timezone"),
            ]}
    except Exception:
        pass
    return {}


def _rgeo(lat, lon):
    try:
        r = json.loads(urllib.request.urlopen(
            f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&addressdetails=1",
            timeout=5).read())
        a = r.get("address", {})
        return {"address": r.get("display_name",""), "road": a.get("road",""),
                "suburb": a.get("suburb") or a.get("neighbourhood",""),
                "postcode": a.get("postcode",""),
                "municipality": a.get("municipality") or a.get("town") or a.get("village","")}
    except Exception:
        return {}


def _own_ip():
    try:
        return urllib.request.urlopen("https://ifconfig.me", timeout=3).read().decode().strip()
    except Exception:
        return ""


def analyze(pcap_path):
    if not os.path.exists(pcap_path):
        return None

    own = _own_ip()
    local = {"127.0.0.1", "::1", "0.0.0.0"}
    if own:
        local.add(own)
    try:
        for line in subprocess.check_output(["ip","-o","addr","show"], text=True).split("\n"):
            m = re.search(r"inet6?\s+([^\s/]+)", line)
            if m:
                local.add(m.group(1))
    except Exception:
        pass

    # Extract all flows
    try:
        r = subprocess.run(
            ["tshark", "-r", pcap_path, "-T", "fields",
             "-e","ip.src","-e","ip.dst","-e","udp.srcport","-e","udp.dstport",
             "-e","frame.len","-e","frame.time_epoch", "-E","separator=|"],
            capture_output=True, text=True, timeout=60)
    except Exception:
        return None

    # SDP IPs
    sdp_ips = set()
    try:
        sr = subprocess.run(
            ["tshark","-r",pcap_path,"-Y","sdp","-T","fields",
             "-e","sdp.connection_info.address","-e","sdp.owner.address"],
            capture_output=True, text=True, timeout=30)
        for line in sr.stdout.strip().split("\n"):
            for ip in line.split("\t"):
                ip = ip.strip()
                if ip and not _priv(ip):
                    sdp_ips.add(ip)
    except Exception:
        pass

    # Build candidates
    C = defaultdict(lambda: {"pkts":0,"bytes":0,"ports":set(),"first":0,"last":0})

    for line in r.stdout.strip().split("\n"):
        if not line: continue
        p = line.split("|")
        if len(p) < 5: continue
        src, dst, sp, dp = p[0], p[1], p[2], p[3]
        flen = int(p[4]) if p[4] else 0
        ft = float(p[5]) if len(p) > 5 and p[5] else 0

        for ip, port in [(src,sp),(dst,dp)]:
            if not ip or ip in local or _priv(ip):
                continue
            c = C[ip]
            c["pkts"] += 1
            c["bytes"] += flen
            if port: c["ports"].add(port)
            if not c["first"] or ft < c["first"]: c["first"] = ft
            if ft > c["last"]: c["last"] = ft

    for sip in sdp_ips:
        if sip not in C and sip not in local:
            C[sip] = {"pkts":0,"bytes":0,"ports":set(),"first":0,"last":0}

    if not C:
        return None

    # Score
    results = []
    for ip, c in C.items():
        geo = _geo(ip)
        s = 0.0
        if geo.get("mobile"):       s += 80
        isp = (geo.get("isp") or "").lower()
        for car in ["wind","tre","vodafone","tim","iliad","fastweb","ho.","kena","poste mobile","very mobile","lycamobile"]:
            if car in isp: s += 20; break
        if not geo.get("hosting") and not geo.get("proxy") and not geo.get("mobile"):
            s += 30
        if geo.get("hosting"):       s -= 40
        if ip in sdp_ips:            s += 15
        if c["pkts"] >= 3:           s += 10
        dur = c["last"] - c["first"]
        if dur > 3:                  s += 5

        addr = {}
        if s > 20 and geo.get("lat"):
            addr = _rgeo(geo["lat"], geo["lon"])

        results.append({
            "ip": ip, "score": round(s,1),
            "packets": c["pkts"], "bytes": c["bytes"],
            "ports": sorted(c["ports"])[:10], "duration": round(dur,1),
            "sdp_media": ip in sdp_ips,
            "geo": {**geo, **addr},
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def process(pcap_path, target_number):
    results = analyze(pcap_path)
    if not results:
        print("[!] No results from PCAP")
        return

    label = re.sub(r"[^a-zA-Z0-9_]", "", target_number.replace("+",""))

    print(f"\n{'='*60}")
    print(f"  PCAP Analysis — {len(results)} IPs")
    print(f"{'='*60}")
    for i, r in enumerate(results[:5]):
        g = r["geo"]
        tags = ""
        if g.get("mobile"): tags += " [MOBILE]"
        if g.get("hosting"): tags += " [HOSTING]"
        if r.get("sdp_media"): tags += " [SDP]"
        print(f"\n  #{i+1}  {r['ip']}{tags}")
        print(f"      Score: {r['score']} | Pkts: {r['packets']} | {g.get('city','?')}, {g.get('country','?')} | {g.get('isp','')}")
        if g.get("address"):
            print(f"      {g['address'][:80]}")
    print(f"\n{'='*60}")

    top = results[0]
    # Save _call.json
    save = {"type":"pcap_analysis_v3","timestamp":datetime.now().isoformat(),
            "target_number":target_number,"pcap_file":str(pcap_path),
            "label":label,"total_candidates":len(results),"results":results[:5]}
    (LOG_DIR / f"{label}_call.json").write_text(json.dumps(save, indent=2, default=str))

    # Save _voip.json (compat)
    voip = {"type":"voip_call_capture","timestamp":datetime.now().isoformat(),
            "target_number":target_number,"top_ip":top["ip"],"packets":top["packets"],
            "all_candidates":[{"ip":r["ip"],"packets":r["packets"],"score":r["score"],
                               "mobile":r["geo"].get("mobile",False)} for r in results[:10]],
            "geo":top["geo"],"address":top["geo"].get("address","")}
    (LOG_DIR / f"{label}_voip.json").write_text(json.dumps(voip, indent=2))

    # Log hit
    g = top["geo"]
    try:
        log_hit(label, top["ip"], f"pcap_v3/{target_number}", "", {
            "method":"pcap_v3","hit_type":"real_device","target_number":target_number,
            "score":top["score"],"packets":top["packets"],"mobile":g.get("mobile",False),
            "address":g.get("address",""),"gps_lat":g.get("lat"),"gps_lon":g.get("lon"),
            "gps_accuracy_m":5000 if g.get("mobile") else 25000,"geo_source":"ip_from_pcap"})
        print(f"  Logged: {label}")
    except Exception as e:
        print(f"  (log: {e})")
    return results


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <pcap> <number>")
        sys.exit(1)
    process(sys.argv[1], sys.argv[2])
