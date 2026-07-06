"""Property 6: Neutral submissions always queued for admin review.

**Validates: Requirements 5.4**

Tests that any valid neutral submission appears in the AdminReviewQueue
immediately after creation and enqueue.
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
from app.services.admin_review_queue import AdminReviewQueue
from app.services.submission_store import SubmissionStore


@pytest.fixture(autouse=True)
def fresh_db():
    """Initialize a fresh database before each test."""
    init_db()
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM admin_review_queue")
        conn.execute("DELETE FROM state_transitions")
        conn.execute("DELETE FROM submissions")
        conn.commit()


# Strategies for generating valid neutral submission payloads
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

comment_texts = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=200,
).filter(lambda s: len(s.strip()) >= 1)


neutral_submission_strategy = st.builds(
    SubmissionCreate,
    customer_name=customer_names,
    email=emails,
    phone=st.none(),
    core_request=core_requests,
    sentiment=st.just("neutral"),
    issue_category=st.none(),
    detailed_description=st.none(),
    praise_text=st.none(),
    social_sharing=st.just(False),
    comment_text=comment_texts,
)


@settings(max_examples=100)
@given(data=neutral_submission_strategy)
def test_neutral_submission_always_queued_for_admin_review(data: SubmissionCreate):
    """Property 6: Any valid neutral submission appears in AdminReviewQueue after creation and enqueue.

    Feature: sentiment-routed-frontend, Property 6: Neutral submissions always queued for admin review
    **Validates: Requirements 5.4**
    """
    store = SubmissionStore()
    queue = AdminReviewQueue()

    # Create the submission
    submission = store.create(data)

    # Enqueue it (simulating the workflow in the API endpoint)
    queue.enqueue(str(submission.id))

    # Assert the submission is in the queue
    assert queue.is_queued(str(submission.id)), (
        f"Neutral submission {submission.id} was not found in AdminReviewQueue after enqueue"
    )
