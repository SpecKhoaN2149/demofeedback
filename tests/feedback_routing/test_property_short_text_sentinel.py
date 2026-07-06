"""Property 6: Short Text Sentinel Behavior.

# Feature: nlp-feedback-routing, Property 6

**Validates: Requirements 4.4**

For any Canonical_Feedback record whose cleaned_text contains fewer than 5
characters, the Sentiment_Analyzer SHALL assign sentiment_label "neutral" and
sentiment_score 0.0 without invoking the language model.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from nlp_processing.enrichment.sentiment_routing import SentimentAnalyzer
from nlp_processing.models.feedback_routing import CanonicalFeedback
from nlp_processing.transport.client import GeminiRequest, GeminiResult

from .strategies import (
    _uuid_text,
    feedback_routing_settings,
    processing_statuses,
    timestamp_iso,
)

# ---------------------------------------------------------------------------
# Strategies: generate CanonicalFeedback with short cleaned_text (1-4 chars)
# ---------------------------------------------------------------------------

# Printable ASCII characters for generating short text
_PRINTABLE = st.characters(min_codepoint=32, max_codepoint=126)


@st.composite
def short_text_canonical_feedback(draw: st.DrawFn) -> CanonicalFeedback:
    """Generate a CanonicalFeedback record with cleaned_text of 1-4 characters.

    The model has min_length=1 on cleaned_text, so we generate 1-4 chars
    which are all below the SHORT_TEXT_THRESHOLD of 5.
    """
    short_text = draw(st.text(alphabet=_PRINTABLE, min_size=1, max_size=4))
    source_type = draw(st.sampled_from(["social", "widget"]))
    language_code = draw(
        st.sampled_from(["en", "es", "fr", "de", "pt", "ja", "zh", "und"])
    )

    return CanonicalFeedback(
        feedback_id=draw(_uuid_text),
        source_type=source_type,
        original_source_id=draw(_uuid_text),
        cleaned_text=short_text,
        detected_language=language_code,
        ingested_at=draw(timestamp_iso()),
        duplicate_count=draw(st.integers(min_value=0, max_value=100)),
        profanity_detected=draw(st.booleans()),
        metadata=draw(
            st.fixed_dictionaries({}, optional={
                "platform": st.sampled_from(["reddit", "x", "facebook"]),
            })
        ),
        processing_status=draw(processing_statuses()),
    )


# ---------------------------------------------------------------------------
# Fake generate function that tracks invocations
# ---------------------------------------------------------------------------


def _make_tracking_generate():
    """Create a fake generate function that tracks whether it was called.

    If this function is invoked, it means the model was called — which
    violates the short-text sentinel requirement (Req 4.4).
    """
    call_log: list[GeminiRequest] = []

    def _generate(request: GeminiRequest) -> GeminiResult:
        call_log.append(request)
        # Return something valid in case it's called — the assertion will catch this
        return GeminiResult(
            record_id=request.record_id,
            attempts=1,
            text='{"sentiment_label": "positive", "sentiment_score": 0.9}',
        )

    _generate.call_log = call_log  # type: ignore[attr-defined]
    return _generate


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(feedback=short_text_canonical_feedback())
def test_short_text_returns_neutral_label(feedback: CanonicalFeedback) -> None:
    """Short text (1-4 chars) always returns sentiment_label "neutral".

    # Feature: nlp-feedback-routing, Property 6
    **Validates: Requirements 4.4**
    """
    generate_fn = _make_tracking_generate()
    analyzer = SentimentAnalyzer(generate_fn)
    result = analyzer.analyze(feedback)

    assert result.sentiment_label == "neutral", (
        f"Expected 'neutral' for short text {feedback.cleaned_text!r} "
        f"(len={len(feedback.cleaned_text)}), got {result.sentiment_label!r}"
    )


@settings(max_examples=100)
@given(feedback=short_text_canonical_feedback())
def test_short_text_returns_zero_score(feedback: CanonicalFeedback) -> None:
    """Short text (1-4 chars) always returns sentiment_score 0.0.

    # Feature: nlp-feedback-routing, Property 6
    **Validates: Requirements 4.4**
    """
    generate_fn = _make_tracking_generate()
    analyzer = SentimentAnalyzer(generate_fn)
    result = analyzer.analyze(feedback)

    assert result.sentiment_score == 0.0, (
        f"Expected 0.0 for short text {feedback.cleaned_text!r} "
        f"(len={len(feedback.cleaned_text)}), got {result.sentiment_score}"
    )


@settings(max_examples=100)
@given(feedback=short_text_canonical_feedback())
def test_short_text_does_not_invoke_model(feedback: CanonicalFeedback) -> None:
    """Short text (1-4 chars) must NOT invoke the language model (generate function).

    # Feature: nlp-feedback-routing, Property 6
    **Validates: Requirements 4.4**
    """
    generate_fn = _make_tracking_generate()
    analyzer = SentimentAnalyzer(generate_fn)
    analyzer.analyze(feedback)

    assert len(generate_fn.call_log) == 0, (
        f"Model was invoked {len(generate_fn.call_log)} time(s) for short text "
        f"{feedback.cleaned_text!r} (len={len(feedback.cleaned_text)}). "
        f"Sentinel should have prevented model invocation."
    )
