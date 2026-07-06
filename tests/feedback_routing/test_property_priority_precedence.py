"""Property-based test for priority level precedence rules.

# Feature: nlp-feedback-routing, Property 7

**Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6**

Property 7: Priority Level Follows Precedence Rules — For any feedback
analysis result, the Priority_Scorer SHALL assign the highest applicable
priority level by evaluating criteria in descending order (critical → high →
medium → low): critical when outage keywords + sentiment < -0.7 OR escalation
language; high when sentiment < -0.5 OR cluster volume > 10; medium when
sentiment in [-0.5, -0.2) OR intent in {request_for_help, billing_dispute};
low otherwise.
"""

from __future__ import annotations

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from nlp_processing.enrichment.priority_scorer import (
    CRITICAL_SENTIMENT_THRESHOLD,
    ESCALATION_KEYWORDS,
    HIGH_SENTIMENT_THRESHOLD,
    MEDIUM_INTENTS,
    MEDIUM_SENTIMENT_LOWER,
    MEDIUM_SENTIMENT_UPPER,
    OUTAGE_KEYWORDS,
    PriorityScorer,
)
from nlp_processing.models.feedback_routing import (
    CanonicalFeedback,
    FeedbackAnalysis,
)
from tests.feedback_routing.strategies import (
    canonical_feedback_records,
    feedback_analysis_records,
    intent_types,
    sentiment_scores,
    timestamp_iso,
    theme_categories,
    _uuid_text,
)


# ---------------------------------------------------------------------------
# Strategies tailored for priority precedence testing
# ---------------------------------------------------------------------------

# Keywords that trigger critical priority
_OUTAGE_KEYWORD_SAMPLES = st.sampled_from(OUTAGE_KEYWORDS)
_ESCALATION_KEYWORD_SAMPLES = st.sampled_from(ESCALATION_KEYWORDS)

# Sentiments for specific ranges
_critical_sentiments = st.floats(
    min_value=-1.0, max_value=-0.71, allow_nan=False, allow_infinity=False
)
_high_sentiments = st.floats(
    min_value=-0.51, max_value=-0.50001, allow_nan=False, allow_infinity=False
)
_medium_sentiments = st.floats(
    min_value=-0.5, max_value=-0.20001, allow_nan=False, allow_infinity=False
)
_neutral_sentiments = st.floats(
    min_value=-0.2, max_value=1.0, allow_nan=False, allow_infinity=False
)

# Non-triggering text (no outage or escalation keywords)
_SAFE_TEXT_CHARS = st.characters(min_codepoint=65, max_codepoint=90)  # A-Z only
_safe_text = st.text(alphabet=_SAFE_TEXT_CHARS, min_size=5, max_size=100)

# Non-medium intents (those that don't trigger medium priority by intent)
_NON_MEDIUM_INTENTS = [
    "complaint", "outage_report", "feature_suggestion",
    "praise", "cancellation_risk", "unclassified",
]


def _make_canonical(cleaned_text: str, draw) -> CanonicalFeedback:
    """Helper to create a CanonicalFeedback with specific cleaned_text."""
    return CanonicalFeedback(
        feedback_id=draw(_uuid_text),
        source_type=draw(st.sampled_from(["social", "widget"])),
        original_source_id=draw(_uuid_text),
        cleaned_text=cleaned_text,
        detected_language="en",
        ingested_at=draw(timestamp_iso()),
        duplicate_count=0,
        profanity_detected=False,
        metadata={},
        processing_status="analyzed",
    )


def _make_analysis(
    feedback_id: str,
    sentiment_score: float,
    intent: str,
    draw,
) -> FeedbackAnalysis:
    """Helper to create a FeedbackAnalysis with specific signals."""
    # Derive consistent label from score
    if sentiment_score > 0.2:
        label = "positive"
    elif sentiment_score < -0.2:
        label = "negative"
    else:
        label = "neutral"

    return FeedbackAnalysis(
        feedback_id=feedback_id,
        sentiment_label=label,
        sentiment_score=sentiment_score,
        priority_score=0.5,  # placeholder, not used by scorer input
        priority_level="medium",  # placeholder, not used by scorer input
        theme_primary=draw(theme_categories()),
        theme_secondary=None,
        intent=intent,
        cluster_id=None,
        requires_action=False,
        entities=[],
        processed_at=draw(timestamp_iso()),
    )


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

