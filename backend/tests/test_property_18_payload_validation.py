"""Property 18: API payload validation returns 422.

For any request payload that fails Pydantic v2 validation (missing required fields,
type errors, constraint violations), the API_Server SHALL return 422 Unprocessable
Entity with field-level error details.

Feature: sentiment-routed-frontend, Property 18: API payload validation returns 422
**Validates: Requirements 11.7**
"""

import os
import tempfile

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from starlette.testclient import TestClient

from app.database import init_db, get_connection
from app.main import app

# Initialize DB
init_db()


@pytest.fixture(autouse=True)
def fresh_db():
    """Initialize a fresh database before each test."""
    init_db()
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM state_transitions")
        conn.execute("DELETE FROM submissions")
        conn.commit()


_client = TestClient(app)


# --- Strategies for generating invalid payloads ---

# Valid building blocks for constructing partially-invalid payloads
_valid_sentiments = ["negative", "positive", "neutral"]

_valid_customer_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
    min_size=1,
    max_size=50,
).filter(lambda s: len(s.strip()) >= 1)

_valid_core_requests = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
    min_size=1,
    max_size=100,
).filter(lambda s: len(s.strip()) >= 1)

# Invalid sentiment values: strings that are NOT one of the three valid values
_invalid_sentiments = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=20,
).filter(lambda s: s not in _valid_sentiments)

# Short descriptions (< 10 chars) for negative submissions
_short_descriptions = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=9,
)

# Whitespace-only comments for neutral submissions
_whitespace_only = st.from_regex(r"[\s\t\n]+", fullmatch=True).filter(lambda s: len(s) >= 1)

_valid_issue_categories = st.sampled_from([
    "billing", "network_speed", "outage",
    "support_experience", "device_hardware", "pricing",
])


@settings(max_examples=50)
@given(core_request=_valid_core_requests)
def test_missing_customer_name_returns_422(core_request: str):
    """Payload missing customer_name (required field) returns 422.

    **Validates: Requirements 11.7**
    """
    payload = {
        "core_request": core_request,
        "sentiment": "neutral",
        "comment_text": "Some valid comment text here",
    }
    # customer_name is missing entirely
    response = _client.post("/api/submissions", json=payload)
    assert response.status_code == 422, (
        f"Expected 422 for missing customer_name, got {response.status_code}"
    )


@settings(max_examples=50)
@given(core_request=_valid_core_requests)
def test_empty_customer_name_returns_422(core_request: str):
    """Payload with empty string customer_name returns 422.

    **Validates: Requirements 11.7**
    """
    payload = {
        "customer_name": "",
        "core_request": core_request,
        "sentiment": "neutral",
        "comment_text": "Some valid comment text here",
    }
    response = _client.post("/api/submissions", json=payload)
    assert response.status_code == 422, (
        f"Expected 422 for empty customer_name, got {response.status_code}"
    )


@settings(max_examples=50)
@given(customer_name=_valid_customer_names)
def test_missing_core_request_returns_422(customer_name: str):
    """Payload missing core_request (required field) returns 422.

    **Validates: Requirements 11.7**
    """
    payload = {
        "customer_name": customer_name,
        "sentiment": "neutral",
        "comment_text": "Some valid comment text here",
    }
    # core_request is missing entirely
    response = _client.post("/api/submissions", json=payload)
    assert response.status_code == 422, (
        f"Expected 422 for missing core_request, got {response.status_code}"
    )


@settings(max_examples=50)
@given(
    customer_name=_valid_customer_names,
    core_request=_valid_core_requests,
    invalid_sentiment=_invalid_sentiments,
)
def test_invalid_sentiment_value_returns_422(
    customer_name: str, core_request: str, invalid_sentiment: str
):
    """Payload with invalid sentiment value (not negative/positive/neutral) returns 422.

    **Validates: Requirements 11.7**
    """
    payload = {
        "customer_name": customer_name,
        "core_request": core_request,
        "sentiment": invalid_sentiment,
    }
    response = _client.post("/api/submissions", json=payload)
    assert response.status_code == 422, (
        f"Expected 422 for invalid sentiment '{invalid_sentiment}', got {response.status_code}"
    )


@settings(max_examples=50)
@given(
    customer_name=_valid_customer_names,
    core_request=_valid_core_requests,
    description=_short_descriptions,
)
def test_negative_without_issue_category_returns_422(
    customer_name: str, core_request: str, description: str
):
    """Negative submission without issue_category returns 422.

    **Validates: Requirements 11.7**
    """
    payload = {
        "customer_name": customer_name,
        "core_request": core_request,
        "sentiment": "negative",
        "detailed_description": "This is a sufficiently long description for validation",
        # issue_category is intentionally missing
    }
    response = _client.post("/api/submissions", json=payload)
    assert response.status_code == 422, (
        f"Expected 422 for negative submission without issue_category, got {response.status_code}"
    )


@settings(max_examples=50)
@given(
    customer_name=_valid_customer_names,
    core_request=_valid_core_requests,
    short_desc=_short_descriptions,
    category=_valid_issue_categories,
)
def test_negative_with_short_description_returns_422(
    customer_name: str, core_request: str, short_desc: str, category: str
):
    """Negative submission with description < 10 chars returns 422.

    **Validates: Requirements 11.7**
    """
    assume(len(short_desc) < 10)
    payload = {
        "customer_name": customer_name,
        "core_request": core_request,
        "sentiment": "negative",
        "issue_category": category,
        "detailed_description": short_desc,
    }
    response = _client.post("/api/submissions", json=payload)
    assert response.status_code == 422, (
        f"Expected 422 for short description '{short_desc}' (len={len(short_desc)}), "
        f"got {response.status_code}"
    )


@settings(max_examples=50)
@given(
    customer_name=_valid_customer_names,
    core_request=_valid_core_requests,
    whitespace_comment=_whitespace_only,
)
def test_neutral_with_whitespace_only_comment_returns_422(
    customer_name: str, core_request: str, whitespace_comment: str
):
    """Neutral submission with whitespace-only comment returns 422.

    **Validates: Requirements 11.7**
    """
    assume(whitespace_comment.strip() == "")
    payload = {
        "customer_name": customer_name,
        "core_request": core_request,
        "sentiment": "neutral",
        "comment_text": whitespace_comment,
    }
    response = _client.post("/api/submissions", json=payload)
    assert response.status_code == 422, (
        f"Expected 422 for whitespace-only comment '{whitespace_comment!r}', "
        f"got {response.status_code}"
    )
