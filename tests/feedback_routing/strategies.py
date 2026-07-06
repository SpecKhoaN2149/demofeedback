"""Shared Hypothesis strategies for the NLP Feedback Routing test suite.

Centralizes reusable generators for property-based tests across the feedback
routing feature. Each strategy constrains to the valid input space defined by
the Pydantic models in ``nlp_processing.models.feedback_routing``.

Strategies provided:
- theme_categories()           — valid ThemeCategory values
- intent_types()               — valid IntentType values
- sentiment_scores()           — floats in [-1.0, +1.0]
- sentiment_labels()           — valid sentiment label strings
- priority_scores()            — floats in [0.0, 1.0]
- priority_levels()            — valid priority level strings
- ticket_phases()              — valid TicketPhase values
- ticket_phase_pairs()         — (current, next) phase pairs for transition tests
- valid_timestamp_pairs()      — (created_at, ingested_at) where ingested >= created
- routing_departments()        — valid RoutingDepartment values
- routing_actions()            — valid RoutingAction values
- processing_statuses()        — valid ProcessingStatus values
- extracted_entities()         — valid ExtractedEntity records
- feedback_analysis_records()  — valid FeedbackAnalysis records
- canonical_feedback_records() — valid CanonicalFeedback records

Configuration: All property tests using these strategies should apply
``@settings(max_examples=100)``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import get_args

from hypothesis import settings, strategies as st

from nlp_processing.models.feedback_routing import (
    CanonicalFeedback,
    ClusterStatus,
    ExtractedEntity,
    FeedbackAnalysis,
    IntentType,
    ProcessingStatus,
    RoutingAction,
    RoutingDepartment,
    ThemeCategory,
    TicketPhase,
)

# ---------------------------------------------------------------------------
# Default Hypothesis settings for feedback routing property tests
# ---------------------------------------------------------------------------

feedback_routing_settings = settings(max_examples=100)
"""Apply to all property tests: ``@feedback_routing_settings``."""


# ---------------------------------------------------------------------------
# Enumeration strategies
# ---------------------------------------------------------------------------

# Extract all valid literal values from the type aliases.
THEME_CATEGORY_VALUES: tuple[str, ...] = get_args(ThemeCategory)
INTENT_TYPE_VALUES: tuple[str, ...] = get_args(IntentType)
TICKET_PHASE_VALUES: tuple[str, ...] = get_args(TicketPhase)
ROUTING_DEPARTMENT_VALUES: tuple[str, ...] = get_args(RoutingDepartment)
ROUTING_ACTION_VALUES: tuple[str, ...] = get_args(RoutingAction)
PROCESSING_STATUS_VALUES: tuple[str, ...] = get_args(ProcessingStatus)
CLUSTER_STATUS_VALUES: tuple[str, ...] = get_args(ClusterStatus)

# Sentiment and priority enumerations (not defined as top-level Literal aliases
# in the models module, but used as inline Literal fields).
SENTIMENT_LABELS = ("positive", "neutral", "negative")
PRIORITY_LEVELS = ("low", "medium", "high", "critical")

# Valid ticket phase transitions (from design document).
VALID_TRANSITIONS: set[tuple[str, str]] = {
    ("new", "triaged"),
    ("triaged", "routed"),
    ("routed", "in_progress"),
    ("in_progress", "waiting"),
    ("in_progress", "resolved"),
    ("waiting", "in_progress"),
    ("waiting", "resolved"),
    ("resolved", "closed"),
}

# Terminal phases that cannot transition.
TERMINAL_PHASES = ("closed", "auto_closed")


def theme_categories() -> st.SearchStrategy[str]:
    """Strategy producing valid ThemeCategory values."""
    return st.sampled_from(THEME_CATEGORY_VALUES)


def intent_types() -> st.SearchStrategy[str]:
    """Strategy producing valid IntentType values."""
    return st.sampled_from(INTENT_TYPE_VALUES)


def ticket_phases() -> st.SearchStrategy[str]:
    """Strategy producing valid TicketPhase values."""
    return st.sampled_from(TICKET_PHASE_VALUES)


def routing_departments() -> st.SearchStrategy[str]:
    """Strategy producing valid RoutingDepartment values."""
    return st.sampled_from(ROUTING_DEPARTMENT_VALUES)


def routing_actions() -> st.SearchStrategy[str]:
    """Strategy producing valid RoutingAction values."""
    return st.sampled_from(ROUTING_ACTION_VALUES)


def processing_statuses() -> st.SearchStrategy[str]:
    """Strategy producing valid ProcessingStatus values."""
    return st.sampled_from(PROCESSING_STATUS_VALUES)


def sentiment_labels() -> st.SearchStrategy[str]:
    """Strategy producing valid sentiment label values."""
    return st.sampled_from(SENTIMENT_LABELS)


def priority_levels() -> st.SearchStrategy[str]:
    """Strategy producing valid priority level values."""
    return st.sampled_from(PRIORITY_LEVELS)


# ---------------------------------------------------------------------------
# Numeric score strategies
# ---------------------------------------------------------------------------

def sentiment_scores() -> st.SearchStrategy[float]:
    """Strategy producing valid sentiment scores in [-1.0, +1.0].

    Uses finite floats only (no NaN, no infinity).
    """
    return st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)


def priority_scores() -> st.SearchStrategy[float]:
    """Strategy producing valid priority scores in [0.0, 1.0].

    Uses finite floats only (no NaN, no infinity).
    """
    return st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# Ticket phase pair strategies
# ---------------------------------------------------------------------------

def valid_ticket_phase_pairs() -> st.SearchStrategy[tuple[str, str]]:
    """Strategy producing valid (current_phase, next_phase) transition pairs.

    Only yields pairs that the transition matrix accepts.
    """
    return st.sampled_from(sorted(VALID_TRANSITIONS))


def invalid_ticket_phase_pairs() -> st.SearchStrategy[tuple[str, str]]:
    """Strategy producing invalid (current_phase, next_phase) transition pairs.

    Yields pairs that the transition matrix should reject.
    """
    all_pairs = {
        (p, q) for p in TICKET_PHASE_VALUES for q in TICKET_PHASE_VALUES if p != q
    }
    invalid_pairs = sorted(all_pairs - VALID_TRANSITIONS)
    return st.sampled_from(invalid_pairs)


def ticket_phase_pairs() -> st.SearchStrategy[tuple[str, str, bool]]:
    """Strategy producing (current_phase, next_phase, is_valid) triples.

    Mixes valid and invalid transitions for comprehensive testing.
    """
    valid = valid_ticket_phase_pairs().map(lambda pair: (pair[0], pair[1], True))
    invalid = invalid_ticket_phase_pairs().map(lambda pair: (pair[0], pair[1], False))
    return st.one_of(valid, invalid)


# ---------------------------------------------------------------------------
# Timestamp strategies
# ---------------------------------------------------------------------------

def _iso_timestamp(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC string."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@st.composite
def valid_timestamp_pairs(draw: st.DrawFn) -> tuple[str, str]:
    """Strategy producing (created_at_original, ingested_at) timestamp pairs.

    Guarantees ingested_at >= created_at_original.
    Generates timestamps spanning from 2020 to 2025 with elapsed time
    ranging from 0 to 60 days (well beyond the 30-day recency window).
    """
    # Base timestamp: random point between 2020-01-01 and 2024-12-31
    base_ts = draw(
        st.floats(
            min_value=datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp(),
            max_value=datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp(),
            allow_nan=False,
            allow_infinity=False,
        )
    )
    created_at = datetime.fromtimestamp(base_ts, tz=timezone.utc)

    # Elapsed hours: 0 to 1440 hours (60 days) — covers both in-range and
    # out-of-range for the 720-hour recency formula.
    elapsed_hours = draw(
        st.floats(min_value=0.0, max_value=1440.0, allow_nan=False, allow_infinity=False)
    )
    ingested_at = created_at + timedelta(hours=elapsed_hours)

    return _iso_timestamp(created_at), _iso_timestamp(ingested_at)


@st.composite
def timestamp_iso(draw: st.DrawFn) -> str:
    """Strategy producing a single valid ISO 8601 UTC timestamp string."""
    ts = draw(
        st.floats(
            min_value=datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp(),
            max_value=datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp(),
            allow_nan=False,
            allow_infinity=False,
        )
    )
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return _iso_timestamp(dt)


# ---------------------------------------------------------------------------
# Model record strategies
# ---------------------------------------------------------------------------

# Printable ASCII for text fields (avoids surrogate/control-char issues in
# JSON round-trip tests while still exercising punctuation and whitespace).
_PRINTABLE = st.characters(min_codepoint=32, max_codepoint=126)

# Short identifiers for UUIDs and reference fields.
_uuid_text = st.text(
    alphabet="abcdef0123456789-",
    min_size=8,
    max_size=36,
)


@st.composite
def extracted_entities(draw: st.DrawFn) -> ExtractedEntity:
    """Strategy producing valid ExtractedEntity records."""
    entity_types = get_args(ExtractedEntity.model_fields["entity_type"].annotation)
    return ExtractedEntity(
        entity_type=draw(st.sampled_from(entity_types)),
        entity_value=draw(st.text(alphabet=_PRINTABLE, min_size=1, max_size=50)),
        confidence=draw(
            st.floats(min_value=0.5, max_value=1.0, allow_nan=False, allow_infinity=False)
        ),
    )


@st.composite
def feedback_analysis_records(draw: st.DrawFn) -> FeedbackAnalysis:
    """Strategy producing valid FeedbackAnalysis records.

    All fields satisfy Pydantic constraints: scores in range, valid enum
    values, proper timestamp format, and 0-5 extracted entities.
    """
    sentiment_score = draw(sentiment_scores())

    # Derive consistent label from score (Property 5)
    if sentiment_score > 0.2:
        label = "positive"
    elif sentiment_score < -0.2:
        label = "negative"
    else:
        label = "neutral"

    priority_score_val = draw(priority_scores())

    # Derive consistent level from score (Property 8)
    if priority_score_val >= 0.75:
        level = "critical"
    elif priority_score_val >= 0.50:
        level = "high"
    elif priority_score_val >= 0.25:
        level = "medium"
    else:
        level = "low"

    entities = draw(st.lists(extracted_entities(), min_size=0, max_size=5))

    return FeedbackAnalysis(
        feedback_id=draw(_uuid_text),
        sentiment_label=label,
        sentiment_score=sentiment_score,
        priority_score=priority_score_val,
        priority_level=level,
        theme_primary=draw(theme_categories()),
        theme_secondary=draw(st.one_of(st.none(), theme_categories())),
        intent=draw(intent_types()),
        cluster_id=draw(st.one_of(st.none(), _uuid_text)),
        requires_action=draw(st.booleans()),
        entities=entities,
        processed_at=draw(timestamp_iso()),
    )


@st.composite
def canonical_feedback_records(draw: st.DrawFn) -> CanonicalFeedback:
    """Strategy producing valid CanonicalFeedback records.

    All fields satisfy Pydantic constraints: text length 1-10000, valid
    source_type, proper timestamp, and valid processing_status.
    """
    source_type = draw(st.sampled_from(["social", "widget"]))

    # cleaned_text: non-empty, max 10000 chars, printable ASCII
    cleaned_text = draw(st.text(alphabet=_PRINTABLE, min_size=1, max_size=200))

    # Language code: ISO 639-1 (2-letter) or "und"
    language_code = draw(
        st.sampled_from(["en", "es", "fr", "de", "pt", "ja", "zh", "und"])
    )

    return CanonicalFeedback(
        feedback_id=draw(_uuid_text),
        source_type=source_type,
        original_source_id=draw(_uuid_text),
        cleaned_text=cleaned_text,
        detected_language=language_code,
        ingested_at=draw(timestamp_iso()),
        duplicate_count=draw(st.integers(min_value=0, max_value=100)),
        profanity_detected=draw(st.booleans()),
        metadata=draw(
            st.fixed_dictionaries({}, optional={
                "platform": st.sampled_from(["reddit", "x", "facebook"]),
                "location": st.text(alphabet=_PRINTABLE, min_size=1, max_size=50),
            })
        ),
        processing_status=draw(processing_statuses()),
    )
