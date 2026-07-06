"""Decision Engine: rule-based routing for feedback records (tasks 7.1–7.5).

The :class:`DecisionEngine` evaluates NLP analysis output and determines the
routing action for each feedback record. It applies rules in strict priority
order (short-circuit): escalate → route_to_existing → create_ticket → auto_resolve.

Business rules implemented:
- Evaluation order: escalation > route_to_existing > create_ticket > auto_resolve (Req 10.1–10.5)
- Fallback: create_ticket with priority "medium", department "Customer_Care" (Req 10.6, 10.9)
- Escalation criteria: critical priority, legal keywords, high-value + 3 open tickets, viral (Req 14.1–14.7)
- Route to existing: cluster has open ticket, link to most recent (Req 12.1–12.5)
- Create ticket: requires_action + medium/high, department mapping (Req 13.1–13.7)
- Auto-resolve: duplicate, praise+low, cluster resolved, FAQ match (Req 11.1–11.6)

Design: The engine is a pure-function layer (no external API calls), making it
deterministic and highly testable with property-based tests.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from ..models.feedback_routing import (
    CanonicalFeedback,
    FeedbackAnalysis,
    RoutingDecision,
    Ticket,
)
from ..persistence.feedback_store import FeedbackStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Legal/regulatory keywords for escalation (case-insensitive) (Req 14.2)
LEGAL_KEYWORDS: list[str] = [
    "lawyer",
    "attorney",
    "lawsuit",
    "fcc",
    "regulatory",
    "legal action",
    "class action",
]

# Compile a single regex for efficient keyword matching
_LEGAL_PATTERN = re.compile(
    "|".join(re.escape(kw) for kw in LEGAL_KEYWORDS),
    re.IGNORECASE,
)

# Engagement threshold for viral escalation (Req 14.4)
VIRAL_ENGAGEMENT_THRESHOLD: int = 1000

# Engagement threshold for Social_Media_Care override (Req 13.4)
SOCIAL_ENGAGEMENT_OVERRIDE_THRESHOLD: int = 100

# Department mapping: (primary_theme, intent) → department (Req 13.3)
# Theme takes precedence over intent when both yield different departments.
THEME_TO_DEPARTMENT: dict[str, str] = {
    "outage": "Network_Operations",
    "billing": "Billing_Support",
    "speed_performance": "Technical_Support",
    "installation": "Field_Operations",
    "technician_visit": "Field_Operations",
    "app_usability": "Digital_Product",
    "support_experience": "Customer_Care",
    "cancellation_retention": "Retention",
}

INTENT_TO_DEPARTMENT: dict[str, str] = {
    "outage_report": "Network_Operations",
    "billing_dispute": "Billing_Support",
    "request_for_help": "Technical_Support",
    "feature_suggestion": "Digital_Product",
    "cancellation_risk": "Retention",
}

# FAQ topic list for auto-resolve matching (Req 11.4)
FAQ_TOPICS: frozenset[str] = frozenset({
    "billing",
    "speed_performance",
    "installation",
    "app_usability",
    "equipment",
    "support_experience",
})

# Open ticket phases (not resolved/closed/auto_closed)
_OPEN_PHASES: frozenset[str] = frozenset({
    "new", "triaged", "routed", "in_progress", "waiting",
})


def _now_iso() -> str:
    """Return the current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_ticket_id() -> str:
    """Generate a new UUID for a ticket."""
    return str(uuid.uuid4())


