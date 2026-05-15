"""
DecisionEngine - Target analysis and agent recommendation engine.

Analyzes a given target (IP, domain, URL, file, etc.) and recommends which
security agents to run, with confidence scores and reasoning for each
recommendation.
"""

from __future__ import annotations

import ipaddress
import logging
import mimetypes
import os
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class AgentRecommendation:
    """A recommendation to run a particular agent against the target."""
    agent_name: str
    confidence: float  # 0.0 to 1.0
    reasoning: str
    priority: int = 0  # Lower number = higher priority
    estimated_duration_minutes: int = 0
    prerequisites: list[str] = field(default_factory=list)


@dataclass
class TargetProfile:
    """Analyzed profile of a target."""
    raw_target: str
    target_type: str  # ip, ipv6, cidr, domain, url, file, email, username, cloud, unknown
    attributes: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


class DecisionEngine:
    """
    Analyzes targets and recommends which security agents to deploy.

    Uses a scoring system that considers target type, detected attributes,
    and contextual signals to produce ranked agent recommendations.
    """

    # Agent definitions with their applicability profiles
    AGENT_PROFILES: dict[str, dict[str, Any]] = {
        "ReconAgent": {
            "target_types": ["ip", "ipv6", "domain", "url", "cidr"],
            "base_score": 0.9,
            "tags_boost": {"external": 0.1, "web": 0.05, "infrastructure": 0.1},
            "tags_penalty": {"file": -0.5, "binary": -0.7, "email": -0.3},
            "description": "Reconnaissance and information gathering",
            "estimated_minutes": 15,
        },
        "WebAppAgent": {
            "target_types": ["url", "domain"],
            "base_score": 0.85,
            "tags_boost": {"web": 0.15, "http": 0.1, "https": 0.1, "api": 0.1},
            "tags_penalty": {"file": -0.6, "binary": -0.8, "email": -0.5},
            "description": "Web application security testing",
            "estimated_minutes": 30,
        },
        "BugBountyAgent": {
            "target_types": ["domain", "url"],
            "base_score": 0.75,
            "tags_boost": {"web": 0.15, "bugbounty": 0.25, "external": 0.1, "production": 0.1},
            "tags_penalty": {"internal": -0.3, "file": -0.6},
            "description": "Bug bounty hunting workflow",
            "estimated_minutes": 60,
        },
        "CTFAgent": {
            "target_types": ["file", "url"],
            "base_score": 0.3,
            "tags_boost": {"ctf": 0.7, "binary": 0.3, "crypto": 0.3, "forensics": 0.3, "challenge": 0.5},
            "tags_penalty": {"production": -0.5, "corporate": -0.3},
            "description": "CTF challenge solving",
            "estimated_minutes": 20,
        },
        "CloudAgent": {
            "target_types": ["cloud", "domain", "url"],
            "base_score": 0.5,
            "tags_boost": {"aws": 0.4, "gcp": 0.4, "azure": 0.4, "kubernetes": 0.4, "cloud": 0.35, "s3": 0.3, "container": 0.2},
            "tags_penalty": {"file": -0.4, "binary": -0.6},
            "description": "Cloud security assessment",
            "estimated_minutes": 25,
        },
        "BinaryAgent": {
            "target_types": ["file"],
            "base_score": 0.3,
            "tags_boost": {"binary": 0.6, "elf": 0.5, "pe": 0.5, "executable": 0.5, "ctf": 0.2},
            "tags_penalty": {"web": -0.4, "domain": -0.5, "cloud": -0.5},
            "description": "Binary analysis and exploitation",
            "estimated_minutes": 20,
        },
        "OSINTAgent": {
            "target_types": ["domain", "email", "username", "ip"],
            "base_score": 0.7,
            "tags_boost": {"person": 0.2, "organization": 0.15, "email": 0.15, "external": 0.1},
            "tags_penalty": {"file": -0.5, "binary": -0.7, "ctf": -0.3},
            "description": "Open source intelligence gathering",
            "estimated_minutes": 20,
        },
    }

    def __init__(self) -> None:
        self._cache: dict[str, list[AgentRecommendation]] = {}

    async def analyze_target(self, target: str) -> list[AgentRecommendation]:
        """
        Analyze a target and return ranked agent recommendations.

        Args:
            target: The target string -- IP, domain, URL, file path, email, etc.

        Returns:
            List of AgentRecommendation objects, sorted by confidence (descending).
        """
        # Check cache
        cache_key = target.strip().lower()
        if cache_key in self._cache:
            logger.debug("Returning cached recommendations for: %s", target)
            return self._cache[cache_key]

        # Build target profile
        profile = self._profile_target(target)
        logger.info(
            "Target profiled: type=%s, tags=%s", profile.target_type, profile.tags
        )

        # Score each agent
        recommendations: list[AgentRecommendation] = []
        for agent_name, agent_profile in self.AGENT_PROFILES.items():
            score = self._score_agent(agent_name, agent_profile, profile)
            if score > 0.1:  # Minimum threshold
                reasoning = self._build_reasoning(agent_name, agent_profile, profile, score)
                recommendations.append(
                    AgentRecommendation(
                        agent_name=agent_name,
                        confidence=round(min(score, 1.0), 3),
                        reasoning=reasoning,
                        priority=0,
                        estimated_duration_minutes=agent_profile.get("estimated_minutes", 15),
                    )
                )

        # Sort by confidence descending
        recommendations.sort(key=lambda r: r.confidence, reverse=True)

        # Assign priorities
        for i, rec in enumerate(recommendations):
            rec.priority = i + 1

        # Set prerequisites (ReconAgent should generally run before others)
        for rec in recommendations:
            if rec.agent_name in ("WebAppAgent", "BugBountyAgent") and any(
                r.agent_name == "ReconAgent" for r in recommendations
            ):
                rec.prerequisites = ["ReconAgent"]

        self._cache[cache_key] = recommendations
        return recommendations

    def _profile_target(self, target: str) -> TargetProfile:
        """Build a detailed profile of the target."""
        target = target.strip()
        profile = TargetProfile(raw_target=target, target_type="unknown")

        # --- Type detection ---

        # Email
        if re.match(r"^[\w.+-]+@[\w-]+\.[\w.-]+$", target):
            profile.target_type = "email"
            profile.tags.append("email")
            domain = target.split("@")[1]
            profile.attributes["domain"] = domain
            profile.attributes["local_part"] = target.split("@")[0]
            return profile

        # URL
        if re.match(r"^https?://", target):
            profile.target_type = "url"
            parsed = urlparse(target)
            profile.attributes["scheme"] = parsed.scheme
            profile.attributes["hostname"] = parsed.hostname
            profile.attributes["port"] = parsed.port
            profile.attributes["path"] = parsed.path
            profile.attributes["query"] = parsed.query
            profile.tags.append("web")
            if parsed.scheme == "https":
                profile.tags.append("https")
            else:
                profile.tags.append("http")
            if parsed.path and parsed.path != "/":
                profile.tags.append("specific_path")
            if parsed.query:
                profile.tags.append("parameterized")
            # Check for API indicators
            if any(kw in (parsed.path or "").lower() for kw in ("/api/", "/v1/", "/v2/", "/graphql")):
                profile.tags.append("api")
            # Check for cloud indicators
            self._tag_cloud_indicators(target, profile)
            profile.tags.append("external")
            return profile

        # CIDR
        try:
            network = ipaddress.ip_network(target, strict=False)
            profile.target_type = "cidr"
            profile.attributes["network"] = str(network)
            profile.attributes["num_hosts"] = network.num_addresses
            profile.tags.extend(["infrastructure", "external"])
            if network.is_private:
                profile.tags.append("internal")
                profile.tags.remove("external")
            return profile
        except ValueError:
            pass

        # IP address
        try:
            addr = ipaddress.ip_address(target)
            profile.target_type = "ipv6" if addr.version == 6 else "ip"
            profile.attributes["ip"] = str(addr)
            profile.tags.append("infrastructure")
            if addr.is_private:
                profile.tags.append("internal")
            else:
                profile.tags.append("external")
            return profile
        except ValueError:
            pass

        # File path
        if os.path.exists(target) or target.startswith("/") or target.startswith("./"):
            profile.target_type = "file"
            profile.tags.append("file")
            if os.path.exists(target):
                profile.attributes["size"] = os.path.getsize(target)
                profile.attributes["path"] = os.path.abspath(target)
                mime_type, _ = mimetypes.guess_type(target)
                if mime_type:
                    profile.attributes["mime_type"] = mime_type
                ext = os.path.splitext(target)[1].lower()
                profile.attributes["extension"] = ext
                self._tag_file_type(ext, mime_type or "", profile)
            return profile

        # Cloud identifiers
        if self._is_cloud_target(target):
            profile.target_type = "cloud"
            self._tag_cloud_indicators(target, profile)
            return profile

        # Domain (fallback for anything with dots and no spaces)
        if "." in target and " " not in target:
            profile.target_type = "domain"
            profile.attributes["domain"] = target
            profile.tags.extend(["web", "external"])
            self._tag_cloud_indicators(target, profile)
            return profile

        # Username (starts with @)
        if target.startswith("@"):
            profile.target_type = "username"
            profile.tags.append("person")
            profile.attributes["username"] = target.lstrip("@")
            return profile

        # Person name (contains spaces)
        if " " in target:
            profile.target_type = "username"
            profile.tags.append("person")
            profile.attributes["name"] = target
            return profile

        # Unknown -- treat as username
        profile.target_type = "username"
        profile.attributes["value"] = target
        return profile

    def _tag_file_type(self, ext: str, mime_type: str, profile: TargetProfile) -> None:
        """Add tags based on file type."""
        binary_extensions = {".elf", ".exe", ".bin", ".so", ".dll", ".o", ".out"}
        image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".svg"}
        archive_extensions = {".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar"}
        crypto_extensions = {".pem", ".key", ".crt", ".csr", ".p12", ".pfx"}
        script_extensions = {".py", ".rb", ".pl", ".sh", ".js", ".php"}

        if ext in binary_extensions or "executable" in mime_type or "elf" in mime_type:
            profile.tags.extend(["binary", "executable"])
        elif ext in image_extensions or mime_type.startswith("image/"):
            profile.tags.extend(["image", "forensics"])
        elif ext in archive_extensions:
            profile.tags.extend(["archive", "forensics"])
        elif ext in crypto_extensions:
            profile.tags.extend(["crypto"])
        elif ext in script_extensions:
            profile.tags.extend(["script"])
        elif ext == ".pcap" or ext == ".pcapng":
            profile.tags.extend(["pcap", "forensics"])
        elif ext == ".pdf":
            profile.tags.extend(["document", "forensics"])

    def _is_cloud_target(self, target: str) -> bool:
        """Check if the target appears to be a cloud resource identifier."""
        cloud_patterns = [
            r"arn:aws:",
            r"s3://",
            r"gs://",
            r"az://",
            r"projects/[\w-]+",
            r"subscriptions/[\w-]+",
            r"\.amazonaws\.com",
            r"\.azure\.com",
            r"\.googleapis\.com",
        ]
        return any(re.search(p, target, re.IGNORECASE) for p in cloud_patterns)

    def _tag_cloud_indicators(self, target: str, profile: TargetProfile) -> None:
        """Add cloud-related tags based on target content."""
        target_lower = target.lower()
        cloud_tags = {
            "aws": ["aws", "amazon", "arn:", "s3://", "ec2", "amazonaws"],
            "gcp": ["gcp", "google", "gcloud", "gs://", "googleapis"],
            "azure": ["azure", "microsoft", ".azure."],
            "kubernetes": ["k8s", "kubernetes", "kubectl", "kube-"],
        }
        for tag, keywords in cloud_tags.items():
            if any(kw in target_lower for kw in keywords):
                profile.tags.append(tag)
                if "cloud" not in profile.tags:
                    profile.tags.append("cloud")

    def _score_agent(
        self, agent_name: str, agent_profile: dict[str, Any], target: TargetProfile
    ) -> float:
        """Calculate a confidence score for an agent against a target profile."""
        # Start with base score if target type matches
        valid_types = agent_profile.get("target_types", [])
        if target.target_type in valid_types:
            score = agent_profile.get("base_score", 0.5)
        else:
            # Partial match -- reduced base score
            score = agent_profile.get("base_score", 0.5) * 0.3

        # Apply tag boosts
        boosts = agent_profile.get("tags_boost", {})
        for tag in target.tags:
            if tag in boosts:
                score += boosts[tag]

        # Apply tag penalties
        penalties = agent_profile.get("tags_penalty", {})
        for tag in target.tags:
            if tag in penalties:
                score += penalties[tag]  # penalties are negative

        # Ensure score is in valid range
        return max(0.0, min(1.0, score))

    def _build_reasoning(
        self,
        agent_name: str,
        agent_profile: dict[str, Any],
        target: TargetProfile,
        score: float,
    ) -> str:
        """Build a human-readable reasoning string for the recommendation."""
        parts: list[str] = []

        # Target type match
        valid_types = agent_profile.get("target_types", [])
        if target.target_type in valid_types:
            parts.append(
                f"Target type '{target.target_type}' is a primary target for {agent_name}."
            )
        else:
            parts.append(
                f"Target type '{target.target_type}' is not a primary target, but "
                f"partial applicability detected."
            )

        # Boosting tags
        boosts = agent_profile.get("tags_boost", {})
        matched_boosts = [tag for tag in target.tags if tag in boosts]
        if matched_boosts:
            parts.append(
                f"Positive signals: {', '.join(matched_boosts)}."
            )

        # Penalty tags
        penalties = agent_profile.get("tags_penalty", {})
        matched_penalties = [tag for tag in target.tags if tag in penalties]
        if matched_penalties:
            parts.append(
                f"Reducing factors: {', '.join(matched_penalties)}."
            )

        # Agent description
        parts.append(f"Agent purpose: {agent_profile.get('description', '')}.")

        return " ".join(parts)

    def clear_cache(self) -> None:
        """Clear the recommendation cache."""
        self._cache.clear()

    async def get_execution_plan(
        self, target: str, max_agents: int = 5
    ) -> list[dict[str, Any]]:
        """
        Generate an ordered execution plan for the target.

        Args:
            target: The target to analyze.
            max_agents: Maximum number of agents to include.

        Returns:
            List of execution steps with agent info and ordering.
        """
        recommendations = await self.analyze_target(target)
        selected = recommendations[:max_agents]

        plan: list[dict[str, Any]] = []
        completed: set[str] = set()
        remaining = list(selected)

        step = 1
        while remaining:
            # Find agents whose prerequisites are met
            runnable = [
                r for r in remaining
                if all(p in completed for p in r.prerequisites)
            ]
            if not runnable:
                # Break deadlock -- run the highest-confidence remaining agent
                runnable = [remaining[0]]

            for rec in runnable:
                plan.append({
                    "step": step,
                    "agent": rec.agent_name,
                    "confidence": rec.confidence,
                    "reasoning": rec.reasoning,
                    "estimated_minutes": rec.estimated_duration_minutes,
                    "prerequisites": rec.prerequisites,
                })
                completed.add(rec.agent_name)
                remaining.remove(rec)
                step += 1

        return plan
