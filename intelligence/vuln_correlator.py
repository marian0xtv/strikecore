"""
VulnCorrelator - Vulnerability correlation and deduplication engine.

Collects findings from multiple agents, deduplicates them, assigns
severity scores using a CVSS-like system, and generates attack chains
showing potential exploitation paths.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    """Vulnerability severity levels aligned with CVSS v3.1 ranges."""
    CRITICAL = "critical"  # 9.0 - 10.0
    HIGH = "high"          # 7.0 - 8.9
    MEDIUM = "medium"      # 4.0 - 6.9
    LOW = "low"            # 0.1 - 3.9
    INFO = "info"          # 0.0


@dataclass
class NormalizedFinding:
    """A normalized, deduplicated finding with assigned severity score."""
    finding_id: str
    title: str
    description: str
    severity: Severity
    cvss_score: float
    category: str
    source_agents: list[str] = field(default_factory=list)
    source_tools: list[str] = field(default_factory=list)
    affected_asset: str = ""
    url: str = ""
    parameter: str = ""
    evidence: str = ""
    remediation: str = ""
    cwe_id: str = ""
    cve_ids: list[str] = field(default_factory=list)
    confidence: float = 1.0
    duplicate_of: str | None = None
    references: list[str] = field(default_factory=list)


@dataclass
class AttackChainStep:
    """A single step in an attack chain."""
    step_number: int
    finding_id: str
    title: str
    description: str
    asset: str
    technique: str


@dataclass
class AttackChain:
    """A potential attack path composed of chained findings."""
    chain_id: str
    name: str
    description: str
    steps: list[AttackChainStep]
    overall_severity: Severity
    overall_cvss: float
    impact: str


@dataclass
class CorrelatedReport:
    """The final correlated vulnerability report."""
    total_raw_findings: int
    total_unique_findings: int
    total_duplicates_removed: int
    findings: list[NormalizedFinding]
    attack_chains: list[AttackChain]
    severity_distribution: dict[str, int]
    top_affected_assets: list[dict[str, Any]]
    executive_summary: str


class VulnCorrelator:
    """
    Correlates, deduplicates, and ranks vulnerability findings from
    multiple security agents.
    """

    # CVSS-like scoring weights for different vulnerability attributes
    SEVERITY_SCORES: dict[str, float] = {
        "critical": 9.5,
        "high": 7.5,
        "medium": 5.0,
        "low": 2.5,
        "info": 0.0,
    }

    # Category-based base scores for findings without explicit severity
    CATEGORY_BASE_SCORES: dict[str, float] = {
        "injection": 9.0,
        "sqli": 9.0,
        "rce": 10.0,
        "command_injection": 9.5,
        "xss": 7.0,
        "ssrf": 8.0,
        "authentication": 8.0,
        "authorization": 8.5,
        "idor": 7.5,
        "misconfiguration": 5.0,
        "information_disclosure": 4.0,
        "tls": 4.5,
        "subdomain_takeover": 8.0,
        "vulnerability": 6.0,
        "secrets": 9.0,
        "iam": 8.0,
        "compliance": 5.0,
        "container_vulnerability": 7.0,
        "format_string": 8.5,
        "buffer_overflow": 9.0,
        "protection": 3.0,
    }

    # Similarity thresholds for deduplication
    DEDUP_TITLE_SIMILARITY: float = 0.85
    DEDUP_EXACT_FIELDS: list[str] = ["url", "parameter", "cwe_id"]

    def __init__(self) -> None:
        self._raw_findings: list[dict[str, Any]] = []
        self._normalized: list[NormalizedFinding] = []
        self._attack_chains: list[AttackChain] = []

    def correlate(self, findings: list[dict[str, Any]]) -> CorrelatedReport:
        """
        Process a list of raw findings from multiple agents into a
        correlated, deduplicated report.

        Args:
            findings: List of finding dictionaries from various agents.
                      Each should have at minimum: title, description,
                      severity (or category), and ideally source_tool.

        Returns:
            A CorrelatedReport with deduplicated findings, attack chains,
            and an executive summary.
        """
        self._raw_findings = findings
        total_raw = len(findings)
        logger.info("VulnCorrelator processing %d raw findings.", total_raw)

        # Step 1: Normalize all findings
        normalized = [self._normalize(f) for f in findings]

        # Step 2: Deduplicate
        unique = self._deduplicate(normalized)
        duplicates_removed = total_raw - len(unique)
        logger.info("Deduplication removed %d findings.", duplicates_removed)

        # Step 3: Score and rank
        for finding in unique:
            if finding.cvss_score == 0.0 and finding.severity != Severity.INFO:
                finding.cvss_score = self._compute_cvss(finding)
            finding.severity = self._score_to_severity(finding.cvss_score)

        # Step 4: Sort by severity/score
        unique.sort(key=lambda f: f.cvss_score, reverse=True)

        # Step 5: Boost confidence for multi-source findings
        for finding in unique:
            if len(finding.source_tools) > 1:
                finding.confidence = min(1.0, finding.confidence + 0.1 * (len(finding.source_tools) - 1))

        # Step 6: Generate attack chains
        attack_chains = self._generate_attack_chains(unique)

        # Step 7: Build report
        self._normalized = unique
        self._attack_chains = attack_chains

        severity_dist = self._severity_distribution(unique)
        top_assets = self._top_affected_assets(unique)
        summary = self._generate_executive_summary(unique, attack_chains, severity_dist)

        report = CorrelatedReport(
            total_raw_findings=total_raw,
            total_unique_findings=len(unique),
            total_duplicates_removed=duplicates_removed,
            findings=unique,
            attack_chains=attack_chains,
            severity_distribution=severity_dist,
            top_affected_assets=top_assets,
            executive_summary=summary,
        )

        logger.info(
            "Correlation complete. %d unique findings, %d attack chains.",
            len(unique), len(attack_chains),
        )

        return report

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _normalize(self, raw: dict[str, Any]) -> NormalizedFinding:
        """Normalize a raw finding dictionary into a NormalizedFinding."""
        title = raw.get("title", "Untitled Finding")
        description = raw.get("description", "")
        category = raw.get("category", "unknown")

        # Determine severity
        severity_str = raw.get("severity", "info").lower()
        severity = Severity(severity_str) if severity_str in Severity.__members__.values() else Severity.INFO

        # Compute initial CVSS score
        cvss = self.SEVERITY_SCORES.get(severity_str, 0.0)
        if cvss == 0.0 and category in self.CATEGORY_BASE_SCORES:
            cvss = self.CATEGORY_BASE_SCORES[category]
            severity = self._score_to_severity(cvss)

        # Extract source info
        source_agents = []
        if raw.get("source_agent"):
            source_agents = [raw["source_agent"]]
        elif raw.get("agent_name"):
            source_agents = [raw["agent_name"]]

        source_tools = []
        if raw.get("source_tool"):
            source_tools = [raw["source_tool"]]

        # Extract CVE IDs from description/title
        cve_ids = re.findall(r"CVE-\d{4}-\d+", f"{title} {description}")

        finding_id = self._generate_id(title, raw.get("url", ""), raw.get("parameter", ""))

        return NormalizedFinding(
            finding_id=finding_id,
            title=title,
            description=description,
            severity=severity,
            cvss_score=cvss,
            category=category,
            source_agents=source_agents,
            source_tools=source_tools,
            affected_asset=raw.get("affected_asset", raw.get("url", raw.get("resource", ""))),
            url=raw.get("url", ""),
            parameter=raw.get("parameter", ""),
            evidence=raw.get("evidence", ""),
            remediation=raw.get("remediation", ""),
            cwe_id=raw.get("cwe_id", ""),
            cve_ids=list(set(cve_ids)),
            confidence=raw.get("confidence", 1.0),
            references=raw.get("references", []),
        )

    @staticmethod
    def _generate_id(title: str, url: str, parameter: str) -> str:
        """Generate a deterministic finding ID based on key fields."""
        content = f"{title.lower()}|{url.lower()}|{parameter.lower()}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def _deduplicate(self, findings: list[NormalizedFinding]) -> list[NormalizedFinding]:
        """Remove duplicate findings, merging source information."""
        unique: dict[str, NormalizedFinding] = {}
        id_map: dict[str, str] = {}  # Maps duplicate IDs to canonical IDs

        for finding in findings:
            # Check for exact ID match
            if finding.finding_id in unique:
                self._merge_finding(unique[finding.finding_id], finding)
                continue

            # Check for similar existing finding
            merged = False
            for canonical_id, existing in unique.items():
                if self._are_duplicates(existing, finding):
                    self._merge_finding(existing, finding)
                    id_map[finding.finding_id] = canonical_id
                    finding.duplicate_of = canonical_id
                    merged = True
                    break

            if not merged:
                unique[finding.finding_id] = finding

        return list(unique.values())

    def _are_duplicates(self, a: NormalizedFinding, b: NormalizedFinding) -> bool:
        """Determine if two findings are duplicates."""
        # Same CVE
        if a.cve_ids and b.cve_ids and set(a.cve_ids) & set(b.cve_ids):
            if a.affected_asset == b.affected_asset or not a.affected_asset or not b.affected_asset:
                return True

        # Same CWE + same asset + same parameter
        if (
            a.cwe_id and a.cwe_id == b.cwe_id
            and a.url and a.url == b.url
            and a.parameter and a.parameter == b.parameter
        ):
            return True

        # Title similarity
        if self._title_similarity(a.title, b.title) >= self.DEDUP_TITLE_SIMILARITY:
            if a.url == b.url or not a.url or not b.url:
                return True

        # Same category + same asset
        if a.category == b.category and a.url and a.url == b.url and a.parameter == b.parameter:
            return True

        return False

    @staticmethod
    def _title_similarity(a: str, b: str) -> float:
        """Compute Jaccard similarity between two titles."""
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)

    @staticmethod
    def _merge_finding(canonical: NormalizedFinding, duplicate: NormalizedFinding) -> None:
        """Merge a duplicate finding's data into the canonical finding."""
        # Merge source information
        for agent in duplicate.source_agents:
            if agent not in canonical.source_agents:
                canonical.source_agents.append(agent)
        for tool in duplicate.source_tools:
            if tool not in canonical.source_tools:
                canonical.source_tools.append(tool)

        # Keep the higher CVSS score
        if duplicate.cvss_score > canonical.cvss_score:
            canonical.cvss_score = duplicate.cvss_score

        # Merge CVE IDs
        for cve in duplicate.cve_ids:
            if cve not in canonical.cve_ids:
                canonical.cve_ids.append(cve)

        # Keep longer evidence
        if len(duplicate.evidence) > len(canonical.evidence):
            canonical.evidence = duplicate.evidence

        # Keep remediation if missing
        if not canonical.remediation and duplicate.remediation:
            canonical.remediation = duplicate.remediation

        # Keep CWE if missing
        if not canonical.cwe_id and duplicate.cwe_id:
            canonical.cwe_id = duplicate.cwe_id

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _compute_cvss(self, finding: NormalizedFinding) -> float:
        """Compute a CVSS-like score based on finding attributes."""
        base = self.CATEGORY_BASE_SCORES.get(finding.category, 5.0)

        # Adjust based on attributes
        adjustments = 0.0

        # Network-accessible findings are more severe
        if finding.url:
            adjustments += 0.5

        # Parameterized findings indicate confirmed vulnerability
        if finding.parameter:
            adjustments += 0.3

        # Evidence of exploitation increases severity
        if finding.evidence:
            adjustments += 0.2

        # Known CVE increases severity
        if finding.cve_ids:
            adjustments += 0.5

        # Multi-source confirmation increases score
        if len(finding.source_tools) > 1:
            adjustments += 0.3

        return min(10.0, base + adjustments)

    @staticmethod
    def _score_to_severity(score: float) -> Severity:
        """Convert a CVSS score to a severity level."""
        if score >= 9.0:
            return Severity.CRITICAL
        if score >= 7.0:
            return Severity.HIGH
        if score >= 4.0:
            return Severity.MEDIUM
        if score > 0.0:
            return Severity.LOW
        return Severity.INFO

    # ------------------------------------------------------------------
    # Attack chain generation
    # ------------------------------------------------------------------

    def _generate_attack_chains(
        self, findings: list[NormalizedFinding]
    ) -> list[AttackChain]:
        """Generate potential attack chains from correlated findings."""
        chains: list[AttackChain] = []

        # Group findings by asset
        asset_findings: dict[str, list[NormalizedFinding]] = {}
        for f in findings:
            asset = f.affected_asset or "unknown"
            if asset not in asset_findings:
                asset_findings[asset] = []
            asset_findings[asset].append(f)

        chain_counter = 0

        for asset, asset_vulns in asset_findings.items():
            if len(asset_vulns) < 2:
                continue

            # Look for specific attack chain patterns
            chain = self._detect_recon_to_exploit_chain(asset, asset_vulns)
            if chain:
                chain_counter += 1
                chain.chain_id = f"chain_{chain_counter:03d}"
                chains.append(chain)

            chain = self._detect_escalation_chain(asset, asset_vulns)
            if chain:
                chain_counter += 1
                chain.chain_id = f"chain_{chain_counter:03d}"
                chains.append(chain)

            chain = self._detect_data_exfil_chain(asset, asset_vulns)
            if chain:
                chain_counter += 1
                chain.chain_id = f"chain_{chain_counter:03d}"
                chains.append(chain)

        return chains

    def _detect_recon_to_exploit_chain(
        self, asset: str, findings: list[NormalizedFinding]
    ) -> AttackChain | None:
        """Detect a chain from information disclosure to exploitation."""
        info_findings = [f for f in findings if f.severity in (Severity.INFO, Severity.LOW)]
        exploit_findings = [f for f in findings if f.severity in (Severity.CRITICAL, Severity.HIGH)]

        if not info_findings or not exploit_findings:
            return None

        steps = []
        step_num = 1
        for info_f in info_findings[:2]:
            steps.append(AttackChainStep(
                step_number=step_num,
                finding_id=info_f.finding_id,
                title=info_f.title,
                description=f"Information gathering: {info_f.description[:200]}",
                asset=asset,
                technique="reconnaissance",
            ))
            step_num += 1

        for exploit_f in exploit_findings[:2]:
            steps.append(AttackChainStep(
                step_number=step_num,
                finding_id=exploit_f.finding_id,
                title=exploit_f.title,
                description=f"Exploitation: {exploit_f.description[:200]}",
                asset=asset,
                technique="exploitation",
            ))
            step_num += 1

        max_cvss = max(f.cvss_score for f in exploit_findings[:2])

        return AttackChain(
            chain_id="",
            name=f"Recon-to-Exploit on {asset}",
            description=(
                f"Information disclosure findings enable targeted exploitation "
                f"of {len(exploit_findings)} high-severity vulnerabilities on {asset}."
            ),
            steps=steps,
            overall_severity=self._score_to_severity(max_cvss),
            overall_cvss=max_cvss,
            impact="Full compromise of the affected asset through chained vulnerabilities.",
        )

    def _detect_escalation_chain(
        self, asset: str, findings: list[NormalizedFinding]
    ) -> AttackChain | None:
        """Detect a privilege escalation chain."""
        auth_findings = [f for f in findings if f.category in ("authentication", "authorization", "iam")]
        injection_findings = [f for f in findings if f.category in ("injection", "sqli", "command_injection", "rce")]

        if not auth_findings or not injection_findings:
            return None

        steps = []
        step_num = 1
        for auth_f in auth_findings[:1]:
            steps.append(AttackChainStep(
                step_number=step_num,
                finding_id=auth_f.finding_id,
                title=auth_f.title,
                description=f"Initial access: {auth_f.description[:200]}",
                asset=asset,
                technique="authentication_bypass",
            ))
            step_num += 1

        for inj_f in injection_findings[:1]:
            steps.append(AttackChainStep(
                step_number=step_num,
                finding_id=inj_f.finding_id,
                title=inj_f.title,
                description=f"Privilege escalation: {inj_f.description[:200]}",
                asset=asset,
                technique="code_execution",
            ))
            step_num += 1

        max_cvss = max(
            max((f.cvss_score for f in auth_findings[:1]), default=0),
            max((f.cvss_score for f in injection_findings[:1]), default=0),
        )

        return AttackChain(
            chain_id="",
            name=f"Auth Bypass to Code Execution on {asset}",
            description=(
                "Authentication weakness enables initial access, followed by "
                "injection vulnerability for privilege escalation."
            ),
            steps=steps,
            overall_severity=Severity.CRITICAL,
            overall_cvss=min(10.0, max_cvss + 0.5),
            impact="Complete system compromise through authentication bypass and code execution.",
        )

    def _detect_data_exfil_chain(
        self, asset: str, findings: list[NormalizedFinding]
    ) -> AttackChain | None:
        """Detect a data exfiltration chain."""
        access_findings = [
            f for f in findings
            if f.category in ("authentication", "authorization", "idor", "ssrf", "misconfiguration")
        ]
        data_findings = [
            f for f in findings
            if f.category in ("information_disclosure", "sqli", "injection", "secrets")
        ]

        if not access_findings or not data_findings:
            return None

        steps = []
        step_num = 1
        for af in access_findings[:1]:
            steps.append(AttackChainStep(
                step_number=step_num,
                finding_id=af.finding_id,
                title=af.title,
                description=f"Gain access: {af.description[:200]}",
                asset=asset,
                technique="access_control_bypass",
            ))
            step_num += 1

        for df in data_findings[:1]:
            steps.append(AttackChainStep(
                step_number=step_num,
                finding_id=df.finding_id,
                title=df.title,
                description=f"Extract data: {df.description[:200]}",
                asset=asset,
                technique="data_extraction",
            ))
            step_num += 1

        max_cvss = max(
            max((f.cvss_score for f in access_findings[:1]), default=0),
            max((f.cvss_score for f in data_findings[:1]), default=0),
        )

        return AttackChain(
            chain_id="",
            name=f"Data Exfiltration via {asset}",
            description="Access control weakness enables unauthorized data extraction.",
            steps=steps,
            overall_severity=Severity.HIGH,
            overall_cvss=min(10.0, max_cvss + 0.3),
            impact="Unauthorized access to sensitive data through chained vulnerabilities.",
        )

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    @staticmethod
    def _severity_distribution(findings: list[NormalizedFinding]) -> dict[str, int]:
        """Count findings per severity level."""
        dist: dict[str, int] = {s.value: 0 for s in Severity}
        for f in findings:
            dist[f.severity.value] = dist.get(f.severity.value, 0) + 1
        return dist

    @staticmethod
    def _top_affected_assets(
        findings: list[NormalizedFinding], limit: int = 10
    ) -> list[dict[str, Any]]:
        """Identify the most-affected assets."""
        asset_stats: dict[str, dict[str, Any]] = {}
        for f in findings:
            asset = f.affected_asset or "unknown"
            if asset not in asset_stats:
                asset_stats[asset] = {"asset": asset, "count": 0, "max_cvss": 0.0, "categories": set()}
            asset_stats[asset]["count"] += 1
            asset_stats[asset]["max_cvss"] = max(asset_stats[asset]["max_cvss"], f.cvss_score)
            asset_stats[asset]["categories"].add(f.category)

        # Convert sets to lists for serialization
        for stats in asset_stats.values():
            stats["categories"] = list(stats["categories"])

        sorted_assets = sorted(asset_stats.values(), key=lambda a: (a["max_cvss"], a["count"]), reverse=True)
        return sorted_assets[:limit]

    def _generate_executive_summary(
        self,
        findings: list[NormalizedFinding],
        chains: list[AttackChain],
        severity_dist: dict[str, int],
    ) -> str:
        """Generate a high-level executive summary."""
        total = len(findings)
        critical = severity_dist.get("critical", 0)
        high = severity_dist.get("high", 0)
        medium = severity_dist.get("medium", 0)
        low = severity_dist.get("low", 0)

        parts: list[str] = [
            f"Security assessment identified {total} unique vulnerabilities: "
            f"{critical} critical, {high} high, {medium} medium, and {low} low severity.",
        ]

        if chains:
            parts.append(
                f"{len(chains)} potential attack chain(s) were identified that combine "
                f"multiple findings into exploitable paths."
            )

        if critical > 0:
            crit_findings = [f for f in findings if f.severity == Severity.CRITICAL]
            crit_categories = list({f.category for f in crit_findings})
            parts.append(
                f"Critical findings include: {', '.join(crit_categories)}. "
                "Immediate remediation is strongly recommended."
            )

        if any(f.category == "secrets" for f in findings):
            parts.append(
                "Exposed secrets were detected. Credential rotation should be performed immediately."
            )

        affected_assets = {f.affected_asset for f in findings if f.affected_asset}
        if affected_assets:
            parts.append(f"{len(affected_assets)} unique asset(s) were affected.")

        return " ".join(parts)
