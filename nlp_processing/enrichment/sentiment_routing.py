"""Sentiment_Analyzer for the NLP feedback routing pipeline (task 5.1).

The :class:`SentimentAnalyzer` classifies the sentiment of a
:class:`~nlp_processing.models.feedback_routing.CanonicalFeedback` record and
returns a :class:`~nlp_processing.models.feedback_routing.SentimentResult`
containing a label (``positive | neutral | negative``) and a numeric score
in the range [-1.0, +1.0].

Business rules (Requirements 4.1–4.6):

* Req 4.1: classify sentiment as positive, neutral, or negative.
* Req 4.2: assign a numeric sentiment_score in [-1.0, +1.0].
* Req 4.4: short-text sentinel — if cleaned_text < 5 chars, return
  neutral/0.0 without invoking the language model.
* Req 4.5: label/score consistency enforcement — score > 0.2 → positive,
  score < -0.2 → negative, else neutral. Overrides the model-returned label.
* Req 4.6: on model error or timeout, fallback to neutral/0.0.

Design / testability
---------------------
The analyzer depends on a *generate function* (``GeminiRequest -> GeminiResult``)
rather than a concrete client, so tests inject a fake that returns canned
responses or failures without a network. A :class:`GeminiClient` instance is
also accepted directly (its ``generate`` method is used).
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Optional, Union

from pydantic import BaseModel, ConfigDict

from ..models.feedback_routing import CanonicalFeedback, SentimentResult
from ..transport.client import GeminiClient, GeminiRequest, GeminiResult

logger = logging.getLogger(__name__)

# Short-text sentinel threshold (Req 4.4).
SHORT_TEXT_THRESHOLD = 5

# Label/score consistency boundaries (Req 4.5).
POSITIVE_THRESHOLD = 0.2
NEGATIVE_THRESHOLD = -0.2

# Fallback result used on error or timeout (Req 4.6).
FALLBACK_RESULT = SentimentResult(sentiment_label="neutral", sentiment_score=0.0)

# A callable that performs one transport request. Matches GeminiClient.generate.
GenerateFn = Callable[[GeminiRequest], GeminiResult]


class _SentimentResponse(BaseModel):
    """Lenient Gemini response schema for sentiment analysis.

    Both fields are optional so the analyzer can handle missing values
    gracefully and apply fallback logic.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    sentiment_label: Optional[str] = None
    sentiment_score: Optional[float] = None


def _enforce_label_consistency(score: float) -> str:
    """Apply Req 4.5: derive label from score, overriding model output.

    Rules:
        score > 0.2  → "positive"
        score < -0.2 → "negative"
        else         → "neutral"
    """
    if score > POSITIVE_THRESHOLD:
        return "positive"
    elif score < NEGATIVE_THRESHOLD:
        return "negative"
    return "neutral"


def _clamp_score(score: float) -> float:
    """Clamp a score to the valid [-1.0, +1.0] range."""
    return max(-1.0, min(1.0, score))


class SentimentAnalyzer:
    """Assigns sentiment to feedback records for the routing pipeline.

    Parameters
    ----------
    client:
        Either a :class:`GeminiClient` (its ``generate`` method is used) or any
        callable with the ``GeminiRequest -> GeminiResult`` shape.
    """

    def __init__(self, client: Union[GeminiClient, GenerateFn]) -> None:
        if hasattr(client, "generate"):
            self._generate: GenerateFn = client.generate  # type: ignore[assignment]
        elif callable(client):
            self._generate = client
        else:
            raise TypeError(
                "client must be a GeminiClient or a GeminiRequest->GeminiResult callable"
            )

    def analyze(self, feedback: CanonicalFeedback) -> SentimentResult:
        """Classify sentiment of ``feedback`` and return a SentimentResult.

        Applies all business rules:
        - Short-text sentinel (< 5 chars → neutral/0.0, no model call)
        - Label/score consistency enforcement (overrides model label)
        - Error fallback (neutral/0.0 on any failure)
        """
        # Req 4.4: Short-text sentinel — skip model call for very short text.
        if len(feedback.cleaned_text) < SHORT_TEXT_THRESHOLD:
            return SentimentResult(sentiment_label="neutral", sentiment_score=0.0)

        # Call the model via Gemini transport.
        try:
            result = self._invoke_model(feedback)
        except Exception as exc:
            # Req 4.6: fallback on any unexpected exception.
            logger.warning(
                "Sentiment analysis failed for record %s: %s",
                feedback.feedback_id,
                str(exc),
            )
            return FALLBACK_RESULT

        # If transport returned an error, apply fallback (Req 4.6).
        if not result.ok:
            failure = result.failure
            reason = (
                f"{failure.kind.value}: {failure.message}"
                if failure is not None
                else "unknown transport failure"
            )
            logger.warning(
                "Sentiment model error for record %s: %s",
                feedback.feedback_id,
                reason,
            )
            return FALLBACK_RESULT

        # Parse the model response.
        return self._parse_response(feedback.feedback_id, result.text or "")

    def _invoke_model(self, feedback: CanonicalFeedback) -> GeminiResult:
        """Build and send the sentiment request to the Gemini API."""
        system_instruction = (
            "You are a sentiment analyzer for customer feedback. "
            "Analyze the sentiment of the provided text and return a JSON object "
            "with two fields: 'sentiment_label' (one of 'positive', 'neutral', "
            "'negative') and 'sentiment_score' (a float between -1.0 and 1.0, "
            "where -1.0 is most negative and 1.0 is most positive). "
            "Respond strictly as JSON matching the provided schema."
        )
        contents = json.dumps(
            {
                "instruction": "Determine the sentiment of the following customer feedback.",
                "feedback_text": feedback.cleaned_text,
            }
        )
        request = GeminiRequest(
            record_id=feedback.feedback_id,
            contents=contents,
            response_schema=_SentimentResponse,
            system_instruction=system_instruction,
        )
        return self._generate(request)

    def _parse_response(self, record_id: str, raw_text: str) -> SentimentResult:
        """Parse model JSON response and apply consistency rules.

        On any parse failure or missing/invalid score, returns the fallback
        result (Req 4.6).
        """
        try:
            data = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Failed to parse sentiment JSON for record %s", record_id
            )
            return FALLBACK_RESULT

        # Extract the score from the response.
        raw_score = data.get("sentiment_score") if isinstance(data, dict) else None

        if raw_score is None or not isinstance(raw_score, (int, float)):
            # No usable score from model → fallback (Req 4.6).
            logger.warning(
                "No valid sentiment_score in response for record %s", record_id
            )
            return FALLBACK_RESULT

        # Clamp to valid range and enforce label consistency (Req 4.5).
        score = _clamp_score(float(raw_score))
        label = _enforce_label_consistency(score)

        return SentimentResult(sentiment_label=label, sentiment_score=score)


__all__ = [
    "SentimentAnalyzer",
    "FALLBACK_RESULT",
    "SHORT_TEXT_THRESHOLD",
    "POSITIVE_THRESHOLD",
    "NEGATIVE_THRESHOLD",
]
