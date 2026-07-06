"""Unit tests for the PriorityScorer (task 5.8, Req 7.1–7.8).

Tests cover:
* Critical priority: outage keywords + sentiment < -0.7, escalation language (Req 7.2)
* High priority: sentiment < -0.5, cluster volume > 10 (Req 7.3)
* Medium priority: sentiment in [-0.5, -0.2), intent triggers (Req 7.4)
* Low priority: default when no higher criteria met (Req 7.5)
* Precedence order: critical > high > medium > low (Req 7.6)
* Score range consistency: score within level-specific range (Req 7.8)
"""

from __future__ import annotations

import pytest

from nlp_processing.enrichment.priority_scorer import (
    ESCALATION_KEYWORDS,
    MEDIUM_INTENTS,
    OUTAGE_KEYWORDS,
    SCORE_RANGES,
    PriorityScorer,
)
from nlp_processing.models.feedback_routing import (
    CanonicalFeedback,
    FeedbackAnalysis,
    PriorityResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_feedback(text: str = "General feedback about the service") -> CanonicalFeedback:
    """Create a CanonicalFeedback record for testing."""
    return CanonicalFeedback(
        feedback_id="test-priority-001",
        source_type="widget",
        original_source_id="widget-sub-001",
        cleaned_text=text,
        detected_language="en",
        ingested_at="2024-01-15T10:00:00Z",
    )


def _make_analysis(
    sentiment_score: float = 0.0,
    sentiment_label: str = "neutral",
    intent: str = "complaint",
    cluster_id: str | None = None,
) -> FeedbackAnalysis:
    """Create a FeedbackAnalysis record for testing."""
    # Derive label from score for consistency
    if sentiment_score > 0.2:
        sentiment_label = "positive"
    elif sentiment_score < -0.2:
        sentiment_label = "negative"
    else:
        sentiment_label = "neutral"

    return FeedbackAnalysis(
        feedback_id="test-priority-001",
        sentiment_label=sentiment_label,
        sentiment_score=sentiment_score,
        priority_score=0.0,  # placeholder, will be overwritten
        priority_level="low",  # placeholder
        theme_primary="support_experience",
        intent=intent,
        cluster_id=cluster_id,
        requires_action=True,
        processed_at="2024-01-15T10:05:00Z",
    )


def _assert_score_in_range(result: PriorityResult) -> None:
    """Assert priority_score is within the expected range for the level."""
    level = result.priority_level
    low, high = SCORE_RANGES[level]
    assert low <= result.priority_score <= high, (
        f"Score {result.priority_score} not in range [{low}, {high}] "
        f"for level '{level}'"
    )


# ---------------------------------------------------------------------------
# Test: Critical priority (Req 7.2)
# ---------------------------------------------------------------------------


class TestCriticalPriority:
    """Req 7.2: critical when outage + sentiment < -0.7 OR escalation language."""

    def test_outage_with_severe_sentiment(self):
        """Outage keyword + sentiment < -0.7 → critical."""
        feedback = _make_feedback("There is a major outage affecting all users")
        analysis = _make_analysis(sentiment_score=-0.85)
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "critical"
        _assert_score_in_range(result)

    def test_service_down_with_severe_sentiment(self):
        """'service down' keyword + sentiment < -0.7 → critical."""
        feedback = _make_feedback("The entire service down since yesterday")
        analysis = _make_analysis(sentiment_score=-0.75)
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "critical"
        _assert_score_in_range(result)

    def test_escalation_language_ceo(self):
        """Escalation keyword 'CEO' → critical regardless of sentiment."""
        feedback = _make_feedback("I am writing to the CEO about this problem")
        analysis = _make_analysis(sentiment_score=0.0)
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "critical"
        _assert_score_in_range(result)

    def test_escalation_language_lawyer(self):
        """Escalation keyword 'lawyer' → critical."""
        feedback = _make_feedback("I will get my lawyer involved if not resolved")
        analysis = _make_analysis(sentiment_score=-0.3)
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "critical"
        _assert_score_in_range(result)

    def test_escalation_language_fcc(self):
        """Escalation keyword 'FCC' → critical."""
        feedback = _make_feedback("I am going to report this to the FCC")
        analysis = _make_analysis(sentiment_score=-0.4)
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "critical"
        _assert_score_in_range(result)

    def test_escalation_language_regulatory(self):
        """Escalation keyword 'regulatory' → critical."""
        feedback = _make_feedback("This violates regulatory requirements")
        analysis = _make_analysis(sentiment_score=0.1)
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "critical"
        _assert_score_in_range(result)

    def test_outage_without_severe_sentiment_not_critical(self):
        """Outage keyword without sentiment < -0.7 → NOT critical."""
        feedback = _make_feedback("There was an outage earlier today")
        analysis = _make_analysis(sentiment_score=-0.5)
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level != "critical"


# ---------------------------------------------------------------------------
# Test: High priority (Req 7.3)
# ---------------------------------------------------------------------------


class TestHighPriority:
    """Req 7.3: high when sentiment < -0.5 OR cluster volume > 10."""

    def test_negative_sentiment_below_minus_05(self):
        """Sentiment < -0.5 → high (no outage/escalation)."""
        feedback = _make_feedback("Very disappointed with this service")
        analysis = _make_analysis(sentiment_score=-0.6)
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "high"
        _assert_score_in_range(result)

    def test_cluster_volume_above_10(self):
        """Cluster volume > 10 → high."""
        feedback = _make_feedback("Having some issues with the app")
        analysis = _make_analysis(sentiment_score=0.0, intent="complaint")
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis, cluster_volume=15)

        assert result.priority_level == "high"
        _assert_score_in_range(result)

    def test_sentiment_exactly_minus_05_not_high(self):
        """Sentiment exactly -0.5 → NOT high (< is exclusive)."""
        feedback = _make_feedback("Not great experience with the service")
        analysis = _make_analysis(sentiment_score=-0.5)
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level != "high"

    def test_cluster_volume_exactly_10_not_high(self):
        """Cluster volume exactly 10 → NOT high (> 10 required)."""
        feedback = _make_feedback("Some general feedback here")
        analysis = _make_analysis(sentiment_score=0.0, intent="praise")
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis, cluster_volume=10)

        assert result.priority_level != "high"


