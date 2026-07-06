"""Property 29: Ticket state drives submission progress.

**Validates: Requirements 16.3, 16.4**

For any Ticket transitioning to "in_progress", the linked Submission Progress_State
SHALL become 75%. For any Ticket transitioning to "resolved", the linked Submission
Progress_State SHALL become 100%.
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
from app.services.ticketing_pipeline import TicketingPipeline


@pytest.fixture(autouse=True)
def fresh_db():
    """Initialize a fresh database before each test."""
    init_db()
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM tickets")
        conn.execute("DELETE FROM state_transitions")
        conn.execute("DELETE FROM submissions")
        conn.commit()


# --- Strategies ---

ISSUE_CATEGORIES = [
    "billing",
    "network_speed",
    "outage",
    "support_experience",
    "device_hardware",
    "pricing",
]

issue_category_strategy = st.sampled_from(ISSUE_CATEGORIES)

customer_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=100,
).filter(lambda s: len(s.strip()) >= 1)

emails = st.from_regex(r"[a-z][a-z0-9]{0,10}@[a-z]{2,6}\.[a-z]{2,4}", fullmatch=True)

descriptions = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=10,
    max_size=200,
).filter(lambda s: len(s.strip()) >= 10)

core_requests = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=200,
).filter(lambda s: len(s.strip()) >= 1)


negative_submission_strategy = st.builds(
    SubmissionCreate,
    customer_name=customer_names,
    email=emails,
    phone=st.none(),
    core_request=core_requests,
    sentiment=st.just("negative"),
    issue_category=issue_category_strategy,
    detailed_description=descriptions,
    praise_text=st.none(),
    social_sharing=st.just(False),
    comment_text=st.none(),
)


@settings(max_examples=50)
@given(
    submission_data=negative_submission_strategy,
    category=issue_category_strategy,
    description=descriptions,
)
def test_ticket_in_progress_sets_submission_progress_to_75(
    submission_data: SubmissionCreate, category: str, description: str
):
    """Property 29: Advancing ticket to in_progress sets submission progress to 75%.

    Feature: sentiment-routed-frontend, Property 29
    **Validates: Requirements 16.3, 16.4**
    """
    store = SubmissionStore()
    pipeline = TicketingPipeline()

    # 1. Create a negative submission (starts at 50%)
    submission = store.create(submission_data)
    assert submission.progress_state == 50

    # 2. Create a ticket linked to this submission
    ticket = pipeline.create_ticket(
        submission_id=str(submission.id),
        category=category,
        description=description,
    )
    assert ticket.status == "open"

    # 3. Advance ticket to "in_progress" → submission progress should be 75%
    updated_ticket = pipeline.advance_status(str(ticket.id))
    assert updated_ticket.status == "in_progress"

    # Verify the submission's progress_state is now 75%
    refreshed_submission = store.get(submission.id)
    assert refreshed_submission is not None
    assert refreshed_submission.progress_state == 75, (
        f"Expected progress 75% after ticket moves to in_progress, "
        f"got {refreshed_submission.progress_state}%"
    )

    # 4. Advance ticket to "resolved" → submission progress should be 100%
    resolved_ticket = pipeline.advance_status(str(ticket.id))
    assert resolved_ticket.status == "resolved"

    # Verify the submission's progress_state is now 100%
    final_submission = store.get(submission.id)
    assert final_submission is not None
    assert final_submission.progress_state == 100, (
        f"Expected progress 100% after ticket moves to resolved, "
        f"got {final_submission.progress_state}%"
    )
