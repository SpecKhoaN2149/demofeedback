# Feature: nlp-feedback-routing, Property 14
"""Property-based test for Cluster Sentiment Trend Computation.

**Validates: Requirements 22.3, 22.4**

Property 14: For any cluster with 20 or more feedback records, the
sentiment_trend SHALL be "improving" when the average sentiment_score of the
10 most recent records exceeds the average of the 10 oldest by more than 0.1,
"deteriorating" when the oldest average exceeds the recent by more than 0.1,
and "stable" otherwise. For any cluster with fewer than 20 records, the
sentiment_trend SHALL be "stable".
"""

from __future__ import annotations

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from nlp_processing.trends.feedback_trends import FeedbackRecord, TrendDetector


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

def _make_feedback_record(
    index: int, sentiment_score: float, base_timestamp: str = "2024-06-01T00:00:00Z"
) -> FeedbackRecord:
    """Create a FeedbackRecord with a deterministic processed_at timestamp.

    Records are spaced 1 hour apart so sorting by processed_at yields a
    predictable order.
    """
    # Pad the hour so that lexicographic sort on ISO strings == chronological sort
    day = index // 24
    hour = index % 24
    timestamp = f"2024-06-{1 + day:02d}T{hour:02d}:00:00Z"
    return FeedbackRecord(
        feedback_id=f"fb-{index:04d}",
        theme_primary="billing",
        sentiment_score=sentiment_score,
        cluster_id="cluster-001",
        processed_at=timestamp,
    )


@st.composite
def improving_cluster_records(draw: st.DrawFn) -> list[FeedbackRecord]:
    """Generate a cluster with >= 20 records where recent avg > oldest avg + 0.1."""
    n = draw(st.integers(min_value=20, max_value=50))

    # Oldest 10: sentiment in [-1.0, 0.0] range (low sentiment)
    oldest_scores = [
        draw(st.floats(min_value=-1.0, max_value=0.0, allow_nan=False, allow_infinity=False))
        for _ in range(10)
    ]
    oldest_avg = sum(oldest_scores) / 10.0

    # Recent 10: sentiment must have avg > oldest_avg + 0.1
    # Generate scores that guarantee the improving condition
    min_recent = oldest_avg + 0.15  # give some margin above 0.1 threshold
    min_recent = max(min_recent, -1.0)
    min_recent = min(min_recent, 1.0)

    # If min_recent > 1.0, it's impossible to be improving — skip
    assume(min_recent <= 1.0)

    recent_scores = [
        draw(st.floats(min_value=min_recent, max_value=1.0, allow_nan=False, allow_infinity=False))
        for _ in range(10)
    ]

    # Middle records: any valid sentiment
    middle_count = n - 20
    middle_scores = [
        draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False))
        for _ in range(middle_count)
    ]

    # Build records: oldest first, then middle, then recent
    all_scores = oldest_scores + middle_scores + recent_scores
    records = [_make_feedback_record(i, score) for i, score in enumerate(all_scores)]

    # Verify the improving condition holds
    actual_oldest_avg = sum(oldest_scores) / 10.0
    actual_recent_avg = sum(recent_scores) / 10.0
    assume(actual_recent_avg > actual_oldest_avg + 0.1)

    return records


@st.composite
def deteriorating_cluster_records(draw: st.DrawFn) -> list[FeedbackRecord]:
    """Generate a cluster with >= 20 records where oldest avg > recent avg + 0.1."""
    n = draw(st.integers(min_value=20, max_value=50))

    # Oldest 10: sentiment in [0.0, 1.0] range (high sentiment)
    oldest_scores = [
        draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
        for _ in range(10)
    ]
    oldest_avg = sum(oldest_scores) / 10.0

    # Recent 10: sentiment must have avg < oldest_avg - 0.1
    max_recent = oldest_avg - 0.15  # give some margin below -0.1 threshold
    max_recent = min(max_recent, 1.0)
    max_recent = max(max_recent, -1.0)

    # If max_recent < -1.0, it's impossible — skip
    assume(max_recent >= -1.0)

    recent_scores = [
        draw(st.floats(min_value=-1.0, max_value=max_recent, allow_nan=False, allow_infinity=False))
        for _ in range(10)
    ]

    # Middle records: any valid sentiment
    middle_count = n - 20
    middle_scores = [
        draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False))
        for _ in range(middle_count)
    ]

    # Build records: oldest first, then middle, then recent
    all_scores = oldest_scores + middle_scores + recent_scores
    records = [_make_feedback_record(i, score) for i, score in enumerate(all_scores)]

    # Verify the deteriorating condition holds
    actual_oldest_avg = sum(oldest_scores) / 10.0
    actual_recent_avg = sum(recent_scores) / 10.0
    assume(actual_oldest_avg > actual_recent_avg + 0.1)

    return records


