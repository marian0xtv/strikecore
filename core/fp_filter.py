#!/usr/bin/env python3
"""
StrikeCore False Positive Filter v2 — Hardened FP scoring for findings.

Implements the FP risk scoring system (0-10 scale):
- Score >= 6: AUTO-REJECT (logged with reasoning)
- Score 4-5: FLAG as UNVERIFIED, requires analyst review
- Score 0-3: Include with appropriate confidence

v2 additions:
- phonenumbers (libphonenumbers) structural validation for phone numbers
- Italian FP blacklist patterns (P.IVA, CF, numeri verdi, centralini)
- Enhanced email scoring (MX check, service registration count, GitHub commits)
- Source-quality weighting (web scraping = low, breach DB = high, GitHub = highest)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# --- Phone validation via phonenumbers ---
try:
    import phonenumbers
    from phonenumbers import carrier as pn_carrier
    from phonenumbers import number_type as pn_number_type
    from phonenumbers import PhoneNumberType
    HAS_PHONENUMBERS = True
except ImportError:
    HAS_PHONENUMBERS = False
    logger.warning("phonenumbers library not available — phone validation degraded")

# --- Email validation ---
try:
    from email_validator import validate_email, EmailNotValidError
    HAS_EMAIL_VALIDATOR = True
except ImportError:
    HAS_EMAIL_VALIDATOR = False
    logger.warning("email-validator library not available — email validation degraded")


FP_LOG = Path.home() / ".strikecore" / "false_positives.log"

# Common/generic usernames that produce mass false positives
GENERIC_USERNAMES = frozenset({
    "admin", "user", "test", "info", "contact", "support", "help",
    "john", "jane", "guest", "root", "default", "webmaster", "mail",
    "user123", "admin123", "test123", "anonymous",
})

# Platform-internal URL paths that look like profiles but aren't.
# Catches XML namespaces, static pages, schema URIs, etc.
# (e.g. `facebook.com/2008/fbml` is the FBML XML namespace, not a profile.)
NON_PROFILE_URL_PATTERNS = (
    re.compile(r"^https?://(?:www\.)?facebook\.com/\d{4}(?:/|$)", re.I),  # year namespaces (/2008/, /2010/)
    re.compile(r"^https?://(?:www\.)?facebook\.com/(?:policies|help|business|developers|legal|about|ads|sharer|dialog|tr|plugins|connect|login|reg|recover|home\.php|index\.php)(?:/|\?|$)", re.I),
    re.compile(r"^https?://(?:www\.)?(?:twitter|x)\.com/(?:home|search|i|settings|tos|privacy|notifications|explore|about|login|signup|share|intent)(?:/|\?|$)", re.I),
    re.compile(r"^https?://(?:www\.)?instagram\.com/(?:accounts|developer|legal|p|reel|reels|explore|directory|about|tv|stories|web)(?:/|\?|$)", re.I),
    re.compile(r"^https?://(?:www\.)?github\.com/(?:settings|notifications|pulls|issues|marketplace|topics|trending|features|pricing|about|login|join|search|new)(?:/|\?|$)", re.I),
    re.compile(r"^https?://(?:[a-z]+\.)?linkedin\.com/(?:legal|help|company|jobs|learning|feed|mynetwork|messaging|notifications|premium)(?:/|\?|$)", re.I),
    re.compile(r"^https?://(?:www\.)?youtube\.com/(?:about|watch|results|feed|gaming|premium|tv|kids)(?:/|\?|$)", re.I),
    re.compile(r"^https?://(?:www\.)?tiktok\.com/(?:about|legal|tag|discover|search|trending)(?:/|\?|$)", re.I),
    # XML/schema markers anywhere in the path
    re.compile(r"/(?:fbml|xmlns|schema|ns)(?:/|$)", re.I),
)


def is_non_profile_url(url: str) -> tuple[bool, str | None]:
    """True if URL points to a platform-internal page / namespace, not a real user profile.

    Returns (is_non_profile, reason_or_None).
    """
    if not url or not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False, None
    for pat in NON_PROFILE_URL_PATTERNS:
        if pat.search(url):
            return True, f"matches non-profile URL pattern: {pat.pattern[:80]}"
    return False, None

# Common email domains that suggest disposable/test accounts
DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "tempmail.com", "throwaway.email",
    "yopmail.com", "sharklasers.com", "grr.la", "10minutemail.com",
    "temp-mail.org", "guerrillamailblock.com", "maildrop.cc",
})

# Italian FP patterns — numbers that look like phones but are NOT
ITALIAN_FP_PATTERNS = [
    re.compile(r"^\+?39\d{11}$"),                  # P.IVA (11 cifre dopo prefisso)
    re.compile(r"^\d{16}$"),                         # Codice fiscale numerico
    re.compile(r"^\+?39\s?800\d{6}$"),             # Numeri verdi
    re.compile(r"^\+?39\s?199\d{6}$"),             # Numeri a pagamento 199
    re.compile(r"^\+?39\s?892\d{3}$"),             # Numeri a pagamento 892
    re.compile(r"^\+?39\s?803\d{3}$"),             # Assistenza (803xxx)
    re.compile(r"^\+?39\s?840\d{6}$"),             # Numeri a costo condiviso
    re.compile(r"^\+?39\s?848\d{6}$"),             # Numeri a costo condiviso
    re.compile(r"^1\d{2}$"),                         # Short emergency codes (112, 113, etc.)
]

# Known test/example phone numbers
TEST_NUMBERS = frozenset({
    "3401234567", "3999999999", "1234567890", "0000000000",
    "3331234567", "3491234567", "1111111111", "9999999999",
    "+393401234567", "+391234567890",
})

# High-confidence sources (reduce FP score)
HIGH_CONFIDENCE_SOURCES = frozenset({
    "github_commit", "breach_db", "h8mail_breach", "truecaller_verified",
    "truecaller", "holehe", "emailrep",
})

# Low-confidence sources (increase FP score)
LOW_CONFIDENCE_SOURCES = frozenset({
    "google_dork", "google_dork_name", "google_dork_+39", "duckduckgo",
    "web_scraping", "paginebianche", "generic_regex",
})


# ═══════════════════════════════════════════════════════════════
# Phone Validation
# ═══════════════════════════════════════════════════════════════

def validate_phone_number(
    number: str,
    expected_country: str = "IT",
    require_mobile: bool = False,
) -> dict[str, Any]:
    """Validate a phone number using libphonenumbers.
    
    Returns:
        dict with: valid, number_type, carrier, country, e164, rejection_reason
    """
    result = {
        "valid": False,
        "number_type": "unknown",
        "carrier": None,
        "country": None,
        "e164": None,
        "rejection_reason": None,
    }
    
    clean = re.sub(r"[\s\-\.\(\)]", "", number)
    
    # Check Italian FP patterns first
    for pattern in ITALIAN_FP_PATTERNS:
        if pattern.match(clean):
            result["rejection_reason"] = f"matches Italian FP pattern: {pattern.pattern}"
            return result
    
    # Check test numbers
    clean_digits = re.sub(r"\D", "", clean)
    if clean_digits in TEST_NUMBERS or clean in TEST_NUMBERS:
        result["rejection_reason"] = "known test/example number"
        return result
    
    # Too short
    if len(clean_digits) < 10:
        result["rejection_reason"] = f"too short ({len(clean_digits)} digits, need >= 10)"
        return result
    
    if not HAS_PHONENUMBERS:
        # Fallback: basic format check
        if re.match(r"^\+?\d{10,15}$", clean):
            result["valid"] = True
            result["e164"] = clean if clean.startswith("+") else f"+39{clean}"
        else:
            result["rejection_reason"] = "invalid format (no phonenumbers library)"
        return result
    
    # Full validation with phonenumbers
    try:
        parsed = phonenumbers.parse(clean, expected_country)
    except phonenumbers.NumberParseException as e:
        result["rejection_reason"] = f"parse error: {e}"
        return result
    
    if not phonenumbers.is_valid_number(parsed):
        result["rejection_reason"] = "not a valid number (libphonenumbers)"
        return result
    
    # Valid number — extract metadata
    result["valid"] = True
    result["e164"] = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    
    # Number type
    ntype = phonenumbers.number_type(parsed)
    type_map = {
        PhoneNumberType.MOBILE: "mobile",
        PhoneNumberType.FIXED_LINE: "fixed_line",
        PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_or_mobile",
        PhoneNumberType.VOIP: "voip",
        PhoneNumberType.TOLL_FREE: "toll_free",
        PhoneNumberType.PREMIUM_RATE: "premium_rate",
        PhoneNumberType.SHARED_COST: "shared_cost",
        PhoneNumberType.PERSONAL_NUMBER: "personal",
    }
    result["number_type"] = type_map.get(ntype, "unknown")
    
    # Reject toll-free and premium
    if ntype in (PhoneNumberType.TOLL_FREE, PhoneNumberType.PREMIUM_RATE, PhoneNumberType.SHARED_COST):
        result["valid"] = False
        result["rejection_reason"] = f"non-personal number type: {result['number_type']}"
        return result
    
    # Reject fixed line if mobile required
    if require_mobile and ntype == PhoneNumberType.FIXED_LINE:
        result["valid"] = False
        result["rejection_reason"] = "fixed line, but mobile required"
        return result
    
    # Country check
    country_code = phonenumbers.region_code_for_number(parsed)
    result["country"] = country_code
    if expected_country and country_code != expected_country:
        # Don't reject, but flag
        result["country_mismatch"] = True
    
    # Carrier
    try:
        result["carrier"] = pn_carrier.name_for_number(parsed, "en")
    except Exception:
        pass
    
    return result


# ═══════════════════════════════════════════════════════════════
# Email Validation  
# ═══════════════════════════════════════════════════════════════

def validate_email_address(email: str) -> dict[str, Any]:
    """Validate email syntax and DNS MX record.
    
    Returns:
        dict with: valid, has_mx, normalized, rejection_reason
    """
    result = {
        "valid": False,
        "has_mx": False,
        "normalized": None,
        "rejection_reason": None,
    }
    
    if not email or "@" not in email:
        result["rejection_reason"] = "not an email address"
        return result
    
    domain = email.split("@")[-1].lower()
    
    # Check disposable
    if domain in DISPOSABLE_DOMAINS:
        result["rejection_reason"] = f"disposable domain: {domain}"
        return result
    
    if not HAS_EMAIL_VALIDATOR:
        # Basic fallback
        if re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
            result["valid"] = True
            result["normalized"] = email.lower().strip()
        else:
            result["rejection_reason"] = "invalid format"
        return result
    
    try:
        info = validate_email(email, check_deliverability=True)
        result["valid"] = True
        result["has_mx"] = True
        result["normalized"] = info.normalized
    except EmailNotValidError as e:
        # Try without deliverability check (DNS may be slow/blocked)
        try:
            info = validate_email(email, check_deliverability=False)
            result["valid"] = True
            result["has_mx"] = False  # Could not verify MX
            result["normalized"] = info.normalized
        except EmailNotValidError:
            result["rejection_reason"] = f"invalid email: {e}"
    
    return result


# ═══════════════════════════════════════════════════════════════
# FP Risk Scoring
# ═══════════════════════════════════════════════════════════════

def calculate_fp_risk(
    finding_type: str,
    value: str,
    sources: list[str],
    target_keywords: list[str] | None = None,
    is_corroborated: bool = False,
    account_age_days: int | None = None,
    has_activity: bool = True,
    has_profile_photo: bool = True,
    bio_match: bool = False,
    service_count: int = 0,
    from_github_commit: bool = False,
    from_breach_db: bool = False,
    expected_country: str = "IT",
) -> dict[str, Any]:
    """Calculate FP risk score (0-10) for a finding.

    Returns dict with:
        score: int 0-10 (higher = more likely false positive)
        confidence: str CONFIRMED|PROBABLE|UNVERIFIED|REJECTED
        reasons: list[str] explaining score components
        action: str "include"|"flag"|"reject"
        validation: dict with structural validation details (phone/email)
    """
    score = 0
    reasons = []
    validation = {}

    # --- Source quality assessment ---
    high_conf_sources = [s for s in sources if any(h in s.lower() for h in HIGH_CONFIDENCE_SOURCES)]
    low_conf_sources = [s for s in sources if any(l in s.lower() for l in LOW_CONFIDENCE_SOURCES)]
    
    if len(sources) <= 1:
        if low_conf_sources:
            score += 4
            reasons.append("+4 single low-confidence source (web scraping)")
        else:
            score += 3
            reasons.append("+3 single source, no corroboration")
    elif not is_corroborated:
        score += 2
        reasons.append("+2 multiple sources but not independently corroborated")

    # --- Type-specific factors ---
    if finding_type == "phone":
        # Structural validation
        phone_val = validate_phone_number(value, expected_country=expected_country)
        validation = phone_val
        
        if not phone_val["valid"]:
            score += 5
            reasons.append(f"+5 structurally invalid phone: {phone_val.get('rejection_reason', 'unknown')}")
        else:
            # Valid phone — apply type-based scoring
            ntype = phone_val.get("number_type", "unknown")
            if ntype == "mobile":
                score -= 1
                reasons.append("-1 valid mobile number")
            elif ntype == "fixed_line":
                score += 1
                reasons.append("+1 fixed line (less likely personal contact)")
            elif ntype == "voip":
                score += 2
                reasons.append("+2 VoIP number (possibly disposable)")
            
            if phone_val.get("country_mismatch"):
                score += 2
                reasons.append(f"+2 country mismatch (expected {expected_country}, got {phone_val.get('country')})")
        
        # Name correlation
        if target_keywords:
            # Check if any source mentions the target name alongside this phone
            name_in_source = any(
                any(kw.lower() in s.lower() for kw in target_keywords if len(kw) > 2)
                for s in sources
            )
            if name_in_source:
                score -= 2
                reasons.append("-2 phone associated with target name in source")

    elif finding_type == "email":
        # Structural validation
        email_val = validate_email_address(value)
        validation = email_val
        
        if not email_val["valid"]:
            score += 5
            reasons.append(f"+5 structurally invalid email: {email_val.get('rejection_reason', 'unknown')}")
        else:
            if not email_val.get("has_mx"):
                score += 3
                reasons.append("+3 no valid MX record for domain")
        
        domain = value.split("@")[-1].lower() if "@" in value else ""
        if domain in DISPOSABLE_DOMAINS:
            score += 3
            reasons.append("+3 disposable email domain")

        if target_keywords and not any(kw in value.lower() for kw in target_keywords if len(kw) > 2):
            score += 2
            reasons.append("+2 email doesn't contain target name")
        
        # Service registration count (from Holehe etc.)
        if service_count == 0:
            score += 2
            reasons.append("+2 email not registered on any known service")
        elif service_count >= 3:
            score -= 2
            reasons.append(f"-2 email registered on {service_count} services")
        elif service_count >= 1:
            score -= 1
            reasons.append(f"-1 email registered on {service_count} service(s)")
        
        # GitHub commit = highest confidence email source
        if from_github_commit:
            score -= 3
            reasons.append("-3 email found in GitHub commits (high confidence)")
        
        # Breach DB
        if from_breach_db:
            score -= 2
            reasons.append("-2 email found in breach database (confirms existence)")

    elif finding_type == "username" or finding_type == "profile":
        # Hard reject: platform-internal URLs (FB namespaces, static pages, schemas, ...)
        non_profile, np_reason = is_non_profile_url(value)
        if non_profile:
            score += 8
            reasons.append(f"+8 not a profile: {np_reason}")
            validation = {"valid": False, "rejection_reason": np_reason}

        val_lower = value.lower().split("/")[-1].split("@")[-1]

        if val_lower in GENERIC_USERNAMES:
            score += 2
            reasons.append("+2 generic/common username")

        if account_age_days is not None and account_age_days < 30:
            score += 2
            reasons.append("+2 account < 30 days old (possible fake)")

        if not has_activity:
            score += 1
            reasons.append("+1 zero post/activity history")

        if not has_profile_photo:
            score += 1
            reasons.append("+1 no profile photo (stock/default avatar)")

        if target_keywords and not any(kw in val_lower for kw in target_keywords if len(kw) > 2):
            score += 1
            reasons.append("+1 username doesn't contain target keywords")

    # --- Bonuses (reduce score) ---
    if is_corroborated and len(sources) >= 2:
        bonus = min(len(sources) - 1, 3) * -1
        score += bonus
        reasons.append(f"{bonus} corroborated across {len(sources)} sources")
    
    if high_conf_sources:
        bonus = min(len(high_conf_sources), 2) * -1
        score += bonus
        reasons.append(f"{bonus} has {len(high_conf_sources)} high-confidence source(s)")

    if bio_match:
        score -= 2
        reasons.append("-2 bio/description matches target attributes")

    # --- Clamp ---
    score = max(0, min(10, score))

    # --- Determine action ---
    if score >= 6:
        action = "reject"
        confidence = "REJECTED"
    elif score >= 4:
        action = "flag"
        confidence = "UNVERIFIED"
    elif score >= 2:
        action = "include"
        confidence = "PROBABLE"
    else:
        action = "include"
        confidence = "CONFIRMED"

    return {
        "score": score,
        "confidence": confidence,
        "reasons": reasons,
        "action": action,
        "analyst_review_required": action == "flag",
        "validation": validation,
    }


def log_rejection(finding_type: str, value: str, score: int, reasons: list[str]):
    """Append rejected finding to false_positives.log with reasoning."""
    FP_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = (
        f"[{datetime.now().isoformat()}] REJECTED (score={score}) "
        f"type={finding_type} value={value} reasons={'; '.join(reasons)}\n"
    )
    with open(FP_LOG, "a") as f:
        f.write(entry)


def score_finding(finding: dict, target_baseline: dict | None = None) -> dict:
    """Score a finding dict and return it with FP metadata added.

    Args:
        finding: dict with keys: type, value, sources, [extras]
        target_baseline: dict with target_keywords, known_names, expected_country, etc.

    Returns:
        The finding dict with added keys: fp_score, fp_confidence, fp_action, fp_reasons, fp_validation
    """
    baseline = target_baseline or {}
    keywords = baseline.get("target_keywords", [])
    expected_country = baseline.get("expected_country", "IT")

    result = calculate_fp_risk(
        finding_type=finding.get("type", "unknown"),
        value=finding.get("value", ""),
        sources=finding.get("sources", []),
        target_keywords=keywords,
        is_corroborated=finding.get("corroborated", False),
        account_age_days=finding.get("account_age_days"),
        has_activity=finding.get("has_activity", True),
        has_profile_photo=finding.get("has_profile_photo", True),
        bio_match=finding.get("bio_match", False),
        service_count=finding.get("service_count", 0),
        from_github_commit=finding.get("from_github_commit", False),
        from_breach_db=finding.get("from_breach_db", False),
        expected_country=expected_country,
    )

    finding["fp_score"] = result["score"]
    finding["fp_confidence"] = result["confidence"]
    finding["fp_action"] = result["action"]
    finding["fp_reasons"] = result["reasons"]
    finding["fp_validation"] = result.get("validation", {})

    if result["action"] == "reject":
        log_rejection(
            finding.get("type", "unknown"),
            finding.get("value", ""),
            result["score"],
            result["reasons"],
        )

    return finding


# ═══════════════════════════════════════════════════════════════
# Convenience helpers for bin/ scripts
# ═══════════════════════════════════════════════════════════════

def quick_score_phone(number: str, sources: list[str], target_name: str | None = None, country: str = "IT") -> dict:
    """Quick phone scoring for use in bin/ scripts. Returns full result dict."""
    keywords = target_name.lower().split() if target_name else []
    return calculate_fp_risk(
        finding_type="phone",
        value=number,
        sources=sources,
        target_keywords=keywords,
        expected_country=country,
    )

def quick_score_email(
    email: str, sources: list[str], target_name: str | None = None,
    service_count: int = 0, from_github: bool = False, from_breach: bool = False,
) -> dict:
    """Quick email scoring for use in bin/ scripts. Returns full result dict."""
    keywords = target_name.lower().split() if target_name else []
    return calculate_fp_risk(
        finding_type="email",
        value=email,
        sources=sources,
        target_keywords=keywords,
        service_count=service_count,
        from_github_commit=from_github,
        from_breach_db=from_breach,
    )
