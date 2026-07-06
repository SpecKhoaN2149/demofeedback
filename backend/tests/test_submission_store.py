"""Unit tests for SubmissionStore core CRUD operations."""

import os
import tempfile
import uuid

import pytest

# Point to a temporary database for tests
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

from app.database import init_db
from app.models.submission import SubmissionCreate
from app.services.submission_store import SubmissionStore


@pytest.fixture(autouse=True)
def setup_db():
    """Initialize a fresh database before each test."""
    # Re-initialize to ensure clean state
    init_db()
    yield
    # Clean up tables after each test
    from app.database import get_connection

    with get_connection() as conn:
        conn.execute("DELETE FROM state_transitions")
        conn.execute("DELETE FROM submissions")
        conn.commit()


@pytest.fixture
def store() -> SubmissionStore:
    return SubmissionStore()


class TestCreate:
    """Tests for SubmissionStore.create()."""

    def test_negative_submission_gets_progress_50(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Alice",
            email="alice@example.com",
            core_request="My internet is down",
            sentiment="negative",
            issue_category="outage",
            detailed_description="It has been down since yesterday morning.",
        )
        result = store.create(data)

        assert result.progress_state == 50
        assert result.sentiment == "negative"
        assert result.customer_name == "Alice"
        assert result.email == "alice@example.com"
        assert result.issue_category == "outage"

    def test_positive_submission_gets_progress_100(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Bob",
            phone="1234567890",
            core_request="Great service!",
            sentiment="positive",
            praise_text="The technician was amazing.",
            social_sharing=True,
        )
        result = store.create(data)

        assert result.progress_state == 100
        assert result.sentiment == "positive"
        assert result.social_sharing is True

    def test_neutral_submission_gets_progress_25(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Charlie",
            email="charlie@test.com",
            core_request="Just a thought",
            sentiment="neutral",
            comment_text="I think you could improve the app.",
        )
        result = store.create(data)

        assert result.progress_state == 25
        assert result.sentiment == "neutral"
        assert result.comment_text == "I think you could improve the app."

    def test_create_generates_uuid(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Test",
            email="test@test.com",
            core_request="Test request",
            sentiment="neutral",
            comment_text="A comment.",
        )
        result = store.create(data)

        assert isinstance(result.id, uuid.UUID)

    def test_create_records_initial_state_transition(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Test",
            email="test@test.com",
            core_request="Test request",
            sentiment="negative",
            issue_category="billing",
            detailed_description="I was overcharged on my last bill.",
        )
        result = store.create(data)

        assert len(result.state_transitions) == 1
        transition = result.state_transitions[0]
        assert transition.previous_state == 0
        assert transition.new_state == 50

    def test_create_sets_enrichment_status_pending(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Test",
            email="test@test.com",
            core_request="Test",
            sentiment="positive",
            praise_text="Great work!",
        )
        result = store.create(data)

        assert result.enrichment_status == "pending"
        assert result.enrichment_result is None


