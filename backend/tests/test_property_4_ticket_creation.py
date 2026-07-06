"""Property 4: Negative submission always creates high-priority ticket.

**Validates: Requirements 3.4, 16.1**

For any valid negative submission, a Ticket SHALL be created with priority "high",
status "open", a unique UUID, the selected Issue_Category, and a link to the
submission identifier.
"""

import os
import tempfile
import uuid as uuid_mod

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


@settings(max_examples=100)
@given(
    submission_data=negative_submission_strategy,
    category=issue_category_strategy,
    description=descriptions,
)
def test_negative_submission_creates_high_priority_ticket(
    submission_data: SubmissionCreate, category: str, description: str
):
    """Property 4: Negative submission always creates high-priority ticket.

    Feature: sentiment-routed-frontend, Property 4
    **Validates: Requirements 3.4, 16.1**
    """
    store = SubmissionStore()
    pipeline = TicketingPipeline()

    # Create the negative submission
    submission = store.create(submission_data)

    # Create a ticket via the TicketingPipeline using the generated category and description
    ticket = pipeline.create_ticket(
        submission_id=str(submission.id),
        category=category,
        description=description,
    )

    # Assert: ticket.priority == "high"
    assert ticket.priority == "high", (
        f"Expected priority 'high', got '{ticket.priority}'"
    )

    # Assert: ticket.status == "open"
    assert ticket.status == "open", (
        f"Expected status 'open', got '{ticket.status}'"
    )

    # Assert: ticket.id is a valid UUID
    assert isinstance(ticket.id, uuid_mod.UUID), (
        f"Expected ticket.id to be a UUID, got {type(ticket.id)}"
    )
    # Verify it's a valid UUID by re-parsing
    uuid_mod.UUID(str(ticket.id))

    # Assert: ticket.issue_category matches the input category
    assert ticket.issue_category == category, (
        f"Expected issue_category '{category}', got '{ticket.issue_category}'"
    )

    # Assert: ticket.submission_id matches the submission.id
    assert ticket.submission_id == submission.id, (
        f"Expected submission_id '{submission.id}', got '{ticket.submission_id}'"
    )
