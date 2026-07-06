"""Integration tests for admin sort atomicity and error scenarios.

Tests the full API flow for sorting neutral submissions, verifying:
- Sort-to-negative: queue removal + ticket creation + progress update in single transaction
- Sort-to-positive: queue removal + marketing log + progress update
- Sort failure rollback: mock service failure, verify queue unchanged
- 409 on re-sort attempt

Uses pytest + TestClient against FastAPI app.

Validates: Requirements 10.3, 10.4, 10.6, 11.6
"""

import os
import tempfile

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.database import get_connection, init_db
from app.main import app
from app.services.auth_service import AuthService

# Initialize DB
init_db()

ADMIN_USERNAME = "sort_test_admin"
ADMIN_PASSWORD = "sortpass789"


@pytest.fixture(autouse=True)
def reset_db():
    """Reset all tables before each test to ensure isolation."""
    with get_connection() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.execute("DELETE FROM marketing_log")
        conn.execute("DELETE FROM admin_review_queue")
        conn.execute("DELETE FROM tickets")
        conn.execute("DELETE FROM state_transitions")
        conn.execute("DELETE FROM submissions")
        conn.commit()

    # Seed admin user
    auth = AuthService()
    auth.create_admin(ADMIN_USERNAME, ADMIN_PASSWORD)
    yield


