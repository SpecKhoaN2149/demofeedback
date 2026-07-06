"""Ingestion_Component: batch ingestion and normalization (Req 1).

This module turns a batch of unvalidated :class:`RawFeedback` items into
validated :class:`FeedbackRecord` objects, assigning a unique identifier to
every item up front and recording a keyed validation error for any item that
cannot be normalized.

Rules implemented here (design "Ingestion_Component" section):

- Reject the whole batch when ``len(raw_items) > 1000`` with a batch-size
  validation error; no items are processed (Req 1.6).
- Assign a unique identifier to every item up front, including ones that will
  be rejected (Req 1.5). IDs are unique across all records the component ever
  produces: a per-instance UUID prefix plus a monotonic counter.
- Trim only leading/trailing whitespace (space, tab, CR, LF); preserve all
  interior characters exactly (Req 1.2).
- Reject empty/whitespace-only text (Req 1.3), out-of-set ``source_channel``
  (Req 1.4), and cleaned text longer than 10,000 characters (Req 1.7); each
  produces a validation error keyed by the assigned id and no record.
- Copy original metadata onto the ``FeedbackRecord`` unchanged (Req 1.1).
"""

from __future__ import annotations

import uuid
from typing import get_args

from pydantic import BaseModel, Field

from ..models import FeedbackRecord, RawFeedback, SourceChannel

# Maximum number of items accepted in a single batch (Req 1.6).
MAX_BATCH_SIZE = 1000

# Maximum length of cleaned text, in characters (Req 1.7).
MAX_TEXT_LENGTH = 10_000

# The exact whitespace characters trimmed from the ends of the text (Req 1.2).
# Only space, tab, carriage return, and line feed are stripped; other unicode
# whitespace (e.g. non-breaking space, vertical tab) is treated as content.
_TRIM_CHARS = " \t\r\n"

# The allowed source channels, derived from the SourceChannel literal (Req 1.4).
ALLOWED_CHANNELS: frozenset[str] = frozenset(get_args(SourceChannel))


class IngestionResult(BaseModel):
    """The outcome of ingesting a single batch.

    ``records`` holds one :class:`FeedbackRecord` per successfully normalized
    item. ``errors`` maps each rejected item's assigned identifier to a human
    readable validation reason (Req 1.3, 1.4, 1.7). ``batch_error`` is set only
    when the whole batch is rejected for exceeding the size limit (Req 1.6), in
    which case ``records`` and ``errors`` are empty.
    """

    records: list[FeedbackRecord] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)
    batch_error: str | None = None


class IngestionComponent:
    """Normalizes and validates raw feedback into ``FeedbackRecord`` objects.

    A single instance assigns globally unique identifiers across every batch it
    processes by combining a per-instance UUID prefix with a monotonic counter.
    """

    def __init__(self) -> None:
        # Namespacing the counter with a per-instance UUID keeps identifiers
        # unique even across separate IngestionComponent instances (Req 1.1).
        self._instance_id = uuid.uuid4().hex
        self._counter = 0

    def _next_id(self) -> str:
        """Return the next unique identifier for this component instance."""
        self._counter += 1
        return f"{self._instance_id}-{self._counter}"

    def ingest_batch(self, raw_items: list[RawFeedback]) -> IngestionResult:
        """Normalize and validate a batch of raw feedback items.

        Returns an :class:`IngestionResult` carrying produced records and a map
        of validation errors keyed by each rejected item's assigned id.
        """
        # Req 1.6: reject the whole batch when it exceeds the size limit and
        # process nothing.
        if len(raw_items) > MAX_BATCH_SIZE:
            return IngestionResult(
                batch_error=(
                    f"batch size {len(raw_items)} exceeds the limit of "
                    f"{MAX_BATCH_SIZE} items"
                ),
            )

        records: list[FeedbackRecord] = []
        errors: dict[str, str] = {}

        for item in raw_items:
            # Req 1.5: assign a unique id to every item up front, even rejects.
            assigned_id = self._next_id()
            reason = self._validate(item)
            if reason is not None:
                errors[assigned_id] = reason
                continue

            # Req 1.2: trim only the four whitespace characters at the ends.
            cleaned_text = item.text.strip(_TRIM_CHARS)
            # Req 1.1: copy the original metadata onto the record unchanged.
            records.append(
                FeedbackRecord(
                    id=assigned_id,
                    source_channel=item.source_channel,  # validated below
                    cleaned_text=cleaned_text,
                    metadata=item.metadata,
                )
            )

        return IngestionResult(records=records, errors=errors)

    @staticmethod
    def _validate(item: RawFeedback) -> str | None:
        """Return a validation error reason for ``item``, or ``None`` if valid.

        Checks, in order: out-of-set source channel (Req 1.4), empty or
        whitespace-only text (Req 1.3), and cleaned text exceeding the maximum
        length (Req 1.7).
        """
        if item.source_channel not in ALLOWED_CHANNELS:
            return (
                f"source_channel '{item.source_channel}' is not one of "
                f"{sorted(ALLOWED_CHANNELS)}"
            )

        cleaned_text = item.text.strip(_TRIM_CHARS)
        if not cleaned_text:
            return "text is empty or whitespace-only"

        if len(cleaned_text) > MAX_TEXT_LENGTH:
            return (
                f"cleaned text length {len(cleaned_text)} exceeds the limit of "
                f"{MAX_TEXT_LENGTH} characters"
            )

        return None


__all__ = [
    "IngestionComponent",
    "IngestionResult",
    "MAX_BATCH_SIZE",
    "MAX_TEXT_LENGTH",
    "ALLOWED_CHANNELS",
]
