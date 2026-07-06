"""AdminReviewQueue service for managing neutral submission review queue."""

import json
from datetime import datetime, timezone
from typing import Any

from app.database import get_connection


def _parse_enrichment_summary(raw: str | None) -> dict[str, Any] | None:
    """Parse a stored enrichment_result JSON string into a UI-friendly summary.

    Returns None when there is no enrichment result yet (e.g. pending/failed).
    The summary exposes the fields the admin UI renders: themes, severity,
    sentiment confidence, severity factors, and detected language.
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return {
        "themes": data.get("themes", []),
        "severity_score": data.get("severity_score"),
        "severity_factors": data.get("severity_factors", []),
        "sentiment_confidence": data.get("sentiment_confidence"),
        "language_code": data.get("language_code"),
        "language_confidence": data.get("language_confidence"),
    }


class AdminReviewQueue:
    """Manages the admin review queue for neutral submissions.

    Neutral submissions are enqueued for manual classification by admin staff.
    The queue is ordered by queued_at timestamp ascending (oldest first).
    """

    def enqueue(self, submission_id: str) -> None:
        """Insert a submission into the admin review queue.

        Args:
            submission_id: The UUID string of the submission to enqueue.
        """
        queued_at = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO admin_review_queue (submission_id, queued_at) VALUES (?, ?)",
                (submission_id, queued_at),
            )
            conn.commit()

    def list_queue(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        """Return paginated queue entries ordered by queued_at ascending (oldest first).

        Joins with the submissions table to return submission details including
        timestamp, customer_name, comment_text, and enrichment_result.

        Args:
            limit: Maximum number of entries to return (default 20).
            offset: Number of entries to skip (default 0).

        Returns:
            List of dicts with queue entry and submission details.
        """
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    arq.submission_id,
                    arq.queued_at,
                    s.created_at,
                    s.customer_name,
                    s.comment_text,
                    s.enrichment_status,
                    s.enrichment_result
                FROM admin_review_queue arq
                JOIN submissions s ON arq.submission_id = s.id
                ORDER BY arq.queued_at ASC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

        return [
            {
                "submission_id": row["submission_id"],
                "queued_at": row["queued_at"],
                "created_at": row["created_at"],
                "customer_name": row["customer_name"],
                "comment_text": row["comment_text"],
                "enrichment_status": row["enrichment_status"],
                "enrichment_summary": _parse_enrichment_summary(
                    row["enrichment_result"]
                ),
            }
            for row in rows
        ]

    def remove(self, submission_id: str) -> None:
        """Remove a submission from the admin review queue.

        Args:
            submission_id: The UUID string of the submission to remove.
        """
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM admin_review_queue WHERE submission_id = ?",
                (submission_id,),
            )
            conn.commit()

    def is_queued(self, submission_id: str) -> bool:
        """Check if a submission is currently in the admin review queue.

        Args:
            submission_id: The UUID string of the submission to check.

        Returns:
            True if the submission is in the queue, False otherwise.
        """
        with get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM admin_review_queue WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
        return row is not None