@pytest.fixture
def client():
    """Provide a synchronous test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def admin_headers():
    """Return Authorization headers for admin requests."""
    auth = AuthService()
    session = auth.login(ADMIN_USERNAME, ADMIN_PASSWORD)
    return {"Authorization": f"Bearer {session.token}"}


def _create_neutral_submission(client) -> str:
    """Helper: create a neutral submission and return its ID."""
    payload = {
        "customer_name": "Sort Test User",
        "email": "sorttest@example.com",
        "core_request": "General feedback for testing sort operations",
        "sentiment": "neutral",
        "comment_text": "This is a neutral comment submitted for sort testing purposes.",
    }
    response = client.post("/api/submissions", json=payload)
    assert response.status_code == 201
    return response.json()["submission_id"]


# =============================================================================
# Sort-to-Negative Atomicity
# Validates: Requirement 10.3
# =============================================================================


class TestSortToNegativeAtomicity:
    """Verify sort-to-negative performs queue removal + ticket creation + progress update."""

    def test_sort_to_negative_creates_ticket_and_updates_progress(
        self, client, admin_headers
    ):
        """Sort-to-negative atomically creates ticket, sets progress to 50%, removes from queue.

        Validates: Requirement 10.3
        """
        submission_id = _create_neutral_submission(client)

        # Verify initial state: in queue, progress 25%
        status_resp = client.get(f"/api/submissions/{submission_id}/status")
        assert status_resp.json()["progress_state"] == 25

        queue_resp = client.get("/api/admin/queue", headers=admin_headers)
        queued_ids = [item["submission_id"] for item in queue_resp.json()["items"]]
        assert submission_id in queued_ids

        # Sort to negative
        sort_resp = client.patch(
            f"/api/admin/queue/{submission_id}/sort",
            json={"target_sentiment": "negative", "issue_category": "billing"},
            headers=admin_headers,
        )
        assert sort_resp.status_code == 200
        sort_data = sort_resp.json()
        assert sort_data["target_sentiment"] == "negative"
        assert sort_data["progress_state"] == 50

        # Verify queue removal
        queue_resp = client.get("/api/admin/queue", headers=admin_headers)
        queued_ids = [item["submission_id"] for item in queue_resp.json()["items"]]
        assert submission_id not in queued_ids

        # Verify ticket creation
        tickets_resp = client.get("/api/admin/tickets", headers=admin_headers)
        tickets = tickets_resp.json()
        ticket = next(
            (t for t in tickets if t["submission_id"] == submission_id), None
        )
        assert ticket is not None
        assert ticket["status"] == "open"
        assert ticket["priority"] == "high"
        assert ticket["issue_category"] == "billing"

        # Verify progress updated to 50%
        status_resp = client.get(f"/api/submissions/{submission_id}/status")
        assert status_resp.json()["progress_state"] == 50
        assert status_resp.json()["message"] == "Spectrum is working on this."

    def test_sort_to_negative_with_each_valid_category(self, client, admin_headers):
        """Sort-to-negative works for all valid issue categories.

        Validates: Requirement 10.3
        """
        categories = [
            "billing",
            "network_speed",
            "outage",
            "support_experience",
            "device_hardware",
            "pricing",
        ]
        for category in categories:
            submission_id = _create_neutral_submission(client)

            sort_resp = client.patch(
                f"/api/admin/queue/{submission_id}/sort",
                json={"target_sentiment": "negative", "issue_category": category},
                headers=admin_headers,
            )
            assert sort_resp.status_code == 200, f"Failed for category: {category}"

            # Verify ticket has correct category
            tickets_resp = client.get("/api/admin/tickets", headers=admin_headers)
            ticket = next(
                (
                    t
                    for t in tickets_resp.json()
                    if t["submission_id"] == submission_id
                ),
                None,
            )
            assert ticket is not None
            assert ticket["issue_category"] == category


# =============================================================================
# Sort-to-Positive Atomicity
# Validates: Requirement 10.4
# =============================================================================


class TestSortToPositiveAtomicity:
    """Verify sort-to-positive performs queue removal + marketing log + progress update."""

    def test_sort_to_positive_logs_marketing_and_updates_progress(
        self, client, admin_headers
    ):
        """Sort-to-positive atomically logs marketing, sets progress to 100%, removes from queue.

        Validates: Requirement 10.4
        """
        submission_id = _create_neutral_submission(client)

        # Verify initial state
        status_resp = client.get(f"/api/submissions/{submission_id}/status")
        assert status_resp.json()["progress_state"] == 25

        queue_resp = client.get("/api/admin/queue", headers=admin_headers)
        queued_ids = [item["submission_id"] for item in queue_resp.json()["items"]]
        assert submission_id in queued_ids

        # Sort to positive
        sort_resp = client.patch(
            f"/api/admin/queue/{submission_id}/sort",
            json={"target_sentiment": "positive"},
            headers=admin_headers,
        )
        assert sort_resp.status_code == 200
        sort_data = sort_resp.json()
        assert sort_data["target_sentiment"] == "positive"
        assert sort_data["progress_state"] == 100

        # Verify queue removal
        queue_resp = client.get("/api/admin/queue", headers=admin_headers)
        queued_ids = [item["submission_id"] for item in queue_resp.json()["items"]]
        assert submission_id not in queued_ids

        # Verify marketing log entry
        marketing_resp = client.get("/api/admin/marketing", headers=admin_headers)
        items = marketing_resp.json()["items"]
        entry = next(
            (e for e in items if e["submission_id"] == submission_id), None
        )
        assert entry is not None
        assert entry["customer_name"] == "Sort Test User"

        # Verify progress at 100%
        status_resp = client.get(f"/api/submissions/{submission_id}/status")
        assert status_resp.json()["progress_state"] == 100

    def test_sort_to_positive_marketing_entry_has_correct_data(
        self, client, admin_headers
    ):
        """Sort-to-positive marketing log entry contains submission data.

        Validates: Requirement 10.4
        """
        # Create a neutral submission with specific data
        payload = {
            "customer_name": "Marketing Log User",
            "email": "mktg@example.com",
            "core_request": "Sharing my thoughts",
            "sentiment": "neutral",
            "comment_text": "The staff were really helpful during my last visit to the store.",
        }
        response = client.post("/api/submissions", json=payload)
        assert response.status_code == 201
        submission_id = response.json()["submission_id"]

        # Sort to positive
        sort_resp = client.patch(
            f"/api/admin/queue/{submission_id}/sort",
            json={"target_sentiment": "positive"},
            headers=admin_headers,
        )
        assert sort_resp.status_code == 200

        # Verify marketing log has correct customer name
        marketing_resp = client.get("/api/admin/marketing", headers=admin_headers)
        items = marketing_resp.json()["items"]
        entry = next(
            (e for e in items if e["submission_id"] == submission_id), None
        )
        assert entry is not None
        assert entry["customer_name"] == "Marketing Log User"


# =============================================================================
# Sort Failure Rollback
# Validates: Requirement 10.6
# =============================================================================


class TestSortFailureRollback:
    """Verify that when downstream services fail, submission stays in queue unchanged."""

    def test_ticketing_failure_leaves_queue_unchanged(self, client, admin_headers):
        """If TicketingPipeline.create_ticket fails, submission remains in queue with progress 25%.

        Validates: Requirement 10.6
        """
        submission_id = _create_neutral_submission(client)

        # Mock ticketing pipeline to raise an exception
        with patch(
            "app.routes.admin._ticketing_pipeline.create_ticket",
            side_effect=RuntimeError("Ticketing service unavailable"),
        ):
            sort_resp = client.patch(
                f"/api/admin/queue/{submission_id}/sort",
                json={"target_sentiment": "negative", "issue_category": "outage"},
                headers=admin_headers,
            )
            assert sort_resp.status_code == 500

        # Verify submission is still in queue
        queue_resp = client.get("/api/admin/queue", headers=admin_headers)
        queued_ids = [item["submission_id"] for item in queue_resp.json()["items"]]
        assert submission_id in queued_ids

        # Verify progress is unchanged (still 25%)
        status_resp = client.get(f"/api/submissions/{submission_id}/status")
        assert status_resp.json()["progress_state"] == 25

    def test_marketing_failure_leaves_queue_unchanged(self, client, admin_headers):
        """If MarketingEngine.log_praise fails, submission remains in queue with progress 25%.

        Validates: Requirement 10.6
        """
        submission_id = _create_neutral_submission(client)

        # Mock marketing engine to raise an exception
        with patch(
            "app.routes.admin._marketing_engine.log_praise",
            side_effect=RuntimeError("Marketing service unavailable"),
        ):
            sort_resp = client.patch(
                f"/api/admin/queue/{submission_id}/sort",
                json={"target_sentiment": "positive"},
                headers=admin_headers,
            )
            assert sort_resp.status_code == 500

        # Verify submission is still in queue
        queue_resp = client.get("/api/admin/queue", headers=admin_headers)
        queued_ids = [item["submission_id"] for item in queue_resp.json()["items"]]
        assert submission_id in queued_ids

        # Verify progress is unchanged (still 25%)
        status_resp = client.get(f"/api/submissions/{submission_id}/status")
        assert status_resp.json()["progress_state"] == 25

    def test_ticketing_failure_does_not_remove_from_queue(self, client, admin_headers):
        """On ticket creation failure, no ticket exists and queue entry is preserved.

        Validates: Requirement 10.6
        """
        submission_id = _create_neutral_submission(client)

        with patch(
            "app.routes.admin._ticketing_pipeline.create_ticket",
            side_effect=Exception("Connection timeout"),
        ):
            sort_resp = client.patch(
                f"/api/admin/queue/{submission_id}/sort",
                json={"target_sentiment": "negative", "issue_category": "billing"},
                headers=admin_headers,
            )
            assert sort_resp.status_code == 500

        # No ticket should have been created for this submission
        tickets_resp = client.get("/api/admin/tickets", headers=admin_headers)
        ticket = next(
            (t for t in tickets_resp.json() if t["submission_id"] == submission_id),
            None,
        )
        assert ticket is None

        # Queue entry preserved
        queue_resp = client.get("/api/admin/queue", headers=admin_headers)
        queued_ids = [item["submission_id"] for item in queue_resp.json()["items"]]
        assert submission_id in queued_ids


# =============================================================================
# 409 Conflict on Re-Sort Attempt
# Validates: Requirement 11.6
# =============================================================================


class TestResortConflict:
    """Verify that attempting to sort an already-sorted submission returns 409."""

    def test_409_on_second_sort_to_negative(self, client, admin_headers):
        """Sorting the same submission twice returns 409 Conflict.

        Validates: Requirement 11.6
        """
        submission_id = _create_neutral_submission(client)

        # First sort succeeds
        sort_resp = client.patch(
            f"/api/admin/queue/{submission_id}/sort",
            json={"target_sentiment": "negative", "issue_category": "pricing"},
            headers=admin_headers,
        )
        assert sort_resp.status_code == 200

        # Second sort attempt returns 409
        sort_resp = client.patch(
            f"/api/admin/queue/{submission_id}/sort",
            json={"target_sentiment": "negative", "issue_category": "billing"},
            headers=admin_headers,
        )
        assert sort_resp.status_code == 409
        assert "already sorted" in sort_resp.json()["detail"].lower()

    def test_409_on_second_sort_to_positive(self, client, admin_headers):
        """Sorting a submission that was already sorted to positive returns 409.

        Validates: Requirement 11.6
        """
        submission_id = _create_neutral_submission(client)

        # First sort succeeds
        sort_resp = client.patch(
            f"/api/admin/queue/{submission_id}/sort",
            json={"target_sentiment": "positive"},
            headers=admin_headers,
        )
        assert sort_resp.status_code == 200

        # Second sort attempt returns 409
        sort_resp = client.patch(
            f"/api/admin/queue/{submission_id}/sort",
            json={"target_sentiment": "positive"},
            headers=admin_headers,
        )
        assert sort_resp.status_code == 409
        assert "already sorted" in sort_resp.json()["detail"].lower()

    def test_409_on_cross_sort_attempt(self, client, admin_headers):
        """Sorting to positive after already sorting to negative returns 409.

        Validates: Requirement 11.6
        """
        submission_id = _create_neutral_submission(client)

        # Sort to negative first
        sort_resp = client.patch(
            f"/api/admin/queue/{submission_id}/sort",
            json={"target_sentiment": "negative", "issue_category": "outage"},
            headers=admin_headers,
        )
        assert sort_resp.status_code == 200

        # Attempt to sort to positive returns 409
        sort_resp = client.patch(
            f"/api/admin/queue/{submission_id}/sort",
            json={"target_sentiment": "positive"},
            headers=admin_headers,
        )
        assert sort_resp.status_code == 409

    def test_409_on_non_neutral_submission(self, client, admin_headers):
        """Attempting to sort a submission that was never neutral returns 404 or 409.

        Validates: Requirement 11.6
        """
        # Create a negative submission directly (not neutral)
        payload = {
            "customer_name": "Negative User",
            "email": "neg@example.com",
            "core_request": "I have a billing issue",
            "sentiment": "negative",
            "issue_category": "billing",
            "detailed_description": "I was overcharged on my last bill for services not received.",
        }
        response = client.post("/api/submissions", json=payload)
        assert response.status_code == 201
        submission_id = response.json()["submission_id"]

        # Attempt to sort returns 409 (not in queue)
        sort_resp = client.patch(
            f"/api/admin/queue/{submission_id}/sort",
            json={"target_sentiment": "positive"},
            headers=admin_headers,
        )
        assert sort_resp.status_code == 409
