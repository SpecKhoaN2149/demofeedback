"""Shared fakes and helpers for the Batch_Orchestrator (NLPProcessor) tests.

This module is intentionally *not* named ``test_*`` so pytest does not collect
it; it provides fully controllable, network-free enrichment fakes plus small
construction helpers used by:

* ``tests/test_orchestrator_properties.py``
* ``tests/test_orchestrator_unit.py``
* ``tests/test_integration.py``

The fakes let a test pin, *per record*, whether each enrichment stage succeeds
or fails and exactly what values it produces. Control flags travel on each
``RawFeedback.metadata`` dict, which the real ``IngestionComponent`` copies
verbatim onto the ``FeedbackRecord`` (Req 1.1) so the fakes can read them back
without needing to know the ingestion-assigned ids in advance.

Recognized ``metadata`` flags
-----------------------------
* ``_fail_classify`` / ``_fail_sentiment`` / ``_fail_severity`` (bool):
  force that stage to return a not-ok outcome for the record.
* ``_themes`` (list[str]) + ``_theme_confs`` (list[float]): the theme labels and
  their confidences the classifier assigns (defaults: ``["billing"]`` @ 0.9).
* ``_sentiment`` (str) + ``_sent_conf`` (float): the sentiment value/confidence
  the analyzer assigns (defaults: ``"neutral"`` @ 0.9).
* ``_severity`` (int 1..5): the severity score the scorer assigns (default 3).
"""

from __future__ import annotations

from typing import Any, Optional

from nlp_processing.aggregation import ClusteringComponent, PrioritizationComponent
from nlp_processing.config import Config
from nlp_processing.enrichment.classifier import (
    ClassificationError,
    ClassificationOutcome,
)
from nlp_processing.enrichment.sentiment import SentimentError, SentimentOutcome
from nlp_processing.enrichment.severity import SeverityError, SeverityOutcome
from nlp_processing.ingestion import IngestionComponent
from nlp_processing.models import (
    FeedbackRecord,
    RawFeedback,
    SeverityFactor,
    ThemeAssignment,
)
from nlp_processing.orchestrator import NLPProcessor

# A dummy, non-secret API key / model used for every test Config. Config
# validation is fail-fast, so these must be non-blank strings.
DUMMY_API_KEY = "test-api-key"
DUMMY_MODEL_NAME = "fake-gemini-model"


def default_config(**overrides: Any) -> Config:
    """Build a valid :class:`Config` with dummy credentials for tests."""
    kwargs: dict[str, Any] = {
        "api_key": DUMMY_API_KEY,
        "model_name": DUMMY_MODEL_NAME,
        "similarity_threshold": 0.5,
    }
    kwargs.update(overrides)
    return Config(**kwargs)


class FakeClassifier:
    """Classifier fake driven by per-record ``metadata`` flags."""

    def classify(self, record: FeedbackRecord) -> ClassificationOutcome:
        md = record.metadata
        if md.get("_fail_classify"):
            return ClassificationOutcome(
                record=record,
                error=ClassificationError(
                    record_id=record.id, reason="forced classification failure"
                ),
            )
        labels = md.get("_themes") or ["billing"]
        confs = md.get("_theme_confs")
        if not confs:
            confs = [0.9] * len(labels)
        themes = tuple(
            ThemeAssignment(theme=label, confidence=conf)
            for label, conf in zip(labels, confs)
        )
        return ClassificationOutcome(record=record, themes=themes)


class FakeSentimentAnalyzer:
    """Sentiment fake driven by per-record ``metadata`` flags."""

    def analyze(self, record: FeedbackRecord) -> SentimentOutcome:
        md = record.metadata
        if md.get("_fail_sentiment"):
            return SentimentOutcome(
                record=record,
                error=SentimentError(
                    record_id=record.id,
                    reason="forced sentiment failure",
                    kind="sentiment_failure",
                ),
            )
        sentiment = md.get("_sentiment", "neutral")
        confidence = md.get("_sent_conf", 0.9)
        return SentimentOutcome(
            record=record, sentiment=sentiment, confidence=confidence
        )


class FakeSeverityScorer:
    """Severity fake driven by per-record ``metadata`` flags."""

    def score(self, record: FeedbackRecord) -> SeverityOutcome:
        md = record.metadata
        if md.get("_fail_severity"):
            return SeverityOutcome(
                record=record,
                error=SeverityError(
                    record_id=record.id, reason="forced severity failure"
                ),
            )
        score = md.get("_severity", 3)
        return SeverityOutcome(
            record=record,
            severity_score=score,
            factors=(SeverityFactor(description="fake contributing factor"),),
        )


def make_processor(
    config: Optional[Config] = None,
    *,
    classifier: Any = None,
    sentiment_analyzer: Any = None,
    severity_scorer: Any = None,
    processor_cls: type[NLPProcessor] = NLPProcessor,
) -> NLPProcessor:
    """Construct an :class:`NLPProcessor` with fake enrichment and real pure logic.

    Ingestion, clustering, and prioritization are the real (network-free)
    components; the three enrichment stages default to the controllable fakes.
    ``processor_cls`` allows injecting a subclass (used by the fault-injection
    test that overrides ``_set_review_flag``).
    """
    cfg = config or default_config()
    return processor_cls(
        cfg,
        ingestion=IngestionComponent(),
        classifier=classifier or FakeClassifier(),
        sentiment_analyzer=sentiment_analyzer or FakeSentimentAnalyzer(),
        severity_scorer=severity_scorer or FakeSeverityScorer(),
        clustering=ClusteringComponent(),
        prioritization=PrioritizationComponent(),
    )


def make_raw(
    text: str,
    *,
    channel: str = "email",
    **flags: Any,
) -> RawFeedback:
    """Build a valid :class:`RawFeedback` carrying control ``flags`` in metadata.

    Any keyword in ``flags`` is stored under ``metadata`` so the fakes can read
    it back after ingestion copies metadata through unchanged (Req 1.1).
    """
    return RawFeedback(source_channel=channel, text=text, metadata=dict(flags))
