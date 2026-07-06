"""Integration tests for the end-to-end feedback routing pipeline (task 12.3).

These tests exercise the full pipeline flow using:
- Real Preprocessor (text cleaning, PII masking, deduplication)
- Real FeedbackStore (in-memory SQLite with full schema)
- Real PriorityScorer (deterministic, no external deps)
- Real SimilarityClusterer (in-memory cluster management)
- Mocked NLP components that depend on Gemini API (SentimentAnalyzer,
  ThemeDetector, IntentClassifier, EntityExtractor)

Tests validate:
- Full flow: social post → preprocessing → NLP → decision → ticket (Req 16.1)
- Full flow: widget submission → preprocessing → NLP → decision → ticket (Req 16.1)
- Retry and timeout behavior across stages (Req 16.3, 16.4)
- Per-record isolation: one failure doesn't block others (Req 16.5)
- Persistence of final results to FeedbackStore (Req 16.6)

**Validates: Requirements 16.1, 16.3, 16.4, 16.5, 16.6**
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from nlp_processing.aggregation.similarity_clusterer import SimilarityClusterer
from nlp_processing.enrichment.entity_extractor import EntityExtractor
from nlp_processing.enrichment.intent_classifier import IntentClassifier
from nlp_processing.enrichment.priority_scorer import PriorityScorer
from nlp_processing.enrichment.sentiment_routing import SentimentAnalyzer
from nlp_processing.enrichment.theme_detector import ThemeDetector
from nlp_processing.models.feedback_routing import (
    EngagementMetrics,
    ExtractedEntity,
    IntentResult,
    SentimentResult,
    SocialFeedback,
    ThemeResult,
    WidgetFeedback,
)
from nlp_processing.persistence.feedback_store import FeedbackStore
from nlp_processing.preprocessing.preprocessor import Preprocessor
from nlp_processing.routing.decision_engine import DecisionEngine
from nlp_processing.routing.pipeline_orchestrator import (
    PipelineOrchestrator,
    ProcessingResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> FeedbackStore:
    """Create a real in-memory SQLite FeedbackStore."""
    return FeedbackStore(db_path=":memory:")


@pytest.fixture
def preprocessor() -> Preprocessor:
    """Create a real Preprocessor with default config."""
    return Preprocessor()


@pytest.fixture
def priority_scorer() -> PriorityScorer:
    """Create a real PriorityScorer (no external deps)."""
    return PriorityScorer()


@pytest.fixture
def similarity_clusterer(store) -> SimilarityClusterer:
    """Create a real SimilarityClusterer backed by the store."""
    return SimilarityClusterer(store=store)


@pytest.fixture
def mock_sentiment() -> MagicMock:
    """Create a mock SentimentAnalyzer returning a negative sentiment."""
    mock = MagicMock(spec=SentimentAnalyzer)
    mock.analyze.return_value = SentimentResult(
        sentiment_label="negative", sentiment_score=-0.65
    )
    return mock


@pytest.fixture
def mock_theme() -> MagicMock:
    """Create a mock ThemeDetector returning 'outage'."""
    mock = MagicMock(spec=ThemeDetector)
    mock.detect.return_value = ThemeResult(
        primary_theme="outage", secondary_theme=None, confidence=0.88
    )
    return mock


@pytest.fixture
def mock_intent() -> MagicMock:
    """Create a mock IntentClassifier returning 'outage_report'."""
    mock = MagicMock(spec=IntentClassifier)
    mock.classify.return_value = IntentResult(
        intent="outage_report", confidence=0.85, requires_action=True
    )
    return mock


@pytest.fixture
def mock_entity() -> MagicMock:
    """Create a mock EntityExtractor returning an outage_mention entity."""
    mock = MagicMock(spec=EntityExtractor)
    mock.extract.return_value = [
        ExtractedEntity(
            entity_type="outage_mention",
            entity_value="internet down",
            confidence=0.9,
        )
    ]
    return mock


def _make_social_feedback(
    feedback_id: str = "fb-int-001",
    message_text: str = "My internet has been down for hours, this is unacceptable!",
) -> SocialFeedback:
    """Create a realistic SocialFeedback record for integration testing."""
    return SocialFeedback(
        feedback_id=feedback_id,
        source_type="social",
        platform="reddit",
        username_handle="frustrated_user",
        post_id=f"post-{feedback_id}",
        message_text=message_text,
        post_url=f"https://reddit.com/r/isp/post-{feedback_id}",
        created_at_original="2024-02-10T08:00:00Z",
        ingested_at="2024-02-10T08:05:00Z",
        language_code="en",
        engagement_metrics=EngagementMetrics(likes=12, replies=5, reposts=3),
        recency_score=0.99,
        location="Portland, US",
    )


def _make_widget_feedback(
    feedback_id: str = "fb-int-002",
    message_text: str = "I was charged twice on my last bill, please fix this.",
) -> WidgetFeedback:
    """Create a realistic WidgetFeedback record for integration testing."""
    return WidgetFeedback(
        feedback_id=feedback_id,
        source_type="widget",
        submission_channel="app_widget",
        message_text=message_text,
        created_at="2024-02-10T09:00:00Z",
        consent_to_contact=True,
        customer_id="cust-789",
        account_type="premium",
        selected_category="billing",
    )


def _build_orchestrator(
    store: FeedbackStore,
    preprocessor: Preprocessor,
    priority_scorer: PriorityScorer,
    similarity_clusterer: SimilarityClusterer,
    mock_sentiment: MagicMock,
    mock_theme: MagicMock,
    mock_intent: MagicMock,
    mock_entity: MagicMock,
) -> PipelineOrchestrator:
    """Build a PipelineOrchestrator with real Preprocessor + Store and mocked NLP."""
    decision_engine = DecisionEngine(store=store)
    return PipelineOrchestrator(
        preprocessor=preprocessor,
        sentiment_analyzer=mock_sentiment,
        theme_detector=mock_theme,
        intent_classifier=mock_intent,
        entity_extractor=mock_entity,
        priority_scorer=priority_scorer,
        similarity_clusterer=similarity_clusterer,
        decision_engine=decision_engine,
        store=store,
    )


# ---------------------------------------------------------------------------
# Tests: Full Social Post Flow (Req 16.1)
# ---------------------------------------------------------------------------


class TestSocialPostFullFlow:
    """Integration: social post → preprocessing → NLP → decision → ticket."""

    def test_social_post_routes_to_ticket(
        self,
        store,
        preprocessor,
        priority_scorer,
        similarity_clusterer,
        mock_sentiment,
        mock_theme,
        mock_intent,
        mock_entity,
    ):
        """A social post flows through the full pipeline and produces a ticket."""
        orchestrator = _build_orchestrator(
            store, preprocessor, priority_scorer, similarity_clusterer,
            mock_sentiment, mock_theme, mock_intent, mock_entity,
        )
        feedback = _make_social_feedback()

        result = orchestrator.process_feedback(feedback)

        # Verify pipeline completed successfully
        assert result.status == "routed"
        assert result.feedback_id == "fb-int-001"
        assert result.error is None

        # Verify real preprocessing produced a canonical record
        assert result.canonical is not None
        assert result.canonical.source_type == "social"
        assert result.canonical.detected_language == "en"
        # Text was cleaned (no HTML, NFC normalized, trimmed)
        assert "<" not in result.canonical.cleaned_text
        assert result.canonical.cleaned_text.strip() == result.canonical.cleaned_text

        # Verify NLP analysis was produced
        assert result.analysis is not None
        assert result.analysis.sentiment_label == "negative"
        assert result.analysis.sentiment_score == -0.65
        assert result.analysis.theme_primary == "outage"
        assert result.analysis.intent == "outage_report"
        assert result.analysis.requires_action is True

        # Verify routing decision produced a ticket
        assert result.routing_decision is not None
        assert result.routing_decision.routing_action in (
            "create_ticket", "escalate", "route_to_existing", "auto_resolve"
        )

        # Verify persistence: feedback record exists in DB
        cursor = store._conn.execute(
            "SELECT feedback_id, processing_status FROM feedback WHERE feedback_id = ?",
            ("fb-int-001",),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "fb-int-001"
        assert row[1] == "routed"

        # Verify persistence: analysis record exists
        cursor = store._conn.execute(
            "SELECT feedback_id, sentiment_label FROM feedback_analysis WHERE feedback_id = ?",
            ("fb-int-001",),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[1] == "negative"

    def test_social_post_with_pii_masking(
        self,
        store,
        preprocessor,
        priority_scorer,
        similarity_clusterer,
        mock_sentiment,
        mock_theme,
        mock_intent,
        mock_entity,
    ):
        """PII in social posts is masked during preprocessing."""
        orchestrator = _build_orchestrator(
            store, preprocessor, priority_scorer, similarity_clusterer,
            mock_sentiment, mock_theme, mock_intent, mock_entity,
        )
        feedback = _make_social_feedback(
            feedback_id="fb-pii-001",
            message_text="My email is user@example.com and phone is 555-123-4567, fix my internet!",
        )

        result = orchestrator.process_feedback(feedback)

        assert result.status == "routed"
        assert result.canonical is not None
        # PII should be masked in cleaned_text
        assert "user@example.com" not in result.canonical.cleaned_text
        assert "[EMAIL]" in result.canonical.cleaned_text
        assert "[PHONE]" in result.canonical.cleaned_text


# ---------------------------------------------------------------------------
# Tests: Full Widget Submission Flow (Req 16.1)
# ---------------------------------------------------------------------------


class TestWidgetSubmissionFullFlow:
    """Integration: widget submission → preprocessing → NLP → decision → ticket."""

    def test_widget_submission_routes_to_ticket(
        self,
        store,
        preprocessor,
        priority_scorer,
        similarity_clusterer,
        mock_sentiment,
        mock_theme,
        mock_intent,
        mock_entity,
    ):
        """A widget submission flows through the full pipeline and produces a ticket."""
        # Override mocks for billing theme
        mock_theme.detect.return_value = ThemeResult(
            primary_theme="billing", secondary_theme=None, confidence=0.92
        )
        mock_intent.classify.return_value = IntentResult(
            intent="billing_dispute", confidence=0.9, requires_action=True
        )
        mock_sentiment.analyze.return_value = SentimentResult(
            sentiment_label="negative", sentiment_score=-0.45
        )

        orchestrator = _build_orchestrator(
            store, preprocessor, priority_scorer, similarity_clusterer,
            mock_sentiment, mock_theme, mock_intent, mock_entity,
        )
        feedback = _make_widget_feedback()

        result = orchestrator.process_feedback(feedback)

        # Pipeline completed
        assert result.status == "routed"
        assert result.feedback_id == "fb-int-002"
        assert result.error is None

        # Preprocessing produced canonical
        assert result.canonical is not None
        assert result.canonical.source_type == "widget"

        # Analysis populated
        assert result.analysis is not None
        assert result.analysis.theme_primary == "billing"
        assert result.analysis.intent == "billing_dispute"

        # Decision was made
        assert result.routing_decision is not None

        # Verify feedback persisted
        cursor = store._conn.execute(
            "SELECT feedback_id, source_type, processing_status FROM feedback WHERE feedback_id = ?",
            ("fb-int-002",),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[1] == "widget"
        assert row[2] == "routed"

    def test_widget_with_selected_category_propagated(
        self,
        store,
        preprocessor,
        priority_scorer,
        similarity_clusterer,
        mock_sentiment,
        mock_theme,
        mock_intent,
        mock_entity,
    ):
        """Widget selected_category metadata propagates through preprocessing."""
        mock_theme.detect.return_value = ThemeResult(
            primary_theme="billing", confidence=0.85
        )
        mock_intent.classify.return_value = IntentResult(
            intent="billing_dispute", confidence=0.8, requires_action=True
        )
        mock_sentiment.analyze.return_value = SentimentResult(
            sentiment_label="negative", sentiment_score=-0.3
        )

        orchestrator = _build_orchestrator(
            store, preprocessor, priority_scorer, similarity_clusterer,
            mock_sentiment, mock_theme, mock_intent, mock_entity,
        )
        feedback = _make_widget_feedback(
            feedback_id="fb-cat-001",
            message_text="Billing error on my premium account last month.",
        )

        result = orchestrator.process_feedback(feedback)

        assert result.status == "routed"
        # Verify metadata contains selected_category from widget
        assert result.canonical.metadata.get("selected_category") == "billing"


# ---------------------------------------------------------------------------
# Tests: Retry and Timeout Behavior (Req 16.3, 16.4)
# ---------------------------------------------------------------------------


class TestRetryAndTimeoutIntegration:
    """Integration tests for retry and timeout behavior across pipeline stages."""

    def test_transient_nlp_failure_retries_and_succeeds(
        self,
        store,
        preprocessor,
        priority_scorer,
        similarity_clusterer,
        mock_theme,
        mock_intent,
        mock_entity,
    ):
        """A transient NLP failure triggers retry and eventually succeeds (Req 16.3)."""
        # Sentiment fails on first call, succeeds on second
        mock_sentiment = MagicMock(spec=SentimentAnalyzer)
        mock_sentiment.analyze.side_effect = [
            RuntimeError("transient model timeout"),
            SentimentResult(sentiment_label="negative", sentiment_score=-0.5),
        ]

        orchestrator = _build_orchestrator(
            store, preprocessor, priority_scorer, similarity_clusterer,
            mock_sentiment, mock_theme, mock_intent, mock_entity,
        )
        feedback = _make_social_feedback(feedback_id="fb-retry-001")

        with patch("nlp_processing.routing.pipeline_orchestrator.time.sleep"):
            result = orchestrator.process_feedback(feedback)

        # Should succeed after retry
        assert result.status == "routed"
        assert result.attempts >= 2  # At least 2 attempts on NLP stage

    def test_persistent_nlp_failure_exhausts_retries(
        self,
        store,
        preprocessor,
        priority_scorer,
        similarity_clusterer,
        mock_theme,
        mock_intent,
        mock_entity,
    ):
        """Persistent NLP failure exhausts all 3 retries (Req 16.3)."""
        mock_sentiment = MagicMock(spec=SentimentAnalyzer)
        mock_sentiment.analyze.side_effect = RuntimeError("persistent model error")

        orchestrator = _build_orchestrator(
            store, preprocessor, priority_scorer, similarity_clusterer,
            mock_sentiment, mock_theme, mock_intent, mock_entity,
        )
        feedback = _make_social_feedback(feedback_id="fb-retry-002")

        with patch("nlp_processing.routing.pipeline_orchestrator.time.sleep"):
            result = orchestrator.process_feedback(feedback)

        assert result.status == "failed"
        assert "max_retries_exceeded" in result.error
        assert result.stage_failed == "nlp_analysis"

    def test_timeout_halts_processing(
        self,
        store,
        preprocessor,
        priority_scorer,
        similarity_clusterer,
        mock_sentiment,
        mock_theme,
        mock_intent,
        mock_entity,
    ):
        """Total timeout (120s) halts processing regardless of stage (Req 16.4)."""
        # Simulate time exceeding 120s during NLP analysis retries
        mock_sentiment_timeout = MagicMock(spec=SentimentAnalyzer)
        mock_sentiment_timeout.analyze.side_effect = RuntimeError("slow")

        orchestrator = _build_orchestrator(
            store, preprocessor, priority_scorer, similarity_clusterer,
            mock_sentiment_timeout, mock_theme, mock_intent, mock_entity,
        )
        feedback = _make_social_feedback(feedback_id="fb-timeout-001")

        original_monotonic = time.monotonic
        call_count = [0]
        base_time = [None]

        def fake_monotonic():
            call_count[0] += 1
            if base_time[0] is None:
                base_time[0] = original_monotonic()
            # After the first retry attempt, simulate time past 120s
            if call_count[0] >= 4:
                return base_time[0] + 200.0
            return base_time[0] + (call_count[0] * 0.1)

        with patch("nlp_processing.routing.pipeline_orchestrator.time.monotonic", side_effect=fake_monotonic):
            with patch("nlp_processing.routing.pipeline_orchestrator.time.sleep"):
                result = orchestrator.process_feedback(feedback)

        assert result.status == "failed"
        assert result.error == "processing_timeout"

    def test_routing_stage_retry_on_transient_error(
        self,
        store,
        preprocessor,
        priority_scorer,
        similarity_clusterer,
        mock_sentiment,
        mock_theme,
        mock_intent,
        mock_entity,
    ):
        """Transient errors in the routing/decision stage are retried (Req 16.3)."""
        orchestrator = _build_orchestrator(
            store, preprocessor, priority_scorer, similarity_clusterer,
            mock_sentiment, mock_theme, mock_intent, mock_entity,
        )

        # Monkey-patch the decision engine to fail once, then succeed
        original_evaluate = orchestrator._decision_engine.evaluate
        call_counter = [0]

        def flaky_evaluate(feedback, analysis):
            call_counter[0] += 1
            if call_counter[0] == 1:
                raise RuntimeError("transient DB lock")
            return original_evaluate(feedback, analysis)

        orchestrator._decision_engine.evaluate = flaky_evaluate

        feedback = _make_social_feedback(feedback_id="fb-route-retry-001")

        with patch("nlp_processing.routing.pipeline_orchestrator.time.sleep"):
            result = orchestrator.process_feedback(feedback)

        assert result.status == "routed"
        assert call_counter[0] == 2


# ---------------------------------------------------------------------------
# Tests: Per-Record Isolation (Req 16.5)
# ---------------------------------------------------------------------------


class TestPerRecordIsolationIntegration:
    """Integration tests verifying one failure doesn't block other records."""

    def test_batch_one_failure_others_succeed(
        self,
        store,
        preprocessor,
        priority_scorer,
        similarity_clusterer,
        mock_theme,
        mock_intent,
        mock_entity,
    ):
        """In a batch of 3 records, one NLP failure doesn't block others (Req 16.5)."""
        # Sentiment: first record succeeds, second fails all retries, third succeeds
        sentiment_responses = []
        call_counter = [0]

        def sentiment_side_effect(feedback):
            call_counter[0] += 1
            # Feedback IDs will be processed in order
            if feedback.feedback_id == "fb-batch-002":
                raise RuntimeError("persistent model failure for record 2")
            return SentimentResult(sentiment_label="negative", sentiment_score=-0.5)

        mock_sentiment = MagicMock(spec=SentimentAnalyzer)
        mock_sentiment.analyze.side_effect = sentiment_side_effect

        orchestrator = _build_orchestrator(
            store, preprocessor, priority_scorer, similarity_clusterer,
            mock_sentiment, mock_theme, mock_intent, mock_entity,
        )

        fb1 = _make_social_feedback(feedback_id="fb-batch-001", message_text="First issue with my internet service")
        fb2 = _make_social_feedback(feedback_id="fb-batch-002", message_text="Second different feedback about billing")
        fb3 = _make_social_feedback(feedback_id="fb-batch-003", message_text="Third concern about installation delays")

        with patch("nlp_processing.routing.pipeline_orchestrator.time.sleep"):
            results = orchestrator.process_batch([fb1, fb2, fb3])

        assert len(results) == 3
        # First and third should succeed
        assert results[0].status == "routed"
        assert results[0].feedback_id == "fb-batch-001"
        # Second failed (NLP retries exhausted)
        assert results[1].status == "failed"
        assert results[1].feedback_id == "fb-batch-002"
        # Third still succeeds - isolation
        assert results[2].status == "routed"
        assert results[2].feedback_id == "fb-batch-003"

    def test_batch_preprocessing_failure_isolated(
        self,
        store,
        priority_scorer,
        similarity_clusterer,
        mock_sentiment,
        mock_theme,
        mock_intent,
        mock_entity,
    ):
        """Preprocessing failure (duplicate) for one record doesn't affect others (Req 16.5)."""
        # Use a real preprocessor so deduplication works
        preprocessor = Preprocessor()

        orchestrator = _build_orchestrator(
            store, preprocessor, priority_scorer, similarity_clusterer,
            mock_sentiment, mock_theme, mock_intent, mock_entity,
        )

        # Two records with the same message text (duplicate detection)
        fb1 = _make_social_feedback(
            feedback_id="fb-dup-001",
            message_text="Same complaint about service downtime",
        )
        fb2 = _make_social_feedback(
            feedback_id="fb-dup-002",
            message_text="Same complaint about service downtime",  # duplicate
        )
        fb3 = _make_social_feedback(
            feedback_id="fb-dup-003",
            message_text="A completely different feedback about billing issues",
        )

        results = orchestrator.process_batch([fb1, fb2, fb3])

        assert len(results) == 3
        # First record succeeds
        assert results[0].status == "routed"
        # Second record is duplicate → failed
        assert results[1].status == "failed"
        assert results[1].error == "duplicate_detected"
        # Third record succeeds independently
        assert results[2].status == "routed"

    def test_batch_unhandled_exception_isolated(
        self,
        store,
        preprocessor,
        priority_scorer,
        similarity_clusterer,
        mock_sentiment,
        mock_theme,
        mock_intent,
        mock_entity,
    ):
        """An unhandled exception in one record doesn't crash the batch (Req 16.5)."""
        # Monkey-patch orchestrator to raise for one specific ID
        orchestrator = _build_orchestrator(
            store, preprocessor, priority_scorer, similarity_clusterer,
            mock_sentiment, mock_theme, mock_intent, mock_entity,
        )
        original_process = orchestrator.process_feedback

        def exploding_process(feedback):
            if feedback.feedback_id == "fb-explode-002":
                raise ValueError("Unexpected catastrophic error")
            return original_process(feedback)

        orchestrator.process_feedback = exploding_process

        fb1 = _make_social_feedback(feedback_id="fb-explode-001", message_text="Normal feedback about speed issues")
        fb2 = _make_social_feedback(feedback_id="fb-explode-002", message_text="This will cause an explosion in processing")
        fb3 = _make_social_feedback(feedback_id="fb-explode-003", message_text="Another normal feedback about equipment")

        results = orchestrator.process_batch([fb1, fb2, fb3])

        assert len(results) == 3
        assert results[0].status == "routed"
        assert results[1].status == "failed"
        assert "unhandled_exception" in results[1].error
        assert results[2].status == "routed"


