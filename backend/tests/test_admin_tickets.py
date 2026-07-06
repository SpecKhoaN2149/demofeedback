"""Integration tests for admin ticket endpoints.

Tests:
- GET /api/admin/tickets (list active tickets)
- PATCH /api/admin/tickets/{ticket_id}/advance (advance ticket status)

Validates: Requirements 16.2, 16.5, 16.6
"""

import os
import tempfile

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

import uuid

import pytest

from app.database import get_connection, init_db
from app.main import app
from app.services.auth_service import AuthService
from app.services.submission_store import SubmissionStore
from app.services.ticketing_pipeline import TicketingPipeline
from app.models.submission import SubmissionCreate

# Initialize DB
init_db()

ADMIN_USERNAME = "testadmin"
ADMIN_PASSWORD = "testpass123"


@pytest.fixture(autouse=True)
def setup_db():
    """Reset DB state and seed admin user before each test."""
    with get_connection() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.execute("DELETE FROM tickets")
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


def _create_negative_submission() -> str:
    """Helper to create a negative submission and return its ID."""
    store = SubmissionStore()
    data = SubmissionCreate(
        customer_name="Test User",
        email="test@example.com",
        core_request="My service is broken",
        sentiment="negative",
        issue_category="billing",
        detailed_description="I was charged twice for the same service.",
    )
    submission = store.create(data)
    return str(submission.id)


class TestListTickets:
    """Tests for GET /api/admin/tickets."""

    def test_requires_auth(self, client):
        """Unauthenticated requests return 401."""
        response = client.get("/api/admin/tickets")
        assert response.status_code == 401

    def test_returns_empty_list_when_no_tickets(self, client, admin_token):
        """Returns empty list when no tickets exist."""
        response = client.get(
            "/api/admin/tickets",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_active_tickets(self, client, admin_token):
        """Returns tickets with status open or in_progress."""
        pipeline = TicketingPipeline()
        sub_id = _create_negative_submission()
        ticket = pipeline.create_ticket(sub_id, "billing", "Charged twice")

        response = client.get(
            "/api/admin/tickets",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == str(ticket.id)
        assert data[0]["status"] == "open"
        assert data[0]["issue_category"] == "billing"
        assert data[0]["priority"] == "high"

    def test_excludes_resolved_tickets(self, client, admin_token):
        """Resolved tickets are not included in the active list."""
        pipeline = TicketingPipeline()
        sub_id = _create_negative_submission()
        ticket = pipeline.create_ticket(sub_id, "outage", "Service down")

        # Advance to in_progress then resolved
        pipeline.advance_status(str(ticket.id))
        pipeline.advance_status(str(ticket.id))

        response = client.get(
            "/api/admin/tickets",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_includes_in_progress_tickets(self, client, admin_token):
        """In-progress tickets are included in the active list."""
        pipeline = TicketingPipeline()
        sub_id = _create_negative_submission()
        ticket = pipeline.create_ticket(sub_id, "network_speed", "Slow internet")

        # Advance to in_progress
        pipeline.advance_status(str(ticket.id))

        response = client.get(
            "/api/admin/tickets",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "in_progress"


class TestAdvanceTicket:
    """Tests for PATCH /api/admin/tickets/{ticket_id}/advance."""

    def test_requires_auth(self, client):
        """Unauthenticated requests return 401."""
        response = client.patch(f"/api/admin/tickets/{uuid.uuid4()}/advance")
        assert response.status_code == 401

    def test_advance_open_to_in_progress(self, client, admin_token):
        """Advancing an open ticket moves it to in_progress."""
        pipeline = TicketingPipeline()
        sub_id = _create_negative_submission()
        ticket = pipeline.create_ticket(sub_id, "billing", "Double charge")

        response = client.patch(
            f"/api/admin/tickets/{ticket.id}/advance",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "in_progress"
        assert data["id"] == str(ticket.id)

    def test_advance_in_progress_to_resolved(self, client, admin_token):
        """Advancing an in-progress ticket moves it to resolved."""
        pipeline = TicketingPipeline()
        sub_id = _create_negative_submission()
        ticket = pipeline.create_ticket(sub_id, "outage", "Total outage")

        # First advance to in_progress
        pipeline.advance_status(str(ticket.id))

        response = client.patch(
            f"/api/admin/tickets/{ticket.id}/advance",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "resolved"

    def test_advance_resolved_returns_409(self, client, admin_token):
        """Attempting to advance a resolved ticket returns 409 Conflict."""
        pipeline = TicketingPipeline()
        sub_id = _create_negative_submission()
        ticket = pipeline.create_ticket(sub_id, "billing", "Overcharge")

        # Advance through open → in_progress → resolved
        pipeline.advance_status(str(ticket.id))
        pipeline.advance_status(str(ticket.id))

        response = client.patch(
            f"/api/admin/tickets/{ticket.id}/advance",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 409
        assert "invalid" in response.json()["detail"].lower() or "cannot advance" in response.json()["detail"].lower()

    def test_advance_nonexistent_ticket_returns_409(self, client, admin_token):
        """Advancing a non-existent ticket returns 409."""
        fake_id = str(uuid.uuid4())
        response = client.patch(
            f"/api/admin/tickets/{fake_id}/advance",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 409
        assert "not found" in response.json()["detail"].lower()

    def test_advance_invalid_uuid_returns_409(self, client, admin_token):
        """Advancing with an invalid UUID format returns 409."""
        response = client.patch(
            "/api/admin/tickets/not-a-uuid/advance",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 409
        assert "invalid" in response.json()["detail"].lower()
