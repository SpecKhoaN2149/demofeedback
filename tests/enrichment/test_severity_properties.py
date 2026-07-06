"""Property and unit tests for the SeverityScorer (tasks 11.2-11.5, Req 7).

Covers:

* Property 18 -- severity is well-formed (Req 7.1, 7.2)
* Property 19 -- missing severity defaults to 1 with a note (Req 7.3)
* Property 20 -- invalid severity is rejected (Req 7.4)
* unit  -- severity timeout default (Req 7.5)

The scorer accepts an injectable ``GeminiRequest -> GeminiResult`` callable, so
each test wires a fake ``generate`` returning scripted JSON ``text`` (success)
or a typed :class:`GeminiFailure` (transport failure). Response JSON is generated
with local Hypothesis strategies producing the severity response shape
``{"severity_score": ..., "severity_factors": [...]}`` including malformed/edge
variants each property needs.
"""

from __future__ import annotations

import json

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from nlp_processing.enrichment.severity import (
    DEFAULT_SEVERITY,
    MAX_FACTOR_LEN,
    MAX_SEVERITY,
    MIN_SEVERITY,
    SeverityScorer,
)
from nlp_processing.models.records import FeedbackRecord
from nlp_processing.transport.client import (
    GeminiErrorKind,
    GeminiFailure,
    GeminiRequest,
    GeminiResult,
)


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


def make_record(record_id: str = "rec-1", text: str = "total outage all day") -> FeedbackRecord:
    return FeedbackRecord(
        id=record_id,
        source_channel="call_transcript",
        cleaned_text=text,
        metadata={"region": "north"},
    )


# ---------------------------------------------------------------------------
# Local strategies for severity response shapes
# ---------------------------------------------------------------------------
def valid_scores() -> st.SearchStrategy[int]:
    return st.integers(min_value=MIN_SEVERITY, max_value=MAX_SEVERITY)


def valid_factor_text() -> st.SearchStrategy[str]:
    return st.text(min_size=1, max_size=MAX_FACTOR_LEN)


def factor_lists() -> st.SearchStrategy[list]:
    """Lists of factor entries; may be empty (scorer synthesizes a default)."""
    return st.lists(valid_factor_text(), min_size=0, max_size=5)


def out_of_range_int_scores() -> st.SearchStrategy[int]:
    return st.integers().filter(lambda n: not (MIN_SEVERITY <= n <= MAX_SEVERITY))


def non_integer_scores() -> st.SearchStrategy[object]:
    """Present-but-non-integer severity values (floats, strings, bools)."""
    return st.one_of(
        st.floats(allow_nan=False, allow_infinity=False).filter(
            lambda f: not float(f).is_integer()
        ),
        st.text(min_size=1, max_size=10),
        st.booleans(),
    )


# ---------------------------------------------------------------------------
# Property 18: severity is well-formed (Req 7.1, 7.2)
# ---------------------------------------------------------------------------
# Feature: nlp-feedback-processing, Property 18: Severity is well-formed
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(score=valid_scores(), factors=factor_lists())
def test_property_18_severity_well_formed(score, factors):
    """On success: integer 1..5 + >=1 factor of 1..500 chars.

    **Validates: Requirements 7.1, 7.2**
    """
    payload = {"severity_score": score, "severity_factors": factors}
    scorer = SeverityScorer(make_success_generate(payload))
    outcome = scorer.score(make_record())

    assert outcome.ok
    assert outcome.error is None
    # Req 7.1: integer in 1..5.
    assert isinstance(outcome.severity_score, int)
    assert MIN_SEVERITY <= outcome.severity_score <= MAX_SEVERITY
    assert outcome.severity_score == score
    # Req 7.2: at least one contributing factor, each 1..500 chars.
    assert outcome.factors is not None
    assert len(outcome.factors) >= 1
    for factor in outcome.factors:
        assert 1 <= len(factor.description) <= MAX_FACTOR_LEN
    assert outcome.record == make_record()


# ---------------------------------------------------------------------------
# Property 19: missing severity defaults to 1 with a note (Req 7.3)
# ---------------------------------------------------------------------------
# Feature: nlp-feedback-processing, Property 19: Missing severity defaults to 1 with a note
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(factors=factor_lists(), include_null=st.booleans())
def test_property_19_missing_severity_defaults_to_one(factors, include_null):
    """Omitted (or null) severity -> default 1 + missing-severity note keyed by id.

    **Validates: Requirements 7.3**
    """
    payload: dict = {"severity_factors": factors}
    if include_null:
        # Explicit null is treated the same as omission (Req 7.3).
        payload["severity_score"] = None
    record = make_record("rec-missing")
    scorer = SeverityScorer(make_success_generate(payload))
    outcome = scorer.score(record)

    assert outcome.ok
    assert outcome.error is None
    assert outcome.severity_score == DEFAULT_SEVERITY == 1
    assert outcome.factors is not None and len(outcome.factors) >= 1
    # A missing-severity note keyed by the record id is recorded.
    assert len(outcome.notes) == 1
    assert "missing-severity" in outcome.notes[0]
    assert record.id in outcome.notes[0]


# ---------------------------------------------------------------------------
# Property 20: invalid severity is rejected (Req 7.4)
# ---------------------------------------------------------------------------
# Feature: nlp-feedback-processing, Property 20: Invalid severity is rejected
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(data=st.data())
def test_property_20_invalid_severity_rejected(data):
    """Non-integer OR out-of-range -> reject, no insight, severity-range error
    keyed by id.

    **Validates: Requirements 7.4**
    """
    variant = data.draw(st.sampled_from(["out_of_range", "non_integer"]))
    if variant == "out_of_range":
        score = data.draw(out_of_range_int_scores())
    else:
        score = data.draw(non_integer_scores())

    payload = {
        "severity_score": score,
        "severity_factors": data.draw(factor_lists()),
    }
    record = make_record("rec-invalid")
    scorer = SeverityScorer(make_success_generate(payload))
    outcome = scorer.score(record)

    # Req 7.4: rejected with no insight data.
    assert not outcome.ok
    assert outcome.severity_score is None
    assert outcome.factors is None
    assert outcome.error is not None
    assert outcome.error.kind == "severity_range_error"
    assert outcome.error.record_id == "rec-invalid"
    assert outcome.record == record


# ---------------------------------------------------------------------------
# Unit test 11.5: severity timeout default (Req 7.5)
# ---------------------------------------------------------------------------
class TestSeverityTimeoutDefault:
    """Req 7.5: timeout -> default 1 + severity-unavailable note."""

    def test_timeout_defaults_to_one_with_note(self):
        record = make_record("rec-timeout")
        scorer = SeverityScorer(
            make_failure_generate(GeminiErrorKind.TIMEOUT, "request timed out after 30s")
        )
        outcome = scorer.score(record)

        assert outcome.ok
        assert outcome.error is None
        assert outcome.severity_score == DEFAULT_SEVERITY == 1
        assert outcome.factors is not None and len(outcome.factors) >= 1
        assert len(outcome.notes) == 1
        assert "severity-unavailable" in outcome.notes[0]
        assert record.id in outcome.notes[0]
        assert outcome.record == record

    def test_exhausted_also_defaults_to_one_with_note(self):
        record = make_record("rec-exhausted")
        scorer = SeverityScorer(
            make_failure_generate(GeminiErrorKind.EXHAUSTED, "exhausted 5 attempts")
        )
        outcome = scorer.score(record)

        assert outcome.ok
        assert outcome.severity_score == DEFAULT_SEVERITY
        assert len(outcome.notes) == 1
        assert "severity-unavailable" in outcome.notes[0]
