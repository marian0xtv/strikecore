"""StrikeCore Intel Team — embedded multi-agent intelligence orchestration.

A Palantir-Maven-style intelligence team that operates inside StrikeCore,
inspired by gstack's skill-chaining pattern. Components:

- ``pir_router``  classifies operator intent into intelligence domains
- ``agents/*``    domain specialists (SOCINT first; GEOINT/TECHINT/etc. extensible)
- ``agents/audit``    red cell / devil's advocate
- ``agents/analyst``  Opus-tier synthesiser (ACH + Key Assumptions Check)
- ``quality_gate``    wraps ``core.fp_filter`` and enforces the ≥2-source rule
                      for confidence > 0.7 (per CLAUDE.md doctrine §2.4 & §3.7)
- ``orchestrator``    end-to-end pipeline: PIR → dispatch → audit → analyst → dossier

Public entry point: ``IntelTeam(router, store).investigate(pir)`` → ``Dossier``.
"""

from intel_team.types import (
    AgentReport,
    Credibility,
    Domain,
    Dossier,
    Finding,
    PIR,
    Reliability,
    Source,
)
from intel_team.orchestrator import IntelTeam
from intel_team.quality_gate import QualityGate

__all__ = [
    "AgentReport",
    "Credibility",
    "Domain",
    "Dossier",
    "Finding",
    "IntelTeam",
    "PIR",
    "QualityGate",
    "Reliability",
    "Source",
]
