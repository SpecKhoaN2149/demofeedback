"""Property-based test for priority score-level range consistency.

# Feature: nlp-feedback-routing, Property 8

**Validates: Requirements 7.8**

Property 8: Priority Score-Level Range Consistency — For any computed priority
result, the numeric priority_score SHALL fall within the defined range for the
assigned priority_level: 0.75–1.0 for "critical", 0.50–0.74 for "high",
0.25–0.49 for "medium", 0.0–0.24 for "low".
"""

from __future__ import annotations

from hypothesis import given, settings

from nlp_processing.enrichment.priority_scorer import PriorityScorer
from tests.feedback_routing.strategies import (
    canonical_feedback_records,
    feedback_analysis_records,
)

# Priority score ranges per level (Req 7.8).
EXPECTED_RANGES: dict[str, tuple[float, float]] = {
    "critical": (0.75, 1.0),
    "high": (0.50, 0.74),
    "medium": (0.25, 0.49),
    "low": (0.0, 0.24),
}


@given(
    feedback=canonical_feedback_records(),
    analysis=feedback_analysis_records(),
)
@settings(max_examples=100)
def test_priority_score_within_level_range(
    feedback,
    analysis,
) -> None:
    """Verify priority_score falls within the correct range for priority_level.

    # Feature: nlp-feedback-routing, Property 8
    **Validates: Requirements 7.8**
    """
    scorer = PriorityScorer()
    result = scorer.score(feedback, analysis)

    level = result.priority_level
    score = result.priority_score

    assert level in EXPECTED_RANGES, (
        f"Unexpected priority_level '{level}'"
    )

    min_score, max_score = EXPECTED_RANGES[level]
    assert min_score <= score <= max_score, (
        f"priority_score {score} out of range for level '{level}': "
        f"expected [{min_score}, {max_score}]"
    )
