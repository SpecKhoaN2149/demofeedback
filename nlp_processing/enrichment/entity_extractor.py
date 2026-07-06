"""Entity_Extractor: named entity extraction for feedback records (task 5.7, Req 9).

The :class:`EntityExtractor` identifies and extracts structured entities from
:class:`~nlp_processing.models.feedback_routing.CanonicalFeedback` text using the
Gemini API. It builds a schema-constrained extraction request, hands it to the
transport (:class:`~nlp_processing.transport.client.GeminiClient`), parses the
untrusted JSON via the strict
:class:`~nlp_processing.serialization.parser.ResponseParser`, and then applies
the business rules from Requirement 9:

* Extract entity types: service_area, product_name, time_reference,
  dollar_amount, equipment_name, outage_mention, competitor_mention (Req 9.1).
* Store entities with entity_type, entity_value, and confidence score; only
  include entities with confidence >= 0.5 (Req 9.2).
* If no entities have confidence >= 0.5, store an empty list (Req 9.3).
* Normalize dollar_amount to exactly 2 decimal places in range 0.01–999999999.99;
  discard unparseable amounts (Req 9.4, 9.6).
* On timeout (30s) or service error, return empty list and mark status
  "failed" (Req 9.5).
* Enforce max 50 entities per feedback record, entity_value max 200 chars
  (Req 9.1).

Design / testability
---------------------
Like other enrichment components, the extractor depends on a *generate function*
(``GeminiRequest -> GeminiResult``) rather than a concrete client, so tests
inject a fake that returns canned responses without a network.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from ..models.feedback_routing import CanonicalFeedback, ExtractedEntity
from ..serialization.parser import ResponseParser
from ..transport.client import GeminiClient, GeminiRequest, GeminiResult

logger = logging.getLogger(__name__)

# Maximum entities stored per feedback record (Req 9.1).
MAX_ENTITIES_PER_RECORD: int = 50

# Minimum confidence threshold for entity inclusion (Req 9.2).
MIN_CONFIDENCE_THRESHOLD: float = 0.5

# Maximum length for entity_value (Req 9.1).
MAX_ENTITY_VALUE_LENGTH: int = 200

# Dollar amount valid range (Req 9.4).
DOLLAR_AMOUNT_MIN: float = 0.01
DOLLAR_AMOUNT_MAX: float = 999_999_999.99

# Timeout for entity extraction requests in seconds (Req 9.5).
EXTRACTION_TIMEOUT_SECONDS: int = 30

# Valid entity types (Req 9.1).
VALID_ENTITY_TYPES = frozenset(
    {
        "service_area",
        "product_name",
        "time_reference",
        "dollar_amount",
        "equipment_name",
        "outage_mention",
        "competitor_mention",
    }
)

# A callable that performs one transport request. Matches GeminiClient.generate.
GenerateFn = Callable[[GeminiRequest], GeminiResult]


class EntityCandidate(BaseModel):
    """A single entity candidate from the Gemini response.

    Fields are deliberately lenient to allow the extractor to apply business
    rules (filtering, normalization) itself.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    entity_type: str
    entity_value: str
    confidence: float = Field(ge=0.0, le=1.0)


