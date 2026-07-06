"""Property 24: State transition audit trail.

**Validates: Requirements 14.3**

For any Progress_State change on a submission, the Submission_Store SHALL record
a StateTransition entry with the correct previous state, new state, and ISO 8601
UTC timestamp, preserving all prior transitions in chronological order.
"""

import os
import tempfile

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

import pytest
from datetime import datetime, timezone
from hypothesis import given, settings, assume
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


# --- Strategies ---

# Valid progress states for negative submissions: starts at 50, can go to 75, then 100
# We generate sequences of states that represent forward progress
NEGATIVE_PROGRESS_SEQUENCE = st.lists(
    st.sampled_from([75, 100]),
    min_size=1,
    max_size=5,
).map(lambda lst: sorted(set(lst)))  # deduplicate and sort to ensure valid forward progression

customer_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=50,
).filter(lambda s: len(s.strip()) >= 1)

core_requests = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=100,
).filter(lambda s: len(s.strip()) >= 1)

negative_submission_strategy = st.builds(
    SubmissionCreate,
    customer_name=customer_names,
    email=st.just("test@example.com"),
    phone=st.none(),
    core_request=core_requests,
    sentiment=st.just("negative"),
    issue_category=st.just("billing"),
    detailed_description=st.just("A detailed description of the issue."),
    praise_text=st.none(),
    social_sharing=st.just(False),
    comment_text=st.none(),
)


@settings(max_examples=50)
@given(
    submission_data=negative_submission_strategy,
    progress_sequence=NEGATIVE_PROGRESS_SEQUENCE,
)
def test_state_transition_audit_trail(
    submission_data: SubmissionCreate,
    progress_sequence: list[int],
):
    """Property 24: State transition audit trail.

    Feature: sentiment-routed-frontend, Property 24
    **Validates: Requirements 14.3**
    """
    store = SubmissionStore()

    # 1. Create a negative submission (starts at 50)
    submission = store.create(submission_data)
    assert submission.progress_state == 50

    # 2. Call update_progress() for each state in the sequence
    for new_state in progress_sequence:
        store.update_progress(submission.id, new_state)

    # 3. Retrieve submission via get()
    retrieved = store.get(submission.id)
    assert retrieved is not None

    # 4. Assert state_transitions list has length = len(sequence) + 1 (initial + updates)
    expected_transition_count = len(progress_sequence) + 1  # initial (0→50) + updates
    assert len(retrieved.state_transitions) == expected_transition_count, (
        f"Expected {expected_transition_count} transitions, "
        f"got {len(retrieved.state_transitions)}. "
        f"Transitions: {[(t.previous_state, t.new_state) for t in retrieved.state_transitions]}"
    )

    # 5. Assert each transition has correct previous_state and new_state
    # First transition should be 0 → 50 (initial)
    assert retrieved.state_transitions[0].previous_state == 0
    assert retrieved.state_transitions[0].new_state == 50

    # Build expected transition chain: 50 → first_in_sequence → second_in_sequence → ...
    expected_previous = 50
    for i, new_state in enumerate(progress_sequence):
        transition = retrieved.state_transitions[i + 1]
        assert transition.previous_state == expected_previous, (
            f"Transition {i + 1}: expected previous_state={expected_previous}, "
            f"got {transition.previous_state}"
        )
        assert transition.new_state == new_state, (
            f"Transition {i + 1}: expected new_state={new_state}, "
            f"got {transition.new_state}"
        )
        expected_previous = new_state

    # 6. Assert timestamps are in chronological order (non-decreasing)
    for i in range(len(retrieved.state_transitions) - 1):
        ts_current = retrieved.state_transitions[i].timestamp
        ts_next = retrieved.state_transitions[i + 1].timestamp
        assert ts_current <= ts_next, (
            f"Timestamps not in chronological order: "
            f"transition {i} ({ts_current}) > transition {i + 1} ({ts_next})"
        )

    # Additionally verify all timestamps are valid ISO 8601 UTC
    for transition in retrieved.state_transitions:
        assert transition.timestamp is not None
        # Verify it's a valid datetime (pydantic already parsed it)
        assert isinstance(transition.timestamp, datetime)
