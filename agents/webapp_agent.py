"""
WebAppAgent - Web application security testing agent.

Performs comprehensive web application security assessments including
technology identification, directory bruteforcing, parameter discovery,
injection testing, XSS detection, authentication testing, and API testing.
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
class WebAppFinding:
    """A single web application security finding."""
    category: str
    severity: str  # critical, high, medium, low, info
    source_tool: str
    title: str
    description: str
    url: str = ""
    parameter: str = ""
    evidence: str = ""
    remediation: str = ""
    confidence: float = 1.0
    cwe_id: str = ""


class WebAppAgent:
    """Web application security testing agent."""

    name: str = "WebAppAgent"
    description: str = (
        "Performs comprehensive web application security testing including "
        "technology stack identification, directory and file enumeration, "
        "parameter discovery, SQL injection, XSS, command injection, "
        "authentication bypass, and API security testing."
    )

    tools: list[str] = [
        "nuclei",
        "nikto",
        "gobuster",
        "ffuf",
        "feroxbuster",
        "sqlmap",
        "xsstrike",
        "dalfox",
        "commix",
        "whatweb",
        "wappalyzer",
        "testssl",
        "arjun",
        "paramspider",
        "wfuzz",
        "dirsearch",
        "burpsuite",
        "zaproxy",
    ]

    methodology: list[str] = [
        "1. Technology Stack Identification - Fingerprint web server, frameworks, CMS, and libraries",
        "2. Directory Bruteforce - Discover hidden directories, files, and endpoints",
        "3. Parameter Discovery - Find hidden and undocumented parameters",
        "4. Injection Testing - Test for SQL injection, NoSQL injection, LDAP injection, etc.",
        "5. XSS Testing - Test for reflected, stored, and DOM-based cross-site scripting",
        "6. Authentication Testing - Test login mechanisms, session management, and access controls",
        "7. API Testing - Discover and test API endpoints for vulnerabilities",
    ]

    system_prompt: str = (
        "You are a web application security testing specialist within the StrikeCore "
        "framework. Your role is to systematically identify vulnerabilities in web "
        "applications through automated and guided testing.\n\n"
        "RULES:\n"
        "- Only test explicitly authorized targets and scopes.\n"
        "- Begin with passive fingerprinting before active fuzzing.\n"
        "- Avoid destructive payloads unless explicitly approved.\n"
        "- Validate findings to minimize false positives.\n"
        "- Track every discovered endpoint and parameter.\n"
        "- Respect rate limits and avoid causing denial of service.\n\n"
        "METHODOLOGY:\n"
        "1. Technology Stack Identification\n"
        "2. Directory Bruteforce\n"
        "3. Parameter Discovery\n"
        "4. Injection Testing\n"
        "5. XSS Testing\n"
        "6. Authentication Testing\n"
        "7. API Testing\n\n"
        "Prioritize findings by severity. Provide clear reproduction steps for "
        "each confirmed vulnerability."
    )

    # Common wordlists for directory bruteforcing
    WORDLISTS: dict[str, str] = {
        "directories": "/usr/share/wordlists/dirb/common.txt",
        "files": "/usr/share/wordlists/dirb/extensions_common.txt",
        "api": "/usr/share/wordlists/seclists/Discovery/Web-Content/api/api-endpoints.txt",
        "parameters": "/usr/share/wordlists/seclists/Discovery/Web-Content/burp-parameter-names.txt",
        "big": "/usr/share/wordlists/seclists/Discovery/Web-Content/big.txt",
    }

    def __init__(self) -> None:
        self.findings: list[WebAppFinding] = []
        self._tech_stack: dict[str, Any] = {}
        self._discovered_urls: set[str] = set()
        self._discovered_params: dict[str, list[str]] = {}
        self._endpoints: set[str] = set()

    async def run(self, target: str, agent_core: Any) -> dict[str, Any]:
        """
        Execute the full web application testing methodology.

        Args:
            target: The target URL to test.
            agent_core: The core agent loop handler.

        Returns:
            Dictionary containing all findings organized by phase.
        """
        logger.info("WebAppAgent starting against target: %s", target)

        target_url = self._normalize_url(target)
        context = {
            "agent_name": self.name,
            "system_prompt": self.system_prompt,
            "tools": self.tools,
            "target": target_url,
            "methodology": self.methodology,
        }

        results: dict[str, Any] = {
            "target": target_url,
            "phases": {},
            "summary": {},
        }

        # Phase 1: Tech Stack Identification
        results["phases"]["tech_stack"] = await self._phase_tech_stack(target_url, agent_core)

        # Phase 2: Directory Bruteforce
        results["phases"]["directory_bruteforce"] = await self._phase_directory_bruteforce(
            target_url, agent_core
        )

        # Phase 3: Parameter Discovery
        results["phases"]["parameter_discovery"] = await self._phase_parameter_discovery(
            target_url, agent_core
        )

        # Phase 4: Injection Testing
        results["phases"]["injection_testing"] = await self._phase_injection_testing(
            target_url, agent_core
        )

        # Phase 5: XSS Testing
        results["phases"]["xss_testing"] = await self._phase_xss_testing(target_url, agent_core)

        # Phase 6: Authentication Testing
        results["phases"]["auth_testing"] = await self._phase_auth_testing(target_url, agent_core)

        # Phase 7: API Testing
        results["phases"]["api_testing"] = await self._phase_api_testing(target_url, agent_core)

        # TLS testing if HTTPS
        if target_url.startswith("https://"):
            results["phases"]["tls_testing"] = await self._phase_tls_testing(target_url, agent_core)

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
                "remediation": f.remediation,
                "cwe_id": f.cwe_id,
            }
            for f in self.findings
        ]

        logger.info(
            "WebAppAgent completed. %d findings across %d severity levels.",
            len(self.findings),
            len({f.severity for f in self.findings}),
        )

        return await agent_core.delegate(context, results)

    def _normalize_url(self, target: str) -> str:
        """Ensure the target is a proper URL."""
        target = target.strip()
        if not target.startswith(("http://", "https://")):
            target = f"https://{target}"
        return target.rstrip("/")

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    async def _phase_tech_stack(
        self, target_url: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 1: Technology stack identification."""
        phase_results: dict[str, Any] = {"tools_used": [], "technologies": {}}

        whatweb_task = agent_core.run_tool("whatweb", ["-a", "3", "-v", target_url])
        wappalyzer_task = agent_core.run_tool("wappalyzer", [target_url])
        nikto_task = agent_core.run_tool(
            "nikto", ["-h", target_url, "-Tuning", "b", "-maxtime", "120"]
        )

        results = await asyncio.gather(
            whatweb_task, wappalyzer_task, nikto_task,
            return_exceptions=True,
        )

        tool_names = ["whatweb", "wappalyzer", "nikto"]
        for tool_name, result in zip(tool_names, results):
            phase_results["tools_used"].append(tool_name)
            if isinstance(result, Exception):
                logger.warning("Tool %s failed: %s", tool_name, result)
                continue
            output = result.get("output", "") if isinstance(result, dict) else str(result)

            if tool_name == "whatweb":
                self._parse_whatweb(output, target_url)
            elif tool_name == "nikto":
                self._parse_nikto(output, target_url)

            self.findings.append(
                WebAppFinding(
                    category="technology",
                    severity="info",
                    source_tool=tool_name,
                    title=f"Technology fingerprint from {tool_name}",
                    description=output[:2000],
                    url=target_url,
                )
            )

        phase_results["technologies"] = self._tech_stack
        return phase_results

    async def _phase_directory_bruteforce(
        self, target_url: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 2: Directory and file enumeration."""
        phase_results: dict[str, Any] = {"tools_used": [], "discovered": []}

        # Run gobuster and feroxbuster concurrently
        gobuster_task = agent_core.run_tool(
            "gobuster",
            [
                "dir",
                "-u", target_url,
                "-w", self.WORDLISTS["directories"],
                "-t", "50",
                "-x", "php,asp,aspx,jsp,html,js,json,xml,txt,bak,old",
                "--no-error",
                "-q",
            ],
        )
        feroxbuster_task = agent_core.run_tool(
            "feroxbuster",
            [
                "-u", target_url,
                "-w", self.WORDLISTS["big"],
                "-t", "50",
                "-x", "php,asp,aspx,jsp,html,js",
                "--quiet",
                "--no-recursion",
                "--auto-tune",
            ],
        )
        dirsearch_task = agent_core.run_tool(
            "dirsearch",
            [
                "-u", target_url,
                "-e", "php,asp,aspx,jsp,html,js,json,xml",
                "-t", "50",
                "--format", "plain",
                "-q",
            ],
        )

        results = await asyncio.gather(
            gobuster_task, feroxbuster_task, dirsearch_task,
            return_exceptions=True,
        )

        tool_names = ["gobuster", "feroxbuster", "dirsearch"]
        for tool_name, result in zip(tool_names, results):
            phase_results["tools_used"].append(tool_name)
            if isinstance(result, Exception):
                logger.warning("Tool %s failed: %s", tool_name, result)
                continue
            output = result.get("output", "") if isinstance(result, dict) else str(result)
            urls = self._extract_urls_from_bruteforce(output, target_url)
            self._discovered_urls.update(urls)
            self._endpoints.update(urls)

        phase_results["discovered"] = sorted(self._discovered_urls)
        phase_results["total"] = len(self._discovered_urls)

        for url in self._discovered_urls:
            self.findings.append(
                WebAppFinding(
                    category="content_discovery",
                    severity="info",
                    source_tool="directory_bruteforce",
                    title=f"Discovered endpoint: {url}",
                    description=f"Endpoint found during directory enumeration.",
                    url=url,
                )
            )

        return phase_results

    async def _phase_parameter_discovery(
        self, target_url: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 3: Hidden parameter discovery."""
        phase_results: dict[str, Any] = {"tools_used": [], "parameters": {}}

        parsed = urlparse(target_url)
        domain = parsed.hostname or ""

        # Run arjun and paramspider concurrently
        arjun_task = agent_core.run_tool(
            "arjun", ["-u", target_url, "-t", "10", "--stable"]
        )
        paramspider_task = agent_core.run_tool(
            "paramspider", ["-d", domain, "--level", "high", "--quiet"]
        )

        results = await asyncio.gather(
            arjun_task, paramspider_task, return_exceptions=True
        )

        tool_names = ["arjun", "paramspider"]
        for tool_name, result in zip(tool_names, results):
            phase_results["tools_used"].append(tool_name)
            if isinstance(result, Exception):
                logger.warning("Tool %s failed: %s", tool_name, result)
                continue
            output = result.get("output", "") if isinstance(result, dict) else str(result)
            params = self._extract_parameters(output)
            if params:
                self._discovered_params[target_url] = list(
                    set(self._discovered_params.get(target_url, []) + params)
                )

        # Test additional discovered endpoints with arjun
        for endpoint in list(self._endpoints)[:20]:
            if endpoint == target_url:
                continue
            arjun_ep = await agent_core.run_tool(
                "arjun", ["-u", endpoint, "-t", "5", "--stable"]
            )
            if not isinstance(arjun_ep, Exception):
                output = arjun_ep.get("output", "") if isinstance(arjun_ep, dict) else str(arjun_ep)
                params = self._extract_parameters(output)
                if params:
                    self._discovered_params[endpoint] = params

        phase_results["parameters"] = self._discovered_params
        return phase_results

    async def _phase_injection_testing(
        self, target_url: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 4: SQL injection and command injection testing."""
        phase_results: dict[str, Any] = {"tools_used": [], "vulnerabilities": []}

        # Build targets with discovered parameters
        sqli_targets = self._build_injection_targets(target_url)

        # SQL injection with sqlmap
        for sqli_target in sqli_targets[:10]:
            sqlmap_result = await agent_core.run_tool(
                "sqlmap",
                [
                    "-u", sqli_target,
                    "--batch",
                    "--level", "3",
                    "--risk", "2",
                    "--threads", "5",
                    "--random-agent",
                    "--tamper", "space2comment",
                    "--timeout", "30",
                ],
            )
            phase_results["tools_used"].append("sqlmap")
            if not isinstance(sqlmap_result, Exception):
                output = sqlmap_result.get("output", "") if isinstance(sqlmap_result, dict) else str(sqlmap_result)
                if self._sqlmap_found_vuln(output):
                    finding = WebAppFinding(
                        category="injection",
                        severity="critical",
                        source_tool="sqlmap",
                        title="SQL Injection Detected",
                        description=f"SQL injection vulnerability found at {sqli_target}",
                        url=sqli_target,
                        evidence=output[:1000],
                        remediation="Use parameterized queries / prepared statements. Implement input validation.",
                        cwe_id="CWE-89",
                    )
                    self.findings.append(finding)
                    phase_results["vulnerabilities"].append(finding.title)

        # Command injection with commix
        for sqli_target in sqli_targets[:5]:
            commix_result = await agent_core.run_tool(
                "commix",
                ["--url", sqli_target, "--batch", "--level", "3"],
            )
            phase_results["tools_used"].append("commix")
            if not isinstance(commix_result, Exception):
                output = commix_result.get("output", "") if isinstance(commix_result, dict) else str(commix_result)
                if "is injectable" in output.lower() or "command injection" in output.lower():
                    finding = WebAppFinding(
                        category="injection",
                        severity="critical",
                        source_tool="commix",
                        title="OS Command Injection Detected",
                        description=f"Command injection vulnerability found at {sqli_target}",
                        url=sqli_target,
                        evidence=output[:1000],
                        remediation="Avoid passing user input to system commands. Use allowlists for valid input.",
                        cwe_id="CWE-78",
                    )
                    self.findings.append(finding)
                    phase_results["vulnerabilities"].append(finding.title)

        return phase_results

    async def _phase_xss_testing(
        self, target_url: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 5: Cross-site scripting testing."""
        phase_results: dict[str, Any] = {"tools_used": [], "vulnerabilities": []}

        xss_targets = self._build_injection_targets(target_url)

        # Run xsstrike and dalfox concurrently on targets
        for xss_target in xss_targets[:10]:
            xsstrike_task = agent_core.run_tool(
                "xsstrike",
                ["--url", xss_target, "--crawl", "--blind"],
            )
            dalfox_task = agent_core.run_tool(
                "dalfox",
                ["url", xss_target, "--silence", "--no-color", "--skip-bav"],
            )

            results = await asyncio.gather(
                xsstrike_task, dalfox_task, return_exceptions=True
            )

            for tool_name, result in zip(["xsstrike", "dalfox"], results):
                phase_results["tools_used"].append(tool_name)
                if isinstance(result, Exception):
                    continue
                output = result.get("output", "") if isinstance(result, dict) else str(result)
                if self._xss_found(output, tool_name):
                    finding = WebAppFinding(
                        category="xss",
                        severity="high",
                        source_tool=tool_name,
                        title="Cross-Site Scripting (XSS) Detected",
                        description=f"XSS vulnerability found at {xss_target}",
                        url=xss_target,
                        evidence=output[:1000],
                        remediation="Implement output encoding. Use Content-Security-Policy headers. Sanitize user input.",
                        cwe_id="CWE-79",
                    )
                    self.findings.append(finding)
                    phase_results["vulnerabilities"].append(finding.title)

        return phase_results

    async def _phase_auth_testing(
        self, target_url: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 6: Authentication and session testing."""
        phase_results: dict[str, Any] = {"tools_used": [], "vulnerabilities": []}

        # Use nuclei with auth-related templates
        nuclei_result = await agent_core.run_tool(
            "nuclei",
            [
                "-u", target_url,
                "-t", "http/vulnerabilities/",
                "-t", "http/misconfiguration/",
                "-t", "http/exposures/",
                "-t", "http/default-logins/",
                "-severity", "critical,high,medium",
                "-silent",
                "-no-color",
            ],
        )
        phase_results["tools_used"].append("nuclei")

        if not isinstance(nuclei_result, Exception):
            output = nuclei_result.get("output", "") if isinstance(nuclei_result, dict) else str(nuclei_result)
            nuclei_findings = self._parse_nuclei_output(output, target_url)
            self.findings.extend(nuclei_findings)
            phase_results["vulnerabilities"] = [f.title for f in nuclei_findings]

        # Fuzz authentication endpoints with wfuzz
        auth_endpoints = [
            ep for ep in self._endpoints
            if any(kw in ep.lower() for kw in ("login", "auth", "signin", "admin", "session"))
        ]
        for endpoint in auth_endpoints[:5]:
            wfuzz_result = await agent_core.run_tool(
                "wfuzz",
                [
                    "-z", "file,/usr/share/wordlists/seclists/Passwords/Common-Credentials/top-20-common-SSH-passwords.txt",
                    "-d", "username=admin&password=FUZZ",
                    "--hc", "403,404",
                    endpoint,
                ],
            )
            phase_results["tools_used"].append("wfuzz")
            if not isinstance(wfuzz_result, Exception):
                output = wfuzz_result.get("output", "") if isinstance(wfuzz_result, dict) else str(wfuzz_result)
                if self._wfuzz_found_valid(output):
                    self.findings.append(
                        WebAppFinding(
                            category="authentication",
                            severity="critical",
                            source_tool="wfuzz",
                            title="Weak or Default Credentials Detected",
                            description=f"Default/weak credentials found at {endpoint}",
                            url=endpoint,
                            evidence=output[:500],
                            remediation="Enforce strong password policies. Disable default accounts. Implement account lockout.",
                            cwe_id="CWE-521",
                        )
                    )

        return phase_results

    async def _phase_api_testing(
        self, target_url: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 7: API endpoint testing."""
        phase_results: dict[str, Any] = {"tools_used": [], "vulnerabilities": []}

        # Discover API endpoints with ffuf
        ffuf_result = await agent_core.run_tool(
            "ffuf",
            [
                "-u", f"{target_url}/api/FUZZ",
                "-w", self.WORDLISTS.get("api", self.WORDLISTS["directories"]),
                "-mc", "200,201,202,204,301,302,307,401,403,405",
                "-t", "50",
                "-s",
            ],
        )
        phase_results["tools_used"].append("ffuf")

        api_endpoints: list[str] = []
        if not isinstance(ffuf_result, Exception):
            output = ffuf_result.get("output", "") if isinstance(ffuf_result, dict) else str(ffuf_result)
            for line in output.splitlines():
                line = line.strip()
                if line:
                    api_endpoints.append(f"{target_url}/api/{line}")
                    self._endpoints.add(f"{target_url}/api/{line}")

        # Nuclei scan on discovered API endpoints
        if api_endpoints:
            api_targets = "\n".join(api_endpoints)
            nuclei_api = await agent_core.run_tool(
                "nuclei",
                [
                    "-t", "http/vulnerabilities/",
                    "-t", "http/token-spray/",
                    "-severity", "critical,high,medium",
                    "-silent",
                ],
                stdin_data=api_targets,
            )
            phase_results["tools_used"].append("nuclei")
            if not isinstance(nuclei_api, Exception):
                output = nuclei_api.get("output", "") if isinstance(nuclei_api, dict) else str(nuclei_api)
                api_findings = self._parse_nuclei_output(output, target_url)
                self.findings.extend(api_findings)
                phase_results["vulnerabilities"] = [f.title for f in api_findings]

        phase_results["api_endpoints_found"] = len(api_endpoints)
        return phase_results

    async def _phase_tls_testing(
        self, target_url: str, agent_core: Any
    ) -> dict[str, Any]:
        """Optional: TLS/SSL configuration testing."""
        phase_results: dict[str, Any] = {"tools_used": ["testssl"], "issues": []}

        parsed = urlparse(target_url)
        host = parsed.hostname or ""
        port = parsed.port or 443

        testssl_result = await agent_core.run_tool(
            "testssl", ["--quiet", "--color", "0", f"{host}:{port}"]
        )

        if not isinstance(testssl_result, Exception):
            output = testssl_result.get("output", "") if isinstance(testssl_result, dict) else str(testssl_result)
            tls_issues = self._parse_testssl(output, target_url)
            self.findings.extend(tls_issues)
            phase_results["issues"] = [f.title for f in tls_issues]

        return phase_results

    # ------------------------------------------------------------------
    # Parsers and helpers
    # ------------------------------------------------------------------

    def _parse_whatweb(self, output: str, url: str) -> None:
        """Extract technology information from whatweb output."""
        techs = re.findall(r"\[([^\]]+)\]", output)
        for tech in techs:
            tech = tech.strip()
            if tech and len(tech) < 100:
                self._tech_stack[tech] = True

    def _parse_nikto(self, output: str, url: str) -> None:
        """Extract findings from nikto output."""
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("+") and "OSVDB" in line:
                self.findings.append(
                    WebAppFinding(
                        category="misconfiguration",
                        severity="medium",
                        source_tool="nikto",
                        title=f"Nikto finding: {line[:100]}",
                        description=line,
                        url=url,
                    )
                )

    def _extract_urls_from_bruteforce(self, output: str, base_url: str) -> set[str]:
        """Extract discovered URLs from bruteforce tool output."""
        urls: set[str] = set()
        for line in output.splitlines():
            line = line.strip()
            # Match common output formats: status code + URL or just paths
            url_match = re.search(r"(https?://\S+)", line)
            if url_match:
                urls.add(url_match.group(1))
                continue
            path_match = re.match(r"(?:\d{3}\s+)?(/\S+)", line)
            if path_match:
                urls.add(f"{base_url}{path_match.group(1)}")
        return urls

    def _extract_parameters(self, output: str) -> list[str]:
        """Extract discovered parameter names from tool output."""
        params: list[str] = []
        # Arjun format: [param_name]
        arjun_params = re.findall(r"\[(\w+)\]", output)
        params.extend(arjun_params)
        # Generic: param=value patterns in URLs
        url_params = re.findall(r"[?&](\w+)=", output)
        params.extend(url_params)
        return list(set(params))

    def _build_injection_targets(self, base_url: str) -> list[str]:
        """Build injectable target URLs from discovered params."""
        targets: list[str] = []
        for url, params in self._discovered_params.items():
            for param in params:
                targets.append(f"{url}?{param}=FUZZ")
        # If no params discovered, use the base URL
        if not targets:
            targets.append(base_url)
        return targets

    def _sqlmap_found_vuln(self, output: str) -> bool:
        """Check if sqlmap found a vulnerability."""
        indicators = [
            "is vulnerable",
            "sqlmap identified the following injection",
            "parameter is vulnerable",
            "Type: boolean-based",
            "Type: time-based",
            "Type: UNION query",
            "Type: error-based",
        ]
        output_lower = output.lower()
        return any(ind.lower() in output_lower for ind in indicators)

    def _xss_found(self, output: str, tool_name: str) -> bool:
        """Check if XSS tool found a vulnerability."""
        if tool_name == "xsstrike":
            return "Vulnerable" in output or "XSS" in output
        if tool_name == "dalfox":
            return "[POC]" in output or "[V]" in output or "Verified" in output
        return False

    def _parse_nuclei_output(self, output: str, target_url: str) -> list[WebAppFinding]:
        """Parse nuclei output into findings."""
        findings: list[WebAppFinding] = []
        severity_map = {
            "critical": "critical",
            "high": "high",
            "medium": "medium",
            "low": "low",
            "info": "info",
        }
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            # Nuclei output format: [template-id] [protocol] [severity] url
            match = re.match(
                r"\[([^\]]+)\]\s*\[([^\]]+)\]\s*\[([^\]]+)\]\s*(.*)", line
            )
            if match:
                template_id = match.group(1)
                protocol = match.group(2)
                severity_raw = match.group(3).lower()
                found_url = match.group(4).strip() or target_url
                severity = severity_map.get(severity_raw, "info")
                findings.append(
                    WebAppFinding(
                        category="vulnerability",
                        severity=severity,
                        source_tool="nuclei",
                        title=f"Nuclei: {template_id}",
                        description=f"Detected by template {template_id} via {protocol}",
                        url=found_url,
                    )
                )
        return findings

    def _wfuzz_found_valid(self, output: str) -> bool:
        """Check if wfuzz found valid credentials."""
        for line in output.splitlines():
            if re.search(r"\b200\b", line) and "Ch" in line:
                return True
        return False

    def _parse_testssl(self, output: str, target_url: str) -> list[WebAppFinding]:
        """Parse testssl output for TLS issues."""
        findings: list[WebAppFinding] = []
        severity_keywords = {
            "CRITICAL": "critical",
            "HIGH": "high",
            "MEDIUM": "medium",
            "LOW": "low",
        }
        for line in output.splitlines():
            for keyword, severity in severity_keywords.items():
                if keyword in line:
                    findings.append(
                        WebAppFinding(
                            category="tls",
                            severity=severity,
                            source_tool="testssl",
                            title=f"TLS Issue: {line.strip()[:80]}",
                            description=line.strip(),
                            url=target_url,
                            remediation="Update TLS configuration to disable weak ciphers and protocols.",
                            cwe_id="CWE-326",
                        )
                    )
                    break
        return findings

    def _build_summary(self) -> dict[str, Any]:
        """Compile a summary of all findings."""
        severity_counts: dict[str, int] = {}
        for f in self.findings:
            severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1
        return {
            "total_findings": len(self.findings),
            "severity_counts": severity_counts,
            "endpoints_discovered": len(self._endpoints),
            "parameters_discovered": sum(len(v) for v in self._discovered_params.values()),
            "technologies_identified": list(self._tech_stack.keys()),
            "categories": list({f.category for f in self.findings}),
        }
