"""Property 14: Sort-to-negative atomicity.

For any neutral submission in the AdminReviewQueue, sorting it to negative with a valid
Issue_Category SHALL atomically: (1) create a high-priority Ticket, (2) update the
submission Progress_State to 50%, and (3) remove the submission from the queue.

**Validates: Requirements 10.3**
"""

import os
import tempfile
import uuid

# Set up temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

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

issue_category_strategy = st.sampled_from(VALID_CATEGORIES)

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
    from datetime import datetime, timezone

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


# --- Property Test ---


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    customer_name=customer_names,
    comment_text=comment_texts,
    category=issue_category_strategy,
)
def test_sort_to_negative_atomicity(
    customer_name: str,
    comment_text: str,
    category: str,
):
    """Property 14: Sort-to-negative atomicity.

    For any neutral submission in the AdminReviewQueue, sorting it to negative
    with a valid Issue_Category SHALL atomically:
    (1) create a high-priority Ticket,
    (2) update the submission Progress_State to 50%, and
    (3) remove the submission from the queue.

    Feature: sentiment-routed-frontend, Property 14: Sort-to-negative atomicity
    **Validates: Requirements 10.3**
    """
    _reset_db()

    # Setup: create admin token and a neutral submission in the queue
    token = _create_admin_token()
    submission_id = _create_neutral_submission_and_enqueue(customer_name, comment_text)

    # Verify preconditions: submission is in queue with progress 25%
    queue = AdminReviewQueue()
    assert queue.is_queued(submission_id), "Precondition: submission should be in queue"

    with get_connection() as conn:
        row = conn.execute(
            "SELECT progress_state FROM submissions WHERE id = ?", (submission_id,)
        ).fetchone()
        assert row["progress_state"] == 25, "Precondition: progress should be 25%"

    # Act: call the PATCH sort endpoint with target_sentiment="negative"
    response = _client.patch(
        f"/api/admin/queue/{submission_id}/sort",
        json={"target_sentiment": "negative", "issue_category": category},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, (
        f"Expected 200 from sort endpoint, got {response.status_code}: {response.text}"
    )

    # Verify condition (1): A high-priority ticket was created for this submission
    with get_connection() as conn:
        ticket_row = conn.execute(
            "SELECT * FROM tickets WHERE submission_id = ?", (submission_id,)
        ).fetchone()

    assert ticket_row is not None, (
        "Atomicity condition 1 failed: No ticket was created for the submission"
    )
    assert ticket_row["priority"] == "high", (
        f"Atomicity condition 1 failed: Ticket priority should be 'high', "
        f"got '{ticket_row['priority']}'"
    )
    assert ticket_row["issue_category"] == category, (
        f"Atomicity condition 1 failed: Ticket category should be '{category}', "
        f"got '{ticket_row['issue_category']}'"
    )
    assert ticket_row["status"] == "open", (
        f"Atomicity condition 1 failed: Ticket status should be 'open', "
        f"got '{ticket_row['status']}'"
    )

    # Verify condition (2): Submission progress_state updated to 50%
    with get_connection() as conn:
        sub_row = conn.execute(
            "SELECT progress_state FROM submissions WHERE id = ?", (submission_id,)
        ).fetchone()

    assert sub_row["progress_state"] == 50, (
        f"Atomicity condition 2 failed: Submission progress_state should be 50, "
        f"got {sub_row['progress_state']}"
    )

    # Verify condition (3): Submission removed from the queue
    assert not queue.is_queued(submission_id), (
        "Atomicity condition 3 failed: Submission should no longer be in the queue"
    )
