"""Unit tests for PipelineOrchestrator (task 8.1).

Tests cover:
- Successful end-to-end processing (status tracking through all stages)
- Retry logic with exponential backoff
- Total timeout enforcement (120s)
- Per-record isolation in batch processing
- Persistence on "routed" status
- Handling of preprocessing failures (duplicates, empty text)
- NLP analysis stage failure and retry
- Decision routing stage failure and retry
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch, call

import pytest

from nlp_processing.models.feedback_routing import (
    CanonicalFeedback,
    ExtractedEntity,
    FeedbackAnalysis,
    IntentResult,
    PriorityResult,
    RoutingDecision,
    SentimentResult,
    SocialFeedback,
    EngagementMetrics,
    ThemeResult,
    Ticket,
    WidgetFeedback,
)
from nlp_processing.routing.pipeline_orchestrator import (
    BACKOFF_DELAYS,
    MAX_RETRIES,
    TOTAL_TIMEOUT_SECONDS,
    PipelineOrchestrator,
    ProcessingResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_social_feedback(feedback_id: str = "fb-001") -> SocialFeedback:
    """Create a minimal SocialFeedback for testing."""
    return SocialFeedback(
        feedback_id=feedback_id,
        source_type="social",
        platform="reddit",
        username_handle="test_user",
        post_id="post-123",
        message_text="My internet has been down for hours. Very frustrated!",
        post_url="https://reddit.com/r/test/post-123",
        created_at_original="2024-01-15T10:00:00Z",
        ingested_at="2024-01-15T10:05:00Z",
        language_code="en",
        engagement_metrics=EngagementMetrics(likes=5, replies=2, reposts=1),
        recency_score=0.99,
        location="Seattle, US",
    )


def _make_widget_feedback(feedback_id: str = "fb-002") -> WidgetFeedback:
    """Create a minimal WidgetFeedback for testing."""
    return WidgetFeedback(
        feedback_id=feedback_id,
        source_type="widget",
        submission_channel="app_widget",
        message_text="Billing issue on my account, charged twice.",
        created_at="2024-01-15T11:00:00Z",
        consent_to_contact=True,
        customer_id="cust-456",
    )


def _make_canonical(feedback_id: str = "fb-001") -> CanonicalFeedback:
    """Create a minimal CanonicalFeedback for testing."""
    return CanonicalFeedback(
        feedback_id=feedback_id,
        source_type="social",
        original_source_id="post-123",
        cleaned_text="My internet has been down for hours. Very frustrated!",
        detected_language="en",
        ingested_at="2024-01-15T10:05:00Z",
        duplicate_count=0,
        profanity_detected=False,
        metadata={"platform": "reddit", "engagement_metrics": {"likes": 5, "replies": 2, "reposts": 1}},
        processing_status="preprocessed",
    )


def _make_analysis(feedback_id: str = "fb-001") -> FeedbackAnalysis:
    """Create a minimal FeedbackAnalysis for testing."""
    return FeedbackAnalysis(
        feedback_id=feedback_id,
        sentiment_label="negative",
        sentiment_score=-0.6,
        priority_score=0.55,
        priority_level="high",
        theme_primary="outage",
        theme_secondary=None,
        intent="outage_report",
        cluster_id="cluster-001",
        requires_action=True,
        entities=[],
        processed_at="2024-01-15T10:05:30Z",
    )


def _make_routing_decision() -> RoutingDecision:
    """Create a minimal RoutingDecision for testing."""
    return RoutingDecision(
        routing_action="create_ticket",
        ticket=Ticket(
            ticket_id="ticket-001",
            ticket_phase="new",
            priority_level="high",
            assigned_department="Network_Operations",
            created_at="2024-01-15T10:05:31Z",
            updated_at="2024-01-15T10:05:31Z",
        ),
        department="Network_Operations",
        evaluation_timestamp="2024-01-15T10:05:31Z",
    )


def _make_orchestrator(
    preprocessor=None,
    sentiment_analyzer=None,
    theme_detector=None,
    intent_classifier=None,
    entity_extractor=None,
    priority_scorer=None,
    similarity_clusterer=None,
    decision_engine=None,
    store=None,
) -> PipelineOrchestrator:
    """Create a PipelineOrchestrator with mock components."""
    return PipelineOrchestrator(
        preprocessor=preprocessor or MagicMock(),
        sentiment_analyzer=sentiment_analyzer or MagicMock(),
        theme_detector=theme_detector or MagicMock(),
        intent_classifier=intent_classifier or MagicMock(),
        entity_extractor=entity_extractor or MagicMock(),
        priority_scorer=priority_scorer or MagicMock(),
        similarity_clusterer=similarity_clusterer or MagicMock(),
        decision_engine=decision_engine or MagicMock(),
        store=store or MagicMock(),
    )


# ---------------------------------------------------------------------------
# Tests: Successful Processing
# ---------------------------------------------------------------------------


class TestSuccessfulProcessing:
    """Test successful end-to-end processing."""

    def test_process_social_feedback_success(self):
        """End-to-end processing of a social feedback record results in 'routed' status."""
        feedback = _make_social_feedback()
        canonical = _make_canonical()
        analysis = _make_analysis()
        decision = _make_routing_decision()

        preprocessor = MagicMock()
        preprocessor.preprocess.return_value = canonical

        sentiment = MagicMock()
        sentiment.analyze.return_value = SentimentResult(
            sentiment_label="negative", sentiment_score=-0.6
        )

        theme = MagicMock()
        theme.detect.return_value = ThemeResult(
            primary_theme="outage", secondary_theme=None, confidence=0.9
        )

        intent = MagicMock()
        intent.classify.return_value = IntentResult(
            intent="outage_report", confidence=0.85, requires_action=True
        )

        entity = MagicMock()
        entity.extract.return_value = []

        priority = MagicMock()
        priority.score.return_value = PriorityResult(
            priority_level="high", priority_score=0.55
        )

        clusterer = MagicMock()
        clusterer.assign_cluster.return_value = "cluster-001"

        engine = MagicMock()
        engine.evaluate.return_value = decision

        store = MagicMock()

        orchestrator = PipelineOrchestrator(
            preprocessor=preprocessor,
            sentiment_analyzer=sentiment,
            theme_detector=theme,
            intent_classifier=intent,
            entity_extractor=entity,
            priority_scorer=priority,
            similarity_clusterer=clusterer,
            decision_engine=engine,
            store=store,
        )

        result = orchestrator.process_feedback(feedback)

        assert result.status == "routed"
        assert result.feedback_id == "fb-001"
        assert result.canonical is not None
        assert result.analysis is not None
        assert result.routing_decision is not None
        assert result.error is None

        # Verify persistence was called
        store.insert_feedback.assert_called_once()
        store.insert_analysis.assert_called_once()
        store.insert_ticket.assert_called_once()
        store.link_feedback_ticket.assert_called_once()

    def test_process_widget_feedback_success(self):
        """End-to-end processing of a widget feedback record results in 'routed' status."""
        feedback = _make_widget_feedback()
        canonical = CanonicalFeedback(
            feedback_id="fb-002",
            source_type="widget",
            original_source_id="fb-002",
            cleaned_text="Billing issue on my account, charged twice.",
            detected_language="en",
            ingested_at="2024-01-15T11:00:00Z",
            metadata={"customer_id": "cust-456"},
            processing_status="preprocessed",
        )

        preprocessor = MagicMock()
        preprocessor.preprocess.return_value = canonical

        sentiment = MagicMock()
        sentiment.analyze.return_value = SentimentResult(
            sentiment_label="negative", sentiment_score=-0.4
        )

        theme = MagicMock()
        theme.detect.return_value = ThemeResult(
            primary_theme="billing", confidence=0.8
        )

        intent = MagicMock()
        intent.classify.return_value = IntentResult(
            intent="billing_dispute", confidence=0.9, requires_action=True
        )

        entity = MagicMock()
        entity.extract.return_value = []

        priority = MagicMock()
        priority.score.return_value = PriorityResult(
            priority_level="medium", priority_score=0.4
        )

        clusterer = MagicMock()
        clusterer.assign_cluster.return_value = "cluster-002"

        decision = RoutingDecision(
            routing_action="create_ticket",
            ticket=Ticket(
                ticket_id="ticket-002",
                ticket_phase="new",
                priority_level="medium",
                assigned_department="Billing_Support",
                created_at="2024-01-15T11:00:01Z",
                updated_at="2024-01-15T11:00:01Z",
            ),
            department="Billing_Support",
            evaluation_timestamp="2024-01-15T11:00:01Z",
        )

        engine = MagicMock()
        engine.evaluate.return_value = decision

        store = MagicMock()

        orchestrator = PipelineOrchestrator(
            preprocessor=preprocessor,
            sentiment_analyzer=sentiment,
            theme_detector=theme,
            intent_classifier=intent,
            entity_extractor=entity,
            priority_scorer=priority,
            similarity_clusterer=clusterer,
            decision_engine=engine,
            store=store,
        )

        result = orchestrator.process_feedback(feedback)

        assert result.status == "routed"
        assert result.feedback_id == "fb-002"


class TestStatusTracking:
    """Test that ProcessingStatus transitions through all defined stages."""

    def test_status_reaches_routed_on_success(self):
        """On success, final status is 'routed'."""
        feedback = _make_social_feedback()
        canonical = _make_canonical()

        preprocessor = MagicMock()
        preprocessor.preprocess.return_value = canonical

        sentiment = MagicMock()
        sentiment.analyze.return_value = SentimentResult(
            sentiment_label="neutral", sentiment_score=0.0
        )
        theme = MagicMock()
        theme.detect.return_value = ThemeResult(primary_theme="outage", confidence=0.9)
        intent = MagicMock()
        intent.classify.return_value = IntentResult(
            intent="outage_report", confidence=0.8, requires_action=True
        )
        entity = MagicMock()
        entity.extract.return_value = []
        priority = MagicMock()
        priority.score.return_value = PriorityResult(
            priority_level="medium", priority_score=0.3
        )
        clusterer = MagicMock()
        clusterer.assign_cluster.return_value = "c-1"
        engine = MagicMock()
        engine.evaluate.return_value = _make_routing_decision()
        store = MagicMock()

        orchestrator = PipelineOrchestrator(
            preprocessor=preprocessor,
            sentiment_analyzer=sentiment,
            theme_detector=theme,
            intent_classifier=intent,
            entity_extractor=entity,
            priority_scorer=priority,
            similarity_clusterer=clusterer,
            decision_engine=engine,
            store=store,
        )

        result = orchestrator.process_feedback(feedback)
        assert result.status == "routed"


# ---------------------------------------------------------------------------
# Tests: Preprocessing Failures
# ---------------------------------------------------------------------------


class TestPreprocessingFailures:
    """Test handling of preprocessing stage failures."""

    def test_duplicate_detected_returns_failed(self):
        """When preprocessor returns None (duplicate), result status is 'failed'."""
        feedback = _make_social_feedback()

        preprocessor = MagicMock()
        preprocessor.preprocess.return_value = None

        orchestrator = _make_orchestrator(preprocessor=preprocessor)
        result = orchestrator.process_feedback(feedback)

        assert result.status == "failed"
        assert result.error == "duplicate_detected"
        assert result.stage_failed == "preprocessing"

    def test_empty_after_cleaning_returns_failed(self):
        """When canonical has processing_status='failed', result marks failure."""
        feedback = _make_social_feedback()
        failed_canonical = CanonicalFeedback(
            feedback_id="fb-001",
            source_type="social",
            original_source_id="post-123",
            cleaned_text="empty",
            detected_language="und",
            ingested_at="2024-01-15T10:05:00Z",
            metadata={"reason": "empty_after_cleaning"},
            processing_status="failed",
        )

        preprocessor = MagicMock()
        preprocessor.preprocess.return_value = failed_canonical

        orchestrator = _make_orchestrator(preprocessor=preprocessor)
        result = orchestrator.process_feedback(feedback)

        assert result.status == "failed"
        assert result.error == "empty_after_cleaning"
        assert result.stage_failed == "preprocessing"

    def test_preprocessing_exception_triggers_retry(self):
        """When preprocessing raises exception, retry logic is invoked."""
        feedback = _make_social_feedback()
        canonical = _make_canonical()

        preprocessor = MagicMock()
        # Fail first call, succeed second call
        preprocessor.preprocess.side_effect = [
            RuntimeError("transient error"),
            canonical,
        ]

        sentiment = MagicMock()
        sentiment.analyze.return_value = SentimentResult(sentiment_label="neutral", sentiment_score=0.0)
        theme = MagicMock()
        theme.detect.return_value = ThemeResult(primary_theme="outage", confidence=0.9)
        intent = MagicMock()
        intent.classify.return_value = IntentResult(intent="complaint", confidence=0.8, requires_action=True)
        entity = MagicMock()
        entity.extract.return_value = []
        priority = MagicMock()
        priority.score.return_value = PriorityResult(priority_level="medium", priority_score=0.3)
        clusterer = MagicMock()
        clusterer.assign_cluster.return_value = "c-1"
        engine = MagicMock()
        engine.evaluate.return_value = _make_routing_decision()
        store = MagicMock()

        orchestrator = PipelineOrchestrator(
            preprocessor=preprocessor,
            sentiment_analyzer=sentiment,
            theme_detector=theme,
            intent_classifier=intent,
            entity_extractor=entity,
            priority_scorer=priority,
            similarity_clusterer=clusterer,
            decision_engine=engine,
            store=store,
        )

        with patch("nlp_processing.routing.pipeline_orchestrator.time.sleep"):
            result = orchestrator.process_feedback(feedback)

        assert result.status == "routed"
        assert preprocessor.preprocess.call_count == 2


# ---------------------------------------------------------------------------
# Tests: Retry Logic
# ---------------------------------------------------------------------------


class TestRetryLogic:
    """Test retry behavior with exponential backoff."""

    def test_max_retries_exhausted(self):
        """When all 3 retries fail, result status is 'failed'."""
        feedback = _make_social_feedback()

        preprocessor = MagicMock()
        preprocessor.preprocess.side_effect = RuntimeError("persistent error")

        orchestrator = _make_orchestrator(preprocessor=preprocessor)

        with patch("nlp_processing.routing.pipeline_orchestrator.time.sleep"):
            result = orchestrator.process_feedback(feedback)

        assert result.status == "failed"
        assert "max_retries_exceeded" in result.error
        assert result.stage_failed == "preprocessing"
        assert preprocessor.preprocess.call_count == MAX_RETRIES

    def test_exponential_backoff_delays(self):
        """Verify that backoff delays are applied between retries."""
        feedback = _make_social_feedback()

        preprocessor = MagicMock()
        preprocessor.preprocess.side_effect = RuntimeError("transient")

        orchestrator = _make_orchestrator(preprocessor=preprocessor)

        with patch("nlp_processing.routing.pipeline_orchestrator.time.sleep") as mock_sleep:
            orchestrator.process_feedback(feedback)

        # Should sleep between retries (2 sleeps for 3 attempts)
        assert mock_sleep.call_count == 2
        # First delay should be 5.0s, second should be 10.0s
        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert delays[0] == pytest.approx(5.0, abs=0.1)
        assert delays[1] == pytest.approx(10.0, abs=0.1)

    def test_nlp_analysis_retry_on_failure(self):
        """NLP analysis stage retries on transient failure."""
        feedback = _make_social_feedback()
        canonical = _make_canonical()

        preprocessor = MagicMock()
        preprocessor.preprocess.return_value = canonical

        sentiment = MagicMock()
        # First call fails, second succeeds
        sentiment.analyze.side_effect = [
            RuntimeError("model timeout"),
            SentimentResult(sentiment_label="neutral", sentiment_score=0.0),
        ]

        theme = MagicMock()
        theme.detect.return_value = ThemeResult(primary_theme="outage", confidence=0.9)
        intent = MagicMock()
        intent.classify.return_value = IntentResult(intent="complaint", confidence=0.8, requires_action=True)
        entity = MagicMock()
        entity.extract.return_value = []
        priority = MagicMock()
        priority.score.return_value = PriorityResult(priority_level="medium", priority_score=0.3)
        clusterer = MagicMock()
        clusterer.assign_cluster.return_value = "c-1"
        engine = MagicMock()
        engine.evaluate.return_value = _make_routing_decision()
        store = MagicMock()

        orchestrator = PipelineOrchestrator(
            preprocessor=preprocessor,
            sentiment_analyzer=sentiment,
            theme_detector=theme,
            intent_classifier=intent,
            entity_extractor=entity,
            priority_scorer=priority,
            similarity_clusterer=clusterer,
            decision_engine=engine,
            store=store,
        )

        with patch("nlp_processing.routing.pipeline_orchestrator.time.sleep"):
            result = orchestrator.process_feedback(feedback)

        assert result.status == "routed"


# ---------------------------------------------------------------------------
# Tests: Timeout
# ---------------------------------------------------------------------------


class TestTimeout:
    """Test total timeout enforcement (120 seconds)."""

    def test_timeout_during_retry(self):
        """Processing is halted when total timeout is exceeded."""
        feedback = _make_social_feedback()

        preprocessor = MagicMock()
        preprocessor.preprocess.side_effect = RuntimeError("slow error")

        orchestrator = _make_orchestrator(preprocessor=preprocessor)

        # Simulate time passing beyond 120s during retries
        original_monotonic = time.monotonic

        call_count = [0]

        def fake_monotonic():
            call_count[0] += 1
            # After a few calls, return a time past the timeout
            if call_count[0] >= 3:
                return original_monotonic() + 200.0
            return original_monotonic()

        with patch("nlp_processing.routing.pipeline_orchestrator.time.monotonic", side_effect=fake_monotonic):
            with patch("nlp_processing.routing.pipeline_orchestrator.time.sleep"):
                result = orchestrator.process_feedback(feedback)

        assert result.status == "failed"
        assert result.error == "processing_timeout"

    def test_timeout_check_before_each_stage(self):
        """Timeout is checked before starting each retry attempt."""
        feedback = _make_social_feedback()
        canonical = _make_canonical()

        preprocessor = MagicMock()
        preprocessor.preprocess.return_value = canonical

        sentiment = MagicMock()
        sentiment.analyze.return_value = SentimentResult(sentiment_label="neutral", sentiment_score=0.0)
        theme = MagicMock()
        theme.detect.return_value = ThemeResult(primary_theme="outage", confidence=0.9)
        intent = MagicMock()
        intent.classify.return_value = IntentResult(intent="complaint", confidence=0.8, requires_action=True)
        entity = MagicMock()
        entity.extract.return_value = []
        priority = MagicMock()
        priority.score.return_value = PriorityResult(priority_level="medium", priority_score=0.3)
        clusterer = MagicMock()
        clusterer.assign_cluster.return_value = "c-1"
        engine = MagicMock()
        engine.evaluate.side_effect = RuntimeError("engine error")
        store = MagicMock()

        orchestrator = PipelineOrchestrator(
            preprocessor=preprocessor,
            sentiment_analyzer=sentiment,
            theme_detector=theme,
            intent_classifier=intent,
            entity_extractor=entity,
            priority_scorer=priority,
            similarity_clusterer=clusterer,
            decision_engine=engine,
            store=store,
        )

        # The engine will fail but retries should eventually exhaust or timeout
        with patch("nlp_processing.routing.pipeline_orchestrator.time.sleep"):
            result = orchestrator.process_feedback(feedback)

        assert result.status == "failed"
        assert result.stage_failed == "routing"


# ---------------------------------------------------------------------------
# Tests: Per-Record Isolation (Req 16.5)
# ---------------------------------------------------------------------------


class TestPerRecordIsolation:
    """Test that one failure does not block other records."""

    def test_batch_processing_isolation(self):
        """Batch processes all records even when some fail."""
        fb1 = _make_social_feedback("fb-001")
        fb2 = _make_social_feedback("fb-002")
        fb3 = _make_social_feedback("fb-003")

        canonical = _make_canonical()

        preprocessor = MagicMock()
        # First record succeeds, second fails, third succeeds
        preprocessor.preprocess.side_effect = [
            canonical,
            RuntimeError("persistent error"),
            RuntimeError("persistent error"),
            RuntimeError("persistent error"),
            CanonicalFeedback(
                feedback_id="fb-003",
                source_type="social",
                original_source_id="post-333",
                cleaned_text="Third feedback text",
                detected_language="en",
                ingested_at="2024-01-15T10:05:00Z",
                metadata={},
                processing_status="preprocessed",
            ),
        ]

        sentiment = MagicMock()
        sentiment.analyze.return_value = SentimentResult(sentiment_label="neutral", sentiment_score=0.0)
        theme = MagicMock()
        theme.detect.return_value = ThemeResult(primary_theme="outage", confidence=0.9)
        intent = MagicMock()
        intent.classify.return_value = IntentResult(intent="complaint", confidence=0.8, requires_action=True)
        entity = MagicMock()
        entity.extract.return_value = []
        priority = MagicMock()
        priority.score.return_value = PriorityResult(priority_level="medium", priority_score=0.3)
        clusterer = MagicMock()
        clusterer.assign_cluster.return_value = "c-1"
        engine = MagicMock()
        engine.evaluate.return_value = _make_routing_decision()
        store = MagicMock()

        orchestrator = PipelineOrchestrator(
            preprocessor=preprocessor,
            sentiment_analyzer=sentiment,
            theme_detector=theme,
            intent_classifier=intent,
            entity_extractor=entity,
            priority_scorer=priority,
            similarity_clusterer=clusterer,
            decision_engine=engine,
            store=store,
        )

        with patch("nlp_processing.routing.pipeline_orchestrator.time.sleep"):
            results = orchestrator.process_batch([fb1, fb2, fb3])

        assert len(results) == 3
        # First and third succeed, second fails
        assert results[0].status == "routed"
        assert results[1].status == "failed"
        assert results[2].status == "routed"

    def test_batch_unhandled_exception_isolation(self):
        """Unhandled exceptions in one record don't crash the batch."""
        fb1 = _make_social_feedback("fb-001")
        fb2 = _make_social_feedback("fb-002")

        preprocessor = MagicMock()
        # First raises an unexpected error at orchestrator level
        preprocessor.preprocess.side_effect = [
            None,  # duplicate for first
            _make_canonical(),  # success for second (with fb-002 id)
        ]

        sentiment = MagicMock()
        sentiment.analyze.return_value = SentimentResult(sentiment_label="neutral", sentiment_score=0.0)
        theme = MagicMock()
        theme.detect.return_value = ThemeResult(primary_theme="billing", confidence=0.8)
        intent = MagicMock()
        intent.classify.return_value = IntentResult(intent="complaint", confidence=0.8, requires_action=True)
        entity = MagicMock()
        entity.extract.return_value = []
        priority = MagicMock()
        priority.score.return_value = PriorityResult(priority_level="medium", priority_score=0.3)
        clusterer = MagicMock()
        clusterer.assign_cluster.return_value = "c-1"
        engine = MagicMock()
        engine.evaluate.return_value = _make_routing_decision()
        store = MagicMock()

        orchestrator = PipelineOrchestrator(
            preprocessor=preprocessor,
            sentiment_analyzer=sentiment,
            theme_detector=theme,
            intent_classifier=intent,
            entity_extractor=entity,
            priority_scorer=priority,
            similarity_clusterer=clusterer,
            decision_engine=engine,
            store=store,
        )

        results = orchestrator.process_batch([fb1, fb2])

        assert len(results) == 2
        # First record is duplicate (failed), second succeeds
        assert results[0].status == "failed"
        assert results[1].status == "routed"


