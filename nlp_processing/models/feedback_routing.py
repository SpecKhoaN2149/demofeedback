"""Feedback routing enumerations and Pydantic v2 models.

This module defines all Literal type enumerations and structured data models
for the NLP-powered feedback routing pipeline. Models enforce field-level
constraints (ranges, enums, string lengths) at construction time using
Pydantic v2 Field validators.

Enumerations:
    ThemeCategory, IntentType, TicketPhase, RoutingDepartment, RoutingAction,
    ProcessingStatus, ClusterStatus, ResolutionType

Models:
    SocialFeedback, WidgetFeedback, CanonicalFeedback, EngagementMetrics,
    FeedbackAnalysis, ExtractedEntity, Ticket, ClusterRecord, RoutingDecision,
    PriorityResult, SentimentResult, ThemeResult, IntentResult
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Literal Type Enumerations
# ---------------------------------------------------------------------------

ThemeCategory = Literal[
    "outage",
    "billing",
    "speed_performance",
    "installation",
    "technician_visit",
    "support_experience",
    "app_usability",
    "equipment",
    "cancellation_retention",
]

IntentType = Literal[
    "complaint",
    "request_for_help",
    "outage_report",
    "billing_dispute",
    "feature_suggestion",
    "praise",
    "cancellation_risk",
    "unclassified",
]

TicketPhase = Literal[
    "new",
    "triaged",
    "routed",
    "in_progress",
    "waiting",
    "resolved",
    "closed",
    "auto_closed",
]

RoutingDepartment = Literal[
    "Network_Operations",
    "Billing_Support",
    "Technical_Support",
    "Field_Operations",
    "Digital_Product",
    "Customer_Care",
    "Retention",
    "Social_Media_Care",
    "Executive_Escalations",
]

RoutingAction = Literal[
    "auto_resolve",
    "route_to_existing",
    "create_ticket",
    "escalate",
]

ProcessingStatus = Literal[
    "ingested",
    "preprocessing",
    "preprocessed",
    "analyzing",
    "analyzed",
    "routing",
    "routed",
    "retrying",
    "failed",
]

ClusterStatus = Literal["active", "monitoring", "resolved"]

ResolutionType = Literal[
    "resolved_by_agent",
    "auto_resolved",
    "duplicate",
    "known_resolved",
    "no_action_required",
    "faq_matched",
]


# ---------------------------------------------------------------------------
# Supporting Models
# ---------------------------------------------------------------------------


class EngagementMetrics(BaseModel):
    """Social media engagement metrics for a post."""

    likes: int = Field(default=0, ge=0)
    replies: int = Field(default=0, ge=0)
    reposts: int = Field(default=0, ge=0)


# ---------------------------------------------------------------------------
# Ingestion Models
# ---------------------------------------------------------------------------


class SocialFeedback(BaseModel):
    """Raw feedback record from the Social_Listener channel."""

    feedback_id: str  # UUID
    source_type: Literal["social"]
    platform: Literal["reddit", "x", "facebook"]
    username_handle: str = Field(max_length=320)
    post_id: str
    message_text: str = Field(max_length=10_000)
    post_url: str | None = None
    created_at_original: str  # ISO 8601 UTC
    ingested_at: str  # ISO 8601 UTC
    language_code: str
    engagement_metrics: EngagementMetrics
    recency_score: float = Field(ge=0.0, le=1.0)
    location: str | None = None  # "City, CC"


class WidgetFeedback(BaseModel):
    """Raw feedback record from the Widget_Intake channel."""

    feedback_id: str  # UUID
    source_type: Literal["widget"]
    submission_channel: Literal["app_widget", "website_form", "support_intake_form"]
    message_text: str = Field(min_length=1, max_length=10_000)
    created_at: str  # ISO 8601 UTC
    consent_to_contact: bool
    customer_id: str | None = None
    account_type: str | None = None
    selected_category: ThemeCategory | None = None
    location: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Preprocessing Models
# ---------------------------------------------------------------------------


class CanonicalFeedback(BaseModel):
    """Unified feedback schema produced by the Preprocessor."""

    feedback_id: str  # UUID
    source_type: Literal["social", "widget"]
    original_source_id: str
    cleaned_text: str = Field(min_length=1, max_length=10_000)
    detected_language: str  # ISO 639-1 or "und"
    ingested_at: str  # ISO 8601 UTC
    duplicate_count: int = Field(default=0, ge=0)
    profanity_detected: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    processing_status: ProcessingStatus = "ingested"


# ---------------------------------------------------------------------------
# NLP Analysis Result Models
# ---------------------------------------------------------------------------


class SentimentResult(BaseModel):
    """Output of the Sentiment_Analyzer."""

    sentiment_label: Literal["positive", "neutral", "negative"]
    sentiment_score: float = Field(ge=-1.0, le=1.0)


class ThemeResult(BaseModel):
    """Output of the Theme_Detector."""

    primary_theme: str
    secondary_theme: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class IntentResult(BaseModel):
    """Output of the Intent_Classifier."""

    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    requires_action: bool


class PriorityResult(BaseModel):
    """Output of the Priority_Scorer."""

    priority_level: Literal["low", "medium", "high", "critical"]
    priority_score: float = Field(ge=0.0, le=1.0)


class ExtractedEntity(BaseModel):
    """A single entity extracted from feedback text."""

    entity_type: Literal[
        "service_area",
        "product_name",
        "time_reference",
        "dollar_amount",
        "equipment_name",
        "outage_mention",
        "competitor_mention",
    ]
    entity_value: str = Field(max_length=200)
    confidence: float = Field(ge=0.5, le=1.0)


class FeedbackAnalysis(BaseModel):
    """Complete NLP analysis result for a single feedback record."""

    feedback_id: str
    sentiment_label: Literal["positive", "neutral", "negative"]
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    priority_score: float = Field(ge=0.0, le=1.0)
    priority_level: Literal["low", "medium", "high", "critical"]
    theme_primary: str
    theme_secondary: str | None = None
    intent: str
    cluster_id: str | None = None
    requires_action: bool
    entities: list[ExtractedEntity] = Field(default_factory=list)
    processed_at: str  # ISO 8601 UTC


# ---------------------------------------------------------------------------
# Ticket and Cluster Models
# ---------------------------------------------------------------------------


class Ticket(BaseModel):
    """An operational ticket created by the Decision_Engine."""

    ticket_id: str  # UUID
    ticket_phase: TicketPhase
    priority_level: Literal["low", "medium", "high", "critical"]
    assigned_department: RoutingDepartment
    created_at: str  # ISO 8601 UTC
    updated_at: str  # ISO 8601 UTC
    resolution_type: ResolutionType | None = None
    resolution_notes: str | None = Field(default=None, max_length=2000)
    linked_cluster_id: str | None = None


class ClusterRecord(BaseModel):
    """A cluster grouping related feedback records."""

    cluster_id: str  # UUID
    theme: str = Field(max_length=120)
    cluster_summary: str | None = Field(default=None, max_length=500)
    volume_count: int = Field(ge=1, default=1)
    sentiment_trend: str | None = Field(default=None, max_length=50)
    priority_level: Literal["low", "medium", "high", "critical"]
    first_seen_at: str  # ISO 8601 UTC
    last_seen_at: str  # ISO 8601 UTC
    status: ClusterStatus = "active"


# ---------------------------------------------------------------------------
# Routing Decision Model
# ---------------------------------------------------------------------------


class RoutingDecision(BaseModel):
    """Output of the Decision_Engine evaluation."""

    routing_action: RoutingAction
    ticket: Ticket | None = None
    linked_ticket_id: str | None = None  # for route_to_existing
    resolution_type: ResolutionType | None = None
    department: RoutingDepartment | None = None
    evaluation_timestamp: str  # ISO 8601 UTC


__all__ = [
    # Enumerations
    "ThemeCategory",
    "IntentType",
    "TicketPhase",
    "RoutingDepartment",
    "RoutingAction",
    "ProcessingStatus",
    "ClusterStatus",
    "ResolutionType",
    # Models
    "EngagementMetrics",
    "SocialFeedback",
    "WidgetFeedback",
    "CanonicalFeedback",
    "SentimentResult",
    "ThemeResult",
    "IntentResult",
    "PriorityResult",
    "ExtractedEntity",
    "FeedbackAnalysis",
    "Ticket",
    "ClusterRecord",
    "RoutingDecision",
]
