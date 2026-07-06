"""Pydantic data models for the NLP pipeline enhancements.

This module defines models for:
- Persistence layer (BatchMetadata, SaveResult)
- Enrichment caching (CachedEnrichment, CacheEntry)
- Language detection (LanguageDetectionResult)
- Trend detection (TimeWindow, ThemeSpike, SentimentShift, SeverityEscalation, TrendReport)

Field constraints follow the design specification:
- Confidence values: 0.0..1.0 inclusive
- Severity scores: 1..5 inclusive (integer) or 1.0..5.0 (float mean)
- Timestamps: ISO 8601 UTC strings
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .records import SeverityFactor, ThemeAssignment
from .types import SentimentValue


class BatchMetadata(BaseModel):
    """Metadata for a persisted batch (Req 1.2)."""

    batch_id: str
    timestamp: str  # ISO 8601 UTC
    status: Literal["completed"]
    record_count: int


class SaveResult(BaseModel):
    """Outcome of a batch save operation (Req 1.6)."""

    batch_id: str
    success: bool
    error: str | None = None


class CachedEnrichment(BaseModel):
    """Cached enrichment result for a single feedback text (Req 2.1, 2.9)."""

    themes: list[ThemeAssignment]
    sentiment: SentimentValue
    sentiment_confidence: float = Field(ge=0.0, le=1.0)
    severity_score: int = Field(ge=1, le=5)
    severity_factors: list[SeverityFactor]
    cached_at: str  # ISO 8601 UTC


class CacheEntry(BaseModel):
    """Storage representation of a cache entry with TTL tracking (Req 2.1)."""

    key: str
    enrichment: CachedEnrichment
    created_at: str  # ISO 8601 UTC
    expires_at: str  # ISO 8601 UTC


class LanguageDetectionResult(BaseModel):
    """Output of language detection for a FeedbackRecord (Req 5.3, 5.5)."""

    record_id: str
    language_code: str  # ISO 639-1
    confidence: float = Field(ge=0.0, le=1.0)
    is_uncertain: bool = False
    note: str | None = None


class TimeWindow(BaseModel):
    """A start/end time range for trend analysis (Req 3.2)."""

    start: str  # ISO 8601 UTC
    end: str  # ISO 8601 UTC


class ThemeSpike(BaseModel):
    """A single theme whose frequency spiked (Req 3.5)."""

    theme: str
    baseline_frequency: float = Field(ge=0.0, le=1.0)
    current_frequency: float = Field(ge=0.0, le=1.0)
    percentage_increase: float | str  # float or "new" for new themes


class SentimentShift(BaseModel):
    """An identified shift in negative sentiment proportion (Req 4.1, 4.5)."""

    baseline_negative_proportion: float = Field(ge=0.0, le=1.0)
    current_negative_proportion: float = Field(ge=0.0, le=1.0)
    difference_ppt: float  # percentage points


class SeverityEscalation(BaseModel):
    """An identified escalation in mean severity (Req 4.5)."""

    baseline_mean_severity: float = Field(ge=1.0, le=5.0)
    current_mean_severity: float = Field(ge=1.0, le=5.0)
    difference: float


class TrendReport(BaseModel):
    """Complete trend analysis output (Req 3.5, 4.5)."""

    theme_spikes: list[ThemeSpike] = Field(default_factory=list)
    sentiment_shifts: list[SentimentShift] = Field(default_factory=list)
    severity_escalations: list[SeverityEscalation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


__all__ = [
    "BatchMetadata",
    "SaveResult",
    "CachedEnrichment",
    "CacheEntry",
    "LanguageDetectionResult",
    "TimeWindow",
    "ThemeSpike",
    "SentimentShift",
    "SeverityEscalation",
    "TrendReport",
]
