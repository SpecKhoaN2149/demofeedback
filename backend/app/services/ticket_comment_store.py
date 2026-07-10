"""TicketCommentStore service for managing internal ticket comments in SQLite."""

import uuid
from datetime import datetime, timezone

from app.database import get_connection
from app.models.feedback import TicketComment


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


class TicketCommentStore:
    """Manages CRUD operations for ticket comments backed by SQLite."""

    def add(self, ticket_id: str, author: str, text: str) -> TicketComment:
        """Create a comment on a ticket.

        Args:
            ticket_id: The ticket to attach the comment to.
            author: The admin username recorded as the comment author.
            text: The comment body. Must be non-empty after stripping whitespace.

        Returns:
            The created TicketComment.

        Raises:
            ValueError: If ``text`` is empty or whitespace-only (Req 7.2).
                The route layer translates this to a 422.
            LookupError: If ``ticket_id`` does not reference an existing ticket
                (Req 7.3). The route layer translates this to a 404.
        """
        if not text or not text.strip():
            raise ValueError("Comment text must not be empty or whitespace-only.")

        tid = str(ticket_id)
        created_at = _utcnow_iso()

        with get_connection() as conn:
            # Verify the ticket exists before inserting (Req 7.3).
            exists = conn.execute(
                "SELECT 1 FROM tickets WHERE ticket_id = ?", (tid,)
            ).fetchone()
            if exists is None:
                raise LookupError(f"Ticket not found: {tid}")

            cursor = conn.execute(
                """
                INSERT INTO ticket_comments (ticket_id, author, created_at, text)
                VALUES (?, ?, ?, ?)
                """,
                (tid, author, created_at, text),
            )
            conn.commit()
            comment_id = cursor.lastrowid

        return TicketComment(
            id=comment_id,
            ticket_id=uuid.UUID(tid),
            author=author,
            created_at=datetime.fromisoformat(created_at),
            text=text,
        )

    def list_for_ticket(self, ticket_id: str) -> list[TicketComment]:
        """Return all comments for a ticket ordered by created_at ascending.

        Equal timestamps are tie-broken by the autoincrement ``id`` so ordering
        is stable and deterministic (Req 7.5, 8.5).
        """
        tid = str(ticket_id)

        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, ticket_id, author, created_at, text
                FROM ticket_comments
                WHERE ticket_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (tid,),
            ).fetchall()

        return [
            TicketComment(
                id=row["id"],
                ticket_id=uuid.UUID(row["ticket_id"]),
                author=row["author"],
                created_at=datetime.fromisoformat(row["created_at"]),
                text=row["text"],
            )
            for row in rows
        ]
