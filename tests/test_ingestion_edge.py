"""Edge/boundary tests for ingestion limits (task 2.6).

Covers the exact boundaries of the batch-size limit (Req 1.6) and the cleaned
text length limit after trimming (Req 1.7): batch size 1000/1001 and cleaned
text length 10000/10001.
"""

from __future__ import annotations

from nlp_processing.ingestion import (
    MAX_BATCH_SIZE,
    MAX_TEXT_LENGTH,
    IngestionComponent,
)
from nlp_processing.models import RawFeedback


def _raw(text: str, channel: str = "email") -> RawFeedback:
    return RawFeedback(source_channel=channel, text=text, metadata={})


class TestBatchSizeBoundary:
    def test_batch_of_exactly_1000_is_accepted(self):
        comp = IngestionComponent()
        items = [_raw(f"item {i}") for i in range(MAX_BATCH_SIZE)]
        result = comp.ingest_batch(items)
        assert result.batch_error is None
        assert len(result.records) == MAX_BATCH_SIZE

    def test_batch_of_1001_is_rejected_processing_nothing(self):
        comp = IngestionComponent()
        items = [_raw(f"item {i}") for i in range(MAX_BATCH_SIZE + 1)]
        result = comp.ingest_batch(items)
        assert result.batch_error is not None
        assert "1000" in result.batch_error
        assert result.records == []
        assert result.errors == {}


class TestTextLengthBoundary:
    def test_cleaned_text_of_exactly_10000_is_accepted(self):
        comp = IngestionComponent()
        result = comp.ingest_batch([_raw("a" * MAX_TEXT_LENGTH)])
        assert result.batch_error is None
        assert len(result.records) == 1
        assert len(result.records[0].cleaned_text) == MAX_TEXT_LENGTH

    def test_cleaned_text_of_10001_is_rejected(self):
        comp = IngestionComponent()
        result = comp.ingest_batch([_raw("a" * (MAX_TEXT_LENGTH + 1))])
        assert result.records == []
        assert len(result.errors) == 1
        (err_id,) = result.errors.keys()
        assert str(MAX_TEXT_LENGTH) in result.errors[err_id]

    def test_text_trims_to_exactly_10000_is_accepted(self):
        comp = IngestionComponent()
        # Over the limit raw, but outer whitespace trims it to exactly 10000.
        raw_text = "\t\n  " + "a" * MAX_TEXT_LENGTH + "  \r\n"
        result = comp.ingest_batch([_raw(raw_text)])
        assert len(result.records) == 1
        assert len(result.records[0].cleaned_text) == MAX_TEXT_LENGTH

    def test_text_trims_to_10001_is_rejected(self):
        comp = IngestionComponent()
        # Interior length is 10001 after trimming the outer whitespace.
        raw_text = "  " + "a" * (MAX_TEXT_LENGTH + 1) + "\t"
        result = comp.ingest_batch([_raw(raw_text)])
        assert result.records == []
        assert len(result.errors) == 1