scorer = PriorityScorer()


@st.composite
def critical_outage_scenario(draw):
    """Generate a scenario that meets critical criteria via outage + severe sentiment."""
    keyword = draw(_OUTAGE_KEYWORD_SAMPLES)
    # Build text containing an outage keyword
    prefix = draw(st.text(alphabet=_SAFE_TEXT_CHARS, min_size=1, max_size=30))
    cleaned_text = f"{prefix} {keyword} issue reported"

    sentiment_score = draw(_critical_sentiments)
    intent = draw(st.sampled_from(_NON_MEDIUM_INTENTS))

    feedback = CanonicalFeedback(
        feedback_id=draw(_uuid_text),
        source_type=draw(st.sampled_from(["social", "widget"])),
        original_source_id=draw(_uuid_text),
        cleaned_text=cleaned_text,
        detected_language="en",
        ingested_at=draw(timestamp_iso()),
        duplicate_count=0,
        profanity_detected=False,
        metadata={},
        processing_status="analyzed",
    )

    analysis = _make_analysis(feedback.feedback_id, sentiment_score, intent, draw)
    cluster_volume = draw(st.integers(min_value=0, max_value=5))

    return feedback, analysis, cluster_volume


@st.composite
def critical_escalation_scenario(draw):
    """Generate a scenario that meets critical criteria via escalation language."""
    keyword = draw(_ESCALATION_KEYWORD_SAMPLES)
    prefix = draw(st.text(alphabet=_SAFE_TEXT_CHARS, min_size=1, max_size=30))
    cleaned_text = f"{prefix} contact {keyword} immediately"

    # Escalation language alone triggers critical regardless of sentiment
    sentiment_score = draw(sentiment_scores())
    intent = draw(intent_types())

    feedback = CanonicalFeedback(
        feedback_id=draw(_uuid_text),
        source_type=draw(st.sampled_from(["social", "widget"])),
        original_source_id=draw(_uuid_text),
        cleaned_text=cleaned_text,
        detected_language="en",
        ingested_at=draw(timestamp_iso()),
        duplicate_count=0,
        profanity_detected=False,
        metadata={},
        processing_status="analyzed",
    )

    analysis = _make_analysis(feedback.feedback_id, sentiment_score, intent, draw)
    cluster_volume = draw(st.integers(min_value=0, max_value=50))

    return feedback, analysis, cluster_volume


@st.composite
def high_sentiment_scenario(draw):
    """Generate a scenario that meets HIGH criteria via sentiment < -0.5 but NOT critical."""
    # Ensure no outage or escalation keywords in text
    cleaned_text = draw(_safe_text)
    # Sentiment that triggers high but NOT critical (outage+sentiment path)
    # Since there are no outage keywords, sentiment < -0.5 alone triggers high
    sentiment_score = draw(st.floats(
        min_value=-0.7, max_value=-0.50001, allow_nan=False, allow_infinity=False
    ))
    intent = draw(st.sampled_from(_NON_MEDIUM_INTENTS))

    feedback = CanonicalFeedback(
        feedback_id=draw(_uuid_text),
        source_type=draw(st.sampled_from(["social", "widget"])),
        original_source_id=draw(_uuid_text),
        cleaned_text=cleaned_text,
        detected_language="en",
        ingested_at=draw(timestamp_iso()),
        duplicate_count=0,
        profanity_detected=False,
        metadata={},
        processing_status="analyzed",
    )

    analysis = _make_analysis(feedback.feedback_id, sentiment_score, intent, draw)
    cluster_volume = draw(st.integers(min_value=0, max_value=10))

    return feedback, analysis, cluster_volume


