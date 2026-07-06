"""Property and unit tests for the SentimentAnalyzer (tasks 10.2-10.4, Req 6).

Covers:

* Property 15 -- sentiment is well-formed and always recorded (Req 6.1, 6.2, 6.3)
* Property 16 -- missing sentiment defaults to neutral with a note (Req 6.4)
* Property 17 -- invalid sentiment is rejected (Req 6.5)

The analyzer accepts an injectable ``GeminiRequest -> GeminiResult`` callable, so
each test wires a fake ``generate`` returning scripted JSON ``text``. Response
JSON is generated with local Hypothesis strategies producing the sentiment
response shape ``{"sentiment": str?, "sentiment_confidence": number?}`` including
the malformed/edge variants each property needs.
"""

from __future__ import annotations

import json

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from nlp_processing.enrichment.sentiment import (
    ALLOWED_SENTIMENTS,
    DEFAULT_SENTIMENT,
    SentimentAnalyzer,
)
from nlp_processing.models.records import FeedbackRecord
from nlp_processing.transport.client import (
    GeminiErrorKind,
    GeminiFailure,
    GeminiRequest,
    GeminiResult,
)

VALID_SENTIMENTS: tuple[str, ...] = tuple(sorted(ALLOWED_SENTIMENTS))


# ---------------------------------------------------------------------------
# Fakes and helpers
# ---------------------------------------------------------------------------
def make_success_generate(payload: dict):
    """A fake ``generate`` returning a successful result with ``payload`` JSON."""

    def _generate(request: GeminiRequest) -> GeminiResult:
        return GeminiResult(
            record_id=request.record_id, attempts=1, text=json.dumps(payload)
        )

    return _generate


def make_failure_generate(kind: GeminiErrorKind, message: str = "boom"):
    def _generate(request: GeminiRequest) -> GeminiResult:
        return GeminiResult(
            record_id=request.record_id,
            attempts=1,
            failure=GeminiFailure(
                record_id=request.record_id, kind=kind, message=message, attempts=1
            ),
        )

    return _generate


def make_record(record_id: str = "rec-1", text: str = "service was great") -> FeedbackRecord:
    return FeedbackRecord(
        id=record_id,
        source_channel="survey",
        cleaned_text=text,
        metadata={"k": "v"},
    )


# ---------------------------------------------------------------------------
# Local strategies for sentiment response shapes
# ---------------------------------------------------------------------------
def in_range_confidence() -> st.SearchStrategy[float]:
    return st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


def out_of_range_confidence() -> st.SearchStrategy[float]:
    below = st.floats(
        min_value=-1e6, max_value=0.0, exclude_max=True, allow_nan=False
    )
    above = st.floats(
        min_value=1.0, max_value=1e6, exclude_min=True, allow_nan=False
    )
    return st.one_of(below, above)


def invalid_sentiment_values() -> st.SearchStrategy[str]:
    return st.text(min_size=1, max_size=20).filter(lambda s: s not in ALLOWED_SENTIMENTS)


# ---------------------------------------------------------------------------
# Property 15: sentiment is well-formed and always recorded (Req 6.1, 6.2, 6.3)
# ---------------------------------------------------------------------------
# Feature: nlp-feedback-processing, Property 15: Sentiment is well-formed and always recorded
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(
    sentiment=st.sampled_from(VALID_SENTIMENTS),
    confidence=in_range_confidence(),
)
def test_property_15_sentiment_well_formed(sentiment, confidence):
    """Valid value + in-range confidence: one of the allowed values, recorded
    regardless of magnitude.

    **Validates: Requirements 6.1, 6.2, 6.3**
    """
    payload = {"sentiment": sentiment, "sentiment_confidence": confidence}
    analyzer = SentimentAnalyzer(make_success_generate(payload))
    outcome = analyzer.analyze(make_record())

    assert outcome.ok
    assert outcome.error is None
    # Req 6.1: exactly one of positive/neutral/negative.
    assert outcome.sentiment in ALLOWED_SENTIMENTS
    assert outcome.sentiment == sentiment
    # Req 6.2, 6.3: confidence in 0..1 recorded regardless of magnitude.
    assert outcome.confidence is not None
    assert 0.0 <= outcome.confidence <= 1.0
    assert outcome.confidence == confidence
    # No rejection note for a clean valid response.
    assert outcome.notes == ()
    assert outcome.record == make_record()


# ---------------------------------------------------------------------------
# Property 16: missing sentiment defaults to neutral with a note (Req 6.4)
# ---------------------------------------------------------------------------
# Feature: nlp-feedback-processing, Property 16: Missing sentiment defaults to neutral with a note
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(
    # Either omit the confidence entirely, or supply an in-range one. An
    # out-of-range confidence is a separate rejection path (Property 17).
    confidence=st.one_of(st.none(), in_range_confidence()),
)
def test_property_16_missing_sentiment_defaults_neutral(confidence):
    """Omitted sentiment -> neutral default + missing-sentiment note keyed by id.

    **Validates: Requirements 6.4**
    """
    payload: dict = {}
    if confidence is not None:
        payload["sentiment_confidence"] = confidence
    record = make_record("rec-missing")
    analyzer = SentimentAnalyzer(make_success_generate(payload))
    outcome = analyzer.analyze(record)

    assert outcome.ok
    assert outcome.error is None
    assert outcome.sentiment == DEFAULT_SENTIMENT == "neutral"
    assert outcome.confidence is not None
    # A missing-sentiment note keyed by the record id is recorded.
    assert len(outcome.notes) == 1
    assert "missing-sentiment" in outcome.notes[0]
    assert record.id in outcome.notes[0]


# ---------------------------------------------------------------------------
# Property 17: invalid sentiment is rejected (Req 6.5)
# ---------------------------------------------------------------------------
# Feature: nlp-feedback-processing, Property 17: Invalid sentiment is rejected
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(data=st.data())
def test_property_17_invalid_sentiment_rejected(data):
    """Out-of-set value OR out-of-range confidence -> reject, no insight,
    sentiment-validation error keyed by id.

    **Validates: Requirements 6.5**
    """
    # Pick one of the two invalid shapes.
    variant = data.draw(st.sampled_from(["bad_value", "bad_confidence"]))
    if variant == "bad_value":
        payload = {
            "sentiment": data.draw(invalid_sentiment_values()),
            "sentiment_confidence": data.draw(in_range_confidence()),
        }
    else:
        payload = {
            "sentiment": data.draw(st.sampled_from(VALID_SENTIMENTS)),
            "sentiment_confidence": data.draw(out_of_range_confidence()),
        }

    record = make_record("rec-invalid")
    analyzer = SentimentAnalyzer(make_success_generate(payload))
    outcome = analyzer.analyze(record)

    # Req 6.5: rejected with no insight fields.
    assert not outcome.ok
    assert outcome.sentiment is None
    assert outcome.confidence is None
    assert outcome.error is not None
    assert outcome.error.kind == "sentiment_validation"
    assert outcome.error.record_id == "rec-invalid"
    # Record preserved unchanged.
    assert outcome.record == record


class TestSentimentTransportFailure:
    """A transport failure rejects the record (no insight)."""

    def test_timeout_rejects_with_failure_error(self):
        record = make_record("rec-timeout")
        analyzer = SentimentAnalyzer(make_failure_generate(GeminiErrorKind.TIMEOUT))
        outcome = analyzer.analyze(record)

        assert not outcome.ok
        assert outcome.sentiment is None
        assert outcome.confidence is None
        assert outcome.error is not None
        assert outcome.error.kind == "sentiment_failure"
        assert outcome.record == record
