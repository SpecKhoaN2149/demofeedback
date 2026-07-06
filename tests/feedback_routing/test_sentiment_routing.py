"""Unit tests for the feedback routing SentimentAnalyzer (task 5.1, Req 4.1-4.6).

Tests cover:
* Short-text sentinel: < 5 chars → neutral/0.0 without model call (Req 4.4)
* Label/score consistency enforcement (Req 4.5)
* Error fallback: neutral/0.0 on model error or timeout (Req 4.6)
* Normal inference path (Req 4.1, 4.2)
"""

from __future__ import annotations

import json

import pytest

from nlp_processing.enrichment.sentiment_routing import (
    FALLBACK_RESULT,
    NEGATIVE_THRESHOLD,
    POSITIVE_THRESHOLD,
    SHORT_TEXT_THRESHOLD,
    SentimentAnalyzer,
    _enforce_label_consistency,
)
from nlp_processing.models.feedback_routing import CanonicalFeedback, SentimentResult
from nlp_processing.transport.client import (
    GeminiErrorKind,
    GeminiFailure,
    GeminiRequest,
    GeminiResult,
)


# ---------------------------------------------------------------------------
# Helpers / Fakes
# ---------------------------------------------------------------------------


def _make_feedback(text: str = "The service was terrible and slow") -> CanonicalFeedback:
    """Create a CanonicalFeedback record for testing."""
    return CanonicalFeedback(
        feedback_id="test-001",
        source_type="widget",
        original_source_id="widget-sub-001",
        cleaned_text=text,
        detected_language="en",
        ingested_at="2024-01-15T10:00:00Z",
    )


def _make_success_generate(payload: dict):
    """A fake generate that returns a successful result with JSON payload."""
    call_count = {"n": 0}

    def _generate(request: GeminiRequest) -> GeminiResult:
        call_count["n"] += 1
        return GeminiResult(
            record_id=request.record_id, attempts=1, text=json.dumps(payload)
        )

    _generate.call_count = call_count  # type: ignore[attr-defined]
    return _generate


def _make_failure_generate(kind: GeminiErrorKind, message: str = "boom"):
    """A fake generate that returns a transport failure."""

    def _generate(request: GeminiRequest) -> GeminiResult:
        return GeminiResult(
            record_id=request.record_id,
            attempts=1,
            failure=GeminiFailure(
                record_id=request.record_id, kind=kind, message=message, attempts=1
            ),
        )

    return _generate


def _make_exception_generate(exc: Exception):
    """A fake generate that raises an exception."""

    def _generate(request: GeminiRequest) -> GeminiResult:
        raise exc

    return _generate


# ---------------------------------------------------------------------------
# Test: Short-text sentinel (Req 4.4)
# ---------------------------------------------------------------------------


class TestShortTextSentinel:
    """Req 4.4: cleaned_text < 5 chars → neutral/0.0 without model call."""

    def test_empty_string(self):
        """Empty text → neutral/0.0, no model invocation."""
        gen = _make_success_generate({"sentiment_label": "positive", "sentiment_score": 0.9})
        # Need min_length=1 for CanonicalFeedback, use text that's 1 char
        feedback = _make_feedback("X")
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(feedback)

        assert result.sentiment_label == "neutral"
        assert result.sentiment_score == 0.0
        assert gen.call_count["n"] == 0  # Model was NOT called

    def test_four_chars(self):
        """4-char text → neutral/0.0, no model invocation."""
        gen = _make_success_generate({"sentiment_label": "negative", "sentiment_score": -0.8})
        feedback = _make_feedback("abcd")
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(feedback)

        assert result.sentiment_label == "neutral"
        assert result.sentiment_score == 0.0
        assert gen.call_count["n"] == 0

    def test_exactly_five_chars_calls_model(self):
        """5-char text → model IS called (threshold is < 5, not <=)."""
        gen = _make_success_generate({"sentiment_label": "neutral", "sentiment_score": 0.0})
        feedback = _make_feedback("abcde")
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(feedback)

        assert gen.call_count["n"] == 1  # Model WAS called


# ---------------------------------------------------------------------------
# Test: Label/score consistency enforcement (Req 4.5)
# ---------------------------------------------------------------------------


class TestLabelScoreConsistency:
    """Req 4.5: label derived from score, overriding model-returned label."""

    def test_positive_score_overrides_negative_label(self):
        """Score > 0.2 → label "positive" even if model says "negative"."""
        gen = _make_success_generate({"sentiment_label": "negative", "sentiment_score": 0.5})
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(_make_feedback())

        assert result.sentiment_label == "positive"
        assert result.sentiment_score == 0.5

    def test_negative_score_overrides_positive_label(self):
        """Score < -0.2 → label "negative" even if model says "positive"."""
        gen = _make_success_generate({"sentiment_label": "positive", "sentiment_score": -0.6})
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(_make_feedback())

        assert result.sentiment_label == "negative"
        assert result.sentiment_score == -0.6

    def test_neutral_range_overrides_label(self):
        """Score in [-0.2, 0.2] → label "neutral" even if model says otherwise."""
        gen = _make_success_generate({"sentiment_label": "positive", "sentiment_score": 0.1})
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(_make_feedback())

        assert result.sentiment_label == "neutral"
        assert result.sentiment_score == 0.1

    def test_boundary_positive(self):
        """Score exactly 0.2 → neutral (> 0.2 required for positive)."""
        gen = _make_success_generate({"sentiment_label": "positive", "sentiment_score": 0.2})
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(_make_feedback())

        assert result.sentiment_label == "neutral"

    def test_boundary_negative(self):
        """Score exactly -0.2 → neutral (< -0.2 required for negative)."""
        gen = _make_success_generate({"sentiment_label": "negative", "sentiment_score": -0.2})
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(_make_feedback())

        assert result.sentiment_label == "neutral"

    def test_score_clamped_above_1(self):
        """Score > 1.0 is clamped to 1.0."""
        gen = _make_success_generate({"sentiment_label": "positive", "sentiment_score": 1.5})
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(_make_feedback())

        assert result.sentiment_score == 1.0
        assert result.sentiment_label == "positive"

    def test_score_clamped_below_negative_1(self):
        """Score < -1.0 is clamped to -1.0."""
        gen = _make_success_generate({"sentiment_label": "negative", "sentiment_score": -2.0})
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(_make_feedback())

        assert result.sentiment_score == -1.0
        assert result.sentiment_label == "negative"


