"""TicketingPipeline service for managing support tickets from negative submissions."""

import uuid
from datetime import datetime, timezone

from app.database import get_connection
from app.models.ticket import Ticket


# Valid status transitions: current_status → next_status
_VALID_TRANSITIONS: dict[str, str] = {
    "open": "in_progress",
    "in_progress": "resolved",
}

# Progress state associated with each ticket status transition target
_STATUS_PROGRESS_MAP: dict[str, int] = {
    "in_progress": 75,
    "resolved": 100,
}


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


class TicketingPipeline:
    """Manages support tickets for negative-sentiment submissions.

    Creates high-priority tickets linked to submissions and enforces the
    status transition state machine: open → in_progress → resolved.
    When a ticket advances, the linked submission's progress state is updated.
    """

    def create_ticket(
        self, submission_id: str, category: str, description: str
    ) -> Ticket:
        """Create a new high-priority ticket linked to a submission.

        Args:
            submission_id: UUID string of the linked submission.
            category: Issue category from the predefined set.
            description: Detailed description of the issue (max 5000 chars).

        Returns:
            The created Ticket model instance.
        """
        ticket_id = str(uuid.uuid4())
        created_at = _utcnow_iso()

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO tickets (id, submission_id, issue_category, description, priority, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    submission_id,
                    category,
                    description,
                    "high",
                    "open",
                    created_at,
                ),
            )
            conn.commit()

        return Ticket(
            id=uuid.UUID(ticket_id),
            submission_id=uuid.UUID(submission_id),
            issue_category=category,
            description=description,
            priority="high",
            status="open",
            created_at=datetime.fromisoformat(created_at),
        )

    def advance_status(self, ticket_id: str) -> Ticket:
        """Advance a ticket to the next valid status.

        Enforces the state machine: open → in_progress → resolved.
        Updates the linked submission's progress state accordingly:
        - in_progress → submission progress 75%
        - resolved → submission progress 100%

        Args:
            ticket_id: UUID string of the ticket to advance.

        Returns:
            The updated Ticket model instance.

        Raises:
            ValueError: If the ticket is not found or the transition is invalid
                (e.g., ticket is already resolved).
        """
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
            ).fetchone()

            if row is None:
                raise ValueError(f"Ticket not found: {ticket_id}")

            current_status = row["status"]
            new_status = _VALID_TRANSITIONS.get(current_status)

            if new_status is None:
                raise ValueError(
                    f"Invalid status transition: cannot advance from '{current_status}'"
                )

            # Update ticket status
            conn.execute(
                "UPDATE tickets SET status = ? WHERE id = ?",
                (new_status, ticket_id),
            )

            # Update linked submission progress state
            submission_id = row["submission_id"]
            new_progress = _STATUS_PROGRESS_MAP[new_status]
            previous_progress = conn.execute(
                "SELECT progress_state FROM submissions WHERE id = ?",
                (submission_id,),
            ).fetchone()["progress_state"]

            conn.execute(
                "UPDATE submissions SET progress_state = ? WHERE id = ?",
                (new_progress, submission_id),
            )

            # Record state transition on the submission
            transition_timestamp = _utcnow_iso()
            conn.execute(
                """
                INSERT INTO state_transitions (submission_id, previous_state, new_state, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (submission_id, previous_progress, new_progress, transition_timestamp),
            )

            conn.commit()

        return Ticket(
            id=uuid.UUID(row["id"]),
            submission_id=uuid.UUID(row["submission_id"]),
            issue_category=row["issue_category"],
            description=row["description"],
            priority=row["priority"],
            status=new_status,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_active(self) -> list[Ticket]:
        """Return all tickets with status 'open' or 'in_progress', ordered by created_at ascending.

        Returns:
            List of Ticket model instances for active tickets.
        """
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tickets
                WHERE status IN ('open', 'in_progress')
                ORDER BY created_at ASC
                """,
            ).fetchall()

        return [
            Ticket(
                id=uuid.UUID(row["id"]),
                submission_id=uuid.UUID(row["submission_id"]),
                issue_category=row["issue_category"],
                description=row["description"],
                priority=row["priority"],
                status=row["status"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        """Retrieve a single ticket by ID.

        Args:
            ticket_id: UUID string of the ticket to retrieve.

        Returns:
            The Ticket model instance, or None if not found.
        """
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
            ).fetchone()

        if row is None:
            return None

        return Ticket(
            id=uuid.UUID(row["id"]),
            submission_id=uuid.UUID(row["submission_id"]),
            issue_category=row["issue_category"],
            description=row["description"],
            priority=row["priority"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
