#!/usr/bin/env python3
"""
StrikeCore Call Sniffer v3 — Real-time peer IP extraction + precision geolocation.

Captures VoIP/WebRTC P2P traffic during WhatsApp, Telegram, Instagram, or
Messenger calls to extract the target's real public IP and geolocate them.

Usage:
    sudo call-sniffer -i wlp0s20f3 -t mario_rossi                # Quick 60s capture
    sudo call-sniffer -i wlp0s20f3 -t mario_rossi -d 180         # 3 min capture
    sudo call-sniffer -i wlp0s20f3 -t mario_rossi --continuous    # Until Ctrl+C
    sudo call-sniffer -i wlp0s20f3 -t mario_rossi --save-pcap    # Save raw PCAP too
    sudo call-sniffer --list-interfaces

Workflow:
    1. Run this BEFORE starting the call
    2. Call the target on WhatsApp/Telegram/Instagram
    3. Wait 10-30s for P2P link to establish
    4. Script extracts peer IP, geolocates with multi-API + reverse geocode
    5. Results: ~/strikecore-data/ip_logs/{label}_call.json + dashboard tracker
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# ── Import shared modules from core ──

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.ip_logger import (
    LOG_DIR, is_excluded, get_local_ips, geolocate_full, log_hit,
)

# ── ANSI helpers ──

CYAN = "\033[1;36m"
YELLOW = "\033[1;33m"
GREEN = "\033[1;32m"
RED = "\033[1;31m"
WHITE = "\033[1;37m"
RESET = "\033[0m"
LINE = "=" * 60


# ── Subprocess context managers ──

@contextmanager
def managed_process(cmd: list[str], **kwargs):
    """Run a subprocess with guaranteed cleanup on exit or signal."""
    proc = subprocess.Popen(cmd, **kwargs)
    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


# ── Packet capture engine ──

class CaptureSession:
    """Manages a tshark capture session with clean process lifecycle."""

    BPF = "udp and (port 3478 or port 19302 or portrange 10000-65535)"

    TSHARK_FIELDS = [
        "ip.src", "ip.dst", "ipv6.src", "ipv6.dst",
        "udp.srcport", "udp.dstport",
        "stun.att.ipv4", "stun.att.ipv6",
        "frame.len", "frame.time_epoch",
    ]

    def __init__(self, iface: str, duration: int, continuous: bool,
                 label: str, save_pcap: bool):
        self.iface = iface
        self.duration = duration
        self.continuous = continuous
        self.label = label
        self.save_pcap = save_pcap

        self.local_ips = get_local_ips()
        self.candidates: dict[str, dict] = {}
        self.stun_ips: set[str] = set()
        self._stopped = False

    def run(self) -> list[dict]:
        """Execute the full capture → score → geolocate → save pipeline."""
        self._print_banner()

        # Register SIGINT for clean shutdown
        original_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._handle_signal)

        try:
            self._capture()
        finally:
            signal.signal(signal.SIGINT, original_handler)

        if not self.candidates:
            self._print_no_results()
            return []

        ranked = self._score_candidates()
        geo_results = self._geolocate_top(ranked)
        self._save_results(geo_results)
        return geo_results

    # ── Capture phase ──

    def _capture(self):
        """Run tshark and optionally a parallel PCAP writer."""
        tshark_cmd = self._build_tshark_cmd()
        pcap_path = ""

        # Optional raw PCAP saver (parallel process)
        pcap_ctx = self._pcap_writer() if self.save_pcap else None

        with managed_process(tshark_cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True) as proc:
            if pcap_ctx:
                pcap_ctx.__enter__()

            try:
                self._read_packets(proc)
            finally:
                if pcap_ctx:
                    pcap_ctx.__exit__(None, None, None)

        print("\n")

    def _build_tshark_cmd(self) -> list[str]:
        cmd = [
            "tshark", "-i", self.iface, "-f", self.BPF, "-l",
            "-T", "fields",
        ]
        for field in self.TSHARK_FIELDS:
            cmd += ["-e", field]
        cmd += ["-E", "separator=|"]

        if not self.continuous:
            cmd += ["-a", f"duration:{self.duration}"]

        return cmd

    @contextmanager
    def _pcap_writer(self):
        """Context manager for the optional parallel PCAP capture."""
        pcap_path = str(LOG_DIR / f"{self.label or 'call'}_{int(time.time())}.pcap")
        cmd = [
            "tshark", "-i", self.iface, "-f", self.BPF,
            "-w", pcap_path, "-a", f"duration:{self.duration + 10}",
        ]
        with managed_process(cmd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL) as proc:
            self._pcap_path = pcap_path
            yield proc

    def _read_packets(self, proc: subprocess.Popen):
        """Parse tshark output line by line, updating candidates."""
        start = time.time()
        last_status = 0

        for line in proc.stdout:
            if self._stopped:
                break

            parts = line.strip().split("|")
            if len(parts) < 10:
                continue

            (src4, dst4, src6, dst6, sport, dport,
             stun4, stun6, flen_s, _ftime) = parts[:10]
            flen = int(flen_s) if flen_s else 0

            # Track non-local, non-infrastructure IPs
            for ip in (src4, dst4, src6, dst6):
                if ip and ip not in self.local_ips and not is_excluded(ip):
                    self._update_candidate(ip, flen, sport, dport)

            # STUN-revealed IPs (NAT traversal → peer's real public IP)
            for sip in (stun4, stun6):
                if sip and sip not in self.local_ips and not is_excluded(sip):
                    self.stun_ips.add(sip)
                    self._update_candidate(sip, 0, "", "")
                    self.candidates[sip]["stun"] += 1

            # Status line (every 2s)
            now = time.time()
            if now - last_status > 2:
                self._print_status(int(now - start))
                last_status = now

    def _update_candidate(self, ip: str, flen: int, sport: str, dport: str):
        """Add or update a candidate IP entry."""
        if ip not in self.candidates:
            self.candidates[ip] = {
                "packets": 0, "bytes": 0, "first": time.time(),
                "last": time.time(), "ports": set(), "stun": 0,
            }
        c = self.candidates[ip]
        c["packets"] += 1
        c["bytes"] += flen
        c["last"] = time.time()
        for p in (sport, dport):
            if p and p.isdigit():
                c["ports"].add(int(p))

    def _handle_signal(self, signum, frame):
        self._stopped = True

    # ── Scoring phase ──

    def _score_candidates(self) -> list[dict]:
        """Score and rank all candidate IPs."""
        results = []
        for ip, c in self.candidates.items():
            score = 0.0
            score += c["stun"] * 30                          # STUN = strongest signal
            score += min(c["packets"] * 0.3, 40)             # Packet volume (capped)
            score += min(c["bytes"] / 5000, 25)              # Byte volume (media)
            high_ports = [p for p in c["ports"] if 10000 <= p <= 65535]
            score += min(len(high_ports) * 3, 15)            # RTP-range ports
            duration_s = c["last"] - c["first"]
            if duration_s > 5:
                score += min(duration_s * 0.5, 20)           # Sustained connection
            if ip in self.stun_ips:
                score += 25                                   # STUN membership bonus

            results.append({
                "ip": ip,
                "score": round(score, 1),
                "packets": c["packets"],
                "bytes": c["bytes"],
                "first": c["first"],
                "last": c["last"],
                "ports": sorted(c["ports"])[:15],
                "stun": c["stun"],
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    # ── Geolocation phase ──

    def _geolocate_top(self, ranked: list[dict], top_n: int = 5) -> list[dict]:
        """Geolocate the top N candidates and print results."""
        print(f"{CYAN}{LINE}{RESET}")
        print(f"{CYAN}  RESULTS — {len(ranked)} candidate IPs{RESET}")
        print(f"{CYAN}{LINE}{RESET}")

        geo_results = []
        for i, r in enumerate(ranked[:top_n]):
            geo = geolocate_full(r["ip"])
            r["geo"] = geo
            self._print_candidate(i, r)
            geo_results.append(r)

        print(f"\n{CYAN}{LINE}{RESET}")
        return geo_results

    # ── Persistence ──

    def _save_results(self, geo_results: list[dict]):
        """Save results to JSON and optionally log to tracker."""
        label = self.label or f"call_{int(time.time())}"

        save_data = {
            "type": "call_sniffer_v3",
            "timestamp": datetime.now().isoformat(),
            "interface": self.iface,
            "label": self.label,
            "total_candidates": len(self.candidates),
            "stun_ips": list(self.stun_ips),
            "results": geo_results,
        }
        if hasattr(self, "_pcap_path"):
            save_data["pcap_file"] = self._pcap_path

        out_path = LOG_DIR / f"{label}_call.json"
        out_path.write_text(json.dumps(save_data, indent=2, default=str))
        print(f"  Saved: {out_path}")

        # Log top result as tracking hit
        if geo_results and geo_results[0]["score"] > 15:
            self._log_tracking_hit(label, geo_results[0])

    def _log_tracking_hit(self, label: str, top: dict):
        """Push the top result into the StrikeCore tracker."""
        geo = top.get("geo", {})
        try:
            log_hit(label, top["ip"], "call_sniffer_v3", "", {
                "method": "call_sniffer",
                "hit_type": "real_device",
                "score": top["score"],
                "stun_hits": top["stun"],
                "packets": top["packets"],
                "address": geo.get("address", ""),
                "road": geo.get("road", ""),
                "suburb": geo.get("suburb", ""),
                "postcode": geo.get("postcode", ""),
                "gps_lat": geo.get("lat"),
                "gps_lon": geo.get("lon"),
                "gps_accuracy_m": 20000,
                "geo_source": "ip_from_call",
            })
            print(f"  Logged to tracker: {label}")
        except Exception as e:
            print(f"  (tracker log failed: {e})")

    # ── Output ──

    def _print_banner(self):
        print(f"{CYAN}{LINE}{RESET}")
        print(f"{CYAN}  StrikeCore Call Sniffer v3{RESET}")
        print(f"{CYAN}{LINE}{RESET}")
        print(f"  Interface: {self.iface}")
        dur = "continuous (Ctrl+C)" if self.continuous else f"{self.duration}s"
        print(f"  Duration:  {dur}")
        print(f"  Label:     {self.label or '(none)'}")
        print(f"  Local IPs: {', '.join(sorted(self.local_ips)[:4])}")
        print()
        print(f"{YELLOW}  >>> START THE CALL NOW <<<{RESET}")
        print()

    def _print_status(self, elapsed: int):
        n = len(self.candidates)
        s = len(self.stun_ips)
        pkts = sum(c["packets"] for c in self.candidates.values())
        best = ""
        if self.candidates:
            top_ip = max(self.candidates,
                         key=lambda k: self.candidates[k]["stun"] * 100
                         + self.candidates[k]["packets"])
            best = f" | Best: {top_ip}"
            if self.candidates[top_ip]["stun"]:
                best += f" [STUN x{self.candidates[top_ip]['stun']}]"
        print(f"\r  [{elapsed}s] {n} candidates | {s} STUN | {pkts} pkts{best}   ",
              end="", flush=True)

    def _print_candidate(self, idx: int, r: dict):
        geo = r.get("geo", {})
        stun_tag = f" {GREEN}[STUN x{r['stun']}]{RESET}" if r["stun"] else ""
        top_tag = f" {YELLOW}<<< LIKELY TARGET{RESET}" if r["score"] > 30 else ""

        print(f"\n  {WHITE}#{idx+1}  {r['ip']}{RESET}{stun_tag}{top_tag}")
        dur = r["last"] - r["first"]
        print(f"      Score: {r['score']} | Pkts: {r['packets']} "
              f"| Bytes: {r['bytes']} | Dur: {dur:.0f}s")

        if geo.get("city"):
            flags = ""
            if geo.get("mobile"):  flags += " [MOBILE]"
            if geo.get("vpn"):     flags += " [VPN]"
            if geo.get("proxy"):   flags += " [PROXY]"
            print(f"      {GREEN}Location: {geo['city']}, "
                  f"{geo.get('region','')}, {geo['country']}{RESET}{flags}")
            print(f"      ISP: {geo.get('isp','')} | ASN: {geo.get('as','')}")
            if geo.get("address"):
                print(f"      {YELLOW}Address: {geo['address'][:100]}{RESET}")
            if geo.get("road"):
                print(f"      Street: {geo['road']} {geo.get('house_number','')}, "
                      f"{geo.get('suburb','')}")
                print(f"      ZIP: {geo.get('postcode','')} "
                      f"{geo.get('municipality','')}")
            print(f"      Coords: {geo.get('lat',0):.6f}, {geo.get('lon',0):.6f}")
            if geo.get("hostname"):
                print(f"      Hostname: {geo['hostname']}")

    def _print_no_results(self):
        print(f"{RED}  No peer IPs captured.{RESET}")
        print("  Possible causes:")
        print("    - Call was relayed via TURN server (not P2P)")
        print("    - Wrong interface (try: --list-interfaces)")
        print("    - Call wasn't active during capture")
        print("    - Target uses VPN that routes media through relay")


# ── Interface listing ──

def list_interfaces():
    print("  Available interfaces:")
    try:
        out = subprocess.check_output(["ip", "-o", "link", "show", "up"], text=True)
        for line in out.split("\n"):
            if not line.strip():
                continue
            parts = line.split(":")
            name = parts[1].strip().split("@")[0]
            try:
                ip_out = subprocess.check_output(
                    ["ip", "-o", "-4", "addr", "show", name], text=True)
                m = re.search(r"inet\s+([^\s/]+)", ip_out)
                ip = m.group(1) if m else "no IPv4"
            except Exception:
                ip = "?"
            flag = " (recommended)" if name.startswith(("wl", "en")) else ""
            if name != "lo":
                print(f"    {name:20} {ip:20}{flag}")
    except Exception:
        subprocess.run(["tshark", "-D"], check=False)


# ── Auto-detect interface ──

def detect_interface() -> str:
    try:
        out = subprocess.check_output(["ip", "-o", "link", "show", "up"], text=True)
        for line in out.split("\n"):
            if ":" not in line:
                continue
            name = line.split(":")[1].strip().split("@")[0]
            if name and name not in ("lo", "docker0") and not name.startswith("veth"):
                return name
    except Exception:
        pass
    return ""


# ── CLI ──

def main():
    parser = argparse.ArgumentParser(
        description="StrikeCore Call Sniffer v3 — P2P peer IP extraction + geolocation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  sudo call-sniffer -i wlp0s20f3 -t mario_rossi
  sudo call-sniffer -i wlp0s20f3 -t mario_rossi -d 180 --save-pcap
  sudo call-sniffer -i wlp0s20f3 --continuous
  sudo call-sniffer --list-interfaces
""")
    parser.add_argument("--iface", "-i", default="", help="Network interface")
    parser.add_argument("--duration", "-d", type=int, default=60,
                        help="Capture seconds (default 60)")
    parser.add_argument("--continuous", "-c", action="store_true",
                        help="Capture until Ctrl+C")
    parser.add_argument("--target-label", "-t", default="",
                        help="Target label (for filename)")
    parser.add_argument("--save-pcap", action="store_true",
                        help="Save raw PCAP file")
    parser.add_argument("--list-interfaces", "-l", action="store_true")

    args = parser.parse_args()

    if args.list_interfaces:
        list_interfaces()
        return

    if not args.iface:
        args.iface = detect_interface()
        if not args.iface:
            print("[!] No interface found. Use --iface or --list-interfaces")
            sys.exit(1)

    duration = 86400 if args.continuous else args.duration

    session = CaptureSession(
        iface=args.iface,
        duration=duration,
        continuous=args.continuous,
        label=args.target_label,
        save_pcap=args.save_pcap,
    )
    session.run()


if __name__ == "__main__":
    main()