@st.composite
def high_cluster_volume_scenario(draw):
    """Generate a scenario that meets HIGH criteria via cluster volume > 10 but NOT critical."""
    cleaned_text = draw(_safe_text)
    # Sentiment must be >= -0.5 (not trigger high via sentiment) and in neutral range
    # to isolate the cluster volume trigger
    sentiment_score = draw(_neutral_sentiments)
    intent = draw(st.sampled_from(_NON_MEDIUM_INTENTS))
    cluster_volume = draw(st.integers(min_value=11, max_value=100))

    feedback = CanonicalFeedback(
        feedback_id=draw(_uuid_text),
        source_type=draw(st.sampled_from(["social", "widget"])),
        original_source_id=draw(_uuid_text),
        cleaned_text=cleaned_text,
        detected_language="en",
        ingested_at=draw(timestamp_iso()),
        duplicate_count=0,
        profanity_detected=False,
        metadata={},
        processing_status="analyzed",
    )

    analysis = _make_analysis(feedback.feedback_id, sentiment_score, intent, draw)

    return feedback, analysis, cluster_volume


@st.composite
def medium_sentiment_scenario(draw):
    """Generate a scenario that meets MEDIUM criteria via sentiment in [-0.5, -0.2)."""
    cleaned_text = draw(_safe_text)
    # Sentiment in [-0.5, -0.2) — triggers medium but not high (high requires < -0.5 strict)
    sentiment_score = draw(_medium_sentiments)
    intent = draw(st.sampled_from(_NON_MEDIUM_INTENTS))
    cluster_volume = draw(st.integers(min_value=0, max_value=10))

    feedback = CanonicalFeedback(
        feedback_id=draw(_uuid_text),
        source_type=draw(st.sampled_from(["social", "widget"])),
        original_source_id=draw(_uuid_text),
        cleaned_text=cleaned_text,
        detected_language="en",
        ingested_at=draw(timestamp_iso()),
        duplicate_count=0,
        profanity_detected=False,
        metadata={},
        processing_status="analyzed",
    )

    analysis = _make_analysis(feedback.feedback_id, sentiment_score, intent, draw)

    return feedback, analysis, cluster_volume


@st.composite
def medium_intent_scenario(draw):
    """Generate a scenario that meets MEDIUM criteria via intent."""
    cleaned_text = draw(_safe_text)
    # Neutral sentiment (>= -0.2) so medium is triggered only by intent
    sentiment_score = draw(_neutral_sentiments)
    intent = draw(st.sampled_from(sorted(MEDIUM_INTENTS)))
    cluster_volume = draw(st.integers(min_value=0, max_value=10))

    feedback = CanonicalFeedback(
        feedback_id=draw(_uuid_text),
        source_type=draw(st.sampled_from(["social", "widget"])),
        original_source_id=draw(_uuid_text),
        cleaned_text=cleaned_text,
        detected_language="en",
        ingested_at=draw(timestamp_iso()),
        duplicate_count=0,
        profanity_detected=False,
        metadata={},
        processing_status="analyzed",
    )

    analysis = _make_analysis(feedback.feedback_id, sentiment_score, intent, draw)

    return feedback, analysis, cluster_volume


@st.composite
def low_priority_scenario(draw):
    """Generate a scenario where no higher-level criteria are met → LOW."""
    cleaned_text = draw(_safe_text)
    # Sentiment >= -0.2 (no medium/high/critical trigger)
    sentiment_score = draw(_neutral_sentiments)
    # Intent not in medium set
    intent = draw(st.sampled_from(_NON_MEDIUM_INTENTS))
    # Cluster volume <= 10 (no high trigger)
    cluster_volume = draw(st.integers(min_value=0, max_value=10))

    feedback = CanonicalFeedback(
        feedback_id=draw(_uuid_text),
        source_type=draw(st.sampled_from(["social", "widget"])),
        original_source_id=draw(_uuid_text),
        cleaned_text=cleaned_text,
        detected_language="en",
        ingested_at=draw(timestamp_iso()),
        duplicate_count=0,
        profanity_detected=False,
        metadata={},
        processing_status="analyzed",
    )

    analysis = _make_analysis(feedback.feedback_id, sentiment_score, intent, draw)

    return feedback, analysis, cluster_volume