class DecisionEngine:
    """Rule-based routing decision engine (Req 10).

    Evaluates routing rules in priority order for each feedback record.
    Requires a :class:`FeedbackStore` for persistence operations (linking
    feedback to tickets, querying existing tickets by cluster).

    Parameters
    ----------
    store : FeedbackStore
        The persistence layer for ticket CRUD and link operations.
    """

    def __init__(self, store: FeedbackStore) -> None:
        self._store = store

    def evaluate(
        self, feedback: CanonicalFeedback, analysis: FeedbackAnalysis
    ) -> RoutingDecision:
        """Evaluate routing rules and return the routing decision.

        Evaluation order (short-circuit on first match):
        1. Escalation
        2. Route to existing
        3. Create ticket
        4. Auto-resolve

        If NLP fields are missing or invalid, falls back to create_ticket
        with priority "medium" and department "Customer_Care" (Req 10.9).

        Parameters
        ----------
        feedback : CanonicalFeedback
            The preprocessed feedback record.
        analysis : FeedbackAnalysis
            The complete NLP analysis result.

        Returns
        -------
        RoutingDecision
            The determined routing action with ticket/link details.
        """
        # Req 10.9: Validate required NLP fields
        if not self._has_valid_nlp_fields(analysis):
            return self._make_fallback_decision(feedback, analysis)

        # Req 10.1: Check escalation criteria first
        decision = self._check_escalation(feedback, analysis)
        if decision is not None:
            return decision

        # Req 10.3: Check route to existing
        decision = self._check_route_to_existing(feedback, analysis)
        if decision is not None:
            return decision

        # Req 10.4: Check create ticket
        decision = self._check_create_ticket(feedback, analysis)
        if decision is not None:
            return decision

        # Req 10.5: Check auto-resolve (always produces a decision)
        return self._check_auto_resolve(feedback, analysis)

    # ------------------------------------------------------------------
    # Escalation logic (Req 14)
    # ------------------------------------------------------------------

    def _check_escalation(
        self, feedback: CanonicalFeedback, analysis: FeedbackAnalysis
    ) -> Optional[RoutingDecision]:
        """Check escalation criteria (Req 14.1–14.7).

        Criteria (any one triggers escalation):
        - priority_level "critical" (Req 14.1)
        - Legal/regulatory keywords in text (Req 14.2)
        - High-value account with 3+ open tickets (Req 14.3)
        - Viral social post with engagement > 1000 (Req 14.4)

        Returns a RoutingDecision if escalation criteria are met, None otherwise.
        Produces exactly one ticket regardless of how many criteria match (Req 14.7).
        """
        should_escalate = False

        # Req 14.1: Critical priority
        if analysis.priority_level == "critical":
            should_escalate = True

        # Req 14.2: Legal/regulatory keywords (case-insensitive)
        if not should_escalate and _LEGAL_PATTERN.search(feedback.cleaned_text):
            should_escalate = True

        # Req 14.3: High-value account with 3+ open tickets
        if not should_escalate:
            account_type = feedback.metadata.get("account_type")
            customer_id = feedback.metadata.get("customer_id")
            if account_type == "high_value" and customer_id:
                open_count = self._count_open_tickets_for_customer(customer_id)
                if open_count >= 3:
                    should_escalate = True

        # Req 14.4: Viral social post (engagement > 1000)
        if not should_escalate:
            if feedback.source_type == "social":
                total_engagement = self._get_total_engagement(feedback)
                if total_engagement > VIRAL_ENGAGEMENT_THRESHOLD:
                    should_escalate = True

        if not should_escalate:
            return None

        # Create escalation ticket (Req 14.5)
        now = _now_iso()
        ticket = Ticket(
            ticket_id=_new_ticket_id(),
            ticket_phase="new",
            priority_level="critical",
            assigned_department="Executive_Escalations",
            created_at=now,
            updated_at=now,
            linked_cluster_id=analysis.cluster_id,
        )

        return RoutingDecision(
            routing_action="escalate",
            ticket=ticket,
            department="Executive_Escalations",
            evaluation_timestamp=now,
        )

    # ------------------------------------------------------------------
    # Route to existing logic (Req 12)
    # ------------------------------------------------------------------

    def _check_route_to_existing(
        self, feedback: CanonicalFeedback, analysis: FeedbackAnalysis
    ) -> Optional[RoutingDecision]:
        """Check if feedback should be linked to an existing open ticket (Req 12.1–12.5).

        Criteria: feedback's cluster has an existing open ticket (phase not
        resolved/closed/auto_closed). Links to most recently updated open ticket
        when multiple exist. Updates the existing ticket's updated_at timestamp.
        Does NOT create a new ticket.
        """
        if not analysis.cluster_id:
            return None

        # Query existing open tickets for this cluster
        open_ticket = self._find_most_recent_open_ticket_for_cluster(
            analysis.cluster_id
        )
        if open_ticket is None:
            return None

        now = _now_iso()

        # Req 12.2: Update the existing ticket's updated_at timestamp
        self._update_ticket_timestamp(open_ticket["ticket_id"], now)

        return RoutingDecision(
            routing_action="route_to_existing",
            linked_ticket_id=open_ticket["ticket_id"],
            department=open_ticket["assigned_department"],
            evaluation_timestamp=now,
        )

    # ------------------------------------------------------------------
    # Create ticket logic (Req 13)
    # ------------------------------------------------------------------

    def _check_create_ticket(
        self, feedback: CanonicalFeedback, analysis: FeedbackAnalysis
    ) -> Optional[RoutingDecision]:
        """Check if a new ticket should be created (Req 13.1–13.7).

        Criteria: requires_action=true AND priority "medium" or "high".
        Applies department mapping with social engagement override.
        """
        # Req 13.1: requires_action=true and priority "medium" or "high"
        if not analysis.requires_action:
            return None
        if analysis.priority_level not in ("medium", "high"):
            return None

        # Determine department (Req 13.3, 13.4, 13.6)
        department = self._determine_department(feedback, analysis)

        now = _now_iso()
        ticket = Ticket(
            ticket_id=_new_ticket_id(),
            ticket_phase="new",
            priority_level=analysis.priority_level,
            assigned_department=department,
            created_at=now,
            updated_at=now,
            linked_cluster_id=analysis.cluster_id,
        )

        return RoutingDecision(
            routing_action="create_ticket",
            ticket=ticket,
            department=department,
            evaluation_timestamp=now,
        )

    # ------------------------------------------------------------------
    # Auto-resolve logic (Req 11)
    # ------------------------------------------------------------------

    def _check_auto_resolve(
        self, feedback: CanonicalFeedback, analysis: FeedbackAnalysis
    ) -> RoutingDecision:
        """Check auto-resolve criteria (Req 11.1–11.6).

        Criteria checked in order:
        1. Duplicate (duplicate_count > 0) → "duplicate" (Req 11.1)
        2. Praise + low + no action → "no_action_required" (Req 11.2)
        3. Cluster all tickets resolved → "known_resolved" (Req 11.3)
        4. FAQ match + low + request_for_help → "faq_matched" (Req 11.4)
        5. Default fallback → "no_action_required" (Req 11.6)

        Always returns a RoutingDecision (this is the final fallback).
        """
        resolution_type: str

        # Req 11.1: Duplicate
        if feedback.duplicate_count > 0:
            resolution_type = "duplicate"
        # Req 11.2: Praise + low + no action
        elif (
            analysis.intent == "praise"
            and analysis.priority_level == "low"
            and not analysis.requires_action
        ):
            resolution_type = "no_action_required"
        # Req 11.3: Cluster all tickets resolved
        elif analysis.cluster_id and self._are_all_cluster_tickets_resolved(
            analysis.cluster_id
        ):
            resolution_type = "known_resolved"
        # Req 11.4: FAQ match + low + request_for_help
        elif (
            analysis.intent == "request_for_help"
            and analysis.priority_level == "low"
            and analysis.theme_primary in FAQ_TOPICS
        ):
            resolution_type = "faq_matched"
        # Req 11.6: Default fallback
        else:
            resolution_type = "no_action_required"

        now = _now_iso()
        ticket = Ticket(
            ticket_id=_new_ticket_id(),
            ticket_phase="auto_closed",
            priority_level=analysis.priority_level,
            assigned_department="Customer_Care",
            created_at=now,
            updated_at=now,
            resolution_type=resolution_type,
            linked_cluster_id=analysis.cluster_id,
        )

        return RoutingDecision(
            routing_action="auto_resolve",
            ticket=ticket,
            resolution_type=resolution_type,
            department="Customer_Care",
            evaluation_timestamp=now,
        )

    # ------------------------------------------------------------------
    # Fallback decision (Req 10.6, 10.9)
    # ------------------------------------------------------------------

    def _make_fallback_decision(
        self, feedback: CanonicalFeedback, analysis: FeedbackAnalysis
    ) -> RoutingDecision:
        """Create fallback decision when no rules match or NLP fields invalid.

        Assigns create_ticket with priority "medium" and department "Customer_Care".
        """
        now = _now_iso()
        ticket = Ticket(
            ticket_id=_new_ticket_id(),
            ticket_phase="new",
            priority_level="medium",
            assigned_department="Customer_Care",
            created_at=now,
            updated_at=now,
            linked_cluster_id=analysis.cluster_id,
        )

        return RoutingDecision(
            routing_action="create_ticket",
            ticket=ticket,
            department="Customer_Care",
            evaluation_timestamp=now,
        )

    # ------------------------------------------------------------------
    # Department mapping (Req 13.3, 13.4, 13.6)
    # ------------------------------------------------------------------

    def _determine_department(
        self, feedback: CanonicalFeedback, analysis: FeedbackAnalysis
    ) -> str:
        """Determine the routing department based on theme/intent/engagement.

        Priority:
        1. Social engagement > 100 → Social_Media_Care (override) (Req 13.4)
        2. Theme mapping (Req 13.3)
        3. Intent mapping (Req 13.3)
        4. Customer_Care fallback (Req 13.6)
        """
        # Req 13.4: Social engagement override
        if feedback.source_type == "social":
            total_engagement = self._get_total_engagement(feedback)
            if total_engagement > SOCIAL_ENGAGEMENT_OVERRIDE_THRESHOLD:
                return "Social_Media_Care"

        # Req 13.3: Theme takes precedence over intent
        theme_dept = THEME_TO_DEPARTMENT.get(analysis.theme_primary)
        if theme_dept:
            return theme_dept

        # Intent mapping
        intent_dept = INTENT_TO_DEPARTMENT.get(analysis.intent)
        if intent_dept:
            return intent_dept

        # Req 13.6: Fallback to Customer_Care
        return "Customer_Care"

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _update_ticket_timestamp(self, ticket_id: str, timestamp: str) -> None:
        """Update the updated_at timestamp on an existing ticket (Req 12.2)."""
        try:
            self._store._conn.execute(
                "UPDATE tickets SET updated_at = ? WHERE ticket_id = ?",
                (timestamp, ticket_id),
            )
            self._store._conn.commit()
        except Exception as exc:
            logger.warning(
                "Failed to update ticket timestamp for %s: %s",
                ticket_id,
                exc,
            )

    def _has_valid_nlp_fields(self, analysis: FeedbackAnalysis) -> bool:
        """Check that required NLP fields are present and valid (Req 10.9).

        Validates that priority_level, intent, and requires_action are present.
        Since FeedbackAnalysis uses Pydantic with strict typing, if the object
        was constructed it should be valid. This catches None or empty values
        on the required fields.
        """
        if not analysis.priority_level:
            return False
        if not analysis.intent:
            return False
        # requires_action is a bool, so it's always present if model is valid
        return True

    def _get_total_engagement(self, feedback: CanonicalFeedback) -> int:
        """Extract total engagement (likes + replies + reposts) from metadata."""
        engagement = feedback.metadata.get("engagement_metrics", {})
        if isinstance(engagement, dict):
            likes = engagement.get("likes", 0)
            replies = engagement.get("replies", 0)
            reposts = engagement.get("reposts", 0)
            return int(likes) + int(replies) + int(reposts)
        return 0

    def _count_open_tickets_for_customer(self, customer_id: str) -> int:
        """Count open tickets linked to a customer_id.

        Queries feedback_ticket_link + tickets + feedback to find tickets
        for this customer that are still open.
        """
        try:
            cursor = self._store._conn.execute(
                """
                SELECT COUNT(*) FROM tickets t
                INNER JOIN feedback_ticket_link ftl ON ftl.ticket_id = t.ticket_id
                INNER JOIN feedback f ON f.feedback_id = ftl.feedback_id
                WHERE f.customer_id = ?
                AND t.ticket_phase IN ('new', 'triaged', 'routed', 'in_progress', 'waiting')
                """,
                (customer_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0
        except Exception as exc:
            logger.warning(
                "Failed to count open tickets for customer %s: %s",
                customer_id,
                exc,
            )
            return 0

    def _find_most_recent_open_ticket_for_cluster(
        self, cluster_id: str
    ) -> Optional[dict]:
        """Find the most recently updated open ticket for a cluster.

        Returns a dict with ticket_id and assigned_department, or None.
        """
        try:
            cursor = self._store._conn.execute(
                """
                SELECT ticket_id, assigned_department, updated_at
                FROM tickets
                WHERE linked_cluster_id = ?
                AND ticket_phase IN ('new', 'triaged', 'routed', 'in_progress', 'waiting')
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (cluster_id,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "ticket_id": row[0],
                    "assigned_department": row[1],
                    "updated_at": row[2],
                }
            return None
        except Exception as exc:
            logger.warning(
                "Failed to find open ticket for cluster %s: %s",
                cluster_id,
                exc,
            )
            return None

    def _are_all_cluster_tickets_resolved(self, cluster_id: str) -> bool:
        """Check if all tickets for a cluster are resolved/closed/auto_closed.

        Returns True if the cluster has at least one ticket AND all tickets
        are in a terminal phase. Returns False if no tickets exist or any
        ticket is still open.
        """
        try:
            # Count total tickets for this cluster
            cursor = self._store._conn.execute(
                "SELECT COUNT(*) FROM tickets WHERE linked_cluster_id = ?",
                (cluster_id,),
            )
            total = cursor.fetchone()[0]
            if total == 0:
                return False

            # Count tickets NOT in resolved/closed/auto_closed
            cursor = self._store._conn.execute(
                """
                SELECT COUNT(*) FROM tickets
                WHERE linked_cluster_id = ?
                AND ticket_phase NOT IN ('resolved', 'closed', 'auto_closed')
                """,
                (cluster_id,),
            )
            open_count = cursor.fetchone()[0]
            return open_count == 0
        except Exception as exc:
            logger.warning(
                "Failed to check cluster ticket status for %s: %s",
                cluster_id,
                exc,
            )
            return False


__all__ = [
    "DecisionEngine",
    "LEGAL_KEYWORDS",
    "VIRAL_ENGAGEMENT_THRESHOLD",
    "SOCIAL_ENGAGEMENT_OVERRIDE_THRESHOLD",
    "THEME_TO_DEPARTMENT",
    "INTENT_TO_DEPARTMENT",
    "FAQ_TOPICS",
]
