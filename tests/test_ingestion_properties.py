"""Property-based tests for the Ingestion_Component (tasks 2.3, 2.4, 2.5).

Each property below is a single Hypothesis test running at least 100 examples.
The strategies live in ``tests/strategies.py`` so they can be reused across the
suite.

Properties (from the design "Correctness Properties" section):

- Property 1: Ingestion preserves identity, channel, and metadata.
- Property 2: Whitespace trimming preserves interior content.
- Property 3: Invalid items are rejected with an error and no record.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from nlp_processing.ingestion import MAX_TEXT_LENGTH, IngestionComponent
from nlp_processing.models import RawFeedback

from .strategies import (
    TRIM_WHITESPACE,
    blank_text,
    core_text,
    invalid_channels,
    metadata,
    text_with_surrounding_whitespace,
    valid_channels,
    valid_raw_feedback,
)


# Feature: nlp-feedback-processing, Property 1: For any valid Raw_Feedback item,
# the produced Feedback_Record carries the same source_channel, the same
# metadata unchanged, cleaned text within 1..10000 characters, and an
# identifier; across any batch, all assigned identifiers are unique.
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(batch=st.lists(valid_raw_feedback(), min_size=1, max_size=40))
def test_property_1_ingestion_preserves_identity_channel_metadata(
    batch: list[RawFeedback],
) -> None:
    comp = IngestionComponent()
    result = comp.ingest_batch(batch)

    # All valid items become records; no rejects, no batch error.
    assert result.batch_error is None
    assert result.errors == {}
    assert len(result.records) == len(batch)

    for raw, record in zip(batch, result.records):
        # source_channel preserved (Req 1.1).
        assert record.source_channel == raw.source_channel
        # metadata copied unchanged (Req 1.1).
        assert record.metadata == raw.metadata
        # cleaned text equals the raw text with only outer trim-whitespace removed.
        assert record.cleaned_text == raw.text.strip(TRIM_WHITESPACE)
        # cleaned text within 1..10000 chars.
        assert 1 <= len(record.cleaned_text) <= MAX_TEXT_LENGTH
        # has a non-empty identifier.
        assert isinstance(record.id, str) and record.id

    # All assigned identifiers are unique across the batch (Req 1.5).
    ids = [r.id for r in result.records]
    assert len(ids) == len(set(ids))


# Feature: nlp-feedback-processing, Property 2: For any core string and any
# surrounding leading/trailing whitespace (space, tab, CR, LF), the cleaned text
# equals the core string with only outer whitespace removed and all characters
# between the first and last non-whitespace character preserved exactly.
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(
    pair=text_with_surrounding_whitespace(),
    channel=valid_channels(),
    meta=metadata(),
)
def test_property_2_whitespace_trimming_preserves_interior(
    pair: tuple[str, str], channel: str, meta: dict
) -> None:
    raw_text, expected_core = pair
    comp = IngestionComponent()
    result = comp.ingest_batch(
        [RawFeedback(source_channel=channel, text=raw_text, metadata=meta)]
    )

    assert result.batch_error is None
    assert len(result.records) == 1
    cleaned = result.records[0].cleaned_text

    # Only outer whitespace removed; interior preserved exactly.
    assert cleaned == expected_core
    # The core carries no leading/trailing trim-whitespace by construction, and
    # trimming again is a no-op (idempotent on the cleaned result).
    assert cleaned == cleaned.strip(TRIM_WHITESPACE)


# Feature: nlp-feedback-processing, Property 3: For any Raw_Feedback whose text
# is empty/whitespace-only, or whose source_channel is outside the allowed set,
# the item is rejected, no Feedback_Record is produced, and a validation error
# is recorded keyed by the item's assigned identifier.
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(
    invalid_kind=st.sampled_from(["blank_text", "bad_channel"]),
    blank=blank_text(),
    bad_channel=invalid_channels(),
    core=core_text(),
    meta=metadata(),
)
def test_property_3_invalid_items_rejected_with_error_no_record(
    invalid_kind: str,
    blank: str,
    bad_channel: str,
    core: str,
    meta: dict,
) -> None:
    if invalid_kind == "blank_text":
        # Valid channel, but empty/whitespace-only text (Req 1.3).
        raw = RawFeedback(source_channel="email", text=blank, metadata=meta)
    else:
        # Non-blank text, but an out-of-set channel (Req 1.4).
        raw = RawFeedback(source_channel=bad_channel, text=core, metadata=meta)

    comp = IngestionComponent()
    result = comp.ingest_batch([raw])

    # No record produced; exactly one validation error keyed by the assigned id.
    assert result.batch_error is None
    assert result.records == []
    assert len(result.errors) == 1
    (err_id,) = result.errors.keys()
    assert isinstance(err_id, str) and err_id
    assert isinstance(result.errors[err_id], str) and result.errors[err_id]
