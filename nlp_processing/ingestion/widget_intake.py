"""Widget Intake ingestion service (Requirements 2.1–2.7).

This module receives direct customer feedback submissions from app widgets,
website forms, and support intake forms. It validates required fields, enforces
constraints, and produces validated WidgetFeedback records.

Validation rules:
- Reject empty or whitespace-only message_text (Req 2.4)
- Reject message_text exceeding 10,000 characters (Req 2.5)
- Reject missing consent_to_contact field (Req 2.6)
- Reject invalid selected_category not in ThemeCategory set (Req 2.7)
- Store optional fields when provided (Req 2.2)
- Accept structured category selection + free-text simultaneously (Req 2.3)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import get_args

from nlp_processing.models.feedback_routing import ThemeCategory, WidgetFeedback

# Valid submission channels for widget feedback.
VALID_SUBMISSION_CHANNELS = {"app_widget", "website_form", "support_intake_form"}

# Maximum message text length (Req 2.5).
MAX_MESSAGE_LENGTH = 10_000

# Valid theme categories derived from the Literal type.
VALID_THEME_CATEGORIES: frozenset[str] = frozenset(get_args(ThemeCategory))


class ValidationError(Exception):
    """Raised when a widget submission fails validation.

    Attributes:
        field: The field that caused the validation failure.
        message: Human-readable description of the error.
    """

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class WidgetIntake:
    """Ingestion service for direct customer feedback submissions.

    Validates incoming widget/form submissions and produces WidgetFeedback
    records for downstream processing.
    """

    def ingest_widget(self, submission: dict) -> WidgetFeedback | ValidationError:
        """Validate and ingest a widget feedback submission.

        Args:
            submission: Dictionary containing the raw submission data. Expected
                keys include message_text, consent_to_contact, and optionally
                submission_channel, customer_id, account_type, selected_category,
                location, etc.

        Returns:
            A validated WidgetFeedback instance on success, or a ValidationError
            instance describing why the submission was rejected.
        """
        # Req 2.6: consent_to_contact must be explicitly provided as bool.
        error = self._validate_consent(submission)
        if error is not None:
            return error

        # Req 2.4: message_text must not be empty or whitespace-only.
        error = self._validate_message_text(submission)
        if error is not None:
            return error

        # Req 2.5: message_text must not exceed 10,000 characters.
        error = self._validate_message_length(submission)
        if error is not None:
            return error

        # Req 2.7: selected_category must be valid if provided.
        error = self._validate_selected_category(submission)
        if error is not None:
            return error

        # Req 2.1: Build the WidgetFeedback record with required fields.
        feedback_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Determine submission channel (default to "website_form" if not provided
        # or invalid).
        submission_channel = submission.get("submission_channel", "website_form")
        if submission_channel not in VALID_SUBMISSION_CHANNELS:
            submission_channel = "website_form"

        # Req 2.2: Store optional fields when provided.
        widget_feedback = WidgetFeedback(
            feedback_id=feedback_id,
            source_type="widget",
            submission_channel=submission_channel,
            message_text=submission["message_text"],
            created_at=created_at,
            consent_to_contact=submission["consent_to_contact"],
            customer_id=submission.get("customer_id"),
            account_type=submission.get("account_type"),
            selected_category=submission.get("selected_category"),
            location=submission.get("location"),
        )

        return widget_feedback

    @staticmethod
    def _validate_consent(submission: dict) -> ValidationError | None:
        """Validate that consent_to_contact is explicitly provided as a boolean.

        Req 2.6: Reject if not explicitly provided as true or false.
        """
        if "consent_to_contact" not in submission:
            return ValidationError(
                field="consent_to_contact",
                message="consent_to_contact field is required",
            )

        value = submission["consent_to_contact"]
        if not isinstance(value, bool):
            return ValidationError(
                field="consent_to_contact",
                message="consent_to_contact must be a boolean (true or false)",
            )

        return None

    @staticmethod
    def _validate_message_text(submission: dict) -> ValidationError | None:
        """Validate that message_text is present and not empty/whitespace.

        Req 2.4: Reject empty or whitespace-only message_text.
        """
        message_text = submission.get("message_text")

        if message_text is None:
            return ValidationError(
                field="message_text",
                message="message text is required",
            )

        if not isinstance(message_text, str):
            return ValidationError(
                field="message_text",
                message="message text is required",
            )

        if not message_text.strip():
            return ValidationError(
                field="message_text",
                message="message text is required",
            )

        return None

    @staticmethod
    def _validate_message_length(submission: dict) -> ValidationError | None:
        """Validate that message_text does not exceed maximum length.

        Req 2.5: Reject message_text exceeding 10,000 characters.
        """
        message_text = submission.get("message_text", "")

        if len(message_text) > MAX_MESSAGE_LENGTH:
            return ValidationError(
                field="message_text",
                message=(
                    f"message text exceeds the maximum limit of "
                    f"{MAX_MESSAGE_LENGTH} characters"
                ),
            )

        return None

    @staticmethod
    def _validate_selected_category(submission: dict) -> ValidationError | None:
        """Validate that selected_category is in the ThemeCategory set if provided.

        Req 2.7: Reject invalid selected_category values.
        """
        selected_category = submission.get("selected_category")

        if selected_category is None:
            return None

        if selected_category not in VALID_THEME_CATEGORIES:
            return ValidationError(
                field="selected_category",
                message=(
                    f"'{selected_category}' is not a valid category; "
                    f"valid options are: {sorted(VALID_THEME_CATEGORIES)}"
                ),
            )

        return None


__all__ = [
    "WidgetIntake",
    "ValidationError",
    "VALID_SUBMISSION_CHANNELS",
    "MAX_MESSAGE_LENGTH",
    "VALID_THEME_CATEGORIES",
]
