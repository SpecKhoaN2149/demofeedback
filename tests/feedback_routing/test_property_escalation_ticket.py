# Feature: nlp-feedback-routing, Property 12
"""Property test for Escalation Produces Single Critical Ticket.

**Property 12: Escalation Produces Single Critical Ticket** — For any feedback
record that meets one or more escalation criteria (critical priority,
legal/regulatory keywords, high-value repeat customer, viral social post), the
Decision_Engine SHALL produce exactly one Ticket with priority_level "critical"
and assigned_department "Executive_Escalations", and exactly one
feedback_ticket_link record.

**Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from nlp_processing.models.feedback_routing import (
    CanonicalFeedback,
    FeedbackAnalysis,
)
from nlp_processing.persistence.feedback_store import FeedbackStore
from nlp_processing.routing.decision_engine import (
    DecisionEngine,
    LEGAL_KEYWORDS,
    VIRAL_ENGAGEMENT_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_store() -> FeedbackStore:
    """Create a fresh in-memory FeedbackStore for each test example."""
    return FeedbackStore(":memory:")


# ---------------------------------------------------------------------------
# Strategies: Generate feedback matching MULTIPLE escalation criteria
# ---------------------------------------------------------------------------

# Legal keywords to embed in text (Req 14.2)
legal_keyword_strategy = st.sampled_from(LEGAL_KEYWORDS)

# Engagement values exceeding viral threshold (Req 14.4)
viral_engagement = st.integers(
    min_value=VIRAL_ENGAGEMENT_THRESHOLD + 1, max_value=100_000
)

# Printable ASCII for surrounding text
_PRINTABLE = st.characters(min_codepoint=32, max_codepoint=126)


@st.composite
def escalation_feedback_and_analysis(draw: st.DrawFn) -> tuple[CanonicalFeedback, FeedbackAnalysis]:
    """Generate a (CanonicalFeedback, FeedbackAnalysis) pair that matches
    multiple escalation criteria simultaneously:
    - Critical priority (Req 14.1)
    - Legal keywords in text (Req 14.2)
    - Viral social post with engagement > 1000 (Req 14.4)
    """
    feedback_id = str(uuid.uuid4())

    # Embed a legal keyword in the text (Req 14.2)
    keyword = draw(legal_keyword_strategy)
    prefix = draw(st.text(alphabet=_PRINTABLE, min_size=1, max_size=50))
    suffix = draw(st.text(alphabet=_PRINTABLE, min_size=1, max_size=50))
    cleaned_text = f"{prefix} {keyword} {suffix}"

    # Generate viral engagement metrics (Req 14.4)
    total_engagement = draw(viral_engagement)
    # Distribute across likes, replies, reposts so they sum > threshold
    likes = draw(st.integers(min_value=0, max_value=total_engagement))
    remainder = total_engagement - likes
    replies = draw(st.integers(min_value=0, max_value=remainder))
    reposts = remainder - replies

    metadata = {
        "engagement_metrics": {
            "likes": likes,
            "replies": replies,
            "reposts": reposts,
        },
    }

    feedback = CanonicalFeedback(
        feedback_id=feedback_id,
        source_type="social",  # Required for viral engagement check
        original_source_id=str(uuid.uuid4()),
        cleaned_text=cleaned_text,
        detected_language="en",
        ingested_at=_now_iso(),
        duplicate_count=0,
        profanity_detected=False,
        metadata=metadata,
        processing_status="analyzed",
    )

    # Critical priority (Req 14.1) — score in [0.75, 1.0]
    priority_score = draw(
        st.floats(min_value=0.75, max_value=1.0, allow_nan=False, allow_infinity=False)
    )

    analysis = FeedbackAnalysis(
        feedback_id=feedback_id,
        sentiment_label="negative",
        sentiment_score=draw(
            st.floats(min_value=-1.0, max_value=-0.3, allow_nan=False, allow_infinity=False)
        ),
        priority_score=priority_score,
        priority_level="critical",  # Req 14.1
        theme_primary=draw(
            st.sampled_from([
                "outage", "billing", "speed_performance", "installation",
                "support_experience", "app_usability", "equipment",
                "cancellation_retention",
            ])
        ),
        theme_secondary=None,
        intent=draw(
            st.sampled_from([
                "complaint", "request_for_help", "outage_report",
                "billing_dispute", "cancellation_risk",
            ])
        ),
        cluster_id=None,
        requires_action=True,
        entities=[],
        processed_at=_now_iso(),
    )

    return feedback, analysis


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(data=escalation_feedback_and_analysis())
def test_escalation_produces_exactly_one_ticket(
    data: tuple[CanonicalFeedback, FeedbackAnalysis],
) -> None:
    """Escalation with multiple criteria produces exactly one Ticket.

    Generates feedback matching critical priority + legal keywords + viral
    engagement simultaneously. Verifies the decision engine produces a single
    escalation ticket regardless of how many criteria are satisfied.

    Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7
    """
    feedback, analysis = data
    store = _make_store()
    engine = DecisionEngine(store)

    decision = engine.evaluate(feedback, analysis)

    # Req 14.7: Exactly one routing action "escalate"
    assert decision.routing_action == "escalate", (
        f"Expected routing_action='escalate', got {decision.routing_action!r}"
    )

    # Req 14.5: Exactly one Ticket is produced
    assert decision.ticket is not None, (
        "Expected exactly one Ticket on escalation decision, got None"
    )

    # Req 14.5: Ticket has priority_level "critical"
    assert decision.ticket.priority_level == "critical", (
        f"Expected ticket priority_level='critical', "
        f"got {decision.ticket.priority_level!r}"
    )

    # Req 14.5: Ticket has assigned_department "Executive_Escalations"
    assert decision.ticket.assigned_department == "Executive_Escalations", (
        f"Expected ticket assigned_department='Executive_Escalations', "
        f"got {decision.ticket.assigned_department!r}"
    )

    # Req 14.5: Ticket phase is "new"
    assert decision.ticket.ticket_phase == "new", (
        f"Expected ticket_phase='new', got {decision.ticket.ticket_phase!r}"
    )

    # Req 14.5: Ticket has a valid UUID ticket_id
    assert decision.ticket.ticket_id, (
        "Expected ticket to have a non-empty ticket_id"
    )

    # The department on the decision also matches
    assert decision.department == "Executive_Escalations", (
        f"Expected decision department='Executive_Escalations', "
        f"got {decision.department!r}"
    )


@settings(max_examples=100)
@given(data=escalation_feedback_and_analysis())
def test_escalation_ticket_link_is_singular(
    data: tuple[CanonicalFeedback, FeedbackAnalysis],
) -> None:
    """Escalation produces a structure allowing exactly one feedback_ticket_link.

    The RoutingDecision contains exactly one ticket (not a list), ensuring
    the downstream process creates exactly one feedback_ticket_link record
    per Req 14.6.

    Validates: Requirements 14.6, 14.7
    """
    feedback, analysis = data
    store = _make_store()
    engine = DecisionEngine(store)

    decision = engine.evaluate(feedback, analysis)

    # Exactly one ticket object — not None, not a list
    assert decision.ticket is not None, (
        "Expected a single Ticket for feedback_ticket_link creation"
    )

    # The ticket_id is unique (UUID format)
    try:
        uuid.UUID(decision.ticket.ticket_id)
    except ValueError:
        raise AssertionError(
            f"Expected ticket_id to be a valid UUID, got {decision.ticket.ticket_id!r}"
        )

    # linked_ticket_id should be None for escalation (not route_to_existing)
    assert decision.linked_ticket_id is None, (
        f"Expected linked_ticket_id=None for escalation, "
        f"got {decision.linked_ticket_id!r}"
    )
