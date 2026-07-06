"""Property 25: Dashboard aggregation correctness.

For any set of submissions in the store, the dashboard summary SHALL report
counts by sentiment route and Progress_State that exactly match the actual data.

**Validates: Requirements 15.1**
"""

import os
import tempfile

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

from collections import Counter

from fastapi.testclient import TestClient
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.database import get_connection, init_db
from app.main import app
from app.models.submission import SubmissionCreate
from app.services.auth_service import AuthService
from app.services.submission_store import SubmissionStore

# Initialize DB once at module load
init_db()

_client = TestClient(app)

# Valid sentiments and their initial progress states
_SENTIMENTS = ["negative", "positive", "neutral"]
_INITIAL_PROGRESS = {"negative": 50, "positive": 100, "neutral": 25}

# Valid issue categories for negative submissions
_ISSUE_CATEGORIES = [
    "billing",
    "network_speed",
    "outage",
    "support_experience",
    "device_hardware",
    "pricing",
]

# All valid progress states that can be assigned
_PROGRESS_STATES = [25, 50, 75, 100]


def _reset_db():
    """Clear all tables between test runs."""
    with get_connection() as conn:
        conn.execute("DELETE FROM admin_review_queue")
        conn.execute("DELETE FROM state_transitions")
        conn.execute("DELETE FROM tickets")
        conn.execute("DELETE FROM marketing_log")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.execute("DELETE FROM submissions")
        conn.commit()


def _get_admin_token() -> str:
    """Create an admin user and return a valid session token."""
    auth = AuthService()
    auth.create_admin("testadmin", "testpass123")
    session = auth.login("testadmin", "testpass123")
    assert session is not None
    return session.token


# Strategy: generate a list of (sentiment, progress_state) pairs representing submissions
submission_spec_strategy = st.lists(
    st.tuples(
        st.sampled_from(_SENTIMENTS),
        st.sampled_from(_PROGRESS_STATES),
    ),
    min_size=1,
    max_size=20,
)


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(submission_specs=submission_spec_strategy)
def test_dashboard_aggregation_matches_actual_data(submission_specs):
    """Property 25: Dashboard counts by sentiment and progress state match actual data.

    Feature: sentiment-routed-frontend, Property 25: Dashboard aggregation correctness
    **Validates: Requirements 15.1**
    """
    _reset_db()

    store = SubmissionStore()

    # Create submissions with specified sentiments and then override progress states
    for sentiment, progress_state in submission_specs:
        # Build the SubmissionCreate with appropriate fields per sentiment
        if sentiment == "negative":
            data = SubmissionCreate(
                customer_name="Test User",
                email="test@example.com",
                core_request="Test request",
                sentiment="negative",
                issue_category="billing",
                detailed_description="A detailed description of the issue for testing.",
            )
        elif sentiment == "positive":
            data = SubmissionCreate(
                customer_name="Test User",
                email="test@example.com",
                core_request="Test request",
                sentiment="positive",
                praise_text="Great service!",
                social_sharing=False,
            )
        else:  # neutral
            data = SubmissionCreate(
                customer_name="Test User",
                email="test@example.com",
                core_request="Test request",
                sentiment="neutral",
                comment_text="Just a comment",
            )

        submission = store.create(data)

        # Override the progress state to the desired value if different from initial
        initial_progress = _INITIAL_PROGRESS[sentiment]
        if progress_state != initial_progress:
            store.update_progress(submission.id, progress_state)

    # Get admin token and call the dashboard endpoint
    token = _get_admin_token()
    response = _client.get(
        "/api/admin/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, (
        f"Dashboard endpoint returned {response.status_code}: {response.text}"
    )

    dashboard = response.json()

    # Compute expected counts from the input specs
    expected_by_sentiment: Counter = Counter()
    expected_by_progress: Counter = Counter()

    for sentiment, progress_state in submission_specs:
        expected_by_sentiment[sentiment] += 1
        expected_by_progress[str(progress_state)] += 1

    # Verify total submissions
    assert dashboard["total_submissions"] == len(submission_specs), (
        f"Expected total_submissions={len(submission_specs)}, "
        f"got {dashboard['total_submissions']}"
    )

    # Verify by_sentiment counts
    for sentiment in _SENTIMENTS:
        expected_count = expected_by_sentiment.get(sentiment, 0)
        actual_count = dashboard["by_sentiment"].get(sentiment, 0)
        assert actual_count == expected_count, (
            f"by_sentiment['{sentiment}']: expected {expected_count}, got {actual_count}"
        )

    # Verify by_progress_state counts
    for progress in _PROGRESS_STATES:
        key = str(progress)
        expected_count = expected_by_progress.get(key, 0)
        actual_count = dashboard["by_progress_state"].get(key, 0)
        assert actual_count == expected_count, (
            f"by_progress_state['{key}']: expected {expected_count}, got {actual_count}"
        )
