"""Tests for GET /api/submissions/{submission_id}/status endpoint.

Validates: Requirements 11.2, 11.3, 14.5
"""

import os
import tempfile
import uuid

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

import pytest
from starlette.testclient import TestClient

from app.database import init_db
from app.main import app
from app.services.submission_store import SubmissionStore
from app.models.submission import SubmissionCreate

# Initialize DB
init_db()


@pytest.fixture
def client():
    """Provide a synchronous test client."""
    return TestClient(app)


@pytest.fixture
def store():
    """Provide a SubmissionStore instance."""
    return SubmissionStore()


@pytest.fixture
def sample_submission(store):
    """Create a sample submission and return its ID."""
    data = SubmissionCreate(
        customer_name="Test User",
        email="test@example.com",
        core_request="I have an issue with my billing",
        sentiment="negative",
        issue_category="billing",
        detailed_description="My bill was double charged last month and I need a refund.",
    )
    submission = store.create(data)
    return str(submission.id)


class TestGetSubmissionStatus:
    """Tests for the status polling endpoint."""

    def test_valid_submission_returns_status(self, client, sample_submission):
        """A valid submission ID returns 200 with status fields."""
        response = client.get(f"/api/submissions/{sample_submission}/status")

        assert response.status_code == 200
        data = response.json()
        assert data["submission_id"] == sample_submission
        assert "progress_state" in data
        assert "sentiment" in data
        assert "message" in data
        assert "enrichment_status" in data

    def test_valid_submission_has_correct_sentiment(self, client, sample_submission):
        """Status response reflects the submission's sentiment."""
        response = client.get(f"/api/submissions/{sample_submission}/status")

        assert response.status_code == 200
        data = response.json()
        assert data["sentiment"] == "negative"

    def test_valid_submission_has_pending_enrichment(self, client, sample_submission):
        """New submission has enrichment_status of 'pending'."""
        response = client.get(f"/api/submissions/{sample_submission}/status")

        assert response.status_code == 200
        data = response.json()
        assert data["enrichment_status"] == "pending"

    def test_nonexistent_uuid_returns_404(self, client):
        """A valid UUID format but nonexistent submission returns 404."""
        fake_id = str(uuid.uuid4())
        response = client.get(f"/api/submissions/{fake_id}/status")

        assert response.status_code == 404
        assert response.json()["detail"] == "Submission not found"

    def test_invalid_uuid_format_returns_404(self, client):
        """An invalid UUID format returns 404."""
        response = client.get("/api/submissions/not-a-valid-uuid/status")

        assert response.status_code == 404
        assert response.json()["detail"] == "Submission not found"

    def test_empty_string_id_returns_404(self, client):
        """An empty-ish submission ID returns 404."""
        response = client.get("/api/submissions/12345/status")

        assert response.status_code == 404
        assert response.json()["detail"] == "Submission not found"

    def test_progress_state_matches_initial(self, client, store):
        """Negative submission starts at progress_state 50."""
        data = SubmissionCreate(
            customer_name="Jane",
            email="jane@example.com",
            core_request="Network is slow",
            sentiment="negative",
            issue_category="network_speed",
            detailed_description="My internet is extremely slow during peak hours every day.",
        )
        submission = store.create(data)

        response = client.get(f"/api/submissions/{submission.id}/status")

        assert response.status_code == 200
        assert response.json()["progress_state"] == 50

    def test_positive_submission_starts_at_100(self, client, store):
        """Positive submission starts at progress_state 100."""
        data = SubmissionCreate(
            customer_name="Bob",
            email="bob@example.com",
            core_request="Great service",
            sentiment="positive",
            praise_text="Your team was amazing, thanks for fixing my issue so quickly!",
        )
        submission = store.create(data)

        response = client.get(f"/api/submissions/{submission.id}/status")

        assert response.status_code == 200
        assert response.json()["progress_state"] == 100
