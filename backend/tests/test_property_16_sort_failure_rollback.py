"""Property 16: Sort failure leaves queue unchanged.

For any sort operation where the downstream service (TicketingPipeline or MarketingEngine)
fails, the submission SHALL remain in the Admin_Review_Queue with its Progress_State unchanged.

**Validates: Requirements 10.6**
"""

import os
import tempfile
import uuid
from unittest.mock import patch

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


# --- Property Tests ---


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    customer_name=customer_names,
    comment_text=comment_texts,
    category=issue_category_strategy,
)
def test_sort_to_negative_failure_leaves_queue_unchanged(
    customer_name: str,
    comment_text: str,
    category: str,
):
    """Property 16: Sort failure (TicketingPipeline) leaves queue unchanged.

    When TicketingPipeline.create_ticket raises an exception during sort-to-negative,
    the submission SHALL remain in the Admin_Review_Queue with Progress_State 25%.

    Feature: sentiment-routed-frontend, Property 16: Sort failure leaves queue unchanged
    **Validates: Requirements 10.6**
    """
    _reset_db()

    # Setup: create admin token and a neutral submission in the queue
    token = _create_admin_token()
    submission_id = _create_neutral_submission_and_enqueue(customer_name, comment_text)

    # Verify preconditions
    queue = AdminReviewQueue()
    assert queue.is_queued(submission_id), "Precondition: submission should be in queue"

    with get_connection() as conn:
        row = conn.execute(
            "SELECT progress_state FROM submissions WHERE id = ?", (submission_id,)
        ).fetchone()
        assert row["progress_state"] == 25, "Precondition: progress should be 25%"

    # Act: call the PATCH sort endpoint with a failing TicketingPipeline
    with patch(
        "app.routes.admin._ticketing_pipeline.create_ticket",
        side_effect=RuntimeError("Downstream service unavailable"),
    ):
        response = _client.patch(
            f"/api/admin/queue/{submission_id}/sort",
            json={"target_sentiment": "negative", "issue_category": category},
            headers={"Authorization": f"Bearer {token}"},
        )

    # Verify: API returns 500
    assert response.status_code == 500, (
        f"Expected 500 from sort endpoint when service fails, got {response.status_code}"
    )

    # Verify: submission remains in queue
    assert queue.is_queued(submission_id), (
        "Rollback failed: submission should still be in the queue after service failure"
    )

    # Verify: progress_state unchanged at 25%
    with get_connection() as conn:
        row = conn.execute(
            "SELECT progress_state FROM submissions WHERE id = ?", (submission_id,)
        ).fetchone()
        assert row["progress_state"] == 25, (
            f"Rollback failed: progress_state should remain 25%, got {row['progress_state']}"
        )


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    customer_name=customer_names,
    comment_text=comment_texts,
)
def test_sort_to_positive_failure_leaves_queue_unchanged(
    customer_name: str,
    comment_text: str,
):
    """Property 16: Sort failure (MarketingEngine) leaves queue unchanged.

    When MarketingEngine.log_praise raises an exception during sort-to-positive,
    the submission SHALL remain in the Admin_Review_Queue with Progress_State 25%.

    Feature: sentiment-routed-frontend, Property 16: Sort failure leaves queue unchanged
    **Validates: Requirements 10.6**
    """
    _reset_db()

    # Setup: create admin token and a neutral submission in the queue
    token = _create_admin_token()
    submission_id = _create_neutral_submission_and_enqueue(customer_name, comment_text)

    # Verify preconditions
    queue = AdminReviewQueue()
    assert queue.is_queued(submission_id), "Precondition: submission should be in queue"

    with get_connection() as conn:
        row = conn.execute(
            "SELECT progress_state FROM submissions WHERE id = ?", (submission_id,)
        ).fetchone()
        assert row["progress_state"] == 25, "Precondition: progress should be 25%"

    # Act: call the PATCH sort endpoint with a failing MarketingEngine
    with patch(
        "app.routes.admin._marketing_engine.log_praise",
        side_effect=RuntimeError("Marketing service unavailable"),
    ):
        response = _client.patch(
            f"/api/admin/queue/{submission_id}/sort",
            json={"target_sentiment": "positive"},
            headers={"Authorization": f"Bearer {token}"},
        )

    # Verify: API returns 500
    assert response.status_code == 500, (
        f"Expected 500 from sort endpoint when service fails, got {response.status_code}"
    )

    # Verify: submission remains in queue
    assert queue.is_queued(submission_id), (
        "Rollback failed: submission should still be in the queue after service failure"
    )

    # Verify: progress_state unchanged at 25%
    with get_connection() as conn:
        row = conn.execute(
            "SELECT progress_state FROM submissions WHERE id = ?", (submission_id,)
        ).fetchone()
        assert row["progress_state"] == 25, (
            f"Rollback failed: progress_state should remain 25%, got {row['progress_state']}"
        )
