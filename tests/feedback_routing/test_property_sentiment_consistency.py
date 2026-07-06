"""Property-based test for sentiment label-score consistency.

# Feature: nlp-feedback-routing, Property 5

**Validates: Requirements 4.5**

Property 5: Sentiment Label-Score Consistency — For any sentiment_score in
[-1.0, +1.0], the assigned sentiment_label SHALL be "positive" when score > 0.2,
"negative" when score < -0.2, and "neutral" when -0.2 <= score <= 0.2 —
regardless of what the underlying model returns.
"""

from __future__ import annotations

from hypothesis import given, settings

from nlp_processing.enrichment.sentiment_routing import _enforce_label_consistency
from tests.feedback_routing.strategies import sentiment_scores


@given(score=sentiment_scores())
@settings(max_examples=100)
def test_sentiment_label_score_consistency(score: float) -> None:
    """Verify label assignment: > 0.2 → positive, < -0.2 → negative, else neutral.

    # Feature: nlp-feedback-routing, Property 5
    **Validates: Requirements 4.5**
    """
    label = _enforce_label_consistency(score)

    if score > 0.2:
        assert label == "positive", (
            f"Expected 'positive' for score {score}, got '{label}'"
        )
    elif score < -0.2:
        assert label == "negative", (
            f"Expected 'negative' for score {score}, got '{label}'"
        )
    else:
        assert label == "neutral", (
            f"Expected 'neutral' for score {score}, got '{label}'"
        )
