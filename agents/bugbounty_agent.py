"""
BugBountyAgent - Bug bounty hunting workflow agent.

Combines reconnaissance and web application testing methodologies with
bug-bounty-specific tactics: scope analysis, asset discovery, subdomain
enumeration, alive checking, content discovery, vulnerability scanning,
and guided manual testing suggestions.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class BountyFinding:
    """A potential bug-bounty-worthy finding."""
    category: str
    severity: str
    source_tool: str
    title: str
    description: str
    url: str = ""
    parameter: str = ""
    evidence: str = ""
    bounty_relevance: str = ""
    remediation: str = ""
    confidence: float = 1.0
    cwe_id: str = ""
    duplicate_risk: str = "unknown"  # low, medium, high


class BugBountyAgent:
    """Bug bounty hunting workflow agent."""

    name: str = "BugBountyAgent"
    description: str = (
        "Executes a complete bug bounty hunting workflow combining "
        "reconnaissance and web application testing with bounty-specific "
        "techniques including scope analysis, gf pattern matching, custom "
        "nuclei templates, and targeted vulnerability scanning."
    )

    # Combined recon + webapp tools plus bounty-specific additions
    tools: list[str] = [
        # Recon tools
        "nmap", "masscan", "rustscan", "subfinder", "amass", "httpx",
        "dnsrecon", "fierce", "whois", "dig", "theHarvester", "shodan",
        "censys", "waybackurls", "gau", "assetfinder",
        # Web app tools
        "nuclei", "nikto", "gobuster", "ffuf", "feroxbuster", "sqlmap",
        "xsstrike", "dalfox", "commix", "whatweb", "wappalyzer", "testssl",
        "arjun", "paramspider", "wfuzz", "dirsearch", "burpsuite", "zaproxy",
        # Bug bounty extras
        "gf", "qsreplace", "anew", "unfurl", "freq", "hakrawler",
        "gospider", "katana",
    ]

    methodology: list[str] = [
        "1. Scope Analysis - Parse program scope, identify in-scope assets and exclusions",
        "2. Asset Discovery - Enumerate all assets belonging to the target organization",
        "3. Subdomain Enumeration - Comprehensive subdomain discovery using multiple sources",
        "4. Alive Checking - Probe discovered hosts for live web services",
        "5. Content Discovery - Directory bruteforce, JS file analysis, endpoint mapping",
        "6. Vulnerability Scanning - Automated scanning with nuclei templates and gf patterns",
        "7. Manual Testing Suggestions - Generate prioritized list of manual testing targets",
    ]

    system_prompt: str = (
        "You are a bug bounty hunting specialist within the StrikeCore framework. "
        "Your role is to systematically discover vulnerabilities in bug bounty "
        "programs while maximizing impact and minimizing duplicate risk.\n\n"
        "RULES:\n"
        "- Strictly respect program scope boundaries.\n"
        "- Prioritize high-impact, low-duplicate-risk findings.\n"
        "- Focus on business logic flaws and chained vulnerabilities.\n"
        "- Document complete reproduction steps for every finding.\n"
        "- Avoid noisy scanning that could trigger WAF blocks.\n"
        "- Track which assets are likely well-tested vs under-explored.\n\n"
        "STRATEGY:\n"
        "- Wider recon scope leads to less-explored attack surface.\n"
        "- Chain low-severity bugs into high-impact scenarios.\n"
        "- Focus on newer features and recently acquired assets.\n"
        "- Look for IDOR, access control, and business logic issues.\n"
        "- Check for misconfigurations in cloud assets and APIs.\n\n"
        "METHODOLOGY:\n"
        "1. Scope Analysis\n"
        "2. Asset Discovery\n"
        "3. Subdomain Enumeration\n"
        "4. Alive Checking\n"
        "5. Content Discovery\n"
        "6. Vulnerability Scanning\n"
        "7. Manual Testing Suggestions"
    )

    # gf pattern categories for targeted grep
    GF_PATTERNS: list[str] = [
        "xss", "sqli", "ssrf", "redirect", "rce", "idor",
        "lfi", "ssti", "debug_logic", "cors", "base64",
        "aws-keys", "s3-buckets", "firebase", "json-sec",
    ]

    NUCLEI_TEMPLATE_SETS: list[str] = [
        "http/cves/",
        "http/vulnerabilities/",
        "http/misconfiguration/",
        "http/exposures/",
        "http/default-logins/",
        "http/takeovers/",
        "http/token-spray/",
        "dns/",
    ]

    def __init__(self) -> None:
        self.findings: list[BountyFinding] = []
        self._scope: dict[str, Any] = {"in_scope": [], "out_of_scope": []}
        self._assets: set[str] = set()
        self._subdomains: set[str] = set()
        self._live_hosts: list[dict[str, Any]] = []
        self._urls_collected: set[str] = set()
        self._js_files: set[str] = set()
        self._parameters: dict[str, list[str]] = {}

    async def run(self, target: str, agent_core: Any) -> dict[str, Any]:
        """
        Execute the full bug bounty hunting workflow.

        Args:
            target: The target domain or program scope definition.
            agent_core: The core agent loop handler.

        Returns:
            Dictionary with all findings and manual testing suggestions.
        """
        logger.info("BugBountyAgent starting against target: %s", target)

        context = {
            "agent_name": self.name,
            "system_prompt": self.system_prompt,
            "tools": self.tools,
            "target": target,
            "methodology": self.methodology,
        }

        results: dict[str, Any] = {
            "target": target,
            "phases": {},
            "summary": {},
        }

        # Phase 1: Scope Analysis
        results["phases"]["scope_analysis"] = await self._phase_scope_analysis(target, agent_core)

        # Phase 2: Asset Discovery
        results["phases"]["asset_discovery"] = await self._phase_asset_discovery(target, agent_core)

        # Phase 3: Subdomain Enumeration
        results["phases"]["subdomain_enum"] = await self._phase_subdomain_enum(target, agent_core)

        # Phase 4: Alive Checking
        results["phases"]["alive_checking"] = await self._phase_alive_checking(agent_core)

        # Phase 5: Content Discovery
        results["phases"]["content_discovery"] = await self._phase_content_discovery(agent_core)

        # Phase 6: Vulnerability Scanning
        results["phases"]["vuln_scanning"] = await self._phase_vuln_scanning(target, agent_core)

        # Phase 7: Manual Testing Suggestions
        results["phases"]["manual_suggestions"] = self._generate_manual_suggestions()

        results["summary"] = self._build_summary()
        results["findings"] = [
            {
                "category": f.category,
                "severity": f.severity,
                "source_tool": f.source_tool,
                "title": f.title,
                "description": f.description,
                "url": f.url,
                "parameter": f.parameter,
                "evidence": f.evidence,
                "bounty_relevance": f.bounty_relevance,
                "duplicate_risk": f.duplicate_risk,
                "cwe_id": f.cwe_id,
            }
            for f in self.findings
        ]

        logger.info(
            "BugBountyAgent completed. %d findings, %d manual test suggestions.",
            len(self.findings),
            len(results["phases"]["manual_suggestions"].get("suggestions", [])),
        )

        return await agent_core.delegate(context, results)

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    async def _phase_scope_analysis(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 1: Analyze the bug bounty program scope."""
        phase_results: dict[str, Any] = {"tools_used": [], "scope": {}}

        domain = self._extract_root_domain(target)
        self._scope["in_scope"].append(f"*.{domain}")
        self._assets.add(domain)

        # Whois to understand the organization
        whois_result = await agent_core.run_tool("whois", [domain])
        phase_results["tools_used"].append("whois")

        if not isinstance(whois_result, Exception):
            output = whois_result.get("output", "") if isinstance(whois_result, dict) else str(whois_result)
            # Extract organization info for related asset discovery
            org_match = re.search(r"(?:Org(?:anization)?[:\s]+)(.+)", output, re.IGNORECASE)
            if org_match:
                self._scope["organization"] = org_match.group(1).strip()

            # Extract ASN for netblock discovery
            asn_matches = re.findall(r"AS\d+", output)
            if asn_matches:
                self._scope["asns"] = list(set(asn_matches))

        # DNS enumeration for related domains
        dig_result = await agent_core.run_tool("dig", [domain, "ANY", "+short"])
        phase_results["tools_used"].append("dig")

        phase_results["scope"] = self._scope
        phase_results["root_domain"] = domain
        return phase_results

    async def _phase_asset_discovery(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 2: Discover all organizational assets."""
        phase_results: dict[str, Any] = {"tools_used": [], "assets": []}

        domain = self._extract_root_domain(target)

        # Use multiple tools for asset discovery
        assetfinder_task = agent_core.run_tool("assetfinder", [domain])
        shodan_task = agent_core.run_tool("shodan", ["search", f"org:{domain}"])
        censys_task = agent_core.run_tool("censys", ["search", domain])
        theharvester_task = agent_core.run_tool(
            "theHarvester", ["-d", domain, "-b", "all", "-l", "500"]
        )

        results = await asyncio.gather(
            assetfinder_task, shodan_task, censys_task, theharvester_task,
            return_exceptions=True,
        )

        tool_names = ["assetfinder", "shodan", "censys", "theHarvester"]
        for tool_name, result in zip(tool_names, results):
            phase_results["tools_used"].append(tool_name)
            if isinstance(result, Exception):
                logger.warning("Tool %s failed: %s", tool_name, result)
                continue
            output = result.get("output", "") if isinstance(result, dict) else str(result)
            # Extract domains and IPs
            domains = re.findall(r"(?:[\w-]+\.)+[\w-]+", output)
            ips = re.findall(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", output)
            for d in domains:
                if domain in d:
                    self._assets.add(d)
            for ip in ips:
                self._assets.add(ip)

        phase_results["assets"] = sorted(self._assets)
        phase_results["total"] = len(self._assets)
        return phase_results

    async def _phase_subdomain_enum(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 3: Comprehensive subdomain enumeration."""
        phase_results: dict[str, Any] = {"tools_used": [], "subdomains": []}

        domain = self._extract_root_domain(target)

        subfinder_task = agent_core.run_tool(
            "subfinder", ["-d", domain, "-all", "-silent"]
        )
        amass_task = agent_core.run_tool(
            "amass", ["enum", "-passive", "-d", domain, "-timeout", "15"]
        )
        assetfinder_task = agent_core.run_tool(
            "assetfinder", ["--subs-only", domain]
        )

        results = await asyncio.gather(
            subfinder_task, amass_task, assetfinder_task,
            return_exceptions=True,
        )

        tool_names = ["subfinder", "amass", "assetfinder"]
        for tool_name, result in zip(tool_names, results):
            phase_results["tools_used"].append(tool_name)
            if isinstance(result, Exception):
                continue
            output = result.get("output", "") if isinstance(result, dict) else str(result)
            for line in output.splitlines():
                sub = line.strip()
                if sub and "." in sub and domain in sub:
                    self._subdomains.add(sub)

        phase_results["subdomains"] = sorted(self._subdomains)
        phase_results["total"] = len(self._subdomains)
        return phase_results

    async def _phase_alive_checking(self, agent_core: Any) -> dict[str, Any]:
        """Phase 4: Probe discovered hosts for live HTTP services."""
        phase_results: dict[str, Any] = {"tools_used": [], "live_hosts": []}

        if not self._subdomains:
            phase_results["skipped"] = True
            return phase_results

        subdomain_list = "\n".join(sorted(self._subdomains))

        httpx_result = await agent_core.run_tool(
            "httpx",
            [
                "-silent",
                "-status-code",
                "-title",
                "-tech-detect",
                "-content-length",
                "-follow-redirects",
                "-threads", "50",
            ],
            stdin_data=subdomain_list,
        )
        phase_results["tools_used"].append("httpx")

        if not isinstance(httpx_result, Exception):
            output = httpx_result.get("output", "") if isinstance(httpx_result, dict) else str(httpx_result)
            for line in output.splitlines():
                line = line.strip()
                if not line:
                    continue
                # Parse httpx output: url [status] [title] [tech]
                url_match = re.match(r"(https?://\S+)", line)
                if url_match:
                    host_info: dict[str, Any] = {
                        "url": url_match.group(1),
                        "raw": line,
                    }
                    status_match = re.search(r"\[(\d{3})\]", line)
                    if status_match:
                        host_info["status"] = int(status_match.group(1))
                    self._live_hosts.append(host_info)

        phase_results["live_hosts"] = self._live_hosts
        phase_results["total_live"] = len(self._live_hosts)
        return phase_results

    async def _phase_content_discovery(self, agent_core: Any) -> dict[str, Any]:
        """Phase 5: Content discovery via crawling, URL collection, and JS analysis."""
        phase_results: dict[str, Any] = {"tools_used": [], "urls_collected": 0, "js_files": 0}

        live_urls = [h["url"] for h in self._live_hosts[:30]]

        if not live_urls:
            phase_results["skipped"] = True
            return phase_results

        # Crawl with katana and gospider, collect historical URLs
        tasks = []
        task_names = []

        for url in live_urls[:5]:
            tasks.append(
                agent_core.run_tool("katana", ["-u", url, "-d", "3", "-silent", "-jc"])
            )
            task_names.append("katana")
            tasks.append(
                agent_core.run_tool("gospider", ["-s", url, "-d", "2", "-c", "10", "--quiet"])
            )
            task_names.append("gospider")

        # Historical URLs
        for url in live_urls[:5]:
            parsed = urlparse(url)
            domain = parsed.hostname or ""
            tasks.append(agent_core.run_tool("waybackurls", [domain]))
            task_names.append("waybackurls")
            tasks.append(agent_core.run_tool("gau", [domain, "--threads", "5"]))
            task_names.append("gau")

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for tool_name, result in zip(task_names, results):
            if tool_name not in phase_results["tools_used"]:
                phase_results["tools_used"].append(tool_name)
            if isinstance(result, Exception):
                continue
            output = result.get("output", "") if isinstance(result, dict) else str(result)
            for line in output.splitlines():
                url_candidate = line.strip()
                if url_candidate.startswith("http"):
                    self._urls_collected.add(url_candidate)
                    if re.search(r"\.js(\?|$)", url_candidate):
                        self._js_files.add(url_candidate)

        # Apply gf patterns to collected URLs for interesting parameters
        if self._urls_collected:
            url_text = "\n".join(sorted(self._urls_collected))
            for pattern in self.GF_PATTERNS:
                gf_result = await agent_core.run_tool(
                    "gf", [pattern], stdin_data=url_text
                )
                if not isinstance(gf_result, Exception):
                    output = gf_result.get("output", "") if isinstance(gf_result, dict) else str(gf_result)
                    matched_urls = [u.strip() for u in output.splitlines() if u.strip()]
                    if matched_urls:
                        self.findings.append(
                            BountyFinding(
                                category="pattern_match",
                                severity="medium" if pattern in ("sqli", "rce", "ssrf", "ssti") else "low",
                                source_tool="gf",
                                title=f"GF pattern match: {pattern} ({len(matched_urls)} URLs)",
                                description=f"Found {len(matched_urls)} URLs matching the '{pattern}' pattern.",
                                evidence="\n".join(matched_urls[:10]),
                                bounty_relevance=f"URLs matching '{pattern}' pattern are candidates for {pattern.upper()} testing.",
                                duplicate_risk="medium",
                            )
                        )

        phase_results["urls_collected"] = len(self._urls_collected)
        phase_results["js_files"] = len(self._js_files)
        return phase_results

    async def _phase_vuln_scanning(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 6: Automated vulnerability scanning."""
        phase_results: dict[str, Any] = {"tools_used": [], "vulnerabilities": []}

        live_urls = [h["url"] for h in self._live_hosts]
        if not live_urls:
            phase_results["skipped"] = True
            return phase_results

        targets_text = "\n".join(live_urls[:50])

        # Nuclei scan with multiple template sets
        template_args: list[str] = []
        for ts in self.NUCLEI_TEMPLATE_SETS:
            template_args.extend(["-t", ts])

        nuclei_result = await agent_core.run_tool(
            "nuclei",
            template_args + [
                "-severity", "critical,high,medium",
                "-silent",
                "-no-color",
                "-rate-limit", "100",
                "-bulk-size", "50",
                "-concurrency", "25",
            ],
            stdin_data=targets_text,
        )
        phase_results["tools_used"].append("nuclei")

        if not isinstance(nuclei_result, Exception):
            output = nuclei_result.get("output", "") if isinstance(nuclei_result, dict) else str(nuclei_result)
            for line in output.splitlines():
                line = line.strip()
                if not line:
                    continue
                match = re.match(r"\[([^\]]+)\]\s*\[([^\]]+)\]\s*\[([^\]]+)\]\s*(.*)", line)
                if match:
                    template_id, protocol, severity_raw, found_url = (
                        match.group(1), match.group(2),
                        match.group(3).lower(), match.group(4).strip(),
                    )
                    severity_map = {"critical": "critical", "high": "high", "medium": "medium", "low": "low"}
                    severity = severity_map.get(severity_raw, "info")
                    self.findings.append(
                        BountyFinding(
                            category="vulnerability",
                            severity=severity,
                            source_tool="nuclei",
                            title=f"Nuclei: {template_id}",
                            description=f"Detected by template {template_id} via {protocol}",
                            url=found_url,
                            bounty_relevance=f"Severity: {severity}. Check program policy for bounty eligibility.",
                            duplicate_risk="high" if severity in ("critical", "high") else "medium",
                        )
                    )

        # Subdomain takeover check
        if self._subdomains:
            sub_text = "\n".join(sorted(self._subdomains))
            takeover_result = await agent_core.run_tool(
                "nuclei",
                ["-t", "http/takeovers/", "-silent", "-no-color"],
                stdin_data=sub_text,
            )
            phase_results["tools_used"].append("nuclei")
            if not isinstance(takeover_result, Exception):
                output = takeover_result.get("output", "") if isinstance(takeover_result, dict) else str(takeover_result)
                for line in output.splitlines():
                    if line.strip():
                        self.findings.append(
                            BountyFinding(
                                category="subdomain_takeover",
                                severity="high",
                                source_tool="nuclei",
                                title=f"Potential Subdomain Takeover: {line.strip()[:80]}",
                                description=line.strip(),
                                bounty_relevance="Subdomain takeovers are typically high-severity bounty-eligible findings.",
                                duplicate_risk="low",
                                cwe_id="CWE-284",
                            )
                        )

        phase_results["vulnerabilities"] = [f.title for f in self.findings if f.category == "vulnerability"]
        return phase_results

    def _generate_manual_suggestions(self) -> dict[str, Any]:
        """Phase 7: Generate prioritized manual testing suggestions."""
        suggestions: list[dict[str, Any]] = []

        # Suggest IDOR testing on API endpoints
        api_urls = [u for u in self._urls_collected if "/api/" in u or "/v1/" in u or "/v2/" in u]
        if api_urls:
            suggestions.append({
                "priority": "high",
                "category": "IDOR / Access Control",
                "description": "Test API endpoints for Insecure Direct Object References.",
                "targets": sorted(api_urls)[:20],
                "technique": "Swap user IDs, object IDs, and UUIDs between accounts. Test horizontal and vertical privilege escalation.",
            })

        # Suggest business logic testing on authenticated endpoints
        auth_urls = [u for u in self._urls_collected if any(kw in u.lower() for kw in ("account", "profile", "settings", "admin", "dashboard", "payment", "order"))]
        if auth_urls:
            suggestions.append({
                "priority": "high",
                "category": "Business Logic",
                "description": "Test business logic flows for bypasses.",
                "targets": sorted(auth_urls)[:20],
                "technique": "Test race conditions, parameter tampering, workflow bypasses, and price manipulation.",
            })

        # Suggest JS file analysis
        if self._js_files:
            suggestions.append({
                "priority": "medium",
                "category": "JavaScript Analysis",
                "description": "Analyze JavaScript files for sensitive data and hidden endpoints.",
                "targets": sorted(self._js_files)[:30],
                "technique": "Look for API keys, secrets, internal endpoints, debug functions, and hardcoded credentials.",
            })

        # Suggest SSRF testing on URL-accepting parameters
        ssrf_candidates = [u for u in self._urls_collected if any(p in u.lower() for p in ("url=", "redirect=", "next=", "dest=", "link=", "src=", "page=", "callback="))]
        if ssrf_candidates:
            suggestions.append({
                "priority": "high",
                "category": "SSRF",
                "description": "Test URL parameters for Server-Side Request Forgery.",
                "targets": sorted(ssrf_candidates)[:15],
                "technique": "Use collaborator/webhook.site payloads. Test internal IP ranges, cloud metadata endpoints (169.254.169.254).",
            })

        # Suggest CORS testing
        live_urls = [h["url"] for h in self._live_hosts]
        if live_urls:
            suggestions.append({
                "priority": "medium",
                "category": "CORS Misconfiguration",
                "description": "Test for permissive CORS policies.",
                "targets": live_urls[:20],
                "technique": "Send requests with Origin headers from attacker domains. Check for reflected origins and credentials allowed.",
            })

        # Always suggest cache poisoning
        if live_urls:
            suggestions.append({
                "priority": "medium",
                "category": "Web Cache Poisoning",
                "description": "Test for web cache poisoning vulnerabilities.",
                "targets": live_urls[:10],
                "technique": "Inject unkeyed headers (X-Forwarded-Host, X-Original-URL) and check if responses are cached.",
            })

        return {
            "suggestions": suggestions,
            "total_suggestions": len(suggestions),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_root_domain(self, target: str) -> str:
        """Extract the root domain from a target string."""
        target = target.strip()
        if target.startswith(("http://", "https://")):
            parsed = urlparse(target)
            hostname = parsed.hostname or ""
        else:
            hostname = target.split("/")[0]
        # Extract root domain (last two parts)
        parts = hostname.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return hostname

    def _build_summary(self) -> dict[str, Any]:
        """Compile a summary of the bug bounty workflow."""
        severity_counts: dict[str, int] = {}
        for f in self.findings:
            severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1

        return {
            "total_findings": len(self.findings),
            "severity_counts": severity_counts,
            "assets_discovered": len(self._assets),
            "subdomains_found": len(self._subdomains),
            "live_hosts": len(self._live_hosts),
            "urls_collected": len(self._urls_collected),
            "js_files_found": len(self._js_files),
            "categories": list({f.category for f in self.findings}),
            "high_value_findings": [
                f.title for f in self.findings
                if f.severity in ("critical", "high") and f.duplicate_risk != "high"
            ],
        }
