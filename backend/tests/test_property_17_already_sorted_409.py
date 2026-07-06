"""Property 17: 409 Conflict on already-sorted submission.

For any submission that has already been sorted (no longer in neutral/unsorted state),
a PATCH sort request SHALL return 409 Conflict.

**Validates: Requirements 11.6**
"""

import os
import tempfile
import uuid

# Set up temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.database import get_connection, init_db
from app.main import app
from app.services.admin_review_queue import AdminReviewQueue
from app.services.auth_service import AuthService

# Initialize DB once at module load
init_db()

_client = TestClient(app)

# Valid issue categories
VALID_CATEGORIES = [
    "billing",
    "network_speed",
    "outage",
    "support_experience",
    "device_hardware",
    "pricing",
]

# --- Strategies ---

target_sentiments = st.sampled_from(["negative", "positive"])
issue_categories = st.sampled_from(VALID_CATEGORIES)

customer_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
    min_size=1,
    max_size=50,
).filter(lambda s: len(s.strip()) >= 1)

comment_texts = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=200,
).filter(lambda s: len(s.strip()) >= 1)


# --- Helpers ---


def _reset_db():
    """Clear all tables between test runs."""
    with get_connection() as conn:
        conn.execute("DELETE FROM admin_review_queue")
        conn.execute("DELETE FROM tickets")
        conn.execute("DELETE FROM state_transitions")
        conn.execute("DELETE FROM marketing_log")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.execute("DELETE FROM submissions")
        conn.commit()


def _create_admin_token() -> str:
    """Create an admin user and return a valid session token."""
    auth = AuthService()
    auth.create_admin("testadmin", "testpassword123")
    session = auth.login("testadmin", "testpassword123")
    assert session is not None
    return session.token


def _create_neutral_submission_and_enqueue(
    customer_name: str, comment_text: str
) -> str:
    """Create a neutral submission directly in DB and enqueue it.

    Returns the submission_id.
    """
    submission_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO submissions
            (id, created_at, customer_name, email, core_request, sentiment,
             progress_state, comment_text, enrichment_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                submission_id,
                now,
                customer_name,
                "test@example.com",
                "General feedback",
                "neutral",
                25,
                comment_text,
                "pending",
            ),
        )
        conn.commit()

    queue = AdminReviewQueue()
    queue.enqueue(submission_id)
    return submission_id


# --- Property Tests ---


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    customer_name=customer_names,
    comment_text=comment_texts,
    first_sort_sentiment=target_sentiments,
    first_sort_category=issue_categories,
    second_sort_sentiment=target_sentiments,
    second_sort_category=issue_categories,
)
def test_already_sorted_submission_returns_409(
    customer_name: str,
    comment_text: str,
    first_sort_sentiment: str,
    first_sort_category: str,
    second_sort_sentiment: str,
    second_sort_category: str,
):
    """Property 17: 409 Conflict on already-sorted submission.

    For any submission that has already been sorted (no longer in neutral/unsorted state),
    a PATCH sort request SHALL return 409 Conflict.

    Feature: sentiment-routed-frontend, Property 17: 409 Conflict on already-sorted submission
    **Validates: Requirements 11.6**
    """
    _reset_db()

    # Setup: create admin token and a neutral submission in the queue
    token = _create_admin_token()
    submission_id = _create_neutral_submission_and_enqueue(customer_name, comment_text)

    # Step 1: Sort the submission successfully (first sort)
    first_sort_body = {"target_sentiment": first_sort_sentiment}
    if first_sort_sentiment == "negative":
        first_sort_body["issue_category"] = first_sort_category

    response = _client.patch(
        f"/api/admin/queue/{submission_id}/sort",
        json=first_sort_body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, (
        f"Precondition failed: first sort should succeed, "
        f"got {response.status_code}: {response.text}"
    )

    # Verify: submission is no longer in queue
    queue = AdminReviewQueue()
    assert not queue.is_queued(submission_id), (
        "Precondition: submission should be removed from queue after first sort"
    )

    # Step 2: Attempt to sort the same submission again → expect 409 Conflict
    second_sort_body = {"target_sentiment": second_sort_sentiment}
    if second_sort_sentiment == "negative":
        second_sort_body["issue_category"] = second_sort_category

    response = _client.patch(
        f"/api/admin/queue/{submission_id}/sort",
        json=second_sort_body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409, (
        f"Property 17 violated: Expected 409 Conflict for already-sorted submission, "
        f"got {response.status_code}: {response.text}"
    )
    assert "already sorted" in response.json()["detail"].lower(), (
        f"Expected detail to mention 'already sorted', got: {response.json()['detail']}"
    )


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    sort_sentiment=target_sentiments,
    sort_category=issue_categories,
)
def test_submission_never_in_queue_returns_409(
    sort_sentiment: str,
    sort_category: str,
):
    """Property 17 (variant): Sorting a submission that was never in the queue returns 409.

    For any submission that exists but was never enqueued (not in neutral/unsorted state),
    a PATCH sort request SHALL return 409 Conflict.

    Feature: sentiment-routed-frontend, Property 17: 409 Conflict on already-sorted submission
    **Validates: Requirements 11.6**
    """
    _reset_db()

    # Setup: create admin token
    token = _create_admin_token()

    # Create a submission that is NOT in the queue (e.g., a negative submission that was
    # never neutral, so never enqueued)
    submission_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO submissions
            (id, created_at, customer_name, email, core_request, sentiment,
             progress_state, enrichment_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                submission_id,
                now,
                "Test User",
                "test@example.com",
                "My issue description",
                "negative",
                50,
                "pending",
            ),
        )
        conn.commit()

    # Attempt to sort this non-queued submission → expect 409 Conflict
    sort_body = {"target_sentiment": sort_sentiment}
    if sort_sentiment == "negative":
        sort_body["issue_category"] = sort_category

    response = _client.patch(
        f"/api/admin/queue/{submission_id}/sort",
        json=sort_body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409, (
        f"Property 17 violated: Expected 409 Conflict for submission never in queue, "
        f"got {response.status_code}: {response.text}"
    )
    assert "already sorted" in response.json()["detail"].lower(), (
        f"Expected detail to mention 'already sorted', got: {response.json()['detail']}"
    )