# ---------------------------------------------------------------------------
# Test: Critical priority via outage keywords + severe sentiment (Req 7.2)
# ---------------------------------------------------------------------------


@given(scenario=critical_outage_scenario())
@settings(max_examples=100)
def test_critical_priority_outage_keywords(scenario) -> None:
    """Critical is assigned when outage keywords present AND sentiment < -0.7.

    # Feature: nlp-feedback-routing, Property 7
    **Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6**
    """
    feedback, analysis, cluster_volume = scenario
    result = scorer.score(feedback, analysis, cluster_volume=cluster_volume)

    assert result.priority_level == "critical", (
        f"Expected 'critical' but got '{result.priority_level}' "
        f"(text contains outage keyword, sentiment={analysis.sentiment_score})"
    )


# ---------------------------------------------------------------------------
# Test: Critical priority via escalation language (Req 7.2)
# ---------------------------------------------------------------------------


@given(scenario=critical_escalation_scenario())
@settings(max_examples=100)
def test_critical_priority_escalation_language(scenario) -> None:
    """Critical is assigned when escalation language is detected.

    # Feature: nlp-feedback-routing, Property 7
    **Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6**
    """
    feedback, analysis, cluster_volume = scenario
    result = scorer.score(feedback, analysis, cluster_volume=cluster_volume)

    assert result.priority_level == "critical", (
        f"Expected 'critical' but got '{result.priority_level}' "
        f"(text contains escalation keyword, sentiment={analysis.sentiment_score})"
    )


# ---------------------------------------------------------------------------
# Test: High priority via sentiment < -0.5 (Req 7.3)
# ---------------------------------------------------------------------------


@given(scenario=high_sentiment_scenario())
@settings(max_examples=100)
def test_high_priority_negative_sentiment(scenario) -> None:
    """High is assigned when sentiment < -0.5 and no critical criteria met.

    # Feature: nlp-feedback-routing, Property 7
    **Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6**
    """
    feedback, analysis, cluster_volume = scenario
    result = scorer.score(feedback, analysis, cluster_volume=cluster_volume)

    assert result.priority_level == "high", (
        f"Expected 'high' but got '{result.priority_level}' "
        f"(sentiment={analysis.sentiment_score}, cluster_vol={cluster_volume})"
    )


# ---------------------------------------------------------------------------
# Test: High priority via cluster volume > 10 (Req 7.3)
# ---------------------------------------------------------------------------


@given(scenario=high_cluster_volume_scenario())
@settings(max_examples=100)
def test_high_priority_cluster_volume(scenario) -> None:
    """High is assigned when cluster volume > 10 and no critical criteria met.

    # Feature: nlp-feedback-routing, Property 7
    **Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6**
    """
    feedback, analysis, cluster_volume = scenario
    result = scorer.score(feedback, analysis, cluster_volume=cluster_volume)

    assert result.priority_level == "high", (
        f"Expected 'high' but got '{result.priority_level}' "
        f"(sentiment={analysis.sentiment_score}, cluster_vol={cluster_volume})"
    )


# ---------------------------------------------------------------------------
# Test: Medium priority via sentiment in [-0.5, -0.2) (Req 7.4)
# ---------------------------------------------------------------------------


@given(scenario=medium_sentiment_scenario())
@settings(max_examples=100)
def test_medium_priority_sentiment_range(scenario) -> None:
    """Medium is assigned when sentiment in [-0.5, -0.2) and no higher criteria met.

    # Feature: nlp-feedback-routing, Property 7
    **Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6**
    """
    feedback, analysis, cluster_volume = scenario
    result = scorer.score(feedback, analysis, cluster_volume=cluster_volume)

    assert result.priority_level == "medium", (
        f"Expected 'medium' but got '{result.priority_level}' "
        f"(sentiment={analysis.sentiment_score}, intent={analysis.intent})"
    )


# ---------------------------------------------------------------------------
# Test: Medium priority via intent in {request_for_help, billing_dispute} (Req 7.4)
# ---------------------------------------------------------------------------


