# Feature: nlp-feedback-routing, Property 13
"""Property test for Ticket Phase Transition Validity.

**Property 13: Ticket Phase Transition Validity** — For any ticket in phase P
and any attempted transition to phase Q, the transition SHALL be accepted if and
only if (P, Q) is in the valid transition set. Transitions from "closed" or
"auto_closed" SHALL always be rejected.

**Validates: Requirements 15.1, 15.2, 15.7**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from hypothesis import given, settings

from nlp_processing.models.feedback_routing import Ticket
from nlp_processing.persistence.feedback_store import (
    FeedbackStore,
    InvalidTransitionError,
)
from tests.feedback_routing.strategies import (
    TERMINAL_PHASES,
    VALID_TRANSITIONS,
    invalid_ticket_phase_pairs,
    valid_ticket_phase_pairs,
)


def _make_ticket(phase: str, resolution_type: str | None = None) -> Ticket:
    """Create a Ticket with the given phase for testing."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return Ticket(
        ticket_id=str(uuid.uuid4()),
        ticket_phase=phase,
        priority_level="medium",
        assigned_department="Customer_Care",
        created_at=now,
        updated_at=now,
        resolution_type=resolution_type,
    )


def _setup_store_with_ticket(phase: str) -> tuple[FeedbackStore, str]:
    """Create a FeedbackStore with a ticket in the given phase.

    For phases that require resolution_type (resolved), the ticket is
    pre-configured accordingly.
    """
    store = FeedbackStore(":memory:")

    # If the ticket needs to be in a phase that requires resolution_type set,
    # provide one. The 'resolved' phase requires resolution_type for transition
    # *to* it, but a ticket can be inserted directly in any phase.
    resolution_type = None
    if phase in ("resolved", "closed"):
        resolution_type = "resolved_by_agent"

    ticket = _make_ticket(phase, resolution_type=resolution_type)
    store.insert_ticket(ticket)
    return store, ticket.ticket_id


@settings(max_examples=100)
@given(pair=valid_ticket_phase_pairs())
def test_valid_transitions_are_accepted(pair: tuple[str, str]) -> None:
    """Valid (current_phase, next_phase) pairs must be accepted.

    Validates: Requirements 15.1
    """
    current_phase, next_phase = pair

    # For transitions to 'resolved', the ticket needs a resolution_type set
    resolution_type = None
    if next_phase == "resolved":
        resolution_type = "resolved_by_agent"

    store = FeedbackStore(":memory:")
    ticket = _make_ticket(current_phase, resolution_type=resolution_type)
    store.insert_ticket(ticket)

    # The transition should succeed without raising
    store.transition_ticket_phase(ticket.ticket_id, next_phase, "test_actor")

    # Verify the ticket is now in the new phase
    cursor = store._conn.execute(
        "SELECT ticket_phase FROM tickets WHERE ticket_id = ?",
        (ticket.ticket_id,),
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == next_phase


@settings(max_examples=100)
@given(pair=invalid_ticket_phase_pairs())
def test_invalid_transitions_are_rejected(pair: tuple[str, str]) -> None:
    """Invalid (current_phase, next_phase) pairs must be rejected.

    Validates: Requirements 15.2
    """
    current_phase, next_phase = pair

    store, ticket_id = _setup_store_with_ticket(current_phase)

    # The transition should raise InvalidTransitionError
    try:
        store.transition_ticket_phase(ticket_id, next_phase, "test_actor")
        assert False, (
            f"Expected InvalidTransitionError for transition "
            f"({current_phase!r} -> {next_phase!r}) but none was raised."
        )
    except InvalidTransitionError as exc:
        # Verify the error reports the correct current phase
        assert exc.current_phase == current_phase
        assert exc.requested_phase == next_phase

    # Verify the ticket phase is unchanged
    cursor = store._conn.execute(
        "SELECT ticket_phase FROM tickets WHERE ticket_id = ?",
        (ticket_id,),
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == current_phase


@settings(max_examples=100)
@given(pair=valid_ticket_phase_pairs())
def test_terminal_phases_have_no_valid_transitions(pair: tuple[str, str]) -> None:
    """Transitions from 'closed' and 'auto_closed' are always rejected.

    This test verifies that terminal phases cannot transition to ANY phase,
    including phases that would be valid next steps for other phases.

    Validates: Requirements 15.7
    """
    _, next_phase = pair  # Use valid next_phases as targets

    for terminal_phase in TERMINAL_PHASES:
        store, ticket_id = _setup_store_with_ticket(terminal_phase)

        try:
            store.transition_ticket_phase(ticket_id, next_phase, "test_actor")
            assert False, (
                f"Expected InvalidTransitionError for transition from "
                f"terminal phase {terminal_phase!r} to {next_phase!r} "
                f"but none was raised."
            )
        except InvalidTransitionError as exc:
            assert exc.current_phase == terminal_phase
            assert exc.requested_phase == next_phase
            # Terminal phases should have no valid next phases
            assert exc.valid_phases == []

        # Verify the ticket phase is unchanged
        cursor = store._conn.execute(
            "SELECT ticket_phase FROM tickets WHERE ticket_id = ?",
            (ticket_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == terminal_phase
