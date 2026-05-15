#!/usr/bin/env python3
"""
StrikeCore Contact Validator — Centralized phone/email validation and cross-validation.

Provides a single entry point for all contact validation in StrikeCore.
Wraps fp_filter for scoring and adds cross-validation logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.fp_filter import (
    validate_phone_number,
    validate_email_address,
    quick_score_phone,
    quick_score_email,
    log_rejection,
)


@dataclass
class ValidationResult:
    """Result of validating a single contact."""
    value: str
    contact_type: str  # "phone" or "email"
    valid: bool
    confidence: str  # CONFIRMED, PROBABLE, UNVERIFIED, REJECTED
    fp_score: int
    reasons: list[str] = field(default_factory=list)
    normalized: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def should_include(self) -> bool:
        return self.fp_score < 6

    @property
    def needs_review(self) -> bool:
        return 4 <= self.fp_score <= 5


@dataclass
class CrossValidationReport:
    """Report from cross-validating phones, emails, and names."""
    phones: list[ValidationResult] = field(default_factory=list)
    emails: list[ValidationResult] = field(default_factory=list)
    cross_links: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""

    @property
    def confirmed_phones(self) -> list[ValidationResult]:
        return [p for p in self.phones if p.confidence in ("CONFIRMED", "PROBABLE")]

    @property
    def confirmed_emails(self) -> list[ValidationResult]:
        return [e for e in self.emails if e.confidence in ("CONFIRMED", "PROBABLE")]


class ContactValidator:
    """Centralized contact validation for StrikeCore."""

    def __init__(self, target_name: str | None = None, expected_country: str = "IT"):
        self.target_name = target_name
        self.expected_country = expected_country
        self._target_keywords = target_name.lower().split() if target_name else []

    def validate_phone(
        self,
        number: str,
        sources: list[str] | None = None,
        require_mobile: bool = False,
    ) -> ValidationResult:
        """Validate a phone number structurally and score it."""
        sources = sources or ["unknown"]

        # Step 1: Structural validation
        struct = validate_phone_number(
            number,
            expected_country=self.expected_country,
            require_mobile=require_mobile,
        )

        if not struct["valid"]:
            result = ValidationResult(
                value=number,
                contact_type="phone",
                valid=False,
                confidence="REJECTED",
                fp_score=10,
                reasons=[f"Invalid: {struct.get('rejection_reason', 'unknown')}"],
                metadata=struct,
            )
            log_rejection("phone", number, 10, result.reasons)
            return result

        # Step 2: FP scoring
        fp = quick_score_phone(
            number=struct.get("e164", number),
            sources=sources,
            target_name=self.target_name,
            country=self.expected_country,
        )

        return ValidationResult(
            value=number,
            contact_type="phone",
            valid=True,
            confidence=fp["confidence"],
            fp_score=fp["score"],
            reasons=fp["reasons"],
            normalized=struct.get("e164"),
            metadata={
                "number_type": struct.get("number_type"),
                "carrier": struct.get("carrier"),
                "country": struct.get("country"),
            },
        )

    def validate_email(
        self,
        email: str,
        sources: list[str] | None = None,
        service_count: int = 0,
        from_github: bool = False,
        from_breach: bool = False,
    ) -> ValidationResult:
        """Validate an email structurally and score it."""
        sources = sources or ["unknown"]

        # Step 1: Structural validation
        struct = validate_email_address(email)

        if not struct["valid"]:
            result = ValidationResult(
                value=email,
                contact_type="email",
                valid=False,
                confidence="REJECTED",
                fp_score=10,
                reasons=[f"Invalid: {struct.get('rejection_reason', 'unknown')}"],
                metadata=struct,
            )
            log_rejection("email", email, 10, result.reasons)
            return result

        # Step 2: FP scoring
        fp = quick_score_email(
            email=struct.get("normalized", email),
            sources=sources,
            target_name=self.target_name,
            service_count=service_count,
            from_github=from_github,
            from_breach=from_breach,
        )

        return ValidationResult(
            value=email,
            contact_type="email",
            valid=True,
            confidence=fp["confidence"],
            fp_score=fp["score"],
            reasons=fp["reasons"],
            normalized=struct.get("normalized"),
            metadata={"has_mx": struct.get("has_mx")},
        )

    def cross_validate(
        self,
        phones: dict[str, dict],
        emails: dict[str, dict],
        names: list[str] | None = None,
    ) -> CrossValidationReport:
        """Cross-validate phones and emails — boost confidence when correlated.

        Args:
            phones: {number: {"sources": [...], "confidence": ...}}
            emails: {email: {"sources": [...], "confidence": ...}}
            names: list of names found associated with the target
        """
        report = CrossValidationReport()
        names = names or []
        name_lower = [n.lower() for n in names]

        # Validate all phones
        for number, info in phones.items():
            vr = self.validate_phone(number, sources=info.get("sources", []))
            report.phones.append(vr)

        # Validate all emails
        for email, info in emails.items():
            vr = self.validate_email(
                email,
                sources=info.get("sources", []),
                service_count=info.get("service_count", 0),
                from_github=info.get("from_github", False),
                from_breach=info.get("from_breach", False),
            )
            report.emails.append(vr)

        # Cross-link: find phones and emails that share sources
        for pvr in report.phones:
            for evr in report.emails:
                shared_sources = set(s.split(":")[0] for s in (pvr.reasons or [])) & \
                                 set(s.split(":")[0] for s in (evr.reasons or []))
                
                # Check if same source mentions both
                p_sources = set(phones.get(pvr.value, {}).get("sources", []))
                e_sources = set(emails.get(evr.value, {}).get("sources", []))
                shared = p_sources & e_sources
                
                if shared:
                    report.cross_links.append({
                        "phone": pvr.normalized or pvr.value,
                        "email": evr.normalized or evr.value,
                        "shared_sources": list(shared),
                        "boost": True,
                    })
                    # Boost confidence for both
                    pvr.fp_score = max(0, pvr.fp_score - 2)
                    pvr.reasons.append(f"-2 cross-validated with email {evr.value}")
                    evr.fp_score = max(0, evr.fp_score - 2)
                    evr.reasons.append(f"-2 cross-validated with phone {pvr.value}")
                    # Update confidence labels
                    pvr.confidence = _score_to_confidence(pvr.fp_score)
                    evr.confidence = _score_to_confidence(evr.fp_score)

        # Check name correlation
        if self._target_keywords:
            for name in name_lower:
                for kw in self._target_keywords:
                    if kw in name and len(kw) > 2:
                        # Name matches — boost all contacts from same source
                        for pvr in report.phones:
                            if pvr.fp_score > 0:
                                pvr.fp_score = max(0, pvr.fp_score - 1)
                                pvr.reasons.append(f"-1 target name '{kw}' found in associated names")
                                pvr.confidence = _score_to_confidence(pvr.fp_score)
                        break

        # Summary
        confirmed_p = len(report.confirmed_phones)
        confirmed_e = len(report.confirmed_emails)
        total_p = len(report.phones)
        total_e = len(report.emails)
        report.summary = (
            f"Cross-validation: {confirmed_p}/{total_p} phones, "
            f"{confirmed_e}/{total_e} emails passed. "
            f"{len(report.cross_links)} cross-link(s) found."
        )

        return report


def _score_to_confidence(score: int) -> str:
    if score >= 6:
        return "REJECTED"
    elif score >= 4:
        return "UNVERIFIED"
    elif score >= 2:
        return "PROBABLE"
    return "CONFIRMED"
