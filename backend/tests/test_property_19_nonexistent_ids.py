"""Property 19: Non-existent submission IDs return 404.

For any submission identifier that does not exist in the Submission_Store or is not
a valid UUID, GET requests SHALL return 404 Not Found.

Feature: sentiment-routed-frontend, Property 19: Non-existent submission IDs return 404
**Validates: Requirements 11.3, 14.5**
"""

import os
import tempfile

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

import uuid

from fastapi.testclient import TestClient
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.database import init_db
from app.main import app

# Initialize DB once at module load
init_db()

_client = TestClient(app)


# --- Strategies ---

# Random valid UUIDs (overwhelmingly unlikely to exist in an empty DB)
random_uuids = st.uuids().map(str)

# Random non-UUID strings: alphanumeric and special characters
non_uuid_alphanumeric = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=50,
).filter(lambda s: len(s.strip()) >= 1)

non_uuid_special_chars = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        # Exclude characters with special URL semantics
        blacklist_characters="/?#&=%",
    ),
    min_size=1,
    max_size=50,
).filter(lambda s: len(s.strip()) >= 1 and "/" not in s and "?" not in s and "#" not in s)


# --- Property Tests ---


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(submission_id=random_uuids)
def test_random_uuid_not_in_db_returns_404(submission_id: str):
    """Property 19 (Class 1): Random valid UUIDs that don't exist in DB return 404.

    Feature: sentiment-routed-frontend, Property 19: Non-existent submission IDs return 404
    **Validates: Requirements 11.3, 14.5**
    """
    response = _client.get(f"/api/submissions/{submission_id}/status")
    assert response.status_code == 404, (
        f"Expected 404 for non-existent UUID '{submission_id}', got {response.status_code}"
    )
    assert response.json()["detail"] == "Submission not found"


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(invalid_id=non_uuid_alphanumeric)
def test_non_uuid_alphanumeric_returns_404(invalid_id: str):
    """Property 19 (Class 2): Random non-UUID alphanumeric strings return 404.

    Feature: sentiment-routed-frontend, Property 19: Non-existent submission IDs return 404
    **Validates: Requirements 11.3, 14.5**
    """
    # Skip if it happens to be a valid UUID (extremely unlikely but be safe)
    try:
        uuid.UUID(invalid_id)
        return  # Skip valid UUIDs — tested in Class 1
    except ValueError:
        pass

    response = _client.get(f"/api/submissions/{invalid_id}/status")
    assert response.status_code == 404, (
        f"Expected 404 for non-UUID string '{invalid_id[:30]}...', got {response.status_code}"
    )
    assert response.json()["detail"] == "Submission not found"


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(invalid_id=non_uuid_special_chars)
def test_non_uuid_special_chars_returns_404(invalid_id: str):
    """Property 19 (Class 3): Non-UUID strings with special characters return 404.

    Feature: sentiment-routed-frontend, Property 19: Non-existent submission IDs return 404
    **Validates: Requirements 11.3, 14.5**
    """
    # Skip if it happens to be a valid UUID
    try:
        uuid.UUID(invalid_id)
        return
    except ValueError:
        pass

    response = _client.get(f"/api/submissions/{invalid_id}/status")
    assert response.status_code == 404, (
        f"Expected 404 for special char string '{invalid_id[:30]}...', got {response.status_code}"
    )
    assert response.json()["detail"] == "Submission not found"


def test_empty_string_returns_404():
    """Property 19 (Edge case 1): Empty string submission ID returns 404.

    Feature: sentiment-routed-frontend, Property 19: Non-existent submission IDs return 404
    **Validates: Requirements 11.3, 14.5**
    """
    # Empty path segment — FastAPI may return 404 or redirect depending on routing
    response = _client.get("/api/submissions//status")
    # FastAPI returns 404 for unmatched routes
    assert response.status_code == 404


def test_very_long_string_returns_404():
    """Property 19 (Edge case 2): Very long string submission ID returns 404.

    Feature: sentiment-routed-frontend, Property 19: Non-existent submission IDs return 404
    **Validates: Requirements 11.3, 14.5**
    """
    long_id = "a" * 1000
    response = _client.get(f"/api/submissions/{long_id}/status")
    assert response.status_code == 404, (
        f"Expected 404 for very long string, got {response.status_code}"
    )
    assert response.json()["detail"] == "Submission not found"