@st.composite
def stable_cluster_records(draw: st.DrawFn) -> list[FeedbackRecord]:
    """Generate a cluster with >= 20 records where |recent avg - oldest avg| <= 0.1."""
    n = draw(st.integers(min_value=20, max_value=50))

    # Use a fixed base score and generate all records near it
    base_score = draw(st.floats(min_value=-0.8, max_value=0.8, allow_nan=False, allow_infinity=False))

    # All scores within a tight band so averages are within 0.1
    all_scores = [
        draw(st.floats(
            min_value=max(-1.0, base_score - 0.04),
            max_value=min(1.0, base_score + 0.04),
            allow_nan=False,
            allow_infinity=False,
        ))
        for _ in range(n)
    ]

    records = [_make_feedback_record(i, score) for i, score in enumerate(all_scores)]

    # Verify the stable condition holds
    sorted_records = sorted(records, key=lambda r: r.processed_at)
    oldest_avg = sum(r.sentiment_score for r in sorted_records[:10]) / 10.0
    recent_avg = sum(r.sentiment_score for r in sorted_records[-10:]) / 10.0
    diff = recent_avg - oldest_avg
    assume(abs(diff) <= 0.1)

    return records


@st.composite
def small_cluster_records(draw: st.DrawFn) -> list[FeedbackRecord]:
    """Generate a cluster with fewer than 20 records (any sentiment scores)."""
    n = draw(st.integers(min_value=0, max_value=19))
    scores = [
        draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False))
        for _ in range(n)
    ]
    return [_make_feedback_record(i, score) for i, score in enumerate(scores)]


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------

detector = TrendDetector()


@given(records=improving_cluster_records())
@settings(max_examples=100)
def test_improving_trend_detected(records: list[FeedbackRecord]) -> None:
    """Clusters with recent avg > oldest avg + 0.1 get 'improving' trend.

    **Validates: Requirements 22.3**
    """
    result = detector.compute_sentiment_trend(records)
    assert result == "improving", (
        f"Expected 'improving' but got '{result}'. "
        f"Records count: {len(records)}"
    )


@given(records=deteriorating_cluster_records())
@settings(max_examples=100)
def test_deteriorating_trend_detected(records: list[FeedbackRecord]) -> None:
    """Clusters with oldest avg > recent avg + 0.1 get 'deteriorating' trend.

    **Validates: Requirements 22.3**
    """
    result = detector.compute_sentiment_trend(records)
    assert result == "deteriorating", (
        f"Expected 'deteriorating' but got '{result}'. "
        f"Records count: {len(records)}"
    )


@given(records=stable_cluster_records())
@settings(max_examples=100)
def test_stable_trend_when_difference_within_threshold(records: list[FeedbackRecord]) -> None:
    """Clusters with |recent avg - oldest avg| <= 0.1 get 'stable' trend.

    **Validates: Requirements 22.3**
    """
    result = detector.compute_sentiment_trend(records)
    assert result == "stable", (
        f"Expected 'stable' but got '{result}'. "
        f"Records count: {len(records)}"
    )


@given(records=small_cluster_records())
@settings(max_examples=100)
def test_small_cluster_always_stable(records: list[FeedbackRecord]) -> None:
    """Clusters with fewer than 20 records always get 'stable' trend.

    **Validates: Requirements 22.4**
    """
    assert len(records) < 20, f"Expected < 20 records, got {len(records)}"
    result = detector.compute_sentiment_trend(records)
    assert result == "stable", (
        f"Expected 'stable' for cluster with {len(records)} records "
        f"(< 20 threshold) but got '{result}'"
    )
