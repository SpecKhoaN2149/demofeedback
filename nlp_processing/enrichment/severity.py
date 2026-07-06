"""Severity_Scorer: operational-impact scoring for feedback records (task 11.1, Req 7).

The :class:`SeverityScorer` turns a
:class:`~nlp_processing.models.records.FeedbackRecord` into a severity score and
its contributing factors using the Gemini API. It builds a schema-constrained
severity request, hands it to the transport
(:class:`~nlp_processing.transport.client.GeminiClient`), parses the untrusted
JSON via the strict :class:`~nlp_processing.serialization.parser.ResponseParser`,
and then applies the business rules from Requirement 7:

* assign exactly one integer severity in the inclusive range 1..5 together with
  at least one contributing factor of 1..500 characters (Req 7.1, 7.2);
* if the model **completely omits** a severity value, default the score to 1 and
  record a missing-severity note keyed by the record id (Req 7.3);
* if the model produces a severity value that is **present but invalid**
  (non-integer or outside 1..5), reject the record, produce no ``Insight_Record``,
  and record a severity-range error keyed by the record id (Req 7.4);
* if the API does not respond within the timeout (>30s -- surfaced by the
  transport as a ``TIMEOUT``/``EXHAUSTED`` failure), default the score to 1 and
  record a severity-unavailable note keyed by the record id (Req 7.5).

Design / testability
---------------------
Like the :class:`~nlp_processing.enrichment.classifier.Classifier`, the scorer
depends on a *generate function* (``GeminiRequest -> GeminiResult``) rather than
a concrete client, so tests can inject a fake transport that returns canned
responses or failures without a network. A :class:`GeminiClient` instance is
also accepted directly (its ``generate`` method is used).

The shared strict enrichment schema enforces ``severity_score`` in 1..5, which
makes it impossible to distinguish an *omitted* severity (Req 7.3) from a
*present-but-out-of-range* one (Req 7.4). The scorer therefore defines its own
**lenient** severity response schema (``severity_score`` optional and untyped)
and performs the range/type validation itself, so the two cases are handled by
their distinct rules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from ..models.records import FeedbackRecord, SeverityFactor
from ..serialization.parser import ResponseParser
from ..transport.client import GeminiErrorKind, GeminiClient, GeminiRequest, GeminiResult

# The default severity assigned on a non-fatal degradation: an omitted severity
# value (Req 7.3) or an unavailable/timed-out response (Req 7.5).
DEFAULT_SEVERITY: int = 1

# Inclusive bounds for a valid severity score (Req 7.1).
MIN_SEVERITY: int = 1
MAX_SEVERITY: int = 5

# Contributing-factor length bounds (Req 7.2), mirroring SeverityFactor.
MIN_FACTOR_LEN: int = 1
MAX_FACTOR_LEN: int = 500

# Factor synthesized when the model supplies a usable severity (or a defaulted
# one) but no usable contributing factors, so the insight stays well-formed
# (>= 1 factor, Req 7.2).
DEFAULT_FACTOR_TEXT: str = "No contributing factors were provided by the model."


# A callable that performs one transport request. Matches GeminiClient.generate.
GenerateFn = Callable[[GeminiRequest], GeminiResult]

# Transport failure kinds treated as "no response within the timeout window"
# (the >30s / unavailable path, Req 7.5). A timeout is reported directly; an
# exhaustion means retryable failures (incl. repeated timeouts) ran out.
_UNAVAILABLE_KINDS = frozenset({GeminiErrorKind.TIMEOUT, GeminiErrorKind.EXHAUSTED})


class SeverityResponse(BaseModel):
    """Lenient severity-only Gemini response schema.

    Deliberately *not* strict about ``severity_score``: it is optional and
    accepts any JSON value so the scorer can tell apart an omitted value
    (``None`` -- Req 7.3) from a present-but-invalid value (a float, string, or
    out-of-range integer -- Req 7.4), which a strict 1..5 schema could never
    surface. Range/type enforcement is done by the scorer, not the schema.

    ``severity_factors`` is accepted as a free list of arbitrary entries; the
    scorer keeps only well-formed (1..500 char) string factors and synthesizes a
    default when none qualify.
    """

    model_config = ConfigDict(extra="ignore")

    # ``None`` means the field was omitted (or explicitly null) -> Req 7.3.
    severity_score: Optional[Any] = None
    severity_factors: list[Any] = Field(default_factory=list)


@dataclass(frozen=True)
class SeverityError:
    """A severity-range rejection keyed to the originating record (Req 7.4).

    ``kind`` is always ``"severity_range_error"``; ``reason`` carries a
    human-readable, secret-free description of why the record was rejected.
    """

    record_id: str
    reason: str
    kind: str = "severity_range_error"


@dataclass(frozen=True)
class SeverityOutcome:
    """Result of :meth:`SeverityScorer.score`.

    The original ``record`` is always preserved unchanged. On success (including
    the non-fatal default cases) ``severity_score`` is an integer in 1..5,
    ``factors`` is a non-empty tuple of :class:`SeverityFactor`, ``notes`` may
    carry a missing-severity (Req 7.3) or severity-unavailable (Req 7.5) note,
    and ``error`` is ``None``. On a severity-range rejection (Req 7.4)
    ``severity_score`` and ``factors`` are ``None`` and ``error`` carries a
    :class:`SeverityError`; no ``Insight_Record`` should be produced. Use
    :attr:`ok` to discriminate.
    """

    record: FeedbackRecord
    severity_score: Optional[int] = None
    factors: Optional[tuple[SeverityFactor, ...]] = None
    notes: tuple[str, ...] = ()
    error: Optional[SeverityError] = None

    @property
    def ok(self) -> bool:
        """True when scoring succeeded (a severity score is available)."""
        return self.error is None

    @property
    def record_id(self) -> str:
        """The id of the (preserved) feedback record."""
        return self.record.id

    def __post_init__(self) -> None:
        if self.error is None:
            # Success / degraded-default path: a well-formed score + factors.
            if self.severity_score is None or self.factors is None:
                raise ValueError(
                    "a successful SeverityOutcome must carry a score and factors"
                )
            if not (MIN_SEVERITY <= self.severity_score <= MAX_SEVERITY):
                raise ValueError("severity_score must be an integer in 1..5")
            if len(self.factors) == 0:
                raise ValueError("a successful SeverityOutcome needs >= 1 factor")
        else:
            # Rejection path: no insight data is carried (Req 7.4).
            if self.severity_score is not None or self.factors is not None:
                raise ValueError(
                    "a rejected SeverityOutcome must not carry a score or factors"
                )


class SeverityScorer:
    """Assigns an operational-impact severity to feedback records (Req 7).

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

    def score(
        self, record: FeedbackRecord, *, language_code: str = "en"
    ) -> SeverityOutcome:
        """Score ``record`` for severity and gather its contributing factors.

        Builds a schema-constrained request, calls the transport, parses the
        response, and applies the Requirement 7 business rules. The input
        ``record`` is never mutated and is returned on the outcome regardless of
        success, default, or rejection.

        Parameters
        ----------
        language_code:
            ISO 639-1 code for the input language. When not "en", a language
            override clause is prepended to the system instruction (Req 6.1).
            Defaults to "en" (no override).
        """
        request = self._build_request(record, language_code=language_code)
        result = self._generate(request)

        # Req 7.5: no response within the timeout window (>30s) -- and, more
        # broadly, any retry-exhausting unavailability -- defaults the score to
        # 1 with a severity-unavailable note. Any other transport failure is
        # treated the same way (no usable response was obtained).
        if not result.ok:
            failure = result.failure
            kind = failure.kind if failure is not None else None
            detail = (
                f"({kind.value})" if kind is not None else "(no response)"
            )
            note = (
                f"severity-unavailable: no severity response for record "
                f"{record.id} {detail}; defaulted to {DEFAULT_SEVERITY}"
            )
            return self._defaulted_outcome(record, note, factors=())

        # Strictly parse the untrusted JSON against the lenient severity schema.
        outcome = self._parser.parse_enrichment(
            result.text or "", record.id, SeverityResponse
        )
        if not outcome.ok:
            assert outcome.error is not None
            detail = outcome.error.reason
            if outcome.error.details:
                detail = f"{detail}: {'; '.join(outcome.error.details)}"
            # An unparseable/invalid response yields no trustworthy severity
            # value; reject rather than silently defaulting (defaulting is
            # reserved for an explicit omission or an unavailable response).
            return SeverityOutcome(
                record=record,
                error=SeverityError(
                    record_id=record.id,
                    reason=f"severity response invalid: {detail}",
                ),
            )

        return self._apply_rules(record, outcome.value)

    def _apply_rules(
        self, record: FeedbackRecord, response: SeverityResponse
    ) -> SeverityOutcome:
        """Apply the Req 7.1-7.4 rules to a parsed severity response."""
        raw = response.severity_score
        factors = self._extract_factors(response)

        # Req 7.3: severity completely omitted (or null) -> default 1 + note.
        if raw is None:
            note = (
                f"missing-severity: record {record.id} had no severity value; "
                f"defaulted to {DEFAULT_SEVERITY}"
            )
            return self._defaulted_outcome(record, note, factors=factors)

        # Req 7.4: present but non-integer (bool excluded; floats/strings) or
        # out of the 1..5 range -> reject, no insight, severity-range error.
        if isinstance(raw, bool) or not isinstance(raw, int):
            return SeverityOutcome(
                record=record,
                error=SeverityError(
                    record_id=record.id,
                    reason=(
                        f"severity value is non-integer: {raw!r}"
                    ),
                ),
            )
        if not (MIN_SEVERITY <= raw <= MAX_SEVERITY):
            return SeverityOutcome(
                record=record,
                error=SeverityError(
                    record_id=record.id,
                    reason=(
                        f"severity value {raw} is outside the range "
                        f"{MIN_SEVERITY}..{MAX_SEVERITY}"
                    ),
                ),
            )

        # Req 7.1 / 7.2: a well-formed integer severity with >= 1 factor.
        factors = factors or (SeverityFactor(description=DEFAULT_FACTOR_TEXT),)
        return SeverityOutcome(
            record=record, severity_score=raw, factors=factors
        )

    def _defaulted_outcome(
        self,
        record: FeedbackRecord,
        note: str,
        *,
        factors: tuple[SeverityFactor, ...],
    ) -> SeverityOutcome:
        """Build a default-severity (=1) outcome carrying ``note`` (Req 7.3, 7.5).

        Ensures at least one contributing factor is present so the resulting
        insight stays well-formed (Req 7.2).
        """
        factors = factors or (SeverityFactor(description=DEFAULT_FACTOR_TEXT),)
        return SeverityOutcome(
            record=record,
            severity_score=DEFAULT_SEVERITY,
            factors=factors,
            notes=(note,),
        )

    @staticmethod
    def _extract_factors(
        response: SeverityResponse,
    ) -> tuple[SeverityFactor, ...]:
        """Keep only well-formed (1..500 char) string factors from a response.

        Non-string and out-of-length entries are discarded. The result may be
        empty; callers synthesize a default factor when needed (Req 7.2).
        """
        kept: list[SeverityFactor] = []
        for entry in response.severity_factors:
            if not isinstance(entry, str):
                continue
            if MIN_FACTOR_LEN <= len(entry) <= MAX_FACTOR_LEN:
                kept.append(SeverityFactor(description=entry))
        return tuple(kept)

    def _build_request(
        self, record: FeedbackRecord, *, language_code: str = "en"
    ) -> GeminiRequest:
        """Build the schema-constrained severity request for ``record``."""
        from .language_prompts import apply_language_override

        system_instruction = (
            "You are a severity scorer for telecom customer feedback. "
            "Assign exactly one integer severity score from 1 to 5 inclusive, "
            "where 5 is the most operationally severe. Provide at least one "
            "short contributing factor (1 to 500 characters) explaining the "
            "score. Respond strictly as JSON matching the provided schema."
        )
        system_instruction = apply_language_override(
            system_instruction, language_code
        )
        contents = json.dumps(
            {
                "instruction": (
                    "Score the operational severity of the following customer "
                    "feedback and list the contributing factors."
                ),
                "feedback_text": record.cleaned_text,
            }
        )
        return GeminiRequest(
            record_id=record.id,
            contents=contents,
            response_schema=SeverityResponse,
            system_instruction=system_instruction,
        )


__all__ = [
    "SeverityScorer",
    "SeverityOutcome",
    "SeverityError",
    "SeverityResponse",
    "DEFAULT_SEVERITY",
]
