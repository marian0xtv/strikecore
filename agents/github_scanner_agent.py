"""
GitHubScannerAgent — Discovers, evaluates and integrates OSINT tools from GitHub.

Searches GitHub for open-source OSINT tools (phone lookup, email verification,
breach checkers, etc.), evaluates them for quality and compatibility, and
generates integration wrappers for StrikeCore's tool registry.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolCandidate:
    """A GitHub repository evaluated as a potential tool to integrate."""
    name: str
    full_name: str  # owner/repo
    url: str
    description: str
    stars: int
    language: str
    last_updated: str
    license: str = ""
    category: str = ""  # phone, email, breach, validation, etc.
    score: float = 0.0  # 0-10 evaluation score
    already_integrated: bool = False
    install_command: str = ""
    test_command: str = ""
    notes: str = ""


class GitHubScannerAgent:
    """Scans GitHub for OSINT tools to integrate into StrikeCore."""

    name: str = "GitHubScannerAgent"
    description: str = (
        "Discovers, evaluates and proposes integration of open-source OSINT "
        "tools from GitHub. Focuses on phone lookup, email verification, "
        "breach correlation, and contact validation tools."
    )

    techniques = [
        "discover_phone_tools",
        "discover_email_tools",
        "discover_validation_tools",
        "discover_breach_tools",
        "evaluate_tool",
        "integrate_tool",
    ]

    # Tools already in StrikeCore (skip these)
    KNOWN_TOOLS = frozenset({
        "phoneinfoga", "sherlock", "maigret", "holehe", "h8mail",
        "ignorant", "blackbird", "nexfil", "social-analyzer",
        "instaloader", "toutatis", "ghunt", "crosslinked",
        "yt-dlp", "gallery-dl", "exiftool", "theHarvester",
    })

    # Search queries per category
    SEARCH_QUERIES = {
        "phone": [
            "phone OSINT lookup stars:>50 language:Python",
            "phone number intelligence tool stars:>30",
            "caller ID lookup open source stars:>20",
            "phone validation carrier lookup python",
            "reverse phone lookup OSINT",
            "moriarty phone osint",
        ],
        "email": [
            "email OSINT verification stars:>50 language:Python",
            "email breach check tool stars:>30",
            "email to phone correlation osint",
            "email permutation finder osint",
            "email intelligence gathering python",
        ],
        "validation": [
            "phone number validation library python stars:>100",
            "email validation MX check python stars:>50",
            "data verification OSINT tool",
        ],
        "breach": [
            "breach database search tool stars:>50",
            "leaked data search OSINT stars:>30",
            "credential leak checker python",
            "data breach lookup open source",
        ],
    }

    def __init__(self) -> None:
        self.candidates: list[ToolCandidate] = []
        self._gh_api_base = "https://api.github.com"
        self._headers = {"User-Agent": "StrikeCore-Scanner/1.0"}
        # Use GitHub token if available
        gh_token = os.environ.get("GITHUB_TOKEN", "")
        if gh_token:
            self._headers["Authorization"] = f"token {gh_token}"

    @classmethod
    def get_all_techniques(cls) -> list[str]:
        return list(cls.techniques)

    def get_commands(self, target: str | None = None, technique: str | None = None) -> list[dict[str, str]]:
        """Return commands for a given technique."""
        commands: list[dict[str, str]] = []

        if technique:
            method = getattr(self, f"_cmd_{technique}", None)
            if method:
                commands.extend(method(target))
            return commands

        # Default: discover all categories
        for cat in ["phone", "email", "validation", "breach"]:
            commands.extend(self._cmd_discover(cat))
        return commands

    def _cmd_discover(self, category: str) -> list[dict[str, str]]:
        queries = self.SEARCH_QUERIES.get(category, [])
        cmds = []
        for q in queries[:3]:
            encoded = q.replace(" ", "+")
            cmds.append({
                "tool": "curl",
                "command": f'curl -s "https://api.github.com/search/repositories?q={encoded}&sort=stars&per_page=10" -H "User-Agent: StrikeCore"',
                "description": f"Search GitHub for {category} tools: {q}",
            })
        return cmds

    def _cmd_discover_phone_tools(self, target: str | None = None) -> list[dict[str, str]]:
        return self._cmd_discover("phone")

    def _cmd_discover_email_tools(self, target: str | None = None) -> list[dict[str, str]]:
        return self._cmd_discover("email")

    def _cmd_discover_validation_tools(self, target: str | None = None) -> list[dict[str, str]]:
        return self._cmd_discover("validation")

    def _cmd_discover_breach_tools(self, target: str | None = None) -> list[dict[str, str]]:
        return self._cmd_discover("breach")

    def _cmd_evaluate_tool(self, repo_full_name: str | None = None) -> list[dict[str, str]]:
        if not repo_full_name:
            return []
        return [
            {"tool": "curl", "command": f'curl -s "https://api.github.com/repos/{repo_full_name}" -H "User-Agent: StrikeCore"', "description": f"Get repo info for {repo_full_name}"},
            {"tool": "curl", "command": f'curl -s "https://api.github.com/repos/{repo_full_name}/readme" -H "User-Agent: StrikeCore" | python3 -c "import sys,json,base64; print(base64.b64decode(json.load(sys.stdin).get(\"content\",\"\")+\"==\").decode(errors=\"ignore\")[:3000])"', "description": f"Read README for {repo_full_name}"},
        ]

    def _cmd_integrate_tool(self, repo_full_name: str | None = None) -> list[dict[str, str]]:
        if not repo_full_name:
            return []
        name = repo_full_name.split("/")[-1]
        return [
            {"tool": "bash", "command": f'cd /tmp && git clone --depth 1 https://github.com/{repo_full_name}.git 2>&1 | tail -3', "description": f"Clone {repo_full_name}"},
            {"tool": "bash", "command": f'cd /tmp/{name} && (pip install . 2>&1 || pip install -r requirements.txt 2>&1) | tail -5', "description": f"Install {name}"},
            {"tool": "bash", "command": f'which {name} 2>/dev/null || python3 -m {name} --help 2>&1 | head -10', "description": f"Test {name}"},
        ]

    # ── Discovery logic (for programmatic use) ──

    def discover(self, category: str = "all") -> list[ToolCandidate]:
        """Search GitHub for tools in the given category. Returns list of candidates."""
        import urllib.request

        categories = [category] if category != "all" else list(self.SEARCH_QUERIES.keys())
        seen_repos = set()

        for cat in categories:
            queries = self.SEARCH_QUERIES.get(cat, [])
            for query in queries[:2]:  # Limit to avoid rate limiting
                encoded = query.replace(" ", "+")
                url = f"{self._gh_api_base}/search/repositories?q={encoded}&sort=stars&per_page=10"

                try:
                    req = urllib.request.Request(url, headers=self._headers)
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        data = json.loads(resp.read())
                except Exception as e:
                    logger.warning(f"GitHub search failed for '{query}': {e}")
                    continue

                for item in data.get("items", []):
                    full_name = item.get("full_name", "")
                    name = item.get("name", "").lower()

                    if full_name in seen_repos:
                        continue
                    seen_repos.add(full_name)

                    # Check if already integrated
                    if name in self.KNOWN_TOOLS:
                        continue

                    candidate = ToolCandidate(
                        name=item.get("name", ""),
                        full_name=full_name,
                        url=item.get("html_url", ""),
                        description=item.get("description", "") or "",
                        stars=item.get("stargazers_count", 0),
                        language=item.get("language", "") or "",
                        last_updated=item.get("pushed_at", "")[:10],
                        license=(item.get("license") or {}).get("spdx_id", ""),
                        category=cat,
                    )

                    # Score the candidate
                    candidate.score = self._score_candidate(candidate)

                    if candidate.score >= 3.0:
                        self.candidates.append(candidate)

                time.sleep(1)  # Rate limiting

        # Sort by score
        self.candidates.sort(key=lambda c: c.score, reverse=True)
        return self.candidates

    def _score_candidate(self, c: ToolCandidate) -> float:
        """Score a tool candidate 0-10 based on quality metrics."""
        score = 0.0

        # Stars (max 3 points)
        if c.stars >= 1000:
            score += 3.0
        elif c.stars >= 500:
            score += 2.5
        elif c.stars >= 100:
            score += 2.0
        elif c.stars >= 50:
            score += 1.0

        # Language preference (max 2 points)
        if c.language.lower() == "python":
            score += 2.0
        elif c.language.lower() in ("go", "javascript", "shell"):
            score += 1.0

        # License (max 1 point)
        open_licenses = {"MIT", "Apache-2.0", "GPL-3.0", "GPL-2.0", "BSD-2-Clause", "BSD-3-Clause", "AGPL-3.0"}
        if c.license in open_licenses:
            score += 1.0

        # Recency (max 2 points)
        if c.last_updated:
            try:
                from datetime import datetime
                updated = datetime.strptime(c.last_updated, "%Y-%m-%d")
                days_ago = (datetime.now() - updated).days
                if days_ago < 90:
                    score += 2.0
                elif days_ago < 365:
                    score += 1.0
            except Exception:
                pass

        # Description quality (max 1 point)
        good_keywords = ["osint", "phone", "email", "lookup", "intelligence",
                         "verification", "breach", "validation", "reverse"]
        matches = sum(1 for kw in good_keywords if kw in c.description.lower())
        score += min(matches * 0.25, 1.0)

        # Already integrated penalty
        if c.name.lower() in self.KNOWN_TOOLS:
            score = 0.0

        return min(score, 10.0)

    def evaluate(self, repo_full_name: str) -> ToolCandidate | None:
        """Deep evaluation of a specific repo."""
        import urllib.request

        try:
            req = urllib.request.Request(
                f"{self._gh_api_base}/repos/{repo_full_name}",
                headers=self._headers,
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            logger.error(f"Cannot evaluate {repo_full_name}: {e}")
            return None

        candidate = ToolCandidate(
            name=data.get("name", ""),
            full_name=repo_full_name,
            url=data.get("html_url", ""),
            description=data.get("description", "") or "",
            stars=data.get("stargazers_count", 0),
            language=data.get("language", "") or "",
            last_updated=data.get("pushed_at", "")[:10],
            license=(data.get("license") or {}).get("spdx_id", ""),
        )
        candidate.score = self._score_candidate(candidate)

        # Try to determine install method from README
        try:
            req = urllib.request.Request(
                f"{self._gh_api_base}/repos/{repo_full_name}/readme",
                headers=self._headers,
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                readme_data = json.loads(resp.read())
            import base64
            readme = base64.b64decode(readme_data.get("content", "")).decode(errors="ignore")

            # Detect install method
            if "pip install" in readme:
                pip_match = re.search(r'pip install (\S+)', readme)
                if pip_match:
                    candidate.install_command = f"pip install {pip_match.group(1)}"
            elif "requirements.txt" in readme:
                candidate.install_command = f"cd /tmp/{candidate.name} && pip install -r requirements.txt"

            # Detect test/usage command
            usage_match = re.search(r'(?:usage|example)[:\s]*\n', readme, re.IGNORECASE | re.DOTALL)
            if usage_match:
                candidate.test_command = usage_match.group(1).strip().split("\n")[0]

        except Exception:
            pass

        return candidate

    def format_report(self) -> str:
        """Generate a formatted report of discovered tools."""
        lines = [
            "\n" + "=" * 60,
            "  GITHUB SCANNER — TOOL DISCOVERY REPORT",
            "=" * 60,
            f"  Candidates found: {len(self.candidates)}",
            "",
        ]

        for cat in ["phone", "email", "validation", "breach"]:
            cat_tools = [c for c in self.candidates if c.category == cat]
            if cat_tools:
                lines.append(f"\n  [{cat.upper()}]")
                for c in cat_tools[:5]:
                    lines.append(f"    [{c.score:.1f}/10] {c.full_name} ({c.stars} stars, {c.language})")
                    lines.append(f"             {c.description[:80]}")
                    if c.install_command:
                        lines.append(f"             Install: {c.install_command}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)
