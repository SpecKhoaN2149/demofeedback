"""Intent_Classifier: intent assignment for feedback records (task 5.5).

The :class:`IntentClassifier` takes a
:class:`~nlp_processing.models.feedback_routing.CanonicalFeedback` and assigns
exactly one intent from the :data:`IntentType` set, returning an
:class:`~nlp_processing.models.feedback_routing.IntentResult`.

Business rules (Requirement 8):

* Assign exactly one intent from the IntentType set (Req 8.1).
* Store intent and confidence on the feedback_analysis record (Req 8.2).
* Assign "unclassified" when confidence <= 0.4 (Req 8.3).
* Set requires_action=true for {complaint, request_for_help, outage_report,
  billing_dispute, cancellation_risk} (Req 8.4).
* Set requires_action=false for {feature_suggestion, praise, unclassified}
  (Req 8.5).
* On error or timeout (10 seconds), assign "unclassified" with
  requires_action=false (Req 8.6).

Design / testability
---------------------
The classifier depends on a *generate function* (``GeminiRequest -> GeminiResult``)
rather than a concrete client, so tests inject a fake that returns canned
responses or failures without a network. A :class:`GeminiClient` instance is
also accepted directly (its ``generate`` method is used).
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Optional, Union, get_args

from pydantic import BaseModel, ConfigDict, Field

from ..models.feedback_routing import CanonicalFeedback, IntentResult, IntentType
from ..serialization.parser import ResponseParser
from ..transport.client import GeminiClient, GeminiRequest, GeminiResult

logger = logging.getLogger(__name__)

# The valid intent values derived from the IntentType literal.
VALID_INTENTS: frozenset[str] = frozenset(get_args(IntentType))

# Confidence threshold: if the highest confidence is at or below this value,
# the intent is set to "unclassified" (Req 8.3).
INTENT_CONFIDENCE_THRESHOLD: float = 0.4

# Intents that require action (Req 8.4).
ACTION_REQUIRED_INTENTS: frozenset[str] = frozenset(
    {
        "complaint",
        "request_for_help",
        "outage_report",
        "billing_dispute",
        "cancellation_risk",
    }
)

# Intents that do NOT require action (Req 8.5).
NO_ACTION_INTENTS: frozenset[str] = frozenset(
    {
        "feature_suggestion",
        "praise",
        "unclassified",
    }
)

# Timeout for the intent classification call (Req 8.6).
INTENT_TIMEOUT_SECONDS: int = 10

# Fallback result returned on error or timeout (Req 8.6).
FALLBACK_RESULT = IntentResult(
    intent="unclassified",
    confidence=0.0,
    requires_action=False,
)

# A callable that performs one transport request.
GenerateFn = Callable[[GeminiRequest], GeminiResult]


class IntentClassificationResponse(BaseModel):
    """Focused, intent-only Gemini response schema.

    Both fields are optional and lenient so the classifier can apply business
    rules itself. The model may return any string for intent; out-of-set values
    are handled by the classifier.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    intent: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


def _determine_requires_action(intent: str) -> bool:
    """Determine the requires_action flag for a given intent (Req 8.4, 8.5).

    Returns True for action-required intents, False otherwise.
    """
    if intent in ACTION_REQUIRED_INTENTS:
        return True
    return False


