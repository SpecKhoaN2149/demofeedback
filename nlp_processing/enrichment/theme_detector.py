"""Theme_Detector: business-category assignment for feedback routing (task 5.4).

The :class:`ThemeDetector` maps a
:class:`~nlp_processing.models.feedback_routing.CanonicalFeedback` record to a
:class:`~nlp_processing.models.feedback_routing.ThemeResult` containing a
primary_theme and optional secondary_theme drawn from the
:data:`~nlp_processing.models.feedback_routing.ThemeCategory` set.

Business rules (Requirement 5):
    * Assign a primary_theme from ThemeCategory (Req 5.1).
    * Optionally assign a distinct secondary_theme (Req 5.2).
    * When confidence < 0.3, assign primary_theme as "unclassified" (Req 5.3).
    * Store results on the feedback_analysis record (Req 5.4).
    * Weight customer-provided selected_category alongside NLP classification
      to produce the final primary_theme (Req 5.5).

Design / testability
---------------------
Like the existing :class:`~nlp_processing.enrichment.classifier.Classifier`,
the detector depends on a *generate function* (``GeminiRequest -> GeminiResult``)
rather than a concrete client, so tests inject a fake that returns canned
responses or failures without the network. A :class:`GeminiClient` instance is
also accepted directly (its ``generate`` method is used).
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Optional, Union, get_args

from pydantic import BaseModel, ConfigDict, Field

from ..models.feedback_routing import (
    CanonicalFeedback,
    ThemeCategory,
    ThemeResult,
)
from ..serialization.parser import ResponseParser
from ..transport.client import GeminiClient, GeminiRequest, GeminiResult

logger = logging.getLogger(__name__)

# The valid theme categories, derived from the Literal type so they stay in sync.
VALID_THEME_CATEGORIES: frozenset[str] = frozenset(get_args(ThemeCategory))

# Confidence threshold below which the theme is "unclassified" (Req 5.3).
THEME_CONFIDENCE_THRESHOLD: float = 0.3

# Weight given to customer-provided selected_category when blending with NLP
# classification (Req 5.5). A value of 0.4 means the customer signal contributes
# 40% of the final confidence for that theme.
CUSTOMER_CATEGORY_WEIGHT: float = 0.4

# NLP model weight (complement of customer weight).
NLP_WEIGHT: float = 1.0 - CUSTOMER_CATEGORY_WEIGHT

# Fallback theme when confidence is below threshold.
UNCLASSIFIED_THEME: str = "unclassified"

# A callable that performs one transport request. Matches GeminiClient.generate.
GenerateFn = Callable[[GeminiRequest], GeminiResult]


class ThemeCandidate(BaseModel):
    """A single theme candidate returned by the model."""

    model_config = ConfigDict(extra="forbid", strict=True)

    theme: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class ThemeDetectionResponse(BaseModel):
    """Gemini response schema for theme detection.

    The model returns a list of candidate themes with confidences. The
    ThemeDetector selects the primary and optional secondary from this list
    after applying business rules.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    themes: list[ThemeCandidate] = Field(default_factory=list)


