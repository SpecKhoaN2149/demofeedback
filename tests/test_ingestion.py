"""Unit tests for the Ingestion_Component (task 2.1).

These cover the normalization and validation rules from Requirement 1:
identity/metadata preservation, whitespace trimming, invalid-item rejection,
unique id assignment for every item, and batch/text size limits.
"""

from nlp_processing.ingestion import (
    MAX_BATCH_SIZE,
    MAX_TEXT_LENGTH,
    IngestionComponent,
)
from nlp_processing.models import RawFeedback


def _raw(channel="email", text="hello", metadata=None):
    return RawFeedback(
        source_channel=channel, text=text, metadata=metadata or {}
    )


class TestIdentityAndMetadata:
    def test_produces_record_with_channel_and_metadata_unchanged(self):
        comp = IngestionComponent()
        meta = {"customer": "abc", "nested": {"k": [1, 2]}}
        result = comp.ingest_batch([_raw(channel="survey", text="great", metadata=meta)])

        assert result.batch_error is None
        assert len(result.records) == 1
        rec = result.records[0]
        assert rec.source_channel == "survey"
        assert rec.cleaned_text == "great"
        assert rec.metadata == meta

    def test_assigns_unique_ids_across_items_including_rejects(self):
        comp = IngestionComponent()
        result = comp.ingest_batch(
            [
                _raw(text="valid one"),
                _raw(text="   "),  # rejected: whitespace-only
                _raw(channel="fax", text="bad channel"),  # rejected: channel
                _raw(text="valid two"),
            ]
        )

        record_ids = [r.id for r in result.records]
        error_ids = list(result.errors.keys())
        all_ids = record_ids + error_ids
        # Every item (valid + rejected) got an id, and all are unique.
        assert len(all_ids) == 4
        assert len(set(all_ids)) == 4

    def test_ids_unique_across_batches_on_same_instance(self):
        comp = IngestionComponent()
        first = comp.ingest_batch([_raw(text="a")])
        second = comp.ingest_batch([_raw(text="b")])
        assert first.records[0].id != second.records[0].id


class TestWhitespaceTrimming:
    def test_trims_only_outer_whitespace_preserving_interior(self):
        comp = IngestionComponent()
        text = "\t\r\n  hello \tworld\n  \r"
        result = comp.ingest_batch([_raw(text=text)])
        assert result.records[0].cleaned_text == "hello \tworld"

    def test_preserves_non_stripped_unicode_whitespace(self):
        comp = IngestionComponent()
        # Non-breaking space (\xa0) is content, not trimmed.
        result = comp.ingest_batch([_raw(text="  \xa0keep\xa0  ")])
        assert result.records[0].cleaned_text == "\xa0keep\xa0"


class TestInvalidItemRejection:
    def test_rejects_empty_text(self):
        comp = IngestionComponent()
        result = comp.ingest_batch([_raw(text="")])
        assert result.records == []
        assert len(result.errors) == 1

    def test_rejects_whitespace_only_text(self):
        comp = IngestionComponent()
        result = comp.ingest_batch([_raw(text=" \t\r\n")])
        assert result.records == []
        assert len(result.errors) == 1

    def test_rejects_out_of_set_channel(self):
        comp = IngestionComponent()
        result = comp.ingest_batch([_raw(channel="carrier_pigeon", text="hi")])
        assert result.records == []
        assert len(result.errors) == 1

    def test_error_keyed_by_assigned_id(self):
        comp = IngestionComponent()
        result = comp.ingest_batch([_raw(text="")])
        (err_id,) = result.errors.keys()
        assert isinstance(err_id, str) and err_id


class TestBatchSizeLimit:
    def test_accepts_batch_at_limit(self):
        comp = IngestionComponent()
        items = [_raw(text=f"item {i}") for i in range(MAX_BATCH_SIZE)]
        result = comp.ingest_batch(items)
        assert result.batch_error is None
        assert len(result.records) == MAX_BATCH_SIZE

    def test_rejects_batch_over_limit_processing_nothing(self):
        comp = IngestionComponent()
        items = [_raw(text=f"item {i}") for i in range(MAX_BATCH_SIZE + 1)]
        result = comp.ingest_batch(items)
        assert result.batch_error is not None
        assert result.records == []
        assert result.errors == {}


class TestTextLengthLimit:
    def test_accepts_text_at_limit(self):
        comp = IngestionComponent()
        result = comp.ingest_batch([_raw(text="a" * MAX_TEXT_LENGTH)])
        assert len(result.records) == 1
        assert len(result.records[0].cleaned_text) == MAX_TEXT_LENGTH

    def test_rejects_text_over_limit_after_trim(self):
        comp = IngestionComponent()
        # Surrounding whitespace is trimmed first; interior length still over.
        result = comp.ingest_batch([_raw(text="  " + "a" * (MAX_TEXT_LENGTH + 1) + "  ")])
        assert result.records == []
        assert len(result.errors) == 1

    def test_text_within_limit_after_trimming_whitespace_is_accepted(self):
        comp = IngestionComponent()
        # Raw is over limit, but trims to exactly the limit -> accepted.
        raw_text = "  " + "a" * MAX_TEXT_LENGTH + "  "
        result = comp.ingest_batch([_raw(text=raw_text)])
        assert len(result.records) == 1


class TestEmptyBatch:
    def test_empty_batch_produces_empty_result(self):
        comp = IngestionComponent()
        result = comp.ingest_batch([])
        assert result.batch_error is None
        assert result.records == []
        assert result.errors == {}
