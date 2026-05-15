"""
OSINTAgent - Open Source Intelligence gathering agent.

Performs comprehensive OSINT operations including target profiling, email
harvesting, social media enumeration, domain intelligence gathering,
data breach checking, and cross-source correlation.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class OSINTFinding:
    """A single OSINT data point."""
    category: str
    source_tool: str
    data_type: str  # email, username, domain, ip, phone, social_profile, etc.
    value: str
    context: str = ""
    confidence: float = 1.0
    related_to: list[str] = field(default_factory=list)
    raw_source: str = ""


class OSINTAgent:
    """Open Source Intelligence gathering agent."""

    name: str = "OSINTAgent"
    description: str = (
        "Performs comprehensive open source intelligence gathering including "
        "target profiling, email harvesting, social media enumeration, "
        "domain intelligence, data breach checking, and cross-source "
        "correlation analysis."
    )

    tools: list[str] = [
        "theHarvester",
        "recon-ng",
        "maltego",
        "spiderfoot",
        "shodan",
        "censys",
        "whois",
        "social-analyzer",
        "holehe",
        "sherlock",
    ]

    methodology: list[str] = [
        "1. Target Profiling - Identify target type and gather initial intelligence",
        "2. Email Harvesting - Discover email addresses associated with the target",
        "3. Social Media Enumeration - Find social media profiles and usernames",
        "4. Domain Intelligence - WHOIS, DNS, and infrastructure mapping",
        "5. Data Breach Checking - Check for compromised credentials and data exposure",
        "6. Correlation - Cross-reference findings across all sources",
    ]

    system_prompt: str = (
        "You are an OSINT (Open Source Intelligence) specialist within the StrikeCore "
        "framework. Your role is to gather intelligence from publicly available sources "
        "in a systematic and thorough manner.\n\n"
        "RULES:\n"
        "- Only use publicly available information and authorized tools.\n"
        "- Respect privacy laws and ethical boundaries.\n"
        "- Cross-reference findings across multiple sources for validation.\n"
        "- Assign confidence levels to all findings.\n"
        "- Track the provenance of every piece of information.\n"
        "- Look for connections and patterns across data points.\n\n"
        "FOCUS AREAS:\n"
        "- Email addresses and naming conventions\n"
        "- Social media presence and digital footprint\n"
        "- Domain and infrastructure relationships\n"
        "- Historical data and archived content\n"
        "- Public data breaches and leaked credentials\n"
        "- Organizational relationships and employee information\n\n"
        "METHODOLOGY:\n"
        "1. Target Profiling\n"
        "2. Email Harvesting\n"
        "3. Social Media Enumeration\n"
        "4. Domain Intelligence\n"
        "5. Data Breach Checking\n"
        "6. Correlation"
    )

    def __init__(self) -> None:
        self.findings: list[OSINTFinding] = []
        self._target_type: str = "unknown"
        self._emails: set[str] = set()
        self._usernames: set[str] = set()
        self._social_profiles: list[dict[str, str]] = []
        self._domains: set[str] = set()
        self._ips: set[str] = set()
        self._organization_info: dict[str, Any] = {}

    async def run(self, target: str, agent_core: Any) -> dict[str, Any]:
        """
        Execute the full OSINT methodology.

        Args:
            target: The target to investigate (person name, email, domain, username, IP).
            agent_core: The core agent loop handler.

        Returns:
            Dictionary containing all OSINT findings and correlations.
        """
        logger.info("OSINTAgent starting against target: %s", target)

        self._target_type = self._classify_target(target)

        context = {
            "agent_name": self.name,
            "system_prompt": self.system_prompt,
            "tools": self.tools,
            "target": target,
            "methodology": self.methodology,
            "target_type": self._target_type,
        }

        results: dict[str, Any] = {
            "target": target,
            "target_type": self._target_type,
            "phases": {},
            "summary": {},
        }

        # Phase 1: Target Profiling
        results["phases"]["target_profiling"] = await self._phase_target_profiling(
            target, agent_core
        )

        # Phase 2: Email Harvesting
        results["phases"]["email_harvesting"] = await self._phase_email_harvesting(
            target, agent_core
        )

        # Phase 3: Social Media Enumeration
        results["phases"]["social_media"] = await self._phase_social_media(
            target, agent_core
        )

        # Phase 4: Domain Intelligence
        results["phases"]["domain_intelligence"] = await self._phase_domain_intelligence(
            target, agent_core
        )

        # Phase 5: Data Breach Checking
        results["phases"]["breach_check"] = await self._phase_breach_check(
            target, agent_core
        )

        # Phase 6: Correlation
        results["phases"]["correlation"] = self._phase_correlation()

        results["summary"] = self._build_summary()
        results["findings"] = [
            {
                "category": f.category,
                "source_tool": f.source_tool,
                "data_type": f.data_type,
                "value": f.value,
                "context": f.context,
                "confidence": f.confidence,
                "related_to": f.related_to,
            }
            for f in self.findings
        ]

        logger.info(
            "OSINTAgent completed. %d findings, %d emails, %d social profiles.",
            len(self.findings), len(self._emails), len(self._social_profiles),
        )

        return await agent_core.delegate(context, results)

    def _classify_target(self, target: str) -> str:
        """Classify the type of OSINT target."""
        target = target.strip()
        if re.match(r"^[\w.+-]+@[\w-]+\.[\w.-]+$", target):
            return "email"
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", target):
            return "ip"
        if re.match(r"^https?://", target):
            return "url"
        if "." in target and not " " in target:
            return "domain"
        if target.startswith("@"):
            return "username"
        if " " in target:
            return "person"
        return "username"

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    async def _phase_target_profiling(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 1: Initial target profiling."""
        phase_results: dict[str, Any] = {"tools_used": [], "profile": {}}

        # SpiderFoot for automated OSINT scan
        spiderfoot_result = await agent_core.run_tool(
            "spiderfoot",
            ["-s", target, "-t", "all", "-q", "-o", "json"],
        )
        phase_results["tools_used"].append("spiderfoot")

        if not isinstance(spiderfoot_result, Exception):
            output = spiderfoot_result.get("output", "") if isinstance(spiderfoot_result, dict) else str(spiderfoot_result)
            # Extract data points from SpiderFoot results
            emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", output)
            self._emails.update(emails)
            domains = re.findall(r"(?:[\w-]+\.)+(?:com|org|net|io|co|gov|edu|info)\b", output)
            self._domains.update(domains)
            ips = re.findall(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", output)
            self._ips.update(ips)

            for email in emails:
                self.findings.append(
                    OSINTFinding(
                        category="email",
                        source_tool="spiderfoot",
                        data_type="email",
                        value=email,
                        context="Discovered during initial profiling",
                    )
                )

        # For domain targets, get whois info
        if self._target_type in ("domain", "url"):
            domain = self._extract_domain(target)
            whois_result = await agent_core.run_tool("whois", [domain])
            phase_results["tools_used"].append("whois")

            if not isinstance(whois_result, Exception):
                output = whois_result.get("output", "") if isinstance(whois_result, dict) else str(whois_result)
                self._parse_whois(output, domain)
                phase_results["profile"]["whois"] = output[:3000]

        phase_results["profile"]["target_type"] = self._target_type
        return phase_results

    async def _phase_email_harvesting(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 2: Email address discovery."""
        phase_results: dict[str, Any] = {"tools_used": [], "emails": []}

        domain = self._extract_domain(target)
        if not domain and self._target_type == "email":
            domain = target.split("@")[1] if "@" in target else ""

        if domain:
            # theHarvester
            harvester_result = await agent_core.run_tool(
                "theHarvester",
                ["-d", domain, "-b", "all", "-l", "500"],
            )
            phase_results["tools_used"].append("theHarvester")

            if not isinstance(harvester_result, Exception):
                output = harvester_result.get("output", "") if isinstance(harvester_result, dict) else str(harvester_result)
                emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", output)
                for email in emails:
                    email = email.lower()
                    if email not in self._emails:
                        self._emails.add(email)
                        self.findings.append(
                            OSINTFinding(
                                category="email",
                                source_tool="theHarvester",
                                data_type="email",
                                value=email,
                                context=f"Harvested from domain {domain}",
                            )
                        )

            # recon-ng email modules
            reconng_result = await agent_core.run_tool(
                "recon-ng",
                [
                    "-w", "strikecore",
                    "-C", f"db insert domains {domain}",
                    "-C", "modules load recon/domains-contacts/whois_pocs",
                    "-C", "run",
                    "-C", "modules load recon/domains-contacts/metacrawler",
                    "-C", "run",
                    "-C", "show contacts",
                ],
            )
            phase_results["tools_used"].append("recon-ng")

            if not isinstance(reconng_result, Exception):
                output = reconng_result.get("output", "") if isinstance(reconng_result, dict) else str(reconng_result)
                emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", output)
                for email in emails:
                    email = email.lower()
                    if email not in self._emails:
                        self._emails.add(email)
                        self.findings.append(
                            OSINTFinding(
                                category="email",
                                source_tool="recon-ng",
                                data_type="email",
                                value=email,
                                context=f"Discovered via recon-ng modules",
                            )
                        )

        # If target is an email, check account existence with holehe
        if self._target_type == "email" or self._emails:
            emails_to_check = [target] if self._target_type == "email" else list(self._emails)[:10]
            for email in emails_to_check:
                holehe_result = await agent_core.run_tool("holehe", [email])
                phase_results["tools_used"].append("holehe")
                if not isinstance(holehe_result, Exception):
                    output = holehe_result.get("output", "") if isinstance(holehe_result, dict) else str(holehe_result)
                    # Parse holehe output for registered services
                    registered = re.findall(r"\[(\+)\]\s*(\S+)", output)
                    for _, service in registered:
                        self.findings.append(
                            OSINTFinding(
                                category="email_registration",
                                source_tool="holehe",
                                data_type="service_registration",
                                value=service,
                                context=f"Email {email} is registered on {service}",
                                related_to=[email],
                            )
                        )

        phase_results["emails"] = sorted(self._emails)
        phase_results["total"] = len(self._emails)
        return phase_results

    async def _phase_social_media(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 3: Social media profile enumeration."""
        phase_results: dict[str, Any] = {"tools_used": [], "profiles": []}

        # Determine usernames to check
        usernames: set[str] = set()
        if self._target_type == "username":
            usernames.add(target.lstrip("@"))
        elif self._target_type == "person":
            # Generate username variations
            parts = target.lower().split()
            if len(parts) >= 2:
                first, last = parts[0], parts[-1]
                usernames.update([
                    f"{first}{last}",
                    f"{first}.{last}",
                    f"{first}_{last}",
                    f"{first[0]}{last}",
                    f"{last}{first}",
                ])
        elif self._target_type == "email":
            local_part = target.split("@")[0]
            usernames.add(local_part)

        # Extract usernames from email addresses
        for email in self._emails:
            local = email.split("@")[0]
            if len(local) > 3:
                usernames.add(local)

        self._usernames = usernames

        # Sherlock for username checking across platforms
        for username in list(usernames)[:5]:
            sherlock_result = await agent_core.run_tool(
                "sherlock",
                [username, "--print-found", "--no-color", "--timeout", "10"],
            )
            phase_results["tools_used"].append("sherlock")
            if not isinstance(sherlock_result, Exception):
                output = sherlock_result.get("output", "") if isinstance(sherlock_result, dict) else str(sherlock_result)
                for line in output.splitlines():
                    url_match = re.search(r"(https?://\S+)", line)
                    if url_match:
                        profile_url = url_match.group(1)
                        platform = self._extract_platform(profile_url)
                        profile = {"username": username, "platform": platform, "url": profile_url}
                        self._social_profiles.append(profile)
                        self.findings.append(
                            OSINTFinding(
                                category="social_media",
                                source_tool="sherlock",
                                data_type="social_profile",
                                value=profile_url,
                                context=f"Username '{username}' found on {platform}",
                                related_to=[username],
                            )
                        )

        # social-analyzer for deeper social media analysis
        if usernames:
            username_list = " ".join(list(usernames)[:3])
            social_result = await agent_core.run_tool(
                "social-analyzer",
                ["--username", username_list, "--metadata", "--output", "json"],
            )
            phase_results["tools_used"].append("social-analyzer")
            if not isinstance(social_result, Exception):
                output = social_result.get("output", "") if isinstance(social_result, dict) else str(social_result)
                # Extract found profiles
                found = re.findall(r'"link":\s*"(https?://[^"]+)"', output)
                for link in found:
                    platform = self._extract_platform(link)
                    if not any(p["url"] == link for p in self._social_profiles):
                        self._social_profiles.append({
                            "platform": platform,
                            "url": link,
                        })
                        self.findings.append(
                            OSINTFinding(
                                category="social_media",
                                source_tool="social-analyzer",
                                data_type="social_profile",
                                value=link,
                                context=f"Profile found on {platform}",
                            )
                        )

        phase_results["profiles"] = self._social_profiles
        phase_results["total"] = len(self._social_profiles)
        return phase_results

    async def _phase_domain_intelligence(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 4: Domain and infrastructure intelligence."""
        phase_results: dict[str, Any] = {"tools_used": [], "domains": [], "infrastructure": {}}

        domain = self._extract_domain(target)
        if not domain and self._domains:
            domain = next(iter(self._domains))

        if not domain:
            phase_results["skipped"] = True
            phase_results["reason"] = "No domain to investigate."
            return phase_results

        # Shodan for infrastructure
        shodan_result = await agent_core.run_tool("shodan", ["domain", domain])
        phase_results["tools_used"].append("shodan")
        if not isinstance(shodan_result, Exception):
            output = shodan_result.get("output", "") if isinstance(shodan_result, dict) else str(shodan_result)
            ips = re.findall(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", output)
            self._ips.update(ips)
            self.findings.append(
                OSINTFinding(
                    category="infrastructure",
                    source_tool="shodan",
                    data_type="infrastructure",
                    value=domain,
                    context=f"Shodan data: {output[:500]}",
                    related_to=list(ips)[:10],
                )
            )

        # Censys for certificate transparency
        censys_result = await agent_core.run_tool("censys", ["search", domain])
        phase_results["tools_used"].append("censys")
        if not isinstance(censys_result, Exception):
            output = censys_result.get("output", "") if isinstance(censys_result, dict) else str(censys_result)
            # Extract additional domains from certificates
            cert_domains = re.findall(r"(?:[\w-]+\.)+[\w-]+", output)
            for d in cert_domains:
                if d not in self._domains and domain in d:
                    self._domains.add(d)
                    self.findings.append(
                        OSINTFinding(
                            category="domain",
                            source_tool="censys",
                            data_type="domain",
                            value=d,
                            context="Discovered via certificate transparency",
                            related_to=[domain],
                        )
                    )

        # Maltego-style entity enrichment via recon-ng
        reconng_result = await agent_core.run_tool(
            "recon-ng",
            [
                "-w", "strikecore",
                "-C", f"db insert domains {domain}",
                "-C", "modules load recon/domains-hosts/hackertarget",
                "-C", "run",
                "-C", "modules load recon/hosts-hosts/resolve",
                "-C", "run",
                "-C", "show hosts",
            ],
        )
        phase_results["tools_used"].append("recon-ng")
        if not isinstance(reconng_result, Exception):
            output = reconng_result.get("output", "") if isinstance(reconng_result, dict) else str(reconng_result)
            hosts = re.findall(r"((?:[\w-]+\.)+[\w-]+)\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", output)
            for hostname, ip in hosts:
                self._ips.add(ip)
                self.findings.append(
                    OSINTFinding(
                        category="infrastructure",
                        source_tool="recon-ng",
                        data_type="host_mapping",
                        value=f"{hostname} -> {ip}",
                        context="DNS resolution via recon-ng",
                    )
                )

        # IP-based lookups for discovered infrastructure
        for ip in list(self._ips)[:10]:
            shodan_ip = await agent_core.run_tool("shodan", ["host", ip])
            if not isinstance(shodan_ip, Exception):
                output = shodan_ip.get("output", "") if isinstance(shodan_ip, dict) else str(shodan_ip)
                self.findings.append(
                    OSINTFinding(
                        category="infrastructure",
                        source_tool="shodan",
                        data_type="ip_info",
                        value=ip,
                        context=output[:500],
                    )
                )

        phase_results["domains"] = sorted(self._domains)
        phase_results["ips"] = sorted(self._ips)
        return phase_results

    async def _phase_breach_check(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 5: Check for data breaches and exposed credentials."""
        phase_results: dict[str, Any] = {"tools_used": [], "breaches_found": 0}

        # Use SpiderFoot for breach checking
        emails_to_check = list(self._emails)[:20]
        if self._target_type == "email":
            emails_to_check.insert(0, target)

        for email in emails_to_check:
            sf_result = await agent_core.run_tool(
                "spiderfoot",
                ["-s", email, "-t", "EMAILADDR_COMPROMISED,ACCOUNT_EXTERNAL_OWNED", "-q"],
            )
            phase_results["tools_used"].append("spiderfoot")
            if not isinstance(sf_result, Exception):
                output = sf_result.get("output", "") if isinstance(sf_result, dict) else str(sf_result)
                if "compromised" in output.lower() or "breach" in output.lower():
                    phase_results["breaches_found"] += 1
                    self.findings.append(
                        OSINTFinding(
                            category="breach",
                            source_tool="spiderfoot",
                            data_type="breach_record",
                            value=email,
                            context=f"Email found in data breach: {output[:500]}",
                            confidence=0.85,
                        )
                    )

        # Domain-level breach checking
        domain = self._extract_domain(target)
        if domain:
            sf_domain = await agent_core.run_tool(
                "spiderfoot",
                ["-s", domain, "-t", "EMAILADDR_COMPROMISED", "-q"],
            )
            if not isinstance(sf_domain, Exception):
                output = sf_domain.get("output", "") if isinstance(sf_domain, dict) else str(sf_domain)
                breach_emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", output)
                for email in breach_emails:
                    if email.lower() not in self._emails:
                        self._emails.add(email.lower())
                        self.findings.append(
                            OSINTFinding(
                                category="breach",
                                source_tool="spiderfoot",
                                data_type="breached_email",
                                value=email,
                                context=f"Email from {domain} found in breach data",
                                confidence=0.8,
                            )
                        )

        return phase_results

    def _phase_correlation(self) -> dict[str, Any]:
        """Phase 6: Cross-reference and correlate all findings."""
        correlations: list[dict[str, Any]] = []

        # Group findings by value for cross-referencing
        value_sources: dict[str, list[str]] = {}
        for f in self.findings:
            key = f.value.lower()
            if key not in value_sources:
                value_sources[key] = []
            value_sources[key].append(f.source_tool)

        # Find values confirmed by multiple sources
        for value, sources in value_sources.items():
            unique_sources = list(set(sources))
            if len(unique_sources) > 1:
                correlations.append({
                    "value": value,
                    "confirmed_by": unique_sources,
                    "confidence": min(1.0, 0.5 + 0.15 * len(unique_sources)),
                })

        # Email-to-social-profile correlation
        for email in self._emails:
            local_part = email.split("@")[0]
            related_profiles = [
                p for p in self._social_profiles
                if local_part.lower() in p.get("username", "").lower()
                or local_part.lower() in p.get("url", "").lower()
            ]
            if related_profiles:
                correlations.append({
                    "type": "email_social_correlation",
                    "email": email,
                    "profiles": [p["url"] for p in related_profiles],
                    "confidence": 0.7,
                })

        # Domain-IP correlation
        domain_ip_map: dict[str, set[str]] = {}
        for f in self.findings:
            if f.data_type == "host_mapping" and "->" in f.value:
                parts = f.value.split("->")
                hostname = parts[0].strip()
                ip = parts[1].strip()
                if hostname not in domain_ip_map:
                    domain_ip_map[hostname] = set()
                domain_ip_map[hostname].add(ip)

        # Identify shared infrastructure
        ip_hosts: dict[str, list[str]] = {}
        for hostname, ips in domain_ip_map.items():
            for ip in ips:
                if ip not in ip_hosts:
                    ip_hosts[ip] = []
                ip_hosts[ip].append(hostname)

        for ip, hosts in ip_hosts.items():
            if len(hosts) > 1:
                correlations.append({
                    "type": "shared_infrastructure",
                    "ip": ip,
                    "hosts": hosts,
                    "note": "Multiple domains sharing the same IP may indicate related infrastructure.",
                })

        return {
            "correlations": correlations,
            "total_correlations": len(correlations),
            "multi_source_confirmations": len(
                [c for c in correlations if "confirmed_by" in c]
            ),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_domain(self, target: str) -> str:
        """Extract a domain from the target string."""
        target = target.strip()
        if target.startswith(("http://", "https://")):
            from urllib.parse import urlparse
            parsed = urlparse(target)
            return parsed.hostname or ""
        if "@" in target:
            return target.split("@")[1]
        if "." in target and " " not in target:
            return target.split("/")[0]
        return ""

    def _parse_whois(self, output: str, domain: str) -> None:
        """Parse WHOIS output and create findings."""
        fields = {
            "Registrant Organization": "organization",
            "Registrant Name": "registrant_name",
            "Registrant Email": "registrant_email",
            "Admin Email": "admin_email",
            "Tech Email": "tech_email",
            "Name Server": "nameserver",
            "Creation Date": "created",
            "Updated Date": "updated",
            "Registry Expiry Date": "expires",
        }

        for whois_field, data_type in fields.items():
            match = re.search(rf"{whois_field}:\s*(.+)", output, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                if not value or "REDACTED" in value.upper():
                    continue
                self._organization_info[data_type] = value

                if "email" in data_type:
                    self._emails.add(value.lower())
                    self.findings.append(
                        OSINTFinding(
                            category="whois",
                            source_tool="whois",
                            data_type="email",
                            value=value,
                            context=f"From WHOIS {whois_field} for {domain}",
                        )
                    )
                else:
                    self.findings.append(
                        OSINTFinding(
                            category="whois",
                            source_tool="whois",
                            data_type=data_type,
                            value=value,
                            context=f"WHOIS data for {domain}",
                        )
                    )

    @staticmethod
    def _extract_platform(url: str) -> str:
        """Extract the platform name from a social media URL."""
        platform_patterns = {
            "twitter.com": "Twitter/X",
            "x.com": "Twitter/X",
            "facebook.com": "Facebook",
            "instagram.com": "Instagram",
            "linkedin.com": "LinkedIn",
            "github.com": "GitHub",
            "reddit.com": "Reddit",
            "youtube.com": "YouTube",
            "tiktok.com": "TikTok",
            "pinterest.com": "Pinterest",
            "tumblr.com": "Tumblr",
            "medium.com": "Medium",
            "stackoverflow.com": "StackOverflow",
            "keybase.io": "Keybase",
            "mastodon": "Mastodon",
        }
        url_lower = url.lower()
        for domain, name in platform_patterns.items():
            if domain in url_lower:
                return name
        # Fallback: extract domain name
        match = re.search(r"https?://(?:www\.)?([^/]+)", url_lower)
        return match.group(1) if match else "Unknown"

    def _build_summary(self) -> dict[str, Any]:
        """Compile OSINT summary."""
        return {
            "target_type": self._target_type,
            "total_findings": len(self.findings),
            "emails_found": len(self._emails),
            "usernames_checked": len(self._usernames),
            "social_profiles_found": len(self._social_profiles),
            "domains_discovered": len(self._domains),
            "ips_discovered": len(self._ips),
            "organization_info": self._organization_info,
            "data_types": list({f.data_type for f in self.findings}),
            "source_tools": list({f.source_tool for f in self.findings}),
        }
