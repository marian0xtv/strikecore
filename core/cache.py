"""
LRU result cache with TTL support and disk persistence for StrikeCore.

Caches tool execution results keyed by a SHA-256 command hash so that
repeated identical invocations are served instantly.  The cache is persisted
to ``~/.strikecore/cache/`` as a single JSON file and restored on startup.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Paths and defaults
# ---------------------------------------------------------------------------

_CACHE_DIR = Path.home() / ".strikecore" / "cache"
_CACHE_FILE = _CACHE_DIR / "result_cache.json"
_DEFAULT_MAX_SIZE = 512
_DEFAULT_TTL = 3600  # seconds


# ---------------------------------------------------------------------------
# Cache entry
# ---------------------------------------------------------------------------

@dataclass
class CacheEntry:
    """A single cached value with expiration metadata."""

    key: str
    value: Any
    created_at: float
    ttl: float  # seconds; 0 means no expiry
    hits: int = 0

    @property
    def expires_at(self) -> float:
        if self.ttl <= 0:
            return float("inf")
        return self.created_at + self.ttl

    @property
    def is_expired(self) -> bool:
        if self.ttl <= 0:
            return False
        return time.time() > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "created_at": self.created_at,
            "ttl": self.ttl,
            "hits": self.hits,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CacheEntry:
        return cls(
            key=data["key"],
            value=data["value"],
            created_at=data["created_at"],
            ttl=data["ttl"],
            hits=data.get("hits", 0),
        )


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@dataclass
class CacheStats:
    """Snapshot of cache performance counters."""

    total_entries: int
    max_size: int
    default_ttl: float
    total_hits: int
    total_misses: int
    total_sets: int
    total_evictions: int
    expired_purged: int
    size_bytes: int

    @property
    def hit_rate(self) -> float:
        total = self.total_hits + self.total_misses
        return self.total_hits / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_entries": self.total_entries,
            "max_size": self.max_size,
            "default_ttl": self.default_ttl,
            "total_hits": self.total_hits,
            "total_misses": self.total_misses,
            "total_sets": self.total_sets,
            "total_evictions": self.total_evictions,
            "expired_purged": self.expired_purged,
            "size_bytes": self.size_bytes,
            "hit_rate": round(self.hit_rate, 4),
        }


# ---------------------------------------------------------------------------
# Result Cache
# ---------------------------------------------------------------------------

class ResultCache:
    """Thread-safe LRU cache with per-entry TTL and JSON disk persistence.

    Usage::

        cache = ResultCache(max_size=256, default_ttl=1800)
        cache.load()  # restore from disk

        key = cache.make_key("nmap -sV 10.0.0.1")
        cached = cache.get(key)
        if cached is None:
            result = await executor.execute("nmap -sV 10.0.0.1")
            cache.set(key, result.to_dict())

        cache.save()  # persist to disk
    """

    def __init__(
        self,
        max_size: int = _DEFAULT_MAX_SIZE,
        default_ttl: float = _DEFAULT_TTL,
        cache_dir: str | Path | None = None,
    ) -> None:
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.cache_dir = Path(cache_dir) if cache_dir else _CACHE_DIR
        self.cache_file = self.cache_dir / "result_cache.json"
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

        # Counters.
        self._total_hits = 0
        self._total_misses = 0
        self._total_sets = 0
        self._total_evictions = 0
        self._expired_purged = 0

        # Ensure directory exists and load persisted data.
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._load_from_disk()

    # ------------------------------------------------------------------
    # Key generation
    # ------------------------------------------------------------------

    @staticmethod
    def make_key(command: str) -> str:
        """Derive a cache key from a command string (SHA-256 hex digest)."""
        return hashlib.sha256(command.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def get(self, key: str) -> Any | None:
        """Return the cached value for *key*, or ``None`` on miss / expiry.

        On hit, the entry is promoted to the most-recently-used position.
        """
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._total_misses += 1
                return None
            if entry.is_expired:
                del self._cache[key]
                self._expired_purged += 1
                self._total_misses += 1
                return None
            self._cache.move_to_end(key)
            entry.hits += 1
            self._total_hits += 1
            return entry.value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store *value* under *key* with an optional per-entry *ttl*.

        If the cache exceeds ``max_size``, the least-recently-used entry is
        evicted.
        """
        effective_ttl = ttl if ttl is not None else self.default_ttl
        with self._lock:
            if key in self._cache:
                self._cache.pop(key)
            elif len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)
                self._total_evictions += 1
            self._cache[key] = CacheEntry(
                key=key,
                value=value,
                created_at=time.time(),
                ttl=effective_ttl,
            )
            self._total_sets += 1

    def invalidate(self, key: str) -> bool:
        """Remove *key* from the cache.  Returns ``True`` if it existed."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """Remove all entries from the cache (memory and disk)."""
        with self._lock:
            self._cache.clear()
        # Remove the persisted file as well.
        try:
            if self.cache_file.exists():
                self.cache_file.unlink()
        except OSError:
            pass

    def purge_expired(self) -> int:
        """Remove all expired entries.  Returns the number purged."""
        purged = 0
        with self._lock:
            expired_keys = [k for k, v in self._cache.items() if v.is_expired]
            for k in expired_keys:
                del self._cache[k]
                purged += 1
            self._expired_purged += purged
        return purged

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> CacheStats:
        """Return a snapshot of cache performance statistics."""
        with self._lock:
            size_bytes = 0
            for entry in self._cache.values():
                try:
                    size_bytes += len(json.dumps(entry.value, default=str).encode("utf-8"))
                except (TypeError, ValueError):
                    pass
            return CacheStats(
                total_entries=len(self._cache),
                max_size=self.max_size,
                default_ttl=self.default_ttl,
                total_hits=self._total_hits,
                total_misses=self._total_misses,
                total_sets=self._total_sets,
                total_evictions=self._total_evictions,
                expired_purged=self._expired_purged,
                size_bytes=size_bytes,
            )

    # ------------------------------------------------------------------
    # Disk persistence
    # ------------------------------------------------------------------

    def save(self, path: Path | None = None) -> None:
        """Persist the cache to disk as JSON.

        Expired entries are purged before writing.  The write is atomic
        (write to temp then rename) to prevent corruption.
        """
        self.purge_expired()
        target = path or self.cache_file
        target.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            data = {
                "version": 1,
                "max_size": self.max_size,
                "default_ttl": self.default_ttl,
                "entries": [entry.to_dict() for entry in self._cache.values()],
                "stats": {
                    "hits": self._total_hits,
                    "misses": self._total_misses,
                    "sets": self._total_sets,
                    "evictions": self._total_evictions,
                    "expired_purged": self._expired_purged,
                },
            }

        tmp_path = target.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, default=str)
            tmp_path.replace(target)
        except OSError:
            # Best-effort persistence.
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def load(self, path: Path | None = None) -> int:
        """Load cache from disk, returning the number of entries restored.

        Expired entries are discarded during loading.
        """
        source = path or self.cache_file
        return self._load_from_disk(source)

    def _load_from_disk(self, source: Path | None = None) -> int:
        """Internal disk loader, also used during __init__."""
        target = source or self.cache_file
        if not target.exists():
            return 0

        try:
            with open(target, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return 0

        entries_list = data.get("entries", [])
        restored = 0

        with self._lock:
            self._cache.clear()

            for entry_dict in entries_list:
                try:
                    entry = CacheEntry.from_dict(entry_dict)
                except (KeyError, TypeError):
                    continue
                if entry.is_expired:
                    continue
                self._cache[entry.key] = entry
                restored += 1
                if len(self._cache) >= self.max_size:
                    break

            # Restore stats counters.
            stats = data.get("stats", {})
            self._total_hits = stats.get("hits", 0)
            self._total_misses = stats.get("misses", 0)
            self._total_sets = stats.get("sets", 0)
            self._total_evictions = stats.get("evictions", 0)
            self._expired_purged = stats.get("expired_purged", 0)

        return restored

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    def __contains__(self, key: str) -> bool:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None or entry.is_expired:
                return False
            return True

    def __repr__(self) -> str:
        s = self.stats()
        return (
            f"<ResultCache entries={s.total_entries}/{s.max_size} "
            f"hit_rate={s.hit_rate:.1%}>"
        )
