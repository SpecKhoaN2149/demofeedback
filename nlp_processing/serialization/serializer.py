"""Response_Serializer: canonical JSON serialization (Req 4.3, 4.4, 4.6).

This module emits **canonical JSON** for storage and downstream consumption.
Canonical JSON is defined as:

- object keys sorted lexicographically,
- insignificant whitespace removed (compact separators),
- stable number formatting,

so that the JSON round-trip property (Req 4.6) is byte-for-byte checkable and
serializing equal values always yields identical bytes.

Rules implemented here (design "Response_Serializer" section):

- Serialize only schema-valid, complete :class:`InsightRecord` values (Req
  4.3). An invalid or incomplete record produces a serialization error keyed by
  its ``feedback_id`` and no output for that record (Req 4.4).
- :meth:`ResponseSerializer.serialize_batch` serializes the published
  :class:`BatchOutput` schema as canonical JSON (Req 10.4).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..models import BatchOutput, InsightRecord


def canonical_json(data: Any) -> str:
    """Render a JSON-compatible value as canonical JSON.

    The output has lexicographically sorted object keys, no insignificant
    whitespace, and stable number formatting. Rendering is deterministic, so
    equal inputs always produce byte-for-byte identical output (Req 4.6).

    ``ensure_ascii`` is disabled so interior text content is preserved verbatim;
    combined with sorted keys and compact separators this makes the rendering
    idempotent under parse-then-serialize.
    """
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


class SerializeOutcome(BaseModel):
    """The outcome of serializing a single :class:`InsightRecord`.

    On success ``json_text`` holds the canonical JSON and ``errors`` is empty.
    On failure ``json_text`` is ``None`` and ``errors`` maps the offending
    record's ``feedback_id`` to a human-readable reason (Req 4.4).
    """

    json_text: str | None = None
    errors: dict[str, str] = Field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when serialization produced output and recorded no error."""
        return self.json_text is not None and not self.errors


class ResponseSerializer:
    """Serializes internal data objects into canonical JSON.

    The serializer is stateless; a single instance may be reused across records
    and batches.
    """

    def serialize_insight(self, insight: InsightRecord) -> SerializeOutcome:
        """Serialize a single ``InsightRecord`` to canonical JSON.

        Re-validates the record against the published output schema first; an
        invalid or incomplete record yields a serialization error keyed by its
        ``feedback_id`` and no output (Req 4.3, 4.4). A valid record is rendered
        as canonical JSON (Req 4.6).
        """
        # Determine the id to key any error by, tolerating partial/odd inputs.
        feedback_id = self._extract_feedback_id(insight)

        validated = self._revalidate_insight(insight)
        if validated is None:
            return SerializeOutcome(
                errors={
                    feedback_id: (
                        "insight record is invalid or incomplete with respect "
                        "to the published output schema"
                    )
                }
            )

        data = validated.model_dump(mode="json")
        return SerializeOutcome(json_text=canonical_json(data))

    def serialize_batch(self, output: BatchOutput) -> str:
        """Serialize a ``BatchOutput`` as canonical, schema-conforming JSON.

        The assembled batch output is rendered with sorted keys, normalized
        whitespace, and stable number formatting (Req 4.6, 10.4).
        """
        data = output.model_dump(mode="json")
        return canonical_json(data)

    @staticmethod
    def _revalidate_insight(insight: Any) -> InsightRecord | None:
        """Return a schema-valid ``InsightRecord`` or ``None`` if invalid.

        Guards against records constructed without validation (e.g. via
        ``model_construct``) by re-validating the dumped data against the
        schema. Returns ``None`` on any schema violation so the caller can
        record a serialization error rather than emit partial output.
        """
        if not isinstance(insight, InsightRecord):
            return None
        try:
            # Dump tolerantly (the input may have been built without validation)
            # then re-validate strictly against the published schema.
            raw = insight.model_dump()
            return InsightRecord.model_validate(raw)
        except (ValidationError, ValueError, TypeError):
            return None

    @staticmethod
    def _extract_feedback_id(insight: Any) -> str:
        """Best-effort extraction of the record id for keying errors."""
        feedback_id = getattr(insight, "feedback_id", None)
        if isinstance(feedback_id, str) and feedback_id:
            return feedback_id
        return "<unknown>"


__all__ = [
    "ResponseSerializer",
    "SerializeOutcome",
    "canonical_json",
]
