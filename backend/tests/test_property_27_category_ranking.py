"""Property-based test for Property 27: Top 5 category ranking by frequency.

For any set of negative submissions, the top 5 Issue_Categories displayed SHALL be
ordered by submission frequency descending, and the frequency counts SHALL match
the actual number of submissions per category.

**Validates: Requirements 15.5**
"""

import os
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timezone

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# Set up temp database before importing app modules
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["SUBMISSIONS_DB_PATH"] = _tmp_db.name
_tmp_db.close()

from fastapi.testclient import TestClient

from app.database import get_connection, init_db
from app.main import app
from app.services.auth_service import AuthService

# Initialize DB once at module load
init_db()

_client = TestClient(app)

# Valid issue categories for negative submissions
VALID_CATEGORIES = [
    "billing",
    "network_speed",
    "outage",
    "support_experience",
    "device_hardware",
    "pricing",
]


def _reset_db():
    """Clear all tables between test runs."""
    with get_connection() as conn:
        conn.execute("DELETE FROM admin_review_queue")
        conn.execute("DELETE FROM state_transitions")
        conn.execute("DELETE FROM tickets")
        conn.execute("DELETE FROM marketing_log")
        conn.execute("DELETE FROM submissions")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.commit()


def _get_admin_token() -> str:
    """Create an admin user and return a valid session token."""
    auth = AuthService()
    auth.create_admin("testadmin", "testpass123")
    session = auth.login("testadmin", "testpass123")
    assert session is not None
    return session.token


def _create_negative_submission(category: str) -> str:
    """Insert a negative submission with the given issue_category directly into DB.

    Returns the submission_id.
    """
    submission_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO submissions
            (id, created_at, customer_name, core_request, sentiment,
             progress_state, issue_category, comment_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                submission_id,
                now,
                "Test User",
                "test request",
                "negative",
                50,
                category,
                "test comment",
            ),
        )
        conn.commit()
    return submission_id


# Strategy: generate a list of 5-30 categories drawn from the valid set
category_lists = st.lists(
    st.sampled_from(VALID_CATEGORIES),
    min_size=5,
    max_size=30,
)


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(categories=category_lists)
def test_top_5_category_ranking_by_frequency(categories: list[str]):
    """Property 27: Top 5 category ranking by frequency.

    For any set of negative submissions, the top 5 Issue_Categories displayed
    SHALL be ordered by submission frequency descending, and the frequency counts
    SHALL match the actual number of submissions per category.

    **Validates: Requirements 15.5**
    """
    _reset_db()

    # Create negative submissions with the generated categories
    for cat in categories:
        _create_negative_submission(cat)

    # Get admin token and call the dashboard endpoint
    token = _get_admin_token()
    response = _client.get(
        "/api/admin/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    data = response.json()
    top_categories = data["top_categories"]

    # Compute expected frequency counts
    actual_counts = Counter(categories)
    # Sort by count descending, take top 5
    expected_top = actual_counts.most_common(5)

    # 1. top_categories has at most 5 entries
    assert len(top_categories) <= 5, (
        f"Expected at most 5 top categories, got {len(top_categories)}"
    )

    # 2. Categories are ordered by count descending
    counts_returned = [entry["count"] for entry in top_categories]
    for i in range(len(counts_returned) - 1):
        assert counts_returned[i] >= counts_returned[i + 1], (
            f"Categories not in descending frequency order: "
            f"count[{i}]={counts_returned[i]} < count[{i+1}]={counts_returned[i+1]}"
        )

    # 3. Counts match the actual number of submissions with that category
    for entry in top_categories:
        category = entry["category"]
        reported_count = entry["count"]
        expected_count = actual_counts[category]
        assert reported_count == expected_count, (
            f"Count mismatch for category '{category}': "
            f"reported {reported_count}, expected {expected_count}"
        )

    # Verify we got the correct number of entries
    # (number of distinct categories, capped at 5)
    expected_num_entries = min(len(actual_counts), 5)
    assert len(top_categories) == expected_num_entries, (
        f"Expected {expected_num_entries} top categories, got {len(top_categories)}"
    )