class ThemeDetector:
    """Assigns business-category themes to feedback records via Gemini (Req 5).

    Parameters
    ----------
    client:
        Either a :class:`GeminiClient` (its ``generate`` method is used) or any
        callable with the ``GeminiRequest -> GeminiResult`` shape.
    parser:
        The strict response parser. Defaults to a fresh :class:`ResponseParser`.
    confidence_threshold:
        Minimum confidence for a theme to be considered valid (Req 5.3).
        Defaults to :data:`THEME_CONFIDENCE_THRESHOLD` (0.3).
    customer_weight:
        Weight given to the customer-provided selected_category (Req 5.5).
        Defaults to :data:`CUSTOMER_CATEGORY_WEIGHT` (0.4).
    """

    def __init__(
        self,
        client: Union[GeminiClient, GenerateFn],
        *,
        parser: Optional[ResponseParser] = None,
        confidence_threshold: float = THEME_CONFIDENCE_THRESHOLD,
        customer_weight: float = CUSTOMER_CATEGORY_WEIGHT,
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
        self._confidence_threshold = confidence_threshold
        self._customer_weight = customer_weight
        self._nlp_weight = 1.0 - customer_weight

    def detect(self, feedback: CanonicalFeedback) -> ThemeResult:
        """Detect the business-category theme(s) of ``feedback``.

        Builds a schema-constrained request, calls the transport, parses the
        response, and applies the Requirement 5 business rules. Returns a
        :class:`ThemeResult` with primary_theme and optional secondary_theme.

        On transport failure or parse error, returns "unclassified" with
        confidence 0.0 as a graceful fallback.
        """
        # Extract customer-provided category if present in metadata.
        selected_category = self._get_selected_category(feedback)

        request = self._build_request(feedback, selected_category)
        result = self._generate(request)

        # Transport failure fallback.
        if not result.ok:
            failure = result.failure
            reason = (
                f"theme detection failed ({failure.kind.value}): {failure.message}"
                if failure is not None
                else "theme detection failed: transport returned no response"
            )
            logger.warning(
                "Theme detection failed for record %s: %s",
                feedback.feedback_id,
                reason,
            )
            return ThemeResult(
                primary_theme=UNCLASSIFIED_THEME,
                secondary_theme=None,
                confidence=0.0,
            )

        # Parse the response.
        outcome = self._parser.parse_enrichment(
            result.text or "", feedback.feedback_id, ThemeDetectionResponse
        )
        if not outcome.ok:
            logger.warning(
                "Theme detection response invalid for record %s",
                feedback.feedback_id,
            )
            return ThemeResult(
                primary_theme=UNCLASSIFIED_THEME,
                secondary_theme=None,
                confidence=0.0,
            )

        return self._apply_rules(outcome.value, selected_category)

    def _apply_rules(
        self,
        response: ThemeDetectionResponse,
        selected_category: Optional[str],
    ) -> ThemeResult:
        """Apply Requirement 5 business rules to a parsed response.

        Steps:
        1. Filter to valid ThemeCategory values only.
        2. Weight customer-provided category alongside NLP results (Req 5.5).
        3. Select primary (highest confidence) and secondary (second highest).
        4. If primary confidence < threshold, assign "unclassified" (Req 5.3).
        """
        # Build confidence map from NLP results (only valid categories).
        nlp_confidences: dict[str, float] = {}
        for candidate in response.themes:
            theme = candidate.theme
            if theme not in VALID_THEME_CATEGORIES:
                continue
            # Keep highest confidence if duplicates exist.
            existing = nlp_confidences.get(theme, 0.0)
            if candidate.confidence > existing:
                nlp_confidences[theme] = candidate.confidence

        # Blend with customer-provided category (Req 5.5).
        final_confidences = self._blend_with_customer_category(
            nlp_confidences, selected_category
        )

        # Sort by confidence descending for selection.
        sorted_themes = sorted(
            final_confidences.items(), key=lambda item: -item[1]
        )

        if not sorted_themes:
            # No valid themes from model or customer.
            return ThemeResult(
                primary_theme=UNCLASSIFIED_THEME,
                secondary_theme=None,
                confidence=0.0,
            )

        primary_theme, primary_confidence = sorted_themes[0]

        # Req 5.3: confidence below threshold → "unclassified".
        if primary_confidence < self._confidence_threshold:
            return ThemeResult(
                primary_theme=UNCLASSIFIED_THEME,
                secondary_theme=None,
                confidence=primary_confidence,
            )

        # Req 5.2: optional secondary_theme (distinct from primary).
        secondary_theme: Optional[str] = None
        if len(sorted_themes) > 1:
            sec_theme, sec_confidence = sorted_themes[1]
            # Only assign secondary if it also meets the threshold.
            if sec_confidence >= self._confidence_threshold:
                secondary_theme = sec_theme

        return ThemeResult(
            primary_theme=primary_theme,
            secondary_theme=secondary_theme,
            confidence=primary_confidence,
        )

    def _blend_with_customer_category(
        self,
        nlp_confidences: dict[str, float],
        selected_category: Optional[str],
    ) -> dict[str, float]:
        """Blend NLP-derived confidences with the customer-provided category.

        When a customer provides a selected_category (Req 5.5), we weight it
        alongside the NLP classification:
        - If NLP also identified that category: blended = nlp_weight * nlp_conf + customer_weight * 1.0
        - If NLP did not identify it: add the category with confidence = customer_weight * 1.0
        - Other NLP categories are scaled by nlp_weight.
        """
        if selected_category is None or selected_category not in VALID_THEME_CATEGORIES:
            return nlp_confidences

        blended: dict[str, float] = {}

        for theme, conf in nlp_confidences.items():
            if theme == selected_category:
                # Blend: NLP confidence weighted + customer full confidence weighted.
                blended[theme] = min(
                    1.0, self._nlp_weight * conf + self._customer_weight * 1.0
                )
            else:
                # Scale NLP-only themes by NLP weight.
                blended[theme] = self._nlp_weight * conf

        # If customer category wasn't in NLP results, add it.
        if selected_category not in blended:
            blended[selected_category] = self._customer_weight * 1.0

        return blended

    def _get_selected_category(self, feedback: CanonicalFeedback) -> Optional[str]:
        """Extract customer-provided selected_category from feedback metadata.

        The selected_category is stored in metadata by the preprocessor when
        the original source was a WidgetFeedback with a selected_category field.
        """
        category = feedback.metadata.get("selected_category")
        if category is not None and category in VALID_THEME_CATEGORIES:
            return category
        return None

    def _build_request(
        self,
        feedback: CanonicalFeedback,
        selected_category: Optional[str],
    ) -> GeminiRequest:
        """Build the schema-constrained theme detection request."""
        theme_list = ", ".join(sorted(VALID_THEME_CATEGORIES))
        system_instruction = (
            "You are a theme classifier for telecom customer feedback. "
            "Classify the feedback into one or more business categories drawn "
            f"ONLY from the following set: {theme_list}. "
            "For each applicable theme, return its label and a confidence score "
            "between 0.0 and 1.0. Return at most 3 themes. If no theme applies "
            "with reasonable confidence, return an empty themes list. "
            "Respond strictly as JSON matching the provided schema."
        )

        contents_data: dict[str, object] = {
            "instruction": "Classify the following customer feedback by business category/theme.",
            "allowed_themes": sorted(VALID_THEME_CATEGORIES),
            "feedback_text": feedback.cleaned_text,
        }

        # Include customer-provided category as a hint (Req 5.5).
        if selected_category is not None:
            contents_data["customer_selected_category"] = selected_category
            contents_data["category_hint"] = (
                f"The customer selected '{selected_category}' as their category. "
                "Consider this alongside your own analysis."
            )

        contents = json.dumps(contents_data)

        return GeminiRequest(
            record_id=feedback.feedback_id,
            contents=contents,
            response_schema=ThemeDetectionResponse,
            system_instruction=system_instruction,
        )


__all__ = [
    "ThemeDetector",
    "ThemeDetectionResponse",
    "ThemeCandidate",
    "VALID_THEME_CATEGORIES",
    "THEME_CONFIDENCE_THRESHOLD",
    "CUSTOMER_CATEGORY_WEIGHT",
    "UNCLASSIFIED_THEME",
]
