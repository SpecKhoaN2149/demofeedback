"""Integration tests for GET /api/submissions/{submission_id} (admin-only).

Tests the full HTTP request/response cycle for retrieving a full submission record.

Validates: Requirements 14.4
"""

import os
import tempfile

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

import uuid

import pytest

from app.database import init_db
from app.main import app
from app.models.submission import SubmissionCreate
from app.services.auth_service import AuthService
from app.services.submission_store import SubmissionStore

# Initialize DB
init_db()

ADMIN_USERNAME = "testadmin"
ADMIN_PASSWORD = "testpass123"


@pytest.fixture(autouse=True)
def setup_db():
    """Reset DB state and seed admin user before each test."""
    from app.database import get_connection

    with get_connection() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.execute("DELETE FROM state_transitions")
        conn.execute("DELETE FROM submissions")
        conn.commit()

    auth = AuthService()
    auth.create_admin(ADMIN_USERNAME, ADMIN_PASSWORD)
    yield


@pytest.fixture
def client():
    """Provide a synchronous test client."""
    from starlette.testclient import TestClient

    return TestClient(app)


@pytest.fixture
def admin_token():
    """Create admin and return a valid session token."""
    auth = AuthService()
    session = auth.login(ADMIN_USERNAME, ADMIN_PASSWORD)
    return session.token


@pytest.fixture
def sample_submission():
    """Create a sample submission and return it."""
    store = SubmissionStore()
    data = SubmissionCreate(
        customer_name="Alice Test",
        email="alice@example.com",
        phone="555-0100",
        core_request="My internet is slow",
        sentiment="negative",
        issue_category="network_speed",
        detailed_description="It has been slow since yesterday morning.",
    )
    return store.create(data)


class TestGetSubmissionAdmin:
    """Tests for GET /api/submissions/{submission_id}."""

    def test_returns_full_submission_for_admin(self, client, admin_token, sample_submission):
        """Admin can retrieve a full submission record."""
        response = client.get(
            f"/api/submissions/{sample_submission.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(sample_submission.id)
        assert data["customer_name"] == "Alice Test"
        assert data["email"] == "alice@example.com"
        assert data["sentiment"] == "negative"
        assert data["progress_state"] == 50
        assert data["issue_category"] == "network_speed"
        assert data["enrichment_status"] == "pending"
        assert "state_transitions" in data
        assert len(data["state_transitions"]) >= 1

    def test_returns_404_for_nonexistent_submission(self, client, admin_token):
        """Returns 404 when submission does not exist."""
        fake_id = str(uuid.uuid4())
        response = client.get(
            f"/api/submissions/{fake_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Submission not found"

    def test_returns_404_for_invalid_uuid(self, client, admin_token):
        """Returns 404 for malformed UUID."""
        response = client.get(
            "/api/submissions/not-a-valid-uuid",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Submission not found"

    def test_returns_401_without_auth(self, client, sample_submission):
        """Returns 401 when no auth token is provided."""
        response = client.get(
            f"/api/submissions/{sample_submission.id}",
        )

        assert response.status_code == 401

    def test_returns_401_with_invalid_token(self, client, sample_submission):
        """Returns 401 for invalid/expired token."""
        response = client.get(
            f"/api/submissions/{sample_submission.id}",
            headers={"Authorization": "Bearer invalid-token-123"},
        )

        assert response.status_code == 401

    def test_includes_enrichment_result_when_present(self, client, admin_token):
        """Returns enrichment_result when enrichment has completed."""
        from app.models.submission import EnrichmentResult

        store = SubmissionStore()
        data = SubmissionCreate(
            customer_name="Bob",
            email="bob@example.com",
            core_request="Great service!",
            sentiment="positive",
            praise_text="Everything works perfectly.",
        )
        submission = store.create(data)

        # Add enrichment result
        enrichment = EnrichmentResult(
            themes=[{"name": "praise", "confidence": 0.95}],
            sentiment_confidence=0.92,
            severity_score=1,
            severity_factors=[],
            language_code="en",
            language_confidence=0.99,
        )
        store.update_enrichment(submission.id, enrichment)

        response = client.get(
            f"/api/submissions/{submission.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        result = response.json()
        assert result["enrichment_status"] == "completed"
        assert result["enrichment_result"] is not None
        assert result["enrichment_result"]["sentiment_confidence"] == 0.92
