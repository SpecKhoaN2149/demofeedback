"""Property 10: Session token expires within 8 hours.

**Validates: Requirements 9.2**

For any successfully authenticated login, the issued session token SHALL have
an expiration time no more than 8 hours from the time of issuance.
"""

import os
import tempfile

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

import pytest
from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from app.database import init_db, get_connection
from app.services.auth_service import AuthService


@pytest.fixture(autouse=True)
def fresh_db():
    """Initialize a fresh database before each test."""
    init_db()
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.commit()


# Strategies for generating valid admin credentials
usernames = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=3,
    max_size=20,
).filter(lambda s: s.strip() == s and len(s) >= 3)

passwords = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=4,
    max_size=30,
).filter(lambda s: len(s.strip()) >= 4)


@settings(max_examples=50)
@given(username=usernames, password=passwords)
def test_session_token_expires_within_8_hours(username: str, password: str):
    """Property 10: Session token expires within 8 hours of issuance.

    Feature: sentiment-routed-frontend, Property 10: Session token expires within 8 hours
    **Validates: Requirements 9.2**
    """
    auth = AuthService()

    # Step 1: Create admin user
    auth.create_admin(username, password)

    # Step 2: Record time before login
    before = datetime.now(timezone.utc)

    # Step 3: Login
    token = auth.login(username, password)

    # Assert login succeeded
    assert token is not None, f"Login failed for username={username!r}"

    # Step 4: Assert token expires at most 8 hours + 5 seconds from before (small tolerance)
    max_expiry = before + timedelta(hours=8, seconds=5)
    assert token.expires_at <= max_expiry, (
        f"Token expires_at ({token.expires_at.isoformat()}) exceeds "
        f"8 hours + 5s from login time ({max_expiry.isoformat()})"
    )

    # Step 5: Assert token hasn't already expired (expires_at > before)
    assert token.expires_at > before, (
        f"Token expires_at ({token.expires_at.isoformat()}) is not after "
        f"login time ({before.isoformat()}) — token is already expired"
    )

    # Cleanup for next hypothesis example
    with get_connection() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.commit()