# ---------------------------------------------------------------------------
# Test: Error fallback (Req 4.6)
# ---------------------------------------------------------------------------


class TestErrorFallback:
    """Req 4.6: neutral/0.0 on model error or timeout."""

    def test_timeout_returns_fallback(self):
        gen = _make_failure_generate(GeminiErrorKind.TIMEOUT, "timed out after 30s")
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(_make_feedback())

        assert result.sentiment_label == "neutral"
        assert result.sentiment_score == 0.0

    def test_auth_error_returns_fallback(self):
        gen = _make_failure_generate(GeminiErrorKind.AUTH, "401 unauthorized")
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(_make_feedback())

        assert result.sentiment_label == "neutral"
        assert result.sentiment_score == 0.0

    def test_exhausted_retries_returns_fallback(self):
        gen = _make_failure_generate(GeminiErrorKind.EXHAUSTED, "exhausted 5 attempts")
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(_make_feedback())

        assert result.sentiment_label == "neutral"
        assert result.sentiment_score == 0.0

    def test_non_retryable_error_returns_fallback(self):
        gen = _make_failure_generate(GeminiErrorKind.ERROR, "bad request")
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(_make_feedback())

        assert result.sentiment_label == "neutral"
        assert result.sentiment_score == 0.0

    def test_exception_in_generate_returns_fallback(self):
        """Any unexpected exception from generate → fallback."""
        gen = _make_exception_generate(RuntimeError("unexpected crash"))
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(_make_feedback())

        assert result.sentiment_label == "neutral"
        assert result.sentiment_score == 0.0

    def test_invalid_json_returns_fallback(self):
        """Malformed JSON response → fallback."""

        def _generate(request: GeminiRequest) -> GeminiResult:
            return GeminiResult(
                record_id=request.record_id, attempts=1, text="not valid json {"
            )

        analyzer = SentimentAnalyzer(_generate)
        result = analyzer.analyze(_make_feedback())

        assert result.sentiment_label == "neutral"
        assert result.sentiment_score == 0.0

    def test_missing_score_in_response_returns_fallback(self):
        """Response JSON with no sentiment_score → fallback."""
        gen = _make_success_generate({"sentiment_label": "positive"})
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(_make_feedback())

        assert result.sentiment_label == "neutral"
        assert result.sentiment_score == 0.0


# ---------------------------------------------------------------------------
# Test: Normal inference (Req 4.1, 4.2)
# ---------------------------------------------------------------------------


class TestNormalInference:
    """Normal path: model returns valid label and score."""

    def test_positive_sentiment(self):
        gen = _make_success_generate({"sentiment_label": "positive", "sentiment_score": 0.85})
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(_make_feedback("I love this service so much"))

        assert result.sentiment_label == "positive"
        assert result.sentiment_score == 0.85

    def test_negative_sentiment(self):
        gen = _make_success_generate({"sentiment_label": "negative", "sentiment_score": -0.7})
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(_make_feedback("This is absolutely terrible"))

        assert result.sentiment_label == "negative"
        assert result.sentiment_score == -0.7

    def test_neutral_sentiment(self):
        gen = _make_success_generate({"sentiment_label": "neutral", "sentiment_score": 0.05})
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(_make_feedback("I used the service yesterday"))

        assert result.sentiment_label == "neutral"
        assert result.sentiment_score == 0.05

    def test_result_is_sentiment_result_type(self):
        gen = _make_success_generate({"sentiment_label": "neutral", "sentiment_score": 0.0})
        analyzer = SentimentAnalyzer(gen)
        result = analyzer.analyze(_make_feedback("Some feedback text here"))

        assert isinstance(result, SentimentResult)


# ---------------------------------------------------------------------------
# Test: _enforce_label_consistency helper
# ---------------------------------------------------------------------------


class TestEnforceLabelConsistency:
    """Direct tests for the consistency enforcement function."""

    @pytest.mark.parametrize(
        "score,expected_label",
        [
            (0.21, "positive"),
            (0.5, "positive"),
            (1.0, "positive"),
            (-0.21, "negative"),
            (-0.5, "negative"),
            (-1.0, "negative"),
            (0.0, "neutral"),
            (0.2, "neutral"),
            (-0.2, "neutral"),
            (0.1, "neutral"),
            (-0.1, "neutral"),
        ],
    )
    def test_consistency_rules(self, score, expected_label):
        assert _enforce_label_consistency(score) == expected_label
