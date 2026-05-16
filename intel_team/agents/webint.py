"""WEBINT specialist — exposed-data, breach, archives, dorking, document forensics.

Domain coverage (CLAUDE.md §5 WEBINT/RECON + §2.3 asymmetric tradecraft):

* Breach corpora correlation (h8mail, DeHashed, IntelX, HIBP — distinct upstreams)
* Wayback / archive.today / Google cache historical diffs
* Search-engine dorking (Google / Bing / DuckDuckGo: ``site:``, ``intitle:``, ``ext:``)
* Document forensics (exiftool on PDF/DOCX/JPG — author, revision history, embedded thumbnails)
* Certificate Transparency (crt.sh → SAN names → forgotten subdomains)
* Code-repo archaeology (GitHub event API for force-pushed secrets, gists tied to email)
* Italian-specific: paginebianche.it, registroimprese.it, infocamere.it, ANSA archive, comune Albo Pretorio

The specialist operates over **pre-collected tool output** — it does not run
the tools. It applies WEBINT tradecraft to surface defensible findings.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from intel_team.agents.base import AgentConfig, BaseSpecialist
from intel_team.types import Domain

logger = logging.getLogger("intel_team.agents.webint")


class WEBINTSpecialist(BaseSpecialist):
    """Web / open-data intelligence specialist."""

    config = AgentConfig(
        name="webint_specialist",
        domain=Domain.WEBINT,
        system_prompt_file="webint.md",
        allowed_tool_categories=["webint", "recon"],
        model_tier="specialist",
        max_tokens=6000,
        temperature=0.15,
    )

    # Finding types this specialist may emit. ``other`` accepts anything the
    # LLM produces that isn't in the explicit list (rather than rejecting it).
    _ALLOWED_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "email",
            "breach_record",
            "leaked_password_hash",
            "credential_pair",
            "document",
            "document_author",
            "document_revision",
            "domain",
            "subdomain",
            "cert_san",
            "archived_url",
            "wayback_snapshot",
            "google_dork_hit",
            "github_commit",
            "github_gist",
            "exposed_endpoint",
            "registry_record",   # registroimprese / infocamere
            "ansa_article",
            "comune_albo_pretorio",
            "paginebianche_entry",
            "exif_author",
            "other",
        }
    )

    # _FORBIDDEN_TYPES inherited (forbids phone — phones come only from
    # phone-specific tools per CLAUDE.md §3.4)
