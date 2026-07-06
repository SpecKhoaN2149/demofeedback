"""Sentiment_Analyzer: polarity assignment for feedback records (task 10.1, Req 6).

The :class:`SentimentAnalyzer` turns a
:class:`~nlp_processing.models.records.FeedbackRecord` into a sentiment value
(``positive | neutral | negative``) plus a confidence score, using the Gemini
API. It builds a schema-constrained, sentiment-only request, hands it to the
transport (:class:`~nlp_processing.transport.client.GeminiClient`), parses the
untrusted JSON via the strict
:class:`~nlp_processing.serialization.parser.ResponseParser`, and then applies
the business rules from Requirement 6:

* assign exactly one of ``positive | neutral | negative`` with a confidence in
  the inclusive range 0.0..1.0, recorded on the insight **regardless of the
  confidence magnitude** (Req 6.1, 6.2, 6.3);
* if the model omits the sentiment value, default to ``neutral`` and record a
  missing-sentiment note keyed by the record id (Req 6.4);
* if the produced sentiment value is outside the allowed set, or the produced
  confidence is outside 0.0..1.0, reject the record, produce no
  ``Insight_Record``, and record a sentiment-validation error keyed by the
  record id (Req 6.5).

Design / testability
---------------------
Like the :class:`~nlp_processing.enrichment.classifier.Classifier`, the analyzer
depends on a *generate function* (``GeminiRequest -> GeminiResult``) rather than
a concrete client, so tests inject a fake that returns canned responses or
failures without a network. A :class:`GeminiClient` instance is also accepted
directly (its ``generate`` method is used).

The response schema is sentiment-specific and defined locally so the analyzer
stays independently callable. It is intentionally **lenient** about the
sentiment value and confidence range: it accepts any string for ``sentiment``
and any number for ``sentiment_confidence``, and both fields are optional. This
lets the analyzer *observe* an omitted value (Req 6.4) and an out-of-set /
out-of-range value (Req 6.5) and apply the distinct business rules, rather than
collapsing all three cases into a single parse error.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Optional, Union, get_args

from pydantic import BaseModel, ConfigDict, Field

from ..models.records import FeedbackRecord
from ..models.types import SentimentValue
from ..serialization.parser import ResponseParser
from ..transport.client import GeminiClient, GeminiRequest, GeminiResult

# The default sentiment assigned when the model omits a sentiment value
# entirely (Req 6.4).
DEFAULT_SENTIMENT: SentimentValue = "neutral"

# Confidence recorded for a defaulted ``neutral`` when the model omits the
# sentiment value and provides no usable confidence (Req 6.4). A defaulted
# sentiment carries no model-derived confidence, so it is recorded as 0.0 --
# this also ensures the insight is review-flagged downstream (Req 11.2).
DEFAULT_MISSING_CONFIDENCE: float = 0.0

# The allowed sentiment values (Req 6.1), derived from the shared literal so the
# two never drift apart.
ALLOWED_SENTIMENTS: frozenset[str] = frozenset(get_args(SentimentValue))


# A callable that performs one transport request. Matches GeminiClient.generate.
GenerateFn = Callable[[GeminiRequest], GeminiResult]


class SentimentResponse(BaseModel):
    """Focused, sentiment-only Gemini response schema.

    Both fields are optional and deliberately lenient so the analyzer can apply
    the Requirement 6 rules itself:

    * ``sentiment`` is any string (or omitted); out-of-set values are rejected
      by the analyzer (Req 6.5), and an omitted value triggers the ``neutral``
      default (Req 6.4).
    * ``sentiment_confidence`` is any number (or omitted) with **no** range
      constraint here, so an out-of-range confidence reaches the analyzer and is
      rejected as a sentiment-validation error (Req 6.5) rather than a parse
      error.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    sentiment: Optional[str] = None
    sentiment_confidence: Optional[float] = None


@dataclass(frozen=True)
class SentimentError:
    """A sentiment rejection keyed to the originating record.

    ``kind`` is ``"sentiment_validation"`` for Requirement 6.5 rejections
    (out-of-set value or out-of-range/missing confidence) and
    ``"sentiment_failure"`` for transport or parse failures. In every case the
    record is rejected and no ``Insight_Record`` is produced.
    """

    record_id: str
    reason: str
    kind: str = "sentiment_validation"