class TestGet:
    """Tests for SubmissionStore.get()."""

    def test_get_existing_submission(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Alice",
            email="alice@example.com",
            core_request="My internet is down",
            sentiment="negative",
            issue_category="outage",
            detailed_description="It has been down since yesterday morning.",
        )
        created = store.create(data)
        retrieved = store.get(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.customer_name == "Alice"
        assert retrieved.email == "alice@example.com"
        assert retrieved.core_request == "My internet is down"
        assert retrieved.sentiment == "negative"
        assert retrieved.progress_state == 50
        assert retrieved.issue_category == "outage"
        assert retrieved.detailed_description == "It has been down since yesterday morning."

    def test_get_includes_state_transitions(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Test",
            email="test@test.com",
            core_request="Request",
            sentiment="neutral",
            comment_text="A comment.",
        )
        created = store.create(data)
        retrieved = store.get(created.id)

        assert retrieved is not None
        assert len(retrieved.state_transitions) == 1
        assert retrieved.state_transitions[0].previous_state == 0
        assert retrieved.state_transitions[0].new_state == 25

    def test_get_nonexistent_returns_none(self, store: SubmissionStore):
        fake_id = uuid.uuid4()
        result = store.get(fake_id)

        assert result is None

    def test_get_preserves_social_sharing_flag(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Bob",
            phone="5551234567",
            core_request="Love it!",
            sentiment="positive",
            praise_text="Excellent support.",
            social_sharing=True,
        )
        created = store.create(data)
        retrieved = store.get(created.id)

        assert retrieved is not None
        assert retrieved.social_sharing is True


class TestGetStatus:
    """Tests for SubmissionStore.get_status()."""

    def test_negative_at_50_returns_working_message(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Test",
            email="test@test.com",
            core_request="Issue",
            sentiment="negative",
            issue_category="billing",
            detailed_description="Overcharged on bill again.",
        )
        created = store.create(data)
        status = store.get_status(created.id)

        assert status is not None
        assert status.progress_state == 50
        assert status.message == "Spectrum is working on this."
        assert status.sentiment == "negative"
        assert status.enrichment_status == "pending"

    def test_positive_at_100_returns_praise_message(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Test",
            phone="5551234567",
            core_request="Praise",
            sentiment="positive",
            praise_text="Great work!",
        )
        created = store.create(data)
        status = store.get_status(created.id)

        assert status is not None
        assert status.progress_state == 100
        assert status.message == "Praise received & noted!"

    def test_neutral_at_25_returns_awaiting_message(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Test",
            email="test@test.com",
            core_request="Comment",
            sentiment="neutral",
            comment_text="General feedback.",
        )
        created = store.create(data)
        status = store.get_status(created.id)

        assert status is not None
        assert status.progress_state == 25
        assert status.message == "Awaiting Review"

    def test_get_status_nonexistent_returns_none(self, store: SubmissionStore):
        fake_id = uuid.uuid4()
        result = store.get_status(fake_id)

        assert result is None

    def test_get_status_returns_submission_id(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Test",
            email="test@test.com",
            core_request="Request",
            sentiment="neutral",
            comment_text="Something.",
        )
        created = store.create(data)
        status = store.get_status(created.id)

        assert status is not None
        assert status.submission_id == created.id


from app.models.submission import EnrichmentResult


class TestUpdateProgress:
    """Tests for SubmissionStore.update_progress()."""

    def test_updates_progress_state(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Alice",
            email="alice@example.com",
            core_request="Issue here",
            sentiment="negative",
            issue_category="billing",
            detailed_description="Overcharged on my bill.",
        )
        created = store.create(data)
        assert created.progress_state == 50

        store.update_progress(created.id, 75)

        retrieved = store.get(created.id)
        assert retrieved is not None
        assert retrieved.progress_state == 75

    def test_records_state_transition(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Bob",
            email="bob@example.com",
            core_request="My issue",
            sentiment="negative",
            issue_category="outage",
            detailed_description="Network is completely down.",
        )
        created = store.create(data)

        store.update_progress(created.id, 75)

        retrieved = store.get(created.id)
        assert retrieved is not None
        # Initial transition (0→50) + update (50→75) = 2 transitions
        assert len(retrieved.state_transitions) == 2
        second_transition = retrieved.state_transitions[1]
        assert second_transition.previous_state == 50
        assert second_transition.new_state == 75

    def test_multiple_progress_updates(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Charlie",
            email="charlie@example.com",
            core_request="Problem",
            sentiment="negative",
            issue_category="network_speed",
            detailed_description="Very slow internet speeds.",
        )
        created = store.create(data)

        store.update_progress(created.id, 75)
        store.update_progress(created.id, 100)

        retrieved = store.get(created.id)
        assert retrieved is not None
        assert retrieved.progress_state == 100
        # 3 transitions: 0→50, 50→75, 75→100
        assert len(retrieved.state_transitions) == 3
        assert retrieved.state_transitions[2].previous_state == 75
        assert retrieved.state_transitions[2].new_state == 100

    def test_update_progress_nonexistent_does_nothing(self, store: SubmissionStore):
        fake_id = uuid.uuid4()
        # Should not raise
        store.update_progress(fake_id, 75)


class TestUpdateEnrichment:
    """Tests for SubmissionStore.update_enrichment()."""

    def test_stores_enrichment_result(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Alice",
            email="alice@example.com",
            core_request="Issue",
            sentiment="negative",
            issue_category="billing",
            detailed_description="I was overcharged.",
        )
        created = store.create(data)
        assert created.enrichment_status == "pending"

        enrichment = EnrichmentResult(
            themes=[{"theme": "billing", "confidence": 0.95}],
            sentiment_confidence=0.87,
            severity_score=4,
            severity_factors=["financial_impact", "repeated_issue"],
            language_code="en",
            language_confidence=0.99,
        )

        store.update_enrichment(created.id, enrichment)

        retrieved = store.get(created.id)
        assert retrieved is not None
        assert retrieved.enrichment_status == "completed"
        assert retrieved.enrichment_result is not None
        assert retrieved.enrichment_result.sentiment_confidence == 0.87
        assert retrieved.enrichment_result.severity_score == 4
        assert len(retrieved.enrichment_result.themes) == 1
        assert retrieved.enrichment_result.themes[0]["theme"] == "billing"
        assert retrieved.enrichment_result.language_code == "en"

    def test_enrichment_updates_status_to_completed(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Bob",
            phone="5551234567",
            core_request="Feedback",
            sentiment="positive",
            praise_text="Great service!",
        )
        created = store.create(data)

        enrichment = EnrichmentResult(
            themes=[{"theme": "support_experience", "confidence": 0.9}],
            sentiment_confidence=0.95,
            severity_score=1,
            severity_factors=[],
        )

        store.update_enrichment(created.id, enrichment)

        status = store.get_status(created.id)
        assert status is not None
        assert status.enrichment_status == "completed"


class TestMarkEnrichmentFailed:
    """Tests for SubmissionStore.mark_enrichment_failed()."""

    def test_marks_as_failed(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Test",
            email="test@test.com",
            core_request="Request",
            sentiment="neutral",
            comment_text="A comment.",
        )
        created = store.create(data)

        store.mark_enrichment_failed(created.id, reason="NLP processing error")

        retrieved = store.get(created.id)
        assert retrieved is not None
        assert retrieved.enrichment_status == "failed"

    def test_marks_as_timeout(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Test",
            email="test@test.com",
            core_request="Request",
            sentiment="negative",
            issue_category="outage",
            detailed_description="Complete outage for hours.",
        )
        created = store.create(data)

        store.mark_enrichment_failed(created.id, reason="Exceeded 30s", status="timeout")

        retrieved = store.get(created.id)
        assert retrieved is not None
        assert retrieved.enrichment_status == "timeout"

    def test_invalid_status_defaults_to_failed(self, store: SubmissionStore):
        data = SubmissionCreate(
            customer_name="Test",
            email="test@test.com",
            core_request="Request",
            sentiment="neutral",
            comment_text="Feedback.",
        )
        created = store.create(data)

        store.mark_enrichment_failed(created.id, reason="Error", status="invalid_status")

        retrieved = store.get(created.id)
        assert retrieved is not None
        assert retrieved.enrichment_status == "failed"


class TestListBySentiment:
    """Tests for SubmissionStore.list_by_sentiment()."""

    def test_returns_only_matching_sentiment(self, store: SubmissionStore):
        # Create one of each sentiment
        store.create(
            SubmissionCreate(
                customer_name="Neg",
                email="n@test.com",
                core_request="Issue",
                sentiment="negative",
                issue_category="billing",
                detailed_description="Billing problem here.",
            )
        )
        store.create(
            SubmissionCreate(
                customer_name="Pos",
                phone="5551234567",
                core_request="Praise",
                sentiment="positive",
                praise_text="Great!",
            )
        )
        store.create(
            SubmissionCreate(
                customer_name="Neu",
                email="neu@test.com",
                core_request="Comment",
                sentiment="neutral",
                comment_text="Just a thought.",
            )
        )

        negatives = store.list_by_sentiment("negative")
        assert len(negatives) == 1
        assert negatives[0].sentiment == "negative"
        assert negatives[0].customer_name == "Neg"

    def test_respects_limit_and_offset(self, store: SubmissionStore):
        # Create 3 negative submissions
        for i in range(3):
            store.create(
                SubmissionCreate(
                    customer_name=f"User{i}",
                    email=f"user{i}@test.com",
                    core_request=f"Issue {i}",
                    sentiment="negative",
                    issue_category="billing",
                    detailed_description=f"Description for issue {i}.",
                )
            )

        # Limit to 2
        result = store.list_by_sentiment("negative", limit=2, offset=0)
        assert len(result) == 2

        # Offset by 2
        result = store.list_by_sentiment("negative", limit=2, offset=2)
        assert len(result) == 1

    def test_returns_empty_list_for_no_matches(self, store: SubmissionStore):
        result = store.list_by_sentiment("positive")
        assert result == []

    def test_ordered_by_created_at_descending(self, store: SubmissionStore):
        # Create 3 submissions - they'll have increasing timestamps
        for i in range(3):
            store.create(
                SubmissionCreate(
                    customer_name=f"User{i}",
                    email=f"user{i}@test.com",
                    core_request=f"Request {i}",
                    sentiment="neutral",
                    comment_text=f"Comment {i}.",
                )
            )

        result = store.list_by_sentiment("neutral")
        assert len(result) == 3
        # Newest first
        for i in range(len(result) - 1):
            assert result[i].created_at >= result[i + 1].created_at


class TestCountBySentiment:
    """Tests for SubmissionStore.count_by_sentiment()."""

    def test_returns_correct_counts(self, store: SubmissionStore):
        # Create 2 negative, 1 positive, 3 neutral
        for _ in range(2):
            store.create(
                SubmissionCreate(
                    customer_name="Neg",
                    email="n@test.com",
                    core_request="Issue",
                    sentiment="negative",
                    issue_category="billing",
                    detailed_description="Billing problem here.",
                )
            )
        store.create(
            SubmissionCreate(
                customer_name="Pos",
                phone="5551234567",
                core_request="Praise",
                sentiment="positive",
                praise_text="Great!",
            )
        )
        for _ in range(3):
            store.create(
                SubmissionCreate(
                    customer_name="Neu",
                    email="neu@test.com",
                    core_request="Comment",
                    sentiment="neutral",
                    comment_text="Just a thought.",
                )
            )

        counts = store.count_by_sentiment()

        assert counts["negative"]["total"] == 2
        assert counts["positive"]["total"] == 1
        assert counts["neutral"]["total"] == 3

    def test_groups_by_progress_state(self, store: SubmissionStore):
        # Create 2 negative submissions, advance one
        sub1 = store.create(
            SubmissionCreate(
                customer_name="A",
                email="a@test.com",
                core_request="Issue 1",
                sentiment="negative",
                issue_category="outage",
                detailed_description="Outage description here.",
            )
        )
        store.create(
            SubmissionCreate(
                customer_name="B",
                email="b@test.com",
                core_request="Issue 2",
                sentiment="negative",
                issue_category="billing",
                detailed_description="Billing issue details.",
            )
        )

        # Advance sub1 to 75%
        store.update_progress(sub1.id, 75)

        counts = store.count_by_sentiment()

        assert counts["negative"]["total"] == 2
        assert counts["negative"]["by_progress"][50] == 1
        assert counts["negative"]["by_progress"][75] == 1

    def test_empty_store_returns_empty_dict(self, store: SubmissionStore):
        counts = store.count_by_sentiment()
        assert counts == {}
