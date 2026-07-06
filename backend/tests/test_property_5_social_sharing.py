"""Property 5: Social sharing controls marketing outbound behavior.

**Validates: Requirements 4.4, 4.5, 17.2, 17.3**

For any positive submission, if social_sharing is true, the Marketing_Engine SHALL
generate a shareable URL and email template; if social_sharing is false, the
Marketing_Engine SHALL log for internal use only with social_status "internal_only"
and no shareable URL.
"""

import os
import tempfile
import uuid

# Set up a temp database before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SUBMISSIONS_DB_PATH"] = _tmp.name

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.database import init_db, get_connection
from app.services.marketing_engine import MarketingEngine


@pytest.fixture(autouse=True)
def fresh_db():
    """Initialize a fresh database before each test."""
    init_db()
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM marketing_log")
        conn.execute("DELETE FROM submissions")
        conn.commit()


# Strategies for generating valid positive submission data
customer_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
    min_size=1,
    max_size=50,
).filter(lambda s: len(s.strip()) >= 1)

praise_texts = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=200,
).filter(lambda s: len(s.strip()) >= 1)

social_sharing_flag = st.booleans()


@settings(max_examples=100)
@given(
    customer_name=customer_names,
    praise_text=praise_texts,
    social_sharing=social_sharing_flag,
)
def test_social_sharing_controls_marketing_outbound(
    customer_name: str, praise_text: str, social_sharing: bool
):
    """Property 5: Social sharing controls marketing outbound behavior.

    Feature: sentiment-routed-frontend, Property 5
    **Validates: Requirements 4.4, 4.5, 17.2, 17.3**
    """
    engine = MarketingEngine()
    submission_id = str(uuid.uuid4())

    # Insert a parent submission row so FK constraint is satisfied
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO submissions (id, created_at, customer_name, email, core_request,
                                     sentiment, progress_state, praise_text, social_sharing)
            VALUES (?, datetime('now'), ?, NULL, 'Great service', 'positive', 100, ?, ?)
            """,
            (submission_id, customer_name, praise_text, 1 if social_sharing else 0),
        )
        conn.commit()

    # Call MarketingEngine.log_praise()
    engine.log_praise(
        submission_id=submission_id,
        customer_name=customer_name,
        praise_text=praise_text,
        social_sharing=social_sharing,
    )

    # Retrieve the marketing log entry
    with get_connection() as conn:
        row = conn.execute(
            "SELECT social_status, shareable_url FROM marketing_log WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()

    assert row is not None, f"No marketing log entry found for submission {submission_id}"

    if social_sharing:
        assert row["social_status"] == "shared", (
            f"Expected social_status='shared' when social_sharing=True, got '{row['social_status']}'"
        )
        assert row["shareable_url"] is not None, (
            "Expected shareable_url to be generated when social_sharing=True"
        )
    else:
        assert row["social_status"] == "internal_only", (
            f"Expected social_status='internal_only' when social_sharing=False, got '{row['social_status']}'"
        )
        assert row["shareable_url"] is None, (
            f"Expected no shareable_url when social_sharing=False, got '{row['shareable_url']}'"
        )

    # Cleanup for this test iteration
    with get_connection() as conn:
        conn.execute("DELETE FROM marketing_log WHERE submission_id = ?", (submission_id,))
        conn.execute("DELETE FROM submissions WHERE id = ?", (submission_id,))
        conn.commit()
