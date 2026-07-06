"""Property and unit tests for the Classifier (tasks 9.2-9.5, Req 5).

Covers:

* Property 12 -- classifier output is well-formed (Req 5.1, 5.2, 5.3)
* Property 13 -- theme threshold selection and default (Req 5.4, 5.5)
* Property 14 -- unknown themes are discarded (Req 5.6)
* unit  -- classification unavailability preserves the record (Req 5.7)

The Classifier accepts an injectable ``GeminiRequest -> GeminiResult`` callable,
so each test wires a fake ``generate`` that returns a :class:`GeminiResult`
carrying scripted JSON ``text`` (success) or a :class:`GeminiFailure` (transport
failure). Response JSON is generated with local Hypothesis strategies producing
the classification response shape ``{"themes": [{"theme", "confidence"}, ...]}``.
"""

from __future__ import annotations

import json

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from nlp_processing.enrichment.classifier import (
    OTHER_THEME,
    THEME_CONFIDENCE_THRESHOLD,
    Classifier,
)
from nlp_processing.models.records import FeedbackRecord
from nlp_processing.models.types import DEFAULT_THEME_SET
from nlp_processing.transport.client import (
    GeminiErrorKind,
    GeminiFailure,
    GeminiRequest,
    GeminiResult,
)

# The configured theme set under test (the seven standard themes), excluding
# the catch-all ``other`` for the "in-set, non-other" candidate strategies.
CONFIGURED_THEMES: tuple[str, ...] = tuple(sorted(DEFAULT_THEME_SET))
CONFIGURED_NON_OTHER: tuple[str, ...] = tuple(
    t for t in CONFIGURED_THEMES if t != OTHER_THEME
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
    """A fake ``generate`` returning a typed transport failure."""

    def _generate(request: GeminiRequest) -> GeminiResult:
        return GeminiResult(
            record_id=request.record_id,
            attempts=1,
            failure=GeminiFailure(
                record_id=request.record_id,
                kind=kind,
                message=message,
                attempts=1,
            ),
        )

    return _generate


def make_record(record_id: str = "rec-1", text: str = "the bill is wrong") -> FeedbackRecord:
    return FeedbackRecord(
        id=record_id,
        source_channel="email",
        cleaned_text=text,
        metadata={"origin": "test"},
    )


# ---------------------------------------------------------------------------
# Local Hypothesis strategies for classification response shapes
# ---------------------------------------------------------------------------
def confidences() -> st.SearchStrategy[float]:
    return st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


def in_set_theme_candidates() -> st.SearchStrategy[dict]:
    """A ``{theme, confidence}`` whose theme is in the configured set."""
    return st.fixed_dictionaries(
        {
            "theme": st.sampled_from(CONFIGURED_THEMES),
            "confidence": confidences(),
        }
    )


def out_of_set_theme_candidates() -> st.SearchStrategy[dict]:
    """A ``{theme, confidence}`` whose theme is NOT in the configured set."""
    unknown = st.text(min_size=1, max_size=20).filter(
        lambda s: s not in DEFAULT_THEME_SET
    )
    return st.fixed_dictionaries({"theme": unknown, "confidence": confidences()})


def classification_payloads() -> st.SearchStrategy[dict]:
    """A full classification response with a mix of in-set/out-of-set themes."""
    candidate = st.one_of(in_set_theme_candidates(), out_of_set_theme_candidates())
    return st.fixed_dictionaries(
        {"themes": st.lists(candidate, min_size=0, max_size=8)}
    )


# ---------------------------------------------------------------------------
# Property 12: Classifier output is well-formed (Req 5.1, 5.2, 5.3)
# ---------------------------------------------------------------------------
# Feature: nlp-feedback-processing, Property 12: Classifier output is well-formed
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(payload=classification_payloads())
def test_property_12_classifier_output_well_formed(payload):
    """On success: >=1 theme, all from the configured set, each confidence 0..1.

    **Validates: Requirements 5.1, 5.2, 5.3**
    """
    classifier = Classifier(make_success_generate(payload), theme_set=DEFAULT_THEME_SET)
    outcome = classifier.classify(make_record())

    # A well-formed (success) outcome is always produced for parseable input.
    assert outcome.ok
    assert outcome.error is None
    assert outcome.themes is not None
    # Req 5.1: at least one theme is assigned.
    assert len(outcome.themes) >= 1
    for assignment in outcome.themes:
        # Req 5.2: every assigned theme is drawn from the configured set.
        assert assignment.theme in DEFAULT_THEME_SET
        # Req 5.3: confidence lies in the inclusive range 0.0..1.0.
        assert 0.0 <= assignment.confidence <= 1.0
    # The originating record is preserved unchanged.
    assert outcome.record == make_record()


# ---------------------------------------------------------------------------
# Property 13: Theme threshold selection and default (Req 5.4, 5.5)
# ---------------------------------------------------------------------------
# Feature: nlp-feedback-processing, Property 13: Theme threshold selection and default
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(
    candidates=st.lists(in_set_theme_candidates(), min_size=0, max_size=8),
)
def test_property_13_threshold_selection_and_default(candidates):
    """Assigns exactly the configured themes with confidence >= 0.5; else `other`.

    **Validates: Requirements 5.4, 5.5**
    """
    payload = {"themes": candidates}
    classifier = Classifier(make_success_generate(payload), theme_set=DEFAULT_THEME_SET)
    outcome = classifier.classify(make_record())

    assert outcome.ok and outcome.themes is not None

    # Expected: the set of in-set themes with at least one candidate >= 0.5.
    expected = set()
    for cand in candidates:
        if cand["theme"] in DEFAULT_THEME_SET and cand["confidence"] >= THEME_CONFIDENCE_THRESHOLD:
            expected.add(cand["theme"])

    assigned = {a.theme for a in outcome.themes}

    if expected:
        # Req 5.4: assigns exactly the themes that reached the threshold.
        assert assigned == expected
        # And each assigned confidence is itself >= the threshold.
        for a in outcome.themes:
            assert a.confidence >= THEME_CONFIDENCE_THRESHOLD
    else:
        # Req 5.5: nothing qualified -> exactly the catch-all `other`.
        assert assigned == {OTHER_THEME}
        assert len(outcome.themes) == 1


# Feature: nlp-feedback-processing, Property 13: Theme threshold selection and default
@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
@given(
    candidates=st.lists(
        st.fixed_dictionaries(
            {
                "theme": st.sampled_from(CONFIGURED_THEMES),
                "confidence": st.floats(
                    min_value=0.0,
                    max_value=THEME_CONFIDENCE_THRESHOLD,
                    exclude_max=True,
                    allow_nan=False,
                ),
            }
        ),
        min_size=0,
        max_size=6,
    ),
)
def test_property_13_all_below_threshold_defaults_to_other(candidates):
    """When no candidate reaches 0.5 (incl. empty), exactly `other` is assigned.

    **Validates: Requirements 5.4, 5.5**
    """
    payload = {"themes": candidates}
    classifier = Classifier(make_success_generate(payload), theme_set=DEFAULT_THEME_SET)
    outcome = classifier.classify(make_record())

    assert outcome.ok and outcome.themes is not None
    assert len(outcome.themes) == 1
    assert outcome.themes[0].theme == OTHER_THEME


# ---------------------------------------------------------------------------
# Property 14: Unknown themes are discarded (Req 5.6)
# ---------------------------------------------------------------------------
# Feature: nlp-feedback-processing, Property 14: Unknown themes are discarded
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(payload=classification_payloads())
def test_property_14_unknown_themes_discarded(payload):
    """Out-of-set labels never appear; if nothing valid qualifies, `other`.

    **Validates: Requirements 5.6**
    """
    classifier = Classifier(make_success_generate(payload), theme_set=DEFAULT_THEME_SET)
    outcome = classifier.classify(make_record())

    assert outcome.ok and outcome.themes is not None
    assigned = {a.theme for a in outcome.themes}

    # Req 5.6: no assigned theme is outside the configured set.
    for theme in assigned:
        assert theme in DEFAULT_THEME_SET

    # Determine whether any *configured* candidate qualified at the threshold.
    qualifying = {
        c["theme"]
        for c in payload["themes"]
        if c["theme"] in DEFAULT_THEME_SET
        and c["confidence"] >= THEME_CONFIDENCE_THRESHOLD
    }
    if not qualifying:
        # Nothing valid qualified -> fall back to the catch-all `other`.
        assert assigned == {OTHER_THEME}


# Feature: nlp-feedback-processing, Property 14: Unknown themes are discarded
@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
@given(candidates=st.lists(out_of_set_theme_candidates(), min_size=1, max_size=6))
def test_property_14_only_unknown_themes_yields_other(candidates):
    """A response made up solely of out-of-set labels falls back to `other`.

    **Validates: Requirements 5.6**
    """
    payload = {"themes": candidates}
    classifier = Classifier(make_success_generate(payload), theme_set=DEFAULT_THEME_SET)
    outcome = classifier.classify(make_record())

    assert outcome.ok and outcome.themes is not None
    assert {a.theme for a in outcome.themes} == {OTHER_THEME}


# ---------------------------------------------------------------------------
# Unit test 9.5: classification unavailability (Req 5.7)
# ---------------------------------------------------------------------------
class TestClassificationUnavailability:
    """Req 5.7: API unavailable/timeout -> record preserved, error attached."""

    def test_timeout_preserves_record_and_attaches_error(self):
        record = make_record("rec-timeout")
        classifier = Classifier(
            make_failure_generate(GeminiErrorKind.TIMEOUT, "request timed out after 30s")
        )
        outcome = classifier.classify(record)

        assert not outcome.ok
        assert outcome.themes is None
        assert outcome.error is not None
        assert outcome.error.kind == "classification_failure"
        assert outcome.error.record_id == "rec-timeout"
        # The original record is preserved unchanged.
        assert outcome.record == record

    def test_exhausted_preserves_record_and_attaches_error(self):
        record = make_record("rec-exhausted")
        classifier = Classifier(
            make_failure_generate(GeminiErrorKind.EXHAUSTED, "exhausted 5 attempts")
        )
        outcome = classifier.classify(record)

        assert not outcome.ok
        assert outcome.themes is None
        assert outcome.error is not None
        assert outcome.error.record_id == "rec-exhausted"
        assert outcome.record == record

    def test_auth_failure_preserves_record(self):
        record = make_record("rec-auth")
        classifier = Classifier(make_failure_generate(GeminiErrorKind.AUTH, "401"))
        outcome = classifier.classify(record)

        assert not outcome.ok
        assert outcome.error is not None
        assert outcome.record == record