@dataclass(frozen=True)
class SentimentOutcome:
    """Result of :meth:`SentimentAnalyzer.analyze`.

    The original ``record`` is always preserved unchanged. On success
    ``sentiment`` is one of ``positive | neutral | negative``, ``confidence`` is
    in 0.0..1.0, ``error`` is ``None``, and ``notes`` may carry a
    missing-sentiment note (Req 6.4). On rejection ``sentiment`` and
    ``confidence`` are ``None`` and ``error`` carries a :class:`SentimentError`
    (Req 6.5). Use :attr:`ok` to discriminate.
    """

    record: FeedbackRecord
    sentiment: Optional[SentimentValue] = None
    confidence: Optional[float] = None
    notes: tuple[str, ...] = field(default_factory=tuple)
    error: Optional[SentimentError] = None

    @property
    def ok(self) -> bool:
        """True when sentiment analysis succeeded and a value is available."""
        return self.error is None

    @property
    def record_id(self) -> str:
        """The id of the (preserved) feedback record."""
        return self.record.id

    def __post_init__(self) -> None:
        # Exactly one of (sentiment + confidence) or error must be populated.
        if (self.error is None) == (self.sentiment is None):
            raise ValueError(
                "SentimentOutcome must carry exactly one of a sentiment or an error"
            )
        if self.error is None:
            # Success: confidence must be present and recorded regardless of
            # magnitude (Req 6.3).
            if self.confidence is None:
                raise ValueError(
                    "a successful sentiment outcome must record a confidence"
                )
        else:
            # Rejection: no insight fields are produced (Req 6.5).
            if self.confidence is not None:
                raise ValueError(
                    "a rejected sentiment outcome must not carry a confidence"
                )


