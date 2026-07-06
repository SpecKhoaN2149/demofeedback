"""Per-record Gemini enrichment response schema (task 3.1).

This module defines the pydantic model the ``Response_Parser`` validates
untrusted Gemini JSON against, mirroring the design's
"Gemini Enrichment Response Schema (per record)" JSON Schema (Req 4.1, 11.1).

The schema is intentionally *self-contained* and minimal: it validates the raw
shape of a Gemini enrichment response only. Business rules that transform this
raw response into an ``InsightRecord`` (unknown-theme discarding, missing-field
defaults, review flags, etc.) live in the enrichment layer, not here.

Validation is strict: every required field must be present, each field must
match its declared type, numeric ranges are enforced, and unexpected
properties are rejected (``additionalProperties: false``). This makes the
``Response_Parser`` all-or-nothing (Req 4.2).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ..models.types import SentimentValue

# A severity contributing factor is free text of 1..500 characters
# (mirrors SeverityFactor.description; Req 7.2). Kept as a plain constrained
# string here because the raw Gemini schema models factors as strings.
SeverityFactorText = Annotated[str, StringConstraints(min_length=1, max_length=500)]


class EnrichmentTheme(BaseModel):
    """A single ``{theme, confidence}`` entry in a Gemini enrichment response.

    ``theme`` is validated as an arbitrary non-empty string here, not against
    the configured theme set: the raw response schema permits any string, and
    discarding out-of-set labels is the Classifier's responsibility (Req 5.6),
    not the parser's.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    theme: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class EnrichmentResponse(BaseModel):
    """The strict per-record Gemini enrichment response schema (Req 4.1).

    Field types and ranges match the design's JSON Schema:

    - ``themes``: at least one ``{theme, confidence}`` object
    - ``sentiment``: one of ``positive`` | ``neutral`` | ``negative``
    - ``sentiment_confidence``: number in 0.0..1.0
    - ``severity_score``: integer in 1..5
    - ``severity_factors``: at least one string of 1..500 characters

    ``extra="forbid"`` enforces ``additionalProperties: false`` and ``strict``
    rejects type coercions (e.g. a string where a number is expected).
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    themes: list[EnrichmentTheme] = Field(min_length=1)
    sentiment: SentimentValue
    sentiment_confidence: float = Field(ge=0.0, le=1.0)
    severity_score: int = Field(ge=1, le=5)
    severity_factors: list[SeverityFactorText] = Field(min_length=1)


__all__ = [
    "EnrichmentTheme",
    "EnrichmentResponse",
    "SeverityFactorText",
]
