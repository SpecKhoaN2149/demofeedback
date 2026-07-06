"""SQLite-backed persistence store for batch outputs and cache entries.

Implements Requirements 1.1–1.9 and 2.6:
- Durable batch storage with unique identifiers, ISO 8601 timestamps, and
  round-trip fidelity via Pydantic JSON serialization.
- Cache entry storage with TTL tracking for enrichment result caching.
- Graceful error handling: write failures return SaveResult(success=False),
  read failures return None.

Uses Python's built-in sqlite3 module (no additional dependency).
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from nlp_processing.config import ConfigurationError
from nlp_processing.models.enhancements import (
    BatchMetadata,
    CachedEnrichment,
    CacheEntry,
    SaveResult,
)
from nlp_processing.models.records import BatchOutput
from nlp_processing.persistence_config import PersistenceConfig

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cache_entries (
    key TEXT PRIMARY KEY,
    language_code TEXT NOT NULL,
    enrichment TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache_entries(expires_at);
CREATE INDEX IF NOT EXISTS idx_batches_timestamp ON batches(timestamp);
"""


class PersistenceStore:
    """Durable storage for batch outputs and cache entries.

    Uses a SQLite database as the storage backend. Configuration is validated
    at construction time via PersistenceConfig; invalid settings raise
    ConfigurationError and prevent the pipeline from starting.
    """

    def __init__(self, backend: str, db_path: str) -> None:
        """Initialize the persistence store.

        Validates configuration using PersistenceConfig (fail-fast) and
        creates the SQLite schema if it doesn't exist.

        Parameters
        ----------
        backend : str
            Storage backend identifier. Must be "sqlite".
        db_path : str
            File path for the SQLite database (or ":memory:" for testing).

        Raises
        ------
        ConfigurationError
            If backend is not "sqlite" or db_path is empty/invalid.
        """
        # Validate via PersistenceConfig — raises ConfigurationError on failure.
        PersistenceConfig(backend=backend, db_path=db_path)

        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        """Create database tables and indexes if they don't exist."""
        self._conn.executescript(_SCHEMA_SQL)

    # ------------------------------------------------------------------
    # Batch persistence
    # ------------------------------------------------------------------

    def save_batch(self, batch_output: BatchOutput) -> SaveResult:
        """Save a completed BatchOutput to durable storage.

        Assigns a unique batch_id (UUID4), an ISO 8601 UTC timestamp, and
        status "completed". Serializes the BatchOutput as JSON.

        Parameters
        ----------
        batch_output : BatchOutput
            The completed batch to persist.

        Returns
        -------
        SaveResult
            On success: SaveResult(batch_id=..., success=True).
            On failure: SaveResult(batch_id=..., success=False, error=...).
        """
        batch_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = batch_output.model_dump_json()

        try:
            self._conn.execute(
                "INSERT INTO batches (batch_id, timestamp, status, payload) "
                "VALUES (?, ?, ?, ?)",
                (batch_id, timestamp, "completed", payload),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            return SaveResult(batch_id=batch_id, success=False, error=str(exc))

        return SaveResult(batch_id=batch_id, success=True)

    def get_batch(self, batch_id: str) -> BatchOutput | None:
        """Retrieve a previously saved BatchOutput by its identifier.

        Parameters
        ----------
        batch_id : str
            The unique batch identifier assigned during save.

        Returns
        -------
        BatchOutput | None
            The deserialized batch, or None if not found or on read error.
        """
        try:
            cursor = self._conn.execute(
                "SELECT payload FROM batches WHERE batch_id = ?",
                (batch_id,),
            )
            row = cursor.fetchone()
        except sqlite3.Error:
            return None

        if row is None:
            return None

        try:
            return BatchOutput.model_validate_json(row[0])
        except Exception:
            return None

    def list_batches(self, start: datetime, end: datetime) -> list[BatchMetadata]:
        """List batch metadata within a time range.

        Parameters
        ----------
        start : datetime
            Inclusive start of the time range (UTC).
        end : datetime
            Exclusive end of the time range (UTC).

        Returns
        -------
        list[BatchMetadata]
            Metadata for batches whose timestamp falls in [start, end),
            ordered by timestamp ascending. record_count is derived from
            the number of InsightRecords in the batch payload.
        """
        start_iso = start.isoformat()
        end_iso = end.isoformat()

        try:
            cursor = self._conn.execute(
                "SELECT batch_id, timestamp, status, payload FROM batches "
                "WHERE timestamp >= ? AND timestamp < ? "
                "ORDER BY timestamp ASC",
                (start_iso, end_iso),
            )
            rows = cursor.fetchall()
        except sqlite3.Error:
            return []

        results: list[BatchMetadata] = []
        for batch_id, timestamp, status, payload in rows:
            try:
                batch = BatchOutput.model_validate_json(payload)
                record_count = len(batch.insights)
            except Exception:
                record_count = 0

            results.append(
                BatchMetadata(
                    batch_id=batch_id,
                    timestamp=timestamp,
                    status=status,
                    record_count=record_count,
                )
            )

        return results

    # ------------------------------------------------------------------
    # Cache entry storage
    # ------------------------------------------------------------------

    def save_cache_entry(
        self, key: str, entry: CacheEntry, language_code: str = "en"
    ) -> None:
        """Save or update a cache entry.

        Parameters
        ----------
        key : str
            The cache key (typically a SHA-256 hash).
        entry : CacheEntry
            The cache entry containing enrichment data and TTL info.
        language_code : str
            The ISO 639-1 language code associated with this cache entry.
            Defaults to "en".
        """
        enrichment_json = entry.enrichment.model_dump_json()

        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache_entries "
                "(key, language_code, enrichment, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    key,
                    language_code,
                    enrichment_json,
                    entry.created_at,
                    entry.expires_at,
                ),
            )
            self._conn.commit()
        except sqlite3.Error:
            # Cache write failures are non-fatal (Req 2.8).
            pass

    def get_cache_entry(self, key: str) -> CacheEntry | None:
        """Retrieve a cache entry by key.

        Parameters
        ----------
        key : str
            The cache key to look up.

        Returns
        -------
        CacheEntry | None
            The reconstructed cache entry, or None if not found or on error.
        """
        try:
            cursor = self._conn.execute(
                "SELECT key, enrichment, created_at, expires_at "
                "FROM cache_entries WHERE key = ?",
                (key,),
            )
            row = cursor.fetchone()
        except sqlite3.Error:
            return None

        if row is None:
            return None

        try:
            enrichment = CachedEnrichment.model_validate_json(row[1])
            return CacheEntry(
                key=row[0],
                enrichment=enrichment,
                created_at=row[2],
                expires_at=row[3],
            )
        except Exception:
            return None

    def delete_expired_cache(self, cutoff: datetime) -> int:
        """Delete cache entries that have expired before the given cutoff.

        Parameters
        ----------
        cutoff : datetime
            Cache entries with expires_at earlier than this time are deleted.

        Returns
        -------
        int
            The number of cache entries deleted. Returns 0 on error.
        """
        cutoff_iso = cutoff.isoformat()

        try:
            cursor = self._conn.execute(
                "DELETE FROM cache_entries WHERE expires_at < ?",
                (cutoff_iso,),
            )
            self._conn.commit()
            return cursor.rowcount
        except sqlite3.Error:
            return 0

    # ------------------------------------------------------------------
    # Resource management
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __del__(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
