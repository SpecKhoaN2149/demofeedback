"""Property 15: Sort-to-positive atomicity.

For any neutral submission in the AdminReviewQueue, sorting it to positive SHALL
atomically: (1) log the submission in the Marketing_Engine, (2) update the submission
Progress_State to 100%, and (3) remove the submission from the queue.

**Validates: Requirements 10.4**
"""

import os
import tempfile

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

from fastapi.testclient import TestClient
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.database import get_connection, init_db
from app.main import app
from app.services.auth_service import AuthService

# Initialize DB once at module load
init_db()

_client = TestClient(app)

# --- Helpers ---

_ADMIN_USERNAME = "testadmin"
_ADMIN_PASSWORD = "testpass123"


def _reset_db():
    """Clear all tables between test runs."""
    with get_connection() as conn:
        conn.execute("DELETE FROM marketing_log")
        conn.execute("DELETE FROM admin_review_queue")
        conn.execute("DELETE FROM state_transitions")
        conn.execute("DELETE FROM tickets")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.execute("DELETE FROM submissions")
        conn.commit()


def _create_admin_and_get_token() -> str:
    """Create an admin user and return a valid session token."""
    auth = AuthService()
    auth.create_admin(_ADMIN_USERNAME, _ADMIN_PASSWORD)
    session = auth.login(_ADMIN_USERNAME, _ADMIN_PASSWORD)
    assert session is not None
    return session.token


def _create_neutral_submission(customer_name: str, comment_text: str) -> str:
    """Create a neutral submission directly in the DB and enqueue it.

    Returns the submission_id.
    """
    import uuid
    from datetime import datetime, timezone

    submission_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.execute(
            """INSERT INTO submissions
            (id, created_at, customer_name, email, phone, core_request,
             sentiment, progress_state, comment_text, enrichment_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                submission_id,
                now,
                customer_name,
                "test@example.com",
                None,
                "general feedback",
                "neutral",
                25,
                comment_text,
                "pending",
            ),
        )
        # Record initial state transition
        conn.execute(
            """INSERT INTO state_transitions
            (submission_id, previous_state, new_state, timestamp)
            VALUES (?, ?, ?, ?)""",
            (submission_id, 0, 25, now),
        )
        # Enqueue in admin review queue
        conn.execute(
            "INSERT INTO admin_review_queue (submission_id, queued_at) VALUES (?, ?)",
            (submission_id, now),
        )
        conn.commit()

    return submission_id


# --- Strategies ---

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


# --- Property Test ---


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(customer_name=customer_names, comment_text=comment_texts)
def test_sort_to_positive_atomicity(customer_name: str, comment_text: str):
    """Property 15: Sort-to-positive atomicity.

    Feature: sentiment-routed-frontend, Property 15: Sort-to-positive atomicity
    **Validates: Requirements 10.4**

    For any neutral submission in the AdminReviewQueue, sorting it to positive SHALL
    atomically:
      (1) log the submission in the Marketing_Engine (marketing_log entry created),
      (2) update the submission Progress_State to 100%,
      (3) remove the submission from the queue.
    """
    _reset_db()

    # Setup: create admin and get auth token
    token = _create_admin_and_get_token()

    # Setup: create a neutral submission and enqueue it
    submission_id = _create_neutral_submission(customer_name, comment_text)

    # Act: sort the submission to positive via PATCH endpoint
    response = _client.patch(
        f"/api/admin/queue/{submission_id}/sort",
        json={"target_sentiment": "positive"},
        headers={"Authorization": f"Bearer {token}"},
    )

    # The sort operation should succeed
    assert response.status_code == 200, (
        f"Expected 200 for sort-to-positive, got {response.status_code}: {response.text}"
    )

    # Verify condition (1): marketing_log entry was created for this submission
    with get_connection() as conn:
        marketing_row = conn.execute(
            "SELECT * FROM marketing_log WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()

    assert marketing_row is not None, (
        f"Expected marketing_log entry for submission {submission_id}, but none found"
    )
    assert marketing_row["customer_name"] == customer_name, (
        f"Expected customer_name '{customer_name}' in marketing_log, "
        f"got '{marketing_row['customer_name']}'"
    )

    # Verify condition (2): submission progress_state is now 100%
    with get_connection() as conn:
        submission_row = conn.execute(
            "SELECT progress_state FROM submissions WHERE id = ?",
            (submission_id,),
        ).fetchone()

    assert submission_row is not None, (
        f"Submission {submission_id} should still exist in submissions table"
    )
    assert submission_row["progress_state"] == 100, (
        f"Expected progress_state 100, got {submission_row['progress_state']}"
    )

    # Verify condition (3): submission is no longer in the admin review queue
    with get_connection() as conn:
        queue_row = conn.execute(
            "SELECT * FROM admin_review_queue WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()

    assert queue_row is None, (
        f"Expected submission {submission_id} to be removed from admin_review_queue, "
        f"but it was still found"
    )
