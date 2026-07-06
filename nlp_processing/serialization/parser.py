"""Strict Response_Parser for untrusted Gemini JSON (task 3.1).

The ``ResponseParser`` maps raw Gemini response text to a typed enrichment
object, validating every required field, type, and range against a pydantic
schema (default :class:`EnrichmentResponse`). Parsing is **all-or-nothing**
(Req 4.2): on invalid JSON, a missing required field, an unknown field, or any
out-of-range / wrong-type value, the parser records a parse error keyed by the
``record_id`` and produces no partial object.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from .schema import EnrichmentResponse

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass(frozen=True)
class ParseError:
    """A parse failure keyed to the originating Feedback_Record (Req 4.2)."""

    record_id: str
    reason: str
    # Per-field detail messages when available (e.g. pydantic validation
    # errors). Empty for invalid-JSON failures.
    details: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ParseOutcome(Generic[SchemaT]):
    """Result of :meth:`ResponseParser.parse_enrichment`.

    Exactly one of ``value`` (success) or ``error`` (failure) is populated,
    never both and never neither. Use :attr:`ok` to discriminate.
    """

    record_id: str
    value: SchemaT | None = None
    error: ParseError | None = None

    @property
    def ok(self) -> bool:
        """True when parsing succeeded and a typed object is available."""
        return self.error is None

    def __post_init__(self) -> None:
        # Enforce the all-or-nothing invariant at construction time.
        if (self.value is None) == (self.error is None):
            raise ValueError(
                "ParseOutcome must carry exactly one of value or error"
            )


class ResponseParser:
    """Parses and strictly schema-validates Gemini enrichment responses."""

    def parse_enrichment(
        self,
        raw_json: str,
        record_id: str,
        schema: type[SchemaT] = EnrichmentResponse,
    ) -> ParseOutcome[SchemaT]:
        """Parse ``raw_json`` and validate it against ``schema``.

        On success returns a :class:`ParseOutcome` carrying the validated typed
        object. On any violation (invalid JSON, missing required field, unknown
        field, wrong type, or out-of-range value) returns a
        :class:`ParseOutcome` carrying a :class:`ParseError` keyed by
        ``record_id`` and no partial object (Req 4.2).
        """
        # Step 1: JSON syntax. Reject anything that is not valid JSON.
        try:
            parsed = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError) as exc:
            return ParseOutcome(
                record_id=record_id,
                error=ParseError(
                    record_id=record_id,
                    reason=f"invalid JSON: {exc}",
                ),
            )

        # Step 2: strict schema validation of every required field, type, and
        # range. ``model_validate`` raises if anything is missing, unexpected,
        # mistyped, or out of range.
        try:
            value = schema.model_validate(parsed)
        except ValidationError as exc:
            details = tuple(
                f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                for err in exc.errors()
            )
            return ParseOutcome(
                record_id=record_id,
                error=ParseError(
                    record_id=record_id,
                    reason="schema validation failed",
                    details=details,
                ),
            )

        return ParseOutcome(record_id=record_id, value=value)


__all__ = [
    "ResponseParser",
    "ParseOutcome",
    "ParseError",
]
