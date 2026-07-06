"""Core pydantic data models for the NLP feedback processing pipeline.

These models carry feedback through the pipeline stages and enforce the field
types and range constraints from the design's Data Models section:

- confidence values in the inclusive range 0.0..1.0
- severity score integers in 1..5
- cluster labels non-empty and <= 120 characters
- severity factor descriptions 1..500 characters
- priority scores >= 0.0
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .types import FailureStage, SentimentValue, SourceChannel, ThemeLabel


class RawFeedback(BaseModel):
    """Unvalidated, normalized feedback as submitted to the pipeline.

    ``source_channel`` is intentionally a plain ``str`` here; it is validated
    against :data:`SourceChannel` by the Ingestion_Component (Req 1.4) so that
    out-of-set channels can be rejected with a keyed validation error rather
    than raising on construction.
    """

    source_channel: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class FeedbackRecord(BaseModel):
    """A validated, normalized feedback record produced by ingestion (Req 1.1)."""

    id: str
    source_channel: SourceChannel
    # Trimmed text; constrained to 1..10000 characters (Req 1.3, 1.7).
    cleaned_text: str = Field(min_length=1, max_length=10_000)
    # Original metadata copied unchanged from the RawFeedback (Req 1.1).
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThemeAssignment(BaseModel):
    """A single theme assignment with its confidence (Req 5.3)."""

    theme: ThemeLabel
    confidence: float = Field(ge=0.0, le=1.0)


class SeverityFactor(BaseModel):
    """A contributing factor to a severity score, 1..500 characters (Req 7.2)."""

    description: str = Field(min_length=1, max_length=500)


class InsightRecord(BaseModel):
    """A fully enriched record: themes, sentiment, severity, and cluster."""

    feedback_id: str
    # At least one theme assignment (Req 5.1).
    themes: list[ThemeAssignment] = Field(min_length=1)
    sentiment: SentimentValue
    sentiment_confidence: float = Field(ge=0.0, le=1.0)  # Req 6.2
    severity_score: int = Field(ge=1, le=5)  # Req 7.1
    # At least one contributing factor (Req 7.2).
    severity_factors: list[SeverityFactor] = Field(min_length=1)
    cluster_id: str
    review_flag: bool = False
    model_name: str
    notes: list[str] = Field(default_factory=list)
    # Language detection metadata (Req 5.5); None for legacy records.
    language_code: str | None = None  # ISO 639-1
    language_confidence: float | None = None  # 0.0..1.0


class Cluster(BaseModel):
    """A group of semantically similar records with a ranked priority score."""

    cluster_id: str
    # Non-empty representative label, <= 120 characters (Req 8.2).
    label: str = Field(min_length=1, max_length=120)
    member_ids: list[str] = Field(default_factory=list)
    priority_score: float = Field(default=0.0, ge=0.0)  # Req 9.4


class FailureEntry(BaseModel):
    """A per-record failure keyed by id and pipeline stage (Req 10.2)."""

    feedback_id: str
    stage: FailureStage
    reason: str


class BatchSummary(BaseModel):
    """Batch accounting summary; ``successful + failures == submitted`` (Req 10.3)."""

    submitted: int = Field(ge=0)
    successful: int = Field(ge=0)
    failures: int = Field(ge=0)


class SystemErrorEntry(BaseModel):
    """A non-record-fatal system error recorded during output assembly.

    Used for the review-flag failure path (Req 11.3): when a below-threshold
    confidence is detected but applying the review flag to the affected insight
    fails, the processor records one of these (identifying the insight by
    ``feedback_id``) and retains the insight unflagged.
    """

    feedback_id: str
    reason: str


class BatchOutput(BaseModel):
    """The assembled batch output emitted as schema-conforming JSON (Req 10.4)."""

    insights: list[InsightRecord] = Field(default_factory=list)
    # Ranked, descending priority (Req 9.2).
    clusters: list[Cluster] = Field(default_factory=list)
    failures: list[FailureEntry] = Field(default_factory=list)
    # Non-record-fatal system errors recorded during assembly (Req 11.3); the
    # affected insights are still present in ``insights`` (retained unflagged).
    system_errors: list[SystemErrorEntry] = Field(default_factory=list)
    summary: BatchSummary
    model_name: str
    # Set iff a ground-truth dataset is supplied (Req 11.6).
    classification_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)


__all__ = [
    "RawFeedback",
    "FeedbackRecord",
    "ThemeAssignment",
    "SeverityFactor",
    "InsightRecord",
    "Cluster",
    "FailureEntry",
    "BatchSummary",
    "SystemErrorEntry",
    "BatchOutput",
]
