"""Property-based tests for the Response_Serializer (tasks 3.5-3.7).

Implements three design properties:

- Property 9  - the serializer rejects invalid/incomplete insights (Req 4.4).
- Property 10 - valid InsightRecords survive a serialize -> parse round-trip
  (Req 4.1, 4.3, 4.5).
- Property 11 - expected-schema JSON values survive a parse -> serialize
  normalization round-trip byte-for-byte (Req 4.6).

Round-trip design note (Property 10): ``serialize_insight`` emits *canonical
JSON of an InsightRecord*, not a Gemini enrichment response, so the strict
``EnrichmentResponse`` schema (which models untrusted Gemini output) is the
wrong lens for parsing it back. Instead we round-trip an ``InsightRecord``
through its own JSON: ``serialize_insight`` -> ``json.loads`` ->
``InsightRecord.model_validate``. The reconstructed record must equal the
original on the fields the requirement enumerates.

Normalization note (Property 11): ``canonical_json`` is the normalizer (sorted
keys, compact separators, stable numbers). "Parse then serialize" for a JSON
*value* is ``canonical_json(json.loads(canonical_json(x)))``; idempotence of
this pipeline is exactly the byte-for-byte normalization round-trip.
"""

from __future__ import annotations

import json

from hypothesis import given, settings

from nlp_processing.models import InsightRecord
from nlp_processing.serialization.serializer import ResponseSerializer, canonical_json
from tests.strategies import (
    expected_schema_json,
    invalid_insight_record,
    valid_insight_record,
)

_SERIALIZER = ResponseSerializer()


# Feature: nlp-feedback-processing, Property 9: Serializer rejects invalid
# insights. For any Insight_Record that is invalid or incomplete with respect
# to the published output schema, the Response_Serializer records a
# serialization error keyed by the record id and produces no output for that
# record.
# Validates: Requirements 4.4
@settings(max_examples=200)
@given(insight=invalid_insight_record())
def test_serializer_rejects_invalid_insights(insight: InsightRecord) -> None:
    outcome = _SERIALIZER.serialize_insight(insight)

    # No output is produced for an invalid/incomplete record.
    assert not outcome.ok
    assert outcome.json_text is None

    # A serialization error is recorded, keyed by the record's feedback_id.
    assert outcome.errors
    assert insight.feedback_id in outcome.errors
    assert outcome.errors[insight.feedback_id]  # non-empty reason


# Feature: nlp-feedback-processing, Property 10: Insight serialization
# round-trip. For any valid Insight_Record, serializing it and then parsing the
# serialized JSON produces an Insight_Record whose themes and theme confidence
# scores, sentiment and sentiment confidence, severity score, and cluster
# assignment are equal to the original.
# Validates: Requirements 4.1, 4.3, 4.5
@settings(max_examples=200)
@given(insight=valid_insight_record())
def test_insight_serialization_round_trip(insight: InsightRecord) -> None:
    outcome = _SERIALIZER.serialize_insight(insight)
    assert outcome.ok
    assert outcome.json_text is not None

    # Parse the serialized JSON back into an InsightRecord through its own
    # schema (see module docstring for why EnrichmentResponse is not used).
    reparsed = InsightRecord.model_validate(json.loads(outcome.json_text))

    # The fields the requirement enumerates must be preserved exactly.
    assert reparsed.themes == insight.themes  # themes + confidences
    assert reparsed.sentiment == insight.sentiment
    assert reparsed.sentiment_confidence == insight.sentiment_confidence
    assert reparsed.severity_score == insight.severity_score
    assert reparsed.cluster_id == insight.cluster_id  # cluster assignment

    # Strengthen the guarantee: the full record round-trips, so re-serializing
    # is byte-for-byte stable (canonical JSON is deterministic).
    assert reparsed == insight
    assert _SERIALIZER.serialize_insight(reparsed).json_text == outcome.json_text


# Feature: nlp-feedback-processing, Property 11: JSON normalization round-trip.
# For any valid expected-schema JSON value, parsing it and then serializing the
# result produces JSON byte-for-byte equal to the original normalized JSON
# (keys in lexicographic order, insignificant whitespace removed).
# Validates: Requirements 4.6
@settings(max_examples=200)
@given(value=expected_schema_json())
def test_json_normalization_round_trip(value: object) -> None:
    normalized = canonical_json(value)

    # Parse the normalized JSON back to a Python value, then re-normalize.
    round_tripped = canonical_json(json.loads(normalized))

    # Normalization is idempotent: byte-for-byte equal after the round-trip.
    assert round_tripped == normalized
