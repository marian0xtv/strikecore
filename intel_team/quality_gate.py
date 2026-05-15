"""Quality gate — military-grade filter applied to every specialist's findings.

Wraps the existing ``core/fp_filter.py`` (sophisticated 574-LOC FP-risk scorer,
phonenumbers validation, non-profile URL detection, Italian-specific patterns)
and adds the doctrinal rule from ``CLAUDE.md`` §2.4 / §3.7:

    *A finding cannot exceed 0.7 confidence without ≥2 independent sources.*

The gate runs *after* a specialist returns its ``AgentReport`` and *before*
the audit (red-cell) agent challenges it. Rejected findings are recorded in
``AgentReport.rejected`` for the audit trail — they are not silently dropped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from intel_team.types import AgentReport, Finding

logger = logging.getLogger("intel_team.quality_gate")


# ---------------------------------------------------------------------------
# Optional reuse of the existing FP filter (graceful degradation if absent)
# ---------------------------------------------------------------------------

try:
    from core.fp_filter import (  # type: ignore[import-not-found]
        GENERIC_USERNAMES,
        is_non_profile_url,
    )

    _HAVE_FP_FILTER = True
except ImportError:  # pragma: no cover -- fp_filter is core, but be defensive
    logger.warning("core.fp_filter not importable — quality gate runs in degraded mode")
    GENERIC_USERNAMES: frozenset[str] = frozenset()  # type: ignore[no-redef]

    def is_non_profile_url(url: str) -> tuple[bool, str | None]:  # type: ignore[no-redef]
        return (False, None)

    _HAVE_FP_FILTER = False


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


@dataclass
class _Verdict:
    accept: bool
    reason: str = ""
    confidence_cap: float | None = None  # if set, cap the finding's confidence here


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------


class QualityGate:
    """Enforces military-grade quality on findings.

    Public entry: :py:meth:`apply` mutates and returns the report.
    """

    # CLAUDE.md doctrine §2.4 + §3.7
    HIGH_CONFIDENCE_THRESHOLD: float = 0.7
    MIN_INDEPENDENT_SOURCES_FOR_HIGH: int = 2

    URL_TYPES: frozenset[str] = frozenset(
        {"profile_url", "social_url", "profile", "url", "social_profile"}
    )
    USERNAME_TYPES: frozenset[str] = frozenset({"username", "handle", "alias", "user"})

    def apply(self, report: AgentReport) -> AgentReport:
        """Filter findings, cap confidences, and refresh the confidence summary."""
        kept: list[Finding] = []
        rejected: list[dict[str, Any]] = list(report.rejected)

        for f in report.findings:
            verdict = self._evaluate(f)
            if not verdict.accept:
                rejected.append(
                    {
                        "type": f.finding_type,
                        "value": f.value,
                        "domain": f.domain.value,
                        "reason": verdict.reason,
                        "original_confidence": round(f.confidence, 2),
                    }
                )
                continue

            # Doctrinal confidence cap
            self._cap_confidence(f)
            # Specialist-supplied cap (e.g. URL passed, but only via single source)
            if verdict.confidence_cap is not None and f.confidence > verdict.confidence_cap:
                self._note(f, f"confidence capped at {verdict.confidence_cap} ({verdict.reason})")
                f.confidence = verdict.confidence_cap

            kept.append(f)

        report.findings = kept
        report.rejected = rejected
        report.confidence_summary = self._summarise(kept)
        return report

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _evaluate(self, f: Finding) -> _Verdict:
        # Empty / whitespace-only values
        if not f.value or not str(f.value).strip():
            return _Verdict(False, "empty value")

        # URL findings — reject platform-internal pages (XML namespaces, settings, …)
        if f.finding_type in self.URL_TYPES:
            is_non, why = is_non_profile_url(f.value)
            if is_non:
                return _Verdict(False, f"non-profile URL: {why or 'platform internal'}")

        # Generic usernames (admin, user, test, …) — cap, do not reject
        if f.finding_type in self.USERNAME_TYPES:
            handle = str(f.value).strip().lstrip("@").lower()
            if handle in GENERIC_USERNAMES:
                return _Verdict(True, "generic username (capped)", confidence_cap=0.3)

        return _Verdict(True)

    def _cap_confidence(self, f: Finding) -> None:
        """Enforce the ≥2-independent-source rule for >0.7 confidence."""
        if (
            f.confidence > self.HIGH_CONFIDENCE_THRESHOLD
            and f.independent_source_count < self.MIN_INDEPENDENT_SOURCES_FOR_HIGH
        ):
            old = f.confidence
            f.confidence = self.HIGH_CONFIDENCE_THRESHOLD
            self._note(
                f,
                f"confidence capped at 0.7 (was {old:.2f}); "
                f"only {f.independent_source_count} independent source(s)",
            )

    @staticmethod
    def _note(f: Finding, note: str) -> None:
        f.notes = f"{f.notes} | {note}".strip(" |") if f.notes else note

    @staticmethod
    def _summarise(findings: list[Finding]) -> dict[str, int]:
        summary: dict[str, int] = {
            "confirmed_>=0.9": 0,
            "probable_>=0.7": 0,
            "unverified_>=0.4": 0,
            "weak_<0.4": 0,
        }
        for f in findings:
            c = f.confidence
            if c >= 0.9:
                summary["confirmed_>=0.9"] += 1
            elif c >= 0.7:
                summary["probable_>=0.7"] += 1
            elif c >= 0.4:
                summary["unverified_>=0.4"] += 1
            else:
                summary["weak_<0.4"] += 1
        return summary