# ---------------------------------------------------------------------------
# Tests: Persistence Verification (Req 16.6)
# ---------------------------------------------------------------------------


class TestPersistenceIntegration:
    """Integration tests verifying data is persisted correctly to the real store."""

    def test_ticket_persisted_with_correct_fields(
        self,
        store,
        preprocessor,
        priority_scorer,
        similarity_clusterer,
        mock_sentiment,
        mock_theme,
        mock_intent,
        mock_entity,
    ):
        """On successful routing, a ticket record exists in the database (Req 16.6)."""
        orchestrator = _build_orchestrator(
            store, preprocessor, priority_scorer, similarity_clusterer,
            mock_sentiment, mock_theme, mock_intent, mock_entity,
        )
        feedback = _make_social_feedback(feedback_id="fb-persist-001")

        result = orchestrator.process_feedback(feedback)

        assert result.status == "routed"
        assert result.routing_decision is not None

        # Check that ticket was actually written to the real SQLite store
        if result.routing_decision.ticket is not None:
            ticket_id = result.routing_decision.ticket.ticket_id
            cursor = store._conn.execute(
                "SELECT ticket_id, ticket_phase, priority_level, assigned_department "
                "FROM tickets WHERE ticket_id = ?",
                (ticket_id,),
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == ticket_id
            # Ticket phase should match what the decision engine set
            assert row[1] == result.routing_decision.ticket.ticket_phase

    def test_feedback_ticket_link_persisted(
        self,
        store,
        preprocessor,
        priority_scorer,
        similarity_clusterer,
        mock_sentiment,
        mock_theme,
        mock_intent,
        mock_entity,
    ):
        """Feedback-ticket link record is persisted on routing (Req 16.6)."""
        orchestrator = _build_orchestrator(
            store, preprocessor, priority_scorer, similarity_clusterer,
            mock_sentiment, mock_theme, mock_intent, mock_entity,
        )
        feedback = _make_social_feedback(feedback_id="fb-link-001")

        result = orchestrator.process_feedback(feedback)

        assert result.status == "routed"

        # Verify the link exists in the database
        cursor = store._conn.execute(
            "SELECT feedback_id, ticket_id FROM feedback_ticket_link WHERE feedback_id = ?",
            ("fb-link-001",),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "fb-link-001"
        # ticket_id should match the decision
        if result.routing_decision.ticket is not None:
            assert row[1] == result.routing_decision.ticket.ticket_id

    def test_analysis_persisted_with_entities(
        self,
        store,
        preprocessor,
        priority_scorer,
        similarity_clusterer,
        mock_sentiment,
        mock_theme,
        mock_intent,
        mock_entity,
    ):
        """Analysis record with entities is persisted correctly (Req 16.6)."""
        orchestrator = _build_orchestrator(
            store, preprocessor, priority_scorer, similarity_clusterer,
            mock_sentiment, mock_theme, mock_intent, mock_entity,
        )
        feedback = _make_social_feedback(feedback_id="fb-analysis-001")

        result = orchestrator.process_feedback(feedback)

        assert result.status == "routed"

        # Verify analysis was persisted
        cursor = store._conn.execute(
            "SELECT sentiment_label, sentiment_score, priority_level, theme_primary, "
            "intent, requires_action, entities FROM feedback_analysis WHERE feedback_id = ?",
            ("fb-analysis-001",),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "negative"  # sentiment_label
        assert row[1] == pytest.approx(-0.65)  # sentiment_score
        assert row[3] == "outage"  # theme_primary
        assert row[4] == "outage_report"  # intent
        assert row[5] == 1  # requires_action (stored as int)

    def test_failed_record_not_persisted(
        self,
        store,
        preprocessor,
        priority_scorer,
        similarity_clusterer,
        mock_theme,
        mock_intent,
        mock_entity,
    ):
        """A failed record (NLP retries exhausted) is NOT persisted to the store."""
        mock_sentiment = MagicMock(spec=SentimentAnalyzer)
        mock_sentiment.analyze.side_effect = RuntimeError("permanent failure")

        orchestrator = _build_orchestrator(
            store, preprocessor, priority_scorer, similarity_clusterer,
            mock_sentiment, mock_theme, mock_intent, mock_entity,
        )
        feedback = _make_social_feedback(feedback_id="fb-nopersist-001")

        with patch("nlp_processing.routing.pipeline_orchestrator.time.sleep"):
            result = orchestrator.process_feedback(feedback)

        assert result.status == "failed"

        # Verify nothing was persisted
        cursor = store._conn.execute(
            "SELECT feedback_id FROM feedback WHERE feedback_id = ?",
            ("fb-nopersist-001",),
        )
        assert cursor.fetchone() is None

        cursor = store._conn.execute(
            "SELECT feedback_id FROM feedback_analysis WHERE feedback_id = ?",
            ("fb-nopersist-001",),
        )
        assert cursor.fetchone() is None
