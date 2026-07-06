"""Property 23: Submission persistence round-trip.

For any valid SubmissionCreate payload, creating a submission and then retrieving
it by ID SHALL return a record where all persisted fields match the original payload.

Feature: sentiment-routed-frontend, Property 23: Submission persistence round-trip
**Validates: Requirements 14.1, 14.4**
"""

import os
import tempfile

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.database import init_db, get_connection
from app.models.submission import SubmissionCreate
from app.services.submission_store import SubmissionStore


@pytest.fixture(autouse=True)
def fresh_db():
    """Initialize a fresh database before each test."""
    init_db()
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM state_transitions")
        conn.execute("DELETE FROM submissions")
        conn.commit()


# --- Strategies for generating valid submission payloads ---

customer_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=100,
).filter(lambda s: len(s.strip()) >= 1)

emails = st.from_regex(r"[a-z][a-z0-9]{0,10}@[a-z]{2,6}\.[a-z]{2,4}", fullmatch=True)

phones = st.from_regex(r"\+1[0-9]{10}", fullmatch=True)

core_requests = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=200,
).filter(lambda s: len(s.strip()) >= 1)

sentiments = st.sampled_from(["negative", "positive", "neutral"])

issue_categories = st.sampled_from(
    ["billing", "network_speed", "outage", "support_experience", "device_hardware", "pricing"]
)

descriptions = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=10,
    max_size=200,
).filter(lambda s: len(s.strip()) >= 10)

praise_texts = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=200,
).filter(lambda s: len(s.strip()) >= 1)

comment_texts = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=200,
).filter(lambda s: len(s.strip()) >= 1)


@st.composite
def submission_strategy(draw):
    """Generate a valid SubmissionCreate with random sentiment and appropriate fields."""
    sentiment = draw(sentiments)
    name = draw(customer_names)
    email = draw(st.one_of(st.none(), emails))
    phone = draw(st.one_of(st.none(), phones))
    request = draw(core_requests)

    # Build sentiment-specific fields
    issue_category = None
    detailed_description = None
    praise_text = None
    social_sharing = False
    comment_text = None

    if sentiment == "negative":
        issue_category = draw(issue_categories)
        detailed_description = draw(descriptions)
    elif sentiment == "positive":
        praise_text = draw(praise_texts)
        social_sharing = draw(st.booleans())
    else:  # neutral
        comment_text = draw(comment_texts)

    return SubmissionCreate(
        customer_name=name,
        email=email,
        phone=phone,
        core_request=request,
        sentiment=sentiment,
        issue_category=issue_category,
        detailed_description=detailed_description,
        praise_text=praise_text,
        social_sharing=social_sharing,
        comment_text=comment_text,
    )


@settings(max_examples=100)
@given(data=submission_strategy())
def test_submission_persistence_round_trip(data: SubmissionCreate):
    """Property 23: For any valid SubmissionCreate payload, creating a submission
    and then retrieving it by ID returns a record where all persisted fields match
    the original payload.

    Feature: sentiment-routed-frontend, Property 23: Submission persistence round-trip
    **Validates: Requirements 14.1, 14.4**
    """
    store = SubmissionStore()

    # Step 1: Create the submission
    created = store.create(data)

    # Step 2: Retrieve by ID
    retrieved = store.get(created.id)

    # Step 3: Assert retrieval succeeded
    assert retrieved is not None, f"Submission {created.id} not found after creation"

    # Step 4: Assert all persisted fields match the original payload
    assert retrieved.customer_name == data.customer_name, (
        f"customer_name mismatch: expected {data.customer_name!r}, got {retrieved.customer_name!r}"
    )
    assert retrieved.email == data.email, (
        f"email mismatch: expected {data.email!r}, got {retrieved.email!r}"
    )
    assert retrieved.phone == data.phone, (
        f"phone mismatch: expected {data.phone!r}, got {retrieved.phone!r}"
    )
    assert retrieved.core_request == data.core_request, (
        f"core_request mismatch: expected {data.core_request!r}, got {retrieved.core_request!r}"
    )
    assert retrieved.sentiment == data.sentiment, (
        f"sentiment mismatch: expected {data.sentiment!r}, got {retrieved.sentiment!r}"
    )
    # progress_state is derived from sentiment, so verify it matches the expected mapping
    expected_progress = {"negative": 50, "positive": 100, "neutral": 25}[data.sentiment]
    assert retrieved.progress_state == expected_progress, (
        f"progress_state mismatch: expected {expected_progress}, got {retrieved.progress_state}"
    )
    assert retrieved.issue_category == data.issue_category, (
        f"issue_category mismatch: expected {data.issue_category!r}, got {retrieved.issue_category!r}"
    )
    assert retrieved.detailed_description == data.detailed_description, (
        f"detailed_description mismatch: expected {data.detailed_description!r}, "
        f"got {retrieved.detailed_description!r}"
    )
    assert retrieved.praise_text == data.praise_text, (
        f"praise_text mismatch: expected {data.praise_text!r}, got {retrieved.praise_text!r}"
    )
    assert retrieved.social_sharing == data.social_sharing, (
        f"social_sharing mismatch: expected {data.social_sharing!r}, got {retrieved.social_sharing!r}"
    )
    assert retrieved.comment_text == data.comment_text, (
        f"comment_text mismatch: expected {data.comment_text!r}, got {retrieved.comment_text!r}"
    )
