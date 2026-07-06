"""Unit tests for the Decision Engine (tasks 7.1–7.5).

Tests cover:
- Evaluation order and short-circuit behavior (Req 10.1–10.5)
- Fallback when NLP fields invalid (Req 10.6, 10.9)
- Escalation logic: critical priority, legal keywords, high-value account, viral (Req 14)
- Route-to-existing: cluster with open ticket (Req 12)
- Create-ticket: requires_action + medium/high, department mapping (Req 13)
- Auto-resolve: duplicate, praise, cluster resolved, FAQ, default fallback (Req 11)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from nlp_processing.models.feedback_routing import (
    CanonicalFeedback,
    FeedbackAnalysis,
    Ticket,
)
from nlp_processing.persistence.feedback_store import FeedbackStore
from nlp_processing.routing.decision_engine import DecisionEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_feedback(
    *,
    feedback_id: str | None = None,
    source_type: str = "widget",
    cleaned_text: str = "My internet is slow and I need help.",
    duplicate_count: int = 0,
    metadata: dict | None = None,
) -> CanonicalFeedback:
    """Create a CanonicalFeedback record for testing."""
    return CanonicalFeedback(
        feedback_id=feedback_id or str(uuid.uuid4()),
        source_type=source_type,
        original_source_id=str(uuid.uuid4()),
        cleaned_text=cleaned_text,
        detected_language="en",
        ingested_at=_now_iso(),
        duplicate_count=duplicate_count,
        profanity_detected=False,
        metadata=metadata or {},
        processing_status="analyzed",
    )


def _make_analysis(
    *,
    feedback_id: str | None = None,
    priority_level: str = "medium",
    priority_score: float = 0.4,
    sentiment_label: str = "negative",
    sentiment_score: float = -0.5,
    theme_primary: str = "speed_performance",
    intent: str = "request_for_help",
    requires_action: bool = True,
    cluster_id: str | None = None,
) -> FeedbackAnalysis:
    """Create a FeedbackAnalysis record for testing."""
    return FeedbackAnalysis(
        feedback_id=feedback_id or str(uuid.uuid4()),
        sentiment_label=sentiment_label,
        sentiment_score=sentiment_score,
        priority_score=priority_score,
        priority_level=priority_level,
        theme_primary=theme_primary,
        theme_secondary=None,
        intent=intent,
        cluster_id=cluster_id,
        requires_action=requires_action,
        entities=[],
        processed_at=_now_iso(),
    )


@pytest.fixture
def store() -> FeedbackStore:
    """Create an in-memory FeedbackStore for testing."""
    return FeedbackStore(":memory:")


@pytest.fixture
def engine(store: FeedbackStore) -> DecisionEngine:
    """Create a DecisionEngine with an in-memory store."""
    return DecisionEngine(store)


def _insert_feedback_record(store: FeedbackStore, feedback_id: str) -> None:
    """Insert a minimal feedback record for FK constraints."""
    store.insert_feedback(
        feedback_id=feedback_id,
        source_type="widget",
        message_text="Test feedback",
        created_at_original=_now_iso(),
    )


# ---------------------------------------------------------------------------
# Task 7.1: Core evaluation order and fallback
# ---------------------------------------------------------------------------


class TestEvaluationOrder:
    """Tests for evaluation order and short-circuit behavior."""

    def test_evaluation_timestamp_is_recorded(self, engine: DecisionEngine) -> None:
        """Req 10.7: evaluation_timestamp is set on the routing decision."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="low",
            intent="praise",
            requires_action=False,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.evaluation_timestamp
        # Should be valid ISO 8601 UTC
        dt = datetime.strptime(decision.evaluation_timestamp, "%Y-%m-%dT%H:%M:%SZ")
        assert dt.year >= 2020

    def test_fallback_when_no_rules_match(self, engine: DecisionEngine) -> None:
        """Req 10.6: Fallback to create_ticket/medium/Customer_Care when
        the feedback doesn't match escalation, route_to_existing, or create_ticket
        and also doesn't match any auto_resolve criteria.
        
        Actually auto_resolve always fires as the last step with a default
        'no_action_required'. So this tests that auto_resolve default works.
        """
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            intent="complaint",
            requires_action=False,  # won't trigger create_ticket
        )
        decision = engine.evaluate(feedback, analysis)
        # Should fall through to auto_resolve with no_action_required
        assert decision.routing_action == "auto_resolve"
        assert decision.resolution_type == "no_action_required"

    def test_escalation_short_circuits_lower_rules(
        self, engine: DecisionEngine
    ) -> None:
        """Req 10.2: Escalation prevents lower-priority rules from executing."""
        feedback = _make_feedback(
            cleaned_text="I will contact my lawyer about this outage!",
        )
        analysis = _make_analysis(
            priority_level="critical",
            intent="complaint",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "escalate"

    def test_fallback_on_missing_priority_level(self, engine: DecisionEngine) -> None:
        """Req 10.9: Missing/invalid NLP fields → fallback create_ticket."""
        feedback = _make_feedback()
        # Create analysis with empty intent (which is invalid)
        # Since Pydantic won't allow empty string for required field easily,
        # we test by monkeypatching
        analysis = _make_analysis(priority_level="medium", intent="complaint")
        # Override intent to empty after construction
        object.__setattr__(analysis, "intent", "")
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "create_ticket"
        assert decision.ticket is not None
        assert decision.ticket.priority_level == "medium"
        assert decision.ticket.assigned_department == "Customer_Care"


# ---------------------------------------------------------------------------
# Task 7.2: Escalation logic
# ---------------------------------------------------------------------------


class TestEscalation:
    """Tests for escalation criteria (Req 14)."""

    def test_escalate_on_critical_priority(self, engine: DecisionEngine) -> None:
        """Req 14.1: priority_level 'critical' triggers escalation."""
        feedback = _make_feedback()
        analysis = _make_analysis(priority_level="critical", priority_score=0.85)
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "escalate"
        assert decision.ticket is not None
        assert decision.ticket.priority_level == "critical"
        assert decision.ticket.assigned_department == "Executive_Escalations"
        assert decision.ticket.ticket_phase == "new"

    def test_escalate_on_legal_keyword_lawyer(self, engine: DecisionEngine) -> None:
        """Req 14.2: Legal keyword 'lawyer' triggers escalation."""
        feedback = _make_feedback(
            cleaned_text="I am going to call my LAWYER about this.",
        )
        analysis = _make_analysis(priority_level="medium")
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "escalate"

    def test_escalate_on_legal_keyword_fcc(self, engine: DecisionEngine) -> None:
        """Req 14.2: Legal keyword 'fcc' triggers escalation (case-insensitive)."""
        feedback = _make_feedback(
            cleaned_text="I will report you to the FCC if this is not fixed.",
        )
        analysis = _make_analysis(priority_level="low", priority_score=0.1)
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "escalate"

    def test_escalate_on_legal_keyword_class_action(
        self, engine: DecisionEngine
    ) -> None:
        """Req 14.2: Multi-word keyword 'class action' triggers escalation."""
        feedback = _make_feedback(
            cleaned_text="We are organizing a class action against your company.",
        )
        analysis = _make_analysis(priority_level="low", priority_score=0.1)
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "escalate"

    def test_escalate_on_legal_keyword_legal_action(
        self, engine: DecisionEngine
    ) -> None:
        """Req 14.2: 'legal action' triggers escalation."""
        feedback = _make_feedback(
            cleaned_text="I will take legal action unless resolved immediately.",
        )
        analysis = _make_analysis(priority_level="medium")
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "escalate"

    def test_escalate_on_high_value_with_3_open_tickets(
        self, store: FeedbackStore, engine: DecisionEngine
    ) -> None:
        """Req 14.3: High-value account with 3+ open tickets → escalation."""
        customer_id = "cust-high-001"

        # Create 3 open tickets linked to this customer
        for i in range(3):
            fid = f"fb-{i}-{uuid.uuid4()}"
            tid = f"tk-{i}-{uuid.uuid4()}"
            _insert_feedback_record(store, fid)
            # Update customer_id on the feedback record
            store._conn.execute(
                "UPDATE feedback SET customer_id = ? WHERE feedback_id = ?",
                (customer_id, fid),
            )
            store._conn.commit()

            ticket = Ticket(
                ticket_id=tid,
                ticket_phase="in_progress",
                priority_level="medium",
                assigned_department="Customer_Care",
                created_at=_now_iso(),
                updated_at=_now_iso(),
            )
            store.insert_ticket(ticket)
            store.link_feedback_ticket(fid, tid)

        # Now evaluate new feedback from same high_value customer
        feedback = _make_feedback(
            metadata={"account_type": "high_value", "customer_id": customer_id},
        )
        analysis = _make_analysis(priority_level="medium")
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "escalate"

    def test_escalate_on_viral_social_post(self, engine: DecisionEngine) -> None:
        """Req 14.4: Social post with engagement > 1000 → escalation."""
        feedback = _make_feedback(
            source_type="social",
            metadata={
                "engagement_metrics": {"likes": 500, "replies": 300, "reposts": 250},
            },
        )
        analysis = _make_analysis(priority_level="medium")
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "escalate"

    def test_no_escalate_on_low_engagement(self, engine: DecisionEngine) -> None:
        """Engagement <= 1000 does not trigger viral escalation."""
        feedback = _make_feedback(
            source_type="social",
            metadata={
                "engagement_metrics": {"likes": 50, "replies": 30, "reposts": 20},
            },
        )
        analysis = _make_analysis(priority_level="medium")
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action != "escalate"

    def test_multiple_escalation_criteria_single_ticket(
        self, engine: DecisionEngine
    ) -> None:
        """Req 14.7: Multiple criteria match → exactly one escalation ticket."""
        feedback = _make_feedback(
            source_type="social",
            cleaned_text="I will call my lawyer about this outage!",
            metadata={
                "engagement_metrics": {"likes": 600, "replies": 300, "reposts": 200},
            },
        )
        analysis = _make_analysis(priority_level="critical", priority_score=0.9)
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "escalate"
        assert decision.ticket is not None
        # Exactly one ticket
        assert decision.ticket.ticket_id is not None
        assert decision.ticket.priority_level == "critical"
        assert decision.ticket.assigned_department == "Executive_Escalations"


# ---------------------------------------------------------------------------
# Task 7.3: Route-to-existing logic
# ---------------------------------------------------------------------------


class TestRouteToExisting:
    """Tests for route_to_existing criteria (Req 12)."""

    def test_route_to_existing_when_cluster_has_open_ticket(
        self, store: FeedbackStore, engine: DecisionEngine
    ) -> None:
        """Req 12.1: Cluster with open ticket → route_to_existing."""
        cluster_id = str(uuid.uuid4())

        # Create cluster first
        from nlp_processing.models.feedback_routing import ClusterRecord

        cluster = ClusterRecord(
            cluster_id=cluster_id,
            theme="outage",
            volume_count=5,
            priority_level="high",
            first_seen_at=_now_iso(),
            last_seen_at=_now_iso(),
            status="active",
        )
        store.insert_cluster(cluster)

        # Create an open ticket for this cluster
        existing_ticket = Ticket(
            ticket_id=str(uuid.uuid4()),
            ticket_phase="in_progress",
            priority_level="high",
            assigned_department="Network_Operations",
            created_at=_now_iso(),
            updated_at=_now_iso(),
            linked_cluster_id=cluster_id,
        )
        store.insert_ticket(existing_ticket)

        # Evaluate feedback in same cluster (not critical, not escalating)
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            cluster_id=cluster_id,
            intent="complaint",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "route_to_existing"
        assert decision.linked_ticket_id == existing_ticket.ticket_id
        assert decision.ticket is None  # Req 12.3: No new ticket created

    def test_route_to_most_recent_when_multiple_open_tickets(
        self, store: FeedbackStore, engine: DecisionEngine
    ) -> None:
        """Req 12.4: Multiple open tickets → link to most recently updated."""
        cluster_id = str(uuid.uuid4())

        from nlp_processing.models.feedback_routing import ClusterRecord

        cluster = ClusterRecord(
            cluster_id=cluster_id,
            theme="billing",
            volume_count=3,
            priority_level="medium",
            first_seen_at=_now_iso(),
            last_seen_at=_now_iso(),
            status="active",
        )
        store.insert_cluster(cluster)

        # Create two open tickets, the second is more recent
        older_ticket = Ticket(
            ticket_id=str(uuid.uuid4()),
            ticket_phase="triaged",
            priority_level="medium",
            assigned_department="Billing_Support",
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
            linked_cluster_id=cluster_id,
        )
        newer_ticket = Ticket(
            ticket_id=str(uuid.uuid4()),
            ticket_phase="in_progress",
            priority_level="medium",
            assigned_department="Billing_Support",
            created_at="2024-01-05T00:00:00Z",
            updated_at="2024-01-05T12:00:00Z",
            linked_cluster_id=cluster_id,
        )
        store.insert_ticket(older_ticket)
        store.insert_ticket(newer_ticket)

        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            cluster_id=cluster_id,
            intent="billing_dispute",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "route_to_existing"
        assert decision.linked_ticket_id == newer_ticket.ticket_id

    def test_no_route_when_cluster_tickets_all_resolved(
        self, store: FeedbackStore, engine: DecisionEngine
    ) -> None:
        """No route_to_existing when all cluster tickets are resolved/closed."""
        cluster_id = str(uuid.uuid4())

        from nlp_processing.models.feedback_routing import ClusterRecord

        cluster = ClusterRecord(
            cluster_id=cluster_id,
            theme="billing",
            volume_count=2,
            priority_level="low",
            first_seen_at=_now_iso(),
            last_seen_at=_now_iso(),
            status="active",
        )
        store.insert_cluster(cluster)

        # Create ticket that is already resolved
        resolved_ticket = Ticket(
            ticket_id=str(uuid.uuid4()),
            ticket_phase="resolved",
            priority_level="medium",
            assigned_department="Billing_Support",
            created_at=_now_iso(),
            updated_at=_now_iso(),
            resolution_type="resolved_by_agent",
            linked_cluster_id=cluster_id,
        )
        store.insert_ticket(resolved_ticket)

        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="low",
            cluster_id=cluster_id,
            intent="praise",
            requires_action=False,
        )
        decision = engine.evaluate(feedback, analysis)
        # Should NOT route to existing (ticket is resolved)
        assert decision.routing_action != "route_to_existing"

    def test_no_route_when_no_cluster_id(self, engine: DecisionEngine) -> None:
        """No route_to_existing when feedback has no cluster_id."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            cluster_id=None,
            intent="complaint",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action != "route_to_existing"

    def test_route_to_existing_updates_ticket_timestamp(
        self, store: FeedbackStore, engine: DecisionEngine
    ) -> None:
        """Req 12.2: Routing to existing ticket updates its updated_at timestamp."""
        cluster_id = str(uuid.uuid4())

        from nlp_processing.models.feedback_routing import ClusterRecord

        cluster = ClusterRecord(
            cluster_id=cluster_id,
            theme="outage",
            volume_count=5,
            priority_level="high",
            first_seen_at=_now_iso(),
            last_seen_at=_now_iso(),
            status="active",
        )
        store.insert_cluster(cluster)

        # Create an open ticket with an old updated_at
        old_timestamp = "2024-01-01T00:00:00Z"
        existing_ticket = Ticket(
            ticket_id=str(uuid.uuid4()),
            ticket_phase="in_progress",
            priority_level="high",
            assigned_department="Network_Operations",
            created_at=old_timestamp,
            updated_at=old_timestamp,
            linked_cluster_id=cluster_id,
        )
        store.insert_ticket(existing_ticket)

        # Evaluate feedback to trigger route_to_existing
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            cluster_id=cluster_id,
            intent="complaint",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "route_to_existing"

        # Verify the ticket's updated_at was changed from the old timestamp
        cursor = store._conn.execute(
            "SELECT updated_at FROM tickets WHERE ticket_id = ?",
            (existing_ticket.ticket_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] != old_timestamp  # Timestamp was updated
        assert row[0] == decision.evaluation_timestamp  # Updated to evaluation time


# ---------------------------------------------------------------------------
# Task 7.4: Create-ticket logic with department mapping
# ---------------------------------------------------------------------------


class TestCreateTicket:
    """Tests for create_ticket criteria and department mapping (Req 13)."""

    def test_create_ticket_when_requires_action_and_medium(
        self, engine: DecisionEngine
    ) -> None:
        """Req 13.1: requires_action=true + priority medium → create_ticket."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            intent="complaint",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "create_ticket"
        assert decision.ticket is not None
        assert decision.ticket.ticket_phase == "new"
        assert decision.ticket.priority_level == "medium"

    def test_create_ticket_when_requires_action_and_high(
        self, engine: DecisionEngine
    ) -> None:
        """Req 13.1: requires_action=true + priority high → create_ticket."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="high",
            priority_score=0.6,
            intent="outage_report",
            requires_action=True,
            theme_primary="outage",
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "create_ticket"
        assert decision.ticket is not None
        assert decision.ticket.priority_level == "high"

    def test_no_create_ticket_when_not_requires_action(
        self, engine: DecisionEngine
    ) -> None:
        """Req 13.1: requires_action=false → does not trigger create_ticket."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            intent="feature_suggestion",
            requires_action=False,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action != "create_ticket"

    def test_no_create_ticket_when_priority_low(self, engine: DecisionEngine) -> None:
        """Req 13.1: priority 'low' does not trigger create_ticket."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="low",
            priority_score=0.15,
            intent="request_for_help",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        # Low priority + requires_action should fall through to auto_resolve
        assert decision.routing_action != "create_ticket"

    def test_department_mapping_outage(self, engine: DecisionEngine) -> None:
        """Req 13.3: outage theme → Network_Operations."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="high",
            priority_score=0.6,
            theme_primary="outage",
            intent="outage_report",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.department == "Network_Operations"

    def test_department_mapping_billing(self, engine: DecisionEngine) -> None:
        """Req 13.3: billing theme → Billing_Support."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            theme_primary="billing",
            intent="billing_dispute",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.department == "Billing_Support"

    def test_department_mapping_speed_performance(
        self, engine: DecisionEngine
    ) -> None:
        """Req 13.3: speed_performance theme → Technical_Support."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            theme_primary="speed_performance",
            intent="request_for_help",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.department == "Technical_Support"

    def test_department_mapping_installation(self, engine: DecisionEngine) -> None:
        """Req 13.3: installation theme → Field_Operations."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            theme_primary="installation",
            intent="complaint",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.department == "Field_Operations"

    def test_department_mapping_app_usability(self, engine: DecisionEngine) -> None:
        """Req 13.3: app_usability theme → Digital_Product."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            theme_primary="app_usability",
            intent="complaint",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.department == "Digital_Product"

    def test_department_mapping_cancellation_retention(
        self, engine: DecisionEngine
    ) -> None:
        """Req 13.3: cancellation_retention theme → Retention."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            theme_primary="cancellation_retention",
            intent="cancellation_risk",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.department == "Retention"

    def test_department_mapping_support_experience(
        self, engine: DecisionEngine
    ) -> None:
        """Req 13.3: support_experience theme → Customer_Care."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            theme_primary="support_experience",
            intent="complaint",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.department == "Customer_Care"

    def test_social_engagement_override(self, engine: DecisionEngine) -> None:
        """Req 13.4: Social engagement > 100 → Social_Media_Care override."""
        feedback = _make_feedback(
            source_type="social",
            metadata={
                "engagement_metrics": {"likes": 60, "replies": 30, "reposts": 20},
            },
        )
        analysis = _make_analysis(
            priority_level="medium",
            theme_primary="billing",
            intent="billing_dispute",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        # Engagement = 110 > 100, should override to Social_Media_Care
        assert decision.department == "Social_Media_Care"

    def test_no_social_override_when_engagement_at_threshold(
        self, engine: DecisionEngine
    ) -> None:
        """Engagement exactly 100 does not trigger override (> 100 required)."""
        feedback = _make_feedback(
            source_type="social",
            metadata={
                "engagement_metrics": {"likes": 50, "replies": 30, "reposts": 20},
            },
        )
        analysis = _make_analysis(
            priority_level="medium",
            theme_primary="billing",
            intent="billing_dispute",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        # Engagement = 100, not > 100
        assert decision.department == "Billing_Support"

    def test_fallback_to_customer_care_unclassified_theme(
        self, engine: DecisionEngine
    ) -> None:
        """Req 13.6: Unclassified theme + unmapped intent → Customer_Care."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            theme_primary="unclassified",
            intent="complaint",  # complaint not in INTENT_TO_DEPARTMENT
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.department == "Customer_Care"

    def test_theme_takes_precedence_over_intent(
        self, engine: DecisionEngine
    ) -> None:
        """Req 13.3: Theme mapping takes precedence over intent mapping."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            theme_primary="outage",  # → Network_Operations
            intent="billing_dispute",  # → Billing_Support (if intent had precedence)
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.department == "Network_Operations"

    def test_intent_mapping_when_theme_unclassified(
        self, engine: DecisionEngine
    ) -> None:
        """Intent mapping used when theme is unclassified."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            theme_primary="unclassified",
            intent="billing_dispute",  # → Billing_Support
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.department == "Billing_Support"


# ---------------------------------------------------------------------------
# Task 7.5: Auto-resolve logic
# ---------------------------------------------------------------------------


class TestAutoResolve:
    """Tests for auto-resolve criteria (Req 11)."""

    def test_auto_resolve_duplicate(self, engine: DecisionEngine) -> None:
        """Req 11.1: duplicate_count > 0 → auto_resolve with 'duplicate'."""
        feedback = _make_feedback(duplicate_count=3)
        analysis = _make_analysis(
            priority_level="low",
            priority_score=0.1,
            intent="complaint",
            requires_action=True,
        )
        # duplicate_count > 0 should trigger auto_resolve even with
        # requires_action=True because escalation and route_to_existing
        # don't match, and create_ticket requires medium/high + requires_action.
        # Actually low priority won't trigger create_ticket, so it falls to auto_resolve.
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "auto_resolve"
        assert decision.resolution_type == "duplicate"
        assert decision.ticket is not None
        assert decision.ticket.ticket_phase == "auto_closed"
        assert decision.ticket.resolution_type == "duplicate"

    def test_auto_resolve_praise_low_no_action(self, engine: DecisionEngine) -> None:
        """Req 11.2: praise + low + no action → 'no_action_required'."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="low",
            priority_score=0.1,
            sentiment_label="positive",
            sentiment_score=0.8,
            intent="praise",
            requires_action=False,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "auto_resolve"
        assert decision.resolution_type == "no_action_required"

    def test_auto_resolve_cluster_all_resolved(
        self, store: FeedbackStore, engine: DecisionEngine
    ) -> None:
        """Req 11.3: Cluster all tickets resolved → 'known_resolved'."""
        cluster_id = str(uuid.uuid4())

        from nlp_processing.models.feedback_routing import ClusterRecord

        cluster = ClusterRecord(
            cluster_id=cluster_id,
            theme="billing",
            volume_count=5,
            priority_level="medium",
            first_seen_at=_now_iso(),
            last_seen_at=_now_iso(),
            status="active",
        )
        store.insert_cluster(cluster)

        # Create resolved and closed tickets
        for phase in ("resolved", "closed", "auto_closed"):
            ticket = Ticket(
                ticket_id=str(uuid.uuid4()),
                ticket_phase=phase,
                priority_level="medium",
                assigned_department="Billing_Support",
                created_at=_now_iso(),
                updated_at=_now_iso(),
                resolution_type="resolved_by_agent" if phase == "resolved" else "auto_resolved",
                linked_cluster_id=cluster_id,
            )
            store.insert_ticket(ticket)

        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="low",
            priority_score=0.1,
            cluster_id=cluster_id,
            intent="complaint",
            requires_action=False,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "auto_resolve"
        assert decision.resolution_type == "known_resolved"

    def test_auto_resolve_faq_match(self, engine: DecisionEngine) -> None:
        """Req 11.4: FAQ match + low + request_for_help → 'faq_matched'."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="low",
            priority_score=0.15,
            theme_primary="billing",  # In FAQ_TOPICS
            intent="request_for_help",
            requires_action=True,  # This is True but priority is low so no create_ticket
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "auto_resolve"
        assert decision.resolution_type == "faq_matched"

    def test_auto_resolve_default_fallback(self, engine: DecisionEngine) -> None:
        """Req 11.6: No auto-resolve criteria → 'no_action_required'."""
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="low",
            priority_score=0.1,
            theme_primary="equipment",
            intent="unclassified",
            requires_action=False,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "auto_resolve"
        assert decision.resolution_type == "no_action_required"

    def test_auto_resolve_ticket_has_correct_fields(
        self, engine: DecisionEngine
    ) -> None:
        """Req 11.5: Auto-resolve creates ticket with auto_closed phase."""
        feedback = _make_feedback(duplicate_count=1)
        analysis = _make_analysis(
            priority_level="low",
            priority_score=0.1,
            intent="praise",
            requires_action=False,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.ticket is not None
        assert decision.ticket.ticket_phase == "auto_closed"
        assert decision.ticket.resolution_type is not None
        assert decision.ticket.ticket_id is not None
        assert decision.ticket.created_at is not None
        assert decision.ticket.updated_at is not None


# ---------------------------------------------------------------------------
# Integration: Evaluation order between levels
# ---------------------------------------------------------------------------


class TestEvaluationPrecedence:
    """Tests verifying correct precedence across all rule levels."""

    def test_escalation_beats_route_to_existing(
        self, store: FeedbackStore, engine: DecisionEngine
    ) -> None:
        """Escalation takes precedence over route_to_existing."""
        cluster_id = str(uuid.uuid4())

        from nlp_processing.models.feedback_routing import ClusterRecord

        cluster = ClusterRecord(
            cluster_id=cluster_id,
            theme="outage",
            volume_count=10,
            priority_level="high",
            first_seen_at=_now_iso(),
            last_seen_at=_now_iso(),
            status="active",
        )
        store.insert_cluster(cluster)

        # Create open ticket for cluster
        existing_ticket = Ticket(
            ticket_id=str(uuid.uuid4()),
            ticket_phase="in_progress",
            priority_level="high",
            assigned_department="Network_Operations",
            created_at=_now_iso(),
            updated_at=_now_iso(),
            linked_cluster_id=cluster_id,
        )
        store.insert_ticket(existing_ticket)

        # Feedback with critical priority (escalation trigger)
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="critical",
            priority_score=0.85,
            cluster_id=cluster_id,
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "escalate"

    def test_route_to_existing_beats_create_ticket(
        self, store: FeedbackStore, engine: DecisionEngine
    ) -> None:
        """Route_to_existing takes precedence over create_ticket."""
        cluster_id = str(uuid.uuid4())

        from nlp_processing.models.feedback_routing import ClusterRecord

        cluster = ClusterRecord(
            cluster_id=cluster_id,
            theme="speed_performance",
            volume_count=5,
            priority_level="medium",
            first_seen_at=_now_iso(),
            last_seen_at=_now_iso(),
            status="active",
        )
        store.insert_cluster(cluster)

        # Create open ticket for cluster
        existing_ticket = Ticket(
            ticket_id=str(uuid.uuid4()),
            ticket_phase="new",
            priority_level="medium",
            assigned_department="Technical_Support",
            created_at=_now_iso(),
            updated_at=_now_iso(),
            linked_cluster_id=cluster_id,
        )
        store.insert_ticket(existing_ticket)

        # Feedback that would trigger create_ticket (requires_action + medium)
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            cluster_id=cluster_id,
            intent="request_for_help",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        # Route_to_existing should win
        assert decision.routing_action == "route_to_existing"

    def test_create_ticket_beats_auto_resolve(self, engine: DecisionEngine) -> None:
        """Create_ticket takes precedence over auto_resolve."""
        # This feedback would match FAQ auto-resolve if priority were low,
        # but with medium priority + requires_action it triggers create_ticket
        feedback = _make_feedback()
        analysis = _make_analysis(
            priority_level="medium",
            theme_primary="billing",  # In FAQ_TOPICS
            intent="request_for_help",
            requires_action=True,
        )
        decision = engine.evaluate(feedback, analysis)
        assert decision.routing_action == "create_ticket"