# ---------------------------------------------------------------------------
# Test: Medium priority (Req 7.4)
# ---------------------------------------------------------------------------


class TestMediumPriority:
    """Req 7.4: medium when sentiment in [-0.5, -0.2) OR intent trigger."""

    def test_sentiment_in_medium_range(self):
        """Sentiment -0.35 (in [-0.5, -0.2)) → medium."""
        feedback = _make_feedback("Not very happy with this service")
        analysis = _make_analysis(sentiment_score=-0.35, intent="complaint")
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "medium"
        _assert_score_in_range(result)

    def test_sentiment_exactly_minus_05_is_medium(self):
        """Sentiment exactly -0.5 (inclusive lower bound) → medium."""
        feedback = _make_feedback("Fairly unhappy with this experience")
        analysis = _make_analysis(sentiment_score=-0.5, intent="complaint")
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "medium"
        _assert_score_in_range(result)

    def test_sentiment_exactly_minus_02_not_medium(self):
        """Sentiment exactly -0.2 (upper bound exclusive) → NOT medium via sentiment."""
        feedback = _make_feedback("Okay experience nothing special")
        analysis = _make_analysis(sentiment_score=-0.2, intent="praise")
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        # -0.2 is NOT in [-0.5, -0.2) and intent is "praise" → low
        assert result.priority_level == "low"

    def test_intent_request_for_help(self):
        """Intent 'request_for_help' → medium."""
        feedback = _make_feedback("Can someone help me with my bill")
        analysis = _make_analysis(sentiment_score=0.0, intent="request_for_help")
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "medium"
        _assert_score_in_range(result)

    def test_intent_billing_dispute(self):
        """Intent 'billing_dispute' → medium."""
        feedback = _make_feedback("My bill is wrong and I need it fixed")
        analysis = _make_analysis(sentiment_score=0.1, intent="billing_dispute")
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "medium"
        _assert_score_in_range(result)


# ---------------------------------------------------------------------------
# Test: Low priority (Req 7.5)
# ---------------------------------------------------------------------------


