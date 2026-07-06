"""Unit tests for AdminReviewQueue service."""

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
from app.services.admin_review_queue import AdminReviewQueue


@pytest.fixture(autouse=True)
def setup_db():
    """Initialize a fresh database for each test."""
    init_db()
    # Clear tables between tests
    with get_connection() as conn:
        conn.execute("DELETE FROM admin_review_queue")
        conn.execute("DELETE FROM submissions")
        conn.commit()
    yield


def _create_submission(submission_id: str, customer_name: str = "Test User") -> str:
    """Helper to insert a submission record for FK constraints."""
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO submissions
            (id, created_at, customer_name, core_request, sentiment, progress_state, comment_text)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (submission_id, now, customer_name, "test request", "neutral", 25, "test comment"),
        )
        conn.commit()
    return submission_id


class TestEnqueue:
    def test_enqueue_adds_to_queue(self):
        queue = AdminReviewQueue()
        sub_id = _create_submission(str(uuid.uuid4()))
        queue.enqueue(sub_id)
        assert queue.is_queued(sub_id) is True

    def test_enqueue_sets_queued_at_timestamp(self):
        queue = AdminReviewQueue()
        sub_id = _create_submission(str(uuid.uuid4()))
        before = datetime.now(timezone.utc)
        queue.enqueue(sub_id)
        after = datetime.now(timezone.utc)

        entries = queue.list_queue()
        assert len(entries) == 1
        queued_at = datetime.fromisoformat(entries[0]["queued_at"])
        # Ensure queued_at has tzinfo for comparison
        if queued_at.tzinfo is None:
            queued_at = queued_at.replace(tzinfo=timezone.utc)
        assert before <= queued_at <= after


class TestListQueue:
    def test_list_queue_empty(self):
        queue = AdminReviewQueue()
        result = queue.list_queue()
        assert result == []

    def test_list_queue_returns_entries_ordered_by_queued_at_asc(self):
        queue = AdminReviewQueue()
        ids = []
        for i in range(3):
            sub_id = _create_submission(str(uuid.uuid4()), f"User {i}")
            queue.enqueue(sub_id)
            ids.append(sub_id)

        result = queue.list_queue()
        assert len(result) == 3
        # Should be in insertion order (oldest first)
        for i, entry in enumerate(result):
            assert entry["submission_id"] == ids[i]

    def test_list_queue_pagination_limit(self):
        queue = AdminReviewQueue()
        for _ in range(5):
            sub_id = _create_submission(str(uuid.uuid4()))
            queue.enqueue(sub_id)

        result = queue.list_queue(limit=2)
        assert len(result) == 2

    def test_list_queue_pagination_offset(self):
        queue = AdminReviewQueue()
        ids = []
        for _ in range(5):
            sub_id = _create_submission(str(uuid.uuid4()))
            queue.enqueue(sub_id)
            ids.append(sub_id)

        result = queue.list_queue(limit=2, offset=2)
        assert len(result) == 2
        assert result[0]["submission_id"] == ids[2]
        assert result[1]["submission_id"] == ids[3]

    def test_list_queue_includes_submission_details(self):
        queue = AdminReviewQueue()
        sub_id = _create_submission(str(uuid.uuid4()), "Alice")
        queue.enqueue(sub_id)

        result = queue.list_queue()
        assert len(result) == 1
        entry = result[0]
        assert entry["customer_name"] == "Alice"
        assert entry["comment_text"] == "test comment"
        assert "created_at" in entry
        # The queue now exposes a parsed enrichment_summary (None until the NLP
        # enrichment completes) plus the raw enrichment_status.
        assert "enrichment_summary" in entry
        assert "enrichment_status" in entry


class TestRemove:
    def test_remove_deletes_entry(self):
        queue = AdminReviewQueue()
        sub_id = _create_submission(str(uuid.uuid4()))
        queue.enqueue(sub_id)
        assert queue.is_queued(sub_id) is True

        queue.remove(sub_id)
        assert queue.is_queued(sub_id) is False

    def test_remove_nonexistent_does_not_raise(self):
        queue = AdminReviewQueue()
        # Should not raise an error
        queue.remove(str(uuid.uuid4()))


class TestIsQueued:
    def test_is_queued_false_when_not_in_queue(self):
        queue = AdminReviewQueue()
        sub_id = _create_submission(str(uuid.uuid4()))
        assert queue.is_queued(sub_id) is False

    def test_is_queued_true_when_in_queue(self):
        queue = AdminReviewQueue()
        sub_id = _create_submission(str(uuid.uuid4()))
        queue.enqueue(sub_id)
        assert queue.is_queued(sub_id) is True

    def test_is_queued_false_after_removal(self):
        queue = AdminReviewQueue()
        sub_id = _create_submission(str(uuid.uuid4()))
        queue.enqueue(sub_id)
        queue.remove(sub_id)
        assert queue.is_queued(sub_id) is False
