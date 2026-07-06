"""Property-based test for Property 13: Review queue ordered by submission timestamp ascending.

For any set of submissions in the Admin_Review_Queue, the list endpoint SHALL return them
ordered by submission timestamp ascending (oldest first).

**Validates: Requirements 10.1**
"""

import os
import tempfile
import uuid
from datetime import datetime, timezone

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# Set up temp database before importing app modules
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["SUBMISSIONS_DB_PATH"] = _tmp_db.name
_tmp_db.close()

from app.database import get_connection, init_db
from app.services.admin_review_queue import AdminReviewQueue

# Initialize DB once at module load
init_db()


def _reset_db():
    """Clear all tables between test runs."""
    with get_connection() as conn:
        conn.execute("DELETE FROM admin_review_queue")
        conn.execute("DELETE FROM submissions")
        conn.commit()


def _create_and_enqueue(queue: AdminReviewQueue) -> str:
    """Create a neutral submission and enqueue it in the admin review queue.

    Returns the submission_id.
    """
    submission_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO submissions
            (id, created_at, customer_name, core_request, sentiment, progress_state, comment_text)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (submission_id, now, "Test User", "test request", "neutral", 25, "test comment"),
        )
        conn.commit()
    queue.enqueue(submission_id)
    return submission_id


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(num_submissions=st.integers(min_value=1, max_value=20))
def test_queue_ordered_by_queued_at_ascending(num_submissions: int):
    """Property 13: For any set of submissions in the Admin_Review_Queue,
    the list endpoint SHALL return them ordered by queued_at ascending (oldest first).

    **Validates: Requirements 10.1**
    """
    # Reset DB state at the start of each generated example
    _reset_db()

    queue = AdminReviewQueue()

    # Create and enqueue a random number of submissions
    for _ in range(num_submissions):
        _create_and_enqueue(queue)

    # Retrieve the queue
    result = queue.list_queue(limit=100)

    # Assert we got back all the submissions we enqueued
    assert len(result) == num_submissions

    # Assert ordering: for any two consecutive entries, entry[i].queued_at <= entry[i+1].queued_at
    for i in range(len(result) - 1):
        current_queued_at = result[i]["queued_at"]
        next_queued_at = result[i + 1]["queued_at"]
        assert current_queued_at <= next_queued_at, (
            f"Queue not ordered by queued_at ascending: "
            f"entry[{i}].queued_at={current_queued_at} > entry[{i+1}].queued_at={next_queued_at}"
        )
