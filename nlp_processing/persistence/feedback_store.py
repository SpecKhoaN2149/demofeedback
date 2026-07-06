"""Feedback routing persistence layer.

Implements Requirements 15, 17, 18, 19, 20, 21:
- Insert and retrieve feedback, analysis, ticket, link, and cluster records.
- Enforce ticket phase transition matrix with audit trail recording.
- Handle constraint violations with specific error messages per constraint type.
- Cascade delete behavior via ON DELETE CASCADE (schema-enforced).

Uses SQLite with WAL mode and foreign key enforcement.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from nlp_processing.models.feedback_routing import (
    ClusterRecord,
    FeedbackAnalysis,
    Ticket,
)
from nlp_processing.persistence.feedback_schema import initialize_feedback_schema


# ---------------------------------------------------------------------------
# Valid ticket phase transitions (Requirement 15.1)
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[str, list[str]] = {
    "new": ["triaged"],
    "triaged": ["routed"],
    "routed": ["in_progress"],
    "in_progress": ["waiting", "resolved"],
    "waiting": ["in_progress", "resolved"],
    "resolved": ["closed"],
    "closed": [],  # terminal
    "auto_closed": [],  # terminal
}


class FeedbackStoreError(Exception):
    """Base exception for FeedbackStore operations."""


class ConstraintViolationError(FeedbackStoreError):
    """Raised when a database constraint is violated."""

    def __init__(self, message: str, constraint_type: str) -> None:
        super().__init__(message)
        self.constraint_type = constraint_type


class InvalidTransitionError(FeedbackStoreError):
    """Raised when an invalid ticket phase transition is attempted."""

    def __init__(self, current_phase: str, requested_phase: str, valid_phases: list[str]) -> None:
        msg = (
            f"Invalid transition from '{current_phase}' to '{requested_phase}'. "
            f"Valid next phases: {valid_phases}"
        )
        super().__init__(msg)
        self.current_phase = current_phase
        self.requested_phase = requested_phase
        self.valid_phases = valid_phases


class FeedbackStore:
    """Relational persistence for feedback routing data.

    Manages feedback, analysis, ticket, feedback-ticket link, and cluster
    records with constraint enforcement and ticket lifecycle management.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        """Initialize FeedbackStore with schema creation.

        Parameters
        ----------
        db_path : str
            SQLite database path. Use ":memory:" for testing.
        """
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        initialize_feedback_schema(self._conn)

    # ------------------------------------------------------------------
    # Feedback operations (Requirement 17)
    # ------------------------------------------------------------------

    def insert_feedback(
        self,
        feedback_id: str,
        source_type: str,
        message_text: str,
        created_at_original: str,
        *,
        platform: str | None = None,
        customer_id: str | None = None,
        ingested_at: str | None = None,
        recency_score: float | None = None,
        channel_metadata: dict | None = None,
        processing_status: str = "ingested",
        routing_action: str | None = None,
    ) -> None:
        """Insert a feedback record.

        Parameters
        ----------
        feedback_id : str
            Unique UUID for the feedback record.
        source_type : str
            Must be "social" or "widget".
        message_text : str
            The feedback text (1–10000 chars, non-whitespace).
        created_at_original : str
            Original creation timestamp in ISO 8601 UTC.
        platform : str | None
            Source platform (max 50 chars).
        customer_id : str | None
            Customer identifier (max 100 chars).
        ingested_at : str | None
            Ingestion timestamp. Auto-populated if None.
        recency_score : float | None
            Score between 0.0 and 1.0.
        channel_metadata : dict | None
            Additional metadata as JSON-serializable dict.
        processing_status : str
            Processing status enum value. Default "ingested".
        routing_action : str | None
            Routing action string (max 50 chars).

        Raises
        ------
        ConstraintViolationError
            If any constraint is violated.
        """
        metadata_json = json.dumps(channel_metadata) if channel_metadata else None

        # Requirement 17.7: auto-populate ingested_at if not provided
        if ingested_at is None:
            ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            self._conn.execute(
                """INSERT INTO feedback (
                    feedback_id, source_type, platform, message_text,
                    customer_id, created_at_original, ingested_at,
                    recency_score, channel_metadata, processing_status,
                    routing_action
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    feedback_id,
                    source_type,
                    platform,
                    message_text,
                    customer_id,
                    created_at_original,
                    ingested_at,
                    recency_score,
                    metadata_json,
                    processing_status,
                    routing_action,
                ),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            self._conn.rollback()
            raise self._map_feedback_error(exc, feedback_id) from exc
        except sqlite3.Error as exc:
            self._conn.rollback()
            raise FeedbackStoreError(f"Failed to insert feedback: {exc}") from exc

    def _map_feedback_error(
        self, exc: sqlite3.IntegrityError, feedback_id: str
    ) -> ConstraintViolationError:
        """Map a SQLite IntegrityError to a specific constraint violation."""
        msg = str(exc).lower()

        if "unique" in msg or "primary" in msg:
            return ConstraintViolationError(
                f"Duplicate feedback_id: '{feedback_id}' already exists.",
                constraint_type="unique_violation",
            )
        if "check" in msg:
            if "source_type" in msg:
                return ConstraintViolationError(
                    "Invalid source_type. Must be 'social' or 'widget'.",
                    constraint_type="enum_violation",
                )
            if "message_text" in msg:
                return ConstraintViolationError(
                    "message_text must be non-empty and at most 10000 characters.",
                    constraint_type="text_constraint_violation",
                )
            if "recency_score" in msg:
                return ConstraintViolationError(
                    "recency_score must be between 0.0 and 1.0.",
                    constraint_type="range_violation",
                )
            if "processing_status" in msg:
                return ConstraintViolationError(
                    "Invalid processing_status value.",
                    constraint_type="enum_violation",
                )
            if "platform" in msg:
                return ConstraintViolationError(
                    "platform must not exceed 50 characters.",
                    constraint_type="length_violation",
                )
            if "customer_id" in msg:
                return ConstraintViolationError(
                    "customer_id must not exceed 100 characters.",
                    constraint_type="length_violation",
                )
            return ConstraintViolationError(
                f"CHECK constraint violated: {exc}",
                constraint_type="check_violation",
            )
        if "not null" in msg:
            return ConstraintViolationError(
                f"NOT NULL constraint violated: {exc}",
                constraint_type="not_null_violation",
            )

        return ConstraintViolationError(
            f"Constraint violation: {exc}",
            constraint_type="unknown",
        )

    # ------------------------------------------------------------------
    # Analysis operations (Requirement 18)
    # ------------------------------------------------------------------

    def insert_analysis(self, analysis: FeedbackAnalysis) -> None:
        """Insert a feedback analysis record.

        Parameters
        ----------
        analysis : FeedbackAnalysis
            The NLP analysis result to persist.

        Raises
        ------
        ConstraintViolationError
            If any constraint is violated (FK, range, enum).
        """
        entities_json = (
            json.dumps([e.model_dump() for e in analysis.entities])
            if analysis.entities
            else None
        )

        try:
            self._conn.execute(
                """INSERT INTO feedback_analysis (
                    feedback_id, sentiment_label, sentiment_score,
                    priority_score, priority_level, theme_primary,
                    theme_secondary, intent, cluster_id,
                    requires_action, entities, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    analysis.feedback_id,
                    analysis.sentiment_label,
                    analysis.sentiment_score,
                    analysis.priority_score,
                    analysis.priority_level,
                    analysis.theme_primary,
                    analysis.theme_secondary,
                    analysis.intent,
                    analysis.cluster_id,
                    int(analysis.requires_action),
                    entities_json,
                    analysis.processed_at,
                ),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            self._conn.rollback()
            raise self._map_analysis_error(exc, analysis.feedback_id) from exc
        except sqlite3.Error as exc:
            self._conn.rollback()
            raise FeedbackStoreError(f"Failed to insert analysis: {exc}") from exc

    def _map_analysis_error(
        self, exc: sqlite3.IntegrityError, feedback_id: str
    ) -> ConstraintViolationError:
        """Map analysis insert errors to specific constraint violations."""
        msg = str(exc).lower()

        if "unique" in msg or "primary" in msg:
            return ConstraintViolationError(
                f"Analysis for feedback_id '{feedback_id}' already exists.",
                constraint_type="unique_violation",
            )
        if "foreign" in msg:
            if "cluster" in msg:
                return ConstraintViolationError(
                    "Referenced cluster_id does not exist.",
                    constraint_type="foreign_key_violation",
                )
            return ConstraintViolationError(
                f"Referenced feedback_id '{feedback_id}' does not exist in feedback table.",
                constraint_type="foreign_key_violation",
            )
        if "check" in msg:
            if "sentiment_score" in msg:
                return ConstraintViolationError(
                    "sentiment_score must be between -1.0 and 1.0.",
                    constraint_type="range_violation",
                )
            if "priority_score" in msg:
                return ConstraintViolationError(
                    "priority_score must be between 0.0 and 1.0.",
                    constraint_type="range_violation",
                )
            if "sentiment_label" in msg:
                return ConstraintViolationError(
                    "Invalid sentiment_label. Must be 'positive', 'neutral', or 'negative'.",
                    constraint_type="enum_violation",
                )
            if "priority_level" in msg:
                return ConstraintViolationError(
                    "Invalid priority_level. Must be 'low', 'medium', 'high', or 'critical'.",
                    constraint_type="enum_violation",
                )
            return ConstraintViolationError(
                f"CHECK constraint violated: {exc}",
                constraint_type="check_violation",
            )

        return ConstraintViolationError(
            f"Constraint violation: {exc}",
            constraint_type="unknown",
        )

    # ------------------------------------------------------------------
    # Ticket operations (Requirement 19)
    # ------------------------------------------------------------------

    def insert_ticket(self, ticket: Ticket) -> None:
        """Insert a ticket record.

        Parameters
        ----------
        ticket : Ticket
            The ticket to persist.

        Raises
        ------
        ConstraintViolationError
            If any constraint is violated.
        """
        try:
            self._conn.execute(
                """INSERT INTO tickets (
                    ticket_id, ticket_phase, priority_level,
                    assigned_department, created_at, updated_at,
                    resolution_type, resolution_notes, linked_cluster_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticket.ticket_id,
                    ticket.ticket_phase,
                    ticket.priority_level,
                    ticket.assigned_department,
                    ticket.created_at,
                    ticket.updated_at,
                    ticket.resolution_type,
                    ticket.resolution_notes,
                    ticket.linked_cluster_id,
                ),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            self._conn.rollback()
            raise self._map_ticket_error(exc, ticket.ticket_id) from exc
        except sqlite3.Error as exc:
            self._conn.rollback()
            raise FeedbackStoreError(f"Failed to insert ticket: {exc}") from exc

    def _map_ticket_error(
        self, exc: sqlite3.IntegrityError, ticket_id: str
    ) -> ConstraintViolationError:
        """Map ticket insert errors to specific constraint violations."""
        msg = str(exc).lower()

        if "unique" in msg or "primary" in msg:
            return ConstraintViolationError(
                f"Duplicate ticket_id: '{ticket_id}' already exists.",
                constraint_type="unique_violation",
            )
        if "foreign" in msg:
            return ConstraintViolationError(
                "Referenced linked_cluster_id does not exist in clusters table.",
                constraint_type="foreign_key_violation",
            )
        if "check" in msg:
            if "ticket_phase" in msg:
                return ConstraintViolationError(
                    "Invalid ticket_phase value.",
                    constraint_type="enum_violation",
                )
            if "priority_level" in msg:
                return ConstraintViolationError(
                    "Invalid priority_level. Must be 'low', 'medium', 'high', or 'critical'.",
                    constraint_type="enum_violation",
                )
            if "assigned_department" in msg:
                return ConstraintViolationError(
                    "Invalid assigned_department value.",
                    constraint_type="enum_violation",
                )
            if "resolution_type" in msg:
                return ConstraintViolationError(
                    "Invalid resolution_type value.",
                    constraint_type="enum_violation",
                )
            if "resolution_notes" in msg:
                return ConstraintViolationError(
                    "resolution_notes must not exceed 2000 characters.",
                    constraint_type="length_violation",
                )
            return ConstraintViolationError(
                f"CHECK constraint violated: {exc}",
                constraint_type="check_violation",
            )

        return ConstraintViolationError(
            f"Constraint violation: {exc}",
            constraint_type="unknown",
        )

    # ------------------------------------------------------------------
    # Ticket phase transition (Requirement 15)
    # ------------------------------------------------------------------

    def transition_ticket_phase(
        self, ticket_id: str, new_phase: str, actor: str
    ) -> None:
        """Transition a ticket to a new phase with audit trail.

        Enforces the valid transition matrix. Records previous phase, new
        phase, transition timestamp, and actor in the audit trail.

        Parameters
        ----------
        ticket_id : str
            The ticket to transition.
        new_phase : str
            The desired next phase.
        actor : str
            The system component or user who triggered the transition
            (max 150 characters).

        Raises
        ------
        InvalidTransitionError
            If the transition violates the allowed sequences.
        ConstraintViolationError
            If the ticket doesn't exist or resolution_type is required but missing.
        FeedbackStoreError
            On other storage errors.
        """
        # Fetch current phase
        cursor = self._conn.execute(
            "SELECT ticket_phase, resolution_type FROM tickets WHERE ticket_id = ?",
            (ticket_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ConstraintViolationError(
                f"Ticket '{ticket_id}' does not exist.",
                constraint_type="not_found",
            )

        current_phase = row[0]
        valid_next = _VALID_TRANSITIONS.get(current_phase, [])

        # Check if transition is valid (Req 15.1, 15.7)
        if new_phase not in valid_next:
            raise InvalidTransitionError(current_phase, new_phase, valid_next)

        # Requirement 15.5, 15.6: resolved requires resolution_type
        if new_phase == "resolved":
            # Check if resolution_type is already set on the ticket
            existing_resolution = row[1]
            if not existing_resolution:
                raise ConstraintViolationError(
                    "Transition to 'resolved' requires a valid resolution_type. "
                    "Set resolution_type on the ticket before transitioning to 'resolved'.",
                    constraint_type="missing_resolution_type",
                )

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            # Update the ticket phase and updated_at (Req 15.4)
            self._conn.execute(
                "UPDATE tickets SET ticket_phase = ?, updated_at = ? WHERE ticket_id = ?",
                (new_phase, now, ticket_id),
            )

            # Record the audit trail (Req 15.3)
            self._ensure_audit_table()
            self._conn.execute(
                """INSERT INTO ticket_phase_audit (
                    ticket_id, previous_phase, new_phase,
                    transition_timestamp, actor
                ) VALUES (?, ?, ?, ?, ?)""",
                (ticket_id, current_phase, new_phase, now, actor[:150]),
            )

            self._conn.commit()
        except sqlite3.Error as exc:
            self._conn.rollback()
            raise FeedbackStoreError(
                f"Failed to transition ticket phase: {exc}"
            ) from exc

    def _ensure_audit_table(self) -> None:
        """Create the audit trail table if it doesn't exist."""
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS ticket_phase_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL,
                previous_phase TEXT NOT NULL,
                new_phase TEXT NOT NULL,
                transition_timestamp TEXT NOT NULL,
                actor TEXT NOT NULL CHECK (length(actor) <= 150)
            )"""
        )

    # ------------------------------------------------------------------
    # Feedback-Ticket Link operations (Requirement 20)
    # ------------------------------------------------------------------

    def link_feedback_ticket(self, feedback_id: str, ticket_id: str) -> None:
        """Create a feedback-to-ticket association.

        Parameters
        ----------
        feedback_id : str
            The feedback record to link.
        ticket_id : str
            The ticket to link to.

        Raises
        ------
        ConstraintViolationError
            If the feedback is already linked, or referenced records don't exist.
        """
        try:
            self._conn.execute(
                "INSERT INTO feedback_ticket_link (feedback_id, ticket_id) VALUES (?, ?)",
                (feedback_id, ticket_id),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            self._conn.rollback()
            msg = str(exc).lower()
            if "unique" in msg:
                raise ConstraintViolationError(
                    f"Feedback '{feedback_id}' is already linked to a ticket.",
                    constraint_type="already_linked",
                ) from exc
            if "foreign" in msg:
                # Determine which FK is violated
                cursor = self._conn.execute(
                    "SELECT 1 FROM feedback WHERE feedback_id = ?", (feedback_id,)
                )
                if cursor.fetchone() is None:
                    raise ConstraintViolationError(
                        f"Referenced feedback_id '{feedback_id}' does not exist.",
                        constraint_type="foreign_key_violation",
                    ) from exc
                raise ConstraintViolationError(
                    f"Referenced ticket_id '{ticket_id}' does not exist.",
                    constraint_type="foreign_key_violation",
                ) from exc
            raise ConstraintViolationError(
                f"Constraint violation: {exc}",
                constraint_type="unknown",
            ) from exc
        except sqlite3.Error as exc:
            self._conn.rollback()
            raise FeedbackStoreError(
                f"Failed to link feedback to ticket: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Cluster operations (Requirement 21)
    # ------------------------------------------------------------------

    def insert_cluster(self, cluster: ClusterRecord) -> None:
        """Insert a cluster record.

        Parameters
        ----------
        cluster : ClusterRecord
            The cluster to persist.

        Raises
        ------
        ConstraintViolationError
            If any constraint is violated.
        """
        try:
            self._conn.execute(
                """INSERT INTO clusters (
                    cluster_id, theme, cluster_summary, volume_count,
                    sentiment_trend, priority_level, first_seen_at,
                    last_seen_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cluster.cluster_id,
                    cluster.theme,
                    cluster.cluster_summary,
                    cluster.volume_count,
                    cluster.sentiment_trend,
                    cluster.priority_level,
                    cluster.first_seen_at,
                    cluster.last_seen_at,
                    cluster.status,
                ),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            self._conn.rollback()
            raise self._map_cluster_error(exc, cluster.cluster_id) from exc
        except sqlite3.Error as exc:
            self._conn.rollback()
            raise FeedbackStoreError(f"Failed to insert cluster: {exc}") from exc

    def _map_cluster_error(
        self, exc: sqlite3.IntegrityError, cluster_id: str
    ) -> ConstraintViolationError:
        """Map cluster insert errors to specific constraint violations."""
        msg = str(exc).lower()

        if "unique" in msg or "primary" in msg:
            return ConstraintViolationError(
                f"Duplicate cluster_id: '{cluster_id}' already exists.",
                constraint_type="unique_violation",
            )
        if "check" in msg:
            if "theme" in msg:
                return ConstraintViolationError(
                    "theme must not exceed 120 characters.",
                    constraint_type="length_violation",
                )
            if "cluster_summary" in msg:
                return ConstraintViolationError(
                    "cluster_summary must not exceed 500 characters.",
                    constraint_type="length_violation",
                )
            if "volume_count" in msg:
                return ConstraintViolationError(
                    "volume_count must be at least 1.",
                    constraint_type="range_violation",
                )
            if "priority_level" in msg:
                return ConstraintViolationError(
                    "Invalid priority_level. Must be 'low', 'medium', 'high', or 'critical'.",
                    constraint_type="enum_violation",
                )
            if "status" in msg:
                return ConstraintViolationError(
                    "Invalid status. Must be 'active', 'monitoring', or 'resolved'.",
                    constraint_type="enum_violation",
                )
            if "sentiment_trend" in msg:
                return ConstraintViolationError(
                    "sentiment_trend must not exceed 50 characters.",
                    constraint_type="length_violation",
                )
            return ConstraintViolationError(
                f"CHECK constraint violated: {exc}",
                constraint_type="check_violation",
            )

        return ConstraintViolationError(
            f"Constraint violation: {exc}",
            constraint_type="unknown",
        )

    def update_cluster(self, cluster_id: str, volume_increment: int = 1) -> None:
        """Atomically increment cluster volume and update last_seen_at.

        Parameters
        ----------
        cluster_id : str
            The cluster to update.
        volume_increment : int
            Amount to add to volume_count. Default is 1.

        Raises
        ------
        ConstraintViolationError
            If the cluster doesn't exist.
        FeedbackStoreError
            On storage errors.
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            cursor = self._conn.execute(
                """UPDATE clusters
                   SET volume_count = volume_count + ?,
                       last_seen_at = ?
                   WHERE cluster_id = ?""",
                (volume_increment, now, cluster_id),
            )
            if cursor.rowcount == 0:
                raise ConstraintViolationError(
                    f"Cluster '{cluster_id}' does not exist.",
                    constraint_type="not_found",
                )
            self._conn.commit()
        except ConstraintViolationError:
            self._conn.rollback()
            raise
        except sqlite3.Error as exc:
            self._conn.rollback()
            raise FeedbackStoreError(
                f"Failed to update cluster: {exc}"
            ) from exc

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
