"""Priority_Scorer for the NLP feedback routing pipeline (task 5.8).

The :class:`PriorityScorer` evaluates multiple signals from a
:class:`~nlp_processing.models.feedback_routing.CanonicalFeedback` record and
its associated :class:`~nlp_processing.models.feedback_routing.FeedbackAnalysis`
to produce a :class:`~nlp_processing.models.feedback_routing.PriorityResult`
containing a priority_level and numeric priority_score.

Business rules (Requirements 7.1–7.8):

* Req 7.1: compute priority from weighted signals (sentiment, keywords,
  engagement, cluster volume, outage indicators, escalation language).
* Req 7.2: critical when outage keywords + sentiment < -0.7 OR escalation
  language detected.
* Req 7.3: high when sentiment < -0.5 OR cluster volume > 10.
* Req 7.4: medium when sentiment in [-0.5, -0.2) OR intent in
  {request_for_help, billing_dispute}.
* Req 7.5: low when no higher-level criteria are met.
* Req 7.6: evaluate in descending precedence (critical > high > medium > low),
  assign the highest matching level.
* Req 7.7: store computed priority_level on the feedback_analysis record.
* Req 7.8: priority_score within level range: critical 0.75–1.0,
  high 0.50–0.74, medium 0.25–0.49, low 0.0–0.24.

Design / testability
---------------------
The PriorityScorer is a pure function with no external dependencies. It is
fully deterministic given the same inputs, making it straightforward to test
with property-based tests.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..models.feedback_routing import (
    CanonicalFeedback,
    FeedbackAnalysis,
    PriorityResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Outage indicator keywords (Req 7.2) — matched case-insensitively.
OUTAGE_KEYWORDS: list[str] = [
    "outage",
    "service down",
    "system down",
    "not working for everyone",
    "widespread issue",
]

# Executive escalation keywords (Req 7.2) — matched case-insensitively.
ESCALATION_KEYWORDS: list[str] = [
    "ceo",
    "executive",
    "lawyer",
    "attorney",
    "fcc",
    "regulatory",
    "lawsuit",
]

# Intents that trigger medium priority (Req 7.4).
MEDIUM_INTENTS: set[str] = {"request_for_help", "billing_dispute"}

# Priority score ranges per level (Req 7.8).
SCORE_RANGES: dict[str, tuple[float, float]] = {
    "critical": (0.75, 1.0),
    "high": (0.50, 0.74),
    "medium": (0.25, 0.49),
    "low": (0.0, 0.24),
}

# Sentiment thresholds.
CRITICAL_SENTIMENT_THRESHOLD = -0.7
HIGH_SENTIMENT_THRESHOLD = -0.5
MEDIUM_SENTIMENT_LOWER = -0.5  # inclusive
MEDIUM_SENTIMENT_UPPER = -0.2  # exclusive


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _text_contains_keywords(text: str, keywords: list[str]) -> bool:
    """Check if text contains any of the given keywords (case-insensitive)."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def _compute_critical_score(
    feedback: CanonicalFeedback,
    analysis: FeedbackAnalysis,
) -> float:
    """Compute a normalized score within the critical range [0.75, 1.0].

    Higher sub-scores for:
    - More negative sentiment
    - Both outage + escalation criteria met simultaneously
    """
    base = 0.75
    bonus = 0.0

    text = feedback.cleaned_text

    has_outage = _text_contains_keywords(text, OUTAGE_KEYWORDS)
    has_escalation = _text_contains_keywords(text, ESCALATION_KEYWORDS)
    severe_sentiment = analysis.sentiment_score < CRITICAL_SENTIMENT_THRESHOLD

    # Both outage+sentiment AND escalation → max urgency
    if has_outage and severe_sentiment and has_escalation:
        bonus = 0.25
    elif has_escalation:
        # Escalation alone scores mid-high in the critical range
        bonus = 0.15
        # Additional bonus for very negative sentiment
        if analysis.sentiment_score < -0.8:
            bonus += 0.05
    elif has_outage and severe_sentiment:
        # Outage + severe sentiment
        bonus = 0.10
        # Scale by how negative the sentiment is
        sentiment_factor = min(1.0, abs(analysis.sentiment_score) - 0.7) / 0.3
        bonus += sentiment_factor * 0.10

    return min(1.0, base + bonus)


def _compute_high_score(
    feedback: CanonicalFeedback,
    analysis: FeedbackAnalysis,
    cluster_volume: int,
) -> float:
    """Compute a normalized score within the high range [0.50, 0.74].

    Higher sub-scores for:
    - More negative sentiment
    - Higher cluster volume
    """
    base = 0.50
    bonus = 0.0

    # Sentiment contribution (< -0.5 triggers high)
    if analysis.sentiment_score < HIGH_SENTIMENT_THRESHOLD:
        # Scale from 0 at -0.5 to 0.12 at -0.7
        sentiment_factor = min(
            1.0, (abs(analysis.sentiment_score) - 0.5) / 0.2
        )
        bonus += sentiment_factor * 0.12

    # Cluster volume contribution (> 10 triggers high)
    if cluster_volume > 10:
        # Scale from 0 at 10 to 0.12 at 50+
        volume_factor = min(1.0, (cluster_volume - 10) / 40.0)
        bonus += volume_factor * 0.12

    return min(0.74, base + bonus)


