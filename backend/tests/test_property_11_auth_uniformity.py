"""Property 11: Authentication error uniformity.

For any failed login attempt (wrong username, wrong password, or both),
the API_Server SHALL return the same 401 error response without revealing
which credential was incorrect.

**Validates: Requirements 9.3**
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

# Seeded admin account credentials
ADMIN_USERNAME = "spectrum_admin"
ADMIN_PASSWORD = "correct_password_123"


def _reset_db():
    """Clear auth-related tables and re-seed admin account between test runs."""
    with get_connection() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM admin_users")
        conn.commit()

    auth = AuthService()
    auth.create_admin(ADMIN_USERNAME, ADMIN_PASSWORD)


# Strategies for generating random credentials
random_usernames = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=3,
    max_size=20,
).filter(lambda s: s.strip() == s and len(s) >= 3)

random_passwords = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=4,
    max_size=30,
).filter(lambda s: len(s) >= 4)


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(wrong_password=random_passwords)
def test_correct_username_wrong_password_returns_none(wrong_password: str):
    """Scenario 1: Correct username + wrong password → login returns None.

    Feature: sentiment-routed-frontend, Property 11: Authentication error uniformity
    **Validates: Requirements 9.3**
    """
    # Ensure wrong_password differs from the correct password
    if wrong_password == ADMIN_PASSWORD:
        wrong_password = wrong_password + "WRONG"

    _reset_db()

    auth = AuthService()
    result = auth.login(ADMIN_USERNAME, wrong_password)

    # The result must be identically None — no information leakage
    assert result is None, (
        f"Login with correct username '{ADMIN_USERNAME}' and wrong password "
        f"should return None, got {result!r}"
    )


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(wrong_username=random_usernames, any_password=random_passwords)
def test_wrong_username_any_password_returns_none(wrong_username: str, any_password: str):
    """Scenario 2: Wrong username + any password → login returns None.

    Feature: sentiment-routed-frontend, Property 11: Authentication error uniformity
    **Validates: Requirements 9.3**
    """
    # Ensure wrong_username differs from the seeded admin username
    if wrong_username == ADMIN_USERNAME:
        wrong_username = wrong_username + "_fake"

    _reset_db()

    auth = AuthService()
    result = auth.login(wrong_username, any_password)

    # The result must be identically None — no information leakage
    assert result is None, (
        f"Login with wrong username '{wrong_username}' should return None, got {result!r}"
    )


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(wrong_username=random_usernames, wrong_password=random_passwords)
def test_wrong_username_wrong_password_returns_none(wrong_username: str, wrong_password: str):
    """Scenario 3: Wrong username + wrong password → login returns None.

    Feature: sentiment-routed-frontend, Property 11: Authentication error uniformity
    **Validates: Requirements 9.3**
    """
    # Ensure both credentials are wrong
    if wrong_username == ADMIN_USERNAME:
        wrong_username = wrong_username + "_fake"
    if wrong_password == ADMIN_PASSWORD:
        wrong_password = wrong_password + "WRONG"

    _reset_db()

    auth = AuthService()
    result = auth.login(wrong_username, wrong_password)

    # The result must be identically None — no information leakage
    assert result is None, (
        f"Login with wrong username '{wrong_username}' and wrong password "
        f"should return None, got {result!r}"
    )
