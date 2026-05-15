"""
CVEManager - CVE lookup, search, and caching for StrikeCore.

Provides methods to look up CVE details, search for CVEs by product
and version, find known exploits, and maintain a local cache for
offline and high-speed access.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CVEEntry:
    """A single CVE record."""
    cve_id: str
    description: str
    severity: str = "unknown"
    cvss_v3_score: float | None = None
    cvss_v3_vector: str = ""
    cvss_v2_score: float | None = None
    published_date: str = ""
    last_modified_date: str = ""
    affected_products: list[dict[str, str]] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    cwe_ids: list[str] = field(default_factory=list)
    exploit_available: bool = False
    exploit_references: list[str] = field(default_factory=list)


@dataclass
class ExploitInfo:
    """Information about a known exploit for a CVE."""
    cve_id: str
    source: str  # exploit-db, github, metasploit, etc.
    title: str
    url: str
    exploit_type: str = ""  # remote, local, webapps, dos
    platform: str = ""
    verified: bool = False


class CVEManager:
    """
    Manages CVE data with local caching and online lookup capabilities.

    Supports lookup by CVE ID, searching by product/version, and
    finding known exploits associated with CVEs.
    """

    # Well-known CVE data sources
    NVD_API_BASE: str = "https://services.nvd.nist.gov/rest/json/cves/2.0"
    EXPLOIT_DB_API: str = "https://exploit-db.com/search"
    GITHUB_ADVISORY_API: str = "https://api.github.com/advisories"

    # Cache settings
    DEFAULT_CACHE_DIR: str = os.path.expanduser("~/.strikecore/cve_cache")
    CACHE_TTL_SECONDS: int = 86400 * 7  # 7 days

    def __init__(
        self,
        cache_dir: str | None = None,
        cache_ttl: int | None = None,
        http_client: Any | None = None,
    ) -> None:
        """
        Initialize the CVE manager.

        Args:
            cache_dir: Directory for local CVE cache. Defaults to ~/.strikecore/cve_cache.
            cache_ttl: Cache time-to-live in seconds. Defaults to 7 days.
            http_client: Optional async HTTP client (e.g. aiohttp.ClientSession).
                         If not provided, a client will be created when needed.
        """
        self._cache_dir = Path(cache_dir or self.DEFAULT_CACHE_DIR)
        self._cache_ttl = cache_ttl or self.CACHE_TTL_SECONDS
        self._http_client = http_client
        self._memory_cache: dict[str, tuple[float, CVEEntry]] = {}
        self._product_index: dict[str, list[str]] = {}  # product_key -> [cve_ids]
        self._ensure_cache_dir()

    def _ensure_cache_dir(self) -> None:
        """Create the cache directory if it does not exist."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def lookup(self, cve_id: str) -> CVEEntry | None:
        """
        Look up a CVE by its identifier.

        Checks memory cache first, then disk cache, then queries
        the NVD API as a last resort.

        Args:
            cve_id: The CVE identifier (e.g. 'CVE-2021-44228').

        Returns:
            A CVEEntry if found, None otherwise.
        """
        cve_id = self._normalize_cve_id(cve_id)
        if not cve_id:
            logger.warning("Invalid CVE ID provided.")
            return None

        # Check memory cache
        if cve_id in self._memory_cache:
            timestamp, entry = self._memory_cache[cve_id]
            if time.time() - timestamp < self._cache_ttl:
                logger.debug("CVE %s found in memory cache.", cve_id)
                return entry

        # Check disk cache
        disk_entry = self._read_disk_cache(cve_id)
        if disk_entry is not None:
            self._memory_cache[cve_id] = (time.time(), disk_entry)
            logger.debug("CVE %s found in disk cache.", cve_id)
            return disk_entry

        # Fetch from NVD API
        entry = await self._fetch_from_nvd(cve_id)
        if entry:
            self._cache_entry(entry)
            logger.info("CVE %s fetched from NVD and cached.", cve_id)
            return entry

        logger.warning("CVE %s not found.", cve_id)
        return None

    async def search(
        self,
        product: str,
        version: str = "",
        vendor: str = "",
        max_results: int = 50,
    ) -> list[CVEEntry]:
        """
        Search for CVEs affecting a specific product and version.

        Args:
            product: Product name (e.g. 'apache', 'nginx', 'openssl').
            version: Version string (e.g. '2.4.49'). Optional.
            vendor: Vendor name. Optional.
            max_results: Maximum number of results to return.

        Returns:
            List of matching CVEEntry objects, sorted by CVSS score descending.
        """
        product = product.strip().lower()
        version = version.strip()
        vendor = vendor.strip().lower()

        logger.info("Searching CVEs for product=%s version=%s vendor=%s", product, version, vendor)

        # Check local product index first
        product_key = self._product_key(product, version, vendor)
        if product_key in self._product_index:
            cached_ids = self._product_index[product_key]
            entries = []
            for cve_id in cached_ids[:max_results]:
                entry = await self.lookup(cve_id)
                if entry:
                    entries.append(entry)
            if entries:
                return self._sort_by_cvss(entries)

        # Fetch from NVD API with keyword search
        entries = await self._search_nvd(product, version, vendor, max_results)

        # Cache results
        cve_ids = [e.cve_id for e in entries]
        self._product_index[product_key] = cve_ids
        for entry in entries:
            self._cache_entry(entry)

        return self._sort_by_cvss(entries)

    async def get_exploits(self, cve_id: str) -> list[ExploitInfo]:
        """
        Find known exploits for a given CVE.

        Searches Exploit-DB references, GitHub advisories, and
        common exploit databases.

        Args:
            cve_id: The CVE identifier.

        Returns:
            List of ExploitInfo objects with exploit details.
        """
        cve_id = self._normalize_cve_id(cve_id)
        if not cve_id:
            return []

        exploits: list[ExploitInfo] = []

        # Check if CVE data already has exploit references
        entry = await self.lookup(cve_id)
        if entry and entry.exploit_references:
            for ref in entry.exploit_references:
                source = self._classify_exploit_source(ref)
                exploits.append(
                    ExploitInfo(
                        cve_id=cve_id,
                        source=source,
                        title=f"Exploit for {cve_id}",
                        url=ref,
                    )
                )

        # Check references in CVE data for exploit indicators
        if entry:
            for ref in entry.references:
                if self._is_exploit_reference(ref):
                    source = self._classify_exploit_source(ref)
                    if not any(e.url == ref for e in exploits):
                        exploits.append(
                            ExploitInfo(
                                cve_id=cve_id,
                                source=source,
                                title=f"Potential exploit reference for {cve_id}",
                                url=ref,
                            )
                        )

        # Search exploit databases via API
        api_exploits = await self._search_exploit_databases(cve_id)
        for exp in api_exploits:
            if not any(e.url == exp.url for e in exploits):
                exploits.append(exp)

        # Update the entry's exploit info
        if entry and exploits:
            entry.exploit_available = True
            entry.exploit_references = list({e.url for e in exploits})
            self._cache_entry(entry)

        return exploits

    async def bulk_lookup(self, cve_ids: list[str]) -> dict[str, CVEEntry | None]:
        """
        Look up multiple CVEs concurrently.

        Args:
            cve_ids: List of CVE identifiers.

        Returns:
            Dictionary mapping CVE IDs to their entries (or None).
        """
        tasks = [self.lookup(cve_id) for cve_id in cve_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            cve_id: (result if isinstance(result, CVEEntry) else None)
            for cve_id, result in zip(cve_ids, results)
        }

    async def map_service_to_cves(
        self, service: str, version: str, port: int | None = None
    ) -> list[CVEEntry]:
        """
        Map a discovered service/version to known CVEs.

        This is a convenience method that normalizes common service names
        and delegates to search().

        Args:
            service: Service name as reported by nmap or similar tools.
            version: Version string.
            port: Optional port number for context.

        Returns:
            List of matching CVE entries.
        """
        # Normalize service names
        service_map = {
            "http": "apache",
            "ssh": "openssh",
            "ftp": "vsftpd",
            "smtp": "postfix",
            "mysql": "mysql",
            "mssql": "microsoft sql_server",
            "postgresql": "postgresql",
            "redis": "redis",
            "mongodb": "mongodb",
            "nginx": "nginx",
            "apache": "apache http_server",
            "iis": "microsoft iis",
            "tomcat": "apache tomcat",
            "elasticsearch": "elasticsearch",
            "jenkins": "jenkins",
            "grafana": "grafana",
            "gitlab": "gitlab",
            "jira": "atlassian jira",
        }

        normalized = service.lower().strip()
        product = service_map.get(normalized, normalized)

        # Extract vendor if possible
        vendor = ""
        if " " in product:
            parts = product.split(" ", 1)
            vendor = parts[0]
            product = parts[1]

        return await self.search(product=product, version=version, vendor=vendor)

    # ------------------------------------------------------------------
    # Cache operations
    # ------------------------------------------------------------------

    def _cache_entry(self, entry: CVEEntry) -> None:
        """Write a CVE entry to both memory and disk cache."""
        self._memory_cache[entry.cve_id] = (time.time(), entry)
        self._write_disk_cache(entry)

    def _write_disk_cache(self, entry: CVEEntry) -> None:
        """Persist a CVE entry to disk."""
        cache_file = self._cache_dir / f"{entry.cve_id}.json"
        data = {
            "cve_id": entry.cve_id,
            "description": entry.description,
            "severity": entry.severity,
            "cvss_v3_score": entry.cvss_v3_score,
            "cvss_v3_vector": entry.cvss_v3_vector,
            "cvss_v2_score": entry.cvss_v2_score,
            "published_date": entry.published_date,
            "last_modified_date": entry.last_modified_date,
            "affected_products": entry.affected_products,
            "references": entry.references,
            "cwe_ids": entry.cwe_ids,
            "exploit_available": entry.exploit_available,
            "exploit_references": entry.exploit_references,
            "cached_at": time.time(),
        }
        try:
            cache_file.write_text(json.dumps(data, indent=2))
        except OSError as e:
            logger.warning("Failed to write cache file %s: %s", cache_file, e)

    def _read_disk_cache(self, cve_id: str) -> CVEEntry | None:
        """Read a CVE entry from disk cache if it exists and is not expired."""
        cache_file = self._cache_dir / f"{cve_id}.json"
        if not cache_file.exists():
            return None

        try:
            data = json.loads(cache_file.read_text())
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to read cache file %s: %s", cache_file, e)
            return None

        # Check TTL
        cached_at = data.get("cached_at", 0)
        if time.time() - cached_at > self._cache_ttl:
            logger.debug("Cache expired for %s", cve_id)
            return None

        return CVEEntry(
            cve_id=data["cve_id"],
            description=data.get("description", ""),
            severity=data.get("severity", "unknown"),
            cvss_v3_score=data.get("cvss_v3_score"),
            cvss_v3_vector=data.get("cvss_v3_vector", ""),
            cvss_v2_score=data.get("cvss_v2_score"),
            published_date=data.get("published_date", ""),
            last_modified_date=data.get("last_modified_date", ""),
            affected_products=data.get("affected_products", []),
            references=data.get("references", []),
            cwe_ids=data.get("cwe_ids", []),
            exploit_available=data.get("exploit_available", False),
            exploit_references=data.get("exploit_references", []),
        )

    def clear_cache(self) -> int:
        """
        Clear all cached CVE data.

        Returns:
            Number of cache entries removed.
        """
        self._memory_cache.clear()
        self._product_index.clear()
        count = 0
        for cache_file in self._cache_dir.glob("CVE-*.json"):
            try:
                cache_file.unlink()
                count += 1
            except OSError:
                pass
        logger.info("Cleared %d CVE cache entries.", count)
        return count

    def cache_stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        disk_files = list(self._cache_dir.glob("CVE-*.json"))
        total_size = sum(f.stat().st_size for f in disk_files if f.exists())
        return {
            "memory_entries": len(self._memory_cache),
            "disk_entries": len(disk_files),
            "product_index_entries": len(self._product_index),
            "disk_size_bytes": total_size,
            "cache_dir": str(self._cache_dir),
            "cache_ttl_seconds": self._cache_ttl,
        }

    # ------------------------------------------------------------------
    # API interaction
    # ------------------------------------------------------------------

    async def _fetch_from_nvd(self, cve_id: str) -> CVEEntry | None:
        """Fetch a CVE from the NVD API."""
        url = f"{self.NVD_API_BASE}?cveId={cve_id}"
        response_data = await self._http_get(url)
        if not response_data:
            return None

        try:
            vulnerabilities = response_data.get("vulnerabilities", [])
            if not vulnerabilities:
                return None

            cve_data = vulnerabilities[0].get("cve", {})
            return self._parse_nvd_cve(cve_data)
        except (KeyError, IndexError, TypeError) as e:
            logger.warning("Failed to parse NVD response for %s: %s", cve_id, e)
            return None

    async def _search_nvd(
        self, product: str, version: str, vendor: str, max_results: int
    ) -> list[CVEEntry]:
        """Search the NVD API for CVEs matching product/version."""
        keyword = f"{vendor} {product} {version}".strip()
        url = (
            f"{self.NVD_API_BASE}"
            f"?keywordSearch={keyword}"
            f"&resultsPerPage={min(max_results, 100)}"
        )

        response_data = await self._http_get(url)
        if not response_data:
            return []

        entries: list[CVEEntry] = []
        try:
            for vuln in response_data.get("vulnerabilities", []):
                cve_data = vuln.get("cve", {})
                entry = self._parse_nvd_cve(cve_data)
                if entry:
                    # Verify the product/version actually matches
                    if self._matches_product(entry, product, version, vendor):
                        entries.append(entry)
        except (KeyError, TypeError) as e:
            logger.warning("Failed to parse NVD search results: %s", e)

        return entries[:max_results]

    async def _search_exploit_databases(self, cve_id: str) -> list[ExploitInfo]:
        """Search known exploit databases for a CVE."""
        exploits: list[ExploitInfo] = []

        # Search GitHub Advisory Database
        gh_url = f"{self.GITHUB_ADVISORY_API}?cve_id={cve_id}"
        gh_data = await self._http_get(gh_url)
        if gh_data and isinstance(gh_data, list):
            for advisory in gh_data:
                html_url = advisory.get("html_url", "")
                if html_url:
                    exploits.append(
                        ExploitInfo(
                            cve_id=cve_id,
                            source="github_advisory",
                            title=advisory.get("summary", f"Advisory for {cve_id}"),
                            url=html_url,
                            exploit_type=advisory.get("type", ""),
                        )
                    )

        return exploits

    async def _http_get(self, url: str) -> dict[str, Any] | list | None:
        """Perform an HTTP GET request. Uses the provided client or a basic fallback."""
        if self._http_client is not None:
            try:
                async with self._http_client.get(url, timeout=30) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    logger.warning("HTTP %d from %s", resp.status, url)
            except Exception as e:
                logger.warning("HTTP request failed for %s: %s", url, e)
            return None

        # Fallback: use asyncio subprocess with curl
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", "-f", "--max-time", "30",
                "-H", "Accept: application/json",
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=35)
            if proc.returncode == 0 and stdout:
                return json.loads(stdout.decode())
            if stderr:
                logger.debug("curl stderr: %s", stderr.decode()[:200])
        except (asyncio.TimeoutError, json.JSONDecodeError, OSError) as e:
            logger.warning("Fallback HTTP request failed for %s: %s", url, e)

        return None

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    def _parse_nvd_cve(self, cve_data: dict[str, Any]) -> CVEEntry | None:
        """Parse a CVE entry from NVD API v2.0 format."""
        cve_id = cve_data.get("id", "")
        if not cve_id:
            return None

        # Description
        descriptions = cve_data.get("descriptions", [])
        description = ""
        for desc in descriptions:
            if desc.get("lang") == "en":
                description = desc.get("value", "")
                break
        if not description and descriptions:
            description = descriptions[0].get("value", "")

        # CVSS scores
        metrics = cve_data.get("metrics", {})
        cvss_v3_score = None
        cvss_v3_vector = ""
        cvss_v2_score = None

        v31_data = metrics.get("cvssMetricV31", [])
        if v31_data:
            cvss_obj = v31_data[0].get("cvssData", {})
            cvss_v3_score = cvss_obj.get("baseScore")
            cvss_v3_vector = cvss_obj.get("vectorString", "")

        v2_data = metrics.get("cvssMetricV2", [])
        if v2_data:
            cvss_obj = v2_data[0].get("cvssData", {})
            cvss_v2_score = cvss_obj.get("baseScore")

        # Severity
        severity = "unknown"
        if cvss_v3_score is not None:
            if cvss_v3_score >= 9.0:
                severity = "critical"
            elif cvss_v3_score >= 7.0:
                severity = "high"
            elif cvss_v3_score >= 4.0:
                severity = "medium"
            elif cvss_v3_score > 0:
                severity = "low"
            else:
                severity = "info"

        # Dates
        published = cve_data.get("published", "")
        modified = cve_data.get("lastModified", "")

        # References
        references: list[str] = []
        for ref in cve_data.get("references", []):
            url = ref.get("url", "")
            if url:
                references.append(url)

        # CWE IDs
        cwe_ids: list[str] = []
        weaknesses = cve_data.get("weaknesses", [])
        for weakness in weaknesses:
            for desc in weakness.get("description", []):
                val = desc.get("value", "")
                if val.startswith("CWE-"):
                    cwe_ids.append(val)

        # Affected products (CPE)
        affected_products: list[dict[str, str]] = []
        configurations = cve_data.get("configurations", [])
        for config in configurations:
            for node in config.get("nodes", []):
                for cpe_match in node.get("cpeMatch", []):
                    criteria = cpe_match.get("criteria", "")
                    if criteria:
                        product_info = self._parse_cpe(criteria)
                        if product_info:
                            affected_products.append(product_info)

        # Check for exploit indicators in references
        exploit_refs = [r for r in references if self._is_exploit_reference(r)]

        return CVEEntry(
            cve_id=cve_id,
            description=description,
            severity=severity,
            cvss_v3_score=cvss_v3_score,
            cvss_v3_vector=cvss_v3_vector,
            cvss_v2_score=cvss_v2_score,
            published_date=published,
            last_modified_date=modified,
            affected_products=affected_products,
            references=references,
            cwe_ids=cwe_ids,
            exploit_available=bool(exploit_refs),
            exploit_references=exploit_refs,
        )

    @staticmethod
    def _parse_cpe(cpe_string: str) -> dict[str, str] | None:
        """Parse a CPE 2.3 URI into vendor/product/version dict."""
        # CPE 2.3 format: cpe:2.3:a:vendor:product:version:...
        parts = cpe_string.split(":")
        if len(parts) < 6:
            return None
        return {
            "vendor": parts[3] if parts[3] != "*" else "",
            "product": parts[4] if parts[4] != "*" else "",
            "version": parts[5] if parts[5] != "*" else "",
        }

    @staticmethod
    def _matches_product(
        entry: CVEEntry, product: str, version: str, vendor: str
    ) -> bool:
        """Check if a CVE entry matches the given product/version/vendor."""
        product_lower = product.lower()
        version_lower = version.lower()
        vendor_lower = vendor.lower()

        for affected in entry.affected_products:
            p = affected.get("product", "").lower()
            v = affected.get("version", "").lower()
            vnd = affected.get("vendor", "").lower()

            product_match = product_lower in p or p in product_lower
            version_match = not version_lower or version_lower in v or v in version_lower
            vendor_match = not vendor_lower or vendor_lower in vnd or vnd in vendor_lower

            if product_match and version_match and vendor_match:
                return True

        # Fallback: check description
        desc_lower = entry.description.lower()
        if product_lower in desc_lower:
            if not version_lower or version_lower in desc_lower:
                return True

        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_cve_id(cve_id: str) -> str:
        """Normalize and validate a CVE identifier."""
        cve_id = cve_id.strip().upper()
        if re.match(r"^CVE-\d{4}-\d{4,}$", cve_id):
            return cve_id
        # Try to extract CVE ID from a string
        match = re.search(r"(CVE-\d{4}-\d{4,})", cve_id)
        return match.group(1) if match else ""

    @staticmethod
    def _product_key(product: str, version: str, vendor: str) -> str:
        """Generate a cache key for product/version/vendor combination."""
        return f"{vendor}:{product}:{version}".lower()

    @staticmethod
    def _sort_by_cvss(entries: list[CVEEntry]) -> list[CVEEntry]:
        """Sort CVE entries by CVSS v3 score, falling back to v2."""
        return sorted(
            entries,
            key=lambda e: e.cvss_v3_score if e.cvss_v3_score is not None else (e.cvss_v2_score or 0),
            reverse=True,
        )

    @staticmethod
    def _is_exploit_reference(url: str) -> bool:
        """Check if a URL is likely an exploit reference."""
        exploit_indicators = [
            "exploit-db.com",
            "packetstormsecurity.com",
            "github.com/poc",
            "github.com/exploit",
            "/exploit",
            "metasploit",
            "rapid7.com/db",
            "vulndb",
            "0day",
            "sploitus",
        ]
        url_lower = url.lower()
        return any(indicator in url_lower for indicator in exploit_indicators)

    @staticmethod
    def _classify_exploit_source(url: str) -> str:
        """Classify the source of an exploit based on its URL."""
        url_lower = url.lower()
        if "exploit-db.com" in url_lower:
            return "exploit-db"
        if "github.com" in url_lower:
            return "github"
        if "packetstormsecurity" in url_lower:
            return "packetstorm"
        if "metasploit" in url_lower or "rapid7" in url_lower:
            return "metasploit"
        if "sploitus" in url_lower:
            return "sploitus"
        return "other"
