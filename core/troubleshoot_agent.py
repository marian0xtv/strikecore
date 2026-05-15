"""
StrikeCore Troubleshoot Sub-Agent.

Auto-invoked when tools fail. Diagnoses errors and generates fixes:
- Rate-limit → rotate proxy and retry
- Missing dependency → install or use alternative
- Auth required → switch to unauthenticated method
- Syntax error → correct the command
- Network error → retry with proxy
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Diagnosis:
    """Result of error diagnosis."""
    error_type: str        # rate_limit, auth, syntax, network, dependency, permission, unknown
    description: str       # Human-readable explanation
    fix_command: str        # Fixed/alternative command to run
    use_proxy: bool        # Whether to route through proxy
    retry: bool            # Whether this is a retry of the same goal
    confidence: float      # 0.0-1.0


class TroubleshootAgent:
    """Diagnoses tool failures and generates automatic fixes."""

    # Error patterns → (error_type, description_template, fix_strategy)
    PATTERNS = [
        # Rate limiting
        (r"429|Too Many Requests|rate.?limit|throttl|Retry-After|retried in \d+ minutes",
         "rate_limit", "API rate limit hit", "proxy_retry"),

        # Instagram specific
        (r"challenge_required|login_required|checkpoint_required",
         "auth", "Instagram requires login/challenge", "alt_method"),
        (r"Please.*login|not logged in|authentication required|Unauthorized",
         "auth", "Authentication required", "alt_method"),

        # Network
        (r"Connection refused|Connection reset|timeout|timed out|Network is unreachable",
         "network", "Network/connection error", "proxy_retry"),
        (r"SSL|certificate|CERTIFICATE_VERIFY_FAILED",
         "network", "SSL/TLS error", "skip_ssl"),

        # Command not found
        (r"not found|No such file|command not found|ModuleNotFoundError",
         "dependency", "Tool/module not found", "alt_tool"),

        # Permission
        (r"Permission denied|EPERM|Operation not permitted|requires root",
         "permission", "Permission denied", "add_sudo"),

        # Python/syntax errors
        (r"SyntaxError|TypeError|ValueError|AttributeError|ImportError",
         "syntax", "Python runtime error", "alt_tool"),

        # Empty/no results
        (r"^$|no results|nothing found|0 results",
         "empty", "No results returned", "alt_tool"),
    ]

    # Alternative tool mappings
    ALTERNATIVES = {
        "instaloader": [
            ("gallery-dl", 'gallery-dl --dump-json "https://www.instagram.com/{target}/"'),
            ("curl+jq", 'curl -sL "https://www.instagram.com/{target}/?__a=1&__d=dis" -H "User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)" | jq . 2>/dev/null || echo "API blocked, trying Wayback..."'),
            ("wayback", 'curl -s "https://web.archive.org/web/2024/https://www.instagram.com/{target}/" | grep -oP \'(?<=content=")[^"]*(?=")\' | head -20'),
        ],
        "toutatis": [
            ("instaloader", "instaloader --no-pictures --no-videos {target}"),
            ("curl", 'curl -sL "https://www.instagram.com/{target}/?__a=1" -H "User-Agent: Instagram 275.0" | jq .graphql.user'),
        ],
        "sherlock": [
            ("maigret", "maigret {target} --timeout 8 --no-color"),
            ("blackbird", "blackbird -u {target}"),
            ("nexfil", "nexfil -u {target}"),
        ],
        "maigret": [
            ("sherlock", "sherlock {target} --print-found --timeout 10"),
            ("blackbird", "blackbird -u {target}"),
            ("nexfil", "nexfil -u {target}"),
        ],
        "holehe": [
            ("mosint", "mosint {target}"),
            ("h8mail", "h8mail -t {target}"),
            ("curl_emailrep", 'curl -s "https://emailrep.io/{target}" -H "User-Agent: StrikeCore" | jq .'),
        ],
        "socialscan": [
            ("sherlock", "sherlock {target} --print-found --timeout 10"),
            ("blackbird", "blackbird -u {target}"),
        ],
        "social-analyzer": [
            ("sherlock", "sherlock {target} --print-found --timeout 10"),
            ("nexfil", "nexfil -u {target}"),
        ],
        "gallery-dl": [
            ("yt-dlp", "yt-dlp --dump-json --no-download {target}"),
            ("curl", 'curl -sL "{target}" -H "User-Agent: Mozilla/5.0" | grep -oP \'https?://[^"\\s]+\' | head -20'),
        ],
        "phoneinfoga": [
            ("ignorant", "ignorant {cc} {number}"),
            ("curl_numverify", 'curl -s "http://apilayer.net/api/validate?number={target}" | jq .'),
        ],
    }

    def diagnose(self, tool: str, command: str, output: str, exit_code: int) -> Optional[Diagnosis]:
        """Analyze a failed command and return a diagnosis with fix."""
        if exit_code == 0 and not self._is_empty(output):
            return None  # Not a failure

        combined = f"{output} EXIT:{exit_code}"

        # Match against patterns
        for pattern, err_type, desc_tmpl, strategy in self.PATTERNS:
            if re.search(pattern, combined, re.IGNORECASE):
                fix = self._generate_fix(tool, command, strategy, err_type)
                if fix:
                    return Diagnosis(
                        error_type=err_type,
                        description=desc_tmpl,
                        fix_command=fix["command"],
                        use_proxy=fix.get("use_proxy", False),
                        retry=fix.get("retry", False),
                        confidence=fix.get("confidence", 0.7),
                    )

        # Unknown error
        return Diagnosis(
            error_type="unknown",
            description=f"Unknown error (exit {exit_code})",
            fix_command="",
            use_proxy=False,
            retry=False,
            confidence=0.0,
        )

    def _is_empty(self, output: str) -> bool:
        cleaned = output.strip()
        return len(cleaned) < 5

    def _extract_target(self, command: str) -> str:
        """Extract the target (username/email/URL) from a command."""
        parts = command.split()
        # Skip the tool name and flags
        for p in reversed(parts):
            if not p.startswith("-") and not p.startswith("/"):
                return p.strip("'\"")
        return ""

    def _generate_fix(self, tool: str, command: str, strategy: str, err_type: str) -> Optional[dict]:
        target = self._extract_target(command)
        tool_base = tool.split("/")[-1].split()[0]

        if strategy == "proxy_retry":
            return {
                "command": f"proxychains4 -q {command}",
                "use_proxy": True,
                "retry": True,
                "confidence": 0.8,
            }

        elif strategy == "alt_method":
            alts = self.ALTERNATIVES.get(tool_base, [])
            if alts:
                alt_name, alt_cmd = alts[0]
                return {
                    "command": alt_cmd.format(target=target),
                    "use_proxy": False,
                    "retry": False,
                    "confidence": 0.7,
                }

        elif strategy == "alt_tool":
            alts = self.ALTERNATIVES.get(tool_base, [])
            if alts:
                alt_name, alt_cmd = alts[0]
                return {
                    "command": alt_cmd.format(target=target),
                    "use_proxy": False,
                    "retry": False,
                    "confidence": 0.7,
                }

        elif strategy == "add_sudo":
            if not command.startswith("sudo"):
                return {
                    "command": f"sudo {command}",
                    "use_proxy": False,
                    "retry": True,
                    "confidence": 0.9,
                }

        elif strategy == "skip_ssl":
            if "curl" in command:
                return {
                    "command": command.replace("curl", "curl -k"),
                    "use_proxy": False,
                    "retry": True,
                    "confidence": 0.8,
                }

        return None

    def get_all_alternatives(self, tool: str) -> list[tuple[str, str]]:
        """Return all known alternatives for a tool."""
        return self.ALTERNATIVES.get(tool, [])
