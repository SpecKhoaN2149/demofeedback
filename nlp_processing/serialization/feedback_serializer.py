"""FeedbackAnalysis serializer: deterministic JSON with round-trip fidelity.

This module provides canonical JSON serialization and strict deserialization
for :class:`FeedbackAnalysis` records (Requirements 23.1–23.6).

Serialization produces **deterministic** output:
- Object keys sorted lexicographically
- Compact separators (",", ":")
- Floating-point values with a maximum of 6 decimal digits of precision
- Byte-for-byte identical output for the same input record

Deserialization validates all schema constraints:
- sentiment_score in [-1.0, +1.0]
- priority_score in [0.0, 1.0]
- sentiment_label in {"positive", "neutral", "negative"}
- priority_level in {"low", "medium", "high", "critical"}
- intent in valid IntentType values
- processed_at as ISO 8601 UTC timestamp
- entities with confidence in [0.5, 1.0] and valid entity_type

Malformed JSON is rejected with a parsing error (Req 23.5).
Schema constraint violations are rejected with field-specific errors (Req 23.4).
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from pydantic import ValidationError

from ..models.feedback_routing import FeedbackAnalysis


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class SerializationError(Exception):
    """Error raised when serialization fails."""

    def __init__(self, feedback_id: str, reason: str) -> None:
        self.feedback_id = feedback_id
        self.reason = reason
        super().__init__(f"[{feedback_id}] {reason}")


class DeserializationError(Exception):
    """Error raised when deserialization fails.

    Carries field-specific detail messages when available.
    """

    def __init__(self, reason: str, details: tuple[str, ...] = ()) -> None:
        self.reason = reason
        self.details = details
        super().__init__(reason if not details else f"{reason}: {details}")


# ---------------------------------------------------------------------------
# Float precision helper
# ---------------------------------------------------------------------------

# ISO 8601 UTC pattern: YYYY-MM-DDTHH:MM:SSZ or with fractional seconds
_ISO8601_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$"
)


def _round_float(value: float, precision: int = 6) -> float:
    """Round a float to the given number of decimal digits."""
    return round(value, precision)


# ---------------------------------------------------------------------------
# Canonical JSON serialization
# ---------------------------------------------------------------------------


def _serialize_value(value: Any) -> Any:
    """Recursively transform a value for JSON serialization.

    Replaces floats with their precision-formatted string representation
    wrapped in a sentinel that we can replace after json.dumps.
    """
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None  # NaN/Inf are not valid JSON
        return _round_float(value, 6)
    elif isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_serialize_value(item) for item in value]
    return value


def _canonical_json_with_precision(data: dict[str, Any]) -> str:
    """Produce canonical JSON with sorted keys, compact separators, and
    6-decimal float precision.

    The approach: pre-round all floats to 6 decimals, then use json.dumps
    which will naturally omit trailing zeros in its default float formatting.
    We then post-process to ensure deterministic float output.
    """
    # Pre-process to round floats
    processed = _serialize_value(data)

    # Use a custom default handler and manual float formatting
    # json.dumps with sort_keys and compact separators
    result = json.dumps(
        processed,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return result


# ---------------------------------------------------------------------------
# FeedbackAnalysisSerializer
# ---------------------------------------------------------------------------


class FeedbackAnalysisSerializer:
    """Serializes and deserializes FeedbackAnalysis records.

    Serialization produces deterministic canonical JSON (Req 23.2):
    - Sorted keys
    - Compact separators (",", ":")
    - Floats rounded to max 6 decimal digits

    Deserialization validates all constraints (Req 23.3) and rejects:
    - Malformed JSON with a parsing error (Req 23.5)
    - Schema violations with field-specific errors (Req 23.4)
    """

    def serialize(self, record: FeedbackAnalysis) -> str:
        """Serialize a FeedbackAnalysis record to deterministic canonical JSON.

        Args:
            record: A valid FeedbackAnalysis instance.

        Returns:
            A canonical JSON string with sorted keys, compact separators,
            and floats rounded to 6-decimal precision.

        Raises:
            SerializationError: If the record cannot be serialized.
        """
        try:
            # Use Pydantic's model_dump with mode="json" for JSON-safe types
            data = record.model_dump(mode="json")
        except Exception as exc:
            raise SerializationError(
                feedback_id=getattr(record, "feedback_id", "<unknown>"),
                reason=f"failed to dump model: {exc}",
            ) from exc

        return _canonical_json_with_precision(data)

    def deserialize(self, json_str: str) -> FeedbackAnalysis:
        """Deserialize a JSON string into a FeedbackAnalysis record.

        Validates all schema constraints including:
        - sentiment_score in [-1.0, +1.0]
        - priority_score in [0.0, 1.0]
        - sentiment_label in {"positive", "neutral", "negative"}
        - priority_level in {"low", "medium", "high", "critical"}
        - intent in valid IntentType values
        - processed_at as ISO 8601 UTC timestamp
        - entity confidence in [0.5, 1.0], valid entity_type

        Args:
            json_str: A JSON string to deserialize.

        Returns:
            A validated FeedbackAnalysis instance.

        Raises:
            DeserializationError: If the JSON is malformed or violates schema
                constraints.
        """
        # Step 1: Parse JSON syntax
        try:
            parsed = json.loads(json_str)
        except (json.JSONDecodeError, TypeError) as exc:
            raise DeserializationError(
                reason=f"invalid JSON: {exc}",
            ) from exc

        if not isinstance(parsed, dict):
            raise DeserializationError(
                reason="invalid JSON: expected a JSON object at top level",
            )

        # Step 2: Validate timestamp format before Pydantic validation
        # (Pydantic doesn't enforce ISO 8601 format on str fields)
        timestamp_errors: list[str] = []
        processed_at = parsed.get("processed_at")
        if processed_at is not None and isinstance(processed_at, str):
            if not _ISO8601_UTC_RE.match(processed_at):
                timestamp_errors.append(
                    "processed_at: must be a valid ISO 8601 UTC timestamp "
                    "(format: YYYY-MM-DDTHH:MM:SSZ)"
                )

        # Step 3: Strict schema validation via Pydantic
        try:
            record = FeedbackAnalysis.model_validate(parsed)
        except ValidationError as exc:
            details = tuple(
                f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                for err in exc.errors()
            )
            # Combine with any timestamp errors
            all_details = tuple(timestamp_errors) + details
            raise DeserializationError(
                reason="schema validation failed",
                details=all_details,
            ) from exc

        # If Pydantic validation passed but timestamp format is wrong,
        # still reject (Pydantic accepts any string for str fields)
        if timestamp_errors:
            raise DeserializationError(
                reason="schema validation failed",
                details=tuple(timestamp_errors),
            )

        return record


__all__ = [
    "FeedbackAnalysisSerializer",
    "SerializationError",
    "DeserializationError",
]
