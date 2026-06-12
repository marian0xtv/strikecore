"""Hephaestus discovery — GitHub OSINT-tool search + Admiralty scoring.

Live mode queries the GitHub REST search API (public, unauthenticated) over
urllib (stdlib). Dry-run mode returns an offline fixture set so verification is
reproducible and never touches the network. Either way, each candidate is scored
with a NATO Admiralty reliability (A–F) + credibility (1–6) from quality
signals (stars, recency, language).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

# Offline fixtures per StrikeCore gap category (for --dry-run / no-network).
_FIXTURES: dict[str, list[dict]] = {
    "document": [
        {"name": "py-pdf/pypdf", "url": "https://github.com/py-pdf/pypdf",
         "stars": 8200, "language": "Python", "pushed_at": "2026-05-20"},
        {"name": "jsvine/pdfplumber", "url": "https://github.com/jsvine/pdfplumber",
         "stars": 6400, "language": "Python", "pushed_at": "2026-04-11"},
        {"name": "ocrmypdf/OCRmyPDF", "url": "https://github.com/ocrmypdf/OCRmyPDF",
         "stars": 14000, "language": "Python", "pushed_at": "2026-05-31"},
    ],
    "threatint": [
        {"name": "InQuest/python-iocextract", "url": "https://github.com/InQuest/python-iocextract",
         "stars": 520, "language": "Python", "pushed_at": "2026-03-02"},
        {"name": "abuse-ch/urlhaus", "url": "https://github.com/abuse-ch/urlhaus-api",
         "stars": 210, "language": "Python", "pushed_at": "2026-05-10"},
    ],
    "italian-specific": [
        {"name": "lcorbasson/codicefiscale", "url": "https://github.com/lcorbasson/codicefiscale",
         "stars": 95, "language": "Python", "pushed_at": "2025-11-01"},
    ],
}
_GENERIC_FIXTURE = [
    {"name": "sherlock-project/sherlock", "url": "https://github.com/sherlock-project/sherlock",
     "stars": 60000, "language": "Python", "pushed_at": "2026-06-01"},
]


def admiralty_score(cand: dict) -> tuple[str, int, str]:
    """Map quality signals -> (reliability A-F, credibility 1-6, one-line signal)."""
    stars = int(cand.get("stars", 0) or 0)
    pushed = str(cand.get("pushed_at", ""))[:10]
    recent = pushed >= "2026-01-01"  # string compare on ISO date
    if stars >= 5000 and recent:
        rel, cred = "B", 2
    elif stars >= 1000 and recent:
        rel, cred = "C", 3
    elif stars >= 200:
        rel, cred = "C", 4
    else:
        rel, cred = "D", 4
    signal = f"{stars}* lang={cand.get('language','?')} pushed={pushed or '?'}" \
             f" {'recent' if recent else 'stale'}"
    return rel, cred, signal


def _to_candidate(raw: dict) -> dict:
    rel, cred, signal = admiralty_score(raw)
    return {
        "name": raw["name"], "url": raw["url"],
        "stars": int(raw.get("stars", 0) or 0),
        "language": str(raw.get("language") or ""),
        "pushed_at": str(raw.get("pushed_at") or "")[:10],
        "reliability": rel, "confidence": cred, "signal": signal,
    }


def _github_live(topic: str, limit: int) -> list[dict]:
    q = urllib.parse.quote(f"{topic} osint")
    url = (f"https://api.github.com/search/repositories?q={q}"
           f"&sort=stars&order=desc&per_page={limit}")
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "strikecore-hephaestus",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (public API)
        data = json.loads(resp.read().decode("utf-8"))
    out = []
    for item in data.get("items", [])[:limit]:
        out.append({
            "name": item.get("full_name", ""),
            "url": item.get("html_url", ""),
            "stars": item.get("stargazers_count", 0),
            "language": item.get("language") or "",
            "pushed_at": (item.get("pushed_at") or "")[:10],
        })
    return out


def discover(focus_category: str, limit: int = 5, dry_run: bool = False) -> list[dict]:
    """Return scored candidate tools for a focus category."""
    if dry_run:
        raw = _FIXTURES.get(focus_category, _GENERIC_FIXTURE)[:limit]
    else:
        try:
            raw = _github_live(focus_category, limit)
        except Exception:  # network/ratelimit failure -> fall back to fixtures
            raw = _FIXTURES.get(focus_category, _GENERIC_FIXTURE)[:limit]
    return [_to_candidate(r) for r in raw]
