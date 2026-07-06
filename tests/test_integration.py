"""Integration tests for the full enhanced NLP pipeline.

Tests cover:
- Batch persistence (process → persist → retrieve round-trip)
- Cache integration (same text processed twice → second uses cache, no Gemini)
- Language metadata flow (non-English text → InsightRecord carries language info)
- Trend detection end-to-end (multiple batches → detect_trends → TrendReport)

Validates: Requirements 1.1, 1.3, 2.2, 3.1, 4.1, 5.5, 6.7
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from nlp_processing.aggregation import ClusteringComponent, PrioritizationComponent
from nlp_processing.config import Config
from nlp_processing.enrichment.classifier import ClassificationOutcome
from nlp_processing.enrichment.language import LanguageDetector
from nlp_processing.enrichment.sentiment import SentimentOutcome
from nlp_processing.enrichment.severity import SeverityOutcome
from nlp_processing.ingestion import IngestionComponent
from nlp_processing.models import (
    FeedbackRecord,
    RawFeedback,
    SeverityFactor,
    ThemeAssignment,
)
from nlp_processing.models.enhancements import TimeWindow, TrendReport
from nlp_processing.orchestrator import NLPProcessor
from nlp_processing.persistence import CacheLayer, PersistenceStore
from nlp_processing.transport.client import GeminiRequest, GeminiResult


# ---------------------------------------------------------------------------
# Helpers / Fakes
# ---------------------------------------------------------------------------

DUMMY_API_KEY = "test-api-key"
DUMMY_MODEL = "fake-model"


def _config(**overrides: Any) -> Config:
    """Build a valid Config with test defaults."""
    kwargs: dict[str, Any] = {
        "api_key": DUMMY_API_KEY,
        "model_name": DUMMY_MODEL,
        "similarity_threshold": 0.5,
    }
    kwargs.update(overrides)
    return Config(**kwargs)


class _TrackingClassifier:
    """Classifier fake that accepts language_code and tracks call count."""

    def __init__(self) -> None:
        self.call_count = 0

    def classify(
        self, record: FeedbackRecord, *, language_code: str = "en"
    ) -> ClassificationOutcome:
        self.call_count += 1
        themes = (ThemeAssignment(theme="billing", confidence=0.9),)
        return ClassificationOutcome(record=record, themes=themes)


class _TrackingSentimentAnalyzer:
    """Sentiment fake that accepts language_code and tracks call count."""

    def __init__(self) -> None:
        self.call_count = 0

    def analyze(
        self, record: FeedbackRecord, *, language_code: str = "en"
    ) -> SentimentOutcome:
        self.call_count += 1
        return SentimentOutcome(record=record, sentiment="negative", confidence=0.85)


class _TrackingSeverityScorer:
    """Severity fake that accepts language_code and tracks call count."""

    def __init__(self) -> None:
        self.call_count = 0

    def score(
        self, record: FeedbackRecord, *, language_code: str = "en"
    ) -> SeverityOutcome:
        self.call_count += 1
        return SeverityOutcome(
            record=record,
            severity_score=4,
            factors=(SeverityFactor(description="high impact"),),
        )


def _fake_language_generate(request: GeminiRequest) -> GeminiResult:
    """Fake Gemini transport that returns Spanish detection."""
    response = json.dumps({"language_code": "es", "confidence": 0.95})
    return GeminiResult(record_id=request.record_id, attempts=1, text=response)


def _fake_language_generate_en(request: GeminiRequest) -> GeminiResult:
    """Fake Gemini transport that returns English detection."""
    response = json.dumps({"language_code": "en", "confidence": 0.99})
    return GeminiResult(record_id=request.record_id, attempts=1, text=response)


def _make_raw(text: str, channel: str = "email") -> RawFeedback:
    """Build a valid RawFeedback item."""
    return RawFeedback(source_channel=channel, text=text, metadata={})


def _build_processor(
    *,
    persistence_store: PersistenceStore | None = None,
    cache_layer: CacheLayer | None = None,
    language_detector: LanguageDetector | None = None,
    classifier: Any = None,
    sentiment_analyzer: Any = None,
    severity_scorer: Any = None,
) -> NLPProcessor:
    """Build an NLPProcessor with optional enhanced components."""
    return NLPProcessor(
        _config(),
        ingestion=IngestionComponent(),
        classifier=classifier or _TrackingClassifier(),
        sentiment_analyzer=sentiment_analyzer or _TrackingSentimentAnalyzer(),
        severity_scorer=severity_scorer or _TrackingSeverityScorer(),
        clustering=ClusteringComponent(),
        prioritization=PrioritizationComponent(),
        persistence_store=persistence_store,
        cache_layer=cache_layer,
        language_detector=language_detector,
    )


# ---------------------------------------------------------------------------
# Test 1: Persistence round-trip
# Validates: Requirement 1.1, 1.3
# ---------------------------------------------------------------------------


class TestPersistenceIntegration:
    """Process a batch, verify it is persisted and retrievable."""

    def test_batch_persisted_and_retrievable(self) -> None:
        """Process a batch → save succeeds → retrieve returns same output."""
        store = PersistenceStore(backend="sqlite", db_path=":memory:")
        processor = _build_processor(persistence_store=store)

        raw_items = [
            _make_raw("My internet connection keeps dropping every evening"),
            _make_raw("Billing charge is incorrect on my last invoice"),
        ]

        output = processor.process_batch(raw_items)

        # Verify save succeeded
        save_result = processor.last_save_result
        assert save_result is not None
        assert save_result.success is True
        assert save_result.batch_id != ""

        # Retrieve and compare
        retrieved = processor.retrieve_batch(save_result.batch_id)
        assert retrieved is not None
        assert len(retrieved.insights) == len(output.insights)
        assert retrieved.summary.submitted == output.summary.submitted
        assert retrieved.summary.successful == output.summary.successful

        # Verify individual insight fields match
        for orig, retr in zip(output.insights, retrieved.insights):
            assert orig.feedback_id == retr.feedback_id
            assert orig.sentiment == retr.sentiment
            assert orig.severity_score == retr.severity_score
            assert len(orig.themes) == len(retr.themes)


# ---------------------------------------------------------------------------
# Test 2: Cache integration
# Validates: Requirement 2.2, 6.7
# ---------------------------------------------------------------------------


class TestCacheIntegration:
    """Process same feedback text twice, verify second call uses cache."""

    def test_second_call_uses_cache(self) -> None:
        """Same text processed twice → second call has zero Gemini enrichment calls."""
        store = PersistenceStore(backend="sqlite", db_path=":memory:")
        cache = CacheLayer(store=store, ttl_hours=24, enabled=True)

        classifier = _TrackingClassifier()
        sentiment = _TrackingSentimentAnalyzer()
        severity = _TrackingSeverityScorer()

        processor = _build_processor(
            persistence_store=store,
            cache_layer=cache,
            classifier=classifier,
            sentiment_analyzer=sentiment,
            severity_scorer=severity,
        )

        feedback_text = "My router keeps disconnecting from the network"
        raw_items = [_make_raw(feedback_text)]

        # First call: enrichment stages invoked
        processor.process_batch(raw_items)
        first_classify_count = classifier.call_count
        first_sentiment_count = sentiment.call_count
        first_severity_count = severity.call_count

        assert first_classify_count == 1
        assert first_sentiment_count == 1
        assert first_severity_count == 1

        # Second call with same text: should use cache (no new Gemini calls)
        processor.process_batch(raw_items)

        assert classifier.call_count == first_classify_count  # No new calls
        assert sentiment.call_count == first_sentiment_count
        assert severity.call_count == first_severity_count


# ---------------------------------------------------------------------------
# Test 3: Language metadata flow
# Validates: Requirement 5.5
# ---------------------------------------------------------------------------


class TestLanguageIntegration:
    """Process non-English text, verify language metadata flows to InsightRecord."""

    def test_language_metadata_on_insight(self) -> None:
        """Non-English text → InsightRecord carries language_code and language_confidence."""
        store = PersistenceStore(backend="sqlite", db_path=":memory:")
        # Language detector that always returns "es" with 0.95 confidence
        lang_detector = LanguageDetector(client=_fake_language_generate)

        processor = _build_processor(
            persistence_store=store,
            language_detector=lang_detector,
        )

        raw_items = [_make_raw("Mi conexión a internet se cae todas las noches")]

        output = processor.process_batch(raw_items)

        assert len(output.insights) == 1
        insight = output.insights[0]
        assert insight.language_code == "es"
        assert insight.language_confidence == pytest.approx(0.95)


# ---------------------------------------------------------------------------
# Test 4: Trend detection end-to-end
# Validates: Requirement 3.1, 4.1
# ---------------------------------------------------------------------------


class TestTrendDetectionIntegration:
    """Persist multiple batches, run trend detection, verify TrendReport."""

    def test_trend_report_from_multiple_batches(self) -> None:
        """Two batches with different timestamps → detect_trends → TrendReport returned."""
        store = PersistenceStore(backend="sqlite", db_path=":memory:")

        # We need at least 10 records per window for trend detection.
        # Create a classifier that returns different themes for different batches.
        class _BaselineClassifier:
            """Returns 'billing' theme for all records."""

            def classify(
                self, record: FeedbackRecord, *, language_code: str = "en"
            ) -> ClassificationOutcome:
                return ClassificationOutcome(
                    record=record,
                    themes=(ThemeAssignment(theme="billing", confidence=0.9),),
                )

        class _CurrentClassifier:
            """Returns 'outage' theme for all records — simulates a spike."""

            def classify(
                self, record: FeedbackRecord, *, language_code: str = "en"
            ) -> ClassificationOutcome:
                return ClassificationOutcome(
                    record=record,
                    themes=(ThemeAssignment(theme="outage", confidence=0.9),),
                )

        # Sentiment that returns 'neutral' for baseline, 'negative' for current.
        class _BaselineSentiment:
            def analyze(
                self, record: FeedbackRecord, *, language_code: str = "en"
            ) -> SentimentOutcome:
                return SentimentOutcome(
                    record=record, sentiment="neutral", confidence=0.9
                )

        class _CurrentSentiment:
            def analyze(
                self, record: FeedbackRecord, *, language_code: str = "en"
            ) -> SentimentOutcome:
                return SentimentOutcome(
                    record=record, sentiment="negative", confidence=0.9
                )

        severity_scorer = _TrackingSeverityScorer()

        # Process baseline batch (10+ records) — manually insert with known timestamp
        baseline_processor = NLPProcessor(
            _config(),
            ingestion=IngestionComponent(),
            classifier=_BaselineClassifier(),
            sentiment_analyzer=_BaselineSentiment(),
            severity_scorer=severity_scorer,
            clustering=ClusteringComponent(),
            prioritization=PrioritizationComponent(),
            persistence_store=store,
        )

        baseline_items = [
            _make_raw(f"Billing issue number {i}") for i in range(12)
        ]
        baseline_output = baseline_processor.process_batch(baseline_items)
        baseline_save = baseline_processor.last_save_result
        assert baseline_save is not None and baseline_save.success

        # Manually update the batch timestamp to place it in the baseline window
        store._conn.execute(
            "UPDATE batches SET timestamp = ? WHERE batch_id = ?",
            ("2024-01-01T00:00:00+00:00", baseline_save.batch_id),
        )
        store._conn.commit()

        # Process current batch (10+ records)
        current_processor = NLPProcessor(
            _config(),
            ingestion=IngestionComponent(),
            classifier=_CurrentClassifier(),
            sentiment_analyzer=_CurrentSentiment(),
            severity_scorer=severity_scorer,
            clustering=ClusteringComponent(),
            prioritization=PrioritizationComponent(),
            persistence_store=store,
        )

        current_items = [
            _make_raw(f"Network outage report number {i}") for i in range(12)
        ]
        current_output = current_processor.process_batch(current_items)
        current_save = current_processor.last_save_result
        assert current_save is not None and current_save.success

        # Update timestamp for current window
        store._conn.execute(
            "UPDATE batches SET timestamp = ? WHERE batch_id = ?",
            ("2024-06-01T00:00:00+00:00", current_save.batch_id),
        )
        store._conn.commit()

        # Now run trend detection using a processor that has the store
        detector_processor = _build_processor(persistence_store=store)

        baseline_window = TimeWindow(
            start="2023-12-01T00:00:00+00:00",
            end="2024-02-01T00:00:00+00:00",
        )
        current_window = TimeWindow(
            start="2024-05-01T00:00:00+00:00",
            end="2024-07-01T00:00:00+00:00",
        )

        report = detector_processor.detect_trends(baseline_window, current_window)

        # Verify we got a TrendReport back
        assert isinstance(report, TrendReport)

        # The "outage" theme should appear as a new-theme spike
        # (present in current, absent in baseline)
        assert len(report.theme_spikes) > 0
        outage_spike = next(
            (s for s in report.theme_spikes if s.theme == "outage"), None
        )
        assert outage_spike is not None
        assert outage_spike.percentage_increase == "new"

        # Sentiment shift: baseline was all neutral, current is all negative
        # Difference is 100 percentage points (0.0 → 1.0 negative proportion)
        assert len(report.sentiment_shifts) > 0
        shift = report.sentiment_shifts[0]
        assert shift.current_negative_proportion > shift.baseline_negative_proportion
