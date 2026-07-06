"""Unit tests for MarketingEngine service."""

import os
import tempfile
import uuid
from datetime import datetime, timezone

import pytest

# Set the DB path before importing app modules
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["SUBMISSIONS_DB_PATH"] = _tmp_db.name
_tmp_db.close()

from app.database import get_connection, init_db
from app.services.marketing_engine import MarketingEngine


@pytest.fixture(autouse=True)
def setup_db():
    """Initialize a fresh database for each test."""
    init_db()
    with get_connection() as conn:
        conn.execute("DELETE FROM marketing_log")
        conn.execute("DELETE FROM submissions")
        conn.commit()
    yield


def _create_submission(
    submission_id: str,
    customer_name: str = "Jane Doe",
    praise_text: str = "Great service!",
) -> str:
    """Helper to insert a submission record for FK constraints."""
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO submissions
            (id, created_at, customer_name, core_request, sentiment, progress_state, praise_text, social_sharing)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (submission_id, now, customer_name, "test request", "positive", 100, praise_text, 1),
        )
        conn.commit()
    return submission_id


class TestLogPraise:
    def test_log_praise_without_social_sharing(self):
        engine = MarketingEngine()
        sub_id = _create_submission(str(uuid.uuid4()))

        engine.log_praise(sub_id, "Jane Doe", "Great service!", social_sharing=False)

        entries = engine.list_entries()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.submission_id == uuid.UUID(sub_id)
        assert entry.customer_name == "Jane Doe"
        assert entry.praise_text == "Great service!"
        assert entry.social_sharing is False
        assert entry.social_status == "internal_only"
        assert entry.shareable_url is None

    def test_log_praise_with_social_sharing(self):
        engine = MarketingEngine()
        sub_id = _create_submission(str(uuid.uuid4()))

        engine.log_praise(sub_id, "Jane Doe", "Great service!", social_sharing=True)

        entries = engine.list_entries()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.social_sharing is True
        assert entry.social_status == "shared"
        assert entry.shareable_url == f"https://spectrum.net/praise/{sub_id}"

    def test_log_praise_stores_logged_at_timestamp(self):
        engine = MarketingEngine()
        sub_id = _create_submission(str(uuid.uuid4()))

        before = datetime.now(timezone.utc)
        engine.log_praise(sub_id, "Jane Doe", "Great service!", social_sharing=False)
        after = datetime.now(timezone.utc)

        entries = engine.list_entries()
        assert len(entries) == 1
        logged_at = entries[0].logged_at
        if logged_at.tzinfo is None:
            logged_at = logged_at.replace(tzinfo=timezone.utc)
        assert before <= logged_at <= after


