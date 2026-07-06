"""Unit tests for the IntentClassifier (task 5.5, Req 8).

Covers:
* Successful classification with valid intents (Req 8.1, 8.2)
* Confidence <= 0.4 → "unclassified" (Req 8.3)
* requires_action mapping for action-required intents (Req 8.4)
* requires_action mapping for no-action intents (Req 8.5)
* Fallback on transport failure or timeout (Req 8.6)
* Invalid intent values from model → unclassified
* Missing intent or confidence in response → fallback
"""

from __future__ import annotations

import json

import pytest

from nlp_processing.enrichment.intent_classifier import (
    ACTION_REQUIRED_INTENTS,
    FALLBACK_RESULT,
    INTENT_CONFIDENCE_THRESHOLD,
    NO_ACTION_INTENTS,
    VALID_INTENTS,
    IntentClassificationResponse,
    IntentClassifier,
)
from nlp_processing.models.feedback_routing import CanonicalFeedback, IntentResult
from nlp_processing.transport.client import (
    GeminiErrorKind,
    GeminiFailure,
    GeminiRequest,
    GeminiResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_feedback(
    feedback_id: str = "fb-001",
    text: str = "My internet has been down for 3 hours, this is unacceptable!",
) -> CanonicalFeedback:
    """Create a test CanonicalFeedback record."""
    return CanonicalFeedback(
        feedback_id=feedback_id,
        source_type="widget",
        original_source_id="widget-sub-001",
        cleaned_text=text,
        detected_language="en",
        ingested_at="2024-01-15T10:00:00Z",
    )


def make_success_generate(payload: dict):
    """A fake generate returning a successful result with payload JSON."""

    def _generate(request: GeminiRequest) -> GeminiResult:
        return GeminiResult(
            record_id=request.record_id, attempts=1, text=json.dumps(payload)
        )

    return _generate


def make_failure_generate(kind: GeminiErrorKind = GeminiErrorKind.TIMEOUT, message: str = "timed out"):
    """A fake generate returning a transport failure."""

    def _generate(request: GeminiRequest) -> GeminiResult:
        return GeminiResult(
            record_id=request.record_id,
            attempts=1,
            failure=GeminiFailure(
                record_id=request.record_id, kind=kind, message=message, attempts=1
            ),
        )

    return _generate


def make_exception_generate(exc: Exception):
    """A fake generate that raises an exception."""

    def _generate(request: GeminiRequest) -> GeminiResult:
        raise exc

    return _generate


# ---------------------------------------------------------------------------
# Tests: Successful classification (Req 8.1, 8.2)
# ---------------------------------------------------------------------------

class TestSuccessfulClassification:
    """Tests for valid intent classification above confidence threshold."""

    @pytest.mark.parametrize("intent", sorted(ACTION_REQUIRED_INTENTS))
    def test_action_required_intents(self, intent: str):
        """Req 8.4: action-required intents set requires_action=True."""
        gen = make_success_generate({"intent": intent, "confidence": 0.8})
        classifier = IntentClassifier(gen)
        feedback = make_feedback()

        result = classifier.classify(feedback)

        assert result.intent == intent
        assert result.confidence == 0.8
        assert result.requires_action is True

    @pytest.mark.parametrize("intent", sorted(NO_ACTION_INTENTS - {"unclassified"}))
    def test_no_action_intents(self, intent: str):
        """Req 8.5: no-action intents set requires_action=False."""
        gen = make_success_generate({"intent": intent, "confidence": 0.75})
        classifier = IntentClassifier(gen)
        feedback = make_feedback()

        result = classifier.classify(feedback)

        assert result.intent == intent
        assert result.confidence == 0.75
        assert result.requires_action is False

    def test_assigns_exactly_one_intent(self):
        """Req 8.1: exactly one intent is assigned."""
        gen = make_success_generate({"intent": "complaint", "confidence": 0.9})
        classifier = IntentClassifier(gen)
        feedback = make_feedback()

        result = classifier.classify(feedback)

        # IntentResult has a single intent field, guaranteeing exactly one.
        assert result.intent == "complaint"
        assert isinstance(result, IntentResult)


# ---------------------------------------------------------------------------
# Tests: Low confidence → unclassified (Req 8.3)
# ---------------------------------------------------------------------------

class TestLowConfidence:
    """Tests for confidence <= 0.4 producing 'unclassified'."""

    def test_confidence_at_threshold_is_unclassified(self):
        """Req 8.3: confidence exactly 0.4 → unclassified."""
        gen = make_success_generate({"intent": "complaint", "confidence": 0.4})
        classifier = IntentClassifier(gen)
        feedback = make_feedback()

        result = classifier.classify(feedback)

        assert result.intent == "unclassified"
        assert result.confidence == 0.4
        assert result.requires_action is False

    def test_confidence_below_threshold_is_unclassified(self):
        """Req 8.3: confidence below 0.4 → unclassified."""
        gen = make_success_generate({"intent": "outage_report", "confidence": 0.2})
        classifier = IntentClassifier(gen)
        feedback = make_feedback()

        result = classifier.classify(feedback)

        assert result.intent == "unclassified"
        assert result.confidence == 0.2
        assert result.requires_action is False

    def test_confidence_just_above_threshold_is_classified(self):
        """Confidence > 0.4 should classify normally."""
        gen = make_success_generate({"intent": "complaint", "confidence": 0.41})
        classifier = IntentClassifier(gen)
        feedback = make_feedback()

        result = classifier.classify(feedback)

        assert result.intent == "complaint"
        assert result.requires_action is True


# ---------------------------------------------------------------------------
# Tests: Fallback on errors (Req 8.6)
# ---------------------------------------------------------------------------

class TestFallbackBehavior:
    """Tests for fallback on errors and timeouts."""

    def test_transport_timeout_returns_fallback(self):
        """Req 8.6: timeout → unclassified, requires_action=false."""
        gen = make_failure_generate(GeminiErrorKind.TIMEOUT, "request timed out after 10s")
        classifier = IntentClassifier(gen)
        feedback = make_feedback()

        result = classifier.classify(feedback)

        assert result.intent == "unclassified"
        assert result.confidence == 0.0
        assert result.requires_action is False

    def test_transport_error_returns_fallback(self):
        """Req 8.6: any transport error → fallback."""
        gen = make_failure_generate(GeminiErrorKind.ERROR, "internal server error")
        classifier = IntentClassifier(gen)
        feedback = make_feedback()

        result = classifier.classify(feedback)

        assert result.intent == "unclassified"
        assert result.requires_action is False

    def test_transport_auth_error_returns_fallback(self):
        """Req 8.6: auth error → fallback."""
        gen = make_failure_generate(GeminiErrorKind.AUTH, "unauthorized")
        classifier = IntentClassifier(gen)
        feedback = make_feedback()

        result = classifier.classify(feedback)

        assert result.intent == "unclassified"
        assert result.requires_action is False

    def test_exception_in_generate_returns_fallback(self):
        """Req 8.6: unexpected exception → fallback."""
        gen = make_exception_generate(RuntimeError("network down"))
        classifier = IntentClassifier(gen)
        feedback = make_feedback()

        result = classifier.classify(feedback)

        assert result.intent == "unclassified"
        assert result.confidence == 0.0
        assert result.requires_action is False

    def test_invalid_json_response_returns_fallback(self):
        """Req 8.6: unparseable response → fallback."""
        def _generate(request: GeminiRequest) -> GeminiResult:
            return GeminiResult(
                record_id=request.record_id, attempts=1, text="not valid json {{"
            )

        classifier = IntentClassifier(_generate)
        feedback = make_feedback()

        result = classifier.classify(feedback)

        assert result.intent == "unclassified"
        assert result.requires_action is False


# ---------------------------------------------------------------------------
# Tests: Invalid intent values from model
# ---------------------------------------------------------------------------

class TestInvalidIntentValues:
    """Tests for model returning intents outside the valid set."""

    def test_unknown_intent_treated_as_unclassified(self):
        """An intent not in IntentType set is treated as unclassified."""
        gen = make_success_generate({"intent": "random_nonsense", "confidence": 0.9})
        classifier = IntentClassifier(gen)
        feedback = make_feedback()

        result = classifier.classify(feedback)

        assert result.intent == "unclassified"
        assert result.confidence == 0.9
        assert result.requires_action is False

    def test_missing_intent_in_response_returns_fallback(self):
        """Missing intent field → fallback."""
        gen = make_success_generate({"confidence": 0.8})
        classifier = IntentClassifier(gen)
        feedback = make_feedback()

        result = classifier.classify(feedback)

        assert result.intent == "unclassified"
        assert result.requires_action is False

    def test_missing_confidence_in_response_returns_fallback(self):
        """Missing confidence field → fallback."""
        gen = make_success_generate({"intent": "complaint"})
        classifier = IntentClassifier(gen)
        feedback = make_feedback()

        result = classifier.classify(feedback)

        assert result.intent == "unclassified"
        assert result.requires_action is False

    def test_empty_response_returns_fallback(self):
        """Empty JSON object → fallback."""
        gen = make_success_generate({})
        classifier = IntentClassifier(gen)
        feedback = make_feedback()

        result = classifier.classify(feedback)

        assert result.intent == "unclassified"
        assert result.requires_action is False


# ---------------------------------------------------------------------------
# Tests: requires_action completeness
# ---------------------------------------------------------------------------

class TestRequiresActionCompleteness:
    """Verify all valid intents map to the correct requires_action value."""

    def test_all_valid_intents_have_defined_action_mapping(self):
        """Every IntentType value maps to either action or no-action set."""
        covered = ACTION_REQUIRED_INTENTS | NO_ACTION_INTENTS
        assert covered == VALID_INTENTS, (
            f"Unmapped intents: {VALID_INTENTS - covered}"
        )
