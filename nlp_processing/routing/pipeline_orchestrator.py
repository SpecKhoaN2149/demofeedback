"""Pipeline Orchestrator: end-to-end feedback processing coordination (task 8.1).

The :class:`PipelineOrchestrator` coordinates the full processing pipeline for
a single feedback record through the stages:

    ingestion → preprocessing → NLP analysis → decision routing

It tracks :data:`ProcessingStatus` through each stage transition:

    ingested → preprocessing → preprocessed → analyzing → analyzed → routing → routed

Business rules (Requirements 16.1–16.7):

* Req 16.1: Orchestrate the complete pipeline in order.
* Req 16.2: Track ProcessingStatus through all defined stages.
* Req 16.3: Retry logic — 3 attempts with exponential backoff (5s, 10s, 20s, max 60s).
* Req 16.4: 120-second total timeout per record.
* Req 16.5: Per-record isolation — one failure does not block others.
* Req 16.6: Persist final results to FeedbackStore on "routed" status.
* Req 16.7: Wire all pipeline components together.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Union

from ..aggregation.similarity_clusterer import SimilarityClusterer
from ..enrichment.entity_extractor import EntityExtractor
from ..enrichment.intent_classifier import IntentClassifier
from ..enrichment.priority_scorer import PriorityScorer
from ..enrichment.sentiment_routing import SentimentAnalyzer
from ..enrichment.theme_detector import ThemeDetector
from ..models.feedback_routing import (
    CanonicalFeedback,
    FeedbackAnalysis,
    ProcessingStatus,
    RoutingDecision,
    SocialFeedback,
    WidgetFeedback,
)
from ..persistence.feedback_store import FeedbackStore
from ..preprocessing.preprocessor import Preprocessor
from .decision_engine import DecisionEngine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (Req 16.3, 16.4)
# ---------------------------------------------------------------------------

# Maximum retry attempts per stage (Req 16.3)
MAX_RETRIES: int = 3

# Exponential backoff delays in seconds (Req 16.3): 5s, 10s, 20s
BACKOFF_DELAYS: list[float] = [5.0, 10.0, 20.0]

# Maximum backoff delay cap (Req 16.3)
MAX_BACKOFF_SECONDS: float = 60.0

# Total timeout per record in seconds (Req 16.4)
TOTAL_TIMEOUT_SECONDS: float = 120.0


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class ProcessingResult:
    """Result of processing a single feedback record through the pipeline.

    Attributes
    ----------
    feedback_id : str
        The unique identifier of the feedback record.
    status : str
        Final ProcessingStatus value ("routed" on success, "failed" on failure).
    canonical : CanonicalFeedback | None
        The preprocessed canonical record (None if preprocessing failed).
    analysis : FeedbackAnalysis | None
        The NLP analysis result (None if analysis stage failed).
    routing_decision : RoutingDecision | None
        The decision engine output (None if routing stage failed).
    error : str | None
        Error description if the record failed processing.
    stage_failed : str | None
        The pipeline stage at which processing failed.
    attempts : int
        Total number of attempts made across all stages.
    """

    feedback_id: str
    status: str = "ingested"
    canonical: CanonicalFeedback | None = None
    analysis: FeedbackAnalysis | None = None
    routing_decision: RoutingDecision | None = None
    error: str | None = None
    stage_failed: str | None = None
    attempts: int = 0


# ---------------------------------------------------------------------------
# Pipeline Orchestrator
# ---------------------------------------------------------------------------


class PipelineOrchestrator:
    """Coordinates end-to-end feedback processing with status tracking and retries.

    Orchestrates: Preprocessor → SentimentAnalyzer → ThemeDetector →
    IntentClassifier → EntityExtractor → PriorityScorer →
    SimilarityClusterer → DecisionEngine → FeedbackStore persistence.

    Parameters
    ----------
    preprocessor : Preprocessor
        Text cleaning and standardization component.
    sentiment_analyzer : SentimentAnalyzer
        Sentiment classification component.
    theme_detector : ThemeDetector
        Theme/topic classification component.
    intent_classifier : IntentClassifier
        Intent detection component.
    entity_extractor : EntityExtractor
        Named entity extraction component.
    priority_scorer : PriorityScorer
        Priority scoring component.
    similarity_clusterer : SimilarityClusterer
        Feedback clustering component.
    decision_engine : DecisionEngine
        Rule-based routing decision component.
    store : FeedbackStore
        Persistence layer for final results.
    """

    def __init__(
        self,
        preprocessor: Preprocessor,
        sentiment_analyzer: SentimentAnalyzer,
        theme_detector: ThemeDetector,
        intent_classifier: IntentClassifier,
        entity_extractor: EntityExtractor,
        priority_scorer: PriorityScorer,
        similarity_clusterer: SimilarityClusterer,
        decision_engine: DecisionEngine,
        store: FeedbackStore,
    ) -> None:
        self._preprocessor = preprocessor
        self._sentiment_analyzer = sentiment_analyzer
        self._theme_detector = theme_detector
        self._intent_classifier = intent_classifier
        self._entity_extractor = entity_extractor
        self._priority_scorer = priority_scorer
        self._similarity_clusterer = similarity_clusterer
        self._decision_engine = decision_engine
        self._store = store

    def process_feedback(
        self, feedback: Union[SocialFeedback, WidgetFeedback]
    ) -> ProcessingResult:
        """Process a single feedback record through the full pipeline.

        Stages executed in order:
        1. Preprocessing (ingested → preprocessing → preprocessed)
        2. NLP Analysis (preprocessed → analyzing → analyzed)
        3. Decision Routing (analyzed → routing → routed)

        Implements:
        - Retry logic: up to 3 attempts per stage with exponential backoff
        - Total timeout: 120 seconds per record
        - Status tracking through all defined stages
        - Persistence on successful completion ("routed" status)

        Parameters
        ----------
        feedback : SocialFeedback | WidgetFeedback
            The raw feedback record to process.

        Returns
        -------
        ProcessingResult
            Contains the final status, all intermediate results, and error info.
        """
        result = ProcessingResult(feedback_id=feedback.feedback_id)
        start_time = time.monotonic()

        # Stage 1: Preprocessing (Req 16.2: ingested → preprocessing → preprocessed)
        result.status = "preprocessing"
        canonical = self._run_with_retry(
            stage_name="preprocessing",
            operation=lambda: self._preprocessor.preprocess(feedback),
            result=result,
            start_time=start_time,
        )

        if canonical is None:
            # Preprocessing returned None (duplicate) or failed
            if result.error is None:
                # Duplicate detected — mark as completed with special handling
                result.status = "failed"
                result.error = "duplicate_detected"
                result.stage_failed = "preprocessing"
            return result

        result.canonical = canonical
        result.status = "preprocessed"

        # Check if the canonical record was marked as failed (empty after cleaning)
        if canonical.processing_status == "failed":
            result.status = "failed"
            result.error = "empty_after_cleaning"
            result.stage_failed = "preprocessing"
            return result

        # Stage 2: NLP Analysis (Req 16.2: preprocessed → analyzing → analyzed)
        result.status = "analyzing"
        analysis = self._run_with_retry(
            stage_name="nlp_analysis",
            operation=lambda: self._run_nlp_analysis(canonical),
            result=result,
            start_time=start_time,
        )

        if analysis is None:
            return result

        result.analysis = analysis
        result.status = "analyzed"

        # Stage 3: Decision Routing (Req 16.2: analyzed → routing → routed)
        result.status = "routing"
        routing_decision = self._run_with_retry(
            stage_name="routing",
            operation=lambda: self._decision_engine.evaluate(canonical, analysis),
            result=result,
            start_time=start_time,
        )

        if routing_decision is None:
            return result

        result.routing_decision = routing_decision
        result.status = "routed"

        # Req 16.6: Persist final results to FeedbackStore on "routed" status
        self._persist_results(result, feedback, canonical, analysis, routing_decision)

        return result

    def process_batch(
        self, feedback_items: list[Union[SocialFeedback, WidgetFeedback]]
    ) -> list[ProcessingResult]:
        """Process a batch of feedback records with per-record isolation (Req 16.5).

        Each record is processed independently. One failure does not block
        processing of other records in the batch.

        Parameters
        ----------
        feedback_items : list
            List of raw feedback records to process.

        Returns
        -------
        list[ProcessingResult]
            Results for each record, in the same order as input.
        """
        results: list[ProcessingResult] = []
        for item in feedback_items:
            try:
                result = self.process_feedback(item)
            except Exception as exc:
                # Per-record isolation: catch any unhandled exception
                logger.error(
                    "Unhandled exception processing feedback %s: %s",
                    item.feedback_id,
                    str(exc),
                )
                result = ProcessingResult(
                    feedback_id=item.feedback_id,
                    status="failed",
                    error=f"unhandled_exception: {str(exc)}",
                    stage_failed="unknown",
                )
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # NLP Analysis Stage
    # ------------------------------------------------------------------

    def _run_nlp_analysis(
        self, canonical: CanonicalFeedback
    ) -> FeedbackAnalysis:
        """Run all NLP enrichment components and produce a FeedbackAnalysis.

        Executes in order: sentiment → theme → intent → entity → priority → cluster.
        """
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Sentiment analysis
        sentiment_result = self._sentiment_analyzer.analyze(canonical)

        # Theme detection
        theme_result = self._theme_detector.detect(canonical)

        # Intent classification
        intent_result = self._intent_classifier.classify(canonical)

        # Entity extraction
        entities = self._entity_extractor.extract(canonical)

        # Build partial analysis for priority scoring and clustering
        partial_analysis = FeedbackAnalysis(
            feedback_id=canonical.feedback_id,
            sentiment_label=sentiment_result.sentiment_label,
            sentiment_score=sentiment_result.sentiment_score,
            priority_score=0.0,  # placeholder, will be updated
            priority_level="low",  # placeholder, will be updated
            theme_primary=theme_result.primary_theme,
            theme_secondary=theme_result.secondary_theme,
            intent=intent_result.intent,
            cluster_id=None,
            requires_action=intent_result.requires_action,
            entities=entities,
            processed_at=now_iso,
        )

        # Priority scoring (needs the partial analysis for signals)
        priority_result = self._priority_scorer.score(canonical, partial_analysis)

        # Similarity clustering (needs the partial analysis for theme matching)
        cluster_id = self._similarity_clusterer.assign_cluster(
            canonical, partial_analysis
        )

        # Assemble the final FeedbackAnalysis
        return FeedbackAnalysis(
            feedback_id=canonical.feedback_id,
            sentiment_label=sentiment_result.sentiment_label,
            sentiment_score=sentiment_result.sentiment_score,
            priority_score=priority_result.priority_score,
            priority_level=priority_result.priority_level,
            theme_primary=theme_result.primary_theme,
            theme_secondary=theme_result.secondary_theme,
            intent=intent_result.intent,
            cluster_id=cluster_id,
            requires_action=intent_result.requires_action,
            entities=entities,
            processed_at=now_iso,
        )

    # ------------------------------------------------------------------
    # Retry logic (Req 16.3, 16.4)
    # ------------------------------------------------------------------

    def _run_with_retry(
        self,
        stage_name: str,
        operation,
        result: ProcessingResult,
        start_time: float,
    ):
        """Execute an operation with retry logic and timeout enforcement.

        Parameters
        ----------
        stage_name : str
            Name of the pipeline stage (for logging and error reporting).
        operation : callable
            The operation to execute (zero-argument callable).
        result : ProcessingResult
            The result object to update on failure.
        start_time : float
            The monotonic time when processing started (for timeout check).

        Returns
        -------
        The operation result, or None if all retries exhausted or timeout hit.
        """
        last_error: str = ""

        for attempt in range(MAX_RETRIES):
            # Check total timeout (Req 16.4)
            elapsed = time.monotonic() - start_time
            if elapsed >= TOTAL_TIMEOUT_SECONDS:
                result.status = "failed"
                result.error = "processing_timeout"
                result.stage_failed = stage_name
                logger.warning(
                    "Processing timeout for feedback %s at stage '%s' "
                    "(elapsed: %.1fs, limit: %.1fs)",
                    result.feedback_id,
                    stage_name,
                    elapsed,
                    TOTAL_TIMEOUT_SECONDS,
                )
                return None

            try:
                value = operation()
                result.attempts += 1
                return value
            except Exception as exc:
                result.attempts += 1
                last_error = str(exc)
                logger.warning(
                    "Stage '%s' failed for feedback %s (attempt %d/%d): %s",
                    stage_name,
                    result.feedback_id,
                    attempt + 1,
                    MAX_RETRIES,
                    last_error,
                )

                # If we have more retries, apply backoff
                if attempt < MAX_RETRIES - 1:
                    # Mark as retrying
                    result.status = "retrying"

                    # Calculate backoff delay (Req 16.3)
                    delay = min(
                        BACKOFF_DELAYS[attempt] if attempt < len(BACKOFF_DELAYS) else BACKOFF_DELAYS[-1],
                        MAX_BACKOFF_SECONDS,
                    )

                    # Check if sleeping would exceed the timeout
                    time_remaining = TOTAL_TIMEOUT_SECONDS - (time.monotonic() - start_time)
                    if time_remaining <= 0:
                        result.status = "failed"
                        result.error = "processing_timeout"
                        result.stage_failed = stage_name
                        return None

                    # Sleep for backoff duration (capped by remaining time)
                    actual_delay = min(delay, time_remaining)
                    time.sleep(actual_delay)

        # All retries exhausted
        result.status = "failed"
        result.error = f"max_retries_exceeded: {last_error}"
        result.stage_failed = stage_name
        logger.error(
            "All %d retries exhausted for feedback %s at stage '%s': %s",
            MAX_RETRIES,
            result.feedback_id,
            stage_name,
            last_error,
        )
        return None

    # ------------------------------------------------------------------
    # Persistence (Req 16.6)
    # ------------------------------------------------------------------

    def _persist_results(
        self,
        result: ProcessingResult,
        feedback: Union[SocialFeedback, WidgetFeedback],
        canonical: CanonicalFeedback,
        analysis: FeedbackAnalysis,
        routing_decision: RoutingDecision,
    ) -> None:
        """Persist all processing results to FeedbackStore on 'routed' status.

        Persists:
        1. The feedback record
        2. The NLP analysis
        3. The ticket (if created)
        4. The feedback-ticket link (if ticket exists)
        """
        try:
            # 1. Insert the feedback record
            self._store.insert_feedback(
                feedback_id=canonical.feedback_id,
                source_type=canonical.source_type,
                message_text=feedback.message_text,
                created_at_original=self._get_created_at(feedback),
                platform=canonical.metadata.get("platform"),
                customer_id=canonical.metadata.get("customer_id"),
                ingested_at=canonical.ingested_at,
                recency_score=canonical.metadata.get("recency_score"),
                channel_metadata=canonical.metadata,
                processing_status="routed",
                routing_action=routing_decision.routing_action,
            )

            # 2. Insert the analysis
            self._store.insert_analysis(analysis)

            # 3. Insert the ticket (if one was created)
            if routing_decision.ticket is not None:
                self._store.insert_ticket(routing_decision.ticket)

                # 4. Link feedback to ticket
                self._store.link_feedback_ticket(
                    feedback_id=canonical.feedback_id,
                    ticket_id=routing_decision.ticket.ticket_id,
                )
            elif routing_decision.linked_ticket_id is not None:
                # Route to existing: link to the existing ticket
                self._store.link_feedback_ticket(
                    feedback_id=canonical.feedback_id,
                    ticket_id=routing_decision.linked_ticket_id,
                )

        except Exception as exc:
            # Persistence failure — mark as failed but don't re-raise
            # (per-record isolation)
            logger.error(
                "Failed to persist results for feedback %s: %s",
                canonical.feedback_id,
                str(exc),
            )
            result.status = "failed"
            result.error = f"persistence_failed: {str(exc)}"
            result.stage_failed = "persistence"

    def _get_created_at(self, feedback: Union[SocialFeedback, WidgetFeedback]) -> str:
        """Extract the original creation timestamp from feedback."""
        if isinstance(feedback, SocialFeedback):
            return feedback.created_at_original
        return feedback.created_at


__all__ = [
    "PipelineOrchestrator",
    "ProcessingResult",
    "MAX_RETRIES",
    "BACKOFF_DELAYS",
    "MAX_BACKOFF_SECONDS",
    "TOTAL_TIMEOUT_SECONDS",
]
