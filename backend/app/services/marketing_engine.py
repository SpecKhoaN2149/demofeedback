"""MarketingEngine service for managing positive submission marketing logs."""

import re
from datetime import datetime, timezone

from app.database import get_connection
from app.models.marketing import MarketingEntry, ShareResult


class MarketingEngine:
    """Manages marketing log entries for positive submissions.

    Logs praise text, handles social sharing generation (shareable URL + email
    template with PII removed), and provides paginated listing.
    """

    # Patterns to detect PII in text
    _EMAIL_PATTERN = re.compile(
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
    )
    _PHONE_PATTERN = re.compile(r"\+?\d[\d\s\-().]{5,14}\d")

    def log_praise(
        self,
        submission_id: str,
        customer_name: str,
        praise_text: str,
        social_sharing: bool,
    ) -> None:
        """Store a marketing log entry for a positive submission.

        Args:
            submission_id: The UUID string of the submission.
            customer_name: The customer's name.
            praise_text: The praise text from the submission.
            social_sharing: Whether the customer opted in to social sharing.
        """
        social_status = "shared" if social_sharing else "internal_only"
        logged_at = datetime.now(timezone.utc).isoformat()

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO marketing_log
                    (submission_id, customer_name, praise_text, social_sharing, social_status, logged_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    customer_name,
                    praise_text,
                    1 if social_sharing else 0,
                    social_status,
                    logged_at,
                ),
            )
            conn.commit()

        # If social sharing is enabled, generate shareable content and update the entry
        if social_sharing:
            try:
                share_result = self.generate_share(submission_id)
                with get_connection() as conn:
                    conn.execute(
                        """
                        UPDATE marketing_log
                        SET shareable_url = ?
                        WHERE submission_id = ?
                        """,
                        (share_result.shareable_url, submission_id),
                    )
                    conn.commit()
            except Exception:
                # If generation fails, mark as generation_failed per requirement 17.5
                with get_connection() as conn:
                    conn.execute(
                        """
                        UPDATE marketing_log
                        SET social_status = 'generation_failed'
                        WHERE submission_id = ?
                        """,
                        (submission_id,),
                    )
                    conn.commit()

    def generate_share(self, submission_id: str) -> ShareResult:
        """Generate a shareable URL and PII-stripped email template.

        Retrieves the marketing log entry for the submission, creates a
        shareable URL, and generates an email template with all PII
        (customer name, email, phone) removed from the text.

        Args:
            submission_id: The UUID string of the submission.

        Returns:
            ShareResult with shareable_url and email_template.

        Raises:
            ValueError: If no marketing log entry exists for the submission.
        """
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT customer_name, praise_text
                FROM marketing_log
                WHERE submission_id = ?
                """,
                (submission_id,),
            ).fetchone()

        if row is None:
            raise ValueError(
                f"No marketing log entry found for submission {submission_id}"
            )

        customer_name = row["customer_name"]
        praise_text = row["praise_text"]

        # Generate shareable URL
        shareable_url = f"https://spectrum.net/praise/{submission_id}"

        # Generate email template with PII stripped
        email_template = self._strip_pii(praise_text, customer_name)

        # Update the marketing log entry
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE marketing_log
                SET shareable_url = ?, social_status = 'shared'
                WHERE submission_id = ?
                """,
                (shareable_url, submission_id),
            )
            conn.commit()

        return ShareResult(shareable_url=shareable_url, email_template=email_template)

    def list_entries(self, limit: int = 20, offset: int = 0) -> list[MarketingEntry]:
        """Return paginated marketing log entries ordered by logged_at descending.

        Args:
            limit: Maximum number of entries to return (default 20).
            offset: Number of entries to skip (default 0).

        Returns:
            List of MarketingEntry models.
        """
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT submission_id, customer_name, praise_text,
                       social_sharing, social_status, shareable_url, logged_at
                FROM marketing_log
                ORDER BY logged_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

        return [
            MarketingEntry(
                submission_id=row["submission_id"],
                customer_name=row["customer_name"],
                praise_text=row["praise_text"],
                social_sharing=bool(row["social_sharing"]),
                social_status=row["social_status"],
                shareable_url=row["shareable_url"],
                logged_at=row["logged_at"],
            )
            for row in rows
        ]

    def _strip_pii(self, text: str, customer_name: str) -> str:
        """Remove PII (name, email, phone) from text.

        Args:
            text: The original text to sanitize.
            customer_name: The customer name to remove.

        Returns:
            Text with PII replaced by placeholders.
        """
        result = text

        # Remove customer name (case-insensitive)
        if customer_name:
            # Escape special regex chars in the name and match case-insensitively
            escaped_name = re.escape(customer_name)
            result = re.sub(escaped_name, "[CUSTOMER]", result, flags=re.IGNORECASE)

        # Remove email addresses
        result = self._EMAIL_PATTERN.sub("[EMAIL REMOVED]", result)

        # Remove phone numbers
        result = self._PHONE_PATTERN.sub("[PHONE REMOVED]", result)

        return result
