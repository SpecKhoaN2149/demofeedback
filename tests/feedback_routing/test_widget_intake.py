"""Unit tests for the Widget Intake ingestion service (task 2.2).

These cover the validation and ingestion rules from Requirement 2:
- Reject empty/whitespace message_text (Req 2.4)
- Reject message_text > 10,000 characters (Req 2.5)
- Reject missing consent_to_contact (Req 2.6)
- Reject invalid selected_category (Req 2.7)
- Store optional fields (Req 2.2)
- Accept structured category + free-text simultaneously (Req 2.3)
- Produce valid WidgetFeedback records (Req 2.1)
"""

from nlp_processing.ingestion.widget_intake import (
    MAX_MESSAGE_LENGTH,
    VALID_THEME_CATEGORIES,
    ValidationError,
    WidgetIntake,
)
from nlp_processing.models.feedback_routing import WidgetFeedback


def _submission(
    message_text="I have a billing issue",
    consent_to_contact=True,
    **kwargs,
):
    """Helper to build a minimal valid submission dict."""
    data = {
        "message_text": message_text,
        "consent_to_contact": consent_to_contact,
    }
    data.update(kwargs)
    return data


class TestSuccessfulIngestion:
    """Tests that valid submissions produce WidgetFeedback records."""

    def test_minimal_valid_submission_produces_widget_feedback(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(_submission())

        assert isinstance(result, WidgetFeedback)
        assert result.source_type == "widget"
        assert result.message_text == "I have a billing issue"
        assert result.consent_to_contact is True
        assert result.feedback_id  # Non-empty UUID

    def test_generated_fields_are_populated(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(_submission())

        assert isinstance(result, WidgetFeedback)
        assert result.feedback_id  # UUID assigned
        assert result.created_at  # Timestamp assigned
        assert "T" in result.created_at  # ISO format
        assert result.created_at.endswith("Z")

    def test_submission_channel_defaults_to_website_form(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(_submission())

        assert isinstance(result, WidgetFeedback)
        assert result.submission_channel == "website_form"

    def test_valid_submission_channel_is_preserved(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(
            _submission(submission_channel="app_widget")
        )

        assert isinstance(result, WidgetFeedback)
        assert result.submission_channel == "app_widget"

    def test_consent_false_is_accepted(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(_submission(consent_to_contact=False))

        assert isinstance(result, WidgetFeedback)
        assert result.consent_to_contact is False


class TestOptionalFields:
    """Tests that optional fields are stored when provided (Req 2.2)."""

    def test_customer_id_stored(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(_submission(customer_id="CUST-12345"))

        assert isinstance(result, WidgetFeedback)
        assert result.customer_id == "CUST-12345"

    def test_account_type_stored(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(_submission(account_type="premium"))

        assert isinstance(result, WidgetFeedback)
        assert result.account_type == "premium"

    def test_location_stored(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(
            _submission(location="Seattle, US")
        )

        assert isinstance(result, WidgetFeedback)
        assert result.location == "Seattle, US"

    def test_selected_category_stored(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(
            _submission(selected_category="billing")
        )

        assert isinstance(result, WidgetFeedback)
        assert result.selected_category == "billing"

    def test_optional_fields_default_to_none(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(_submission())

        assert isinstance(result, WidgetFeedback)
        assert result.customer_id is None
        assert result.account_type is None
        assert result.location is None
        assert result.selected_category is None


class TestStructuredAndFreeText:
    """Tests that category selection and free-text coexist (Req 2.3)."""

    def test_accepts_category_and_message_simultaneously(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(
            _submission(
                message_text="My bill is wrong this month",
                selected_category="billing",
            )
        )

        assert isinstance(result, WidgetFeedback)
        assert result.message_text == "My bill is wrong this month"
        assert result.selected_category == "billing"


class TestMessageTextValidation:
    """Tests for message_text validation (Req 2.4, 2.5)."""

    def test_rejects_empty_message_text(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(_submission(message_text=""))

        assert isinstance(result, ValidationError)
        assert result.field == "message_text"

    def test_rejects_whitespace_only_message_text(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(_submission(message_text="   \t\n  "))

        assert isinstance(result, ValidationError)
        assert result.field == "message_text"

    def test_rejects_missing_message_text(self):
        intake = WidgetIntake()
        submission = {"consent_to_contact": True}
        result = intake.ingest_widget(submission)

        assert isinstance(result, ValidationError)
        assert result.field == "message_text"

    def test_rejects_message_text_over_limit(self):
        intake = WidgetIntake()
        long_text = "a" * (MAX_MESSAGE_LENGTH + 1)
        result = intake.ingest_widget(_submission(message_text=long_text))

        assert isinstance(result, ValidationError)
        assert result.field == "message_text"
        assert "maximum" in result.message.lower() or "limit" in result.message.lower()

    def test_accepts_message_text_at_limit(self):
        intake = WidgetIntake()
        text = "a" * MAX_MESSAGE_LENGTH
        result = intake.ingest_widget(_submission(message_text=text))

        assert isinstance(result, WidgetFeedback)
        assert len(result.message_text) == MAX_MESSAGE_LENGTH


class TestConsentValidation:
    """Tests for consent_to_contact validation (Req 2.6)."""

    def test_rejects_missing_consent(self):
        intake = WidgetIntake()
        submission = {"message_text": "Hello"}
        result = intake.ingest_widget(submission)

        assert isinstance(result, ValidationError)
        assert result.field == "consent_to_contact"

    def test_rejects_non_boolean_consent_string(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(
            _submission(consent_to_contact="yes")
        )

        assert isinstance(result, ValidationError)
        assert result.field == "consent_to_contact"

    def test_rejects_non_boolean_consent_none(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(
            _submission(consent_to_contact=None)
        )

        assert isinstance(result, ValidationError)
        assert result.field == "consent_to_contact"

    def test_rejects_non_boolean_consent_integer(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(
            _submission(consent_to_contact=1)
        )

        assert isinstance(result, ValidationError)
        assert result.field == "consent_to_contact"


class TestSelectedCategoryValidation:
    """Tests for selected_category validation (Req 2.7)."""

    def test_rejects_invalid_category(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(
            _submission(selected_category="invalid_category")
        )

        assert isinstance(result, ValidationError)
        assert result.field == "selected_category"
        assert "invalid" in result.message.lower() or "not a valid" in result.message.lower()

    def test_accepts_none_category(self):
        intake = WidgetIntake()
        result = intake.ingest_widget(_submission(selected_category=None))

        assert isinstance(result, WidgetFeedback)
        assert result.selected_category is None

    def test_accepts_all_valid_categories(self):
        intake = WidgetIntake()
        for category in VALID_THEME_CATEGORIES:
            result = intake.ingest_widget(
                _submission(selected_category=category)
            )
            assert isinstance(result, WidgetFeedback), (
                f"Expected WidgetFeedback for category '{category}', "
                f"got {type(result).__name__}: {result}"
            )
            assert result.selected_category == category
