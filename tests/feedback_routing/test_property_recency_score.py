"""Property-based test for recency score formula correctness.

# Feature: nlp-feedback-routing, Property 1

**Validates: Requirements 1.2**

Property 1: Recency Score Formula Correctness — For any pair of timestamps
(created_at_original, ingested_at) where ingested_at >= created_at_original,
the computed recency_score SHALL equal max(0.0, 1.0 - (elapsed_hours / 720))
and the result SHALL always be in [0.0, 1.0].
"""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import given, settings

from nlp_processing.ingestion.social_listener import SocialListener
from tests.feedback_routing.strategies import valid_timestamp_pairs


@given(timestamp_pair=valid_timestamp_pairs())
@settings(max_examples=100)
def test_recency_score_formula_correctness(timestamp_pair: tuple[str, str]) -> None:
    """Verify recency score equals max(0.0, 1.0 - (elapsed_hours / 720)) and is in [0.0, 1.0].

    # Feature: nlp-feedback-routing, Property 1
    **Validates: Requirements 1.2**
    """
    created_at_original, ingested_at = timestamp_pair

    # Compute score using the implementation under test
    score = SocialListener._compute_recency_score(created_at_original, ingested_at)

    # Parse timestamps to compute expected score independently
    created_dt = datetime.fromisoformat(created_at_original.replace("Z", "+00:00"))
    ingested_dt = datetime.fromisoformat(ingested_at.replace("Z", "+00:00"))

    elapsed_seconds = (ingested_dt - created_dt).total_seconds()
    # Strategy guarantees ingested_at >= created_at_original, but handle edge cases
    if elapsed_seconds < 0:
        elapsed_seconds = 0

    elapsed_hours = elapsed_seconds / 3600.0
    expected_score = max(0.0, 1.0 - (elapsed_hours / 720))

    # Verify the computed score matches the expected formula
    assert score == expected_score, (
        f"Score mismatch: got {score}, expected {expected_score} "
        f"(elapsed_hours={elapsed_hours:.4f}, "
        f"created_at={created_at_original}, ingested_at={ingested_at})"
    )

    # Verify score is always within [0.0, 1.0]
    assert 0.0 <= score <= 1.0, (
        f"Score {score} is outside [0.0, 1.0] range "
        f"(created_at={created_at_original}, ingested_at={ingested_at})"
    )
