"""
SocialINTAgent - Social Intelligence gathering agent.

Performs comprehensive social intelligence operations including username
hunting, email intelligence, phone OSINT, social media scraping, breach
data correlation, and cross-platform identity resolution.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# FP filter integration
try:
    import sys as _sys
    import os as _os
    _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
    from core.fp_filter import quick_score_phone, quick_score_email
    HAS_FP_FILTER = True
except ImportError:
    HAS_FP_FILTER = False


@dataclass
class SocialFinding:
    """A single social intelligence data point."""
    category: str
    source_tool: str
    data_type: str  # username, email, phone, profile, breach, media
    value: str
    platform: str = ""
    url: str = ""
    confidence: float = 1.0
    context: str = ""
    raw_source: str = ""


class SocialINTAgent:
    """Social Intelligence gathering agent."""

    name: str = "SocialINTAgent"
    description: str = (
        "Performs comprehensive social intelligence gathering including "
        "username hunting across 2500+ platforms, email registration checks, "
        "phone number OSINT, social media profile scraping, breach data "
        "correlation, and cross-platform identity resolution."
    )

    techniques = [
        "username_hunt",
        "email_intel",
        "phone_intel",
        "social_scrape",
        "breach_check",
        "profile_analysis",
        "face_search",
        "identity_correlation",
    ]

    def __init__(self) -> None:
        self.findings: list[SocialFinding] = []

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

        # Auto-select techniques based on target type
        if target_type == "username":
            commands.extend(self._cmd_username_hunt(target, target_type))
            commands.extend(self._cmd_identity_correlation(target, target_type))
        elif target_type == "email":
            commands.extend(self._cmd_email_intel(target, target_type))
            commands.extend(self._cmd_breach_check(target, target_type))
        elif target_type == "phone":
            commands.extend(self._cmd_phone_intel(target, target_type))
        elif target_type == "url":
            commands.extend(self._cmd_social_scrape(target, target_type))
            commands.extend(self._cmd_profile_analysis(target, target_type))
        else:
            # Try everything
            commands.extend(self._cmd_username_hunt(target, target_type))
            commands.extend(self._cmd_email_intel(target, target_type))

        return commands

    def _detect_target_type(self, target: str) -> str:
        if re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}$', target):
            return "email"
        if re.match(r'^\+?[0-9\s\-()]{7,20}$', target):
            return "phone"
        if target.startswith(("http://", "https://")):
            return "url"
        if re.match(r'^@?[a-zA-Z0-9_.]{1,50}$', target):
            return "username"
        return "unknown"

    # -- Technique commands ------------------------------------------------

    def _cmd_username_hunt(self, target: str, ttype: str) -> list[dict[str, str]]:
        username = target.lstrip("@")
        return [
            {"tool": "sherlock", "command": f"sherlock {username} --print-found --timeout 10", "description": "Hunt username across 400+ sites"},
            {"tool": "maigret", "command": f"maigret {username} --timeout 8 --no-color", "description": "Deep username search across 2500+ sites"},
            {"tool": "blackbird", "command": f"blackbird --username {username}", "description": "Username enumeration with web visualization"},
            {"tool": "nexfil", "command": f"nexfil -u {username}", "description": "Username search on 350+ platforms"},
            {"tool": "holehe", "command": f"holehe {username}@gmail.com", "description": "Check email registrations (Gmail variant)"},
        ]

    def _cmd_email_intel(self, target: str, ttype: str) -> list[dict[str, str]]:
        return [
            {"tool": "holehe", "command": f"holehe {target}", "description": "Check which sites this email is registered on"},
            {"tool": "h8mail", "command": f"h8mail -t {target}", "description": "Search email in breach databases"},
            {"tool": "ghunt", "command": f"ghunt email {target}", "description": "Investigate linked Google account"},
            {"tool": "ignorant", "command": f"ignorant {target}", "description": "Check email/phone registrations on sites"},
            {"tool": "curl", "command": f'curl -s "https://emailrep.io/{target}" -H "User-Agent: StrikeCore" | jq .', "description": "Email reputation and activity score"},
        ]

    def _cmd_phone_intel(self, target: str, ttype: str) -> list[dict[str, str]]:
        phone = target.replace(" ", "").replace("-", "")
        return [
            {"tool": "phoneinfoga", "command": f"phoneinfoga scan -n {phone}", "description": "Phone number OSINT scan"},
            {"tool": "ignorant", "command": f"ignorant {phone}", "description": "Check phone registrations on services"},
            {"tool": "curl", "command": f'curl -s "http://apilayer.net/api/validate?number={phone}" | jq .', "description": "Phone number validation and carrier lookup"},
        ]

    def _cmd_social_scrape(self, target: str, ttype: str) -> list[dict[str, str]]:
        cmds = []
        if "instagram.com" in target:
            username = target.rstrip("/").split("/")[-1]
            cmds.append({"tool": "instaloader", "command": f"instaloader --no-pictures --no-videos --no-video-thumbnails {username}", "description": "Scrape Instagram profile metadata"})
            cmds.append({"tool": "toutatis", "command": f"toutatis -u {username}", "description": "Instagram OSINT via Toutatis"})
        if "youtube.com" in target or "youtu.be" in target:
            cmds.append({"tool": "yt-dlp", "command": f"yt-dlp --dump-json --no-download {target}", "description": "Extract YouTube video/channel metadata"})
        if "twitter.com" in target or "x.com" in target:
            cmds.append({"tool": "snscrape", "command": f"snscrape twitter-user {target.split('/')[-1]}", "description": "Scrape Twitter/X profile"})
        if not cmds:
            cmds.append({"tool": "gallery-dl", "command": f"gallery-dl --dump-json {target}", "description": "Extract media metadata from URL"})
        return cmds

    def _cmd_breach_check(self, target: str, ttype: str) -> list[dict[str, str]]:
        return [
            {"tool": "h8mail", "command": f"h8mail -t {target} --loose", "description": "Search breached databases for target"},
            {"tool": "curl", "command": f'curl -s "https://api.pwnedpasswords.com/range/$(echo -n {target} | sha1sum | cut -c1-5)" | head -20', "description": "Check password hash in HIBP range API"},
        ]

    def _cmd_profile_analysis(self, target: str, ttype: str) -> list[dict[str, str]]:
        return [
            {"tool": "social-analyzer", "command": f'social-analyzer --username "{target}" --metadata --top 50', "description": "Cross-platform profile analysis with metadata"},
        ]

    def _cmd_identity_correlation(self, target: str, ttype: str) -> list[dict[str, str]]:
        username = target.lstrip("@")
        return [
            {"tool": "social-analyzer", "command": f'social-analyzer --username "{username}" --metadata --extract --top 100', "description": "Cross-platform identity correlation"},
            {"tool": "sherlock", "command": f"sherlock {username} --print-found --csv", "description": "Export found profiles as CSV for correlation"},
        ]

    def _cmd_face_search(self, target: str, ttype: str) -> list[dict[str, str]]:
        return [
            {"tool": "curl", "command": f'echo "Face search requires manual upload to pimeyes.com or facecheck.id with image: {target}"', "description": "Reverse face search guidance"},
        ]

    # ── FP Filter Integration ──

    def score_finding(self, finding: SocialFinding, target_name: str | None = None) -> dict:
        """Score a SocialFinding through fp_filter. Returns dict with score, confidence, action."""
        if not HAS_FP_FILTER:
            return {"score": 0, "confidence": str(finding.confidence), "action": "include"}

        if finding.data_type == "phone":
            return quick_score_phone(finding.value, [finding.source_tool], target_name)
        elif finding.data_type == "email":
            return quick_score_email(finding.value, [finding.source_tool], target_name)
        return {"score": 0, "confidence": str(finding.confidence), "action": "include"}

    def filter_findings(self, target_name: str | None = None) -> list[SocialFinding]:
        """Filter all findings through fp_filter, removing rejects."""
        filtered = []
        for finding in self.findings:
            if finding.data_type in ("phone", "email"):
                result = self.score_finding(finding, target_name)
                if result["action"] == "reject":
                    logger.info(
                        "REJECTED %s: %s (score=%s)",
                        finding.data_type, finding.value, result["score"],
                    )
                    continue
                finding.confidence = result.get("score", 0) / 10.0
            filtered.append(finding)
        self.findings = filtered
        return filtered
