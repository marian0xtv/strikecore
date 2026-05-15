"""
ReconAgent - Reconnaissance and information gathering agent.

Performs systematic reconnaissance against targets using DNS enumeration,
subdomain discovery, port scanning, service detection, technology
fingerprinting, and OSINT correlation.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ReconFinding:
    """A single piece of reconnaissance data."""
    category: str
    source_tool: str
    data: dict[str, Any]
    confidence: float = 1.0
    raw_output: str = ""


class ReconAgent:
    """Reconnaissance and information gathering security agent."""

    name: str = "ReconAgent"
    description: str = (
        "Performs comprehensive reconnaissance and information gathering "
        "against a target, including DNS enumeration, subdomain discovery, "
        "port scanning, service detection, technology fingerprinting, and "
        "OSINT correlation."
    )

    tools: list[str] = [
        "nmap",
        "masscan",
        "rustscan",
        "subfinder",
        "amass",
        "httpx",
        "dnsrecon",
        "fierce",
        "whois",
        "dig",
        "theHarvester",
        "shodan",
        "censys",
        "waybackurls",
        "gau",
        "assetfinder",
    ]

    methodology: list[str] = [
        "1. DNS Enumeration - Resolve target, enumerate DNS records (A, AAAA, MX, NS, TXT, SOA, CNAME)",
        "2. Subdomain Discovery - Use subfinder, amass, assetfinder, and certificate transparency logs",
        "3. Port Scanning - Fast scan with rustscan/masscan, detailed scan with nmap",
        "4. Service Detection - Banner grabbing and version detection on open ports",
        "5. Technology Fingerprinting - Identify web technologies, frameworks, and server software",
        "6. OSINT Correlation - Cross-reference findings with Shodan, Censys, and historical data",
    ]

    system_prompt: str = (
        "You are a reconnaissance specialist agent within the StrikeCore security "
        "assessment framework. Your role is to perform thorough, methodical "
        "information gathering against authorized targets.\n\n"
        "RULES:\n"
        "- Only operate against explicitly authorized targets.\n"
        "- Follow the methodology steps in order unless context demands otherwise.\n"
        "- Record every finding with its source tool and confidence level.\n"
        "- Correlate data across tools to reduce false positives.\n"
        "- Prioritize passive recon before active scanning.\n"
        "- Flag anything that looks like a security boundary or out-of-scope asset.\n\n"
        "METHODOLOGY:\n"
        "1. DNS Enumeration\n"
        "2. Subdomain Discovery\n"
        "3. Port Scanning\n"
        "4. Service Detection\n"
        "5. Technology Fingerprinting\n"
        "6. OSINT Correlation\n\n"
        "For each step, select the most appropriate tool(s), execute them, parse "
        "the output, and feed relevant results into subsequent steps."
    )

    def __init__(self) -> None:
        self.findings: list[ReconFinding] = []
        self._subdomains: set[str] = set()
        self._open_ports: dict[str, list[int]] = {}
        self._services: dict[str, dict[int, dict[str, str]]] = {}
        self._technologies: dict[str, list[str]] = {}

    async def run(self, target: str, agent_core: Any) -> dict[str, Any]:
        """
        Execute the full reconnaissance methodology against the target.

        Args:
            target: The target to scan (IP, domain, CIDR, or URL).
            agent_core: The core agent loop handler that provides tool
                        execution and LLM interaction capabilities.

        Returns:
            A dictionary containing all reconnaissance findings organized
            by methodology phase.
        """
        logger.info("ReconAgent starting against target: %s", target)

        context = {
            "agent_name": self.name,
            "system_prompt": self.system_prompt,
            "tools": self.tools,
            "target": target,
            "methodology": self.methodology,
        }

        target_type = self._classify_target(target)
        context["target_type"] = target_type

        results: dict[str, Any] = {
            "target": target,
            "target_type": target_type,
            "phases": {},
            "summary": {},
        }

        # Phase 1: DNS Enumeration
        phase1 = await self._phase_dns_enumeration(target, target_type, agent_core)
        results["phases"]["dns_enumeration"] = phase1

        # Phase 2: Subdomain Discovery
        phase2 = await self._phase_subdomain_discovery(target, target_type, agent_core)
        results["phases"]["subdomain_discovery"] = phase2

        # Phase 3: Port Scanning
        scan_targets = self._build_scan_targets(target)
        phase3 = await self._phase_port_scanning(scan_targets, agent_core)
        results["phases"]["port_scanning"] = phase3

        # Phase 4: Service Detection
        phase4 = await self._phase_service_detection(agent_core)
        results["phases"]["service_detection"] = phase4

        # Phase 5: Technology Fingerprinting
        phase5 = await self._phase_tech_fingerprinting(target, agent_core)
        results["phases"]["technology_fingerprinting"] = phase5

        # Phase 6: OSINT Correlation
        phase6 = await self._phase_osint_correlation(target, agent_core)
        results["phases"]["osint_correlation"] = phase6

        results["summary"] = self._build_summary()
        results["findings"] = [
            {
                "category": f.category,
                "source_tool": f.source_tool,
                "data": f.data,
                "confidence": f.confidence,
            }
            for f in self.findings
        ]

        logger.info(
            "ReconAgent completed. Found %d subdomains, %d hosts with open ports.",
            len(self._subdomains),
            len(self._open_ports),
        )

        return await agent_core.delegate(context, results)

    def _classify_target(self, target: str) -> str:
        """Determine the type of the provided target string."""
        target = target.strip()
        if re.match(r"^https?://", target):
            return "url"
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$", target):
            return "cidr"
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", target):
            return "ip"
        if re.match(r"^[a-fA-F0-9:]+/\d{1,3}$", target):
            return "ipv6_cidr"
        if re.match(r"^[a-fA-F0-9:]+$", target):
            return "ipv6"
        return "domain"

    def _build_scan_targets(self, target: str) -> list[str]:
        """Build the list of IPs/hosts to scan from discovered subdomains and the original target."""
        targets = {target}
        targets.update(self._subdomains)
        return sorted(targets)

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    async def _phase_dns_enumeration(
        self, target: str, target_type: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 1: DNS record enumeration."""
        phase_results: dict[str, Any] = {"tools_used": [], "records": {}}

        if target_type not in ("domain", "url"):
            phase_results["skipped"] = True
            phase_results["reason"] = "Target is not a domain; DNS enum limited."
            # Still attempt reverse DNS for IPs
            if target_type == "ip":
                dig_result = await agent_core.run_tool(
                    "dig", ["-x", target, "+short"]
                )
                phase_results["tools_used"].append("dig")
                phase_results["reverse_dns"] = dig_result.get("output", "").strip()
                self.findings.append(
                    ReconFinding(
                        category="dns",
                        source_tool="dig",
                        data={"reverse_dns": phase_results["reverse_dns"], "target": target},
                    )
                )
            return phase_results

        domain = self._extract_domain(target)

        # Run whois, dig, and dnsrecon concurrently
        whois_task = agent_core.run_tool("whois", [domain])
        dig_task = agent_core.run_tool("dig", [domain, "ANY", "+noall", "+answer"])
        dnsrecon_task = agent_core.run_tool(
            "dnsrecon", ["-d", domain, "-t", "std,brt", "--json"]
        )
        fierce_task = agent_core.run_tool("fierce", ["--domain", domain])

        whois_res, dig_res, dnsrecon_res, fierce_res = await asyncio.gather(
            whois_task, dig_task, dnsrecon_task, fierce_task,
            return_exceptions=True,
        )

        for tool_name, result in [
            ("whois", whois_res),
            ("dig", dig_res),
            ("dnsrecon", dnsrecon_res),
            ("fierce", fierce_res),
        ]:
            phase_results["tools_used"].append(tool_name)
            if isinstance(result, Exception):
                logger.warning("Tool %s failed: %s", tool_name, result)
                continue
            output = result.get("output", "") if isinstance(result, dict) else str(result)
            self.findings.append(
                ReconFinding(
                    category="dns",
                    source_tool=tool_name,
                    data={"domain": domain, "output_summary": output[:2000]},
                    raw_output=output,
                )
            )

        phase_results["domain"] = domain
        return phase_results

    async def _phase_subdomain_discovery(
        self, target: str, target_type: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 2: Subdomain enumeration."""
        phase_results: dict[str, Any] = {"tools_used": [], "subdomains": []}

        if target_type not in ("domain", "url"):
            phase_results["skipped"] = True
            phase_results["reason"] = "Subdomain discovery requires a domain target."
            return phase_results

        domain = self._extract_domain(target)

        subfinder_task = agent_core.run_tool(
            "subfinder", ["-d", domain, "-silent", "-o", "-"]
        )
        amass_task = agent_core.run_tool(
            "amass", ["enum", "-passive", "-d", domain]
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
                logger.warning("Tool %s failed: %s", tool_name, result)
                continue
            output = result.get("output", "") if isinstance(result, dict) else str(result)
            found = {
                line.strip()
                for line in output.splitlines()
                if line.strip() and "." in line.strip()
            }
            self._subdomains.update(found)
            self.findings.append(
                ReconFinding(
                    category="subdomains",
                    source_tool=tool_name,
                    data={"domain": domain, "count": len(found), "subdomains": sorted(found)},
                )
            )

        # Probe live subdomains with httpx
        if self._subdomains:
            subdomain_list = "\n".join(sorted(self._subdomains))
            httpx_result = await agent_core.run_tool(
                "httpx",
                ["-silent", "-status-code", "-title", "-tech-detect"],
                stdin_data=subdomain_list,
            )
            phase_results["tools_used"].append("httpx")
            if not isinstance(httpx_result, Exception):
                output = httpx_result.get("output", "") if isinstance(httpx_result, dict) else str(httpx_result)
                self.findings.append(
                    ReconFinding(
                        category="live_hosts",
                        source_tool="httpx",
                        data={"live_hosts": output.splitlines()},
                    )
                )

        phase_results["subdomains"] = sorted(self._subdomains)
        phase_results["total_unique"] = len(self._subdomains)
        return phase_results

    async def _phase_port_scanning(
        self, targets: list[str], agent_core: Any
    ) -> dict[str, Any]:
        """Phase 3: Port scanning with fast scan followed by detailed scan."""
        phase_results: dict[str, Any] = {"tools_used": [], "open_ports": {}}

        primary_target = targets[0] if targets else None
        if not primary_target:
            phase_results["skipped"] = True
            return phase_results

        # Fast scan with rustscan
        rustscan_result = await agent_core.run_tool(
            "rustscan", ["-a", primary_target, "--ulimit", "5000", "-b", "1500"]
        )
        phase_results["tools_used"].append("rustscan")

        discovered_ports: set[int] = set()
        if not isinstance(rustscan_result, Exception):
            output = rustscan_result.get("output", "") if isinstance(rustscan_result, dict) else str(rustscan_result)
            port_matches = re.findall(r"(\d+)/(?:tcp|udp)\s+open", output)
            if not port_matches:
                port_matches = re.findall(r"Open\s+[\d.]+:(\d+)", output)
            discovered_ports.update(int(p) for p in port_matches)
            self.findings.append(
                ReconFinding(
                    category="ports",
                    source_tool="rustscan",
                    data={"target": primary_target, "ports": sorted(discovered_ports)},
                    raw_output=output,
                )
            )

        # Detailed nmap scan on discovered ports (or common ports fallback)
        port_arg = ",".join(str(p) for p in sorted(discovered_ports)) if discovered_ports else "1-1000"
        nmap_result = await agent_core.run_tool(
            "nmap",
            ["-sC", "-sV", "-O", "-p", port_arg, "--open", "-oN", "-", primary_target],
        )
        phase_results["tools_used"].append("nmap")

        if not isinstance(nmap_result, Exception):
            output = nmap_result.get("output", "") if isinstance(nmap_result, dict) else str(nmap_result)
            nmap_ports = re.findall(r"(\d+)/tcp\s+open\s+(\S+)\s*(.*)", output)
            port_details: dict[int, dict[str, str]] = {}
            for port_str, service, version in nmap_ports:
                port_num = int(port_str)
                discovered_ports.add(port_num)
                port_details[port_num] = {
                    "service": service.strip(),
                    "version": version.strip(),
                }
            self._services[primary_target] = port_details
            self.findings.append(
                ReconFinding(
                    category="ports",
                    source_tool="nmap",
                    data={
                        "target": primary_target,
                        "port_details": {str(k): v for k, v in port_details.items()},
                    },
                    raw_output=output,
                )
            )

        self._open_ports[primary_target] = sorted(discovered_ports)
        phase_results["open_ports"] = {primary_target: sorted(discovered_ports)}

        # Scan additional targets with masscan if there are many
        if len(targets) > 1:
            additional = targets[1:50]  # Cap at 50 additional targets
            target_str = " ".join(additional)
            masscan_result = await agent_core.run_tool(
                "masscan",
                [target_str, "-p", "1-65535", "--rate", "1000", "--open-only"],
            )
            phase_results["tools_used"].append("masscan")
            if not isinstance(masscan_result, Exception):
                output = masscan_result.get("output", "") if isinstance(masscan_result, dict) else str(masscan_result)
                self.findings.append(
                    ReconFinding(
                        category="ports",
                        source_tool="masscan",
                        data={"targets": additional, "output_summary": output[:2000]},
                        raw_output=output,
                    )
                )

        return phase_results

    async def _phase_service_detection(self, agent_core: Any) -> dict[str, Any]:
        """Phase 4: Detailed service and version detection."""
        phase_results: dict[str, Any] = {"tools_used": [], "services": {}}

        for host, ports in self._open_ports.items():
            if not ports:
                continue
            port_arg = ",".join(str(p) for p in ports)
            nmap_svc = await agent_core.run_tool(
                "nmap",
                ["-sV", "--version-intensity", "5", "-p", port_arg, host],
            )
            phase_results["tools_used"].append("nmap")
            if not isinstance(nmap_svc, Exception):
                output = nmap_svc.get("output", "") if isinstance(nmap_svc, dict) else str(nmap_svc)
                self.findings.append(
                    ReconFinding(
                        category="services",
                        source_tool="nmap",
                        data={"host": host, "output_summary": output[:3000]},
                        raw_output=output,
                    )
                )

        phase_results["services"] = {
            host: {str(p): info for p, info in svc.items()}
            for host, svc in self._services.items()
        }
        return phase_results

    async def _phase_tech_fingerprinting(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 5: Technology fingerprinting on web services."""
        phase_results: dict[str, Any] = {"tools_used": [], "technologies": {}}

        # Identify web ports
        web_targets: list[str] = []
        for host, svc_map in self._services.items():
            for port, info in svc_map.items():
                svc_name = info.get("service", "").lower()
                if any(kw in svc_name for kw in ("http", "ssl", "https", "web")):
                    scheme = "https" if "ssl" in svc_name or "https" in svc_name or port == 443 else "http"
                    web_targets.append(f"{scheme}://{host}:{port}")

        # If no web services found from scanning, try the target directly
        if not web_targets:
            target_type = self._classify_target(target)
            if target_type in ("domain", "url"):
                web_targets.append(
                    target if target.startswith("http") else f"https://{target}"
                )

        httpx_targets = "\n".join(web_targets)
        if httpx_targets:
            httpx_res = await agent_core.run_tool(
                "httpx",
                ["-silent", "-tech-detect", "-status-code", "-title", "-server", "-content-type"],
                stdin_data=httpx_targets,
            )
            phase_results["tools_used"].append("httpx")
            if not isinstance(httpx_res, Exception):
                output = httpx_res.get("output", "") if isinstance(httpx_res, dict) else str(httpx_res)
                self.findings.append(
                    ReconFinding(
                        category="technology",
                        source_tool="httpx",
                        data={"web_targets": web_targets, "output": output[:3000]},
                        raw_output=output,
                    )
                )

        # Historical URL discovery with waybackurls and gau
        domain = self._extract_domain(target)
        if domain:
            wayback_task = agent_core.run_tool("waybackurls", [domain])
            gau_task = agent_core.run_tool("gau", [domain, "--threads", "5"])
            wayback_res, gau_res = await asyncio.gather(
                wayback_task, gau_task, return_exceptions=True
            )
            for tool_name, result in [("waybackurls", wayback_res), ("gau", gau_res)]:
                phase_results["tools_used"].append(tool_name)
                if isinstance(result, Exception):
                    continue
                output = result.get("output", "") if isinstance(result, dict) else str(result)
                urls = [u.strip() for u in output.splitlines() if u.strip()]
                self.findings.append(
                    ReconFinding(
                        category="historical_urls",
                        source_tool=tool_name,
                        data={"domain": domain, "url_count": len(urls), "sample": urls[:100]},
                    )
                )

        return phase_results

    async def _phase_osint_correlation(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 6: OSINT correlation through Shodan, Censys, and theHarvester."""
        phase_results: dict[str, Any] = {"tools_used": [], "osint_data": {}}

        domain = self._extract_domain(target)

        # theHarvester
        if domain:
            harvester_res = await agent_core.run_tool(
                "theHarvester",
                ["-d", domain, "-b", "all", "-l", "200"],
            )
            phase_results["tools_used"].append("theHarvester")
            if not isinstance(harvester_res, Exception):
                output = harvester_res.get("output", "") if isinstance(harvester_res, dict) else str(harvester_res)
                emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", output)
                self.findings.append(
                    ReconFinding(
                        category="osint",
                        source_tool="theHarvester",
                        data={"domain": domain, "emails": list(set(emails)), "output_summary": output[:2000]},
                        raw_output=output,
                    )
                )

        # Shodan
        shodan_res = await agent_core.run_tool("shodan", ["host", target])
        phase_results["tools_used"].append("shodan")
        if not isinstance(shodan_res, Exception):
            output = shodan_res.get("output", "") if isinstance(shodan_res, dict) else str(shodan_res)
            self.findings.append(
                ReconFinding(
                    category="osint",
                    source_tool="shodan",
                    data={"target": target, "output_summary": output[:3000]},
                    raw_output=output,
                )
            )

        # Censys
        censys_res = await agent_core.run_tool("censys", ["search", target])
        phase_results["tools_used"].append("censys")
        if not isinstance(censys_res, Exception):
            output = censys_res.get("output", "") if isinstance(censys_res, dict) else str(censys_res)
            self.findings.append(
                ReconFinding(
                    category="osint",
                    source_tool="censys",
                    data={"target": target, "output_summary": output[:3000]},
                    raw_output=output,
                )
            )

        return phase_results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_domain(self, target: str) -> str:
        """Extract a bare domain from a target string (URL, domain, etc.)."""
        target = target.strip()
        if target.startswith("http://") or target.startswith("https://"):
            from urllib.parse import urlparse
            parsed = urlparse(target)
            return parsed.hostname or ""
        if "/" in target:
            return target.split("/")[0]
        return target

    def _build_summary(self) -> dict[str, Any]:
        """Compile a summary of all findings."""
        return {
            "subdomains_found": len(self._subdomains),
            "hosts_scanned": len(self._open_ports),
            "total_open_ports": sum(len(p) for p in self._open_ports.values()),
            "services_identified": sum(len(s) for s in self._services.values()),
            "total_findings": len(self.findings),
            "finding_categories": list({f.category for f in self.findings}),
        }
