"""Enrichment result cache backed by PersistenceStore.

Implements Requirements 2.1–2.9 and 6.7:
- Deterministic SHA-256 cache key from cleaned text and language code
- Configurable TTL with fail-fast validation (1..720 hours)
- Graceful degradation when the store is unavailable
- No-op behavior when caching is disabled
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from nlp_processing.config import ConfigurationError
from nlp_processing.models.enhancements import CachedEnrichment, CacheEntry

from .store import PersistenceStore

logger = logging.getLogger(__name__)


class CacheLayer:
    """Enrichment result cache backed by PersistenceStore.

    Provides transparent caching of enrichment results keyed by a SHA-256
    hash of the cleaned feedback text and language code. When disabled,
    ``get`` always returns ``None`` and ``put`` is a no-op.
    """

    def __init__(
        self,
        store: PersistenceStore,
        ttl_hours: int = 24,
        enabled: bool = True,
    ) -> None:
        """Initialize the cache layer.

        Parameters
        ----------
        store : PersistenceStore
            The persistence backend used for cache entry storage.
        ttl_hours : int
            Time-to-live for cache entries in hours. Must be an integer
            in the inclusive range 1..720. Defaults to 24.
        enabled : bool
            Whether caching is active. When False, ``get`` returns None
            and ``put`` is a no-op.

        Raises
        ------
        ConfigurationError
            If ``ttl_hours`` is not an integer or falls outside 1..720.
        """
        if isinstance(ttl_hours, bool) or not isinstance(ttl_hours, int):
            raise ConfigurationError(
                "ttl_hours", "value must be an integer between 1 and 720"
            )
        if not (1 <= ttl_hours <= 720):
            raise ConfigurationError(
                "ttl_hours", "value must be between 1 and 720 (inclusive)"
            )

        self._store = store
        self._ttl_hours = ttl_hours
        self._enabled = enabled

    def compute_key(self, cleaned_text: str, language_code: str) -> str:
        """Compute a deterministic cache key for the given text and language.

        Uses SHA-256 on ``cleaned_text + "\\x00" + language_code`` to produce
        a unique, collision-resistant key. The null-byte separator ensures
        that different (text, language) pairs cannot collide.

        Parameters
        ----------
        cleaned_text : str
            The normalized feedback text.
        language_code : str
            ISO 639-1 language code (e.g. "en", "es").

        Returns
        -------
        str
            A 64-character hexadecimal SHA-256 digest.
        """
        payload = cleaned_text + "\x00" + language_code
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, cleaned_text: str, language_code: str) -> CachedEnrichment | None:
        """Retrieve a cached enrichment result if available and not expired.

        Returns ``None`` when:
        - Caching is disabled
        - No entry exists for the computed key
        - The entry has expired (``expires_at`` is in the past)
        - The store is unavailable (read failure)

        Parameters
        ----------
        cleaned_text : str
            The normalized feedback text to look up.
        language_code : str
            ISO 639-1 language code.

        Returns
        -------
        CachedEnrichment | None
            The cached enrichment result, or None if not available.
        """
        if not self._enabled:
            return None

        key = self.compute_key(cleaned_text, language_code)

        try:
            entry = self._store.get_cache_entry(key)
        except Exception:
            return None

        if entry is None:
            return None

        # Check TTL expiry
        now = datetime.now(timezone.utc)
        try:
            expires_at = datetime.fromisoformat(entry.expires_at)
            # Ensure timezone-aware comparison
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None

        if now >= expires_at:
            return None

        return entry.enrichment

    def put(
        self, cleaned_text: str, language_code: str, result: CachedEnrichment
    ) -> None:
        """Store an enrichment result in the cache.

        When caching is disabled, this method is a no-op. On write failure,
        a warning is logged but no exception is raised.

        Parameters
        ----------
        cleaned_text : str
            The normalized feedback text.
        language_code : str
            ISO 639-1 language code.
        result : CachedEnrichment
            The enrichment result to cache.
        """
        if not self._enabled:
            return

        key = self.compute_key(cleaned_text, language_code)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=self._ttl_hours)

        entry = CacheEntry(
            key=key,
            enrichment=result,
            created_at=now.isoformat(),
            expires_at=expires_at.isoformat(),
        )

        try:
            self._store.save_cache_entry(key, entry, language_code)
        except Exception as exc:
            logger.warning(
                "Cache write failed for key %s: %s", key, exc
            )
