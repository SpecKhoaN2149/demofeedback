"""Backend integration tests for full submission flows.

Tests the complete lifecycle of submissions through the API:
- Negative flow: POST submission → ticket created → advance ticket → progress updates
- Positive flow: POST submission → marketing logged → progress 100%
- Neutral flow: POST submission → queued → admin sort → progress updated
- NLP enrichment: submission → background task → enrichment stored

Uses pytest + httpx TestClient against the FastAPI app.

Validates: Requirements 3.3, 3.4, 4.2, 4.3, 5.2, 5.4, 10.3, 10.4, 13.6
"""

import os
import tempfile

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from app.database import get_connection, init_db
from app.main import app
from app.models.submission import EnrichmentResult
from app.services.auth_service import AuthService
from app.services.submission_store import SubmissionStore

# Initialize DB
init_db()

ADMIN_USERNAME = "integration_admin"
ADMIN_PASSWORD = "securepass456"


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
def admin_token():
    """Return a valid admin session token."""
    auth = AuthService()
    session = auth.login(ADMIN_USERNAME, ADMIN_PASSWORD)
    return session.token


@pytest.fixture
def admin_headers(admin_token):
    """Return Authorization headers for admin requests."""
    return {"Authorization": f"Bearer {admin_token}"}


# =============================================================================
# Negative Flow: POST submission → ticket created → advance → progress updates
# Validates: Requirements 3.3, 3.4
# =============================================================================