def _compute_medium_score(
    feedback: CanonicalFeedback,
    analysis: FeedbackAnalysis,
) -> float:
    """Compute a normalized score within the medium range [0.25, 0.49].

    Higher sub-scores for:
    - More negative sentiment (within medium range)
    - Intent that requires help
    """
    base = 0.25
    bonus = 0.0

    # Sentiment contribution: [-0.5, -0.2)
    if MEDIUM_SENTIMENT_LOWER <= analysis.sentiment_score < MEDIUM_SENTIMENT_UPPER:
        # Scale from 0 at -0.2 to 0.12 at -0.5
        sentiment_factor = (abs(analysis.sentiment_score) - 0.2) / 0.3
        bonus += sentiment_factor * 0.12

    # Intent contribution
    if analysis.intent in MEDIUM_INTENTS:
        bonus += 0.10

    return min(0.49, base + bonus)


def _compute_low_score(
    feedback: CanonicalFeedback,
    analysis: FeedbackAnalysis,
) -> float:
    """Compute a normalized score within the low range [0.0, 0.24].

    Low priority is the default when no higher criteria are met.
    Some signals can push toward the upper end of the low range.
    """
    base = 0.0
    bonus = 0.0

    # Slightly negative sentiment (but not enough for medium: >= -0.2)
    if analysis.sentiment_score < 0.0:
        # Scale from 0 at 0 to 0.12 at -0.2
        sentiment_factor = min(1.0, abs(analysis.sentiment_score) / 0.2)
        bonus += sentiment_factor * 0.12

    # Some positive signal for neutral items that have any action intent
    if analysis.requires_action:
        bonus += 0.06

    return min(0.24, base + bonus)


def _get_cluster_volume(analysis: FeedbackAnalysis) -> int:
    """Extract the cluster volume from the analysis.

    If cluster_id is None or not available, returns 0 (no cluster assigned).
    The actual cluster volume should be passed through analysis metadata
    or looked up. For the scorer's purposes, we use the volume stored
    in the analysis metadata if available, otherwise default to 0.
    """
    # The cluster volume may be stored in the analysis or provided externally.
    # For this pure-function implementation, the scorer accepts a
    # cluster_volume parameter or defaults to 0 when cluster_id is None.
    return 0


# ---------------------------------------------------------------------------
# PriorityScorer class
# ---------------------------------------------------------------------------


class PriorityScorer:
    """Computes priority level and score for feedback records.

    The scorer evaluates criteria in descending precedence order
    (critical → high → medium → low) and assigns the highest matching level.

    This is a pure function with no external dependencies — deterministic
    given the same inputs.
    """

    def score(
        self,
        feedback: CanonicalFeedback,
        analysis: FeedbackAnalysis,
        cluster_volume: Optional[int] = None,
    ) -> PriorityResult:
        """Compute priority level and score for a feedback record.

        Parameters
        ----------
        feedback : CanonicalFeedback
            The preprocessed feedback record.
        analysis : FeedbackAnalysis
            The NLP analysis result containing sentiment, intent, cluster info.
        cluster_volume : int, optional
            The volume_count of the assigned cluster. If None, defaults to 0
            (no cluster or cluster volume not available).

        Returns
        -------
        PriorityResult
            Contains priority_level ("low", "medium", "high", "critical")
            and priority_score (0.0–1.0) within the appropriate range.
        """
        vol = cluster_volume if cluster_volume is not None else 0

        # Evaluate in descending precedence order (Req 7.6).
        if self._is_critical(feedback, analysis):
            priority_level = "critical"
            priority_score = _compute_critical_score(feedback, analysis)
        elif self._is_high(feedback, analysis, vol):
            priority_level = "high"
            priority_score = _compute_high_score(feedback, analysis, vol)
        elif self._is_medium(feedback, analysis):
            priority_level = "medium"
            priority_score = _compute_medium_score(feedback, analysis)
        else:
            priority_level = "low"
            priority_score = _compute_low_score(feedback, analysis)

        return PriorityResult(
            priority_level=priority_level,
            priority_score=priority_score,
        )

    def _is_critical(
        self,
        feedback: CanonicalFeedback,
        analysis: FeedbackAnalysis,
    ) -> bool:
        """Check if feedback meets critical priority criteria (Req 7.2).

        Critical when:
        - Outage keywords present AND sentiment < -0.7
        - OR escalation language detected
        """
        text = feedback.cleaned_text

        # Condition 1: outage keywords + sentiment < -0.7
        has_outage = _text_contains_keywords(text, OUTAGE_KEYWORDS)
        severe_sentiment = analysis.sentiment_score < CRITICAL_SENTIMENT_THRESHOLD

        if has_outage and severe_sentiment:
            return True

        # Condition 2: escalation language
        has_escalation = _text_contains_keywords(text, ESCALATION_KEYWORDS)
        if has_escalation:
            return True

        return False

    def _is_high(
        self,
        feedback: CanonicalFeedback,
        analysis: FeedbackAnalysis,
        cluster_volume: int,
    ) -> bool:
        """Check if feedback meets high priority criteria (Req 7.3).

        High when:
        - Sentiment < -0.5
        - OR cluster volume > 10
        """
        if analysis.sentiment_score < HIGH_SENTIMENT_THRESHOLD:
            return True
        if cluster_volume > 10:
            return True
        return False

    def _is_medium(
        self,
        feedback: CanonicalFeedback,
        analysis: FeedbackAnalysis,
    ) -> bool:
        """Check if feedback meets medium priority criteria (Req 7.4).

        Medium when:
        - Sentiment in [-0.5, -0.2)
        - OR intent in {request_for_help, billing_dispute}
        """
        # Sentiment in [-0.5, -0.2)
        if MEDIUM_SENTIMENT_LOWER <= analysis.sentiment_score < MEDIUM_SENTIMENT_UPPER:
            return True
        # Intent trigger
        if analysis.intent in MEDIUM_INTENTS:
            return True
        return False


__all__ = [
    "PriorityScorer",
    "OUTAGE_KEYWORDS",
    "ESCALATION_KEYWORDS",
    "MEDIUM_INTENTS",
    "SCORE_RANGES",
]
