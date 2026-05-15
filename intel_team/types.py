"""Shared dataclasses and enums for the intel team.

These types are the *lingua franca* across specialists, the audit/red-cell
agent, the analyst, and the quality gate. They map directly to NATO Admiralty
Code (source reliability / information credibility) so the final dossier can
be rendered to military-intel standards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Domain(str, Enum):
    """OSINT/intel domains served by intel-team specialists."""

    SOCINT = "socint"        # social media, usernames, personal accounts
    GEOINT = "geoint"        # geolocation, image GPS, timezone correlation
    TECHINT = "techint"      # infrastructure, DNS, certs, ports, fingerprinting
    WEBINT = "webint"        # exposed data, breach correlation, dorking, archives
    THREATINT = "threatint"  # CTI feeds, IOC enrichment, malware/abuse history
    CROSSDB = "crossdb"      # cross-database fusion / entity resolution
    REDTEAM = "redteam"      # offensive recon, vulnerability mapping, exploit feasibility
    AUDIT = "audit"          # red cell / devil's advocate
    ANALYST = "analyst"      # synthesiser (ACH + KAC + dossier)
    META = "meta"            # pir_router and other orchestration roles


class Reliability(str, Enum):
    """NATO Admiralty Code — source reliability (A = most reliable)."""

    A = "A"  # completely reliable (history of total reliability)
    B = "B"  # usually reliable (minor doubt)
    C = "C"  # fairly reliable (doubt of authenticity but information plausible)
    D = "D"  # not usually reliable (significant doubt; information possibly true)
    E = "E"  # unreliable (history of invalidity)
    F = "F"  # cannot be judged (no basis for evaluation)


class Credibility(str, Enum):
    """NATO Admiralty Code — information credibility (1 = confirmed)."""

    ONE = "1"    # confirmed by independent sources, logical, agrees with prior reporting
    TWO = "2"    # probably true (not confirmed but logical and consistent)
    THREE = "3"  # possibly true (reasonable but not confirmed)
    FOUR = "4"   # doubtful (possible but not logical and not confirmed)
    FIVE = "5"   # improbable (contradicts reliable sources)
    SIX = "6"    # cannot be judged (no basis to assess)


@dataclass
class PIR:
    """Priority Intelligence Requirement — the operator's intel question.

    Every collection action in StrikeCore must trace back to a PIR.
    """

    question: str                                       # the actual intel question
    target: str                                         # primary subject (email/phone/handle/domain/name)
    id: str = field(default_factory=lambda: f"pir-{uuid4().hex[:12]}")
    domains_hint: list[Domain] = field(default_factory=list)   # operator hint; router may add/remove
    constraints: dict[str, Any] = field(default_factory=dict)  # e.g. time window, jurisdiction
    created_at: str = field(default_factory=_utc_now_iso)


@dataclass
class Source:
    """A single piece of provenance for a finding.

    Independence is judged by ``upstream`` — two tools that wrap the same
    underlying API (e.g. HIBP-derived) count as one upstream.
    """

    name: str                              # human-readable tool/source name (e.g. "h8mail", "github_api")
    upstream: str = ""                     # canonical upstream namespace (e.g. "hibp", "github")
    reference: str = ""                    # URL, audit_id, file path
    reliability: Reliability = Reliability.C
    credibility: Credibility = Credibility.THREE
    fetched_at: str = field(default_factory=_utc_now_iso)

    @property
    def admiralty(self) -> str:
        return f"{self.reliability.value}{self.credibility.value}"


@dataclass
class Finding:
    """A single piece of intelligence about the target.

    Confidence is a numeric 0.0–1.0 produced by:
      * the specialist (initial),
      * the quality gate (capped per the ≥2-source rule),
      * the audit/red-cell agent (downgraded if challenged).
    """

    domain: Domain
    finding_type: str                                   # e.g. "email", "phone", "alias", "location", "org"
    value: str                                          # the actual data point
    sources: list[Source] = field(default_factory=list)
    confidence: float = 0.0
    notes: str = ""
    pivot_hints: list[str] = field(default_factory=list)   # follow-on lookups the analyst may propose
    created_at: str = field(default_factory=_utc_now_iso)

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def independent_source_count(self) -> int:
        """Sources judged independent by ``upstream``.

        If ``upstream`` is empty, falls back to the first dotted segment of ``name``
        (e.g. "hibp.api" ≈ "hibp").
        """
        seen: set[str] = set()
        for s in self.sources:
            key = (s.upstream or s.name.split(".")[0]).lower()
            seen.add(key)
        return len(seen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain.value,
            "type": self.finding_type,
            "value": self.value,
            "confidence": round(self.confidence, 2),
            "sources": [
                {
                    "name": s.name,
                    "upstream": s.upstream,
                    "reference": s.reference,
                    "admiralty": s.admiralty,
                    "fetched_at": s.fetched_at,
                }
                for s in self.sources
            ],
            "independent_sources": self.independent_source_count,
            "notes": self.notes,
            "pivot_hints": self.pivot_hints,
            "created_at": self.created_at,
        }


@dataclass
class AgentReport:
    """The output a specialist returns to the orchestrator."""

    agent: str                                     # human-readable agent name
    domain: Domain
    pir_id: str
    findings: list[Finding] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)                 # what could not be answered
    rejected: list[dict[str, Any]] = field(default_factory=list)  # FP/quality-gate rejects (audit trail)
    devils_advocate_notes: list[str] = field(default_factory=list)
    confidence_summary: dict[str, int] = field(default_factory=dict)
    model: str = ""
    latency_seconds: float = 0.0
    error: str | None = None

    def add_finding(self, f: Finding) -> None:
        self.findings.append(f)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "domain": self.domain.value,
            "pir_id": self.pir_id,
            "findings": [f.to_dict() for f in self.findings],
            "gaps": self.gaps,
            "rejected": self.rejected,
            "devils_advocate_notes": self.devils_advocate_notes,
            "confidence_summary": self.confidence_summary,
            "model": self.model,
            "latency_seconds": round(self.latency_seconds, 2),
            "error": self.error,
        }


@dataclass
class Dossier:
    """Final military-grade intelligence dossier.

    Renders to Markdown for operator-facing reports and to JSON for the
    investigation store / audit chain.
    """

    target: str
    pir_id: str
    pir_question: str = ""
    bluf: str = ""                                                # Bottom Line Up Front
    key_judgments: list[dict[str, Any]] = field(default_factory=list)   # {judgment, confidence, sources}
    ach_summary: str = ""                                         # Analysis of Competing Hypotheses
    key_assumptions: list[str] = field(default_factory=list)      # Key Assumptions Check
    source_reliability_matrix: list[dict[str, Any]] = field(default_factory=list)
    intelligence_gaps: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    findings_by_domain: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    agent_reports: list[dict[str, Any]] = field(default_factory=list)
    audit_trail: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "pir_id": self.pir_id,
            "pir_question": self.pir_question,
            "bluf": self.bluf,
            "key_judgments": self.key_judgments,
            "ach_summary": self.ach_summary,
            "key_assumptions": self.key_assumptions,
            "source_reliability_matrix": self.source_reliability_matrix,
            "intelligence_gaps": self.intelligence_gaps,
            "recommended_actions": self.recommended_actions,
            "findings_by_domain": self.findings_by_domain,
            "agent_reports": self.agent_reports,
            "audit_trail": self.audit_trail,
            "generated_at": self.generated_at,
        }

    def to_markdown(self) -> str:
        """Render the dossier as operator-facing Markdown."""
        lines: list[str] = []
        push = lines.append

        push(f"# Intelligence Dossier — {self.target}")
        push("")
        push(f"- **PIR:** `{self.pir_id}` — {self.pir_question}")
        push(f"- **Generated:** {self.generated_at}")
        push("")

        push("## BLUF (Bottom Line Up Front)")
        push("")
        push(self.bluf or "_No BLUF provided._")
        push("")

        if self.key_judgments:
            push("## Key Judgments")
            push("")
            push("| # | Judgment | Confidence | Sources |")
            push("|---|---|---|---|")
            for i, kj in enumerate(self.key_judgments, 1):
                src = ", ".join(kj.get("sources", []))
                push(f"| {i} | {kj.get('judgment', '')} | {kj.get('confidence', '')} | {src} |")
            push("")

        if self.ach_summary:
            push("## Analysis of Competing Hypotheses (ACH)")
            push("")
            push(self.ach_summary)
            push("")

        if self.key_assumptions:
            push("## Key Assumptions Check")
            push("")
            for a in self.key_assumptions:
                push(f"- {a}")
            push("")

        if self.source_reliability_matrix:
            push("## Source Reliability Matrix (NATO Admiralty)")
            push("")
            push("| Source | Upstream | Reliability | Credibility | Admiralty |")
            push("|---|---|---|---|---|")
            for r in self.source_reliability_matrix:
                push(
                    f"| {r.get('name', '')} | {r.get('upstream', '')} | "
                    f"{r.get('reliability', '')} | {r.get('credibility', '')} | "
                    f"{r.get('admiralty', '')} |"
                )
            push("")

        if self.findings_by_domain:
            push("## Findings by Domain")
            push("")
            for domain, items in self.findings_by_domain.items():
                push(f"### {domain.upper()}")
                push("")
                if not items:
                    push("_(no findings)_")
                    push("")
                    continue
                push("| Type | Value | Confidence | Independent sources | Notes |")
                push("|---|---|---|---|---|")
                for it in items:
                    push(
                        f"| {it.get('type', '')} | {it.get('value', '')} | "
                        f"{it.get('confidence', '')} | {it.get('independent_sources', '')} | "
                        f"{it.get('notes', '')} |"
                    )
                push("")

        if self.intelligence_gaps:
            push("## Intelligence Gaps")
            push("")
            for g in self.intelligence_gaps:
                push(f"- {g}")
            push("")

        if self.recommended_actions:
            push("## Recommended Next Actions")
            push("")
            for i, a in enumerate(self.recommended_actions, 1):
                push(f"{i}. {a}")
            push("")

        if self.audit_trail:
            push("## Audit Trail")
            push("")
            for entry in self.audit_trail:
                push(f"- {entry}")
            push("")

        return "\n".join(lines)
