"""TicketingPipeline service for managing independent support tickets.

Tickets are their own entities (`tickets` table, keyed by `ticket_id`). The
link between feedback and a ticket lives on the feedback side
(`feedback.ticket_id`), so a ticket may have many feedback records linked to
it (many-to-one). Ticket status follows the state machine
open -> in_progress -> resolved and is surfaced to customers via the feedback
status view rather than by mutating legacy submission tables.
"""

import uuid
from datetime import datetime, timezone

from app.database import get_connection
from app.models.ticket import Ticket, TicketDetail, TicketWithCount


# Valid status transitions: current_status -> next_status
_VALID_TRANSITIONS: dict[str, str] = {
    "open": "in_progress",
    "in_progress": "resolved",
}


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _ticket_from_row(row) -> Ticket:
    """Build a Ticket model from a `tickets` table row."""
    return Ticket(
        ticket_id=uuid.UUID(row["ticket_id"]),
        issue_category=row["issue_category"],
        description=row["description"],
        priority=row["priority"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class TicketingPipeline:
    """Manages independent support tickets and their feedback linkage.

    Creates high-priority tickets, links feedback records to them, and enforces
    the status transition state machine: open -> in_progress -> resolved.
    """

    def create_ticket(
        self,
        *,
        feedback_id: str,
        issue_category: str,
        description: str,
        priority: str = "high",
    ) -> Ticket:
        """Create a new ticket and link the originating feedback to it.

        Inserts a new `tickets` row (status 'open') and sets
        `feedback.ticket_id` on the originating feedback record.

        Args:
            feedback_id: UUID string of the feedback that triggered the ticket.
            issue_category: Issue category for the ticket.
            description: Detailed description of the issue (max 5000 chars).
            priority: Ticket priority (defaults to 'high').

        Returns:
            The created Ticket model instance.
        """
        ticket_id = str(uuid.uuid4())
        created_at = _utcnow_iso()

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO tickets (ticket_id, issue_category, description, priority, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    issue_category,
                    description,
                    priority,
                    "open",
                    created_at,
                ),
            )
            conn.execute(
                "UPDATE feedback SET ticket_id = ? WHERE feedback_id = ?",
                (ticket_id, feedback_id),
            )
            conn.commit()

        return Ticket(
            ticket_id=uuid.UUID(ticket_id),
            issue_category=issue_category,
            description=description,
            priority=priority,
            status="open",
            created_at=datetime.fromisoformat(created_at),
        )

    def link_feedback(self, ticket_id: str, feedback_id: str) -> None:
        """Link a feedback record to an existing ticket.

        Succeeds for any valid ticket regardless of how many feedback records
        are already linked (including zero).

        Args:
            ticket_id: UUID string of the target ticket.
            feedback_id: UUID string of the feedback to link.

        Raises:
            ValueError: If the ticket does not exist.
        """
        with get_connection() as conn:
            row = conn.execute(
                "SELECT ticket_id FROM tickets WHERE ticket_id = ?", (ticket_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Ticket not found: {ticket_id}")

            conn.execute(
                "UPDATE feedback SET ticket_id = ? WHERE feedback_id = ?",
                (ticket_id, feedback_id),
            )
            conn.commit()

    def advance_status(self, ticket_id: str) -> Ticket:
        """Advance a ticket to the next valid status.

        Enforces the state machine: open -> in_progress -> resolved. The new
        status is surfaced to customers through the feedback status view; no
        legacy submission/state_transition rows are touched.

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
                "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
            ).fetchone()

            if row is None:
                raise ValueError(f"Ticket not found: {ticket_id}")

            current_status = row["status"]
            new_status = _VALID_TRANSITIONS.get(current_status)

            if new_status is None:
                raise ValueError(
                    f"Invalid status transition: cannot advance from '{current_status}'"
                )

            conn.execute(
                "UPDATE tickets SET status = ? WHERE ticket_id = ?",
                (new_status, ticket_id),
            )
            conn.commit()

        return Ticket(
            ticket_id=uuid.UUID(row["ticket_id"]),
            issue_category=row["issue_category"],
            description=row["description"],
            priority=row["priority"],
            status=new_status,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_with_counts(
        self, statuses: tuple[str, ...] | None = None
    ) -> list[TicketWithCount]:
        """Return tickets with their linked feedback counts, optionally filtered.

        Each result carries `linked_feedback_count`, the number of feedback
        records whose `ticket_id` points at the ticket. Ordered by created_at
        ascending.

        Args:
            statuses: When provided, only tickets whose status is in this set
                are returned. When None, all tickets are returned.

        Returns:
            List of TicketWithCount model instances.
        """
        where = ""
        params: list = []
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            where = f"WHERE t.status IN ({placeholders})"
            params = list(statuses)

        with get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT t.*,
                       (SELECT COUNT(*) FROM feedback f WHERE f.ticket_id = t.ticket_id)
                           AS linked_feedback_count
                FROM tickets t
                {where}
                ORDER BY t.created_at ASC
                """,
                params,
            ).fetchall()

        return [
            TicketWithCount(
                ticket_id=uuid.UUID(row["ticket_id"]),
                issue_category=row["issue_category"],
                description=row["description"],
                priority=row["priority"],
                status=row["status"],
                created_at=datetime.fromisoformat(row["created_at"]),
                linked_feedback_count=row["linked_feedback_count"],
            )
            for row in rows
        ]

    def list_active_with_counts(self) -> list[TicketWithCount]:
        """Return active (open/in_progress) tickets with linked feedback counts."""
        return self.list_with_counts(("open", "in_progress"))

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        """Retrieve a single ticket by ID.

        Args:
            ticket_id: UUID string of the ticket to retrieve.

        Returns:
            The Ticket model instance, or None if not found.
        """
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
            ).fetchone()

        if row is None:
            return None

        return _ticket_from_row(row)

    def get_with_feedback_ids(self, ticket_id: str) -> TicketDetail | None:
        """Retrieve a ticket along with the ids of all linked feedback.

        Args:
            ticket_id: UUID string of the ticket to retrieve.

        Returns:
            A TicketDetail model instance, or None if the ticket is not found.
        """
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
            ).fetchone()

            if row is None:
                return None

            feedback_rows = conn.execute(
                "SELECT feedback_id FROM feedback WHERE ticket_id = ? ORDER BY created_at ASC",
                (ticket_id,),
            ).fetchall()

        return TicketDetail(
            ticket_id=uuid.UUID(row["ticket_id"]),
            issue_category=row["issue_category"],
            description=row["description"],
            priority=row["priority"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            feedback_ids=[uuid.UUID(fr["feedback_id"]) for fr in feedback_rows],
        )
