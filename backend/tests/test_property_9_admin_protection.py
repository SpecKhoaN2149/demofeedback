"""Property 9: Admin endpoints require valid authentication.

For any request to an admin-only endpoint, if the request lacks a session token
or presents an expired or invalidated token, the API_Server SHALL return 401
Unauthorized without executing the operation.

**Validates: Requirements 9.1, 9.5**
"""

import os
import tempfile

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.database import get_connection, init_db
from app.middleware.auth import require_admin
from app.models.auth import AdminUser
from app.services.auth_service import AuthService

# Initialize DB once at module load
init_db()

# Create a minimal FastAPI test app with a protected endpoint
_test_app = FastAPI()


@_test_app.get("/admin/protected")
async def protected_endpoint(admin: AdminUser = Depends(require_admin)):
    """A test endpoint protected by require_admin dependency."""
    return {"username": admin.username, "status": "ok"}


_client = TestClient(_test_app)


def _reset_db():
    """Clear auth-related tables between test runs."""
    with get_connection() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.commit()


# --- Strategies ---

# Random token strings that won't exist in the DB (ASCII-only for HTTP header compatibility)
random_tokens = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        max_codepoint=127,
    ),
    min_size=1,
    max_size=64,
).filter(lambda s: len(s.strip()) >= 1)

# Usernames for admin user creation
usernames = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=3,
    max_size=20,
).filter(lambda s: s.strip() == s and len(s) >= 3)

# Passwords for admin user creation
passwords = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=4,
    max_size=30,
).filter(lambda s: len(s) >= 4)


# --- Property Tests ---


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.data())
def test_no_token_returns_401(data):
    """Property 9 (Class 1): Requests without any token get 401.

    Feature: sentiment-routed-frontend, Property 9: Admin endpoints require valid authentication
    **Validates: Requirements 9.1, 9.5**
    """
    _reset_db()

    # No Authorization header, no cookie — must get 401
    response = _client.get("/admin/protected")
    assert response.status_code == 401, (
        f"Expected 401 for request with no token, got {response.status_code}"
    )
    assert response.json()["detail"] == "Authentication required"


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(token=random_tokens)
def test_random_string_token_returns_401(token: str):
    """Property 9 (Class 2): Random string tokens not in DB get 401.

    Feature: sentiment-routed-frontend, Property 9: Admin endpoints require valid authentication
    **Validates: Requirements 9.1, 9.5**
    """
    _reset_db()

    # Use a random token that doesn't correspond to any session in DB
    response = _client.get(
        "/admin/protected",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401, (
        f"Expected 401 for random token '{token[:20]}...', got {response.status_code}"
    )
    assert response.json()["detail"] == "Authentication required"


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(username=usernames, password=passwords)
def test_expired_token_returns_401(username: str, password: str):
    """Property 9 (Class 3): Expired tokens (valid format but expired in DB) get 401.

    Feature: sentiment-routed-frontend, Property 9: Admin endpoints require valid authentication
    **Validates: Requirements 9.1, 9.5**
    """
    _reset_db()

    auth = AuthService()

    # Create admin and get a valid token
    auth.create_admin(username, password)
    session = auth.login(username, password)
    assert session is not None, "Login should succeed with correct credentials"

    token = session.token

    # Manually expire the token by setting expires_at in the past
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE token = ?",
            (past, token),
        )
        conn.commit()

    # Request with expired token should get 401
    response = _client.get(
        "/admin/protected",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401, (
        f"Expected 401 for expired token, got {response.status_code}"
    )
    assert response.json()["detail"] == "Authentication required"


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(username=usernames, password=passwords)
def test_invalidated_token_returns_401(username: str, password: str):
    """Property 9 (Class 3b): Invalidated (logged-out) tokens get 401.

    Feature: sentiment-routed-frontend, Property 9: Admin endpoints require valid authentication
    **Validates: Requirements 9.1, 9.5**
    """
    _reset_db()

    auth = AuthService()

    # Create admin and get a valid token
    auth.create_admin(username, password)
    session = auth.login(username, password)
    assert session is not None, "Login should succeed with correct credentials"

    token = session.token

    # Invalidate the token (simulate logout)
    auth.logout(token)

    # Request with invalidated token should get 401
    response = _client.get(
        "/admin/protected",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401, (
        f"Expected 401 for invalidated token, got {response.status_code}"
    )
    assert response.json()["detail"] == "Authentication required"


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(username=usernames, password=passwords)
def test_valid_token_returns_200(username: str, password: str):
    """Property 9 (Positive case): Valid tokens DO get 200.

    Feature: sentiment-routed-frontend, Property 9: Admin endpoints require valid authentication
    **Validates: Requirements 9.1, 9.5**
    """
    _reset_db()

    auth = AuthService()

    # Create admin and get a valid token
    auth.create_admin(username, password)
    session = auth.login(username, password)
    assert session is not None, "Login should succeed with correct credentials"

    token = session.token

    # Request with valid token should succeed
    response = _client.get(
        "/admin/protected",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, (
        f"Expected 200 for valid token, got {response.status_code}"
    )
    data = response.json()
    assert data["username"] == username
    assert data["status"] == "ok"
