# Feature: nlp-feedback-routing, Property 11
"""Property test for Department Assignment Mapping.

**Property 11: Department Assignment Mapping** — For any (primary_theme,
intent, source_type, engagement_metrics) combination, the Decision_Engine SHALL
assign the Routing_Department according to the defined mapping: social
engagement > 100 overrides to Social_Media_Care; then primary_theme takes
precedence over intent; unclassified theme with no mapped intent defaults to
Customer_Care.

**Validates: Requirements 13.3, 13.4, 13.6**
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
    THEME_TO_DEPARTMENT,
    INTENT_TO_DEPARTMENT,
    SOCIAL_ENGAGEMENT_OVERRIDE_THRESHOLD,
)
from tests.feedback_routing.strategies import (
    theme_categories,
    intent_types,
    feedback_routing_settings,
    THEME_CATEGORY_VALUES,
    INTENT_TYPE_VALUES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_engine() -> DecisionEngine:
    """Create a DecisionEngine with an in-memory store."""
    store = FeedbackStore(":memory:")
    return DecisionEngine(store)


def _make_feedback(
    source_type: str = "widget",
    engagement_total: int = 0,
) -> CanonicalFeedback:
    """Create a CanonicalFeedback record with controlled engagement."""
    metadata: dict = {}
    if source_type == "social":
        # Distribute engagement across metrics
        metadata["engagement_metrics"] = {
            "likes": engagement_total,
            "replies": 0,
            "reposts": 0,
        }
    return CanonicalFeedback(
        feedback_id=str(uuid.uuid4()),
        source_type=source_type,
        original_source_id=str(uuid.uuid4()),
        cleaned_text="Test feedback for department mapping property test.",
        detected_language="en",
        ingested_at=_now_iso(),
        duplicate_count=0,
        profanity_detected=False,
        metadata=metadata,
        processing_status="analyzed",
    )


def _make_analysis(
    theme_primary: str,
    intent: str,
) -> FeedbackAnalysis:
    """Create a FeedbackAnalysis with requires_action=True and priority medium.

    This ensures the create_ticket path is triggered so _determine_department
    is exercised.
    """
    return FeedbackAnalysis(
        feedback_id=str(uuid.uuid4()),
        sentiment_label="neutral",
        sentiment_score=0.0,
        priority_score=0.4,
        priority_level="medium",
        theme_primary=theme_primary,
        theme_secondary=None,
        intent=intent,
        cluster_id=None,
        requires_action=True,
        entities=[],
        processed_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Engagement values that exceed the Social_Media_Care override threshold
high_engagement = st.integers(
    min_value=SOCIAL_ENGAGEMENT_OVERRIDE_THRESHOLD + 1,
    max_value=5000,
)

# Engagement values at or below the threshold (no override)
low_engagement = st.integers(min_value=0, max_value=SOCIAL_ENGAGEMENT_OVERRIDE_THRESHOLD)


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    theme=theme_categories(),
    intent=intent_types(),
    engagement=high_engagement,
)
def test_social_engagement_override_takes_precedence(
    theme: str, intent: str, engagement: int
) -> None:
    """Social engagement > 100 overrides theme/intent mapping to Social_Media_Care.

    Validates: Requirements 13.4
    """
    engine = _make_engine()
    feedback = _make_feedback(source_type="social", engagement_total=engagement)
    analysis = _make_analysis(theme_primary=theme, intent=intent)

    department = engine._determine_department(feedback, analysis)

    assert department == "Social_Media_Care", (
        f"Expected Social_Media_Care for social engagement={engagement} "
        f"(theme={theme!r}, intent={intent!r}), got {department!r}"
    )


@settings(max_examples=100)
@given(
    theme=theme_categories(),
    intent=intent_types(),
    engagement=low_engagement,
)
def test_theme_precedence_over_intent(
    theme: str, intent: str, engagement: int
) -> None:
    """Theme mapping takes precedence over intent when both yield departments.

    When social engagement does NOT trigger override, and theme maps to a
    department, that department is assigned regardless of intent.

    Validates: Requirements 13.3
    """
    engine = _make_engine()
    # Use widget source or social with low engagement to avoid override
    feedback = _make_feedback(source_type="widget", engagement_total=0)
    analysis = _make_analysis(theme_primary=theme, intent=intent)

    department = engine._determine_department(feedback, analysis)

    # If theme is in the mapping, theme's department wins
    if theme in THEME_TO_DEPARTMENT:
        expected = THEME_TO_DEPARTMENT[theme]
        assert department == expected, (
            f"Theme {theme!r} should map to {expected!r}, got {department!r} "
            f"(intent={intent!r})"
        )
    # If theme is NOT in mapping but intent is, intent's department wins
    elif intent in INTENT_TO_DEPARTMENT:
        expected = INTENT_TO_DEPARTMENT[intent]
        assert department == expected, (
            f"Theme {theme!r} not mapped; intent {intent!r} should map to "
            f"{expected!r}, got {department!r}"
        )
    # Neither mapped → Customer_Care fallback
    else:
        assert department == "Customer_Care", (
            f"Theme {theme!r} and intent {intent!r} both unmapped; expected "
            f"Customer_Care fallback, got {department!r}"
        )


@settings(max_examples=100)
@given(intent=intent_types())
def test_customer_care_fallback_unmapped_theme_and_intent(intent: str) -> None:
    """Unclassified theme with no mapped intent defaults to Customer_Care.

    Validates: Requirements 13.6
    """
    # Only test intents that are NOT in INTENT_TO_DEPARTMENT
    assume(intent not in INTENT_TO_DEPARTMENT)

    engine = _make_engine()
    # Use a theme that is NOT in THEME_TO_DEPARTMENT
    # "unclassified" is not in the mapping, representing the fallback case
    feedback = _make_feedback(source_type="widget", engagement_total=0)
    analysis = _make_analysis(theme_primary="unclassified", intent=intent)

    department = engine._determine_department(feedback, analysis)

    assert department == "Customer_Care", (
        f"Expected Customer_Care for unmapped theme='unclassified' and "
        f"unmapped intent={intent!r}, got {department!r}"
    )


@settings(max_examples=100)
@given(
    theme=theme_categories(),
    intent=intent_types(),
    engagement=low_engagement,
)
def test_social_low_engagement_no_override(
    theme: str, intent: str, engagement: int
) -> None:
    """Social source with engagement <= 100 does NOT override to Social_Media_Care.

    The department should follow normal theme/intent mapping rules.

    Validates: Requirements 13.4
    """
    engine = _make_engine()
    feedback = _make_feedback(source_type="social", engagement_total=engagement)
    analysis = _make_analysis(theme_primary=theme, intent=intent)

    department = engine._determine_department(feedback, analysis)

    # Should NOT be Social_Media_Care (unless theme or intent happens to map there,
    # but Social_Media_Care is not in THEME_TO_DEPARTMENT or INTENT_TO_DEPARTMENT)
    # So the result should follow normal precedence rules
    if theme in THEME_TO_DEPARTMENT:
        expected = THEME_TO_DEPARTMENT[theme]
    elif intent in INTENT_TO_DEPARTMENT:
        expected = INTENT_TO_DEPARTMENT[intent]
    else:
        expected = "Customer_Care"

    assert department == expected, (
        f"Social source with engagement={engagement} (<=100) should NOT override. "
        f"Expected {expected!r} for theme={theme!r}, intent={intent!r}, "
        f"got {department!r}"
    )