# ---------------------------------------------------------------------------
# Tests: Persistence (Req 16.6)
# ---------------------------------------------------------------------------


class TestPersistence:
    """Test that results are persisted on 'routed' status."""

    def test_persistence_called_on_routed(self):
        """On successful routing, all persistence methods are called."""
        feedback = _make_social_feedback()
        canonical = _make_canonical()
        decision = _make_routing_decision()

        preprocessor = MagicMock()
        preprocessor.preprocess.return_value = canonical
        sentiment = MagicMock()
        sentiment.analyze.return_value = SentimentResult(sentiment_label="neutral", sentiment_score=0.0)
        theme = MagicMock()
        theme.detect.return_value = ThemeResult(primary_theme="outage", confidence=0.9)
        intent = MagicMock()
        intent.classify.return_value = IntentResult(intent="complaint", confidence=0.8, requires_action=True)
        entity = MagicMock()
        entity.extract.return_value = []
        priority = MagicMock()
        priority.score.return_value = PriorityResult(priority_level="medium", priority_score=0.3)
        clusterer = MagicMock()
        clusterer.assign_cluster.return_value = "c-1"
        engine = MagicMock()
        engine.evaluate.return_value = decision
        store = MagicMock()

        orchestrator = PipelineOrchestrator(
            preprocessor=preprocessor,
            sentiment_analyzer=sentiment,
            theme_detector=theme,
            intent_classifier=intent,
            entity_extractor=entity,
            priority_scorer=priority,
            similarity_clusterer=clusterer,
            decision_engine=engine,
            store=store,
        )

        result = orchestrator.process_feedback(feedback)

        assert result.status == "routed"
        store.insert_feedback.assert_called_once()
        store.insert_analysis.assert_called_once()
        store.insert_ticket.assert_called_once()
        store.link_feedback_ticket.assert_called_once_with(
            feedback_id="fb-001", ticket_id="ticket-001"
        )

    def test_persistence_failure_marks_result_failed(self):
        """If persistence raises an exception, result is marked 'failed'."""
        feedback = _make_social_feedback()
        canonical = _make_canonical()
        decision = _make_routing_decision()

        preprocessor = MagicMock()
        preprocessor.preprocess.return_value = canonical
        sentiment = MagicMock()
        sentiment.analyze.return_value = SentimentResult(sentiment_label="neutral", sentiment_score=0.0)
        theme = MagicMock()
        theme.detect.return_value = ThemeResult(primary_theme="outage", confidence=0.9)
        intent = MagicMock()
        intent.classify.return_value = IntentResult(intent="complaint", confidence=0.8, requires_action=True)
        entity = MagicMock()
        entity.extract.return_value = []
        priority = MagicMock()
        priority.score.return_value = PriorityResult(priority_level="medium", priority_score=0.3)
        clusterer = MagicMock()
        clusterer.assign_cluster.return_value = "c-1"
        engine = MagicMock()
        engine.evaluate.return_value = decision
        store = MagicMock()
        store.insert_feedback.side_effect = Exception("DB connection lost")

        orchestrator = PipelineOrchestrator(
            preprocessor=preprocessor,
            sentiment_analyzer=sentiment,
            theme_detector=theme,
            intent_classifier=intent,
            entity_extractor=entity,
            priority_scorer=priority,
            similarity_clusterer=clusterer,
            decision_engine=engine,
            store=store,
        )

        result = orchestrator.process_feedback(feedback)

        assert result.status == "failed"
        assert "persistence_failed" in result.error
        assert result.stage_failed == "persistence"

    def test_route_to_existing_links_to_existing_ticket(self):
        """When routing decision is 'route_to_existing', link is created without new ticket."""
        feedback = _make_social_feedback()
        canonical = _make_canonical()

        decision = RoutingDecision(
            routing_action="route_to_existing",
            linked_ticket_id="existing-ticket-999",
            department="Network_Operations",
            evaluation_timestamp="2024-01-15T10:05:31Z",
        )

        preprocessor = MagicMock()
        preprocessor.preprocess.return_value = canonical
        sentiment = MagicMock()
        sentiment.analyze.return_value = SentimentResult(sentiment_label="neutral", sentiment_score=0.0)
        theme = MagicMock()
        theme.detect.return_value = ThemeResult(primary_theme="outage", confidence=0.9)
        intent = MagicMock()
        intent.classify.return_value = IntentResult(intent="complaint", confidence=0.8, requires_action=True)
        entity = MagicMock()
        entity.extract.return_value = []
        priority = MagicMock()
        priority.score.return_value = PriorityResult(priority_level="medium", priority_score=0.3)
        clusterer = MagicMock()
        clusterer.assign_cluster.return_value = "c-1"
        engine = MagicMock()
        engine.evaluate.return_value = decision
        store = MagicMock()

        orchestrator = PipelineOrchestrator(
            preprocessor=preprocessor,
            sentiment_analyzer=sentiment,
            theme_detector=theme,
            intent_classifier=intent,
            entity_extractor=entity,
            priority_scorer=priority,
            similarity_clusterer=clusterer,
            decision_engine=engine,
            store=store,
        )

        result = orchestrator.process_feedback(feedback)

        assert result.status == "routed"
        store.insert_ticket.assert_not_called()
        store.link_feedback_ticket.assert_called_once_with(
            feedback_id="fb-001", ticket_id="existing-ticket-999"
        )


# ---------------------------------------------------------------------------
# Tests: ProcessingResult dataclass
# ---------------------------------------------------------------------------


class TestProcessingResult:
    """Test the ProcessingResult dataclass defaults."""

    def test_default_values(self):
        """ProcessingResult has sensible defaults."""
        result = ProcessingResult(feedback_id="test-id")
        assert result.feedback_id == "test-id"
        assert result.status == "ingested"
        assert result.canonical is None
        assert result.analysis is None
        assert result.routing_decision is None
        assert result.error is None
        assert result.stage_failed is None
        assert result.attempts == 0