class SentimentAnalyzer:
    """Assigns sentiment to feedback records via Gemini (Req 6).

    Parameters
    ----------
    client:
        Either a :class:`GeminiClient` (its ``generate`` method is used) or any
        callable with the ``GeminiRequest -> GeminiResult`` shape. The callable
        seam lets tests inject a fake transport without a network.
    parser:
        The strict response parser. Defaults to a fresh :class:`ResponseParser`.
    """

    def __init__(
        self,
        client: Union[GeminiClient, GenerateFn],
        *,
        parser: Optional[ResponseParser] = None,
    ) -> None:
        if hasattr(client, "generate"):
            self._generate: GenerateFn = client.generate  # type: ignore[assignment]
        elif callable(client):
            self._generate = client
        else:  # pragma: no cover - defensive guard
            raise TypeError(
                "client must be a GeminiClient or a GeminiRequest->GeminiResult callable"
            )
        self._parser = parser or ResponseParser()

    def analyze(
        self, record: FeedbackRecord, *, language_code: str = "en"
    ) -> SentimentOutcome:
        """Assign a sentiment value and confidence to ``record``.

        Builds a schema-constrained request, calls the transport, parses the
        response, and applies the Requirement 6 business rules. The input
        ``record`` is never mutated and is returned on the outcome regardless of
        success or rejection.

        Parameters
        ----------
        language_code:
            ISO 639-1 code for the input language. When not "en", a language
            override clause is prepended to the system instruction (Req 6.1).
            Defaults to "en" (no override).
        """
        request = self._build_request(record, language_code=language_code)
        result = self._generate(request)

        # Transport failure: API unavailable, timeout, auth, or exhaustion.
        # Requirement 6 defines no default for an unavailable API, so the record
        # is rejected (no insight) and the orchestrator records the failure.
        if not result.ok:
            failure = result.failure
            reason = (
                f"sentiment request failed ({failure.kind.value}): {failure.message}"
                if failure is not None
                else "sentiment request failed: transport returned no response"
            )
            return SentimentOutcome(
                record=record,
                error=SentimentError(
                    record_id=record.id, reason=reason, kind="sentiment_failure"
                ),
            )

        # Strictly parse the untrusted JSON against the lenient sentiment schema.
        outcome = self._parser.parse_enrichment(
            result.text or "", record.id, SentimentResponse
        )
        if not outcome.ok:
            assert outcome.error is not None
            detail = outcome.error.reason
            if outcome.error.details:
                detail = f"{detail}: {'; '.join(outcome.error.details)}"
            return SentimentOutcome(
                record=record,
                error=SentimentError(
                    record_id=record.id,
                    reason=f"sentiment response invalid: {detail}",
                    kind="sentiment_failure",
                ),
            )

        return self._apply_rules(record, outcome.value)

    def _apply_rules(
        self, record: FeedbackRecord, response: SentimentResponse
    ) -> SentimentOutcome:
        """Apply the Requirement 6 rules to a parsed sentiment response."""
        value = response.sentiment
        confidence = response.sentiment_confidence

        # Req 6.5: a produced confidence outside 0.0..1.0 rejects the record,
        # regardless of whether a sentiment value was provided.
        if confidence is not None and not (0.0 <= confidence <= 1.0):
            return self._reject(
                record,
                f"sentiment confidence {confidence} is outside the inclusive "
                "range 0.0..1.0",
            )

        # Req 6.4: the model omitted the sentiment value entirely -> default to
        # neutral and record a missing-sentiment note keyed by the record id.
        if value is None:
            recorded_confidence = (
                confidence if confidence is not None else DEFAULT_MISSING_CONFIDENCE
            )
            note = (
                f"missing-sentiment: record {record.id} had no sentiment value; "
                f"defaulted to '{DEFAULT_SENTIMENT}'"
            )
            return SentimentOutcome(
                record=record,
                sentiment=DEFAULT_SENTIMENT,
                confidence=recorded_confidence,
                notes=(note,),
            )

        # Req 6.5: a produced value outside the allowed set rejects the record.
        if value not in ALLOWED_SENTIMENTS:
            return self._reject(
                record,
                f"sentiment value '{value}' is outside the allowed set "
                f"{sorted(ALLOWED_SENTIMENTS)}",
            )

        # Req 6.2: a sentiment value with no confidence is malformed; a missing
        # confidence is not a value in 0.0..1.0, so reject (Req 6.5).
        if confidence is None:
            return self._reject(
                record,
                f"sentiment value '{value}' was produced without a confidence "
                "score in 0.0..1.0",
            )

        # Req 6.1, 6.2, 6.3: exactly one valid value with an in-range confidence,
        # recorded regardless of magnitude.
        return SentimentOutcome(
            record=record,
            sentiment=value,  # type: ignore[arg-type] - validated against the set
            confidence=confidence,
        )

    def _reject(self, record: FeedbackRecord, reason: str) -> SentimentOutcome:
        """Build a sentiment-validation rejection outcome (Req 6.5)."""
        return SentimentOutcome(
            record=record,
            error=SentimentError(
                record_id=record.id, reason=reason, kind="sentiment_validation"
            ),
        )

    def _build_request(
        self, record: FeedbackRecord, *, language_code: str = "en"
    ) -> GeminiRequest:
        """Build the schema-constrained sentiment request for ``record``."""
        from .language_prompts import apply_language_override

        system_instruction = (
            "You are a sentiment analyzer for telecom customer feedback. "
            "Assign exactly one sentiment label drawn ONLY from the set: "
            "positive, neutral, negative. Return the label together with a "
            "confidence score between 0.0 and 1.0. Respond strictly as JSON "
            "matching the provided schema."
        )
        system_instruction = apply_language_override(
            system_instruction, language_code
        )
        contents = json.dumps(
            {
                "instruction": "Determine the sentiment of the following customer feedback.",
                "allowed_sentiments": sorted(ALLOWED_SENTIMENTS),
                "feedback_text": record.cleaned_text,
            }
        )
        return GeminiRequest(
            record_id=record.id,
            contents=contents,
            response_schema=SentimentResponse,
            system_instruction=system_instruction,
        )


__all__ = [
    "SentimentAnalyzer",
    "SentimentOutcome",
    "SentimentError",
    "SentimentResponse",
    "DEFAULT_SENTIMENT",
    "ALLOWED_SENTIMENTS",
]
