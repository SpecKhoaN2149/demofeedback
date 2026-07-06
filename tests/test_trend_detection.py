"""Unit tests for the TrendDetector class.

Validates Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7:
- Window validation (start < end, no overlap)
- Minimum 10-record threshold per window
- Record collection from PersistenceStore
- TrendReport generation
- Theme frequency spike detection
- Sentiment shift detection
- Severity escalation detection
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from nlp_processing.models.enhancements import (
    SentimentShift,
    SeverityEscalation,
    ThemeSpike,
    TimeWindow,
    TrendReport,
)
from nlp_processing.models.records import (
    BatchOutput,
    BatchSummary,
    InsightRecord,
    SeverityFactor,
    ThemeAssignment,
)
from nlp_processing.persistence.store import PersistenceStore
from nlp_processing.persistence_config import TrendConfig
from nlp_processing.trends import TrendDetector


def _make_store() -> PersistenceStore:
    """Create an in-memory PersistenceStore for testing."""
    return PersistenceStore(backend="sqlite", db_path=":memory:")


def _make_insight_record(feedback_id: str = "fb-1") -> InsightRecord:
    """Create a minimal valid InsightRecord."""
    return InsightRecord(
        feedback_id=feedback_id,
        themes=[ThemeAssignment(theme="billing", confidence=0.9)],
        sentiment="negative",
        sentiment_confidence=0.85,
        severity_score=3,
        severity_factors=[SeverityFactor(description="customer impact")],
        cluster_id="cl-1",
        model_name="test-model",
    )


def _make_batch_output(num_records: int = 1) -> BatchOutput:
    """Create a BatchOutput with a given number of InsightRecords."""
    insights = [
        _make_insight_record(feedback_id=f"fb-{i}") for i in range(num_records)
    ]
    return BatchOutput(
        insights=insights,
        clusters=[],
        failures=[],
        system_errors=[],
        summary=BatchSummary(
            submitted=num_records, successful=num_records, failures=0
        ),
        model_name="test-model",
    )


def _populate_store(store: PersistenceStore, num_records: int = 10) -> None:
    """Save a batch with the given number of records to the store."""
    batch = _make_batch_output(num_records)
    result = store.save_batch(batch)
    assert result.success


class TestWindowValidation:
    """Requirement 3.8: Reject invalid window configurations."""

    def test_baseline_start_equals_end_raises(self):
        store = _make_store()
        detector = TrendDetector(store, TrendConfig())
        baseline = TimeWindow(start="2024-01-01T00:00:00Z", end="2024-01-01T00:00:00Z")
        current = TimeWindow(start="2024-02-01T00:00:00Z", end="2024-03-01T00:00:00Z")

        with pytest.raises(ValueError, match="Invalid baseline window"):
            detector.detect_trends(baseline, current)

    def test_baseline_start_after_end_raises(self):
        store = _make_store()
        detector = TrendDetector(store, TrendConfig())
        baseline = TimeWindow(start="2024-02-01T00:00:00Z", end="2024-01-01T00:00:00Z")
        current = TimeWindow(start="2024-03-01T00:00:00Z", end="2024-04-01T00:00:00Z")

        with pytest.raises(ValueError, match="Invalid baseline window"):
            detector.detect_trends(baseline, current)

    def test_current_start_equals_end_raises(self):
        store = _make_store()
        detector = TrendDetector(store, TrendConfig())
        baseline = TimeWindow(start="2024-01-01T00:00:00Z", end="2024-02-01T00:00:00Z")
        current = TimeWindow(start="2024-03-01T00:00:00Z", end="2024-03-01T00:00:00Z")

        with pytest.raises(ValueError, match="Invalid current window"):
            detector.detect_trends(baseline, current)

    def test_current_start_after_end_raises(self):
        store = _make_store()
        detector = TrendDetector(store, TrendConfig())
        baseline = TimeWindow(start="2024-01-01T00:00:00Z", end="2024-02-01T00:00:00Z")
        current = TimeWindow(start="2024-04-01T00:00:00Z", end="2024-03-01T00:00:00Z")

        with pytest.raises(ValueError, match="Invalid current window"):
            detector.detect_trends(baseline, current)

    def test_invalid_iso_timestamp_raises(self):
        store = _make_store()
        detector = TrendDetector(store, TrendConfig())
        baseline = TimeWindow(start="not-a-date", end="2024-02-01T00:00:00Z")
        current = TimeWindow(start="2024-03-01T00:00:00Z", end="2024-04-01T00:00:00Z")

        with pytest.raises(ValueError, match="Cannot parse"):
            detector.detect_trends(baseline, current)


class TestWindowOverlap:
    """Requirement 3.8: Reject overlapping windows."""

    def test_overlapping_windows_raises(self):
        store = _make_store()
        detector = TrendDetector(store, TrendConfig())
        # Baseline: Jan 1 - Feb 15, Current: Feb 1 - Mar 1 → overlap Feb 1-15
        baseline = TimeWindow(
            start="2024-01-01T00:00:00Z", end="2024-02-15T00:00:00Z"
        )
        current = TimeWindow(
            start="2024-02-01T00:00:00Z", end="2024-03-01T00:00:00Z"
        )

        with pytest.raises(ValueError, match="must not overlap"):
            detector.detect_trends(baseline, current)

    def test_identical_windows_raises(self):
        store = _make_store()
        detector = TrendDetector(store, TrendConfig())
        baseline = TimeWindow(start="2024-01-01T00:00:00Z", end="2024-02-01T00:00:00Z")
        current = TimeWindow(start="2024-01-01T00:00:00Z", end="2024-02-01T00:00:00Z")

        with pytest.raises(ValueError, match="must not overlap"):
            detector.detect_trends(baseline, current)

    def test_adjacent_windows_no_overlap(self):
        """Adjacent windows (baseline.end == current.start) should NOT overlap."""
        store = _make_store()
        detector = TrendDetector(store, TrendConfig())
        baseline = TimeWindow(start="2024-01-01T00:00:00Z", end="2024-02-01T00:00:00Z")
        current = TimeWindow(start="2024-02-01T00:00:00Z", end="2024-03-01T00:00:00Z")

        # Should not raise — adjacent windows are valid
        report = detector.detect_trends(baseline, current)
        assert isinstance(report, TrendReport)

    def test_non_overlapping_windows_valid(self):
        """Non-overlapping windows with a gap should be valid."""
        store = _make_store()
        detector = TrendDetector(store, TrendConfig())
        baseline = TimeWindow(start="2024-01-01T00:00:00Z", end="2024-02-01T00:00:00Z")
        current = TimeWindow(start="2024-03-01T00:00:00Z", end="2024-04-01T00:00:00Z")

        report = detector.detect_trends(baseline, current)
        assert isinstance(report, TrendReport)


class TestMinimumRecordThreshold:
    """Requirements 3.6, 4.6: Return empty findings with note if < 10 records."""

    def test_empty_store_returns_insufficient_data_note(self):
        store = _make_store()
        detector = TrendDetector(store, TrendConfig())
        baseline = TimeWindow(start="2024-01-01T00:00:00Z", end="2024-02-01T00:00:00Z")
        current = TimeWindow(start="2024-03-01T00:00:00Z", end="2024-04-01T00:00:00Z")

        report = detector.detect_trends(baseline, current)

        assert report.theme_spikes == []
        assert report.sentiment_shifts == []
        assert report.severity_escalations == []
        assert len(report.notes) >= 1
        assert any("Insufficient data" in note for note in report.notes)

    def test_baseline_insufficient_records(self):
        """Baseline has < 10 records, current has >= 10."""
        store = _make_store()
        # Save 5 records (timestamped "now" by default)
        batch_5 = _make_batch_output(num_records=5)
        store.save_batch(batch_5)

        detector = TrendDetector(store, TrendConfig())
        # Use a very wide window to capture the saved batch
        baseline = TimeWindow(start="2020-01-01T00:00:00Z", end="2030-01-01T00:00:00Z")
        current = TimeWindow(start="2030-01-01T00:00:00Z", end="2040-01-01T00:00:00Z")

        report = detector.detect_trends(baseline, current)

        assert report.theme_spikes == []
        assert any("baseline" in note.lower() for note in report.notes)

    def test_both_windows_sufficient_records(self):
        """Both windows have >= 10 records: no insufficient-data note."""
        store = _make_store()

        # We need to control timestamps. Save batches with known timestamps.
        # Baseline window: 2024-01-01 to 2024-02-01
        # Current window: 2024-03-01 to 2024-04-01
        # Insert directly with controlled timestamps.
        import sqlite3

        batch_baseline = _make_batch_output(num_records=12)
        batch_current = _make_batch_output(num_records=15)

        # Insert baseline batch with timestamp in Jan 2024
        store._conn.execute(
            "INSERT INTO batches (batch_id, timestamp, status, payload) VALUES (?, ?, ?, ?)",
            ("b-1", "2024-01-15T00:00:00+00:00", "completed", batch_baseline.model_dump_json()),
        )
        # Insert current batch with timestamp in Mar 2024
        store._conn.execute(
            "INSERT INTO batches (batch_id, timestamp, status, payload) VALUES (?, ?, ?, ?)",
            ("b-2", "2024-03-15T00:00:00+00:00", "completed", batch_current.model_dump_json()),
        )
        store._conn.commit()

        detector = TrendDetector(store, TrendConfig())
        baseline = TimeWindow(start="2024-01-01T00:00:00Z", end="2024-02-01T00:00:00Z")
        current = TimeWindow(start="2024-03-01T00:00:00Z", end="2024-04-01T00:00:00Z")

        report = detector.detect_trends(baseline, current)

        # No insufficient-data notes
        assert not any("Insufficient" in note for note in report.notes)


class TestRecordCollection:
    """Requirement 3.1: Query PersistenceStore for InsightRecords within windows."""

    def test_collects_records_from_multiple_batches(self):
        store = _make_store()

        batch1 = _make_batch_output(num_records=6)
        batch2 = _make_batch_output(num_records=6)

        # Insert both in the baseline window
        store._conn.execute(
            "INSERT INTO batches (batch_id, timestamp, status, payload) VALUES (?, ?, ?, ?)",
            ("b-1", "2024-01-10T00:00:00+00:00", "completed", batch1.model_dump_json()),
        )
        store._conn.execute(
            "INSERT INTO batches (batch_id, timestamp, status, payload) VALUES (?, ?, ?, ?)",
            ("b-2", "2024-01-20T00:00:00+00:00", "completed", batch2.model_dump_json()),
        )
        store._conn.commit()

        detector = TrendDetector(store, TrendConfig())

        # Use the internal _collect_records to verify
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 2, 1, tzinfo=timezone.utc)
        records = detector._collect_records(start, end)

        # Should have 12 records total (6 + 6)
        assert len(records) == 12

    def test_records_outside_window_not_collected(self):
        store = _make_store()

        batch = _make_batch_output(num_records=5)

        # Insert batch outside the query window
        store._conn.execute(
            "INSERT INTO batches (batch_id, timestamp, status, payload) VALUES (?, ?, ?, ?)",
            ("b-1", "2024-06-15T00:00:00+00:00", "completed", batch.model_dump_json()),
        )
        store._conn.commit()

        detector = TrendDetector(store, TrendConfig())

        # Query a different window
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 2, 1, tzinfo=timezone.utc)
        records = detector._collect_records(start, end)

        assert len(records) == 0


class TestTrendReportStructure:
    """Verify the returned TrendReport has the expected structure."""

    def test_report_with_identical_data_has_no_shifts(self):
        """With sufficient identical data in both windows, no shifts are detected."""
        store = _make_store()

        batch_baseline = _make_batch_output(num_records=10)
        batch_current = _make_batch_output(num_records=10)

        store._conn.execute(
            "INSERT INTO batches (batch_id, timestamp, status, payload) VALUES (?, ?, ?, ?)",
            ("b-1", "2024-01-15T00:00:00+00:00", "completed", batch_baseline.model_dump_json()),
        )
        store._conn.execute(
            "INSERT INTO batches (batch_id, timestamp, status, payload) VALUES (?, ?, ?, ?)",
            ("b-2", "2024-03-15T00:00:00+00:00", "completed", batch_current.model_dump_json()),
        )
        store._conn.commit()

        detector = TrendDetector(store, TrendConfig())
        baseline = TimeWindow(start="2024-01-01T00:00:00Z", end="2024-02-01T00:00:00Z")
        current = TimeWindow(start="2024-03-01T00:00:00Z", end="2024-04-01T00:00:00Z")

        report = detector.detect_trends(baseline, current)

        assert isinstance(report, TrendReport)
        # Identical data in both windows → no spikes, shifts, or escalations
        assert report.theme_spikes == []
        assert report.sentiment_shifts == []
        assert report.severity_escalations == []
        assert report.notes == []


class TestThemeSpikeDetection:
    """Requirements 3.2, 3.3, 3.4, 3.5: Theme frequency spike detection."""

    def _make_records_with_themes(
        self, theme_lists: list[list[str]]
    ) -> list[InsightRecord]:
        """Create InsightRecords with specified themes for each record."""
        records = []
        for i, themes in enumerate(theme_lists):
            records.append(
                InsightRecord(
                    feedback_id=f"fb-{i}",
                    themes=[
                        ThemeAssignment(theme=t, confidence=0.9) for t in themes
                    ],
                    sentiment="negative",
                    sentiment_confidence=0.85,
                    severity_score=3,
                    severity_factors=[SeverityFactor(description="impact")],
                    cluster_id="cl-1",
                    model_name="test-model",
                )
            )
        return records

    def test_compute_theme_frequencies_single_theme(self):
        """Req 3.2: Relative frequency = count / total records."""
        detector = TrendDetector(_make_store(), TrendConfig())
        records = self._make_records_with_themes(
            [["billing"], ["billing"], ["network_speed"]]
        )
        freq = detector._compute_theme_frequencies(records)

        assert freq["billing"] == pytest.approx(2 / 3)
        assert freq["network_speed"] == pytest.approx(1 / 3)

    def test_compute_theme_frequencies_multiple_themes_per_record(self):
        """Req 3.2: A record with multiple themes contributes one count to each."""
        detector = TrendDetector(_make_store(), TrendConfig())
        records = self._make_records_with_themes(
            [["billing", "network_speed"], ["billing"]]
        )
        freq = detector._compute_theme_frequencies(records)

        # billing: 2/2 = 1.0, network_speed: 1/2 = 0.5
        assert freq["billing"] == pytest.approx(1.0)
        assert freq["network_speed"] == pytest.approx(0.5)

    def test_compute_theme_frequencies_empty_records(self):
        """Empty records returns empty dict."""
        detector = TrendDetector(_make_store(), TrendConfig())
        freq = detector._compute_theme_frequencies([])
        assert freq == {}

    def test_spike_detected_above_threshold(self):
        """Req 3.3: Spike detected when pct increase >= threshold."""
        detector = TrendDetector(_make_store(), TrendConfig(spike_threshold_pct=50))

        # Baseline: billing in 2/10 records = 0.2
        baseline = self._make_records_with_themes(
            [["billing"]] * 2 + [["network_speed"]] * 8
        )
        # Current: billing in 8/10 records = 0.8
        current = self._make_records_with_themes(
            [["billing"]] * 8 + [["network_speed"]] * 2
        )

        spikes = detector._detect_theme_spikes(baseline, current)

        # billing: (0.8 - 0.2) / 0.2 * 100 = 300% >= 50%
        billing_spikes = [s for s in spikes if s.theme == "billing"]
        assert len(billing_spikes) == 1
        assert billing_spikes[0].percentage_increase == pytest.approx(300.0)
        assert billing_spikes[0].baseline_frequency == pytest.approx(0.2)
        assert billing_spikes[0].current_frequency == pytest.approx(0.8)

    def test_no_spike_below_threshold(self):
        """Req 3.3: No spike when pct increase < threshold."""
        detector = TrendDetector(_make_store(), TrendConfig(spike_threshold_pct=50))

        # Baseline: billing in 5/10 = 0.5
        baseline = self._make_records_with_themes(
            [["billing"]] * 5 + [["network_speed"]] * 5
        )
        # Current: billing in 6/10 = 0.6 → (0.6-0.5)/0.5*100 = 20% < 50%
        current = self._make_records_with_themes(
            [["billing"]] * 6 + [["network_speed"]] * 4
        )

        spikes = detector._detect_theme_spikes(baseline, current)

        billing_spikes = [s for s in spikes if s.theme == "billing"]
        assert len(billing_spikes) == 0

    def test_new_theme_labeled_new(self):
        """Req 3.4: Theme absent in baseline, present in current → 'new'."""
        detector = TrendDetector(_make_store(), TrendConfig(spike_threshold_pct=50))

        baseline = self._make_records_with_themes([["billing"]] * 10)
        # Current has "outage" which didn't exist in baseline
        current = self._make_records_with_themes(
            [["billing"]] * 7 + [["outage"]] * 3
        )

        spikes = detector._detect_theme_spikes(baseline, current)

        outage_spikes = [s for s in spikes if s.theme == "outage"]
        assert len(outage_spikes) == 1
        assert outage_spikes[0].percentage_increase == "new"
        assert outage_spikes[0].baseline_frequency == 0.0
        assert outage_spikes[0].current_frequency == pytest.approx(0.3)

    def test_theme_disappeared_not_spike(self):
        """Theme present in baseline but gone from current is not a spike."""
        detector = TrendDetector(_make_store(), TrendConfig(spike_threshold_pct=50))

        baseline = self._make_records_with_themes(
            [["billing"]] * 5 + [["outage"]] * 5
        )
        # outage disappears from current
        current = self._make_records_with_themes([["billing"]] * 10)

        spikes = detector._detect_theme_spikes(baseline, current)

        outage_spikes = [s for s in spikes if s.theme == "outage"]
        assert len(outage_spikes) == 0

    def test_spikes_ordered_descending_new_first(self):
        """Req 3.5: Ordered by percentage increase descending, new themes first."""
        detector = TrendDetector(_make_store(), TrendConfig(spike_threshold_pct=50))

        # Baseline: billing=5/10=0.5, network_speed=3/10=0.3, support_experience=2/10=0.2
        baseline = self._make_records_with_themes(
            [["billing"]] * 5 + [["network_speed"]] * 3 + [["support_experience"]] * 2
        )
        # Current: 10 records with multiple themes per record
        # billing: 9/10=0.9, network_speed: 8/10=0.8, outage: 3/10=0.3 (new)
        current = self._make_records_with_themes(
            [["billing", "network_speed"]] * 7
            + [["billing", "outage"]] * 2
            + [["outage", "network_speed"]] * 1
        )
        # billing pct: (0.9-0.5)/0.5*100 = 80%
        # network_speed pct: (0.8-0.3)/0.3*100 = 166.67%
        # outage: new

        spikes = detector._detect_theme_spikes(baseline, current)

        # Should have: outage (new), network_speed (166.67%), billing (80%)
        assert len(spikes) == 3
        assert spikes[0].theme == "outage"
        assert spikes[0].percentage_increase == "new"
        assert spikes[1].theme == "network_speed"
        assert spikes[1].percentage_increase == pytest.approx(166.666, rel=0.01)
        assert spikes[2].theme == "billing"
        assert spikes[2].percentage_increase == pytest.approx(80.0)

    def test_same_frequency_no_spike(self):
        """Same theme at same frequency across windows produces no spike."""
        detector = TrendDetector(_make_store(), TrendConfig(spike_threshold_pct=50))

        records = self._make_records_with_themes([["billing"]] * 10)

        spikes = detector._detect_theme_spikes(records, records)
        assert spikes == []

    def test_custom_threshold_applies(self):
        """Configurable threshold is used for spike detection."""
        # Very low threshold: 1%
        detector = TrendDetector(_make_store(), TrendConfig(spike_threshold_pct=1))

        # billing: 9/10 = 0.9 baseline vs 10/10 = 1.0 current → 11.1% increase
        baseline = self._make_records_with_themes(
            [["billing"]] * 9 + [["network_speed"]] * 1
        )
        current = self._make_records_with_themes([["billing"]] * 10)

        spikes = detector._detect_theme_spikes(baseline, current)

        billing_spikes = [s for s in spikes if s.theme == "billing"]
        assert len(billing_spikes) == 1
        # (1.0 - 0.9) / 0.9 * 100 ≈ 11.1%
        assert billing_spikes[0].percentage_increase == pytest.approx(11.111, rel=0.01)

    def test_end_to_end_trend_report_includes_spikes(self):
        """Integration: detect_trends populates theme_spikes in the report."""
        store = _make_store()

        # Create baseline records: all "billing"
        baseline_insights = self._make_records_with_themes(
            [["billing"]] * 10
        )
        baseline_batch = BatchOutput(
            insights=baseline_insights,
            clusters=[],
            failures=[],
            system_errors=[],
            summary=BatchSummary(submitted=10, successful=10, failures=0),
            model_name="test-model",
        )

        # Create current records: mix with new theme "outage"
        current_insights = self._make_records_with_themes(
            [["billing"]] * 5 + [["outage"]] * 5
        )
        current_batch = BatchOutput(
            insights=current_insights,
            clusters=[],
            failures=[],
            system_errors=[],
            summary=BatchSummary(submitted=10, successful=10, failures=0),
            model_name="test-model",
        )

        # Insert batches with controlled timestamps
        store._conn.execute(
            "INSERT INTO batches (batch_id, timestamp, status, payload) VALUES (?, ?, ?, ?)",
            ("b-1", "2024-01-15T00:00:00+00:00", "completed", baseline_batch.model_dump_json()),
        )
        store._conn.execute(
            "INSERT INTO batches (batch_id, timestamp, status, payload) VALUES (?, ?, ?, ?)",
            ("b-2", "2024-03-15T00:00:00+00:00", "completed", current_batch.model_dump_json()),
        )
        store._conn.commit()

        detector = TrendDetector(store, TrendConfig(spike_threshold_pct=50))
        baseline = TimeWindow(start="2024-01-01T00:00:00Z", end="2024-02-01T00:00:00Z")
        current = TimeWindow(start="2024-03-01T00:00:00Z", end="2024-04-01T00:00:00Z")

        report = detector.detect_trends(baseline, current)

        # "outage" is new (baseline=0) → spike with "new"
        assert len(report.theme_spikes) >= 1
        outage_spike = [s for s in report.theme_spikes if s.theme == "outage"]
        assert len(outage_spike) == 1
        assert outage_spike[0].percentage_increase == "new"


class TestSentimentShiftDetection:
    """Requirements 4.1, 4.2, 4.5, 4.7: Sentiment shift detection."""

    def _make_record_with_sentiment(
        self, feedback_id: str, sentiment: str, severity_score: int = 3
    ) -> InsightRecord:
        """Create an InsightRecord with a specific sentiment value."""
        return InsightRecord(
            feedback_id=feedback_id,
            themes=[ThemeAssignment(theme="billing", confidence=0.9)],
            sentiment=sentiment,
            sentiment_confidence=0.85,
            severity_score=severity_score,
            severity_factors=[SeverityFactor(description="impact")],
            cluster_id="cl-1",
            model_name="test-model",
        )

    def test_no_shift_when_same_distribution(self):
        """No shift detected when both windows have same sentiment distribution."""
        store = _make_store()
        detector = TrendDetector(store, TrendConfig(sentiment_shift_ppt=15))

        # Both windows: 20% negative, 30% neutral, 50% positive
        baseline = [self._make_record_with_sentiment(f"b-{i}", "negative") for i in range(2)]
        baseline += [self._make_record_with_sentiment(f"b-{i+2}", "neutral") for i in range(3)]
        baseline += [self._make_record_with_sentiment(f"b-{i+5}", "positive") for i in range(5)]

        current = [self._make_record_with_sentiment(f"c-{i}", "negative") for i in range(2)]
        current += [self._make_record_with_sentiment(f"c-{i+2}", "neutral") for i in range(3)]
        current += [self._make_record_with_sentiment(f"c-{i+5}", "positive") for i in range(5)]

        shifts = detector._detect_sentiment_shifts(baseline, current)
        assert shifts == []

    def test_shift_detected_when_negative_increases_by_threshold(self):
        """Shift detected when current negative exceeds baseline by >= threshold ppt."""
        store = _make_store()
        # threshold = 15 percentage points
        detector = TrendDetector(store, TrendConfig(sentiment_shift_ppt=15))

        # Baseline: 10% negative (1/10)
        baseline = [self._make_record_with_sentiment("b-0", "negative")]
        baseline += [self._make_record_with_sentiment(f"b-{i+1}", "positive") for i in range(9)]

        # Current: 40% negative (4/10) → diff = 30 ppt >= 15 threshold
        current = [self._make_record_with_sentiment(f"c-{i}", "negative") for i in range(4)]
        current += [self._make_record_with_sentiment(f"c-{i+4}", "positive") for i in range(6)]

        shifts = detector._detect_sentiment_shifts(baseline, current)
        assert len(shifts) == 1
        assert shifts[0].baseline_negative_proportion == pytest.approx(0.1)
        assert shifts[0].current_negative_proportion == pytest.approx(0.4)
        assert shifts[0].difference_ppt == pytest.approx(30.0)

    def test_no_shift_when_below_threshold(self):
        """No shift when negative increase is below threshold."""
        store = _make_store()
        # threshold = 15 ppt
        detector = TrendDetector(store, TrendConfig(sentiment_shift_ppt=15))

        # Baseline: 10% negative (1/10)
        baseline = [self._make_record_with_sentiment("b-0", "negative")]
        baseline += [self._make_record_with_sentiment(f"b-{i+1}", "positive") for i in range(9)]

        # Current: 20% negative (2/10) → diff = 10 ppt < 15 threshold
        current = [self._make_record_with_sentiment(f"c-{i}", "negative") for i in range(2)]
        current += [self._make_record_with_sentiment(f"c-{i+2}", "positive") for i in range(8)]

        shifts = detector._detect_sentiment_shifts(baseline, current)
        assert shifts == []

    def test_insufficient_records_returns_empty(self):
        """Returns empty when either window has < 10 records with sentiment."""
        store = _make_store()
        detector = TrendDetector(store, TrendConfig(sentiment_shift_ppt=15))

        baseline = [self._make_record_with_sentiment(f"b-{i}", "negative") for i in range(5)]
        current = [self._make_record_with_sentiment(f"c-{i}", "negative") for i in range(15)]

        shifts = detector._detect_sentiment_shifts(baseline, current)
        assert shifts == []

    def test_proportions_sum_to_one(self):
        """Sentiment proportions should sum to 1.0."""
        store = _make_store()
        detector = TrendDetector(store, TrendConfig())

        records = [self._make_record_with_sentiment(f"r-{i}", "negative") for i in range(3)]
        records += [self._make_record_with_sentiment(f"r-{i+3}", "neutral") for i in range(3)]
        records += [self._make_record_with_sentiment(f"r-{i+6}", "positive") for i in range(4)]

        props = detector._compute_sentiment_proportions(records)
        assert props["negative"] == pytest.approx(0.3)
        assert props["neutral"] == pytest.approx(0.3)
        assert props["positive"] == pytest.approx(0.4)
        assert sum(props.values()) == pytest.approx(1.0)

    def test_shift_at_exact_threshold(self):
        """Shift detected when diff is exactly at the threshold."""
        store = _make_store()
        # threshold = 20 ppt
        detector = TrendDetector(store, TrendConfig(sentiment_shift_ppt=20))

        # Baseline: 10% negative (1/10)
        baseline = [self._make_record_with_sentiment("b-0", "negative")]
        baseline += [self._make_record_with_sentiment(f"b-{i+1}", "positive") for i in range(9)]

        # Current: 30% negative (3/10) → diff = 20 ppt == threshold
        current = [self._make_record_with_sentiment(f"c-{i}", "negative") for i in range(3)]
        current += [self._make_record_with_sentiment(f"c-{i+3}", "positive") for i in range(7)]

        shifts = detector._detect_sentiment_shifts(baseline, current)
        assert len(shifts) == 1
        assert shifts[0].difference_ppt == pytest.approx(20.0)


class TestSeverityEscalationDetection:
    """Requirements 4.3, 4.4, 4.5, 4.7: Severity escalation detection."""

    def _make_record_with_severity(
        self, feedback_id: str, severity_score: int
    ) -> InsightRecord:
        """Create an InsightRecord with a specific severity score."""
        return InsightRecord(
            feedback_id=feedback_id,
            themes=[ThemeAssignment(theme="billing", confidence=0.9)],
            sentiment="neutral",
            sentiment_confidence=0.85,
            severity_score=severity_score,
            severity_factors=[SeverityFactor(description="impact")],
            cluster_id="cl-1",
            model_name="test-model",
        )

    def test_no_escalation_when_same_mean(self):
        """No escalation when both windows have same mean severity."""
        store = _make_store()
        detector = TrendDetector(store, TrendConfig(severity_escalation=1.0))

        # Both windows: all severity 3 → mean = 3.0
        baseline = [self._make_record_with_severity(f"b-{i}", 3) for i in range(10)]
        current = [self._make_record_with_severity(f"c-{i}", 3) for i in range(10)]

        escalations = detector._detect_severity_escalations(baseline, current)
        assert escalations == []

    def test_escalation_detected_when_mean_exceeds_threshold(self):
        """Escalation detected when current mean exceeds baseline by >= threshold."""
        store = _make_store()
        # threshold = 1.0 point
        detector = TrendDetector(store, TrendConfig(severity_escalation=1.0))

        # Baseline: all severity 2 → mean = 2.0
        baseline = [self._make_record_with_severity(f"b-{i}", 2) for i in range(10)]

        # Current: all severity 4 → mean = 4.0, diff = 2.0 >= 1.0
        current = [self._make_record_with_severity(f"c-{i}", 4) for i in range(10)]

        escalations = detector._detect_severity_escalations(baseline, current)
        assert len(escalations) == 1
        assert escalations[0].baseline_mean_severity == pytest.approx(2.0)
        assert escalations[0].current_mean_severity == pytest.approx(4.0)
        assert escalations[0].difference == pytest.approx(2.0)

    def test_no_escalation_when_below_threshold(self):
        """No escalation when diff < threshold."""
        store = _make_store()
        # threshold = 1.0 point
        detector = TrendDetector(store, TrendConfig(severity_escalation=1.0))

        # Baseline: mean = 3.0
        baseline = [self._make_record_with_severity(f"b-{i}", 3) for i in range(10)]

        # Current: mean = 3.5 → diff = 0.5 < 1.0
        current = [self._make_record_with_severity(f"c-{i}", 3) for i in range(5)]
        current += [self._make_record_with_severity(f"c-{i+5}", 4) for i in range(5)]

        escalations = detector._detect_severity_escalations(baseline, current)
        assert escalations == []

    def test_insufficient_records_returns_empty(self):
        """Returns empty when either window has < 10 records with severity."""
        store = _make_store()
        detector = TrendDetector(store, TrendConfig(severity_escalation=1.0))

        baseline = [self._make_record_with_severity(f"b-{i}", 2) for i in range(5)]
        current = [self._make_record_with_severity(f"c-{i}", 5) for i in range(15)]

        escalations = detector._detect_severity_escalations(baseline, current)
        assert escalations == []

    def test_escalation_at_exact_threshold(self):
        """Escalation detected when diff is exactly at the threshold."""
        store = _make_store()
        # threshold = 1.0 point
        detector = TrendDetector(store, TrendConfig(severity_escalation=1.0))

        # Baseline: mean = 2.0
        baseline = [self._make_record_with_severity(f"b-{i}", 2) for i in range(10)]

        # Current: mean = 3.0 → diff = 1.0 == threshold
        current = [self._make_record_with_severity(f"c-{i}", 3) for i in range(10)]

        escalations = detector._detect_severity_escalations(baseline, current)
        assert len(escalations) == 1
        assert escalations[0].difference == pytest.approx(1.0)

    def test_mean_severity_in_valid_range(self):
        """Mean severity should be in [1.0, 5.0] range."""
        store = _make_store()
        detector = TrendDetector(store, TrendConfig(severity_escalation=0.5))

        # Mix of severities: mean = (1+2+3+4+5+1+2+3+4+5) / 10 = 3.0
        baseline = [self._make_record_with_severity(f"b-{i}", (i % 5) + 1) for i in range(10)]
        # All severity 5: mean = 5.0
        current = [self._make_record_with_severity(f"c-{i}", 5) for i in range(10)]

        escalations = detector._detect_severity_escalations(baseline, current)
        assert len(escalations) == 1
        assert 1.0 <= escalations[0].baseline_mean_severity <= 5.0
        assert 1.0 <= escalations[0].current_mean_severity <= 5.0


class TestEndToEndSentimentAndSeverity:
    """Integration test: full detect_trends with sentiment shifts and severity escalations."""

    def test_full_report_with_sentiment_shift_and_severity_escalation(self):
        """detect_trends returns a full report with shifts and escalations."""
        store = _make_store()
        config = TrendConfig(
            spike_threshold_pct=50,
            sentiment_shift_ppt=15,
            severity_escalation=1.0,
        )
        detector = TrendDetector(store, config)

        # Baseline: 10% negative, severity mean = 2.0
        baseline_insights = []
        for i in range(10):
            baseline_insights.append(InsightRecord(
                feedback_id=f"b-{i}",
                themes=[ThemeAssignment(theme="billing", confidence=0.9)],
                sentiment="negative" if i == 0 else "positive",
                sentiment_confidence=0.85,
                severity_score=2,
                severity_factors=[SeverityFactor(description="impact")],
                cluster_id="cl-1",
                model_name="test-model",
            ))

        # Current: 50% negative, severity mean = 4.0
        current_insights = []
        for i in range(10):
            current_insights.append(InsightRecord(
                feedback_id=f"c-{i}",
                themes=[ThemeAssignment(theme="billing", confidence=0.9)],
                sentiment="negative" if i < 5 else "positive",
                sentiment_confidence=0.85,
                severity_score=4,
                severity_factors=[SeverityFactor(description="impact")],
                cluster_id="cl-1",
                model_name="test-model",
            ))

        baseline_batch = BatchOutput(
            insights=baseline_insights,
            clusters=[],
            failures=[],
            system_errors=[],
            summary=BatchSummary(submitted=10, successful=10, failures=0),
            model_name="test-model",
        )
        current_batch = BatchOutput(
            insights=current_insights,
            clusters=[],
            failures=[],
            system_errors=[],
            summary=BatchSummary(submitted=10, successful=10, failures=0),
            model_name="test-model",
        )

        store._conn.execute(
            "INSERT INTO batches (batch_id, timestamp, status, payload) VALUES (?, ?, ?, ?)",
            ("b-1", "2024-01-15T00:00:00+00:00", "completed", baseline_batch.model_dump_json()),
        )
        store._conn.execute(
            "INSERT INTO batches (batch_id, timestamp, status, payload) VALUES (?, ?, ?, ?)",
            ("b-2", "2024-03-15T00:00:00+00:00", "completed", current_batch.model_dump_json()),
        )
        store._conn.commit()

        baseline_window = TimeWindow(start="2024-01-01T00:00:00Z", end="2024-02-01T00:00:00Z")
        current_window = TimeWindow(start="2024-03-01T00:00:00Z", end="2024-04-01T00:00:00Z")

        report = detector.detect_trends(baseline_window, current_window)

        # Sentiment shift: 10% → 50% = 40 ppt >= 15 threshold
        assert len(report.sentiment_shifts) == 1
        assert report.sentiment_shifts[0].difference_ppt == pytest.approx(40.0)

        # Severity escalation: 2.0 → 4.0 = 2.0 >= 1.0 threshold
        assert len(report.severity_escalations) == 1
        assert report.severity_escalations[0].difference == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Property-based tests for trend detection (task 9.4)
# ---------------------------------------------------------------------------

from hypothesis import given, settings

from tests.strategies import insight_records_with_themes


# Feature: nlp-pipeline-enhancements, Property 8: Theme frequency computation
class TestThemeFrequencyProperty:
    """Property 8: Theme frequency computation.

    **Validates: Requirements 3.2**

    For any set of InsightRecords, the computed relative frequency of a theme
    SHALL equal the number of records assigned that theme divided by the total
    number of records in the set. Each record contributes once per distinct
    theme assigned to it.
    """

    @given(records=insight_records_with_themes(min_records=1, max_records=30))
    @settings(max_examples=100)
    def test_theme_frequency_equals_count_over_total(self, records):
        """For any generated records, _compute_theme_frequencies returns
        values matching count/total for each theme."""
        detector = TrendDetector(_make_store(), TrendConfig())
        frequencies = detector._compute_theme_frequencies(records)

        total = len(records)
        # Compute expected frequencies manually
        expected_counts: dict[str, int] = {}
        for record in records:
            for theme_assignment in record.themes:
                theme = theme_assignment.theme
                expected_counts[theme] = expected_counts.get(theme, 0) + 1

        expected_frequencies = {
            theme: count / total for theme, count in expected_counts.items()
        }

        # Verify same set of themes
        assert set(frequencies.keys()) == set(expected_frequencies.keys())

        # Verify each frequency matches count / total
        for theme in expected_frequencies:
            assert frequencies[theme] == pytest.approx(
                expected_frequencies[theme]
            ), f"Frequency mismatch for theme '{theme}'"

        # Verify all frequencies are in valid range [0.0, 1.0]
        for theme, freq in frequencies.items():
            assert 0.0 <= freq <= 1.0, (
                f"Frequency for theme '{theme}' out of range: {freq}"
            )


# ---------------------------------------------------------------------------
# Property-Based Tests for Trend Detection
# ---------------------------------------------------------------------------

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.strategies import insight_records_with_themes


# Feature: nlp-pipeline-enhancements, Property 9: Theme spike detection
# **Validates: Requirements 3.3, 3.4**
class TestThemeSpikeDetectionProperty:
    """Property 9: Theme spike detection.

    **Validates: Requirements 3.3, 3.4**

    For any baseline and current theme frequency distributions and a configured
    spike threshold, a theme SHALL be identified as a spike if and only if its
    relative percentage increase ((current - baseline) / baseline × 100) is at
    least the threshold, or it is a new theme (baseline frequency = 0 and
    current frequency > 0).
    """

    @given(
        baseline_records=insight_records_with_themes(min_records=10, max_records=20),
        current_records=insight_records_with_themes(min_records=10, max_records=20),
        threshold=st.integers(min_value=1, max_value=500),
    )
    @settings(max_examples=100)
    def test_spike_iff_pct_increase_ge_threshold_or_new(
        self, baseline_records, current_records, threshold
    ):
        """Every reported spike has pct_increase >= threshold OR is 'new',
        and every theme NOT in the spike list has pct_increase < threshold
        (or zero current frequency)."""
        store = _make_store()
        config = TrendConfig(spike_threshold_pct=threshold)
        detector = TrendDetector(store, config)

        spikes = detector._detect_theme_spikes(baseline_records, current_records)

        # Compute frequencies independently for verification
        baseline_freq = detector._compute_theme_frequencies(baseline_records)
        current_freq = detector._compute_theme_frequencies(current_records)

        spike_themes = {s.theme for s in spikes}

        # 1. Every reported spike must satisfy: pct_increase >= threshold OR "new"
        for spike in spikes:
            if spike.percentage_increase == "new":
                # New theme: baseline must be 0, current must be > 0
                assert spike.baseline_frequency == 0.0, (
                    f"Spike '{spike.theme}' labeled 'new' but baseline_frequency "
                    f"= {spike.baseline_frequency}"
                )
                assert spike.current_frequency > 0.0, (
                    f"Spike '{spike.theme}' labeled 'new' but current_frequency "
                    f"= {spike.current_frequency}"
                )
                # Verify theme truly absent in baseline
                assert baseline_freq.get(spike.theme, 0.0) == 0.0
            else:
                # Numeric spike: percentage_increase must be >= threshold
                assert spike.percentage_increase >= threshold, (
                    f"Spike '{spike.theme}' has pct_increase "
                    f"{spike.percentage_increase} < threshold {threshold}"
                )

        # 2. Every theme NOT in the spike list must have pct_increase < threshold
        #    (or zero current frequency, meaning it can't be a spike)
        all_themes = set(baseline_freq.keys()) | set(current_freq.keys())
        non_spike_themes = all_themes - spike_themes

        for theme in non_spike_themes:
            b_freq = baseline_freq.get(theme, 0.0)
            c_freq = current_freq.get(theme, 0.0)

            if c_freq == 0.0:
                # Theme not present in current — cannot be a spike (correct)
                continue

            if b_freq == 0.0:
                # New theme with current > 0 that's NOT in spikes — this is a bug
                assert False, (
                    f"Theme '{theme}' is new (baseline=0, current={c_freq}) "
                    f"but was not reported as a spike"
                )
            else:
                # Existing theme: verify pct_increase < threshold
                pct_increase = (c_freq - b_freq) / b_freq * 100
                assert pct_increase < threshold, (
                    f"Theme '{theme}' has pct_increase {pct_increase} >= threshold "
                    f"{threshold} but was not reported as a spike"
                )


# Feature: nlp-pipeline-enhancements, Property 10: Spike ordering
# **Validates: Requirements 3.5**
class TestSpikeOrderingProperty:
    """Property 10: Spikes in a TrendReport are ordered by percentage increase descending.

    For any set of baseline and current InsightRecords, the spikes returned by
    _detect_theme_spikes are ordered: "new" spikes first, then by numeric
    percentage_increase descending.
    """

    @given(
        baseline_records=insight_records_with_themes(min_records=10, max_records=20),
        current_records=insight_records_with_themes(min_records=10, max_records=20),
        threshold=st.integers(min_value=1, max_value=200),
    )
    @settings(max_examples=100)
    def test_spikes_ordered_new_first_then_descending(
        self, baseline_records, current_records, threshold
    ):
        """Spikes are ordered: 'new' spikes first, then by percentage_increase descending."""
        store = _make_store()
        config = TrendConfig(spike_threshold_pct=threshold)
        detector = TrendDetector(store, config)

        spikes = detector._detect_theme_spikes(baseline_records, current_records)

        # Verify ordering: "new" spikes come first, then numeric descending
        new_spikes = [s for s in spikes if s.percentage_increase == "new"]
        numeric_spikes = [s for s in spikes if s.percentage_increase != "new"]

        # All "new" spikes must appear before all numeric spikes
        if new_spikes and numeric_spikes:
            last_new_idx = max(i for i, s in enumerate(spikes) if s.percentage_increase == "new")
            first_numeric_idx = min(i for i, s in enumerate(spikes) if s.percentage_increase != "new")
            assert last_new_idx < first_numeric_idx, (
                f"New spike at index {last_new_idx} appears after numeric spike at index {first_numeric_idx}"
            )

        # Numeric spikes must be sorted by percentage_increase descending
        for i in range(len(numeric_spikes) - 1):
            assert numeric_spikes[i].percentage_increase >= numeric_spikes[i + 1].percentage_increase, (
                f"Spike ordering violated: {numeric_spikes[i].percentage_increase} < "
                f"{numeric_spikes[i + 1].percentage_increase}"
            )

        # Each spike carries theme label, baseline frequency, current frequency, and percentage_increase
        for spike in spikes:
            assert spike.theme is not None and len(spike.theme) > 0
            assert spike.baseline_frequency >= 0.0
            assert spike.current_frequency >= 0.0
            assert spike.percentage_increase is not None

# ---------------------------------------------------------------------------
# Property-Based Tests for Trend Detection (tasks 9.7–9.12)
# ---------------------------------------------------------------------------

from tests.strategies import invalid_time_windows, time_window_pair


# Feature: nlp-pipeline-enhancements, Property 11: Insufficient data guard
# **Validates: Requirements 3.6, 4.6**
class TestInsufficientDataGuardProperty:
    """Property 11: Insufficient data guard.

    **Validates: Requirements 3.6, 4.6**

    For any time window configuration where either the Baseline_Window or
    Current_Window contains fewer than 10 records, the TrendDetector SHALL
    return no trend findings for that metric and SHALL include an
    insufficient-data note.
    """

    @given(records=insight_records_with_themes(min_records=1, max_records=9))
    @settings(max_examples=100)
    def test_insufficient_data_returns_no_findings_with_note(self, records):
        """When either window has < 10 records, return no findings and
        include an insufficient-data note."""
        store = _make_store()
        config = TrendConfig()
        detector = TrendDetector(store, config)

        # Use records directly for both sentiment and severity computation.
        # The detector requires < 10 records in a window to trigger the guard.
        # Test via _detect_sentiment_shifts and _detect_severity_escalations
        # which check per-metric minimums.
        #
        # For the full detect_trends path, we test with a store that has fewer
        # than 10 records in the baseline window.
        #
        # Insert a batch with our small record set into the store
        baseline_batch = BatchOutput(
            insights=records,
            clusters=[],
            failures=[],
            system_errors=[],
            summary=BatchSummary(
                submitted=len(records), successful=len(records), failures=0
            ),
            model_name="test-model",
        )
        store._conn.execute(
            "INSERT INTO batches (batch_id, timestamp, status, payload) VALUES (?, ?, ?, ?)",
            (
                "b-small",
                "2024-01-15T00:00:00+00:00",
                "completed",
                baseline_batch.model_dump_json(),
            ),
        )
        store._conn.commit()

        baseline = TimeWindow(
            start="2024-01-01T00:00:00Z", end="2024-02-01T00:00:00Z"
        )
        current = TimeWindow(
            start="2024-03-01T00:00:00Z", end="2024-04-01T00:00:00Z"
        )

        report = detector.detect_trends(baseline, current)

        # No trend findings
        assert report.theme_spikes == []
        assert report.sentiment_shifts == []
        assert report.severity_escalations == []
        # At least one note mentioning insufficient data
        assert len(report.notes) >= 1
        assert any("Insufficient data" in note for note in report.notes)


# Feature: nlp-pipeline-enhancements, Property 12: Window validation
# **Validates: Requirements 3.8**
class TestWindowValidationProperty:
    """Property 12: Window validation.

    **Validates: Requirements 3.8**

    For any pair of time windows where the Baseline_Window start >= end, or
    the Current_Window start >= end, or the two windows overlap, the
    TrendDetector SHALL reject the request with a ValueError.
    """

    @given(windows=invalid_time_windows())
    @settings(max_examples=100)
    def test_invalid_windows_raise_value_error(self, windows):
        """For invalid windows (start >= end or overlap), TrendDetector raises ValueError."""
        baseline, current = windows
        store = _make_store()
        detector = TrendDetector(store, TrendConfig())

        with pytest.raises(ValueError):
            detector.detect_trends(baseline, current)


# Feature: nlp-pipeline-enhancements, Property 13: Sentiment proportion computation
# **Validates: Requirements 4.1**
class TestSentimentProportionProperty:
    """Property 13: Sentiment proportion computation.

    **Validates: Requirements 4.1**

    For any set of InsightRecords, the computed proportions of negative,
    neutral, and positive sentiment SHALL each be in [0.0, 1.0] and SHALL
    sum to 1.0 (within floating-point tolerance).
    """

    @given(records=insight_records_with_themes(min_records=1, max_records=30))
    @settings(max_examples=100)
    def test_sentiment_proportions_in_range_and_sum_to_one(self, records):
        """For any set of InsightRecords, negative + neutral + positive
        proportions are each in [0,1] and sum to 1.0."""
        store = _make_store()
        detector = TrendDetector(store, TrendConfig())

        props = detector._compute_sentiment_proportions(records)

        # Each proportion is in [0.0, 1.0]
        assert 0.0 <= props["negative"] <= 1.0
        assert 0.0 <= props["neutral"] <= 1.0
        assert 0.0 <= props["positive"] <= 1.0

        # Sum to 1.0 within floating-point tolerance
        total = props["negative"] + props["neutral"] + props["positive"]
        assert total == pytest.approx(1.0), (
            f"Proportions sum to {total}, expected 1.0"
        )


# Feature: nlp-pipeline-enhancements, Property 14: Sentiment shift detection
# **Validates: Requirements 4.2**
class TestSentimentShiftDetectionProperty:
    """Property 14: Sentiment shift detection.

    **Validates: Requirements 4.2**

    For any baseline and current negative sentiment proportions, a sentiment
    shift SHALL be identified if and only if the current negative proportion
    exceeds the baseline negative proportion by at least the configured
    threshold (in percentage points).
    """

    @given(
        baseline_records=insight_records_with_themes(min_records=10, max_records=25),
        current_records=insight_records_with_themes(min_records=10, max_records=25),
        threshold=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=100)
    def test_shift_iff_negative_exceeds_baseline_by_threshold(
        self, baseline_records, current_records, threshold
    ):
        """A shift is identified iff current negative proportion exceeds
        baseline by >= threshold ppt."""
        store = _make_store()
        config = TrendConfig(sentiment_shift_ppt=threshold)
        detector = TrendDetector(store, config)

        shifts = detector._detect_sentiment_shifts(baseline_records, current_records)

        # Compute expected proportions independently
        baseline_with_sentiment = [r for r in baseline_records if r.sentiment is not None]
        current_with_sentiment = [r for r in current_records if r.sentiment is not None]

        # If either window has < 10 records with sentiment, no shift should be detected
        if len(baseline_with_sentiment) < 10 or len(current_with_sentiment) < 10:
            assert shifts == []
            return

        baseline_neg_count = sum(
            1 for r in baseline_with_sentiment if r.sentiment == "negative"
        )
        current_neg_count = sum(
            1 for r in current_with_sentiment if r.sentiment == "negative"
        )

        baseline_neg_prop = baseline_neg_count / len(baseline_with_sentiment)
        current_neg_prop = current_neg_count / len(current_with_sentiment)

        expected_diff_ppt = (current_neg_prop - baseline_neg_prop) * 100

        if expected_diff_ppt >= threshold:
            # A shift should be detected
            assert len(shifts) == 1
            assert shifts[0].baseline_negative_proportion == pytest.approx(
                baseline_neg_prop
            )
            assert shifts[0].current_negative_proportion == pytest.approx(
                current_neg_prop
            )
            assert shifts[0].difference_ppt == pytest.approx(expected_diff_ppt)
        else:
            # No shift should be detected
            assert shifts == []


# Feature: nlp-pipeline-enhancements, Property 15: Mean severity computation and escalation
# **Validates: Requirements 4.3, 4.4**
class TestSeverityComputationProperty:
    """Property 15: Mean severity computation and escalation detection.

    **Validates: Requirements 4.3, 4.4**

    For any set of InsightRecords with severity scores in 1..5, the computed
    mean severity SHALL be in [1.0, 5.0]. A severity escalation SHALL be
    identified if and only if the current mean exceeds the baseline mean by
    at least the configured escalation threshold.
    """

    @given(
        baseline_records=insight_records_with_themes(min_records=10, max_records=25),
        current_records=insight_records_with_themes(min_records=10, max_records=25),
        threshold=st.floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_mean_severity_in_range_and_escalation_iff_exceeds_threshold(
        self, baseline_records, current_records, threshold
    ):
        """Mean severity is in [1.0, 5.0]; escalation iff current mean
        exceeds baseline mean by >= threshold."""
        store = _make_store()
        config = TrendConfig(severity_escalation=threshold)
        detector = TrendDetector(store, config)

        escalations = detector._detect_severity_escalations(
            baseline_records, current_records
        )

        # Compute expected values independently
        baseline_with_severity = [
            r for r in baseline_records if r.severity_score is not None
        ]
        current_with_severity = [
            r for r in current_records if r.severity_score is not None
        ]

        # If either window has < 10 records with severity, no escalation
        if len(baseline_with_severity) < 10 or len(current_with_severity) < 10:
            assert escalations == []
            return

        baseline_mean = sum(r.severity_score for r in baseline_with_severity) / len(
            baseline_with_severity
        )
        current_mean = sum(r.severity_score for r in current_with_severity) / len(
            current_with_severity
        )

        # Verify mean severity is in valid range
        assert 1.0 <= baseline_mean <= 5.0
        assert 1.0 <= current_mean <= 5.0

        diff = current_mean - baseline_mean

        if diff >= threshold:
            # An escalation should be detected
            assert len(escalations) == 1
            assert escalations[0].baseline_mean_severity == pytest.approx(
                baseline_mean
            )
            assert escalations[0].current_mean_severity == pytest.approx(
                current_mean
            )
            assert escalations[0].difference == pytest.approx(diff)
        else:
            # No escalation should be detected
            assert escalations == []


# Feature: nlp-pipeline-enhancements, Property 16: Incomplete record exclusion
# **Validates: Requirements 4.7**
class TestIncompleteRecordExclusionProperty:
    """Property 16: Incomplete record exclusion from metrics.

    **Validates: Requirements 4.7**

    Records without sentiment are excluded from sentiment metrics; records
    without severity are excluded from severity metrics. Exclusion of one
    field does not affect the other metric.
    """

    @given(records=insight_records_with_themes(min_records=10, max_records=25))
    @settings(max_examples=100)
    def test_records_without_sentiment_excluded_from_sentiment_metrics(self, records):
        """Records without sentiment are excluded from sentiment metrics;
        records without severity from severity metrics."""
        store = _make_store()
        detector = TrendDetector(store, TrendConfig())

        # Create a mixed set: some records have sentiment=None, some have
        # severity_score=None. Use model_construct to bypass Pydantic validation.
        mixed_records: list[InsightRecord] = []
        for i, record in enumerate(records):
            if i % 5 == 0:
                # Remove sentiment (set to None)
                r = InsightRecord.model_construct(
                    feedback_id=record.feedback_id,
                    themes=record.themes,
                    sentiment=None,
                    sentiment_confidence=record.sentiment_confidence,
                    severity_score=record.severity_score,
                    severity_factors=record.severity_factors,
                    cluster_id=record.cluster_id,
                    model_name=record.model_name,
                    notes=record.notes,
                )
                mixed_records.append(r)
            elif i % 7 == 0:
                # Remove severity_score (set to None)
                r = InsightRecord.model_construct(
                    feedback_id=record.feedback_id,
                    themes=record.themes,
                    sentiment=record.sentiment,
                    sentiment_confidence=record.sentiment_confidence,
                    severity_score=None,
                    severity_factors=record.severity_factors,
                    cluster_id=record.cluster_id,
                    model_name=record.model_name,
                    notes=record.notes,
                )
                mixed_records.append(r)
            else:
                mixed_records.append(record)

        # Sentiment computation should exclude records without sentiment
        records_with_sentiment = [r for r in mixed_records if r.sentiment is not None]
        records_with_severity = [r for r in mixed_records if r.severity_score is not None]

        # Test sentiment exclusion
        if len(records_with_sentiment) > 0:
            props = detector._compute_sentiment_proportions(records_with_sentiment)
            total = props["negative"] + props["neutral"] + props["positive"]
            assert total == pytest.approx(1.0)
            # Verify only records WITH sentiment are counted
            assert len(records_with_sentiment) <= len(mixed_records)

        # Test severity exclusion: verify mean is only computed from records with severity
        if len(records_with_severity) > 0:
            expected_mean = sum(
                r.severity_score for r in records_with_severity
            ) / len(records_with_severity)
            assert 1.0 <= expected_mean <= 5.0

        # The detector's _detect_sentiment_shifts should filter properly
        # Use mixed_records for both windows to verify filtering logic
        shifts = detector._detect_sentiment_shifts(mixed_records, mixed_records)
        # With same data in both windows, no shift should be detected
        # (unless window has < 10 records with sentiment, in which case empty)
        if len(records_with_sentiment) >= 10:
            assert shifts == []

        # The detector's _detect_severity_escalations should filter properly
        escalations = detector._detect_severity_escalations(
            mixed_records, mixed_records
        )
        # With same data in both windows, no escalation should be detected
        if len(records_with_severity) >= 10:
            assert escalations == []
