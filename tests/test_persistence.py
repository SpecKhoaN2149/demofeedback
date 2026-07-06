"""Property-based tests for the PersistenceStore.

Tests validate batch persistence correctness properties from the design
document for the nlp-pipeline-enhancements feature.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from hypothesis import given, settings

from nlp_processing.persistence.store import PersistenceStore
from tests.strategies import valid_batch_output


# Feature: nlp-pipeline-enhancements, Property 1: Batch persistence round-trip
# **Validates: Requirements 1.1, 1.3, 1.6, 1.7**
@given(batch_output=valid_batch_output())
@settings(max_examples=100)
def test_batch_persistence_round_trip(batch_output):
    """For any valid BatchOutput, saving it to the PersistenceStore and then
    retrieving it by its assigned batch identifier SHALL produce an object whose
    InsightRecords, Clusters, FailureEntries, BatchSummary, and status are
    field-by-field equal to those of the originally saved BatchOutput.
    """
    store = PersistenceStore(backend="sqlite", db_path=":memory:")
    result = store.save_batch(batch_output)

    # Save must succeed
    assert result.success

    # Retrieve must return the saved batch
    retrieved = store.get_batch(result.batch_id)
    assert retrieved is not None

    # Field-by-field equality for InsightRecords
    assert len(retrieved.insights) == len(batch_output.insights)
    for orig, ret in zip(batch_output.insights, retrieved.insights):
        assert orig.feedback_id == ret.feedback_id
        assert orig.themes == ret.themes
        assert orig.sentiment == ret.sentiment
        assert orig.sentiment_confidence == ret.sentiment_confidence
        assert orig.severity_score == ret.severity_score
        assert orig.severity_factors == ret.severity_factors
        assert orig.cluster_id == ret.cluster_id

    # Field-by-field equality for Clusters
    assert len(retrieved.clusters) == len(batch_output.clusters)
    for orig, ret in zip(batch_output.clusters, retrieved.clusters):
        assert orig.cluster_id == ret.cluster_id
        assert orig.label == ret.label
        assert orig.member_ids == ret.member_ids

    # Field-by-field equality for FailureEntries
    assert len(retrieved.failures) == len(batch_output.failures)
    for orig, ret in zip(batch_output.failures, retrieved.failures):
        assert orig.feedback_id == ret.feedback_id
        assert orig.stage == ret.stage
        assert orig.reason == ret.reason

    # BatchSummary equality
    assert retrieved.summary.submitted == batch_output.summary.submitted
    assert retrieved.summary.successful == batch_output.summary.successful
    assert retrieved.summary.failures == batch_output.summary.failures

    # model_name equality
    assert retrieved.model_name == batch_output.model_name

    store.close()


# Feature: nlp-pipeline-enhancements, Property 2: Batch metadata assignment
# **Validates: Requirements 1.2**
@given(batch_output=valid_batch_output())
@settings(max_examples=100)
def test_batch_metadata_assignment(batch_output):
    """For any saved batch, the PersistenceStore SHALL assign a non-empty
    unique batch identifier, a valid ISO 8601 UTC timestamp, and a status
    of "completed".
    """
    store = PersistenceStore(backend="sqlite", db_path=":memory:")
    result = store.save_batch(batch_output)

    # Save must succeed
    assert result.success

    # batch_id must be non-empty
    assert result.batch_id
    assert len(result.batch_id) > 0

    # batch_id must be a valid UUID
    parsed_uuid = uuid.UUID(result.batch_id)
    assert parsed_uuid.version == 4

    # Verify uniqueness by saving the same batch again
    result2 = store.save_batch(batch_output)
    assert result2.success
    assert result2.batch_id != result.batch_id

    # Verify batch metadata is correct via list_batches
    # Use a wide time range to capture the saved batches
    start = datetime(2000, 1, 1, tzinfo=timezone.utc)
    end = datetime(2100, 1, 1, tzinfo=timezone.utc)
    batches = store.list_batches(start, end)

    assert len(batches) == 2

    for batch_meta in batches:
        # batch_id is non-empty
        assert batch_meta.batch_id
        assert len(batch_meta.batch_id) > 0

        # timestamp is valid ISO 8601 UTC
        parsed_ts = datetime.fromisoformat(batch_meta.timestamp)
        assert parsed_ts.tzinfo is not None or batch_meta.timestamp.endswith("+00:00") or "Z" in batch_meta.timestamp

        # status is "completed"
        assert batch_meta.status == "completed"

    # The two batch_ids in the listing must be distinct
    assert batches[0].batch_id != batches[1].batch_id

    store.close()


# ---------------------------------------------------------------------------
# Unit tests for PersistenceStore edge cases (Task 2.4)
# Validates Requirements 1.4, 1.8, 1.9
# ---------------------------------------------------------------------------

import pytest

from nlp_processing.config import ConfigurationError
from nlp_processing.models.records import (
    BatchOutput,
    BatchSummary,
    InsightRecord,
    SeverityFactor,
    ThemeAssignment,
)


def _minimal_batch_output() -> BatchOutput:
    """Create a minimal valid BatchOutput for testing."""
    return BatchOutput(
        insights=[
            InsightRecord(
                feedback_id="test-1",
                themes=[ThemeAssignment(theme="billing", confidence=0.9)],
                sentiment="positive",
                sentiment_confidence=0.85,
                severity_score=2,
                severity_factors=[SeverityFactor(description="minor issue")],
                cluster_id="cl-1",
                model_name="test-model",
            )
        ],
        clusters=[],
        failures=[],
        system_errors=[],
        summary=BatchSummary(submitted=1, successful=1, failures=0),
        model_name="test-model",
    )


class TestGetBatchNotFound:
    """Requirement 1.4: Not-found returns None rather than an error."""

    def test_get_batch_not_found_returns_none(self):
        store = PersistenceStore(backend="sqlite", db_path=":memory:")
        result = store.get_batch("nonexistent-id")
        assert result is None

    def test_get_batch_empty_id_returns_none(self):
        store = PersistenceStore(backend="sqlite", db_path=":memory:")
        result = store.get_batch("")
        assert result is None


class TestInvalidBackendConfig:
    """Requirement 1.9: Invalid backend configuration raises ConfigurationError."""

    def test_unrecognized_backend_raises(self):
        with pytest.raises(ConfigurationError):
            PersistenceStore(backend="postgres", db_path="/tmp/test.db")

    def test_empty_backend_raises(self):
        with pytest.raises(ConfigurationError):
            PersistenceStore(backend="", db_path="/tmp/test.db")

    def test_empty_db_path_raises(self):
        with pytest.raises(ConfigurationError):
            PersistenceStore(backend="sqlite", db_path="")

    def test_whitespace_only_backend_raises(self):
        with pytest.raises(ConfigurationError):
            PersistenceStore(backend="   ", db_path="/tmp/test.db")


class TestSchemaCreation:
    """Verify SQLite schema is created on a fresh database."""

    def test_batches_table_exists(self):
        store = PersistenceStore(backend="sqlite", db_path=":memory:")
        cursor = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert "batches" in tables

    def test_cache_entries_table_exists(self):
        store = PersistenceStore(backend="sqlite", db_path=":memory:")
        cursor = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert "cache_entries" in tables

    def test_indexes_exist(self):
        store = PersistenceStore(backend="sqlite", db_path=":memory:")
        cursor = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_cache_expires" in indexes
        assert "idx_batches_timestamp" in indexes


class TestSaveFailure:
    """Requirement 1.8: Save failure returns SaveResult with success=False."""

    def test_save_failure_after_table_drop(self):
        store = PersistenceStore(backend="sqlite", db_path=":memory:")
        # Drop the batches table to force an INSERT failure
        store._conn.execute("DROP TABLE batches")
        batch_output = _minimal_batch_output()
        result = store.save_batch(batch_output)
        assert not result.success
        assert result.error is not None
        assert result.batch_id  # batch_id is still assigned

    def test_save_failure_after_connection_close(self):
        store = PersistenceStore(backend="sqlite", db_path=":memory:")
        store._conn.close()
        batch_output = _minimal_batch_output()
        result = store.save_batch(batch_output)
        assert not result.success
        assert result.error is not None
