"""Pydantic v2 models for the unified feedback model."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.submission import EnrichmentResult


class FeedbackCreate(BaseModel):
    """Payload for POST /api/feedback.

    Note: there is intentionally NO ``sentiment`` field here. Sentiment is
    never client-supplied; it is derived by the NLP enrichment pipeline
    (Requirement 2.4).
    """

    text: str = Field(min_length=1, max_length=10000)  # Req 1.4, 1.5
    contact: str | None = None


class Feedback(BaseModel):
    """Full feedback record persisted in the ``feedback`` table."""

    feedback_id: UUID
    text: str
    source_type: Literal["direct", "social"]
    channel: str | None = None
    platform: Literal["reddit", "x", "facebook"] | None = None
    created_at: datetime
    enrichment_status: Literal["pending", "completed", "failed", "timeout"] = "pending"
    enrichment_result: EnrichmentResult | None = None
    sentiment: Literal["positive", "neutral", "negative"] | None = None
    triage_outcome: Literal["action_required", "no_action"] | None = None
    triage_decision_source: Literal["automated", "admin"] | None = None
    needs_review: bool = False
    ticket_id: UUID | None = None
    # NLP-derived routing/analytics fields surfaced on the internal dashboard.
    department: str | None = None
    severity: int | None = None  # 1..10 dashboard severity scale
    severity_reasoning: str | None = None  # rationale behind the severity (ⓘ tooltip)
    location_city: str | None = None
    location_state: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class TicketComment(BaseModel):
    """A comment attached to a ticket."""

    id: int
    ticket_id: UUID
    author: str
    created_at: datetime
    text: str


class TriageRequest(BaseModel):
    """Admin manual triage decision for a feedback record."""

    outcome: Literal["action_required", "no_action"]
    ticket_id: UUID | None = None  # link to existing ticket instead of creating


class CommentCreate(BaseModel):
    """Payload for creating a ticket comment.

    Whitespace-only text is rejected in the service layer (Req 7.2).
    """

    text: str = Field(min_length=1)


class StatusTicket(BaseModel):
    """Nested ticket summary shown in the customer status view."""

    ticket_id: UUID
    status: Literal["open", "in_progress", "resolved"]


class StatusView(BaseModel):
    """Public-facing status payload for GET /api/feedback/{id}/status."""

    feedback_id: UUID
    enrichment_status: Literal["pending", "completed", "failed", "timeout"]
    triage_outcome: Literal["action_required", "no_action"] | None = None
    ticket: StatusTicket | None = None
    comments: list[TicketComment] = Field(default_factory=list)
    analysis_in_progress: bool = False
