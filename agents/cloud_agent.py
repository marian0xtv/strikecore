"""
CloudAgent - Cloud security assessment agent.

Performs comprehensive cloud infrastructure security assessments including
credential validation, IAM analysis, resource enumeration, misconfiguration
scanning, secret detection, and container security analysis.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CloudProvider(str, Enum):
    """Supported cloud providers."""
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    KUBERNETES = "kubernetes"
    UNKNOWN = "unknown"


@dataclass
class CloudFinding:
    """A cloud security finding."""
    category: str
    severity: str  # critical, high, medium, low, info
    source_tool: str
    title: str
    description: str
    resource: str = ""
    provider: str = ""
    remediation: str = ""
    compliance: list[str] = field(default_factory=list)  # CIS, NIST, etc.
    confidence: float = 1.0


class CloudAgent:
    """Cloud security assessment agent."""

    name: str = "CloudAgent"
    description: str = (
        "Performs comprehensive cloud security assessments across AWS, GCP, "
        "Azure, and Kubernetes environments. Checks for IAM misconfigurations, "
        "exposed resources, secret leakage, and container vulnerabilities."
    )

    tools: list[str] = [
        "pacu",
        "prowler",
        "scout_suite",
        "cloudfox",
        "trufflehog",
        "gitleaks",
        "kubectl",
        "trivy",
        "grype",
    ]

    methodology: list[str] = [
        "1. Credential Check - Validate provided credentials, check permissions and identity",
        "2. IAM Analysis - Enumerate users, roles, policies; identify privilege escalation paths",
        "3. Resource Enumeration - Discover all cloud resources across services and regions",
        "4. Misconfiguration Scanning - Check for security misconfigurations against CIS benchmarks",
        "5. Secret Detection - Scan for leaked secrets in code repositories and configurations",
        "6. Container Security - Scan container images and Kubernetes configurations",
    ]

    system_prompt: str = (
        "You are a cloud security assessment specialist within the StrikeCore "
        "framework. Your role is to systematically evaluate cloud infrastructure "
        "for security weaknesses.\n\n"
        "RULES:\n"
        "- Only access resources within the authorized assessment scope.\n"
        "- Never modify or delete cloud resources.\n"
        "- Handle credentials with extreme care; never log them.\n"
        "- Check all regions, not just the default region.\n"
        "- Map findings to compliance frameworks (CIS, NIST, SOC2).\n"
        "- Prioritize findings that could lead to data exposure or account compromise.\n\n"
        "FOCUS AREAS:\n"
        "- Overly permissive IAM policies and privilege escalation\n"
        "- Publicly exposed storage (S3, GCS, Azure Blob)\n"
        "- Unencrypted data at rest and in transit\n"
        "- Missing logging and monitoring\n"
        "- Network segmentation issues\n"
        "- Container escape and Kubernetes RBAC\n\n"
        "METHODOLOGY:\n"
        "1. Credential Check\n"
        "2. IAM Analysis\n"
        "3. Resource Enumeration\n"
        "4. Misconfiguration Scanning\n"
        "5. Secret Detection\n"
        "6. Container Security"
    )

    def __init__(self) -> None:
        self.findings: list[CloudFinding] = []
        self._provider: CloudProvider = CloudProvider.UNKNOWN
        self._identity: dict[str, Any] = {}
        self._resources: dict[str, list[dict[str, Any]]] = {}
        self._iam_data: dict[str, Any] = {}

    async def run(self, target: str, agent_core: Any) -> dict[str, Any]:
        """
        Execute the full cloud security assessment methodology.

        Args:
            target: The cloud target -- an AWS account ID, GCP project,
                     Azure subscription, Kubernetes context, or repo URL.
            agent_core: The core agent loop handler.

        Returns:
            Dictionary containing all assessment findings.
        """
        logger.info("CloudAgent starting against target: %s", target)

        self._provider = self._detect_provider(target)

        context = {
            "agent_name": self.name,
            "system_prompt": self.system_prompt,
            "tools": self.tools,
            "target": target,
            "methodology": self.methodology,
            "provider": self._provider.value,
        }

        results: dict[str, Any] = {
            "target": target,
            "provider": self._provider.value,
            "phases": {},
            "summary": {},
        }

        # Phase 1: Credential Check
        results["phases"]["credential_check"] = await self._phase_credential_check(
            target, agent_core
        )

        # Phase 2: IAM Analysis
        results["phases"]["iam_analysis"] = await self._phase_iam_analysis(target, agent_core)

        # Phase 3: Resource Enumeration
        results["phases"]["resource_enum"] = await self._phase_resource_enum(target, agent_core)

        # Phase 4: Misconfiguration Scanning
        results["phases"]["misconfig_scan"] = await self._phase_misconfig_scan(target, agent_core)

        # Phase 5: Secret Detection
        results["phases"]["secret_detection"] = await self._phase_secret_detection(
            target, agent_core
        )

        # Phase 6: Container Security
        results["phases"]["container_security"] = await self._phase_container_security(
            target, agent_core
        )

        results["summary"] = self._build_summary()
        results["findings"] = [
            {
                "category": f.category,
                "severity": f.severity,
                "source_tool": f.source_tool,
                "title": f.title,
                "description": f.description,
                "resource": f.resource,
                "provider": f.provider,
                "remediation": f.remediation,
                "compliance": f.compliance,
            }
            for f in self.findings
        ]

        logger.info(
            "CloudAgent completed. %d findings across provider %s.",
            len(self.findings), self._provider.value,
        )

        return await agent_core.delegate(context, results)

    def _detect_provider(self, target: str) -> CloudProvider:
        """Detect the cloud provider from the target string."""
        target_lower = target.lower()
        if any(kw in target_lower for kw in ("aws", "amazon", "arn:", "s3://", "ec2")):
            return CloudProvider.AWS
        if any(kw in target_lower for kw in ("gcp", "google", "gcloud", "gs://")):
            return CloudProvider.GCP
        if any(kw in target_lower for kw in ("azure", "microsoft", "az://", ".azure.")):
            return CloudProvider.AZURE
        if any(kw in target_lower for kw in ("k8s", "kubernetes", "kubectl", "kube")):
            return CloudProvider.KUBERNETES
        return CloudProvider.UNKNOWN

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    async def _phase_credential_check(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 1: Validate credentials and determine identity."""
        phase_results: dict[str, Any] = {"tools_used": [], "identity": {}}

        if self._provider == CloudProvider.AWS:
            # AWS STS get-caller-identity equivalent via pacu
            pacu_result = await agent_core.run_tool(
                "pacu", ["--exec", "whoami"]
            )
            phase_results["tools_used"].append("pacu")
            if not isinstance(pacu_result, Exception):
                output = pacu_result.get("output", "") if isinstance(pacu_result, dict) else str(pacu_result)
                self._identity = {"raw": output[:2000]}
                # Parse ARN
                arn_match = re.search(r"arn:aws[:\w-]*:iam::\d+:\S+", output)
                if arn_match:
                    self._identity["arn"] = arn_match.group(0)
                account_match = re.search(r"Account:\s*(\d+)", output)
                if account_match:
                    self._identity["account_id"] = account_match.group(1)

        elif self._provider == CloudProvider.KUBERNETES:
            kubectl_result = await agent_core.run_tool(
                "kubectl", ["auth", "whoami", "-o", "json"]
            )
            phase_results["tools_used"].append("kubectl")
            if not isinstance(kubectl_result, Exception):
                output = kubectl_result.get("output", "") if isinstance(kubectl_result, dict) else str(kubectl_result)
                self._identity = {"raw": output[:2000]}

            # Check cluster info
            cluster_result = await agent_core.run_tool(
                "kubectl", ["cluster-info"]
            )
            if not isinstance(cluster_result, Exception):
                output = cluster_result.get("output", "") if isinstance(cluster_result, dict) else str(cluster_result)
                self._identity["cluster_info"] = output[:1000]

        elif self._provider == CloudProvider.GCP:
            scout_result = await agent_core.run_tool(
                "scout_suite", ["--provider", "gcp", "--project-id", target, "--dry-run"]
            )
            phase_results["tools_used"].append("scout_suite")
            if not isinstance(scout_result, Exception):
                output = scout_result.get("output", "") if isinstance(scout_result, dict) else str(scout_result)
                self._identity = {"raw": output[:2000]}

        elif self._provider == CloudProvider.AZURE:
            scout_result = await agent_core.run_tool(
                "scout_suite", ["--provider", "azure", "--subscription", target, "--dry-run"]
            )
            phase_results["tools_used"].append("scout_suite")
            if not isinstance(scout_result, Exception):
                output = scout_result.get("output", "") if isinstance(scout_result, dict) else str(scout_result)
                self._identity = {"raw": output[:2000]}

        phase_results["identity"] = self._identity
        return phase_results

    async def _phase_iam_analysis(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 2: IAM user, role, and policy analysis."""
        phase_results: dict[str, Any] = {"tools_used": [], "iam_issues": []}

        if self._provider == CloudProvider.AWS:
            # Enumerate IAM with pacu
            iam_enum = await agent_core.run_tool(
                "pacu", ["--exec", "iam__enum_users_roles_policies_groups"]
            )
            phase_results["tools_used"].append("pacu")
            if not isinstance(iam_enum, Exception):
                output = iam_enum.get("output", "") if isinstance(iam_enum, dict) else str(iam_enum)
                self._iam_data["enum"] = output[:5000]

            # Check for privilege escalation paths
            privesc = await agent_core.run_tool(
                "pacu", ["--exec", "iam__privesc_scan"]
            )
            if not isinstance(privesc, Exception):
                output = privesc.get("output", "") if isinstance(privesc, dict) else str(privesc)
                if "escalation" in output.lower() or "privilege" in output.lower():
                    self.findings.append(
                        CloudFinding(
                            category="iam",
                            severity="high",
                            source_tool="pacu",
                            title="IAM Privilege Escalation Path Detected",
                            description=output[:1000],
                            provider=self._provider.value,
                            remediation="Review and restrict IAM policies. Apply least-privilege principles.",
                            compliance=["CIS AWS 1.16", "NIST AC-6"],
                        )
                    )
                    phase_results["iam_issues"].append("privilege_escalation_path")

            # CloudFox for AWS enumeration
            cloudfox_result = await agent_core.run_tool(
                "cloudfox", ["aws", "--profile", "default", "all-checks"]
            )
            phase_results["tools_used"].append("cloudfox")
            if not isinstance(cloudfox_result, Exception):
                output = cloudfox_result.get("output", "") if isinstance(cloudfox_result, dict) else str(cloudfox_result)
                self._parse_cloudfox_output(output)

        elif self._provider == CloudProvider.KUBERNETES:
            # Check RBAC
            rbac_result = await agent_core.run_tool(
                "kubectl", ["auth", "can-i", "--list"]
            )
            phase_results["tools_used"].append("kubectl")
            if not isinstance(rbac_result, Exception):
                output = rbac_result.get("output", "") if isinstance(rbac_result, dict) else str(rbac_result)
                self._iam_data["rbac"] = output[:3000]
                if "*" in output:
                    self.findings.append(
                        CloudFinding(
                            category="iam",
                            severity="critical",
                            source_tool="kubectl",
                            title="Kubernetes Wildcard RBAC Permissions",
                            description="Current context has wildcard (*) permissions.",
                            provider="kubernetes",
                            remediation="Restrict RBAC roles to specific resources and verbs.",
                            compliance=["CIS Kubernetes 5.1.1"],
                        )
                    )

            # List cluster roles
            roles_result = await agent_core.run_tool(
                "kubectl", ["get", "clusterrolebindings", "-o", "json"]
            )
            if not isinstance(roles_result, Exception):
                output = roles_result.get("output", "") if isinstance(roles_result, dict) else str(roles_result)
                self._iam_data["cluster_roles"] = output[:5000]

        phase_results["iam_data_collected"] = bool(self._iam_data)
        return phase_results

    async def _phase_resource_enum(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 3: Enumerate cloud resources."""
        phase_results: dict[str, Any] = {"tools_used": [], "resources": {}}

        if self._provider == CloudProvider.AWS:
            # Use pacu for broad resource enumeration
            resource_modules = [
                "ec2__enum",
                "s3__enum",
                "lambda__enum",
                "rds__enum",
                "ecs__enum",
            ]
            for module in resource_modules:
                result = await agent_core.run_tool("pacu", ["--exec", module])
                phase_results["tools_used"].append("pacu")
                if not isinstance(result, Exception):
                    output = result.get("output", "") if isinstance(result, dict) else str(result)
                    service = module.split("__")[0]
                    self._resources[service] = [{"raw": output[:3000]}]

        elif self._provider == CloudProvider.KUBERNETES:
            k8s_resources = [
                ["get", "pods", "--all-namespaces", "-o", "wide"],
                ["get", "services", "--all-namespaces", "-o", "wide"],
                ["get", "deployments", "--all-namespaces", "-o", "wide"],
                ["get", "secrets", "--all-namespaces"],
                ["get", "configmaps", "--all-namespaces"],
                ["get", "ingress", "--all-namespaces"],
                ["get", "networkpolicies", "--all-namespaces"],
            ]
            for cmd_args in k8s_resources:
                result = await agent_core.run_tool("kubectl", cmd_args)
                phase_results["tools_used"].append("kubectl")
                if not isinstance(result, Exception):
                    output = result.get("output", "") if isinstance(result, dict) else str(result)
                    resource_type = cmd_args[1]
                    self._resources[resource_type] = [{"raw": output[:3000]}]

                    # Check for exposed secrets
                    if resource_type == "secrets":
                        if "Opaque" in output:
                            self.findings.append(
                                CloudFinding(
                                    category="secrets",
                                    severity="medium",
                                    source_tool="kubectl",
                                    title="Kubernetes Secrets Found",
                                    description="Opaque secrets found in cluster. Verify they are encrypted at rest.",
                                    provider="kubernetes",
                                    remediation="Enable encryption at rest for secrets. Consider using external secret managers.",
                                    compliance=["CIS Kubernetes 5.4.1"],
                                )
                            )

        phase_results["resources"] = {k: len(v) for k, v in self._resources.items()}
        return phase_results

    async def _phase_misconfig_scan(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 4: CIS benchmark and misconfiguration scanning."""
        phase_results: dict[str, Any] = {"tools_used": [], "checks_passed": 0, "checks_failed": 0}

        if self._provider == CloudProvider.AWS:
            # Prowler for AWS CIS benchmark
            prowler_result = await agent_core.run_tool(
                "prowler",
                [
                    "-M", "json",
                    "--severity", "critical", "high", "medium",
                    "--quiet",
                ],
            )
            phase_results["tools_used"].append("prowler")
            if not isinstance(prowler_result, Exception):
                output = prowler_result.get("output", "") if isinstance(prowler_result, dict) else str(prowler_result)
                prowler_findings = self._parse_prowler_output(output)
                self.findings.extend(prowler_findings)
                phase_results["checks_failed"] = len(prowler_findings)

            # ScoutSuite for comprehensive check
            scout_result = await agent_core.run_tool(
                "scout_suite",
                ["--provider", "aws", "--no-browser", "--quiet"],
            )
            phase_results["tools_used"].append("scout_suite")
            if not isinstance(scout_result, Exception):
                output = scout_result.get("output", "") if isinstance(scout_result, dict) else str(scout_result)
                scout_findings = self._parse_scout_output(output)
                self.findings.extend(scout_findings)

        elif self._provider == CloudProvider.GCP:
            scout_result = await agent_core.run_tool(
                "scout_suite",
                ["--provider", "gcp", "--project-id", target, "--no-browser", "--quiet"],
            )
            phase_results["tools_used"].append("scout_suite")
            if not isinstance(scout_result, Exception):
                output = scout_result.get("output", "") if isinstance(scout_result, dict) else str(scout_result)
                scout_findings = self._parse_scout_output(output)
                self.findings.extend(scout_findings)

        elif self._provider == CloudProvider.AZURE:
            scout_result = await agent_core.run_tool(
                "scout_suite",
                ["--provider", "azure", "--no-browser", "--quiet"],
            )
            phase_results["tools_used"].append("scout_suite")
            if not isinstance(scout_result, Exception):
                output = scout_result.get("output", "") if isinstance(scout_result, dict) else str(scout_result)
                scout_findings = self._parse_scout_output(output)
                self.findings.extend(scout_findings)

        elif self._provider == CloudProvider.KUBERNETES:
            # Use trivy for k8s config audit
            trivy_result = await agent_core.run_tool(
                "trivy", ["k8s", "--report", "summary", "--severity", "CRITICAL,HIGH,MEDIUM", "cluster"]
            )
            phase_results["tools_used"].append("trivy")
            if not isinstance(trivy_result, Exception):
                output = trivy_result.get("output", "") if isinstance(trivy_result, dict) else str(trivy_result)
                trivy_findings = self._parse_trivy_output(output, "kubernetes")
                self.findings.extend(trivy_findings)

        return phase_results

    async def _phase_secret_detection(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 5: Detect leaked secrets in repos and configurations."""
        phase_results: dict[str, Any] = {"tools_used": [], "secrets_found": 0}

        # Determine scan target -- could be a repo URL or local path
        scan_path = target if "/" in target else "."

        # TruffleHog for secret scanning
        trufflehog_result = await agent_core.run_tool(
            "trufflehog",
            ["filesystem", scan_path, "--json", "--no-update"],
        )
        phase_results["tools_used"].append("trufflehog")
        if not isinstance(trufflehog_result, Exception):
            output = trufflehog_result.get("output", "") if isinstance(trufflehog_result, dict) else str(trufflehog_result)
            secret_count = output.count('"DetectorName"')
            if secret_count > 0:
                phase_results["secrets_found"] += secret_count
                self.findings.append(
                    CloudFinding(
                        category="secrets",
                        severity="critical",
                        source_tool="trufflehog",
                        title=f"Leaked Secrets Detected ({secret_count} findings)",
                        description=f"TruffleHog found {secret_count} potential secrets in {scan_path}.",
                        resource=scan_path,
                        provider=self._provider.value,
                        remediation="Rotate all detected secrets immediately. Remove from version control history.",
                        compliance=["CIS 1.14", "NIST IA-5"],
                    )
                )

        # Gitleaks
        gitleaks_result = await agent_core.run_tool(
            "gitleaks",
            ["detect", "--source", scan_path, "--report-format", "json", "--no-banner"],
        )
        phase_results["tools_used"].append("gitleaks")
        if not isinstance(gitleaks_result, Exception):
            output = gitleaks_result.get("output", "") if isinstance(gitleaks_result, dict) else str(gitleaks_result)
            leak_count = output.count('"RuleID"')
            if leak_count > 0:
                phase_results["secrets_found"] += leak_count
                self.findings.append(
                    CloudFinding(
                        category="secrets",
                        severity="critical",
                        source_tool="gitleaks",
                        title=f"Git Secrets Detected ({leak_count} leaks)",
                        description=f"Gitleaks found {leak_count} secrets in {scan_path}.",
                        resource=scan_path,
                        provider=self._provider.value,
                        remediation="Rotate exposed credentials. Use git-filter-repo to remove from history.",
                        compliance=["CIS 1.14", "NIST IA-5"],
                    )
                )

        return phase_results

    async def _phase_container_security(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 6: Container image and Kubernetes security scanning."""
        phase_results: dict[str, Any] = {"tools_used": [], "vulnerabilities": []}

        # Scan container images with trivy
        images_to_scan: list[str] = []

        if self._provider == CloudProvider.KUBERNETES:
            # Get images from running pods
            pods_data = self._resources.get("pods", [{}])
            raw_output = pods_data[0].get("raw", "") if pods_data else ""
            image_matches = re.findall(r"(\S+/\S+:\S+)", raw_output)
            images_to_scan.extend(image_matches[:20])

        # If target looks like an image reference, scan it directly
        if ":" in target and ("/" in target or "." in target):
            images_to_scan.append(target)

        for image in images_to_scan[:10]:
            trivy_result = await agent_core.run_tool(
                "trivy",
                ["image", "--severity", "CRITICAL,HIGH", "--format", "table", image],
            )
            phase_results["tools_used"].append("trivy")
            if not isinstance(trivy_result, Exception):
                output = trivy_result.get("output", "") if isinstance(trivy_result, dict) else str(trivy_result)
                trivy_findings = self._parse_trivy_output(output, image)
                self.findings.extend(trivy_findings)
                phase_results["vulnerabilities"].extend(f.title for f in trivy_findings)

            # Also scan with grype for cross-validation
            grype_result = await agent_core.run_tool(
                "grype", [image, "--only-fixed", "--fail-on", "high"]
            )
            phase_results["tools_used"].append("grype")
            if not isinstance(grype_result, Exception):
                output = grype_result.get("output", "") if isinstance(grype_result, dict) else str(grype_result)
                grype_findings = self._parse_grype_output(output, image)
                self.findings.extend(grype_findings)

        return phase_results

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    def _parse_cloudfox_output(self, output: str) -> None:
        """Parse CloudFox output for findings."""
        severity_keywords = {
            "CRITICAL": "critical",
            "HIGH": "high",
            "MEDIUM": "medium",
        }
        for line in output.splitlines():
            for keyword, severity in severity_keywords.items():
                if keyword in line.upper():
                    self.findings.append(
                        CloudFinding(
                            category="misconfiguration",
                            severity=severity,
                            source_tool="cloudfox",
                            title=f"CloudFox: {line.strip()[:80]}",
                            description=line.strip(),
                            provider=self._provider.value,
                        )
                    )
                    break

    def _parse_prowler_output(self, output: str) -> list[CloudFinding]:
        """Parse Prowler JSON output for findings."""
        findings: list[CloudFinding] = []
        severity_map = {"critical": "critical", "high": "high", "medium": "medium"}
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            # Prowler outputs one JSON object per line
            for sev_key, sev_val in severity_map.items():
                if f'"Severity": "{sev_key}"' in line.lower() or f'"severity": "{sev_key}"' in line.lower():
                    title_match = re.search(r'"(?:Check|Title)":\s*"([^"]+)"', line)
                    title = title_match.group(1) if title_match else line[:80]
                    resource_match = re.search(r'"(?:Resource|ResourceId)":\s*"([^"]+)"', line)
                    resource = resource_match.group(1) if resource_match else ""
                    findings.append(
                        CloudFinding(
                            category="compliance",
                            severity=sev_val,
                            source_tool="prowler",
                            title=f"Prowler: {title}",
                            description=line[:500],
                            resource=resource,
                            provider="aws",
                            compliance=["CIS AWS Foundations Benchmark"],
                        )
                    )
                    break
        return findings

    def _parse_scout_output(self, output: str) -> list[CloudFinding]:
        """Parse ScoutSuite output for findings."""
        findings: list[CloudFinding] = []
        # ScoutSuite outputs warnings with danger/warning levels
        for line in output.splitlines():
            if "danger" in line.lower():
                findings.append(
                    CloudFinding(
                        category="misconfiguration",
                        severity="high",
                        source_tool="scout_suite",
                        title=f"ScoutSuite: {line.strip()[:80]}",
                        description=line.strip(),
                        provider=self._provider.value,
                    )
                )
            elif "warning" in line.lower():
                findings.append(
                    CloudFinding(
                        category="misconfiguration",
                        severity="medium",
                        source_tool="scout_suite",
                        title=f"ScoutSuite: {line.strip()[:80]}",
                        description=line.strip(),
                        provider=self._provider.value,
                    )
                )
        return findings

    def _parse_trivy_output(self, output: str, resource: str) -> list[CloudFinding]:
        """Parse Trivy output for vulnerability findings."""
        findings: list[CloudFinding] = []
        for line in output.splitlines():
            line = line.strip()
            cve_match = re.search(r"(CVE-\d{4}-\d+)", line)
            if cve_match:
                severity = "high"
                if "CRITICAL" in line.upper():
                    severity = "critical"
                elif "HIGH" in line.upper():
                    severity = "high"
                elif "MEDIUM" in line.upper():
                    severity = "medium"
                findings.append(
                    CloudFinding(
                        category="container_vulnerability",
                        severity=severity,
                        source_tool="trivy",
                        title=f"Trivy: {cve_match.group(1)} in {resource}",
                        description=line,
                        resource=resource,
                        provider=self._provider.value,
                        remediation="Update the affected package to the fixed version.",
                    )
                )
        return findings

    def _parse_grype_output(self, output: str, resource: str) -> list[CloudFinding]:
        """Parse Grype output for vulnerability findings."""
        findings: list[CloudFinding] = []
        for line in output.splitlines():
            cve_match = re.search(r"(CVE-\d{4}-\d+)", line)
            if cve_match:
                severity = "medium"
                if "Critical" in line:
                    severity = "critical"
                elif "High" in line:
                    severity = "high"
                findings.append(
                    CloudFinding(
                        category="container_vulnerability",
                        severity=severity,
                        source_tool="grype",
                        title=f"Grype: {cve_match.group(1)} in {resource}",
                        description=line.strip(),
                        resource=resource,
                        provider=self._provider.value,
                        remediation="Update the affected package to the patched version.",
                    )
                )
        return findings

    def _build_summary(self) -> dict[str, Any]:
        """Compile assessment summary."""
        severity_counts: dict[str, int] = {}
        for f in self.findings:
            severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1
        return {
            "provider": self._provider.value,
            "total_findings": len(self.findings),
            "severity_counts": severity_counts,
            "resources_enumerated": sum(len(v) for v in self._resources.values()),
            "categories": list({f.category for f in self.findings}),
            "compliance_frameworks": list(
                {c for f in self.findings for c in f.compliance}
            ),
        }
