"""Property 28: Ticket state machine valid transitions.

**Validates: Requirements 16.2, 16.6**

For any Ticket, the only valid status transitions SHALL be
"open" → "in_progress" and "in_progress" → "resolved".
All other transitions SHALL be rejected with an error.
"""

import os
import tempfile
import uuid as uuid_mod

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.database import init_db, get_connection
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


def _create_submission() -> str:
    """Helper to create a minimal negative submission and return its id."""
    submission_id = str(uuid_mod.uuid4())
    from datetime import datetime, timezone

    created_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO submissions (id, created_at, customer_name, email, core_request,
                                     sentiment, progress_state, issue_category, detailed_description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                submission_id,
                created_at,
                "Test User",
                "test@example.com",
                "Fix my issue",
                "negative",
                50,
                "billing",
                "Something is wrong with my bill",
            ),
        )
        conn.commit()
    return submission_id


def _create_ticket(pipeline: TicketingPipeline, submission_id: str) -> str:
    """Helper to create a ticket and return its id."""
    ticket = pipeline.create_ticket(
        submission_id=submission_id,
        category="billing",
        description="Test ticket for state machine validation",
    )
    return str(ticket.id)


# --- Property tests ---


@settings(max_examples=50)
@given(data=st.data())
def test_open_to_in_progress_always_succeeds(data):
    """Advancing a ticket from 'open' to 'in_progress' always succeeds.

    Feature: sentiment-routed-frontend, Property 28
    **Validates: Requirements 16.2, 16.6**
    """
    pipeline = TicketingPipeline()
    submission_id = _create_submission()
    ticket_id = _create_ticket(pipeline, submission_id)

    # Ticket starts at "open", first advance should go to "in_progress"
    updated = pipeline.advance_status(ticket_id)
    assert updated.status == "in_progress", (
        f"Expected 'in_progress', got '{updated.status}'"
    )


@settings(max_examples=50)
@given(data=st.data())
def test_in_progress_to_resolved_always_succeeds(data):
    """Advancing a ticket from 'in_progress' to 'resolved' always succeeds.

    Feature: sentiment-routed-frontend, Property 28
    **Validates: Requirements 16.2, 16.6**
    """
    pipeline = TicketingPipeline()
    submission_id = _create_submission()
    ticket_id = _create_ticket(pipeline, submission_id)

    # Advance open → in_progress
    pipeline.advance_status(ticket_id)
    # Advance in_progress → resolved
    updated = pipeline.advance_status(ticket_id)
    assert updated.status == "resolved", (
        f"Expected 'resolved', got '{updated.status}'"
    )


@settings(max_examples=50)
@given(data=st.data())
def test_resolved_cannot_advance(data):
    """Advancing a 'resolved' ticket always raises ValueError.

    Feature: sentiment-routed-frontend, Property 28
    **Validates: Requirements 16.2, 16.6**
    """
    pipeline = TicketingPipeline()
    submission_id = _create_submission()
    ticket_id = _create_ticket(pipeline, submission_id)

    # Advance through: open → in_progress → resolved
    pipeline.advance_status(ticket_id)
    pipeline.advance_status(ticket_id)

    # Attempting to advance from "resolved" must raise ValueError
    with pytest.raises(ValueError, match="cannot advance from 'resolved'"):
        pipeline.advance_status(ticket_id)


# Valid statuses for the state machine
ALL_STATUSES = ["open", "in_progress", "resolved"]

# Strategy to generate random sequences of advance attempts (1 to 5 attempts)
advance_sequence_strategy = st.integers(min_value=1, max_value=5)


@settings(max_examples=50)
@given(num_advances=advance_sequence_strategy)
def test_state_machine_enforced_across_random_sequences(num_advances: int):
    """Random sequences of advance attempts always respect the state machine.

    For any number of advance attempts on a ticket, the state machine
    must enforce: open → in_progress → resolved, rejecting any
    advance beyond "resolved".

    Feature: sentiment-routed-frontend, Property 28
    **Validates: Requirements 16.2, 16.6**
    """
    pipeline = TicketingPipeline()
    submission_id = _create_submission()
    ticket_id = _create_ticket(pipeline, submission_id)

    expected_states = ["in_progress", "resolved"]
    current_index = 0  # next expected state index

    for i in range(num_advances):
        if current_index < len(expected_states):
            # Valid transition should succeed
            updated = pipeline.advance_status(ticket_id)
            assert updated.status == expected_states[current_index], (
                f"Advance {i+1}: expected '{expected_states[current_index]}', "
                f"got '{updated.status}'"
            )
            current_index += 1
        else:
            # Invalid transition (already resolved) should raise ValueError
            with pytest.raises(ValueError, match="cannot advance from 'resolved'"):
                pipeline.advance_status(ticket_id)