class TestNegativeFlow:
    """Integration tests for the full negative submission lifecycle."""

    def test_negative_submission_creates_ticket_and_tracks_progress(
        self, client, admin_headers
    ):
        """Full negative flow: submit → ticket created → advance to in_progress → advance to resolved.

        Validates:
        - Req 3.3: Negative submission created with progress_state 50%
        - Req 3.4: Ticket created in TicketingPipeline with high priority
        """
        # Step 1: POST a negative submission
        payload = {
            "customer_name": "Alice Negative",
            "email": "alice@example.com",
            "core_request": "My internet is extremely slow and unreliable",
            "sentiment": "negative",
            "issue_category": "network_speed",
            "detailed_description": "I've been experiencing download speeds of less than 1 Mbps for the past week.",
        }
        response = client.post("/api/submissions", json=payload)
        assert response.status_code == 201
        data = response.json()
        submission_id = data["submission_id"]
        assert data["progress_state"] == 50

        # Step 2: Verify status shows 50% with appropriate message
        status_resp = client.get(f"/api/submissions/{submission_id}/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["progress_state"] == 50
        assert status_data["sentiment"] == "negative"
        assert status_data["message"] == "Spectrum is working on this."

        # Step 3: Verify ticket was created (admin endpoint)
        tickets_resp = client.get("/api/admin/tickets", headers=admin_headers)
        assert tickets_resp.status_code == 200
        tickets = tickets_resp.json()
        assert len(tickets) >= 1

        # Find the ticket linked to our submission
        ticket = next(
            (t for t in tickets if t["submission_id"] == submission_id), None
        )
        assert ticket is not None
        assert ticket["status"] == "open"
        assert ticket["priority"] == "high"
        assert ticket["issue_category"] == "network_speed"

        # Step 4: Advance ticket to in_progress → progress should become 75%
        advance_resp = client.patch(
            f"/api/admin/tickets/{ticket['id']}/advance",
            headers=admin_headers,
        )
        assert advance_resp.status_code == 200
        assert advance_resp.json()["status"] == "in_progress"

        # Verify progress updated to 75%
        status_resp = client.get(f"/api/submissions/{submission_id}/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["progress_state"] == 75
        assert status_resp.json()["message"] == "Almost there — resolution in progress."

        # Step 5: Advance ticket to resolved → progress should become 100%
        advance_resp = client.patch(
            f"/api/admin/tickets/{ticket['id']}/advance",
            headers=admin_headers,
        )
        assert advance_resp.status_code == 200
        assert advance_resp.json()["status"] == "resolved"

        # Verify progress updated to 100%
        status_resp = client.get(f"/api/submissions/{submission_id}/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["progress_state"] == 100

    def test_negative_submission_with_all_categories(self, client):
        """Negative submissions accept all valid issue categories."""
        categories = [
            "billing",
            "network_speed",
            "outage",
            "support_experience",
            "device_hardware",
            "pricing",
        ]
        for category in categories:
            payload = {
                "customer_name": f"User {category}",
                "email": f"{category}@test.com",
                "core_request": f"Issue with {category}",
                "sentiment": "negative",
                "issue_category": category,
                "detailed_description": f"Detailed problem related to {category} area of service.",
            }
            response = client.post("/api/submissions", json=payload)
            assert response.status_code == 201, f"Failed for category: {category}"
            assert response.json()["progress_state"] == 50


# =============================================================================
# Positive Flow: POST submission → marketing logged → progress 100%
# Validates: Requirements 4.2, 4.3
# =============================================================================


class TestPositiveFlow:
    """Integration tests for the full positive submission lifecycle."""

    def test_positive_submission_logs_marketing_and_completes(
        self, client, admin_headers
    ):
        """Full positive flow: submit → marketing logged → progress at 100%.

        Validates:
        - Req 4.2: Positive submission created with progress_state 100%
        - Req 4.3: Submission logged in MarketingEngine
        """
        # Step 1: POST a positive submission
        payload = {
            "customer_name": "Bob Positive",
            "email": "bob@example.com",
            "core_request": "I love Spectrum's service!",
            "sentiment": "positive",
            "praise_text": "Amazing customer support, resolved my issue in 5 minutes!",
            "social_sharing": False,
        }
        response = client.post("/api/submissions", json=payload)
        assert response.status_code == 201
        data = response.json()
        submission_id = data["submission_id"]
        assert data["progress_state"] == 100

        # Step 2: Verify status shows 100% immediately
        status_resp = client.get(f"/api/submissions/{submission_id}/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["progress_state"] == 100
        assert status_data["sentiment"] == "positive"
        assert status_data["message"] == "Praise received & noted!"

        # Step 3: Verify marketing log entry was created (admin endpoint)
        marketing_resp = client.get("/api/admin/marketing", headers=admin_headers)
        assert marketing_resp.status_code == 200
        marketing_data = marketing_resp.json()
        items = marketing_data["items"]
        assert len(items) >= 1

        # Find our entry
        entry = next(
            (e for e in items if e["submission_id"] == submission_id), None
        )
        assert entry is not None
        assert entry["customer_name"] == "Bob Positive"
        assert entry["praise_text"] == "Amazing customer support, resolved my issue in 5 minutes!"
        assert entry["social_status"] == "internal_only"

    def test_positive_submission_with_social_sharing(self, client, admin_headers):
        """Positive submission with social sharing generates shareable URL.

        Validates:
        - Req 4.3: Marketing engine logs with social_sharing=True
        """
        payload = {
            "customer_name": "Charlie Share",
            "email": "charlie@example.com",
            "core_request": "Great experience with Spectrum",
            "sentiment": "positive",
            "praise_text": "Spectrum's fiber internet is incredibly fast and reliable!",
            "social_sharing": True,
        }
        response = client.post("/api/submissions", json=payload)
        assert response.status_code == 201
        submission_id = response.json()["submission_id"]

        # Verify marketing log includes social sharing status
        marketing_resp = client.get("/api/admin/marketing", headers=admin_headers)
        assert marketing_resp.status_code == 200
        items = marketing_resp.json()["items"]
        entry = next(
            (e for e in items if e["submission_id"] == submission_id), None
        )
        assert entry is not None
        assert entry["social_sharing"] is True
        # social_status should be "shared" (URL generated)
        assert entry["social_status"] == "shared"
        assert entry["shareable_url"] is not None


# =============================================================================
# Neutral Flow: POST submission → queued → admin sort → progress updated
# Validates: Requirements 5.2, 5.4, 10.3, 10.4
# =============================================================================


class TestNeutralFlow:
    """Integration tests for the full neutral submission lifecycle."""

    def test_neutral_submission_queued_then_sorted_to_negative(
        self, client, admin_headers
    ):
        """Neutral flow with sort-to-negative: submit → queued → sort → ticket + progress 50%.

        Validates:
        - Req 5.2: Neutral submission created with progress_state 25%
        - Req 5.4: Submission placed in AdminReviewQueue
        - Req 10.3: Sort to negative creates ticket, sets progress 50%, removes from queue
        """
        # Step 1: POST a neutral submission
        payload = {
            "customer_name": "Diana Neutral",
            "email": "diana@example.com",
            "core_request": "General feedback about my experience",
            "sentiment": "neutral",
            "comment_text": "The service is okay but could be improved in some areas.",
        }
        response = client.post("/api/submissions", json=payload)
        assert response.status_code == 201
        data = response.json()
        submission_id = data["submission_id"]
        assert data["progress_state"] == 25

        # Step 2: Verify status shows 25% (awaiting review)
        status_resp = client.get(f"/api/submissions/{submission_id}/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["progress_state"] == 25
        assert status_resp.json()["message"] == "Awaiting Review"

        # Step 3: Verify submission is in the admin review queue
        queue_resp = client.get("/api/admin/queue", headers=admin_headers)
        assert queue_resp.status_code == 200
        queue_items = queue_resp.json()["items"]
        queued_ids = [item["submission_id"] for item in queue_items]
        assert submission_id in queued_ids

        # Step 4: Admin sorts to negative with issue_category
        sort_resp = client.patch(
            f"/api/admin/queue/{submission_id}/sort",
            json={"target_sentiment": "negative", "issue_category": "billing"},
            headers=admin_headers,
        )
        assert sort_resp.status_code == 200
        sort_data = sort_resp.json()
        assert sort_data["target_sentiment"] == "negative"
        assert sort_data["progress_state"] == 50

        # Step 5: Verify submission no longer in queue
        queue_resp = client.get("/api/admin/queue", headers=admin_headers)
        queued_ids = [item["submission_id"] for item in queue_resp.json()["items"]]
        assert submission_id not in queued_ids

        # Step 6: Verify progress updated to 50%
        status_resp = client.get(f"/api/submissions/{submission_id}/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["progress_state"] == 50
        assert status_resp.json()["message"] == "Spectrum is working on this."

        # Step 7: Verify a ticket was created for this submission
        tickets_resp = client.get("/api/admin/tickets", headers=admin_headers)
        tickets = tickets_resp.json()
        ticket = next(
            (t for t in tickets if t["submission_id"] == submission_id), None
        )
        assert ticket is not None
        assert ticket["issue_category"] == "billing"
        assert ticket["priority"] == "high"
        assert ticket["status"] == "open"

    def test_neutral_submission_queued_then_sorted_to_positive(
        self, client, admin_headers
    ):
        """Neutral flow with sort-to-positive: submit → queued → sort → marketing + progress 100%.

        Validates:
        - Req 5.4: Submission placed in AdminReviewQueue
        - Req 10.4: Sort to positive logs marketing, sets progress 100%, removes from queue
        """
        # Step 1: POST a neutral submission
        payload = {
            "customer_name": "Eve Neutral",
            "phone": "+15551234567",
            "core_request": "Wanted to share some feedback",
            "sentiment": "neutral",
            "comment_text": "Your staff was very helpful and friendly when I visited the store.",
        }
        response = client.post("/api/submissions", json=payload)
        assert response.status_code == 201
        submission_id = response.json()["submission_id"]
        assert response.json()["progress_state"] == 25

        # Step 2: Verify in queue
        queue_resp = client.get("/api/admin/queue", headers=admin_headers)
        queued_ids = [item["submission_id"] for item in queue_resp.json()["items"]]
        assert submission_id in queued_ids

        # Step 3: Admin sorts to positive
        sort_resp = client.patch(
            f"/api/admin/queue/{submission_id}/sort",
            json={"target_sentiment": "positive"},
            headers=admin_headers,
        )
        assert sort_resp.status_code == 200
        assert sort_resp.json()["progress_state"] == 100

        # Step 4: Verify removed from queue
        queue_resp = client.get("/api/admin/queue", headers=admin_headers)
        queued_ids = [item["submission_id"] for item in queue_resp.json()["items"]]
        assert submission_id not in queued_ids

        # Step 5: Verify progress at 100%
        status_resp = client.get(f"/api/submissions/{submission_id}/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["progress_state"] == 100

        # Step 6: Verify marketing log entry was created
        marketing_resp = client.get("/api/admin/marketing", headers=admin_headers)
        items = marketing_resp.json()["items"]
        entry = next(
            (e for e in items if e["submission_id"] == submission_id), None
        )
        assert entry is not None
        assert entry["customer_name"] == "Eve Neutral"


# =============================================================================
# NLP Enrichment: submission → background task → enrichment stored
# Validates: Requirement 13.6
# =============================================================================


class TestNLPEnrichment:
    """Integration tests for NLP enrichment background task flow."""

    def test_enrichment_stored_after_background_task(self, client, admin_headers):
        """NLP enrichment is stored on the submission after background processing.

        Validates:
        - Req 13.6: Enrichment result stored on submission after async processing
        """
        # We mock the NLP processing to return a successful enrichment result
        # since the real NLP processor requires a Gemini API key
        mock_enrichment = EnrichmentResult(
            themes=[
                {"theme": "network_speed", "confidence": 0.92},
                {"theme": "outage", "confidence": 0.65},
            ],
            sentiment_confidence=0.85,
            severity_score=4,
            severity_factors=["service_disruption", "repeated_issue"],
            language_code="en",
            language_confidence=0.99,
        )

        # Patch the enrichment service to simulate NLP completing
        with patch(
            "app.routes.submissions._run_nlp_enrichment", new_callable=AsyncMock
        ) as mock_enrich:
            # Make the background task a no-op (we'll manually set enrichment)
            mock_enrich.return_value = None

            payload = {
                "customer_name": "Frank NLP",
                "email": "frank@example.com",
                "core_request": "My internet keeps dropping every few hours",
                "sentiment": "negative",
                "issue_category": "outage",
                "detailed_description": "The connection drops completely about 3-4 times per day.",
            }
            response = client.post("/api/submissions", json=payload)
            assert response.status_code == 201
            submission_id = response.json()["submission_id"]

        # Simulate enrichment being stored (as the background task would do)
        store = SubmissionStore()
        store.update_enrichment(uuid.UUID(submission_id), mock_enrichment)

        # Verify enrichment is accessible via the status endpoint
        status_resp = client.get(f"/api/submissions/{submission_id}/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["enrichment_status"] == "completed"

        # Verify full submission record has enrichment data (admin endpoint)
        sub_resp = client.get(
            f"/api/submissions/{submission_id}", headers=admin_headers
        )
        assert sub_resp.status_code == 200
        sub_data = sub_resp.json()
        assert sub_data["enrichment_status"] == "completed"
        assert sub_data["enrichment_result"] is not None
        assert len(sub_data["enrichment_result"]["themes"]) == 2
        assert sub_data["enrichment_result"]["severity_score"] == 4
        assert sub_data["enrichment_result"]["sentiment_confidence"] == 0.85
        assert sub_data["enrichment_result"]["language_code"] == "en"

    def test_enrichment_pending_when_background_task_not_completed(self, client):
        """Submission enrichment_status starts as 'pending' before background task completes.

        Validates that submission is created successfully and enrichment runs asynchronously.
        """
        with patch(
            "app.routes.submissions._run_nlp_enrichment", new_callable=AsyncMock
        ) as mock_enrich:
            mock_enrich.return_value = None

            payload = {
                "customer_name": "Grace Pending",
                "email": "grace@example.com",
                "core_request": "Just a quick question about my bill",
                "sentiment": "positive",
                "praise_text": "Your billing team was very helpful when I called.",
            }
            response = client.post("/api/submissions", json=payload)
            assert response.status_code == 201
            submission_id = response.json()["submission_id"]

        # Enrichment status should be 'pending' since background task was mocked
        status_resp = client.get(f"/api/submissions/{submission_id}/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["enrichment_status"] == "pending"

    def test_enrichment_failure_marked_on_submission(self, client, admin_headers):
        """When NLP enrichment fails, submission is marked with failed status.

        Validates graceful degradation: submission remains valid even if enrichment fails.
        """
        with patch(
            "app.routes.submissions._run_nlp_enrichment", new_callable=AsyncMock
        ) as mock_enrich:
            mock_enrich.return_value = None

            payload = {
                "customer_name": "Henry Failure",
                "email": "henry@example.com",
                "core_request": "General comment about service quality",
                "sentiment": "neutral",
                "comment_text": "Service is acceptable but nothing special to report.",
            }
            response = client.post("/api/submissions", json=payload)
            assert response.status_code == 201
            submission_id = response.json()["submission_id"]

        # Simulate enrichment failure
        store = SubmissionStore()
        store.mark_enrichment_failed(
            uuid.UUID(submission_id), "NLP processing produced no insight records"
        )

        # Verify failure status
        status_resp = client.get(f"/api/submissions/{submission_id}/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["enrichment_status"] == "failed"

        # Submission itself is still valid and accessible
        sub_resp = client.get(
            f"/api/submissions/{submission_id}", headers=admin_headers
        )
        assert sub_resp.status_code == 200
        assert sub_resp.json()["enrichment_status"] == "failed"
        assert sub_resp.json()["enrichment_result"] is None
