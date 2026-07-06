"""Unit tests for the feedback routing TrendDetector.

Validates Requirements 22.1, 22.2, 22.3, 22.4, 22.5, 22.6, 22.7, 22.8:
- Volume spike detection (theme volume > 2x rolling 7-day average)
- Sentiment trend computation for clusters with 20+ records
- Sentiment trend "stable" for clusters with < 20 records
- Cluster lifecycle evaluation (active → monitoring → resolved)
- Theme frequency distribution over configurable window
- New cluster emergence rate tracking
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nlp_processing.trends.feedback_trends import (
    ClusterInfo,
    ClusterLifecycleChange,
    FeedbackRecord,
    ThemeFrequency,
    TrendDetector,
    TrendResult,
    VolumeSpikeEvent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    feedback_id: str = "fb-1",
    theme_primary: str = "billing",
    sentiment_score: float = 0.0,
    cluster_id: str | None = None,
    processed_at: str = "2024-01-15T12:00:00Z",
) -> FeedbackRecord:
    """Create a minimal FeedbackRecord for testing."""
    return FeedbackRecord(
        feedback_id=feedback_id,
        theme_primary=theme_primary,
        sentiment_score=sentiment_score,
        cluster_id=cluster_id,
        processed_at=processed_at,
    )


def _make_cluster(
    cluster_id: str = "cluster-1",
    status: str = "active",
    first_seen_at: str = "2024-01-01T00:00:00Z",
    last_seen_at: str = "2024-01-15T00:00:00Z",
    volume_count: int = 5,
) -> ClusterInfo:
    """Create a minimal ClusterInfo for testing."""
    return ClusterInfo(
        cluster_id=cluster_id,
        status=status,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
        volume_count=volume_count,
    )


# ---------------------------------------------------------------------------
# TrendDetector initialization
# ---------------------------------------------------------------------------


class TestTrendDetectorInit:
    """Tests for TrendDetector initialization and configuration."""

    def test_default_window_days(self):
        detector = TrendDetector()
        assert detector.window_days == 7

    def test_custom_window_days(self):
        detector = TrendDetector(window_days=30)
        assert detector.window_days == 30

    def test_min_window_days(self):
        detector = TrendDetector(window_days=1)
        assert detector.window_days == 1

    def test_max_window_days(self):
        detector = TrendDetector(window_days=90)
        assert detector.window_days == 90

    def test_invalid_window_days_below(self):
        with pytest.raises(ValueError, match="window_days must be between 1 and 90"):
            TrendDetector(window_days=0)

    def test_invalid_window_days_above(self):
        with pytest.raises(ValueError, match="window_days must be between 1 and 90"):
            TrendDetector(window_days=91)


# ---------------------------------------------------------------------------
# Volume Spike Detection (Req 22.1, 22.2)
# ---------------------------------------------------------------------------


class TestVolumeSpikeDetection:
    """Tests for volume spike detection."""

    def test_spike_detected_when_exceeds_2x_average(self):
        """Volume > 2x rolling 7-day average triggers a spike."""
        detector = TrendDetector()
        # 7 days of normal volume (5 each) + 1 day with spike (15)
        daily_volumes = {"billing": [5, 5, 5, 5, 5, 5, 5, 15]}
        eval_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        spikes = detector.detect_volume_spikes(
            daily_volumes, evaluation_time=eval_time
        )

        assert len(spikes) == 1
        assert spikes[0].theme == "billing"
        assert spikes[0].current_volume == 15
        assert spikes[0].rolling_average == 5.0
        assert spikes[0].detection_timestamp == "2024-01-15T12:00:00Z"

    def test_no_spike_when_volume_within_threshold(self):
        """Volume <= 2x rolling average does not trigger a spike."""
        detector = TrendDetector()
        # Average is 5, current is 10 (exactly 2x) — not > 2x
        daily_volumes = {"billing": [5, 5, 5, 5, 5, 5, 5, 10]}

        spikes = detector.detect_volume_spikes(daily_volumes)

        assert len(spikes) == 0

    def test_no_spike_with_insufficient_data(self):
        """Less than 8 data points (7 history + 1 current) skipped."""
        detector = TrendDetector()
        daily_volumes = {"billing": [5, 5, 5, 5, 5, 5, 100]}  # only 7

        spikes = detector.detect_volume_spikes(daily_volumes)

        assert len(spikes) == 0

    def test_no_spike_when_rolling_average_zero(self):
        """No spike reported when rolling average is zero."""
        detector = TrendDetector()
        daily_volumes = {"billing": [0, 0, 0, 0, 0, 0, 0, 5]}

        spikes = detector.detect_volume_spikes(daily_volumes)

        assert len(spikes) == 0

    def test_multiple_themes_spike_detection(self):
        """Spikes detected independently per theme."""
        detector = TrendDetector()
        eval_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        daily_volumes = {
            "billing": [5, 5, 5, 5, 5, 5, 5, 15],  # spike
            "outage": [3, 3, 3, 3, 3, 3, 3, 4],  # no spike
        }

        spikes = detector.detect_volume_spikes(
            daily_volumes, evaluation_time=eval_time
        )

        assert len(spikes) == 1
        assert spikes[0].theme == "billing"


# ---------------------------------------------------------------------------
# Sentiment Trend Computation (Req 22.3, 22.4)
# ---------------------------------------------------------------------------


class TestSentimentTrendComputation:
    """Tests for cluster sentiment trend computation."""

    def test_improving_trend(self):
        """Recent avg > oldest avg + 0.1 → improving."""
        detector = TrendDetector()
        # 10 oldest with score -0.5, 10 recent with score 0.5
        records = []
        for i in range(10):
            records.append(
                _make_record(
                    feedback_id=f"fb-old-{i}",
                    sentiment_score=-0.5,
                    processed_at=f"2024-01-{i+1:02d}T00:00:00Z",
                )
            )
        for i in range(10):
            records.append(
                _make_record(
                    feedback_id=f"fb-new-{i}",
                    sentiment_score=0.5,
                    processed_at=f"2024-01-{i+15:02d}T00:00:00Z",
                )
            )

        trend = detector.compute_sentiment_trend(records)
        assert trend == "improving"

    def test_deteriorating_trend(self):
        """Oldest avg > recent avg + 0.1 → deteriorating."""
        detector = TrendDetector()
        records = []
        for i in range(10):
            records.append(
                _make_record(
                    feedback_id=f"fb-old-{i}",
                    sentiment_score=0.5,
                    processed_at=f"2024-01-{i+1:02d}T00:00:00Z",
                )
            )
        for i in range(10):
            records.append(
                _make_record(
                    feedback_id=f"fb-new-{i}",
                    sentiment_score=-0.5,
                    processed_at=f"2024-01-{i+15:02d}T00:00:00Z",
                )
            )

        trend = detector.compute_sentiment_trend(records)
        assert trend == "deteriorating"

    def test_stable_trend_within_threshold(self):
        """Difference <= 0.1 → stable."""
        detector = TrendDetector()
        records = []
        for i in range(10):
            records.append(
                _make_record(
                    feedback_id=f"fb-old-{i}",
                    sentiment_score=0.0,
                    processed_at=f"2024-01-{i+1:02d}T00:00:00Z",
                )
            )
        for i in range(10):
            records.append(
                _make_record(
                    feedback_id=f"fb-new-{i}",
                    sentiment_score=0.05,
                    processed_at=f"2024-01-{i+15:02d}T00:00:00Z",
                )
            )

        trend = detector.compute_sentiment_trend(records)
        assert trend == "stable"

    def test_stable_for_less_than_20_records(self):
        """Clusters with < 20 records always get "stable"."""
        detector = TrendDetector()
        records = [
            _make_record(
                feedback_id=f"fb-{i}",
                sentiment_score=float(i) / 10.0,
                processed_at=f"2024-01-{i+1:02d}T00:00:00Z",
            )
            for i in range(19)
        ]

        trend = detector.compute_sentiment_trend(records)
        assert trend == "stable"

    def test_exactly_20_records(self):
        """Exactly 20 records should compute trend normally."""
        detector = TrendDetector()
        records = []
        for i in range(10):
            records.append(
                _make_record(
                    feedback_id=f"fb-old-{i}",
                    sentiment_score=-0.8,
                    processed_at=f"2024-01-{i+1:02d}T00:00:00Z",
                )
            )
        for i in range(10):
            records.append(
                _make_record(
                    feedback_id=f"fb-new-{i}",
                    sentiment_score=0.8,
                    processed_at=f"2024-01-{i+15:02d}T00:00:00Z",
                )
            )

        trend = detector.compute_sentiment_trend(records)
        assert trend == "improving"

    def test_boundary_exactly_0_1_diff_is_stable(self):
        """Exactly 0.1 difference means stable (not improving or deteriorating)."""
        detector = TrendDetector()
        records = []
        for i in range(10):
            records.append(
                _make_record(
                    feedback_id=f"fb-old-{i}",
                    sentiment_score=0.0,
                    processed_at=f"2024-01-{i+1:02d}T00:00:00Z",
                )
            )
        for i in range(10):
            records.append(
                _make_record(
                    feedback_id=f"fb-new-{i}",
                    sentiment_score=0.1,
                    processed_at=f"2024-01-{i+15:02d}T00:00:00Z",
                )
            )

        trend = detector.compute_sentiment_trend(records)
        assert trend == "stable"

    def test_compute_cluster_sentiment_trends(self):
        """Batch computation across multiple clusters."""
        detector = TrendDetector()
        cluster_a_records = [
            _make_record(
                feedback_id=f"fb-a-{i}",
                sentiment_score=-0.5 if i < 10 else 0.5,
                processed_at=f"2024-01-{i+1:02d}T00:00:00Z",
            )
            for i in range(20)
        ]
        cluster_b_records = [
            _make_record(feedback_id=f"fb-b-{i}", sentiment_score=0.0)
            for i in range(5)
        ]

        result = detector.compute_cluster_sentiment_trends(
            {"cluster-a": cluster_a_records, "cluster-b": cluster_b_records}
        )

        assert result["cluster-a"] == "improving"
        assert result["cluster-b"] == "stable"


# ---------------------------------------------------------------------------
# Cluster Lifecycle Evaluation (Req 22.6, 22.7, 22.8)
# ---------------------------------------------------------------------------


class TestClusterLifecycleEvaluation:
    """Tests for cluster lifecycle status transitions."""

    def test_active_to_monitoring_after_7_days(self):
        """Active cluster with >7 days no activity → monitoring."""
        detector = TrendDetector()
        eval_time = datetime(2024, 1, 25, 12, 0, 0, tzinfo=timezone.utc)
        cluster = _make_cluster(
            cluster_id="c-1",
            status="active",
            last_seen_at="2024-01-17T00:00:00Z",  # 8+ days before eval
        )

        changes = detector.evaluate_cluster_lifecycle(
            [cluster], evaluation_time=eval_time
        )

        assert len(changes) == 1
        assert changes[0].cluster_id == "c-1"
        assert changes[0].previous_status == "active"
        assert changes[0].new_status == "monitoring"

    def test_active_stays_active_within_7_days(self):
        """Active cluster with <=7 days no activity stays active."""
        detector = TrendDetector()
        eval_time = datetime(2024, 1, 20, 12, 0, 0, tzinfo=timezone.utc)
        cluster = _make_cluster(
            cluster_id="c-1",
            status="active",
            last_seen_at="2024-01-15T00:00:00Z",  # ~5 days
        )

        changes = detector.evaluate_cluster_lifecycle(
            [cluster], evaluation_time=eval_time
        )

        assert len(changes) == 0

    def test_monitoring_to_resolved_after_21_days(self):
        """Monitoring cluster with >21 days total no activity → resolved."""
        detector = TrendDetector()
        eval_time = datetime(2024, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
        cluster = _make_cluster(
            cluster_id="c-2",
            status="monitoring",
            last_seen_at="2024-01-15T00:00:00Z",  # 26 days before eval
        )

        changes = detector.evaluate_cluster_lifecycle(
            [cluster], evaluation_time=eval_time
        )

        assert len(changes) == 1
        assert changes[0].cluster_id == "c-2"
        assert changes[0].previous_status == "monitoring"
        assert changes[0].new_status == "resolved"

    def test_monitoring_stays_monitoring_within_21_days(self):
        """Monitoring cluster with <=21 days stays monitoring."""
        detector = TrendDetector()
        eval_time = datetime(2024, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
        cluster = _make_cluster(
            cluster_id="c-2",
            status="monitoring",
            last_seen_at="2024-01-15T00:00:00Z",  # 17 days
        )

        changes = detector.evaluate_cluster_lifecycle(
            [cluster], evaluation_time=eval_time
        )

        assert len(changes) == 0

    def test_resolved_cluster_no_change(self):
        """Already-resolved clusters are not transitioned."""
        detector = TrendDetector()
        eval_time = datetime(2024, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        cluster = _make_cluster(
            cluster_id="c-3",
            status="resolved",
            last_seen_at="2024-01-01T00:00:00Z",
        )

        changes = detector.evaluate_cluster_lifecycle(
            [cluster], evaluation_time=eval_time
        )

        assert len(changes) == 0


# ---------------------------------------------------------------------------
# Theme Frequency Distribution (Req 22.1)
# ---------------------------------------------------------------------------


class TestThemeFrequencyDistribution:
    """Tests for theme frequency distribution computation."""

    def test_basic_distribution(self):
        """Frequencies computed correctly for multiple themes."""
        detector = TrendDetector()
        records = [
            _make_record(feedback_id="1", theme_primary="billing"),
            _make_record(feedback_id="2", theme_primary="billing"),
            _make_record(feedback_id="3", theme_primary="outage"),
            _make_record(feedback_id="4", theme_primary="billing"),
        ]

        freqs = detector.compute_theme_frequencies(records)

        assert len(freqs) == 2
        assert freqs[0].theme == "billing"
        assert freqs[0].count == 3
        assert freqs[0].proportion == pytest.approx(0.75)
        assert freqs[1].theme == "outage"
        assert freqs[1].count == 1
        assert freqs[1].proportion == pytest.approx(0.25)

    def test_empty_records(self):
        """Empty input returns empty distribution."""
        detector = TrendDetector()
        freqs = detector.compute_theme_frequencies([])
        assert freqs == []

    def test_single_theme(self):
        """Single theme gets proportion 1.0."""
        detector = TrendDetector()
        records = [_make_record(feedback_id=f"fb-{i}") for i in range(5)]

        freqs = detector.compute_theme_frequencies(records)

        assert len(freqs) == 1
        assert freqs[0].proportion == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# New Cluster Emergence Rate (Req 22.1)
# ---------------------------------------------------------------------------


class TestNewClusterEmergenceRate:
    """Tests for new cluster emergence rate tracking."""

    def test_counts_clusters_within_window(self):
        """Counts clusters with first_seen_at within the window."""
        detector = TrendDetector(window_days=7)
        window_end = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        window_start = window_end - timedelta(days=7)

        clusters = [
            _make_cluster(cluster_id="c-1", first_seen_at="2024-01-10T00:00:00Z"),
            _make_cluster(cluster_id="c-2", first_seen_at="2024-01-14T00:00:00Z"),
            _make_cluster(cluster_id="c-3", first_seen_at="2024-01-01T00:00:00Z"),
        ]

        count = detector.compute_new_cluster_count(
            clusters, window_start=window_start, window_end=window_end
        )

        assert count == 2  # c-1 and c-2 are within the window

    def test_no_clusters_in_window(self):
        """Returns 0 when no clusters were created in the window."""
        detector = TrendDetector(window_days=7)
        window_end = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        window_start = window_end - timedelta(days=7)

        clusters = [
            _make_cluster(cluster_id="c-1", first_seen_at="2024-01-01T00:00:00Z"),
        ]

        count = detector.compute_new_cluster_count(
            clusters, window_start=window_start, window_end=window_end
        )

        assert count == 0


# ---------------------------------------------------------------------------
# Full Analysis (Integration)
# ---------------------------------------------------------------------------


class TestFullAnalysis:
    """Tests for the combined analyze() method."""

    def test_analyze_returns_trend_result(self):
        """Full analysis produces a TrendResult with all fields populated."""
        detector = TrendDetector(window_days=7)
        eval_time = datetime(2024, 1, 25, 12, 0, 0, tzinfo=timezone.utc)

        records = [
            _make_record(
                feedback_id=f"fb-{i}",
                theme_primary="billing",
                cluster_id="c-1",
                sentiment_score=0.0,
                processed_at=f"2024-01-{i+1:02d}T00:00:00Z",
            )
            for i in range(5)
        ]

        clusters = [
            _make_cluster(
                cluster_id="c-1",
                status="active",
                first_seen_at="2024-01-20T00:00:00Z",
                last_seen_at="2024-01-24T00:00:00Z",
            ),
        ]

        daily_volumes = {"billing": [2, 2, 2, 2, 2, 2, 2, 3]}

        result = detector.analyze(
            records, clusters, daily_volumes, evaluation_time=eval_time
        )

        assert isinstance(result, TrendResult)
        assert result.volume_spikes == []  # 3 is not > 2*2
        assert len(result.theme_frequencies) == 1
        assert result.theme_frequencies[0].theme == "billing"
        assert result.sentiment_trends["c-1"] == "stable"  # < 20 records
        assert result.lifecycle_changes == []  # active, last_seen 1 day ago
        assert result.new_cluster_count == 1  # c-1 created within 7 days
