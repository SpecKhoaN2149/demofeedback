"""Property-based tests for the strict Response_Parser (task 3.4).

Implements Property 8 from the design, validating the all-or-nothing parsing
contract (Req 4.2): any invalid response yields a parse error keyed by the
record id and no partial object.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from nlp_processing.serialization import (
    EnrichmentResponse,
    ParseError,
    ResponseParser,
)
from tests.strategies import invalid_enrichment_json

_PARSER = ResponseParser()


# Feature: nlp-feedback-processing, Property 8: Strict parsing rejects invalid
# responses with no partial output. For any Gemini response that is invalid
# JSON, omits a required field, or contains a field violating its type or
# range, the Response_Parser records a parse error keyed by the record id and
# produces no field of, and no partial, Insight_Record.
# Validates: Requirements 4.2
@settings(max_examples=200)
@given(raw_json=invalid_enrichment_json(), record_id=st.text(min_size=1, max_size=24))
def test_strict_parsing_rejects_invalid_responses(raw_json: str, record_id: str) -> None:
    outcome = _PARSER.parse_enrichment(raw_json, record_id, schema=EnrichmentResponse)

    # No partial object is produced on any failure.
    assert not outcome.ok
    assert outcome.value is None

    # A parse error is recorded and keyed by the originating record id.
    assert isinstance(outcome.error, ParseError)
    assert outcome.error.record_id == record_id
    assert outcome.record_id == record_id
    assert outcome.error.reason  # non-empty explanation
