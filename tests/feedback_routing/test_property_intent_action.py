# Feature: nlp-feedback-routing, Property 9
"""Property test for Intent to Requires-Action Mapping.

**Property 9: Intent to Requires-Action Mapping** — For any intent
classification result, requires_action SHALL be true when intent is in
{complaint, request_for_help, outage_report, billing_dispute,
cancellation_risk}, and false when intent is in {feature_suggestion, praise,
unclassified}.

**Validates: Requirements 8.4, 8.5**
"""

from __future__ import annotations

from hypothesis import given, settings

from nlp_processing.enrichment.intent_classifier import (
    ACTION_REQUIRED_INTENTS,
    NO_ACTION_INTENTS,
    _determine_requires_action,
)
from tests.feedback_routing.strategies import intent_types

# The expected action-required intents per Requirements 8.4.
EXPECTED_ACTION_REQUIRED = frozenset(
    {
        "complaint",
        "request_for_help",
        "outage_report",
        "billing_dispute",
        "cancellation_risk",
    }
)

# The expected no-action intents per Requirements 8.5.
EXPECTED_NO_ACTION = frozenset(
    {
        "feature_suggestion",
        "praise",
        "unclassified",
    }
)


@settings(max_examples=100)
@given(intent=intent_types())
def test_action_required_intents_map_to_true(intent: str) -> None:
    """Intents in the action-required set produce requires_action=True.

    Validates: Requirements 8.4
    """
    if intent in EXPECTED_ACTION_REQUIRED:
        result = _determine_requires_action(intent)
        assert result is True, (
            f"Expected requires_action=True for intent {intent!r}, got {result}"
        )


@settings(max_examples=100)
@given(intent=intent_types())
def test_no_action_intents_map_to_false(intent: str) -> None:
    """Intents in the no-action set produce requires_action=False.

    Validates: Requirements 8.5
    """
    if intent in EXPECTED_NO_ACTION:
        result = _determine_requires_action(intent)
        assert result is False, (
            f"Expected requires_action=False for intent {intent!r}, got {result}"
        )


@settings(max_examples=100)
@given(intent=intent_types())
def test_all_intents_covered_by_mapping(intent: str) -> None:
    """Every valid intent is in exactly one of the two mapping sets.

    This ensures no intent is unmapped — the union of action-required and
    no-action sets covers all valid intents.

    Validates: Requirements 8.4, 8.5
    """
    in_action = intent in EXPECTED_ACTION_REQUIRED
    in_no_action = intent in EXPECTED_NO_ACTION

    # Every intent must be in exactly one set.
    assert in_action or in_no_action, (
        f"Intent {intent!r} is not in either the action-required or no-action set"
    )
    assert not (in_action and in_no_action), (
        f"Intent {intent!r} is in both the action-required and no-action sets"
    )

    # Verify the function agrees with the set membership.
    result = _determine_requires_action(intent)
    if in_action:
        assert result is True, (
            f"Intent {intent!r} is action-required but _determine_requires_action "
            f"returned {result}"
        )
    else:
        assert result is False, (
            f"Intent {intent!r} is no-action but _determine_requires_action "
            f"returned {result}"
        )