@given(scenario=medium_intent_scenario())
@settings(max_examples=100)
def test_medium_priority_intent_trigger(scenario) -> None:
    """Medium is assigned when intent is in MEDIUM_INTENTS set and no higher criteria met.

    # Feature: nlp-feedback-routing, Property 7
    **Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6**
    """
    feedback, analysis, cluster_volume = scenario
    result = scorer.score(feedback, analysis, cluster_volume=cluster_volume)

    assert result.priority_level == "medium", (
        f"Expected 'medium' but got '{result.priority_level}' "
        f"(sentiment={analysis.sentiment_score}, intent={analysis.intent})"
    )


# ---------------------------------------------------------------------------
# Test: Low priority when no higher-level criteria are met (Req 7.5)
# ---------------------------------------------------------------------------


@given(scenario=low_priority_scenario())
@settings(max_examples=100)
def test_low_priority_default(scenario) -> None:
    """Low is assigned when no critical, high, or medium criteria are met.

    # Feature: nlp-feedback-routing, Property 7
    **Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6**
    """
    feedback, analysis, cluster_volume = scenario
    result = scorer.score(feedback, analysis, cluster_volume=cluster_volume)

    assert result.priority_level == "low", (
        f"Expected 'low' but got '{result.priority_level}' "
        f"(sentiment={analysis.sentiment_score}, intent={analysis.intent}, "
        f"cluster_vol={cluster_volume})"
    )


# ---------------------------------------------------------------------------
# Test: Precedence — critical > high > medium > low (Req 7.6)
# ---------------------------------------------------------------------------

PRIORITY_ORDER = {"critical": 3, "high": 2, "medium": 1, "low": 0}


@given(
    feedback=canonical_feedback_records(),
    analysis=feedback_analysis_records(),
    cluster_volume=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=100)
def test_precedence_highest_level_assigned(
    feedback: CanonicalFeedback,
    analysis: FeedbackAnalysis,
    cluster_volume: int,
) -> None:
    """The highest applicable priority level is always assigned (Req 7.6).

    For any combination of signals, independently check which criteria are met
    and verify the scorer assigns the highest matching level.

    # Feature: nlp-feedback-routing, Property 7
    **Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6**
    """
    # Sync feedback_id between feedback and analysis for consistency
    analysis = analysis.model_copy(update={"feedback_id": feedback.feedback_id})

    result = scorer.score(feedback, analysis, cluster_volume=cluster_volume)

    # Independently determine which levels are applicable
    text_lower = feedback.cleaned_text.lower()

    # Check critical criteria (Req 7.2)
    has_outage = any(kw in text_lower for kw in OUTAGE_KEYWORDS)
    severe_sentiment = analysis.sentiment_score < CRITICAL_SENTIMENT_THRESHOLD
    has_escalation = any(kw in text_lower for kw in ESCALATION_KEYWORDS)
    is_critical = (has_outage and severe_sentiment) or has_escalation

    # Check high criteria (Req 7.3)
    is_high = analysis.sentiment_score < HIGH_SENTIMENT_THRESHOLD or cluster_volume > 10

    # Check medium criteria (Req 7.4)
    is_medium = (
        MEDIUM_SENTIMENT_LOWER <= analysis.sentiment_score < MEDIUM_SENTIMENT_UPPER
    ) or (analysis.intent in MEDIUM_INTENTS)

    # Determine expected level based on precedence
    if is_critical:
        expected_level = "critical"
    elif is_high:
        expected_level = "high"
    elif is_medium:
        expected_level = "medium"
    else:
        expected_level = "low"

    assert result.priority_level == expected_level, (
        f"Precedence violation: expected '{expected_level}' but got "
        f"'{result.priority_level}' "
        f"(is_critical={is_critical}, is_high={is_high}, is_medium={is_medium}, "
        f"sentiment={analysis.sentiment_score}, intent={analysis.intent}, "
        f"cluster_vol={cluster_volume}, text_snippet={feedback.cleaned_text[:50]!r})"
    )
