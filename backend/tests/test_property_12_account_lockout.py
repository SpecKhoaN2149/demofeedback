"""Property 12: Account lockout after 5 consecutive failures.

For any username that accumulates 5 consecutive failed login attempts,
the API_Server SHALL reject all further login attempts for that username
for at least 60 seconds, including attempts with correct credentials.

**Validates: Requirements 9.6**
"""

import os
import tempfile

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.database import init_db, get_connection
from app.services.auth_service import AuthService


# Initialize DB once at module load
init_db()


def _reset_db():
    """Clear auth-related tables between test runs."""
    with get_connection() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.commit()


# Strategies for generating random usernames and passwords
usernames = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=3,
    max_size=20,
).filter(lambda s: s.strip() == s and len(s) >= 3)

passwords = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=4,
    max_size=30,
).filter(lambda s: len(s) >= 4)

wrong_passwords = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=4,
    max_size=30,
).filter(lambda s: len(s) >= 4)

# Strategy for fewer than 5 failures (to test NOT locked)
fewer_than_5 = st.integers(min_value=0, max_value=4)


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    username=usernames,
    correct_password=passwords,
    wrong_password=wrong_passwords,
)
def test_account_locked_after_5_consecutive_failures(
    username: str,
    correct_password: str,
    wrong_password: str,
):
    """Property 12: After 5 consecutive failed login attempts, login is rejected even with correct credentials.

    Feature: sentiment-routed-frontend, Property 12: Account lockout after 5 consecutive failures
    **Validates: Requirements 9.6**
    """
    # Ensure wrong_password differs from correct_password
    if wrong_password == correct_password:
        wrong_password = correct_password + "WRONG"

    _reset_db()

    auth = AuthService()

    # Create admin user with the correct password
    auth.create_admin(username, correct_password)

    # Record 5 consecutive failed login attempts with wrong password
    for i in range(5):
        result = auth.login(username, wrong_password)
        assert result is None, f"Login should fail on attempt {i + 1} with wrong password"

    # Assert account is now locked
    assert auth.is_locked(username) is True, (
        f"Account '{username}' should be locked after 5 consecutive failures"
    )

    # Assert login with CORRECT password also fails (account is locked)
    result = auth.login(username, correct_password)
    assert result is None, (
        f"Login with correct credentials should be rejected while account '{username}' is locked"
    )


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    username=usernames,
    correct_password=passwords,
    wrong_password=wrong_passwords,
    num_failures=fewer_than_5,
)
def test_account_not_locked_with_fewer_than_5_failures(
    username: str,
    correct_password: str,
    wrong_password: str,
    num_failures: int,
):
    """Property 12 (inverse): With fewer than 5 consecutive failures, account is NOT locked.

    Feature: sentiment-routed-frontend, Property 12: Account lockout after 5 consecutive failures
    **Validates: Requirements 9.6**
    """
    if wrong_password == correct_password:
        wrong_password = correct_password + "WRONG"

    _reset_db()

    auth = AuthService()

    # Create admin user
    auth.create_admin(username, correct_password)

    # Record fewer than 5 failed attempts
    for i in range(num_failures):
        result = auth.login(username, wrong_password)
        assert result is None, f"Login should fail on attempt {i + 1} with wrong password"

    # Assert account is NOT locked
    assert auth.is_locked(username) is False, (
        f"Account '{username}' should NOT be locked after only {num_failures} failures"
    )

    # Assert login with correct password succeeds
    result = auth.login(username, correct_password)
    assert result is not None, (
        f"Login with correct credentials should succeed after only {num_failures} failures"
    )
