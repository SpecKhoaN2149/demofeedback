"""Unit tests for AuthService.

Validates Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# Add backend directory to path so 'app' package resolves correctly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# Set up temp database before importing app modules
_tf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["SUBMISSIONS_DB_PATH"] = _tf.name
_tf.close()

from app.database import init_db
from app.models.auth import AdminUser, SessionToken
from app.services.auth_service import AuthService


@pytest.fixture(autouse=True)
def fresh_db():
    """Reinitialize database for each test."""
    init_db()
    # Clear tables before each test
    from app.database import get_connection

    with get_connection() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.commit()
    yield
    # Cleanup after test
    with get_connection() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.commit()


@pytest.fixture
def auth():
    return AuthService()


@pytest.fixture
def seeded_admin(auth):
    """Create a test admin user."""
    auth.create_admin("admin", "secret123")
    return "admin", "secret123"


class TestLogin:
    """Tests for login() — Requirements 9.2, 9.3."""

    def test_login_valid_credentials_returns_session_token(self, auth, seeded_admin):
        username, password = seeded_admin
        result = auth.login(username, password)
        assert result is not None
        assert isinstance(result, SessionToken)
        assert result.username == username
        assert result.token is not None
        assert len(result.token) > 0

    def test_login_valid_credentials_token_expires_within_8_hours(self, auth, seeded_admin):
        """Validates: Requirement 9.2 — token expiry no longer than 8 hours."""
        username, password = seeded_admin
        before = datetime.now(timezone.utc)
        result = auth.login(username, password)
        max_expiry = before + timedelta(hours=8, seconds=5)  # small tolerance
        assert result.expires_at <= max_expiry

    def test_login_wrong_password_returns_none(self, auth, seeded_admin):
        """Validates: Requirement 9.3 — invalid credentials return failure."""
        username, _ = seeded_admin
        result = auth.login(username, "wrongpassword")
        assert result is None

    def test_login_nonexistent_user_returns_none(self, auth):
        """Validates: Requirement 9.3 — same failure for nonexistent user."""
        result = auth.login("nosuchuser", "anypassword")
        assert result is None

    def test_login_while_locked_returns_none(self, auth, seeded_admin):
        """Validates: Requirement 9.6 — locked account rejects correct creds."""
        username, password = seeded_admin
        # Trigger lockout
        for _ in range(5):
            auth.login(username, "wrong")
        # Even correct password is rejected
        result = auth.login(username, password)
        assert result is None


class TestLogout:
    """Tests for logout() — Requirement 9.4."""

    def test_logout_invalidates_session(self, auth, seeded_admin):
        username, password = seeded_admin
        token = auth.login(username, password)
        auth.logout(token.token)
        user = auth.validate_token(token.token)
        assert user is None

    def test_logout_nonexistent_token_no_error(self, auth):
        """Logout with unknown token should not raise."""
        auth.logout("nonexistent_token_value")


class TestValidateToken:
    """Tests for validate_token() — Requirements 9.1, 9.5."""

    def test_valid_token_returns_admin_user(self, auth, seeded_admin):
        username, password = seeded_admin
        token = auth.login(username, password)
        user = auth.validate_token(token.token)
        assert user is not None
        assert isinstance(user, AdminUser)
        assert user.username == username
        assert user.token == token.token

    def test_invalidated_token_returns_none(self, auth, seeded_admin):
        """Validates: Requirement 9.5 — invalidated tokens are rejected."""
        username, password = seeded_admin
        token = auth.login(username, password)
        auth.logout(token.token)
        assert auth.validate_token(token.token) is None

    def test_expired_token_returns_none(self, auth, seeded_admin):
        """Validates: Requirement 9.5 — expired tokens are rejected."""
        username, password = seeded_admin
        token = auth.login(username, password)
        # Manually expire the token
        from app.database import get_connection

        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with get_connection() as conn:
            conn.execute(
                "UPDATE sessions SET expires_at = ? WHERE token = ?",
                (past, token.token),
            )
            conn.commit()
        assert auth.validate_token(token.token) is None

    def test_unknown_token_returns_none(self, auth):
        """Validates: Requirement 9.1 — missing token means unauthenticated."""
        assert auth.validate_token("totally_fake_token") is None


class TestLockout:
    """Tests for is_locked(), record_failure(), clear_failures() — Requirement 9.6."""

    def test_account_not_locked_initially(self, auth, seeded_admin):
        username, _ = seeded_admin
        assert auth.is_locked(username) is False

    def test_account_locked_after_5_failures(self, auth, seeded_admin):
        """Validates: Requirement 9.6 — 5 consecutive failures triggers lockout."""
        username, _ = seeded_admin
        for _ in range(5):
            auth.record_failure(username)
        assert auth.is_locked(username) is True

    def test_account_not_locked_after_4_failures(self, auth, seeded_admin):
        username, _ = seeded_admin
        for _ in range(4):
            auth.record_failure(username)
        assert auth.is_locked(username) is False

    def test_clear_failures_unlocks_account(self, auth, seeded_admin):
        username, _ = seeded_admin
        for _ in range(5):
            auth.record_failure(username)
        assert auth.is_locked(username) is True
        auth.clear_failures(username)
        assert auth.is_locked(username) is False

    def test_successful_login_clears_failures(self, auth, seeded_admin):
        username, password = seeded_admin
        # Record 4 failures (not enough to lock)
        for _ in range(4):
            auth.record_failure(username)
        # Successful login clears them
        result = auth.login(username, password)
        assert result is not None
        # Now 5 more failures needed to lock
        for _ in range(4):
            auth.record_failure(username)
        assert auth.is_locked(username) is False

    def test_is_locked_nonexistent_user_returns_false(self, auth):
        assert auth.is_locked("nosuchuser") is False


class TestCreateAdmin:
    """Tests for create_admin() helper."""

    def test_create_admin_allows_login(self, auth):
        auth.create_admin("newadmin", "newpass")
        result = auth.login("newadmin", "newpass")
        assert result is not None
        assert result.username == "newadmin"

    def test_create_admin_replace_existing(self, auth):
        """create_admin with existing username updates the password."""
        auth.create_admin("admin", "oldpass")
        auth.create_admin("admin", "newpass")
        assert auth.login("admin", "oldpass") is None
        assert auth.login("admin", "newpass") is not None
