"""Unit tests for auth middleware dependency (require_admin).

Validates: Requirements 9.1, 9.5
- 401 when no token is provided
- 401 when token is expired or invalidated
- 401 when token is unknown
- Returns AdminUser when token is valid
"""

import os
import sys
import tempfile

import pytest

# Add backend directory to path so 'app' package resolves correctly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# Set up temp database before importing app modules
_tf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["SUBMISSIONS_DB_PATH"] = _tf.name
_tf.close()

from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.database import get_connection, init_db
from app.middleware.auth import require_admin
from app.models.auth import AdminUser
from app.services.auth_service import AuthService

# Create a minimal FastAPI app for testing the dependency
_test_app = FastAPI()


@_test_app.get("/protected")
async def protected_route(admin: AdminUser = Depends(require_admin)):
    """Test endpoint that requires admin authentication."""
    return {"username": admin.username, "token": admin.token}


client = TestClient(_test_app)


@pytest.fixture(autouse=True)
def fresh_db():
    """Reinitialize database for each test."""
    init_db()
    with get_connection() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.commit()
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.commit()


@pytest.fixture
def auth_service():
    return AuthService()


@pytest.fixture
def valid_token(auth_service):
    """Create an admin user and return a valid session token."""
    auth_service.create_admin("testadmin", "testpass")
    session = auth_service.login("testadmin", "testpass")
    return session.token


class TestRequireAdminNoToken:
    """Tests for missing token — Requirement 9.1."""

    def test_no_auth_header_no_cookie_returns_401(self):
        """Request with no token at all should get 401."""
        response = client.get("/protected")
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_empty_bearer_returns_401(self):
        """Authorization: Bearer (empty) should get 401."""
        response = client.get("/protected", headers={"Authorization": "Bearer "})
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_malformed_auth_header_returns_401(self):
        """Non-Bearer auth header should get 401."""
        response = client.get("/protected", headers={"Authorization": "Basic abc123"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"


class TestRequireAdminInvalidToken:
    """Tests for invalid/expired/invalidated tokens — Requirement 9.5."""

    def test_unknown_token_returns_401(self):
        """Completely fake token should get 401."""
        response = client.get(
            "/protected",
            headers={"Authorization": "Bearer totally_fake_token_123"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_expired_token_returns_401(self, valid_token):
        """Expired token should get 401."""
        # Manually expire the token in the database
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with get_connection() as conn:
            conn.execute(
                "UPDATE sessions SET expires_at = ? WHERE token = ?",
                (past, valid_token),
            )
            conn.commit()

        response = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_invalidated_token_returns_401(self, auth_service, valid_token):
        """Logged-out (invalidated) token should get 401."""
        auth_service.logout(valid_token)

        response = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"


class TestRequireAdminValidToken:
    """Tests for valid token — successful authentication."""

    def test_valid_bearer_token_returns_admin_user(self, valid_token):
        """Valid Bearer token should allow access and return admin info."""
        response = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testadmin"
        assert data["token"] == valid_token

    def test_valid_cookie_token_returns_admin_user(self, valid_token):
        """Valid session_token cookie should allow access."""
        response = client.get(
            "/protected",
            cookies={"session_token": valid_token},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testadmin"
        assert data["token"] == valid_token

    def test_bearer_takes_precedence_over_cookie(self, auth_service, valid_token):
        """Bearer header should be used even if cookie is also present."""
        # Create a second admin with a different token
        auth_service.create_admin("admin2", "pass2")
        session2 = auth_service.login("admin2", "pass2")

        # Send Bearer with token1 and cookie with token2
        response = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {valid_token}"},
            cookies={"session_token": session2.token},
        )
        assert response.status_code == 200
        # Should use the Bearer token (testadmin)
        assert response.json()["username"] == "testadmin"
