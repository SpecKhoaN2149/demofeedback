"""Property 1: Sentiment determines initial progress state.

For any valid submission, the initial Progress_State SHALL be determined solely
by the sentiment route: negative → 50%, positive → 100%, neutral → 25%.

Feature: sentiment-routed-frontend, Property 1: Sentiment determines initial progress state
**Validates: Requirements 3.3, 4.2, 5.2**
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


# Expected mapping from sentiment to initial progress state
EXPECTED_PROGRESS = {
    "negative": 50,
    "positive": 100,
    "neutral": 25,
}


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
    email = draw(emails)
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
        phone=None,
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
def test_sentiment_determines_initial_progress_state(data: SubmissionCreate):
    """Property 1: For any valid submission, the initial progress_state is determined
    solely by the sentiment route: negative → 50, positive → 100, neutral → 25.

    Feature: sentiment-routed-frontend, Property 1: Sentiment determines initial progress state
    **Validates: Requirements 3.3, 4.2, 5.2**
    """
    store = SubmissionStore()

    submission = store.create(data)

    expected = EXPECTED_PROGRESS[data.sentiment]
    assert submission.progress_state == expected, (
        f"Sentiment '{data.sentiment}' should yield progress_state={expected}, "
        f"but got {submission.progress_state}"
    )
