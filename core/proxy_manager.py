"""
StrikeCore Proxy Manager — Tor rotation, rate-limit evasion, multi-identity.

Provides:
- Tor SOCKS5 proxy with automatic circuit rotation
- proxychains wrapper for any command
- Rate-limit detection and automatic retry with new identity
- Multi-Tor-instance support for parallel requests
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import time
from dataclasses import dataclass

log = logging.getLogger("core.proxy_manager")

# Tor runs as a container on the bridge net (decision I7). Host/port + control
# password come from the environment; defaults work for a host-native tor too.
TOR_HOST = os.environ.get("TOR_HOST", "127.0.0.1")
TOR_CONTROL_PORT = int(os.environ.get("TOR_CONTROL_PORT", "9051"))
TOR_SOCKS_PORT = int(os.environ.get("TOR_SOCKS_PORT", "9050"))
# HashedControlPassword auth: the cleartext password is shared via env to both
# the tor image and this client. Cookie auth can't cross containers, so it's gone.
TOR_CONTROL_PASSWORD = os.environ.get("TOR_CONTROL_PASSWORD", "")


@dataclass
class ProxyIdentity:
    """Represents a proxy circuit."""
    ip: str = ""
    port: int = TOR_SOCKS_PORT
    last_rotation: float = 0.0
    request_count: int = 0


class ProxyManager:
    """Manages Tor-based proxy rotation for OSINT tools."""

    def __init__(self) -> None:
        self._current_ip: str = ""
        self._rotation_count: int = 0
        # No host setup: the tor container ships its own torrc with
        # ControlPort + HashedControlPassword. (Decision I7: host sudo/systemctl
        # and torrc-write paths removed.)

    def rotate_identity(self) -> bool:
        """Send NEWNYM to the Tor container for a new circuit/IP.

        Authenticates with HashedControlPassword over the control port. Failures
        are SURFACED (logged at WARNING) rather than silently swallowed — a silent
        rotation failure means OSINT tools keep hitting rate limits / risk
        deanonymisation with the operator none the wiser.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect((TOR_HOST, TOR_CONTROL_PORT))
                s.send(f'AUTHENTICATE "{TOR_CONTROL_PASSWORD}"\r\n'.encode())
                resp = s.recv(256)
                if b"250" not in resp:
                    log.warning("tor AUTHENTICATE rejected (check TOR_CONTROL_PASSWORD): %r", resp)
                    return False
                s.send(b"SIGNAL NEWNYM\r\n")
                resp = s.recv(256)
                if b"250" in resp:
                    self._rotation_count += 1
                    time.sleep(3)  # Wait for new circuit
                    return True
                log.warning("tor SIGNAL NEWNYM not acknowledged: %r", resp)
        except OSError as exc:
            log.warning("tor control connection to %s:%s failed: %s",
                        TOR_HOST, TOR_CONTROL_PORT, exc)
        return False

    def get_current_ip(self) -> str:
        """Get current Tor exit IP."""
        try:
            result = subprocess.run(
                ["proxychains4", "-q", "curl", "-s", "--max-time", "10",
                 "https://api.ipify.org"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                self._current_ip = result.stdout.strip()
                return self._current_ip
        except Exception:
            pass
        return "unknown"

    def wrap_command(self, cmd: str, use_proxy: bool = True) -> str:
        """Wrap a command with proxychains if needed."""
        if not use_proxy:
            return cmd
        # Don't double-wrap
        if cmd.startswith("proxychains"):
            return cmd
        # Don't proxy local commands
        local_cmds = ("cat ", "echo ", "python3 ", "jq ", "grep ", "awk ",
                      "sed ", "head ", "tail ", "wc ", "sort ", "ls ", "cd ")
        if any(cmd.startswith(c) for c in local_cmds):
            return cmd
        return f"proxychains4 -q {cmd}"

    @property
    def rotation_count(self) -> int:
        return self._rotation_count


# Rate-limit aware tools — these need proxy rotation
RATE_LIMITED_TOOLS = {
    "toutatis", "gallery-dl", "holehe", "ignorant",
    "sherlock", "maigret", "socialscan", "social-analyzer", "nexfil",
    "blackbird", "h8mail", "mosint", "ghunt", "eyes", "curl",
}

def needs_proxy(cmd: str) -> bool:
    """Check if a command should be routed through proxy."""
    first_word = cmd.split()[0] if cmd.split() else ""
    # Strip sudo prefix
    if first_word == "sudo":
        first_word = cmd.split()[1] if len(cmd.split()) > 1 else ""
    # Strip path
    first_word = os.path.basename(first_word)
    return first_word in RATE_LIMITED_TOOLS

def is_rate_limited(output: str) -> bool:
    """Detect rate-limiting in command output."""
    indicators = [
        "429", "Too Many Requests", "rate limit", "rate-limit",
        "temporarily blocked", "try again later", "please wait",
        "throttled", "too many attempts", "CAPTCHA",
        "challenge_required", "login_required",
        "retried in", "Retry-After",
    ]
    output_lower = output.lower()
    return any(ind.lower() in output_lower for ind in indicators)