class TestGenerateShare:
    def test_generate_share_returns_url_and_template(self):
        engine = MarketingEngine()
        sub_id = _create_submission(str(uuid.uuid4()))
        engine.log_praise(sub_id, "Jane Doe", "Great service!", social_sharing=False)

        result = engine.generate_share(sub_id)

        assert result.shareable_url == f"https://spectrum.net/praise/{sub_id}"
        assert isinstance(result.email_template, str)
        assert len(result.email_template) > 0

    def test_generate_share_strips_customer_name(self):
        engine = MarketingEngine()
        sub_id = _create_submission(str(uuid.uuid4()), customer_name="John Smith")
        engine.log_praise(
            sub_id, "John Smith", "I, John Smith, love this service!", social_sharing=False
        )

        result = engine.generate_share(sub_id)

        assert "John Smith" not in result.email_template
        assert "[CUSTOMER]" in result.email_template

    def test_generate_share_strips_email_addresses(self):
        engine = MarketingEngine()
        sub_id = _create_submission(str(uuid.uuid4()))
        engine.log_praise(
            sub_id,
            "Jane Doe",
            "Contact me at jane.doe@example.com for more praise!",
            social_sharing=False,
        )

        result = engine.generate_share(sub_id)

        assert "jane.doe@example.com" not in result.email_template
        assert "[EMAIL REMOVED]" in result.email_template

    def test_generate_share_strips_phone_numbers(self):
        engine = MarketingEngine()
        sub_id = _create_submission(str(uuid.uuid4()))
        engine.log_praise(
            sub_id,
            "Jane Doe",
            "Call me at +1-555-123-4567 to hear more!",
            social_sharing=False,
        )

        result = engine.generate_share(sub_id)

        assert "+1-555-123-4567" not in result.email_template
        assert "[PHONE REMOVED]" in result.email_template

    def test_generate_share_strips_all_pii_types(self):
        engine = MarketingEngine()
        sub_id = _create_submission(str(uuid.uuid4()), customer_name="Alice Johnson")
        praise = "I'm Alice Johnson, email alice@test.org, phone 555-987-6543. Love it!"
        engine.log_praise(sub_id, "Alice Johnson", praise, social_sharing=False)

        result = engine.generate_share(sub_id)

        assert "Alice Johnson" not in result.email_template
        assert "alice@test.org" not in result.email_template
        assert "555-987-6543" not in result.email_template

    def test_generate_share_raises_for_unknown_submission(self):
        engine = MarketingEngine()
        with pytest.raises(ValueError, match="No marketing log entry found"):
            engine.generate_share(str(uuid.uuid4()))

    def test_generate_share_updates_social_status_to_shared(self):
        engine = MarketingEngine()
        sub_id = _create_submission(str(uuid.uuid4()))
        engine.log_praise(sub_id, "Jane Doe", "Great!", social_sharing=False)

        engine.generate_share(sub_id)

        entries = engine.list_entries()
        assert entries[0].social_status == "shared"


class TestListEntries:
    def test_list_entries_empty(self):
        engine = MarketingEngine()
        result = engine.list_entries()
        assert result == []

    def test_list_entries_returns_entries_ordered_by_logged_at_desc(self):
        engine = MarketingEngine()
        ids = []
        for i in range(3):
            sub_id = _create_submission(str(uuid.uuid4()), f"User {i}")
            engine.log_praise(sub_id, f"User {i}", f"Praise {i}", social_sharing=False)
            ids.append(sub_id)

        result = engine.list_entries()
        assert len(result) == 3
        # Most recent first
        assert str(result[0].submission_id) == ids[2]
        assert str(result[1].submission_id) == ids[1]
        assert str(result[2].submission_id) == ids[0]

    def test_list_entries_pagination_limit(self):
        engine = MarketingEngine()
        for i in range(5):
            sub_id = _create_submission(str(uuid.uuid4()), f"User {i}")
            engine.log_praise(sub_id, f"User {i}", f"Praise {i}", social_sharing=False)

        result = engine.list_entries(limit=2)
        assert len(result) == 2

    def test_list_entries_pagination_offset(self):
        engine = MarketingEngine()
        ids = []
        for i in range(5):
            sub_id = _create_submission(str(uuid.uuid4()), f"User {i}")
            engine.log_praise(sub_id, f"User {i}", f"Praise {i}", social_sharing=False)
            ids.append(sub_id)

        result = engine.list_entries(limit=2, offset=2)
        assert len(result) == 2
        # Descending order: ids[4], ids[3], ids[2], ids[1], ids[0]
        # offset=2 → ids[2], ids[1]
        assert str(result[0].submission_id) == ids[2]
        assert str(result[1].submission_id) == ids[1]

    def test_list_entries_returns_marketing_entry_models(self):
        engine = MarketingEngine()
        sub_id = _create_submission(str(uuid.uuid4()))
        engine.log_praise(sub_id, "Jane Doe", "Great!", social_sharing=True)

        from app.models.marketing import MarketingEntry

        result = engine.list_entries()
        assert len(result) == 1
        assert isinstance(result[0], MarketingEntry)
