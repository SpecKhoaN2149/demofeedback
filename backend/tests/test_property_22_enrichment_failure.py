"""Property 22: Enrichment failure classification.

**Validates: Requirements 13.3**

For any BatchOutput with zero InsightRecords and at least one FailureEntry,
the enrichment_status SHALL be set to "failed" with the failure stage and reason
stored on the submission.
"""

import asyncio
import os
import tempfile
from unittest.mock import MagicMock, patch

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


# --- Strategies ---

# Valid stages from NLP processing pipeline
VALID_STAGES = [
    "ingestion",
    "classification",
    "sentiment_analysis",
    "severity_scoring",
    "language_detection",
    "clustering",
    "prioritization",
    "enrichment",
    "validation",
]

failure_stage_strategy = st.sampled_from(VALID_STAGES)

failure_reason_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=200,
).filter(lambda s: len(s.strip()) >= 1)

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

# Strategy for generating a list of failure entries (at least 1)
failure_entries_strategy = st.lists(
    st.fixed_dictionaries({
        "stage": failure_stage_strategy,
        "reason": failure_reason_strategy,
    }),
    min_size=1,
    max_size=5,
)


@settings(max_examples=50)
@given(
    sentiment=sentiments,
    customer_name=customer_names,
    email=emails,
    core_request=core_requests,
    failure_entries=failure_entries_strategy,
)
def test_enrichment_failure_classification(
    sentiment: str, customer_name: str, email: str,
    core_request: str, failure_entries: list,
):
    """Property 22: BatchOutput with zero insights and FailureEntries sets status to 'failed'.

    Feature: sentiment-routed-frontend, Property 22
    **Validates: Requirements 13.3**
    """
    store = SubmissionStore()

    # Build submission-specific fields
    kwargs: dict = {
        "customer_name": customer_name,
        "email": email,
        "phone": None,
        "core_request": core_request,
        "sentiment": sentiment,
        "issue_category": "billing" if sentiment == "negative" else None,
        "detailed_description": "A detailed description text" if sentiment == "negative" else None,
        "praise_text": "Great service!" if sentiment == "positive" else None,
        "social_sharing": False,
        "comment_text": "A neutral comment" if sentiment == "neutral" else None,
    }

    data = SubmissionCreate(**kwargs)
    submission = store.create(data)

    # Verify initial state is "pending"
    initial = store.get(submission.id)
    assert initial is not None
    assert initial.enrichment_status == "pending"

    # Create mock FailureEntry objects
    mock_failures = []
    for entry in failure_entries:
        mock_failure = MagicMock()
        mock_failure.stage = entry["stage"]
        mock_failure.reason = entry["reason"]
        mock_failures.append(mock_failure)

    # Create a mock BatchOutput with zero insights and failure entries
    mock_output = MagicMock()
    mock_output.insights = []  # Zero InsightRecords
    mock_output.failures = mock_failures  # At least one FailureEntry

    # Patch _do_nlp_processing to return the mocked output
    with patch(
        "app.services.enrichment._do_nlp_processing",
        return_value={"success": True, "output": mock_output},
    ), patch(
        "app.services.enrichment._submission_store", store
    ):
        from app.services.enrichment import run_enrichment

        # Run the async enrichment function
        asyncio.run(run_enrichment(str(submission.id), core_request))

    # Verify the submission's enrichment_status is now "failed"
    updated = store.get(submission.id)
    assert updated is not None
    assert updated.enrichment_status == "failed", (
        f"Expected enrichment_status='failed' when BatchOutput has zero insights "
        f"and {len(failure_entries)} FailureEntries, got '{updated.enrichment_status}'"
    )