class TestLowPriority:
    """Req 7.5: low when no higher criteria are met."""

    def test_neutral_sentiment_no_triggers(self):
        """Neutral sentiment, no outage/escalation/cluster → low."""
        feedback = _make_feedback("I used the app today and it worked fine")
        analysis = _make_analysis(sentiment_score=0.0, intent="praise")
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "low"
        _assert_score_in_range(result)

    def test_positive_sentiment(self):
        """Positive sentiment → low."""
        feedback = _make_feedback("Great service, really happy with everything")
        analysis = _make_analysis(sentiment_score=0.8, intent="praise")
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "low"
        _assert_score_in_range(result)

    def test_slightly_negative_below_medium_threshold(self):
        """Sentiment -0.15 (not in [-0.5, -0.2)) → low if no intent trigger."""
        feedback = _make_feedback("Could be better I suppose")
        analysis = _make_analysis(sentiment_score=-0.15, intent="feature_suggestion")
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "low"
        _assert_score_in_range(result)


# ---------------------------------------------------------------------------
# Test: Precedence order (Req 7.6)
# ---------------------------------------------------------------------------


class TestPrecedenceOrder:
    """Req 7.6: highest matching level wins when multiple criteria apply."""

    def test_critical_overrides_high(self):
        """Feedback matching both critical AND high → critical wins."""
        # Escalation language (critical) + sentiment < -0.5 (high)
        feedback = _make_feedback("I will contact my lawyer about this awful service")
        analysis = _make_analysis(sentiment_score=-0.8)
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "critical"

    def test_critical_overrides_medium(self):
        """Feedback matching both critical AND medium → critical wins."""
        # Escalation language (critical) + intent billing_dispute (medium)
        feedback = _make_feedback("I will get the FCC involved in this billing dispute")
        analysis = _make_analysis(sentiment_score=-0.3, intent="billing_dispute")
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "critical"

    def test_high_overrides_medium(self):
        """Feedback matching both high AND medium → high wins."""
        # Sentiment < -0.5 (high) + intent billing_dispute (medium)
        feedback = _make_feedback("Terrible billing experience, very frustrated")
        analysis = _make_analysis(sentiment_score=-0.6, intent="billing_dispute")
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "high"


# ---------------------------------------------------------------------------
# Test: Score range consistency (Req 7.8)
# ---------------------------------------------------------------------------


class TestScoreRangeConsistency:
    """Req 7.8: priority_score within level-specific ranges."""

    @pytest.mark.parametrize(
        "text,sentiment,intent,volume,expected_level",
        [
            # Critical cases
            ("Major outage happening now", -0.9, "outage_report", 0, "critical"),
            ("Contacting my attorney", 0.0, "complaint", 0, "critical"),
            # High cases
            ("Terrible service", -0.6, "complaint", 0, "high"),
            ("Some issue", 0.0, "complaint", 20, "high"),
            # Medium cases
            ("Not great", -0.35, "complaint", 0, "medium"),
            ("Help needed", 0.0, "request_for_help", 0, "medium"),
            # Low cases
            ("All good", 0.5, "praise", 0, "low"),
            ("Neutral feedback", 0.0, "praise", 0, "low"),
        ],
    )
    def test_score_within_range(
        self, text, sentiment, intent, volume, expected_level
    ):
        """Score falls within the defined range for the assigned level."""
        feedback = _make_feedback(text)
        analysis = _make_analysis(sentiment_score=sentiment, intent=intent)
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis, cluster_volume=volume)

        assert result.priority_level == expected_level
        _assert_score_in_range(result)

    def test_critical_score_at_least_075(self):
        """Critical score must be >= 0.75."""
        feedback = _make_feedback("I will sue you, contacting my lawyer now")
        analysis = _make_analysis(sentiment_score=-0.9)
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "critical"
        assert result.priority_score >= 0.75

    def test_high_score_between_050_and_074(self):
        """High score must be in [0.50, 0.74]."""
        feedback = _make_feedback("Very unhappy with the service quality")
        analysis = _make_analysis(sentiment_score=-0.65)
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "high"
        assert 0.50 <= result.priority_score <= 0.74

    def test_medium_score_between_025_and_049(self):
        """Medium score must be in [0.25, 0.49]."""
        feedback = _make_feedback("Could use some help with billing")
        analysis = _make_analysis(sentiment_score=0.0, intent="billing_dispute")
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "medium"
        assert 0.25 <= result.priority_score <= 0.49

    def test_low_score_between_000_and_024(self):
        """Low score must be in [0.0, 0.24]."""
        feedback = _make_feedback("Everything is fine with my service")
        analysis = _make_analysis(sentiment_score=0.5, intent="praise")
        scorer = PriorityScorer()

        result = scorer.score(feedback, analysis)

        assert result.priority_level == "low"
        assert 0.0 <= result.priority_score <= 0.24