class EntityExtractionResponse(BaseModel):
    """Focused, entity-extraction-only Gemini response schema.

    An empty list signals the model found no entities.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    entities: list[EntityCandidate] = Field(default_factory=list)


@dataclass(frozen=True)
class EntityExtractionResult:
    """Result of :meth:`EntityExtractor.extract`.

    On success, ``entities`` contains the validated, filtered list of
    :class:`ExtractedEntity` instances and ``status`` is ``"success"``.
    On failure, ``entities`` is an empty list and ``status`` is ``"failed"``.
    """

    entities: list[ExtractedEntity] = field(default_factory=list)
    status: Literal["success", "failed"] = "success"
    failure_reason: Optional[str] = None

    @property
    def ok(self) -> bool:
        """True when extraction completed without error."""
        return self.status == "success"


def _normalize_dollar_amount(raw_value: str) -> Optional[str]:
    """Normalize a dollar amount string to 2 decimal places.

    Returns the normalized string representation (e.g. "50.00") if parseable
    and within the valid range (0.01–999999999.99), or None if unparseable
    or out of range (Req 9.4, 9.6).
    """
    # Strip common currency symbols, commas, whitespace
    cleaned = raw_value.strip()
    cleaned = re.sub(r"[,$€£¥\s]", "", cleaned)

    # Handle negative values — dollar amounts should be positive
    if cleaned.startswith("-"):
        return None

    try:
        amount = float(cleaned)
    except (ValueError, OverflowError):
        return None

    # Validate range (Req 9.4)
    if amount < DOLLAR_AMOUNT_MIN or amount > DOLLAR_AMOUNT_MAX:
        return None

    # Normalize to exactly 2 decimal places
    return f"{amount:.2f}"


class EntityExtractor:
    """Extracts named entities from feedback text via Gemini (Req 9).

    Parameters
    ----------
    client:
        Either a :class:`GeminiClient` (its ``generate`` method is used) or any
        callable with the ``GeminiRequest -> GeminiResult`` shape. The callable
        seam lets tests inject a fake transport without a network.
    parser:
        The strict response parser. Defaults to a fresh :class:`ResponseParser`.
    timeout_s:
        Per-request timeout in seconds (Req 9.5). Defaults to 30.
    """

    def __init__(
        self,
        client: Union[GeminiClient, GenerateFn],
        *,
        parser: Optional[ResponseParser] = None,
        timeout_s: int = EXTRACTION_TIMEOUT_SECONDS,
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
        self._timeout_s = timeout_s

    def extract(self, feedback: CanonicalFeedback) -> list[ExtractedEntity]:
        """Extract entities from ``feedback`` text.

        Returns a list of validated :class:`ExtractedEntity` instances (possibly
        empty). On any failure (timeout, service error, parse error), returns an
        empty list — callers can use :meth:`extract_with_status` for richer
        error information.

        Parameters
        ----------
        feedback:
            The canonical feedback record to extract entities from.
        """
        result = self.extract_with_status(feedback)
        return result.entities

    def extract_with_status(
        self, feedback: CanonicalFeedback
    ) -> EntityExtractionResult:
        """Extract entities with full status reporting.

        Returns an :class:`EntityExtractionResult` carrying both the entity list
        and the extraction status ("success" or "failed" with reason).
        """
        request = self._build_request(feedback)
        result = self._generate(request)

        # Transport failure: timeout, auth, exhaustion, or other error (Req 9.5).
        if not result.ok:
            failure = result.failure
            reason = (
                f"entity extraction failed ({failure.kind.value}): {failure.message}"
                if failure is not None
                else "entity extraction failed: transport returned no response"
            )
            logger.warning(
                "Entity extraction failed for feedback %s: %s",
                feedback.feedback_id,
                reason,
            )
            return EntityExtractionResult(
                entities=[],
                status="failed",
                failure_reason=reason,
            )

        # Parse the untrusted JSON response against the entity extraction schema.
        outcome = self._parser.parse_enrichment(
            result.text or "", feedback.feedback_id, EntityExtractionResponse
        )
        if not outcome.ok:
            assert outcome.error is not None
            detail = outcome.error.reason
            if outcome.error.details:
                detail = f"{detail}: {'; '.join(outcome.error.details)}"
            reason = f"entity extraction response invalid: {detail}"
            logger.warning(
                "Entity extraction parse failed for feedback %s: %s",
                feedback.feedback_id,
                reason,
            )
            return EntityExtractionResult(
                entities=[],
                status="failed",
                failure_reason=reason,
            )

        # Apply business rules: filter, normalize, and enforce limits.
        entities = self._apply_rules(outcome.value)
        return EntityExtractionResult(entities=entities, status="success")

    def _apply_rules(
        self, response: EntityExtractionResponse
    ) -> list[ExtractedEntity]:
        """Apply Requirement 9 business rules to raw entity candidates.

        Filters by:
        - Valid entity_type (Req 9.1)
        - Confidence >= 0.5 (Req 9.2)
        - entity_value max 200 chars (Req 9.1)
        - dollar_amount normalization and validation (Req 9.4, 9.6)
        - Max 50 entities (Req 9.1)
        """
        validated: list[ExtractedEntity] = []

        for candidate in response.entities:
            # Skip invalid entity types
            if candidate.entity_type not in VALID_ENTITY_TYPES:
                continue

            # Skip below confidence threshold (Req 9.2)
            if candidate.confidence < MIN_CONFIDENCE_THRESHOLD:
                continue

            # Skip empty entity values
            entity_value = candidate.entity_value.strip()
            if not entity_value:
                continue

            # Truncate entity_value to max 200 chars (Req 9.1)
            if len(entity_value) > MAX_ENTITY_VALUE_LENGTH:
                entity_value = entity_value[:MAX_ENTITY_VALUE_LENGTH]

            # Handle dollar_amount normalization (Req 9.4, 9.6)
            if candidate.entity_type == "dollar_amount":
                normalized = _normalize_dollar_amount(entity_value)
                if normalized is None:
                    # Discard unparseable dollar amounts (Req 9.6)
                    continue
                entity_value = normalized

            validated.append(
                ExtractedEntity(
                    entity_type=candidate.entity_type,  # type: ignore[arg-type]
                    entity_value=entity_value,
                    confidence=candidate.confidence,
                )
            )

            # Enforce max entity count (Req 9.1)
            if len(validated) >= MAX_ENTITIES_PER_RECORD:
                break

        return validated

    def _build_request(self, feedback: CanonicalFeedback) -> GeminiRequest:
        """Build the schema-constrained entity extraction request."""
        system_instruction = (
            "You are a named entity extractor for telecom customer feedback. "
            "Extract entities from the feedback text and classify each into one "
            "of the following entity types: service_area, product_name, "
            "time_reference, dollar_amount, equipment_name, outage_mention, "
            "competitor_mention. For each entity, provide the entity_type, "
            "entity_value (the exact text or normalized form), and a confidence "
            "score between 0.0 and 1.0. For dollar_amount entities, extract the "
            "monetary value as it appears in the text. If no entities are found, "
            "return an empty entities list. Respond strictly as JSON matching the "
            "provided schema."
        )
        contents = json.dumps(
            {
                "instruction": "Extract named entities from the following customer feedback.",
                "entity_types": sorted(VALID_ENTITY_TYPES),
                "feedback_text": feedback.cleaned_text,
            }
        )
        return GeminiRequest(
            record_id=feedback.feedback_id,
            contents=contents,
            response_schema=EntityExtractionResponse,
            system_instruction=system_instruction,
        )


__all__ = [
    "EntityExtractor",
    "EntityExtractionResult",
    "EntityExtractionResponse",
    "EntityCandidate",
    "MAX_ENTITIES_PER_RECORD",
    "MIN_CONFIDENCE_THRESHOLD",
    "MAX_ENTITY_VALUE_LENGTH",
    "EXTRACTION_TIMEOUT_SECONDS",
    "VALID_ENTITY_TYPES",
]
