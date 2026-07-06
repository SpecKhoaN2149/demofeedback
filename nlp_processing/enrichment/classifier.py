"""Classifier: theme assignment for feedback records (task 9.1, Req 5).

The :class:`Classifier` turns a :class:`~nlp_processing.models.records.FeedbackRecord`
into a set of :class:`~nlp_processing.models.records.ThemeAssignment`s using the
Gemini API. It builds a schema-constrained classification request, hands it to
the transport (:class:`~nlp_processing.transport.client.GeminiClient`), parses
the untrusted JSON via the strict :class:`~nlp_processing.serialization.parser.ResponseParser`,
and then applies the business rules from Requirement 5:

* assign at least one theme from the configured set, each with a confidence in
  the inclusive range 0.0..1.0 (Req 5.1, 5.2, 5.3);
* assign **all** configured-set themes whose confidence is at least
  :data:`THEME_CONFIDENCE_THRESHOLD` (0.5) (Req 5.4);
* if no configured theme qualifies -- because none reach the threshold or the
  model indicates none apply -- assign the catch-all theme ``other`` (Req 5.5);
* discard any theme label that is not in the configured theme set, falling back
  to ``other`` when nothing else qualifies (Req 5.6);
* on API unavailability or timeout (>30s, enforced by the transport), leave the
  record unclassified, preserve the original record unchanged, and attach a
  classification-failure error (Req 5.7).

Design / testability
---------------------
The classifier depends on a *generate function* (``GeminiRequest -> GeminiResult``)
rather than a concrete client, so tests inject a fake that returns canned
responses or failures without a network. A :class:`GeminiClient` instance is
also accepted directly (its ``generate`` method is used). The response schema is
classification-specific (themes only) and defined here so the classifier stays
independently callable; it does not touch the shared enrichment schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from ..models.records import FeedbackRecord, ThemeAssignment
from ..models.types import DEFAULT_THEME_SET, ThemeLabel
from ..serialization.parser import ResponseParser
from ..transport.client import GeminiClient, GeminiRequest, GeminiResult

# A configured theme qualifies for assignment when its confidence is at least
# this threshold (Req 5.4, 5.5). This is distinct from the review threshold
# (default 0.70) used for review flagging elsewhere.
THEME_CONFIDENCE_THRESHOLD: float = 0.5

# The catch-all theme assigned when no configured theme qualifies (Req 5.5, 5.6).
OTHER_THEME: ThemeLabel = "other"

# Confidence attached to the system-assigned ``other`` fallback. The fallback is
# a deterministic system decision (no configured theme qualified), so it is
# recorded with full confidence rather than a model-derived score.
OTHER_FALLBACK_CONFIDENCE: float = 1.0


# A callable that performs one transport request. Matches GeminiClient.generate.
GenerateFn = Callable[[GeminiRequest], GeminiResult]


class ClassificationTheme(BaseModel):
    """A single ``{theme, confidence}`` candidate in a classification response.

    ``theme`` is validated only as a non-empty string here: the raw model
    output may contain any label, and discarding out-of-set labels is the
    classifier's responsibility (Req 5.6), not the schema's.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    theme: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class ClassificationResponse(BaseModel):
    """Focused, classification-only Gemini response schema (themes only).

    Kept separate from the full enrichment schema so the classifier can be
    called and validated independently. ``themes`` carries the model's
    candidate themes with confidences; an empty list is permitted and signals
    that the model judged no theme to apply (handled by falling back to
    ``other``, Req 5.5).
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    themes: list[ClassificationTheme] = Field(default_factory=list)


@dataclass(frozen=True)
class ClassificationError:
    """A classification failure keyed to the originating record (Req 5.7).

    ``kind`` is always ``"classification_failure"``; ``reason`` carries a
    human-readable, secret-free description of the cause (transport failure or
    unparseable/invalid response).
    """

    record_id: str
    reason: str
    kind: str = "classification_failure"


@dataclass(frozen=True)
class ClassificationOutcome:
    """Result of :meth:`Classifier.classify`.

    The original ``record`` is always preserved unchanged (Req 5.7). On success
    ``themes`` is a non-empty tuple of :class:`ThemeAssignment`s and ``error``
    is ``None``; on failure ``themes`` is ``None`` and ``error`` carries a
    :class:`ClassificationError`. Use :attr:`ok` to discriminate.
    """

    record: FeedbackRecord
    themes: Optional[tuple[ThemeAssignment, ...]] = None
    error: Optional[ClassificationError] = None

    @property
    def ok(self) -> bool:
        """True when classification succeeded and themes are available."""
        return self.error is None

    @property
    def record_id(self) -> str:
        """The id of the (preserved) feedback record."""
        return self.record.id

    def __post_init__(self) -> None:
        # Exactly one of themes / error must be populated.
        if (self.themes is None) == (self.error is None):
            raise ValueError(
                "ClassificationOutcome must carry exactly one of themes or error"
            )
        if self.themes is not None and len(self.themes) == 0:
            raise ValueError("a successful classification must assign >= 1 theme")


class Classifier:
    """Assigns themes to feedback records via Gemini (Req 5).

    Parameters
    ----------
    client:
        Either a :class:`GeminiClient` (its ``generate`` method is used) or any
        callable with the ``GeminiRequest -> GeminiResult`` shape. The callable
        seam lets tests inject a fake transport without a network.
    theme_set:
        The configured set of allowed theme labels (Req 5.2). Defaults to the
        seven standard themes. Labels outside this set are discarded (Req 5.6).
    parser:
        The strict response parser. Defaults to a fresh :class:`ResponseParser`.
    threshold:
        Minimum confidence for a configured theme to be assigned (Req 5.4).
        Defaults to :data:`THEME_CONFIDENCE_THRESHOLD` (0.5).
    """

    def __init__(
        self,
        client: Union[GeminiClient, GenerateFn],
        theme_set: Iterable[str] = DEFAULT_THEME_SET,
        *,
        parser: Optional[ResponseParser] = None,
        threshold: float = THEME_CONFIDENCE_THRESHOLD,
    ) -> None:
        if hasattr(client, "generate"):
            self._generate: GenerateFn = client.generate  # type: ignore[assignment]
        elif callable(client):
            self._generate = client
        else:  # pragma: no cover - defensive guard
            raise TypeError(
                "client must be a GeminiClient or a GeminiRequest->GeminiResult callable"
            )

        self.theme_set: frozenset[str] = frozenset(theme_set)
        if not self.theme_set:
            raise ValueError("theme_set must contain at least one theme")
        self.threshold = threshold
        self._parser = parser or ResponseParser()

    def classify(
        self, record: FeedbackRecord, *, language_code: str = "en"
    ) -> ClassificationOutcome:
        """Classify ``record`` into one or more configured themes.

        Builds a schema-constrained request, calls the transport, parses the
        response, and applies the Requirement 5 business rules. The input
        ``record`` is never mutated and is returned on the outcome regardless of
        success or failure (Req 5.7).

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
        # In every case the record is left unclassified and preserved (Req 5.7).
        if not result.ok:
            failure = result.failure
            reason = (
                f"classification failed ({failure.kind.value}): {failure.message}"
                if failure is not None
                else "classification failed: transport returned no response"
            )
            return ClassificationOutcome(
                record=record,
                error=ClassificationError(record_id=record.id, reason=reason),
            )

        # Strictly parse the untrusted JSON against the classification schema.
        outcome = self._parser.parse_enrichment(
            result.text or "", record.id, ClassificationResponse
        )
        if not outcome.ok:
            assert outcome.error is not None
            detail = outcome.error.reason
            if outcome.error.details:
                detail = f"{detail}: {'; '.join(outcome.error.details)}"
            return ClassificationOutcome(
                record=record,
                error=ClassificationError(
                    record_id=record.id,
                    reason=f"classification response invalid: {detail}",
                ),
            )

        themes = self._select_themes(outcome.value)
        return ClassificationOutcome(record=record, themes=themes)

    def _select_themes(
        self, response: ClassificationResponse
    ) -> tuple[ThemeAssignment, ...]:
        """Apply the theme-selection rules to a parsed response (Req 5.4-5.6).

        Discards labels outside the configured set (Req 5.6), keeps configured
        themes whose confidence is >= the threshold (Req 5.4), and falls back to
        ``other`` when nothing qualifies (Req 5.5). Duplicate labels are
        de-duplicated, keeping the highest confidence seen for each label.
        """
        best_confidence: dict[str, float] = {}
        for candidate in response.themes:
            # Req 5.6: discard any label outside the configured theme set.
            if candidate.theme not in self.theme_set:
                continue
            # Req 5.4: only themes meeting the threshold are assigned.
            if candidate.confidence < self.threshold:
                continue
            prior = best_confidence.get(candidate.theme)
            if prior is None or candidate.confidence > prior:
                best_confidence[candidate.theme] = candidate.confidence

        if not best_confidence:
            # Req 5.5 / 5.6: nothing qualified -> assign the catch-all `other`.
            return (
                ThemeAssignment(
                    theme=OTHER_THEME, confidence=OTHER_FALLBACK_CONFIDENCE
                ),
            )

        # Deterministic order: highest confidence first, then label ascending.
        ordered = sorted(
            best_confidence.items(), key=lambda item: (-item[1], item[0])
        )
        return tuple(
            ThemeAssignment(theme=theme, confidence=confidence)
            for theme, confidence in ordered
        )

    def _build_request(
        self, record: FeedbackRecord, *, language_code: str = "en"
    ) -> GeminiRequest:
        """Build the schema-constrained classification request for ``record``."""
        from .language_prompts import apply_language_override

        theme_list = ", ".join(sorted(self.theme_set))
        system_instruction = (
            "You are a classifier for telecom customer feedback. "
            "Classify the feedback into one or more themes drawn ONLY from the "
            f"configured theme set: {theme_list}. "
            "For each applicable theme, return its label and a confidence score "
            "between 0.0 and 1.0. If no theme applies, return an empty themes "
            "list. Respond strictly as JSON matching the provided schema."
        )
        system_instruction = apply_language_override(
            system_instruction, language_code
        )
        contents = json.dumps(
            {
                "instruction": "Classify the following customer feedback by theme.",
                "allowed_themes": sorted(self.theme_set),
                "feedback_text": record.cleaned_text,
            }
        )
        return GeminiRequest(
            record_id=record.id,
            contents=contents,
            response_schema=ClassificationResponse,
            system_instruction=system_instruction,
        )


__all__ = [
    "Classifier",
    "ClassificationOutcome",
    "ClassificationError",
    "ClassificationResponse",
    "ClassificationTheme",
    "THEME_CONFIDENCE_THRESHOLD",
    "OTHER_THEME",
]
