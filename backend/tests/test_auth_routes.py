"""Integration tests for auth endpoints (POST /api/auth/login, POST /api/auth/logout).

Tests the full HTTP request/response cycle using httpx TestClient against
the FastAPI app.

Validates: Requirements 9.2, 9.3, 9.4
"""

import os
import tempfile

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

from datetime import datetime, timezone, timedelta

import pytest

from app.database import init_db
from app.main import app
from app.services.auth_service import AuthService

# Initialize DB
init_db()

# Test credentials
ADMIN_USERNAME = "testadmin"
ADMIN_PASSWORD = "testpass123"


@pytest.fixture(autouse=True)
def setup_db():
    """Reset DB state and seed admin user before each test."""
    from app.database import get_connection

    with get_connection() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.commit()

    auth = AuthService()
    auth.create_admin(ADMIN_USERNAME, ADMIN_PASSWORD)
    yield


@pytest.fixture
def client():
    """Provide a synchronous test client."""
    from starlette.testclient import TestClient

    return TestClient(app)


class TestLogin:
    """Tests for POST /api/auth/login."""

    def test_successful_login_returns_session_token(self, client):
        """Valid credentials return 200 with token, expires_at, and username."""
        response = client.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )

        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["username"] == ADMIN_USERNAME
        assert "expires_at" in data

    def test_successful_login_sets_cookie(self, client):
        """Successful login sets session_token cookie for browser clients."""
        response = client.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )

        assert response.status_code == 200
        assert "session_token" in response.cookies

    def test_successful_login_token_expires_within_8_hours(self, client):
        """Session token expires within 8 hours from issuance (Req 9.2)."""
        before = datetime.now(timezone.utc)
        response = client.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )

        assert response.status_code == 200
        data = response.json()
        expires_at = datetime.fromisoformat(data["expires_at"])
        # Ensure timezone-aware comparison
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        max_expiry = before + timedelta(hours=8, seconds=5)  # small buffer
        assert expires_at <= max_expiry

    def test_wrong_password_returns_401(self, client):
        """Wrong password returns 401 with generic message (Req 9.3)."""
        response = client.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": "wrong_password"},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication failed"

    def test_wrong_username_returns_401(self, client):
        """Wrong username returns 401 with same generic message (Req 9.3)."""
        response = client.post(
            "/api/auth/login",
            json={"username": "nonexistent_user", "password": ADMIN_PASSWORD},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication failed"

    def test_wrong_both_returns_401(self, client):
        """Both credentials wrong returns same 401 message (Req 9.3)."""
        response = client.post(
            "/api/auth/login",
            json={"username": "nonexistent", "password": "wrongpass"},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication failed"

    def test_locked_account_returns_401(self, client):
        """Locked account returns same 401 message (Req 9.6, no info leak)."""
        # Exhaust failed attempts to trigger lockout
        for _ in range(5):
            client.post(
                "/api/auth/login",
                json={"username": ADMIN_USERNAME, "password": "wrong"},
            )

        # Even with correct password, locked account returns 401
        response = client.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication failed"

    def test_missing_fields_returns_422(self, client):
        """Missing required fields returns 422."""
        response = client.post("/api/auth/login", json={"username": ADMIN_USERNAME})

        assert response.status_code == 422


class TestLogout:
    """Tests for POST /api/auth/logout."""

    def test_successful_logout(self, client):
        """Authenticated logout returns 200 and invalidates token (Req 9.4)."""
        # Login first
        login_resp = client.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        token = login_resp.json()["token"]

        # Logout
        response = client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json()["detail"] == "Logged out successfully"

    def test_token_invalid_after_logout(self, client):
        """After logout, the token can no longer be used (Req 9.4, 9.5)."""
        # Login
        login_resp = client.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        token = login_resp.json()["token"]

        # Logout
        client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Try to use the invalidated token
        response = client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 401

    def test_logout_without_token_returns_401(self, client):
        """Logout without authentication returns 401."""
        response = client.post("/api/auth/logout")

        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_logout_with_invalid_token_returns_401(self, client):
        """Logout with a bogus token returns 401."""
        response = client.post(
            "/api/auth/logout",
            headers={"Authorization": "Bearer totally_invalid_token"},
        )

        assert response.status_code == 401
