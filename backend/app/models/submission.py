"""Pydantic v2 models for customer submissions."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SubmissionCreate(BaseModel):
    """Payload for POST /api/submissions."""

    customer_name: str = Field(min_length=1, max_length=100)
    email: str | None = None
    phone: str | None = None
    core_request: str = Field(min_length=1, max_length=5000)
    sentiment: Literal["negative", "positive", "neutral"]
    # Negative-specific
    issue_category: str | None = None
    detailed_description: str | None = None
    # Positive-specific
    praise_text: str | None = None
    social_sharing: bool = False
    # Neutral-specific
    comment_text: str | None = None


class StateTransition(BaseModel):
    """Records a progress state change."""

    previous_state: int
    new_state: int
    timestamp: datetime


class EnrichmentResult(BaseModel):
    """NLP analysis output stored on a submission."""

    themes: list[dict] = Field(default_factory=list)
    sentiment_confidence: float = Field(ge=0.0, le=1.0)
    severity_score: int = Field(ge=1, le=5)
    severity_factors: list[str] = Field(default_factory=list)
    language_code: str | None = None
    language_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class Submission(BaseModel):
    """Full submission record."""

    id: UUID
    created_at: datetime
    customer_name: str
    email: str | None = None
    phone: str | None = None
    core_request: str
    sentiment: Literal["negative", "positive", "neutral"]
    progress_state: int = Field(description="One of 25, 50, 75, or 100")
    issue_category: str | None = None
    detailed_description: str | None = None
    praise_text: str | None = None
    social_sharing: bool = False
    comment_text: str | None = None
    enrichment_status: Literal["pending", "completed", "failed", "timeout"] = "pending"
    enrichment_result: EnrichmentResult | None = None
    state_transitions: list[StateTransition] = Field(default_factory=list)


class StatusResponse(BaseModel):
    """Public-facing status for polling."""

    submission_id: UUID
    progress_state: int
    sentiment: Literal["negative", "positive", "neutral"]
    message: str
    enrichment_status: Literal["pending", "completed", "failed", "timeout"]
