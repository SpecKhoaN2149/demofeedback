"""Triage_Engine pure decision core.

This module holds the deterministic, side-effect-free heart of the triage step:
given the NLP-derived attributes of a Feedback record, it decides whether the
feedback requires action, needs no action, or must be routed to an admin for a
manual triage decision.

The persistence wrapper ``run_triage(feedback_id)`` (which loads a feedback row,
calls :func:`decide`, and writes the result plus any ticket linkage) is a
separate concern implemented in task 3.4. This file intentionally contains only
the pure core so it can be unit- and property-tested without a database or the
Gemini pipeline.

Design reference: .kiro/specs/feedback-triage-ticketing/design.md
    -> "Components and Interfaces" -> Triage_Engine
Requirements: 3.1, 3.5, 3.9
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids import cycles at runtime
    from app.services.feedback_store import FeedbackStore
    from app.services.ticketing_pipeline import TicketingPipeline

# Confidence-band thresholds. Kept as module constants (env-overridable) so the
# "confident" region for automated decisions is explicit and testable.
ACTION_SEVERITY_THRESHOLD = int(os.environ.get("TRIAGE_ACTION_SEVERITY_THRESHOLD", "3"))
NO_ACTION_SEVERITY_MAX = int(os.environ.get("TRIAGE_NO_ACTION_SEVERITY_MAX", "2"))


@dataclass(frozen=True)
class TriageInput:
    """The NLP-derived attributes the decision core reasons over."""

    enrichment_status: str            # completed | failed | timeout | pending
    sentiment: str | None             # positive | neutral | negative | None
    severity_score: int | None        # typically 1..5, may be None
    themes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TriageDecision:
    """The result of an automated triage evaluation."""

    outcome: str | None               # "action_required" | "no_action" | None (=> needs review)
    needs_review: bool
    decision_source: str              # always "automated" for this engine


def decide(inp: TriageInput) -> TriageDecision:
    """Decide the triage outcome for a single Feedback record.

    Pure, total, and deterministic: returns exactly one :class:`TriageDecision`
    for every possible input, performs no I/O, and always reports
    ``decision_source="automated"``.

    The four-branch rule (design "Automated decision rule"):

    1. Enrichment did not complete (failed/timeout/pending) -> cannot triage
       without analysis, so route to review. (Requirement 3.9)
    2. Confident negative + high severity -> action_required.
    3. Confident positive/neutral + low severity -> no_action.
    4. Anything ambiguous (negative-but-low-severity, missing severity or
       sentiment, borderline) -> route to review. (Requirement 3.5)
    """
    # Branch 1: no completed analysis => cannot triage (Req 3.9 / 2.6 / 2.7).
    if inp.enrichment_status != "completed":
        return TriageDecision(outcome=None, needs_review=True, decision_source="automated")

    # Branch 2: confident action_required.
    if (
        inp.sentiment == "negative"
        and inp.severity_score is not None
        and inp.severity_score >= ACTION_SEVERITY_THRESHOLD
    ):
        return TriageDecision(
            outcome="action_required", needs_review=False, decision_source="automated"
        )

    # Branch 3: confident no_action.
    if (
        inp.sentiment in {"positive", "neutral"}
        and inp.severity_score is not None
        and inp.severity_score <= NO_ACTION_SEVERITY_MAX
    ):
        return TriageDecision(
            outcome="no_action", needs_review=False, decision_source="automated"
        )

    # Branch 4: ambiguous => route to admin review (Req 3.5).
    return TriageDecision(outcome=None, needs_review=True, decision_source="automated")


def run_triage(
    feedback_id: str | uuid.UUID,
    *,
    store: "FeedbackStore | None" = None,
    pipeline: "TicketingPipeline | None" = None,
) -> None:
    """Load a feedback record, decide its triage outcome, and persist the result.

    This is the impure persistence wrapper around the pure :func:`decide` core.
    It is invoked after enrichment reaches a terminal status (see
    ``services/enrichment.py``). Dependencies are injectable purely to make the
    wrapper testable; in production they default to fresh instances.

    Behavior (design "Persistence wrapper run_triage"):

    - Missing feedback → no-op.
    - ``action_required`` → create a Ticket (which links the feedback) and record
      ``triage_outcome="action_required"``, ``decision_source="automated"``,
      ``needs_review=False`` (Req 3.2, 5.3).
    - ``no_action`` → record ``triage_outcome="no_action"``, leave ``ticket_id``
      NULL (Req 3.3, 5.5).
    - needs review (outcome ``None``) → record ``needs_review=True``,
      ``decision_source="automated"``, outcome stays NULL (Req 3.5).
    - Any exception raised while triaging → route to admin review
      (``needs_review=True``) and return (Req 3.9).

    Args:
        feedback_id: The feedback record to triage.
        store: Optional :class:`FeedbackStore` (defaults to a new instance).
        pipeline: Optional :class:`TicketingPipeline` (defaults to a new instance).
    """
    # Local imports keep the pure decision core dependency-free and avoid an
    # import cycle with enrichment (which imports this module).
    from app.services.feedback_store import FeedbackStore
    from app.services.ticketing_pipeline import TicketingPipeline

    store = store if store is not None else FeedbackStore()
    pipeline = pipeline if pipeline is not None else TicketingPipeline()

    feedback = store.get(feedback_id)
    if feedback is None:
        # Nothing to triage.
        return

    enrichment_result = feedback.enrichment_result
    severity_score = (
        enrichment_result.severity_score if enrichment_result is not None else None
    )
    themes: list[str] = []
    if enrichment_result is not None:
        themes = [
            name
            for t in enrichment_result.themes
            if (name := (t.get("theme") if isinstance(t, dict) else None))
        ]

    inp = TriageInput(
        enrichment_status=feedback.enrichment_status,
        sentiment=feedback.sentiment,
        severity_score=severity_score,
        themes=themes,
    )

    decision = decide(inp)

    try:
        if decision.outcome == "action_required":
            issue_category = themes[0] if themes else "general"
            pipeline.create_ticket(
                feedback_id=str(feedback_id),
                issue_category=issue_category,
                description=feedback.text[:5000],
            )
            # create_ticket already links the feedback to the new ticket.
            store.set_triage(
                feedback_id,
                "action_required",
                decision_source="automated",
                needs_review=False,
            )
        elif decision.outcome == "no_action":
            store.set_triage(
                feedback_id,
                "no_action",
                decision_source="automated",
                needs_review=False,
            )
        else:
            # Ambiguous / non-terminal enrichment → route to admin review.
            store.set_triage(
                feedback_id,
                None,
                decision_source="automated",
                needs_review=True,
            )
    except Exception:
        # Any failure while triaging must not lose the feedback: route to review.
        store.set_triage(
            feedback_id,
            None,
            decision_source="automated",
            needs_review=True,
        )
        return
