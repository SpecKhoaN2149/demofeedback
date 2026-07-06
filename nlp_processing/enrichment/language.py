"""Language_Detector: language identification for feedback records (Req 5).

The :class:`LanguageDetector` identifies the natural language of a
:class:`~nlp_processing.models.records.FeedbackRecord`'s cleaned text using the
Gemini API. It builds a schema-constrained language detection request, hands it
to the transport (:class:`~nlp_processing.transport.client.GeminiClient`), parses
the response, and then applies the fallback rules from Requirement 5:

* detect the language and assign an ISO 639-1 code with a confidence score
  between 0.0 and 1.0 (Req 5.1, 5.3);
* support at least English, Spanish, French, German, and Portuguese (Req 5.2);
* if confidence < 0.6, default to "en" with is_uncertain=True and a note
  (Req 5.4);
* if the detected language is not in the supported set, default to "en" with
  is_uncertain=True and a note (Req 5.4);
* on transport failure, default to "en" with confidence 0.0, is_uncertain=True,
  and a failure note (Req 5.4).

Design / testability
---------------------
The detector depends on a *generate function* (``GeminiRequest -> GeminiResult``)
rather than a concrete client, so tests inject a fake that returns canned
responses or failures without a network. A :class:`GeminiClient` instance is
also accepted directly (its ``generate`` method is used).
"""

from __future__ import annotations

import json
from typing import Callable, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from ..models.enhancements import LanguageDetectionResult
from ..models.records import FeedbackRecord
from ..transport.client import GeminiClient, GeminiRequest, GeminiResult

# Default supported languages (Req 5.2): English, Spanish, French, German, Portuguese.
DEFAULT_SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"en", "es", "fr", "de", "pt"})

# Confidence threshold below which detection is considered uncertain (Req 5.4).
CONFIDENCE_THRESHOLD: float = 0.6

# Default language used on fallback (Req 5.4).
DEFAULT_LANGUAGE: str = "en"

# A callable that performs one transport request. Matches GeminiClient.generate.
GenerateFn = Callable[[GeminiRequest], GeminiResult]


class LanguageDetectionResponse(BaseModel):
    """Schema for the Gemini language detection response.

    Fields are optional to handle cases where the model returns incomplete
    data, allowing the detector to apply fallback rules gracefully.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    language_code: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class LanguageDetector:
    """Identifies the natural language of feedback text (Req 5).

    Parameters
    ----------
    client:
        Either a :class:`GeminiClient` (its ``generate`` method is used) or any
        callable with the ``GeminiRequest -> GeminiResult`` shape. The callable
        seam lets tests inject a fake transport without a network.
    supported_languages:
        The set of ISO 639-1 codes considered supported (Req 5.2). Defaults to
        ``{"en", "es", "fr", "de", "pt"}``.
    """

    def __init__(
        self,
        client: Union[GeminiClient, GenerateFn],
        supported_languages: Optional[frozenset[str]] = None,
    ) -> None:
        if hasattr(client, "generate"):
            self._generate: GenerateFn = client.generate  # type: ignore[assignment]
        elif callable(client):
            self._generate = client
        else:  # pragma: no cover - defensive guard
            raise TypeError(
                "client must be a GeminiClient or a GeminiRequest->GeminiResult callable"
            )

        self.supported_languages: frozenset[str] = (
            supported_languages
            if supported_languages is not None
            else DEFAULT_SUPPORTED_LANGUAGES
        )

    def detect(self, record: FeedbackRecord) -> LanguageDetectionResult:
        """Detect the language of ``record``'s cleaned text.

        Builds a schema-constrained request, calls the transport, parses the
        response, and applies the Requirement 5 fallback rules. On any failure
        (transport error, parse error, or unexpected response), defaults to
        English with confidence 0.0 and is_uncertain=True.
        """
        try:
            request = self._build_request(record)
            result = self._generate(request)

            # Transport failure: default to English (Req 5.4).
            if not result.ok:
                failure = result.failure
                reason = (
                    f"Language detection failed: {failure.kind.value} - {failure.message}"
                    if failure is not None
                    else "Language detection failed: transport returned no response"
                )
                return LanguageDetectionResult(
                    record_id=record.id,
                    language_code=DEFAULT_LANGUAGE,
                    confidence=0.0,
                    is_uncertain=True,
                    note=reason,
                )

            # Parse the response JSON.
            return self._parse_and_apply_rules(record, result.text or "")

        except Exception as exc:
            # Catch-all for any unexpected error: default to English gracefully.
            return LanguageDetectionResult(
                record_id=record.id,
                language_code=DEFAULT_LANGUAGE,
                confidence=0.0,
                is_uncertain=True,
                note=f"Language detection failed: {exc}",
            )

    def _parse_and_apply_rules(
        self, record: FeedbackRecord, response_text: str
    ) -> LanguageDetectionResult:
        """Parse the Gemini response and apply fallback rules."""
        try:
            data = json.loads(response_text)
            response = LanguageDetectionResponse.model_validate(data)
        except (json.JSONDecodeError, Exception) as exc:
            # Unparseable response: default to English.
            return LanguageDetectionResult(
                record_id=record.id,
                language_code=DEFAULT_LANGUAGE,
                confidence=0.0,
                is_uncertain=True,
                note=f"Language detection failed: unable to parse response - {exc}",
            )

        language_code = response.language_code
        confidence = response.confidence

        # If the model returned no language code or no confidence, treat as failure.
        if language_code is None or confidence is None:
            return LanguageDetectionResult(
                record_id=record.id,
                language_code=DEFAULT_LANGUAGE,
                confidence=0.0,
                is_uncertain=True,
                note="Language detection failed: incomplete response from model",
            )

        # Normalize the language code to lowercase for comparison.
        language_code = language_code.strip().lower()

        # Req 5.4: If confidence < 0.6, default to English.
        if confidence < CONFIDENCE_THRESHOLD:
            return LanguageDetectionResult(
                record_id=record.id,
                language_code=DEFAULT_LANGUAGE,
                confidence=confidence,
                is_uncertain=True,
                note=f"Language detection uncertain (confidence: {confidence})",
            )

        # Req 5.4: If detected language not in supported set, default to English.
        if language_code not in self.supported_languages:
            return LanguageDetectionResult(
                record_id=record.id,
                language_code=DEFAULT_LANGUAGE,
                confidence=confidence,
                is_uncertain=True,
                note=f"Unsupported language detected: {language_code}",
            )

        # Successful detection with sufficient confidence and supported language.
        return LanguageDetectionResult(
            record_id=record.id,
            language_code=language_code,
            confidence=confidence,
            is_uncertain=False,
            note=None,
        )

    def _build_request(self, record: FeedbackRecord) -> GeminiRequest:
        """Build the schema-constrained language detection request."""
        system_instruction = (
            "You are a language identification expert. "
            "Identify the language of the following text. "
            "Return the ISO 639-1 two-letter language code and your confidence "
            "score between 0.0 and 1.0. Respond strictly as JSON matching the "
            "provided schema."
        )
        contents = json.dumps(
            {
                "instruction": "Identify the language of the following text. "
                "Return the ISO 639-1 code and your confidence score (0.0-1.0).",
                "text": record.cleaned_text,
            }
        )
        return GeminiRequest(
            record_id=record.id,
            contents=contents,
            response_schema=LanguageDetectionResponse,
            system_instruction=system_instruction,
        )


__all__ = [
    "LanguageDetector",
    "LanguageDetectionResponse",
    "DEFAULT_SUPPORTED_LANGUAGES",
    "CONFIDENCE_THRESHOLD",
    "DEFAULT_LANGUAGE",
]
