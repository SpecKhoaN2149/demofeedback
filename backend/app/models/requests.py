"""Pydantic v2 models for request/response pagination, sorting, and trend analysis."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    """Pagination parameters for list endpoints."""

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SortRequest(BaseModel):
    """Request body for sorting a neutral submission."""

    target_sentiment: Literal["negative", "positive"]
    issue_category: str | None = None  # Required when target_sentiment is "negative"


class TimeWindow(BaseModel):
    """A time window defined by start and end datetimes."""

    start: datetime
    end: datetime


class TrendAnalysisRequest(BaseModel):
    """Request body for trend analysis."""

    baseline_window: TimeWindow
    current_window: TimeWindow


class PaginatedResponse(BaseModel):
    """Generic paginated response wrapper."""

    items: list = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int
    offset: int


class DashboardSummary(BaseModel):
    """Admin dashboard summary statistics."""

    total_submissions: int = Field(ge=0)
    by_sentiment: dict[str, int] = Field(default_factory=dict)
    by_progress_state: dict[str, int] = Field(default_factory=dict)
    top_categories: list[dict] = Field(default_factory=list)
    # NLP enrichment analytics (surfaced in the "NLP Insights" dashboard panel).
    enrichment_status_counts: dict[str, int] = Field(default_factory=dict)
    top_themes: list[dict] = Field(default_factory=list)
    average_severity: float | None = None
    by_language: dict[str, int] = Field(default_factory=dict)
