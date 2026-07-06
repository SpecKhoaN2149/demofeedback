"""Unit tests for database schema constraints on feedback routing tables.

Tests all CHECK constraints (enum values, score ranges, length limits),
foreign key enforcement (cluster_id, feedback_id, ticket_id references),
cascade delete behavior on feedback_ticket_link, and duplicate feedback_id
rejection.

Validates: Requirements 17.2, 17.3, 17.6, 18.2, 18.3, 18.4, 18.5, 19.5,
19.6, 20.2, 20.4, 20.5, 20.6, 21.2, 21.3, 21.5
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from nlp_processing.models.feedback_routing import (
    ClusterRecord,
    FeedbackAnalysis,
    Ticket,
)
from nlp_processing.persistence.feedback_store import (
    ConstraintViolationError,
    FeedbackStore,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _uid() -> str:
    return str(uuid.uuid4())


def _insert_valid_feedback(store: FeedbackStore, feedback_id: str | None = None) -> str:
    """Insert a valid feedback record and return its ID."""
    fid = feedback_id or _uid()
    store.insert_feedback(
        feedback_id=fid,
        source_type="social",
        message_text="Valid feedback message for testing.",
        created_at_original=_NOW,
        ingested_at=_NOW,
    )
    return fid


def _make_valid_cluster(cluster_id: str | None = None) -> ClusterRecord:
    cid = cluster_id or _uid()
    return ClusterRecord(
        cluster_id=cid,
        theme="Network outage",
        priority_level="medium",
        first_seen_at=_NOW,
        last_seen_at=_NOW,
    )


def _make_valid_ticket(ticket_id: str | None = None, linked_cluster_id: str | None = None) -> Ticket:
    tid = ticket_id or _uid()
    return Ticket(
        ticket_id=tid,
        ticket_phase="new",
        priority_level="medium",
        assigned_department="Customer_Care",
        created_at=_NOW,
        updated_at=_NOW,
        linked_cluster_id=linked_cluster_id,
    )


def _make_valid_analysis(feedback_id: str, cluster_id: str | None = None) -> FeedbackAnalysis:
    return FeedbackAnalysis(
        feedback_id=feedback_id,
        sentiment_label="neutral",
        sentiment_score=0.0,
        priority_score=0.3,
        priority_level="medium",
        theme_primary="billing",
        intent="request_for_help",
        cluster_id=cluster_id,
        requires_action=True,
        processed_at=_NOW,
    )


@pytest.fixture
def store() -> FeedbackStore:
    """Create a fresh in-memory FeedbackStore for each test."""
    return FeedbackStore(db_path=":memory:")


# ===========================================================================
# Feedback table CHECK constraints (Requirement 17.2, 17.3)
# ===========================================================================


class TestFeedbackCheckConstraints:
    """Test CHECK constraints on the feedback table."""

    def test_invalid_source_type_rejected(self, store: FeedbackStore) -> None:
        """source_type must be 'social' or 'widget'."""
        with pytest.raises(ConstraintViolationError) as exc_info:
            store.insert_feedback(
                feedback_id=_uid(),
                source_type="email",
                message_text="Hello",
                created_at_original=_NOW,
            )
        assert exc_info.value.constraint_type == "enum_violation"

    def test_empty_message_text_rejected(self, store: FeedbackStore) -> None:
        """message_text must be non-empty (at least 1 non-whitespace char)."""
        with pytest.raises(ConstraintViolationError) as exc_info:
            store.insert_feedback(
                feedback_id=_uid(),
                source_type="social",
                message_text="   ",
                created_at_original=_NOW,
            )
        assert exc_info.value.constraint_type == "text_constraint_violation"

    def test_message_text_exceeds_10000_chars_rejected(self, store: FeedbackStore) -> None:
        """message_text must not exceed 10000 characters."""
        with pytest.raises(ConstraintViolationError) as exc_info:
            store.insert_feedback(
                feedback_id=_uid(),
                source_type="widget",
                message_text="x" * 10001,
                created_at_original=_NOW,
            )
        assert exc_info.value.constraint_type == "text_constraint_violation"

    def test_recency_score_below_zero_rejected(self, store: FeedbackStore) -> None:
        """recency_score must be >= 0.0."""
        with pytest.raises(ConstraintViolationError) as exc_info:
            store.insert_feedback(
                feedback_id=_uid(),
                source_type="social",
                message_text="Valid text",
                created_at_original=_NOW,
                recency_score=-0.1,
            )
        assert exc_info.value.constraint_type == "range_violation"

    def test_recency_score_above_one_rejected(self, store: FeedbackStore) -> None:
        """recency_score must be <= 1.0."""
        with pytest.raises(ConstraintViolationError) as exc_info:
            store.insert_feedback(
                feedback_id=_uid(),
                source_type="social",
                message_text="Valid text",
                created_at_original=_NOW,
                recency_score=1.5,
            )
        assert exc_info.value.constraint_type == "range_violation"

    def test_invalid_processing_status_rejected(self, store: FeedbackStore) -> None:
        """processing_status must be a valid enum value."""
        with pytest.raises(ConstraintViolationError) as exc_info:
            store.insert_feedback(
                feedback_id=_uid(),
                source_type="social",
                message_text="Valid text",
                created_at_original=_NOW,
                processing_status="completed",
            )
        assert exc_info.value.constraint_type == "enum_violation"

    def test_platform_exceeds_50_chars_rejected(self, store: FeedbackStore) -> None:
        """platform must not exceed 50 characters."""
        with pytest.raises(ConstraintViolationError) as exc_info:
            store.insert_feedback(
                feedback_id=_uid(),
                source_type="social",
                message_text="Valid text",
                created_at_original=_NOW,
                platform="x" * 51,
            )
        assert exc_info.value.constraint_type == "length_violation"

    def test_customer_id_exceeds_100_chars_rejected(self, store: FeedbackStore) -> None:
        """customer_id must not exceed 100 characters."""
        with pytest.raises(ConstraintViolationError) as exc_info:
            store.insert_feedback(
                feedback_id=_uid(),
                source_type="social",
                message_text="Valid text",
                created_at_original=_NOW,
                customer_id="c" * 101,
            )
        assert exc_info.value.constraint_type == "length_violation"

    def test_valid_feedback_accepted(self, store: FeedbackStore) -> None:
        """A well-formed feedback record should be accepted without error."""
        _insert_valid_feedback(store)  # Should not raise


# ===========================================================================
# Feedback Analysis table CHECK constraints (Requirement 18.2, 18.3, 18.4, 18.5)
# ===========================================================================


class TestAnalysisCheckConstraints:
    """Test CHECK constraints on the feedback_analysis table."""

    def test_invalid_sentiment_label_rejected(self, store: FeedbackStore) -> None:
        """sentiment_label must be 'positive', 'neutral', or 'negative'."""
        fid = _insert_valid_feedback(store)
        analysis = FeedbackAnalysis(
            feedback_id=fid,
            sentiment_label="negative",  # valid for model; we bypass model
            sentiment_score=0.0,
            priority_score=0.3,
            priority_level="medium",
            theme_primary="billing",
            intent="complaint",
            requires_action=True,
            processed_at=_NOW,
        )
        # Directly insert with invalid sentiment_label via raw SQL bypass
        # We need to use the store's insert but with bad data at the DB level
        # Since Pydantic models validate, test at DB level directly
        with pytest.raises(Exception):
            store._conn.execute(
                """INSERT INTO feedback_analysis (
                    feedback_id, sentiment_label, sentiment_score,
                    priority_score, priority_level, theme_primary,
                    theme_secondary, intent, cluster_id,
                    requires_action, entities, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (fid, "very_positive", 0.5, 0.3, "medium", "billing",
                 None, "complaint", None, 1, None, _NOW),
            )

    def test_sentiment_score_below_minus_one_rejected(self, store: FeedbackStore) -> None:
        """sentiment_score must be >= -1.0."""
        fid = _insert_valid_feedback(store)
        with pytest.raises(Exception):
            store._conn.execute(
                """INSERT INTO feedback_analysis (
                    feedback_id, sentiment_label, sentiment_score,
                    priority_score, priority_level, theme_primary,
                    theme_secondary, intent, cluster_id,
                    requires_action, entities, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (fid, "negative", -1.5, 0.3, "medium", "billing",
                 None, "complaint", None, 1, None, _NOW),
            )

    def test_sentiment_score_above_one_rejected(self, store: FeedbackStore) -> None:
        """sentiment_score must be <= 1.0."""
        fid = _insert_valid_feedback(store)
        with pytest.raises(Exception):
            store._conn.execute(
                """INSERT INTO feedback_analysis (
                    feedback_id, sentiment_label, sentiment_score,
                    priority_score, priority_level, theme_primary,
                    theme_secondary, intent, cluster_id,
                    requires_action, entities, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (fid, "positive", 1.5, 0.3, "medium", "billing",
                 None, "complaint", None, 1, None, _NOW),
            )

    def test_priority_score_below_zero_rejected(self, store: FeedbackStore) -> None:
        """priority_score must be >= 0.0."""
        fid = _insert_valid_feedback(store)
        with pytest.raises(Exception):
            store._conn.execute(
                """INSERT INTO feedback_analysis (
                    feedback_id, sentiment_label, sentiment_score,
                    priority_score, priority_level, theme_primary,
                    theme_secondary, intent, cluster_id,
                    requires_action, entities, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (fid, "neutral", 0.0, -0.1, "medium", "billing",
                 None, "complaint", None, 1, None, _NOW),
            )

    def test_priority_score_above_one_rejected(self, store: FeedbackStore) -> None:
        """priority_score must be <= 1.0."""
        fid = _insert_valid_feedback(store)
        with pytest.raises(Exception):
            store._conn.execute(
                """INSERT INTO feedback_analysis (
                    feedback_id, sentiment_label, sentiment_score,
                    priority_score, priority_level, theme_primary,
                    theme_secondary, intent, cluster_id,
                    requires_action, entities, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (fid, "neutral", 0.0, 1.5, "medium", "billing",
                 None, "complaint", None, 1, None, _NOW),
            )

    def test_invalid_priority_level_in_analysis_rejected(self, store: FeedbackStore) -> None:
        """priority_level in feedback_analysis must be 'low', 'medium', 'high', or 'critical'."""
        fid = _insert_valid_feedback(store)
        with pytest.raises(Exception):
            store._conn.execute(
                """INSERT INTO feedback_analysis (
                    feedback_id, sentiment_label, sentiment_score,
                    priority_score, priority_level, theme_primary,
                    theme_secondary, intent, cluster_id,
                    requires_action, entities, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (fid, "neutral", 0.0, 0.3, "urgent", "billing",
                 None, "complaint", None, 1, None, _NOW),
            )

    def test_valid_analysis_accepted(self, store: FeedbackStore) -> None:
        """A well-formed analysis record should be accepted without error."""
        fid = _insert_valid_feedback(store)
        analysis = _make_valid_analysis(fid)
        store.insert_analysis(analysis)  # Should not raise


# ===========================================================================
# Tickets table CHECK constraints (Requirement 19.5, 19.6)
# ===========================================================================


class TestTicketCheckConstraints:
    """Test CHECK constraints on the tickets table."""

    def test_invalid_ticket_phase_rejected(self, store: FeedbackStore) -> None:
        """ticket_phase must be a valid enum value."""
        with pytest.raises(Exception):
            store._conn.execute(
                """INSERT INTO tickets (
                    ticket_id, ticket_phase, priority_level,
                    assigned_department, created_at, updated_at,
                    resolution_type, resolution_notes, linked_cluster_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_uid(), "invalid_phase", "medium", "Customer_Care",
                 _NOW, _NOW, None, None, None),
            )

    def test_invalid_priority_level_in_ticket_rejected(self, store: FeedbackStore) -> None:
        """priority_level must be 'low', 'medium', 'high', or 'critical'."""
        with pytest.raises(Exception):
            store._conn.execute(
                """INSERT INTO tickets (
                    ticket_id, ticket_phase, priority_level,
                    assigned_department, created_at, updated_at,
                    resolution_type, resolution_notes, linked_cluster_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_uid(), "new", "urgent", "Customer_Care",
                 _NOW, _NOW, None, None, None),
            )

    def test_invalid_assigned_department_rejected(self, store: FeedbackStore) -> None:
        """assigned_department must be a valid department name."""
        with pytest.raises(Exception):
            store._conn.execute(
                """INSERT INTO tickets (
                    ticket_id, ticket_phase, priority_level,
                    assigned_department, created_at, updated_at,
                    resolution_type, resolution_notes, linked_cluster_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_uid(), "new", "medium", "Unknown_Dept",
                 _NOW, _NOW, None, None, None),
            )

    def test_invalid_resolution_type_rejected(self, store: FeedbackStore) -> None:
        """resolution_type must be a valid enum value or NULL."""
        with pytest.raises(Exception):
            store._conn.execute(
                """INSERT INTO tickets (
                    ticket_id, ticket_phase, priority_level,
                    assigned_department, created_at, updated_at,
                    resolution_type, resolution_notes, linked_cluster_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_uid(), "new", "medium", "Customer_Care",
                 _NOW, _NOW, "invalid_type", None, None),
            )

    def test_resolution_notes_exceeds_2000_chars_rejected(self, store: FeedbackStore) -> None:
        """resolution_notes must not exceed 2000 characters."""
        with pytest.raises(Exception):
            store._conn.execute(
                """INSERT INTO tickets (
                    ticket_id, ticket_phase, priority_level,
                    assigned_department, created_at, updated_at,
                    resolution_type, resolution_notes, linked_cluster_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_uid(), "new", "medium", "Customer_Care",
                 _NOW, _NOW, None, "n" * 2001, None),
            )

    def test_valid_ticket_accepted(self, store: FeedbackStore) -> None:
        """A well-formed ticket should be accepted without error."""
        ticket = _make_valid_ticket()
        store.insert_ticket(ticket)  # Should not raise


# ===========================================================================
# Clusters table CHECK constraints (Requirement 21.2, 21.3, 21.5)
# ===========================================================================


class TestClusterCheckConstraints:
    """Test CHECK constraints on the clusters table."""

    def test_theme_exceeds_120_chars_rejected(self, store: FeedbackStore) -> None:
        """theme must not exceed 120 characters."""
        with pytest.raises(Exception):
            store._conn.execute(
                """INSERT INTO clusters (
                    cluster_id, theme, cluster_summary, volume_count,
                    sentiment_trend, priority_level, first_seen_at,
                    last_seen_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_uid(), "x" * 121, None, 1, None, "medium", _NOW, _NOW, "active"),
            )

    def test_cluster_summary_exceeds_500_chars_rejected(self, store: FeedbackStore) -> None:
        """cluster_summary must not exceed 500 characters."""
        with pytest.raises(Exception):
            store._conn.execute(
                """INSERT INTO clusters (
                    cluster_id, theme, cluster_summary, volume_count,
                    sentiment_trend, priority_level, first_seen_at,
                    last_seen_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_uid(), "Valid theme", "s" * 501, 1, None, "medium", _NOW, _NOW, "active"),
            )

    def test_volume_count_below_one_rejected(self, store: FeedbackStore) -> None:
        """volume_count must be >= 1."""
        with pytest.raises(Exception):
            store._conn.execute(
                """INSERT INTO clusters (
                    cluster_id, theme, cluster_summary, volume_count,
                    sentiment_trend, priority_level, first_seen_at,
                    last_seen_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_uid(), "Valid theme", None, 0, None, "medium", _NOW, _NOW, "active"),
            )

    def test_invalid_priority_level_in_cluster_rejected(self, store: FeedbackStore) -> None:
        """priority_level must be 'low', 'medium', 'high', or 'critical'."""
        with pytest.raises(Exception):
            store._conn.execute(
                """INSERT INTO clusters (
                    cluster_id, theme, cluster_summary, volume_count,
                    sentiment_trend, priority_level, first_seen_at,
                    last_seen_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_uid(), "Valid theme", None, 1, None, "extreme", _NOW, _NOW, "active"),
            )

    def test_invalid_cluster_status_rejected(self, store: FeedbackStore) -> None:
        """status must be 'active', 'monitoring', or 'resolved'."""
        with pytest.raises(Exception):
            store._conn.execute(
                """INSERT INTO clusters (
                    cluster_id, theme, cluster_summary, volume_count,
                    sentiment_trend, priority_level, first_seen_at,
                    last_seen_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_uid(), "Valid theme", None, 1, None, "medium", _NOW, _NOW, "archived"),
            )

    def test_sentiment_trend_exceeds_50_chars_rejected(self, store: FeedbackStore) -> None:
        """sentiment_trend must not exceed 50 characters."""
        with pytest.raises(Exception):
            store._conn.execute(
                """INSERT INTO clusters (
                    cluster_id, theme, cluster_summary, volume_count,
                    sentiment_trend, priority_level, first_seen_at,
                    last_seen_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_uid(), "Valid theme", None, 1, "t" * 51, "medium", _NOW, _NOW, "active"),
            )

    def test_valid_cluster_accepted(self, store: FeedbackStore) -> None:
        """A well-formed cluster record should be accepted without error."""
        cluster = _make_valid_cluster()
        store.insert_cluster(cluster)  # Should not raise


# ===========================================================================
# Foreign Key Enforcement (Requirements 18.5, 19.5, 20.2, 20.4)
# ===========================================================================


class TestForeignKeyEnforcement:
    """Test foreign key constraints across all tables."""

    def test_analysis_references_nonexistent_feedback_rejected(self, store: FeedbackStore) -> None:
        """feedback_analysis.feedback_id must reference an existing feedback record."""
        nonexistent_fid = _uid()
        analysis = _make_valid_analysis(nonexistent_fid)
        with pytest.raises(ConstraintViolationError) as exc_info:
            store.insert_analysis(analysis)
        assert exc_info.value.constraint_type == "foreign_key_violation"

    def test_analysis_references_nonexistent_cluster_rejected(self, store: FeedbackStore) -> None:
        """feedback_analysis.cluster_id must reference an existing cluster."""
        fid = _insert_valid_feedback(store)
        analysis = _make_valid_analysis(fid, cluster_id="nonexistent-cluster-id")
        with pytest.raises(ConstraintViolationError) as exc_info:
            store.insert_analysis(analysis)
        assert exc_info.value.constraint_type == "foreign_key_violation"

    def test_ticket_references_nonexistent_cluster_rejected(self, store: FeedbackStore) -> None:
        """tickets.linked_cluster_id must reference an existing cluster."""
        ticket = _make_valid_ticket(linked_cluster_id="nonexistent-cluster-id")
        with pytest.raises(ConstraintViolationError) as exc_info:
            store.insert_ticket(ticket)
        assert exc_info.value.constraint_type == "foreign_key_violation"

    def test_link_references_nonexistent_feedback_rejected(self, store: FeedbackStore) -> None:
        """feedback_ticket_link.feedback_id must reference an existing feedback record."""
        ticket = _make_valid_ticket()
        store.insert_ticket(ticket)
        with pytest.raises(ConstraintViolationError) as exc_info:
            store.link_feedback_ticket("nonexistent-feedback-id", ticket.ticket_id)
        assert exc_info.value.constraint_type == "foreign_key_violation"

    def test_link_references_nonexistent_ticket_rejected(self, store: FeedbackStore) -> None:
        """feedback_ticket_link.ticket_id must reference an existing ticket."""
        fid = _insert_valid_feedback(store)
        with pytest.raises(ConstraintViolationError) as exc_info:
            store.link_feedback_ticket(fid, "nonexistent-ticket-id")
        assert exc_info.value.constraint_type == "foreign_key_violation"

    def test_valid_foreign_keys_accepted(self, store: FeedbackStore) -> None:
        """Valid FK references should be accepted without error."""
        cluster = _make_valid_cluster()
        store.insert_cluster(cluster)

        fid = _insert_valid_feedback(store)
        analysis = _make_valid_analysis(fid, cluster_id=cluster.cluster_id)
        store.insert_analysis(analysis)

        ticket = _make_valid_ticket(linked_cluster_id=cluster.cluster_id)
        store.insert_ticket(ticket)

        store.link_feedback_ticket(fid, ticket.ticket_id)  # Should not raise


# ===========================================================================
# Cascade Delete Behavior (Requirement 20.5, 20.6)
# ===========================================================================


class TestCascadeDeleteBehavior:
    """Test ON DELETE CASCADE on feedback_ticket_link."""

    def test_deleting_feedback_cascades_to_link(self, store: FeedbackStore) -> None:
        """Deleting a feedback record should cascade-delete its link entries."""
        fid = _insert_valid_feedback(store)
        ticket = _make_valid_ticket()
        store.insert_ticket(ticket)
        store.link_feedback_ticket(fid, ticket.ticket_id)

        # Verify link exists
        cursor = store._conn.execute(
            "SELECT COUNT(*) FROM feedback_ticket_link WHERE feedback_id = ?",
            (fid,),
        )
        assert cursor.fetchone()[0] == 1

        # Delete the feedback record
        store._conn.execute("DELETE FROM feedback WHERE feedback_id = ?", (fid,))
        store._conn.commit()

        # Link should be cascade-deleted
        cursor = store._conn.execute(
            "SELECT COUNT(*) FROM feedback_ticket_link WHERE feedback_id = ?",
            (fid,),
        )
        assert cursor.fetchone()[0] == 0

    def test_deleting_ticket_cascades_to_link(self, store: FeedbackStore) -> None:
        """Deleting a ticket record should cascade-delete its link entries."""
        fid = _insert_valid_feedback(store)
        ticket = _make_valid_ticket()
        store.insert_ticket(ticket)
        store.link_feedback_ticket(fid, ticket.ticket_id)

        # Verify link exists
        cursor = store._conn.execute(
            "SELECT COUNT(*) FROM feedback_ticket_link WHERE ticket_id = ?",
            (ticket.ticket_id,),
        )
        assert cursor.fetchone()[0] == 1

        # Delete the ticket record
        store._conn.execute("DELETE FROM tickets WHERE ticket_id = ?", (ticket.ticket_id,))
        store._conn.commit()

        # Link should be cascade-deleted
        cursor = store._conn.execute(
            "SELECT COUNT(*) FROM feedback_ticket_link WHERE ticket_id = ?",
            (ticket.ticket_id,),
        )
        assert cursor.fetchone()[0] == 0

    def test_cascade_does_not_delete_unrelated_links(self, store: FeedbackStore) -> None:
        """Deleting one feedback should not affect links for other feedback."""
        fid1 = _insert_valid_feedback(store)
        fid2 = _insert_valid_feedback(store)
        ticket = _make_valid_ticket()
        store.insert_ticket(ticket)
        store.link_feedback_ticket(fid1, ticket.ticket_id)

        # Create a second ticket for fid2
        ticket2 = _make_valid_ticket()
        store.insert_ticket(ticket2)
        store.link_feedback_ticket(fid2, ticket2.ticket_id)

        # Delete fid1
        store._conn.execute("DELETE FROM feedback WHERE feedback_id = ?", (fid1,))
        store._conn.commit()

        # fid2's link should still exist
        cursor = store._conn.execute(
            "SELECT COUNT(*) FROM feedback_ticket_link WHERE feedback_id = ?",
            (fid2,),
        )
        assert cursor.fetchone()[0] == 1


# ===========================================================================
# Duplicate feedback_id Rejection (Requirement 17.6)
# ===========================================================================


class TestDuplicateFeedbackIdRejection:
    """Test that duplicate feedback_id is rejected."""

    def test_duplicate_feedback_id_rejected(self, store: FeedbackStore) -> None:
        """Inserting a feedback record with an existing feedback_id should fail."""
        fid = _uid()
        _insert_valid_feedback(store, feedback_id=fid)

        with pytest.raises(ConstraintViolationError) as exc_info:
            store.insert_feedback(
                feedback_id=fid,
                source_type="widget",
                message_text="Another message",
                created_at_original=_NOW,
            )
        assert exc_info.value.constraint_type == "unique_violation"

    def test_duplicate_feedback_id_in_link_rejected(self, store: FeedbackStore) -> None:
        """A feedback_id can only be linked to one ticket (UNIQUE constraint)."""
        fid = _insert_valid_feedback(store)
        ticket1 = _make_valid_ticket()
        ticket2 = _make_valid_ticket()
        store.insert_ticket(ticket1)
        store.insert_ticket(ticket2)

        store.link_feedback_ticket(fid, ticket1.ticket_id)

        with pytest.raises(ConstraintViolationError) as exc_info:
            store.link_feedback_ticket(fid, ticket2.ticket_id)
        assert exc_info.value.constraint_type == "already_linked"
