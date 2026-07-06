"""SubmissionStore service for managing customer submissions in SQLite."""

import json
import uuid
from datetime import datetime, timezone

from app.database import get_connection
from app.models.submission import (
    EnrichmentResult,
    StateTransition,
    StatusResponse,
    Submission,
    SubmissionCreate,
)

# Initial progress state based on sentiment route
_INITIAL_PROGRESS: dict[str, int] = {
    "negative": 50,
    "positive": 100,
    "neutral": 25,
}

# Message mapping: (progress_state, sentiment) → message
_MESSAGES: dict[int, str] = {
    25: "Awaiting Review",
    50: "Spectrum is working on this.",
    75: "Almost there — resolution in progress.",
}

# Completion messages are sentiment-specific
_COMPLETION_MESSAGES: dict[str, str] = {
    "positive": "Praise received & noted!",
    "negative": "Your issue has been resolved.",
    "neutral": "Your issue has been resolved.",
}


def _get_message(progress_state: int, sentiment: str) -> str:
    """Return the status message for a given progress state and sentiment."""
    if progress_state == 100:
        return _COMPLETION_MESSAGES.get(sentiment, "Your issue has been resolved.")
    return _MESSAGES.get(progress_state, "Awaiting Review")


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


class SubmissionStore:
    """Manages CRUD operations for customer submissions backed by SQLite."""

    def create(self, data: SubmissionCreate) -> Submission:
        """Create a new submission with initial progress based on sentiment.

        Generates a UUID, sets progress from sentiment mapping, persists to SQLite,
        and records the initial state transition (0 → initial_progress).
        """
        submission_id = str(uuid.uuid4())
        created_at = _utcnow_iso()
        initial_progress = _INITIAL_PROGRESS[data.sentiment]

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO submissions (
                    id, created_at, customer_name, email, phone, core_request,
                    sentiment, progress_state, issue_category, detailed_description,
                    praise_text, social_sharing, comment_text, enrichment_status,
                    enrichment_result
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    created_at,
                    data.customer_name,
                    data.email,
                    data.phone,
                    data.core_request,
                    data.sentiment,
                    initial_progress,
                    data.issue_category,
                    data.detailed_description,
                    data.praise_text,
                    1 if data.social_sharing else 0,
                    data.comment_text,
                    "pending",
                    None,
                ),
            )

            # Record the initial state transition (0 → initial_progress)
            transition_timestamp = created_at
            conn.execute(
                """
                INSERT INTO state_transitions (submission_id, previous_state, new_state, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (submission_id, 0, initial_progress, transition_timestamp),
            )

            conn.commit()

        # Build and return the Submission model
        return Submission(
            id=uuid.UUID(submission_id),
            created_at=datetime.fromisoformat(created_at),
            customer_name=data.customer_name,
            email=data.email,
            phone=data.phone,
            core_request=data.core_request,
            sentiment=data.sentiment,
            progress_state=initial_progress,
            issue_category=data.issue_category,
            detailed_description=data.detailed_description,
            praise_text=data.praise_text,
            social_sharing=data.social_sharing,
            comment_text=data.comment_text,
            enrichment_status="pending",
            enrichment_result=None,
            state_transitions=[
                StateTransition(
                    previous_state=0,
                    new_state=initial_progress,
                    timestamp=datetime.fromisoformat(transition_timestamp),
                )
            ],
        )

    def get(self, submission_id: uuid.UUID) -> Submission | None:
        """Retrieve a full submission record with state transitions.

        Returns None if the submission does not exist.
        """
        sid = str(submission_id)

        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM submissions WHERE id = ?", (sid,)
            ).fetchone()

            if row is None:
                return None

            # Fetch state transitions ordered chronologically
            transitions_rows = conn.execute(
                """
                SELECT previous_state, new_state, timestamp
                FROM state_transitions
                WHERE submission_id = ?
                ORDER BY id ASC
                """,
                (sid,),
            ).fetchall()

        # Parse enrichment result if present
        enrichment_result = None
        if row["enrichment_result"]:
            enrichment_result = EnrichmentResult(**json.loads(row["enrichment_result"]))

        # Build state transitions list
        state_transitions = [
            StateTransition(
                previous_state=t["previous_state"],
                new_state=t["new_state"],
                timestamp=datetime.fromisoformat(t["timestamp"]),
            )
            for t in transitions_rows
        ]

        return Submission(
            id=uuid.UUID(row["id"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            customer_name=row["customer_name"],
            email=row["email"],
            phone=row["phone"],
            core_request=row["core_request"],
            sentiment=row["sentiment"],
            progress_state=row["progress_state"],
            issue_category=row["issue_category"],
            detailed_description=row["detailed_description"],
            praise_text=row["praise_text"],
            social_sharing=bool(row["social_sharing"]),
            comment_text=row["comment_text"],
            enrichment_status=row["enrichment_status"],
            enrichment_result=enrichment_result,
            state_transitions=state_transitions,
        )

    def get_status(self, submission_id: uuid.UUID) -> StatusResponse | None:
        """Return the public-facing status for a submission.

        Returns None if the submission does not exist.
        """
        sid = str(submission_id)

        with get_connection() as conn:
            row = conn.execute(
                "SELECT id, progress_state, sentiment, enrichment_status FROM submissions WHERE id = ?",
                (sid,),
            ).fetchone()

        if row is None:
            return None

        progress_state = row["progress_state"]
        sentiment = row["sentiment"]
        message = _get_message(progress_state, sentiment)

        return StatusResponse(
            submission_id=uuid.UUID(row["id"]),
            progress_state=progress_state,
            sentiment=sentiment,
            message=message,
            enrichment_status=row["enrichment_status"],
        )

    def update_progress(self, submission_id: uuid.UUID, new_state: int) -> None:
        """Update the progress state of a submission and record the state transition.

        Reads the current progress_state, updates it, and inserts a state_transitions row
        with the previous state, new state, and current UTC timestamp.
        """
        sid = str(submission_id)

        with get_connection() as conn:
            # Read the current progress state
            row = conn.execute(
                "SELECT progress_state FROM submissions WHERE id = ?", (sid,)
            ).fetchone()

            if row is None:
                return

            previous_state = row["progress_state"]
            timestamp = _utcnow_iso()

            # Update the progress state
            conn.execute(
                "UPDATE submissions SET progress_state = ? WHERE id = ?",
                (new_state, sid),
            )

            # Record the state transition
            conn.execute(
                """
                INSERT INTO state_transitions (submission_id, previous_state, new_state, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (sid, previous_state, new_state, timestamp),
            )

            conn.commit()

    def update_enrichment(self, submission_id: uuid.UUID, result: EnrichmentResult) -> None:
        """Store the enrichment result and mark enrichment as completed.

        Serializes the EnrichmentResult to JSON and updates the submission record.
        """
        sid = str(submission_id)
        result_json = result.model_dump_json()

        with get_connection() as conn:
            conn.execute(
                """
                UPDATE submissions
                SET enrichment_result = ?, enrichment_status = 'completed'
                WHERE id = ?
                """,
                (result_json, sid),
            )
            conn.commit()

    def mark_enrichment_failed(
        self, submission_id: uuid.UUID, reason: str, status: str = "failed"
    ) -> None:
        """Mark enrichment as failed or timed out.

        Args:
            submission_id: The submission to update.
            reason: Description of why enrichment failed.
            status: Either "failed" or "timeout".
        """
        sid = str(submission_id)
        # Ensure status is one of the valid failure statuses
        if status not in ("failed", "timeout"):
            status = "failed"

        with get_connection() as conn:
            conn.execute(
                "UPDATE submissions SET enrichment_status = ? WHERE id = ?",
                (status, sid),
            )
            conn.commit()

    def list_by_sentiment(
        self, sentiment: str, limit: int = 20, offset: int = 0
    ) -> list[Submission]:
        """Return a paginated list of submissions filtered by sentiment.

        Results are ordered by created_at descending (newest first).
        """
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM submissions
                WHERE sentiment = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (sentiment, limit, offset),
            ).fetchall()

            submissions: list[Submission] = []
            for row in rows:
                # Fetch state transitions for each submission
                transitions_rows = conn.execute(
                    """
                    SELECT previous_state, new_state, timestamp
                    FROM state_transitions
                    WHERE submission_id = ?
                    ORDER BY id ASC
                    """,
                    (row["id"],),
                ).fetchall()

                enrichment_result = None
                if row["enrichment_result"]:
                    enrichment_result = EnrichmentResult(
                        **json.loads(row["enrichment_result"])
                    )

                state_transitions = [
                    StateTransition(
                        previous_state=t["previous_state"],
                        new_state=t["new_state"],
                        timestamp=datetime.fromisoformat(t["timestamp"]),
                    )
                    for t in transitions_rows
                ]

                submissions.append(
                    Submission(
                        id=uuid.UUID(row["id"]),
                        created_at=datetime.fromisoformat(row["created_at"]),
                        customer_name=row["customer_name"],
                        email=row["email"],
                        phone=row["phone"],
                        core_request=row["core_request"],
                        sentiment=row["sentiment"],
                        progress_state=row["progress_state"],
                        issue_category=row["issue_category"],
                        detailed_description=row["detailed_description"],
                        praise_text=row["praise_text"],
                        social_sharing=bool(row["social_sharing"]),
                        comment_text=row["comment_text"],
                        enrichment_status=row["enrichment_status"],
                        enrichment_result=enrichment_result,
                        state_transitions=state_transitions,
                    )
                )

        return submissions

    def count_by_sentiment(self) -> dict:
        """Return aggregate counts grouped by sentiment and progress_state.

        Returns a nested dict:
        {
            "negative": {"total": N, "by_progress": {50: n, 75: m, ...}},
            "positive": {"total": N, "by_progress": {100: n, ...}},
            "neutral": {"total": N, "by_progress": {25: n, ...}},
        }
        """
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT sentiment, progress_state, COUNT(*) as cnt
                FROM submissions
                GROUP BY sentiment, progress_state
                """
            ).fetchall()

        result: dict = {}
        for row in rows:
            sentiment = row["sentiment"]
            progress = row["progress_state"]
            count = row["cnt"]

            if sentiment not in result:
                result[sentiment] = {"total": 0, "by_progress": {}}

            result[sentiment]["total"] += count
            result[sentiment]["by_progress"][progress] = count

        return result

    def enrichment_analytics(self) -> dict:
        """Aggregate NLP enrichment output across all submissions.

        Returns a dict with:
          - status_counts: {enrichment_status: count} across every submission
          - top_themes: [{theme, count}] top 10 detected themes by frequency
          - average_severity: mean severity_score over completed enrichments
            (None when there are none)
          - by_language: {language_code: count} over completed enrichments

        Only submissions whose enrichment completed contribute themes, severity,
        and language; status_counts covers every submission regardless of state.
        """
        status_counts: dict[str, int] = {}
        theme_counts: dict[str, int] = {}
        language_counts: dict[str, int] = {}
        severity_total = 0
        severity_n = 0

        with get_connection() as conn:
            status_rows = conn.execute(
                "SELECT enrichment_status, COUNT(*) AS cnt FROM submissions GROUP BY enrichment_status"
            ).fetchall()
            for row in status_rows:
                status_counts[row["enrichment_status"]] = row["cnt"]

            enriched_rows = conn.execute(
                "SELECT enrichment_result FROM submissions "
                "WHERE enrichment_status = 'completed' AND enrichment_result IS NOT NULL"
            ).fetchall()

        for row in enriched_rows:
            try:
                data = json.loads(row["enrichment_result"])
            except (ValueError, TypeError):
                continue

            for theme in data.get("themes", []):
                name = theme.get("theme") if isinstance(theme, dict) else None
                if name:
                    theme_counts[name] = theme_counts.get(name, 0) + 1

            score = data.get("severity_score")
            if isinstance(score, (int, float)):
                severity_total += score
                severity_n += 1

            lang = data.get("language_code")
            if lang:
                language_counts[lang] = language_counts.get(lang, 0) + 1

        top_themes = sorted(
            ({"theme": t, "count": c} for t, c in theme_counts.items()),
            key=lambda x: x["count"],
            reverse=True,
        )[:10]

        average_severity = (
            round(severity_total / severity_n, 2) if severity_n > 0 else None
        )

        return {
            "status_counts": status_counts,
            "top_themes": top_themes,
            "average_severity": average_severity,
            "by_language": language_counts,
        }
