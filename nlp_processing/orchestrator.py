"""Batch_Orchestrator / NLP_Processor: drives the processing pipeline (Req 10).

This module implements **task 13.1** -- the batch orchestration pipeline:

* validate batch size: empty or > 10,000 -> no insights, a batch-validation
  error naming the violated bound (Req 10.5);
* run ingestion, then per-record enrichment (classification, sentiment,
  severity) with strict per-record isolation so one record's failure never
  aborts the batch; every failure is recorded as a
  :class:`~nlp_processing.models.records.FailureEntry` keyed by id and stage
  (Req 3.4, 10.2);
* a record is *successful* only when classification, sentiment, severity, **and**
  cluster assignment all complete without error (Req 10.1);
* invoke clustering then prioritization over the enriched records.

Scope
-----
Task 13.1 implemented *pipeline orchestration*; task 13.2 layers the
output-assembly concerns on top:

* ``_needs_review`` / ``_set_review_flag`` -- review-flag logic (Req 11.2,
  11.3): the flag is set when any theme/sentiment confidence is below
  ``review_threshold``, and a flag-set failure records a system error while
  retaining the insight unflagged.
* ``_compute_classification_accuracy`` -- ground-truth accuracy (Req 11.5,
  11.6).
* ``serialize`` -- canonical-JSON emission via the ``Response_Serializer``
  (Req 10.4).

The summary accounting (Req 10.3) and the configured model name on each insight
(Req 11.4) are produced on every :class:`InsightRecord` / :class:`BatchOutput`.

Design / testability
---------------------
Every collaborator is injected through the constructor so tests can supply
fakes (no network, no real Gemini calls). :meth:`NLPProcessor.from_config`
provides a production wiring path that builds a shared
:class:`~nlp_processing.transport.client.GeminiClient`; the SDK client behind it
is constructed lazily on first use, so building the processor never touches the
network.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from .aggregation import (
    ClusteringComponent,
    PrioritizationComponent,
    as_enriched_record,
)
from .config import Config
from .enrichment import Classifier, SentimentAnalyzer, SeverityScorer
from .enrichment.language import LanguageDetector
from .ingestion import IngestionComponent
from .models import (
    BatchOutput,
    BatchSummary,
    Cluster,
    FailureEntry,
    FeedbackRecord,
    InsightRecord,
    RawFeedback,
    SeverityFactor,
    SystemErrorEntry,
    ThemeAssignment,
)
from .models.enhancements import (
    CachedEnrichment,
    LanguageDetectionResult,
    SaveResult,
    TimeWindow,
    TrendReport,
)
from .persistence import CacheLayer, PersistenceStore
from .persistence_config import CacheConfig, PersistenceConfig, TrendConfig
from .serialization.serializer import ResponseSerializer
from .trends.detector import TrendDetector

logger = logging.getLogger(__name__)

# Inclusive lower / exclusive-of-bound upper limits for a processing batch
# (Req 10.5). An empty batch and a batch larger than this maximum are rejected.
MIN_BATCH_SIZE = 1
MAX_BATCH_SIZE = 10_000


class BatchValidationError(Exception):
    """Raised when a submitted processing batch violates a size bound (Req 10.5).

    The batch is fatal-to-process: no ``Insight_Record``s are produced. The
    message names the violated bound (empty, or over the 10,000 maximum) so the
    operator can see which constraint failed.
    """

    def __init__(self, bound: str, message: str) -> None:
        self.bound = bound
        super().__init__(message)


@dataclass(frozen=True)
class _EnrichedRecord:
    """Intermediate enrichment result for a record that passed all stages.

    Holds everything needed to build an :class:`InsightRecord` once clustering
    assigns a cluster id. Produced only when classification, sentiment, and
    severity all succeed (Req 10.1).
    """

    record: FeedbackRecord
    themes: tuple[ThemeAssignment, ...]
    sentiment: str
    sentiment_confidence: float
    severity_score: int
    severity_factors: tuple[SeverityFactor, ...]
    notes: tuple[str, ...]
    language_code: str | None = None
    language_confidence: float | None = None


class NLPProcessor:
    """Drives ingestion -> enrichment -> clustering -> prioritization (Req 10).

    Parameters
    ----------
    config:
        The validated :class:`Config`. Supplies ``model_name`` (recorded on each
        insight, Req 11.4), ``similarity_threshold`` (clustering), and
        ``review_threshold`` (used by 13.2's review-flag logic).
    ingestion:
        The :class:`IngestionComponent` that normalizes raw items (Req 1).
    classifier, sentiment_analyzer, severity_scorer:
        The enrichment components. Each is injected so tests can provide fakes
        with no network dependency.
    clustering:
        The :class:`ClusteringComponent` that partitions enriched records.
    prioritization:
        The :class:`PrioritizationComponent` that scores and ranks clusters.
    persistence_store:
        Optional :class:`PersistenceStore` for durable batch storage and cache
        backend. When provided, a :class:`TrendDetector` is also exposed.
        Defaults to None (persistence disabled).
    cache_layer:
        Optional :class:`CacheLayer` for enrichment result caching. Requires a
        persistence store as its backend. Defaults to None (caching disabled).
    language_detector:
        Optional :class:`LanguageDetector` for identifying the language of
        incoming feedback text. Defaults to None (language detection disabled).
    """

    def __init__(
        self,
        config: Config,
        *,
        ingestion: IngestionComponent,
        classifier: Classifier,
        sentiment_analyzer: SentimentAnalyzer,
        severity_scorer: SeverityScorer,
        clustering: ClusteringComponent,
        prioritization: PrioritizationComponent,
        persistence_store: Optional[PersistenceStore] = None,
        cache_layer: Optional[CacheLayer] = None,
        language_detector: Optional[LanguageDetector] = None,
    ) -> None:
        self._config = config
        self._ingestion = ingestion
        self._classifier = classifier
        self._sentiment = sentiment_analyzer
        self._severity = severity_scorer
        self._clustering = clustering
        self._prioritization = prioritization
        # New optional dependencies (all default to None/disabled).
        self._persistence_store = persistence_store
        self._cache_layer = cache_layer
        self._language_detector = language_detector
        # Expose a TrendDetector when a PersistenceStore is available.
        self._trend_detector: Optional[TrendDetector] = None
        if persistence_store is not None:
            self._trend_detector = TrendDetector(
                store=persistence_store, config=TrendConfig()
            )
        # Track the most recent save result for batch persistence.
        self._last_save_result: Optional[SaveResult] = None
        # Stateless canonical-JSON serializer used by :meth:`serialize`
        # (Req 10.4). Constructing it is cheap and touches no network.
        self._serializer = ResponseSerializer()

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    @classmethod
    def from_config(
        cls,
        config: Config,
        *,
        ingestion: Optional[IngestionComponent] = None,
        clustering: Optional[ClusteringComponent] = None,
        prioritization: Optional[PrioritizationComponent] = None,
        persistence_config: Optional[PersistenceConfig] = None,
        cache_config: Optional[CacheConfig] = None,
        trend_config: Optional[TrendConfig] = None,
    ) -> "NLPProcessor":
        """Build a processor wired against a real (lazy) Gemini transport.

        Constructs a single shared :class:`GeminiClient` from ``config`` and
        builds the three enrichment components around it. The underlying SDK
        client is created lazily on first request, so this path performs no
        network I/O and requires no live key at construction time.

        The pure-logic components (ingestion, clustering, prioritization) can be
        overridden for testing; sensible defaults are constructed otherwise.

        When ``persistence_config`` is provided, a :class:`PersistenceStore` is
        built and injected. When ``cache_config`` is also provided (and a store
        is available), a :class:`CacheLayer` is wired. A
        :class:`LanguageDetector` is constructed using the shared Gemini client.
        A :class:`TrendDetector` is exposed when a store is available.
        """
        # Local import keeps the transport (and its optional SDK dependency)
        # off the import path for callers that only use injected fakes.
        from .transport.client import GeminiClient

        client = GeminiClient(
            api_key=config.api_key,
            model_name=config.model_name,
            max_attempts=config.max_attempts,
            timeout_s=config.request_timeout_seconds,
        )

        # Wire new optional components when configuration is provided.
        persistence_store: Optional[PersistenceStore] = None
        cache_layer: Optional[CacheLayer] = None
        language_detector: Optional[LanguageDetector] = None

        if persistence_config is not None:
            persistence_store = PersistenceStore(
                backend=persistence_config.backend,
                db_path=persistence_config.db_path,
            )

        if cache_config is not None and persistence_store is not None:
            cache_layer = CacheLayer(
                store=persistence_store,
                ttl_hours=cache_config.ttl_hours,
                enabled=cache_config.enabled,
            )

        # Language detection uses the shared Gemini client.
        language_detector = LanguageDetector(client=client)

        return cls(
            config,
            ingestion=ingestion or IngestionComponent(),
            classifier=Classifier(client, theme_set=config.theme_set),
            sentiment_analyzer=SentimentAnalyzer(client),
            severity_scorer=SeverityScorer(client),
            clustering=clustering or ClusteringComponent(),
            prioritization=prioritization or PrioritizationComponent(),
            persistence_store=persistence_store,
            cache_layer=cache_layer,
            language_detector=language_detector,
        )

    @classmethod
    def from_settings(
        cls,
        *,
        api_key: Any,
        model_name: Any,
        similarity_threshold: Any,
        ingestion: Optional[IngestionComponent] = None,
        clustering: Optional[ClusteringComponent] = None,
        prioritization: Optional[PrioritizationComponent] = None,
        persistence_config: Optional[PersistenceConfig] = None,
        cache_config: Optional[CacheConfig] = None,
        trend_config: Optional[TrendConfig] = None,
        **config_kwargs: Any,
    ) -> "NLPProcessor":
        """Build a processor from raw configuration settings.

        Convenience wrapper for end users that constructs a :class:`Config`
        from keyword settings and delegates to :meth:`from_config`. Because
        :class:`Config` validates every value at construction (Req 2.2, 2.4),
        an invalid setting raises :class:`ConfigurationError` here -- before any
        record is processed and before any component is wired.

        ``config_kwargs`` accepts the optional :class:`Config` parameters
        (``max_attempts``, ``request_timeout_seconds``, ``review_threshold``,
        ``theme_set``), each of which is validated and falls back to its default
        when omitted.

        When ``persistence_config``, ``cache_config``, or ``trend_config`` are
        provided, the corresponding components are wired into the processor.
        """
        config = Config(
            api_key=api_key,
            model_name=model_name,
            similarity_threshold=similarity_threshold,
            **config_kwargs,
        )
        return cls.from_config(
            config,
            ingestion=ingestion,
            clustering=clustering,
            prioritization=prioritization,
            persistence_config=persistence_config,
            cache_config=cache_config,
            trend_config=trend_config,
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def process_batch(
        self,
        raw_items: Sequence[RawFeedback],
        *,
        ground_truth: Optional[Mapping[str, Any]] = None,
    ) -> BatchOutput:
        """Process a batch of raw feedback into a structured :class:`BatchOutput`.

        Pipeline (task 13.1):
          1. Validate the batch size (Req 10.5) -- raises
             :class:`BatchValidationError` for an empty or oversized batch.
          2. Ingest + normalize; ingestion validation errors become
             ``ingestion``-stage failures (Req 1, 10.2).
          3. Detect language for each record (Req 5.1, 6.1) when a
             LanguageDetector is configured.
          4. Enrich each record (classification -> sentiment -> severity) with
             per-record isolation; checks the cache before calling Gemini and
             populates the cache on successful enrichment (Req 2.1, 2.2).
          5. Cluster the fully-enriched records, then prioritize the clusters.
          6. A record is successful only if it was enriched **and** assigned to
             a cluster (Req 10.1).
          7. Persist the assembled BatchOutput if a PersistenceStore is
             configured (Req 1.1). Save failures are non-fatal.

        ``ground_truth`` (a mapping ``feedback_id -> labeled themes``) drives
        classification-accuracy computation (Req 11.5/11.6); when omitted,
        accuracy is left out of the output.
        """
        # --- Step 1: batch-size validation (Req 10.5) ---------------------
        self._validate_batch_size(raw_items)

        # --- Step 2: ingestion (Req 1) ------------------------------------
        ingest_result = self._ingestion.ingest_batch(list(raw_items))
        failures: list[FailureEntry] = []
        if ingest_result.batch_error is not None:
            # Ingestion rejected the whole batch (e.g. > 1000 items, Req 1.6).
            # This is fatal-to-batch at the ingestion layer; surface it the same
            # way as a batch-validation error so no insights are produced.
            raise BatchValidationError("ingestion_batch_size", ingest_result.batch_error)

        for failed_id, reason in ingest_result.errors.items():
            failures.append(
                FailureEntry(feedback_id=failed_id, stage="ingestion", reason=reason)
            )

        # --- Step 3: language detection (Req 5.1, 5.5, 6.1, 6.2) ---------
        # Detect language for each record before enrichment so the language
        # code can be passed to Gemini prompts and recorded on InsightRecords.
        language_results: dict[str, LanguageDetectionResult] = {}
        if self._language_detector is not None:
            for record in ingest_result.records:
                lang_result = self._language_detector.detect(record)
                language_results[record.id] = lang_result

        # --- Step 4: per-record enrichment with isolation (Req 3.4, 10.2) -
        enriched: list[_EnrichedRecord] = []
        for record in ingest_result.records:
            # Determine language_code for this record.
            lang_result = language_results.get(record.id)
            language_code = lang_result.language_code if lang_result else "en"
            language_confidence = lang_result.confidence if lang_result else None

            outcome = self._enrich_record(
                record,
                language_code=language_code,
                language_confidence=language_confidence,
            )
            if isinstance(outcome, FailureEntry):
                failures.append(outcome)
            else:
                enriched.append(outcome)

        # --- Step 5: clustering then prioritization (Req 8, 9) ------------
        clusters, cluster_of = self._cluster(enriched)

        # A record is successful only when it was enriched AND assigned to a
        # cluster (Req 10.1). Clustering partitions every input record, so a
        # missing assignment is a defensive cluster-stage failure.
        insights: list[InsightRecord] = []
        system_errors: list[SystemErrorEntry] = []
        for item in enriched:
            cluster_id = cluster_of.get(item.record.id)
            if cluster_id is None:
                failures.append(
                    FailureEntry(
                        feedback_id=item.record.id,
                        stage="clustering",
                        reason="record was not assigned to any cluster",
                    )
                )
                continue
            insights.append(self._build_insight(item, cluster_id, system_errors))

        ranked_clusters = self._prioritization.prioritize(
            clusters, {insight.feedback_id: insight for insight in insights}
        )

        # --- Step 6: assemble output -------------------------------------
        output = self._assemble_output(
            insights, ranked_clusters, failures, system_errors, ground_truth
        )

        # --- Step 7: persist (Req 1.1, 1.8) ------------------------------
        # Save the batch to durable storage if a PersistenceStore is configured.
        # Save failures are non-fatal: return BatchOutput to caller regardless.
        if self._persistence_store is not None:
            try:
                self._last_save_result = self._persistence_store.save_batch(output)
            except Exception as exc:
                self._last_save_result = SaveResult(
                    batch_id="", success=False, error=str(exc)
                )

        return output

    # ------------------------------------------------------------------ #
    # Pipeline steps
    # ------------------------------------------------------------------ #
    def _validate_batch_size(self, raw_items: Sequence[RawFeedback]) -> None:
        """Reject an empty or oversized batch, naming the bound (Req 10.5)."""
        size = len(raw_items)
        if size < MIN_BATCH_SIZE:
            raise BatchValidationError(
                "empty",
                "batch is empty; at least 1 feedback record is required "
                f"(minimum batch size is {MIN_BATCH_SIZE})",
            )
        if size > MAX_BATCH_SIZE:
            raise BatchValidationError(
                "maximum",
                f"batch size {size} exceeds the maximum of {MAX_BATCH_SIZE} "
                "feedback records",
            )

    def _enrich_record(
        self,
        record: FeedbackRecord,
        *,
        language_code: str = "en",
        language_confidence: float | None = None,
    ) -> _EnrichedRecord | FailureEntry:
        """Enrich one record with per-record isolation (Req 3.4, 10.2).

        Runs classification, then sentiment, then severity. The first stage that
        raises or returns a not-ok outcome produces a stage-keyed
        :class:`FailureEntry`; the record is excluded but the batch continues.
        On full success an :class:`_EnrichedRecord` is returned.

        When a :class:`CacheLayer` is configured, checks the cache before
        calling Gemini (Req 2.2). On a cache hit, the enrichment result is
        constructed from cached data. On a miss and successful enrichment, the
        cache is populated (Req 2.1, 2.5, 2.7, 2.8, 6.7).
        """
        notes: list[str] = []

        # --- Cache lookup (Req 2.2, 2.8) ---
        if self._cache_layer is not None:
            try:
                cached = self._cache_layer.get(record.cleaned_text, language_code)
            except Exception:
                cached = None
                notes.append(f"cache-failure: read failed for record {record.id}")
            else:
                if cached is not None:
                    # Cache hit: construct enrichment result from cached data.
                    return _EnrichedRecord(
                        record=record,
                        themes=tuple(cached.themes),
                        sentiment=cached.sentiment,
                        sentiment_confidence=cached.sentiment_confidence,
                        severity_score=cached.severity_score,
                        severity_factors=tuple(cached.severity_factors),
                        notes=tuple(notes),
                        language_code=language_code,
                        language_confidence=language_confidence,
                    )

        # --- classification (Req 5) ---
        try:
            classification = self._classifier.classify(
                record, language_code=language_code
            )
        except Exception as exc:  # noqa: BLE001 -- isolate per-record failures
            return self._failure(record, "classification", exc)
        if not classification.ok or classification.themes is None:
            reason = (
                classification.error.reason
                if classification.error is not None
                else "classification produced no themes"
            )
            return FailureEntry(
                feedback_id=record.id, stage="classification", reason=reason
            )

        # --- sentiment (Req 6) ---
        try:
            sentiment = self._sentiment.analyze(
                record, language_code=language_code
            )
        except Exception as exc:  # noqa: BLE001
            return self._failure(record, "sentiment", exc)
        if not sentiment.ok or sentiment.sentiment is None or sentiment.confidence is None:
            reason = (
                sentiment.error.reason
                if sentiment.error is not None
                else "sentiment analysis produced no value"
            )
            return FailureEntry(
                feedback_id=record.id, stage="sentiment", reason=reason
            )
        notes.extend(sentiment.notes)

        # --- severity (Req 7) ---
        try:
            severity = self._severity.score(
                record, language_code=language_code
            )
        except Exception as exc:  # noqa: BLE001
            return self._failure(record, "severity", exc)
        if not severity.ok or severity.severity_score is None or severity.factors is None:
            reason = (
                severity.error.reason
                if severity.error is not None
                else "severity scoring produced no value"
            )
            return FailureEntry(
                feedback_id=record.id, stage="severity", reason=reason
            )
        notes.extend(severity.notes)

        # --- Cache population (Req 2.1, 2.5) ---
        if self._cache_layer is not None:
            try:
                cached_enrichment = CachedEnrichment(
                    themes=list(classification.themes),
                    sentiment=sentiment.sentiment,
                    sentiment_confidence=sentiment.confidence,
                    severity_score=severity.severity_score,
                    severity_factors=list(severity.factors),
                    cached_at=datetime.now(timezone.utc).isoformat(),
                )
                self._cache_layer.put(
                    record.cleaned_text, language_code, cached_enrichment
                )
            except Exception as exc:
                logger.warning(
                    "Cache write failed for record %s: %s", record.id, exc
                )

        return _EnrichedRecord(
            record=record,
            themes=tuple(classification.themes),
            sentiment=sentiment.sentiment,
            sentiment_confidence=sentiment.confidence,
            severity_score=severity.severity_score,
            severity_factors=tuple(severity.factors),
            notes=tuple(notes),
            language_code=language_code,
            language_confidence=language_confidence,
        )

    @staticmethod
    def _failure(
        record: FeedbackRecord, stage: str, exc: Exception
    ) -> FailureEntry:
        """Build a failure entry from an exception raised during a stage."""
        return FailureEntry(
            feedback_id=record.id,
            stage=stage,  # type: ignore[arg-type] -- constrained literal
            reason=f"{stage} raised {type(exc).__name__}: {exc}",
        )

    def _cluster(
        self, enriched: Sequence[_EnrichedRecord]
    ) -> tuple[list[Cluster], dict[str, str]]:
        """Cluster enriched records and map each member id to its cluster id.

        Returns the cluster list (unranked) and a ``{feedback_id: cluster_id}``
        lookup used for both success determination (Req 10.1) and insight
        assembly. Empty input yields zero clusters but still returns valid
        output (Req 8.6).
        """
        if not enriched:
            return [], {}

        adapted = [as_enriched_record(item.record) for item in enriched]
        clusters = self._clustering.cluster(
            adapted, self._config.similarity_threshold
        )
        cluster_of: dict[str, str] = {}
        for cluster in clusters:
            for member_id in cluster.member_ids:
                cluster_of[member_id] = cluster.cluster_id
        return clusters, cluster_of

    def _build_insight(
        self,
        item: _EnrichedRecord,
        cluster_id: str,
        system_errors: list[SystemErrorEntry],
    ) -> InsightRecord:
        """Assemble an :class:`InsightRecord` for a fully-successful record.

        Records the configured Gemini model name on the insight (Req 11.4) and
        applies the review flag (Req 11.2). If a below-threshold confidence is
        detected but applying the flag fails, a system error identifying the
        insight is recorded and the insight is retained unflagged (Req 11.3).
        """
        needs_review = self._needs_review(item)

        review_flag = False
        if needs_review:
            try:
                review_flag = self._set_review_flag(item)
            except Exception as exc:  # noqa: BLE001 -- isolate flag-set failure
                # Req 11.3: detected below-threshold but flag-set failed. Record
                # a system error naming the insight and retain it unflagged.
                system_errors.append(
                    SystemErrorEntry(
                        feedback_id=item.record.id,
                        reason=(
                            "below-threshold confidence detected but applying "
                            f"the review flag failed: {type(exc).__name__}: {exc}"
                        ),
                    )
                )
                review_flag = False

        return InsightRecord(
            feedback_id=item.record.id,
            themes=list(item.themes),
            sentiment=item.sentiment,  # type: ignore[arg-type] -- validated value
            sentiment_confidence=item.sentiment_confidence,
            severity_score=item.severity_score,
            severity_factors=list(item.severity_factors),
            cluster_id=cluster_id,
            review_flag=review_flag,
            model_name=self._config.model_name,
            notes=list(item.notes),
            language_code=item.language_code,
            language_confidence=item.language_confidence,
        )

    def _assemble_output(
        self,
        insights: list[InsightRecord],
        clusters: list[Cluster],
        failures: list[FailureEntry],
        system_errors: list[SystemErrorEntry],
        ground_truth: Optional[Mapping[str, Any]],
    ) -> BatchOutput:
        """Assemble the :class:`BatchOutput` (Req 10.3, 11.6).

        The summary accounting holds by construction:
        ``submitted == successful + failures`` and ``successful ==
        len(insights)``. An output is always produced, even when zero insights
        succeed. ``classification_accuracy`` is computed from ``ground_truth``
        when supplied and omitted (``None``) otherwise.
        """
        successful = len(insights)
        failed = len(failures)
        summary = BatchSummary(
            submitted=successful + failed,
            successful=successful,
            failures=failed,
        )
        accuracy = self._compute_classification_accuracy(insights, ground_truth)
        return BatchOutput(
            insights=insights,
            clusters=clusters,
            failures=failures,
            system_errors=system_errors,
            summary=summary,
            model_name=self._config.model_name,
            classification_accuracy=accuracy,
        )

    # ------------------------------------------------------------------ #
    # Output serialization (Req 10.4)
    # ------------------------------------------------------------------ #
    def serialize(self, output: BatchOutput) -> str:
        """Emit ``output`` as canonical, schema-conforming JSON (Req 10.4).

        Delegates to the :class:`ResponseSerializer`, which renders the
        published :class:`BatchOutput` schema with lexicographically sorted
        keys, normalized whitespace, and stable number formatting so the JSON
        round-trip property holds byte-for-byte (Req 4.6).
        """
        return self._serializer.serialize_batch(output)

    # ------------------------------------------------------------------ #
    # Batch retrieval (Req 1.3, 1.4)
    # ------------------------------------------------------------------ #
    def retrieve_batch(self, batch_id: str) -> BatchOutput | None:
        """Retrieve a previously persisted batch by its identifier.

        Returns the :class:`BatchOutput` if found, or ``None`` if the batch
        does not exist or no :class:`PersistenceStore` is configured (Req 1.3,
        1.4).
        """
        if self._persistence_store is None:
            return None
        return self._persistence_store.get_batch(batch_id)

    @property
    def last_save_result(self) -> SaveResult | None:
        """The :class:`SaveResult` from the most recent ``process_batch`` call.

        Returns ``None`` if no batch has been processed or no persistence store
        is configured. Allows callers to inspect whether the save succeeded and
        to obtain the assigned batch_id (Req 1.1, 1.8).
        """
        return self._last_save_result

    # ------------------------------------------------------------------ #
    # Trend detection (Req 3.1, 4.1)
    # ------------------------------------------------------------------ #
    def detect_trends(
        self, baseline: TimeWindow, current: TimeWindow
    ) -> TrendReport:
        """Detect trends by comparing baseline and current time windows.

        Delegates to the :class:`TrendDetector` constructed from the injected
        :class:`PersistenceStore`. Raises :class:`RuntimeError` if no
        persistence store is configured (trend detection requires historical
        data).

        Parameters
        ----------
        baseline : TimeWindow
            The historical reference period.
        current : TimeWindow
            The recent period to compare against the baseline.

        Returns
        -------
        TrendReport
            The trend analysis results.

        Raises
        ------
        RuntimeError
            If no PersistenceStore is configured.
        ValueError
            If the time windows are invalid (delegated from TrendDetector).
        """
        if self._trend_detector is None:
            raise RuntimeError(
                "Trend detection requires a PersistenceStore. "
                "Configure persistence to enable trend analysis."
            )
        return self._trend_detector.detect_trends(baseline, current)

    # ------------------------------------------------------------------ #
    # Extension points for task 13.2 (output assembly / quality controls)
    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # Review flagging (Req 11.2/11.3)
    # ------------------------------------------------------------------ #
    def _needs_review(self, item: _EnrichedRecord) -> bool:
        """Return True when any theme or the sentiment confidence is low (Req 11.2).

        A record needs human review when *any* assigned theme confidence OR the
        sentiment confidence is strictly below the configured
        ``review_threshold``.
        """
        threshold = self._config.review_threshold
        if item.sentiment_confidence < threshold:
            return True
        return any(theme.confidence < threshold for theme in item.themes)

    def _set_review_flag(self, item: _EnrichedRecord) -> bool:
        """Apply the review flag for an insight that needs review (Req 11.2).

        Returns ``True`` to mark the insight for review. Separated from
        :meth:`_needs_review` as the seam where applying the flag could fail;
        :meth:`_build_insight` catches any failure here and records a system
        error while retaining the insight unflagged (Req 11.3).
        """
        return True

    def _compute_classification_accuracy(
        self,
        insights: Sequence[InsightRecord],
        ground_truth: Optional[Mapping[str, Any]],
    ) -> Optional[float]:
        """Compute classification accuracy against a ground-truth set (Req 11.5/11.6).

        When ``ground_truth`` (a mapping ``feedback_id -> labeled themes``) is
        supplied, accuracy is the proportion of *evaluated* records whose
        assigned theme set exactly matches the labeled theme set, as a value in
        ``0.0..1.0``. A record is *evaluated* when it both has a produced
        insight and appears in ``ground_truth``. When no ground truth is
        supplied (``None``), accuracy is omitted (``None``).

        An empty ground-truth mapping, or one whose ids do not intersect the
        produced insights, yields ``0.0`` (no record matched).
        """
        if ground_truth is None:
            return None

        insight_themes = {
            insight.feedback_id: {theme.theme for theme in insight.themes}
            for insight in insights
        }

        evaluated = 0
        matched = 0
        for feedback_id, labels in ground_truth.items():
            assigned = insight_themes.get(feedback_id)
            if assigned is None:
                # Labeled record had no produced insight; it cannot be
                # evaluated for an exact-match, so it does not count.
                continue
            evaluated += 1
            if assigned == self._normalize_label_set(labels):
                matched += 1

        if evaluated == 0:
            return 0.0
        return matched / evaluated

    @staticmethod
    def _normalize_label_set(labels: Any) -> set[str]:
        """Coerce a ground-truth label value into a set of theme strings.

        Accepts a single label string or any iterable of label strings so
        callers can supply ``{"billing"}``, ``["billing", "outage"]`` or a bare
        ``"billing"``.
        """
        if isinstance(labels, str):
            return {labels}
        return set(labels)


__all__ = [
    "NLPProcessor",
    "BatchValidationError",
    "MIN_BATCH_SIZE",
    "MAX_BATCH_SIZE",
]
