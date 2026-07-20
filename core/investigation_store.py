#!/usr/bin/env python3
"""
StrikeCore Investigation Store — Persistent intelligence database.

Stores all findings per target in a JSON file that persists across sessions.
Prevents contradictions, accumulates intelligence, and feeds context to the AI.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

STORE_DIR = Path.home() / "strikecore-data" / "investigations"


class InvestigationStoreUnavailable(RuntimeError):
    """Raised when the Postgres-backed investigation store can't be reached.

    Distinct from a generic AI/provider error so callers (and the shell's
    catch-all handler) can tell a DB outage apart from an LLM failure instead
    of both surfacing as an indistinguishable "AI error: ...".
    """


# ---------------------------------------------------------------------------
# Confidence scoring system
# ---------------------------------------------------------------------------

class ConfidenceScore:
    """Numeric 0.0-1.0 confidence with false-positive risk calculation.

    FP risk factors are additive penalties (higher = more suspicious).
    Bonuses reduce risk when corroborated by multiple sources.
    """

    # Penalties
    FP_SINGLE_SOURCE = 0.3
    FP_NO_CORROBORATION = 0.3
    FP_GENERIC_IDENTIFIER = 0.2
    FP_COMMON_NAME = 0.15
    FP_STALE_DATA = 0.1

    # Bonuses (negative = reduces FP risk)
    CROSS_SOURCE_BONUS = -0.2   # per additional corroborating source
    DIRECT_VERIFY_BONUS = -0.3  # e.g. GitHub commit = real email

    @staticmethod
    def calculate(
        sources_count: int = 1,
        corroborated: bool = False,
        is_generic: bool = False,
        is_common_name: bool = False,
        is_stale: bool = False,
        directly_verified: bool = False,
    ) -> float:
        """Return confidence 0.0-1.0 (higher = more confident)."""
        fp_risk = 0.0
        if sources_count <= 1:
            fp_risk += ConfidenceScore.FP_SINGLE_SOURCE
        if not corroborated:
            fp_risk += ConfidenceScore.FP_NO_CORROBORATION
        if is_generic:
            fp_risk += ConfidenceScore.FP_GENERIC_IDENTIFIER
        if is_common_name:
            fp_risk += ConfidenceScore.FP_COMMON_NAME
        if is_stale:
            fp_risk += ConfidenceScore.FP_STALE_DATA
        # Bonuses
        if sources_count > 1:
            fp_risk += ConfidenceScore.CROSS_SOURCE_BONUS * (sources_count - 1)
        if directly_verified:
            fp_risk += ConfidenceScore.DIRECT_VERIFY_BONUS
        return round(max(0.0, min(1.0, 1.0 - fp_risk)), 2)

    @staticmethod
    def to_legacy(score: float) -> str:
        """Convert numeric score to legacy tier string."""
        if score >= 0.8:
            return "CONFIRMED"
        if score >= 0.4:
            return "PROBABLE"
        return "UNVERIFIED"

    @staticmethod
    def from_legacy(tier: str) -> float:
        """Convert legacy tier string to default numeric score."""
        return {"CONFIRMED": 0.9, "PROBABLE": 0.6, "UNVERIFIED": 0.2}.get(
            tier.upper() if isinstance(tier, str) else "", 0.2
        )

    @staticmethod
    def cap_doctrine(score: float, sources_count: int) -> float:
        """CLAUDE.md §2.4: a finding cannot exceed 0.7 without ≥2 independent sources."""
        if sources_count < 2 and score > 0.7:
            return 0.7
        return score


class InvestigationStore:
    """Persistent per-target intelligence database."""

    def __init__(self, target_id: str):
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        self.target_id = target_id.lower().replace(" ", "_")
        self.path = STORE_DIR / f"{self.target_id}.json"
        self.data = self._load()

    def _load(self) -> dict:
        # Postgres is the authoritative store (JSONB swap). The nested document
        # shape is unchanged — it lives intact in the `investigation.data` JSONB
        # column, so all ~20 methods below and their 18 consumers are untouched.
        from core import pg
        try:
            with pg.cursor() as cur:
                cur.execute("SELECT data FROM investigation WHERE target_id = %s", (self.target_id,))
                row = cur.fetchone()
        except Exception as exc:  # noqa: BLE001 — Postgres is the authoritative store, not best-effort
            raise InvestigationStoreUnavailable(
                f"investigation store (Postgres) unreachable while loading '{self.target_id}': {exc}"
            ) from exc
        if row and row.get("data") is not None:
            return row["data"]
        return {
            "target_id": self.target_id,
            "created": datetime.now().isoformat(),
            "updated": datetime.now().isoformat(),
            "identity": {"names": [], "usernames": [], "dob": None, "gender": None, "nationality": None},
            "emails": {},       # email -> {sources: [], confidence, first_seen, notes}
            "phones": {},       # phone -> {sources: [], confidence, carrier, location}
            "profiles": {},     # platform -> {url, confidence, notes, verified_at}
            "organizations": {},# name -> {role, period, source}
            "locations": [],    # [{name, source, confidence}]
            "social_graph": [], # [{name, relation, platform, url}]
            "breaches": [],     # [{breach_name, data_types, date, source}]
            "documents": [],    # [{filename, content_hash, summary, uploaded_at}]
            "timeline": [],     # [{date, event, source}]
            "devices": [],      # [{device, source}]
            "notes": [],        # [{text, author, timestamp}]
            "raw_evidence": {}, # tool_name -> [{timestamp, output_snippet}]  
            "phase_log": [],    # [{phase, timestamp, tools_used, findings_count}]
        }

    def save(self):
        self.data["updated"] = datetime.now().isoformat()
        from core import pg
        from psycopg2.extras import Json
        # Round-trip through json(default=str) so non-JSON types (datetime etc.)
        # serialise exactly as the legacy file store did before hitting JSONB.
        payload = json.loads(json.dumps(self.data, default=str))
        try:
            with pg.cursor() as cur:
                cur.execute(
                    "INSERT INTO investigation (target_id, data, updated) "
                    "VALUES (%s, %s, NOW()) "
                    "ON CONFLICT (target_id) DO UPDATE SET data = EXCLUDED.data, updated = NOW()",
                    (self.target_id, Json(payload)),
                )
        except Exception as exc:  # noqa: BLE001 — Postgres is the authoritative store, not best-effort
            raise InvestigationStoreUnavailable(
                f"investigation store (Postgres) unreachable while saving '{self.target_id}': {exc}"
            ) from exc

    # ── Adders (accumulate, never overwrite) ──

    def add_name(self, name: str):
        if name and name not in self.data["identity"]["names"]:
            self.data["identity"]["names"].append(name)
            self.save()

    def add_username(self, username: str):
        if username and username not in self.data["identity"]["usernames"]:
            self.data["identity"]["usernames"].append(username)
            self.save()

    def add_email(self, email: str, source: str, confidence: Any = "PROBABLE", notes: str = ""):
        email = email.lower().strip()
        if not email or "@" not in email or "noreply" in email:
            return
        # Resolve numeric vs legacy confidence
        if isinstance(confidence, (int, float)):
            score = float(confidence)
            tier = ConfidenceScore.to_legacy(score)
        else:
            tier = str(confidence)
            score = ConfidenceScore.from_legacy(tier)
        if email not in self.data["emails"]:
            # Doctrine §2.4: cap single-source assertions at 0.7
            capped = ConfidenceScore.cap_doctrine(score, sources_count=1)
            self.data["emails"][email] = {
                "sources": [source],
                "confidence": ConfidenceScore.to_legacy(capped),
                "confidence_score": capped,
                "first_seen": datetime.now().isoformat(), "notes": notes
            }
        else:
            if source not in self.data["emails"][email]["sources"]:
                self.data["emails"][email]["sources"].append(source)
            # Recalculate confidence based on accumulated sources
            sources = self.data["emails"][email]["sources"]
            new_score = ConfidenceScore.calculate(
                sources_count=len(sources), corroborated=len(sources) >= 2
            )
            # Never downgrade — keep the higher score
            old_score = self.data["emails"][email].get("confidence_score", 0.0)
            if new_score > old_score:
                self.data["emails"][email]["confidence_score"] = new_score
                self.data["emails"][email]["confidence"] = ConfidenceScore.to_legacy(new_score)
            if tier == "CONFIRMED":
                # Only honour CONFIRMED if doctrine threshold met
                target_score = ConfidenceScore.cap_doctrine(0.9, sources_count=len(sources))
                if target_score > old_score:
                    self.data["emails"][email]["confidence_score"] = target_score
                    self.data["emails"][email]["confidence"] = ConfidenceScore.to_legacy(target_score)
        self.save()

    def add_phone(self, phone: str, source: str, confidence: Any = "PROBABLE",
                  carrier: str = "", location: str = ""):
        import re
        phone = re.sub(r'[\s\-\(\)\.]', '', phone)
        if not phone or len(phone) < 10:
            return
        if isinstance(confidence, (int, float)):
            score = float(confidence)
            tier = ConfidenceScore.to_legacy(score)
        else:
            tier = str(confidence)
            score = ConfidenceScore.from_legacy(tier)
        if phone not in self.data["phones"]:
            # Doctrine §2.4: cap single-source assertions at 0.7
            capped = ConfidenceScore.cap_doctrine(score, sources_count=1)
            self.data["phones"][phone] = {
                "sources": [source],
                "confidence": ConfidenceScore.to_legacy(capped),
                "confidence_score": capped,
                "carrier": carrier, "location": location,
                "first_seen": datetime.now().isoformat()
            }
        else:
            if source not in self.data["phones"][phone]["sources"]:
                self.data["phones"][phone]["sources"].append(source)
            sources = self.data["phones"][phone]["sources"]
            new_score = ConfidenceScore.calculate(
                sources_count=len(sources), corroborated=len(sources) >= 2
            )
            old_score = self.data["phones"][phone].get("confidence_score", 0.0)
            if new_score > old_score:
                self.data["phones"][phone]["confidence_score"] = new_score
                self.data["phones"][phone]["confidence"] = ConfidenceScore.to_legacy(new_score)
            if tier == "CONFIRMED":
                target_score = ConfidenceScore.cap_doctrine(0.9, sources_count=len(sources))
                if target_score > old_score:
                    self.data["phones"][phone]["confidence_score"] = target_score
                    self.data["phones"][phone]["confidence"] = ConfidenceScore.to_legacy(target_score)
            if carrier:
                self.data["phones"][phone]["carrier"] = carrier
        self.save()

    def add_profile(self, platform: str, url: str, confidence: Any = "CONFIRMED",
                    notes: str = "", *, source: str | None = None):
        """Add/merge a profile finding. Accumulates sources, never silently overwrites.

        Backward-compatible signature: existing callers passing (platform, url, confidence,
        notes) still work. New `source` kwarg lets callers attribute the discovery tool;
        when omitted, falls back to parsing the notes string.
        """
        # Resolve confidence
        if isinstance(confidence, (int, float)):
            score = float(confidence)
            tier = ConfidenceScore.to_legacy(score)
        else:
            tier = str(confidence)
            score = ConfidenceScore.from_legacy(tier)

        # Derive source if not provided
        if source is None:
            if notes and notes.lower().startswith("found by "):
                source = notes.split(" ", 2)[2].strip() or "unknown"
            else:
                source = notes.strip() or "unknown"

        existing = self.data["profiles"].get(platform)
        if not existing:
            capped = ConfidenceScore.cap_doctrine(score, sources_count=1)
            self.data["profiles"][platform] = {
                "url": url,
                "sources": [source],
                "confidence": ConfidenceScore.to_legacy(capped),
                "confidence_score": capped,
                "notes": notes,
                "verified_at": datetime.now().isoformat(),
            }
        else:
            existing.setdefault("sources", [])
            if source not in existing["sources"]:
                existing["sources"].append(source)
            # Track URL conflicts instead of silently overwriting
            if url and existing.get("url") != url:
                existing.setdefault("alt_urls", [])
                if url not in existing["alt_urls"]:
                    existing["alt_urls"].append(url)
            n = len(existing["sources"])
            recalc = ConfidenceScore.calculate(sources_count=n, corroborated=n >= 2)
            old_score = existing.get("confidence_score",
                                     ConfidenceScore.from_legacy(existing.get("confidence", "UNVERIFIED")))
            # Honour caller-asserted score too, but doctrine-capped
            asserted = ConfidenceScore.cap_doctrine(score, sources_count=n)
            new_score = max(old_score, recalc, asserted)
            existing["confidence_score"] = new_score
            existing["confidence"] = ConfidenceScore.to_legacy(new_score)
            if notes and notes not in existing.get("notes", ""):
                existing["notes"] = (existing.get("notes", "") + " | " + notes).strip(" |")
            existing["verified_at"] = datetime.now().isoformat()
        self.save()

    def add_org(self, name: str, role: str = "", source: str = ""):
        self.data["organizations"][name] = {"role": role, "source": source}
        self.save()

    def add_location(self, name: str, source: str = "", confidence: str = "PROBABLE"):
        if not any(l["name"] == name for l in self.data["locations"]):
            self.data["locations"].append({"name": name, "source": source, "confidence": confidence})
            self.save()

    def add_connection(self, name: str, relation: str = "", platform: str = "", url: str = ""):
        if not any(c["name"] == name for c in self.data["social_graph"]):
            self.data["social_graph"].append({"name": name, "relation": relation, "platform": platform, "url": url})
            self.save()

    def add_evidence(self, tool: str, output: str):
        if tool not in self.data["raw_evidence"]:
            self.data["raw_evidence"][tool] = []
        self.data["raw_evidence"][tool].append({
            "timestamp": datetime.now().isoformat(),
            "output": output[:3000]
        })
        self.save()

    def add_note(self, text: str, author: str = "system"):
        self.data["notes"].append({"text": text, "author": author, "timestamp": datetime.now().isoformat()})
        self.save()

    def calculate_confidence(self, finding_type: str, key: str) -> float:
        """Recalculate confidence for an existing finding based on current evidence."""
        section = self.data.get(finding_type, {})
        if isinstance(section, dict) and key in section:
            item = section[key]
            sources = item.get("sources", [])
            score = ConfidenceScore.calculate(
                sources_count=len(sources), corroborated=len(sources) >= 2
            )
            item["confidence_score"] = score
            item["confidence"] = ConfidenceScore.to_legacy(score)
            self.save()
            return score
        return 0.0

    def log_phase(self, phase: str, tools: list, findings: int):
        self.data["phase_log"].append({
            "phase": phase, "timestamp": datetime.now().isoformat(),
            "tools_used": tools, "findings_count": findings
        })
        self.save()

    # ── RAG: Document storage ──

    def add_document(self, filename: str, content: str, summary: str = ""):
        import hashlib
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        doc_path = STORE_DIR / "docs" / f"{self.target_id}_{content_hash}.txt"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(content)
        self.data["documents"].append({
            "filename": filename, "content_hash": content_hash,
            "path": str(doc_path), "summary": summary,
            "uploaded_at": datetime.now().isoformat()
        })
        self.save()

    def search_documents(self, query: str) -> list[dict]:
        """Simple keyword search across stored documents."""
        results = []
        query_lower = query.lower()
        keywords = query_lower.split()
        
        for doc in self.data["documents"]:
            doc_path = Path(doc.get("path", ""))
            if doc_path.exists():
                content = doc_path.read_text().lower()
                score = sum(1 for kw in keywords if kw in content)
                if score > 0:
                    # Extract relevant snippets
                    lines = doc_path.read_text().split("\n")
                    snippets = [l for l in lines if any(kw in l.lower() for kw in keywords)][:5]
                    results.append({
                        "filename": doc["filename"],
                        "score": score,
                        "snippets": snippets
                    })
        
        return sorted(results, key=lambda x: x["score"], reverse=True)

    def search_all(self, query: str) -> str:
        """Search across ALL stored intelligence for a query."""
        query_lower = query.lower()
        results = []
        
        # Search emails
        for email in self.data["emails"]:
            if query_lower in email:
                results.append(f"EMAIL: {email} [{self.data['emails'][email]['confidence']}]")
        
        # Search phones
        for phone in self.data["phones"]:
            if query_lower in phone:
                results.append(f"PHONE: {phone}")
        
        # Search profiles
        for platform, d in self.data["profiles"].items():
            if query_lower in platform.lower() or query_lower in d.get("url", "").lower():
                results.append(f"PROFILE: {platform} → {d['url']}")
        
        # Search notes
        for note in self.data["notes"]:
            if query_lower in note["text"].lower():
                results.append(f"NOTE: {note['text'][:100]}")
        
        # Search documents
        doc_results = self.search_documents(query)
        for dr in doc_results:
            results.append(f"DOC [{dr['filename']}]: {'; '.join(dr['snippets'][:2])}")
        
        return "\n".join(results) if results else "No results found."

    # ── Context generation for AI ──

    def get_context_summary(self) -> str:
        """Generate a concise summary of ALL known intelligence for AI context injection."""
        d = self.data
        parts = []
        
        parts.append(f"=== INVESTIGATION: {self.target_id} ===")
        parts.append(f"Started: {d['created']} | Updated: {d['updated']}")
        parts.append(f"Phases completed: {len(d['phase_log'])}")
        
        if d["identity"]["names"]:
            parts.append(f"\nIDENTITY: {', '.join(d['identity']['names'])}")
            parts.append(f"Usernames: {', '.join(d['identity']['usernames'])}")
        
        if d["emails"]:
            parts.append(f"\nEMAILS ({len(d['emails'])}):")
            for email, info in d["emails"].items():
                score = info.get("confidence_score", "")
                score_str = f"|{score}" if score else ""
                parts.append(f"  [{info['confidence']}{score_str}] {email} (via: {', '.join(info['sources'])})")
        
        if d["phones"]:
            parts.append(f"\nPHONES ({len(d['phones'])}):")
            for phone, info in d["phones"].items():
                parts.append(f"  [{info['confidence']}] {phone} (via: {', '.join(info['sources'])})")
        
        if d["profiles"]:
            parts.append(f"\nPROFILES ({len(d['profiles'])}):")
            for platform, info in d["profiles"].items():
                parts.append(f"  [{info['confidence']}] {platform}: {info['url']}")
        
        if d["organizations"]:
            parts.append(f"\nORGANIZATIONS: {', '.join(d['organizations'].keys())}")
        
        if d["locations"]:
            parts.append(f"LOCATIONS: {', '.join(l['name'] for l in d['locations'])}")
        
        if d["social_graph"]:
            parts.append(f"\nCONNECTIONS ({len(d['social_graph'])}):")
            for c in d["social_graph"][:10]:
                parts.append(f"  {c['name']} — {c['relation']}")
        
        if d["notes"]:
            parts.append(f"\nNOTES:")
            for n in d["notes"][-5:]:
                parts.append(f"  [{n['timestamp'][:10]}] {n['text'][:200]}")
        
        return "\n".join(parts)

    def export_graph_json(self) -> dict:
        """Export data in format compatible with graph_generator.py."""
        d = self.data
        return {
            "target": d["identity"]["names"][0] if d["identity"]["names"] else self.target_id,
            "aliases": d["identity"]["usernames"],
            "emails": [{"email": e, "source": ", ".join(i["sources"]), "confidence": i["confidence"]}
                       for e, i in d["emails"].items()],
            "phones": [{"number": p, "carrier": i.get("carrier", "")} for p, i in d["phones"].items()],
            "profiles": [{"platform": p, "url": i["url"]} for p, i in d["profiles"].items()],
            "organizations": [{"name": n, "role": i.get("role", "")} for n, i in d["organizations"].items()],
            "locations": [l["name"] for l in d["locations"]],
            "connections": [{"name": c["name"], "relation": c["relation"]} for c in d["social_graph"][:20]],
        }
