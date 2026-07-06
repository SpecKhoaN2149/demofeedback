# Feature: nlp-feedback-routing, Property 10
"""Property test for Decision Engine Evaluation Order.

**Property 10: Decision Engine Evaluation Order** — For any feedback record
with complete NLP analysis, the Decision_Engine SHALL assign the routing action
corresponding to the highest-priority matching rule in the evaluation order:
escalate > route_to_existing > create_ticket > auto_resolve. If escalation
criteria are met, the result is always "escalate" regardless of whether
lower-priority rules also match.

**Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from nlp_processing.models.feedback_routing import (
    CanonicalFeedback,
    FeedbackAnalysis,
    Ticket,
)
from nlp_processing.persistence.feedback_store import FeedbackStore
from nlp_processing.routing.decision_engine import (
    DecisionEngine,
    LEGAL_KEYWORDS,
)
from tests.feedback_routing.strategies import (
    theme_categories,
    timestamp_iso,
)


def _now_iso() -> str:
    """Return the current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


def _make_store_with_open_ticket(cluster_id: str) -> FeedbackStore:
    """Create a FeedbackStore pre-populated with an open ticket for a cluster.

    This sets up the route_to_existing condition: the cluster has an open ticket.
    """
    store = FeedbackStore(":memory:")
    ticket_id = _new_uuid()
    now = _now_iso()

    # Insert a cluster
    store._conn.execute(
        """INSERT INTO clusters (cluster_id, theme, volume_count, priority_level,
           first_seen_at, last_seen_at, status)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (cluster_id, "outage", 5, "high", now, now, "active"),
    )

    # Insert an open ticket linked to that cluster
    store._conn.execute(
        """INSERT INTO tickets (ticket_id, ticket_phase, priority_level,
           assigned_department, created_at, updated_at, linked_cluster_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (ticket_id, "in_progress", "high", "Network_Operations", now, now, cluster_id),
    )
    store._conn.commit()
    return store


# ---------------------------------------------------------------------------
# Strategies for generating escalation-triggering inputs
# ---------------------------------------------------------------------------

# Strategy: pick a legal keyword to embed in cleaned_text
_legal_keyword_strategy = st.sampled_from(LEGAL_KEYWORDS)


@st.composite
def escalation_feedback_and_analysis(draw: st.DrawFn):
    """Generate CanonicalFeedback + FeedbackAnalysis that ALWAYS meet escalation
    criteria (legal keywords in text AND critical priority), while ALSO meeting
    conditions for lower-priority rules simultaneously.

    Lower-priority conditions set up:
    - route_to_existing: cluster_id is set (store will have open ticket)
    - create_ticket: requires_action=True, priority medium/high (but we use critical)
    - auto_resolve: duplicate_count > 0 OR intent "praise"
    """
    feedback_id = _new_uuid()
    cluster_id = _new_uuid()

    # Embed a legal keyword in the text to trigger escalation via Req 14.2
    legal_kw = draw(_legal_keyword_strategy)
    # Also include outage keyword for additional escalation signal
    base_text = draw(
        st.text(
            alphabet=st.characters(min_codepoint=32, max_codepoint=126),
            min_size=5,
            max_size=100,
        )
    )
    cleaned_text = f"I will contact my {legal_kw} about this outage issue {base_text}"

    # Source type: use social to also potentially trigger viral escalation
    source_type = draw(st.sampled_from(["social", "widget"]))

    # Set duplicate_count > 0 to also satisfy auto_resolve duplicate criteria
    duplicate_count = draw(st.integers(min_value=1, max_value=10))

    feedback = CanonicalFeedback(
        feedback_id=feedback_id,
        source_type=source_type,
        original_source_id=_new_uuid(),
        cleaned_text=cleaned_text,
        detected_language="en",
        ingested_at=draw(timestamp_iso()),
        duplicate_count=duplicate_count,
        profanity_detected=False,
        metadata={
            "engagement_metrics": {"likes": 50, "replies": 30, "reposts": 25},
            "platform": "reddit",
        },
        processing_status="analyzed",
    )

    # priority_level "critical" triggers escalation via Req 14.1
    # priority_score in [0.75, 1.0] for critical range
    priority_score = draw(
        st.floats(min_value=0.75, max_value=1.0, allow_nan=False, allow_infinity=False)
    )

    # Set requires_action=True and intent that would trigger create_ticket
    # if escalation didn't short-circuit
    analysis = FeedbackAnalysis(
        feedback_id=feedback_id,
        sentiment_label="negative",
        sentiment_score=draw(
            st.floats(min_value=-1.0, max_value=-0.3, allow_nan=False, allow_infinity=False)
        ),
        priority_score=priority_score,
        priority_level="critical",
        theme_primary=draw(theme_categories()),
        theme_secondary=None,
        intent=draw(st.sampled_from(["complaint", "outage_report", "billing_dispute"])),
        cluster_id=cluster_id,  # Set cluster_id so route_to_existing could match
        requires_action=True,  # Would trigger create_ticket rule
        entities=[],
        processed_at=draw(timestamp_iso()),
    )

    return feedback, analysis, cluster_id


@settings(max_examples=100)
@given(data=escalation_feedback_and_analysis())
def test_escalation_always_wins_over_lower_priority_rules(
    data: tuple,
) -> None:
    """When escalation criteria are met, the decision engine always returns
    "escalate" even when route_to_existing, create_ticket, and auto_resolve
    criteria are also satisfied simultaneously.

    Validates: Requirements 10.1, 10.2
    """
    feedback, analysis, cluster_id = data

    # Create a store with an open ticket for the cluster
    # (satisfies route_to_existing criteria)
    store = _make_store_with_open_ticket(cluster_id)
    engine = DecisionEngine(store)

    decision = engine.evaluate(feedback, analysis)

    assert decision.routing_action == "escalate", (
        f"Expected 'escalate' but got '{decision.routing_action}'. "
        f"Escalation criteria met: priority_level='critical', "
        f"legal keyword in text='{feedback.cleaned_text[:80]}...', "
        f"but engine chose a lower-priority action."
    )


@settings(max_examples=100)
@given(data=escalation_feedback_and_analysis())
def test_escalation_produces_executive_escalations_department(
    data: tuple,
) -> None:
    """When escalation is triggered, the department is always
    Executive_Escalations regardless of theme/intent mapping.

    Validates: Requirements 10.1, 10.2
    """
    feedback, analysis, cluster_id = data

    store = _make_store_with_open_ticket(cluster_id)
    engine = DecisionEngine(store)

    decision = engine.evaluate(feedback, analysis)

    assert decision.routing_action == "escalate"
    assert decision.department == "Executive_Escalations", (
        f"Expected department 'Executive_Escalations' for escalation, "
        f"got '{decision.department}'"
    )


@settings(max_examples=100)
@given(data=escalation_feedback_and_analysis())
def test_escalation_short_circuits_evaluation(
    data: tuple,
) -> None:
    """When escalation criteria are met, no ticket is linked to an existing one
    (route_to_existing is not evaluated), confirming short-circuit behavior.

    Validates: Requirements 10.2, 10.3, 10.4, 10.5
    """
    feedback, analysis, cluster_id = data

    store = _make_store_with_open_ticket(cluster_id)
    engine = DecisionEngine(store)

    decision = engine.evaluate(feedback, analysis)

    # Escalation was chosen, so linked_ticket_id must be None
    # (route_to_existing was not applied)
    assert decision.routing_action == "escalate"
    assert decision.linked_ticket_id is None, (
        "Escalation should short-circuit; linked_ticket_id must be None "
        "(route_to_existing should not be evaluated)"
    )
    # Escalation creates its own ticket, not linked to existing
    assert decision.ticket is not None, (
        "Escalation must produce a new ticket"
    )
    assert decision.ticket.priority_level == "critical"
    assert decision.ticket.assigned_department == "Executive_Escalations"