class IntentClassifier:
    """Assigns intent to feedback records via Gemini (Req 8).

    Parameters
    ----------
    client:
        Either a :class:`GeminiClient` (its ``generate`` method is used) or any
        callable with the ``GeminiRequest -> GeminiResult`` shape. The callable
        seam lets tests inject a fake transport without a network.
    parser:
        The strict response parser. Defaults to a fresh :class:`ResponseParser`.
    timeout_s:
        Per-request timeout in seconds (Req 8.6). Defaults to 10.
    """

    def __init__(
        self,
        client: Union[GeminiClient, GenerateFn],
        *,
        parser: Optional[ResponseParser] = None,
        timeout_s: int = INTENT_TIMEOUT_SECONDS,
    ) -> None:
        if hasattr(client, "generate"):
            self._generate: GenerateFn = client.generate  # type: ignore[assignment]
        elif callable(client):
            self._generate = client
        else:  # pragma: no cover
            raise TypeError(
                "client must be a GeminiClient or a GeminiRequest->GeminiResult callable"
            )
        self._parser = parser or ResponseParser()
        self._timeout_s = timeout_s

    def classify(self, feedback: CanonicalFeedback) -> IntentResult:
        """Classify the intent of ``feedback``.

        Builds a schema-constrained request, calls the transport, parses the
        response, and applies the Requirement 8 business rules. On any error
        or timeout, returns the fallback result (unclassified, requires_action=false).

        Parameters
        ----------
        feedback:
            The canonical feedback record to classify.

        Returns
        -------
        IntentResult
            The classified intent with confidence and requires_action flag.
        """
        request = self._build_request(feedback)

        try:
            result = self._generate(request)
        except Exception as exc:
            # Any unexpected exception from the generate call → fallback (Req 8.6).
            logger.warning(
                "Intent classification failed for feedback %s: %s",
                feedback.feedback_id,
                str(exc),
            )
            return FALLBACK_RESULT

        # Transport failure: API unavailable, timeout, auth, or exhaustion.
        if not result.ok:
            failure = result.failure
            reason = (
                f"intent classification failed ({failure.kind.value}): {failure.message}"
                if failure is not None
                else "intent classification failed: transport returned no response"
            )
            logger.warning(
                "Intent classification transport failure for feedback %s: %s",
                feedback.feedback_id,
                reason,
            )
            return FALLBACK_RESULT

        # Parse the response JSON against the intent schema.
        outcome = self._parser.parse_enrichment(
            result.text or "", feedback.feedback_id, IntentClassificationResponse
        )
        if not outcome.ok:
            logger.warning(
                "Intent classification response invalid for feedback %s: %s",
                feedback.feedback_id,
                outcome.error.reason if outcome.error else "unknown parse error",
            )
            return FALLBACK_RESULT

        return self._apply_rules(outcome.value)

    def _apply_rules(self, response: IntentClassificationResponse) -> IntentResult:
        """Apply the Requirement 8 business rules to a parsed response."""
        intent_value = response.intent
        confidence = response.confidence

        # If the model didn't return an intent or confidence, fallback.
        if intent_value is None or confidence is None:
            return FALLBACK_RESULT

        # If confidence is out of valid range (shouldn't happen due to schema
        # validation, but defensive), fallback.
        if not (0.0 <= confidence <= 1.0):
            return FALLBACK_RESULT

        # Req 8.3: If confidence <= 0.4, assign "unclassified".
        if confidence <= INTENT_CONFIDENCE_THRESHOLD:
            return IntentResult(
                intent="unclassified",
                confidence=confidence,
                requires_action=False,
            )

        # If the returned intent is not in the valid set, treat as unclassified.
        if intent_value not in VALID_INTENTS:
            return IntentResult(
                intent="unclassified",
                confidence=confidence,
                requires_action=False,
            )

        # Valid intent with sufficient confidence.
        requires_action = _determine_requires_action(intent_value)
        return IntentResult(
            intent=intent_value,  # type: ignore[arg-type]
            confidence=confidence,
            requires_action=requires_action,
        )

    def _build_request(self, feedback: CanonicalFeedback) -> GeminiRequest:
        """Build the schema-constrained intent classification request."""
        valid_intents_list = sorted(VALID_INTENTS - {"unclassified"})
        system_instruction = (
            "You are an intent classifier for telecom customer feedback. "
            "Classify the customer's intent into exactly one category drawn ONLY "
            f"from the set: {', '.join(valid_intents_list)}. "
            "Return the intent label and a confidence score between 0.0 and 1.0. "
            "Respond strictly as JSON matching the provided schema."
        )
        contents = json.dumps(
            {
                "instruction": "Classify the intent of the following customer feedback.",
                "allowed_intents": valid_intents_list,
                "feedback_text": feedback.cleaned_text,
            }
        )
        return GeminiRequest(
            record_id=feedback.feedback_id,
            contents=contents,
            response_schema=IntentClassificationResponse,
            system_instruction=system_instruction,
        )


__all__ = [
    "IntentClassifier",
    "IntentClassificationResponse",
    "VALID_INTENTS",
    "INTENT_CONFIDENCE_THRESHOLD",
    "ACTION_REQUIRED_INTENTS",
    "NO_ACTION_INTENTS",
    "INTENT_TIMEOUT_SECONDS",
    "FALLBACK_RESULT",
]
