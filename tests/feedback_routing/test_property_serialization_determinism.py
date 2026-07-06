"""Property test for serialization determinism.

# Feature: nlp-feedback-routing, Property 17

**Property 17: Serialization Determinism** — For any valid FeedbackAnalysis
record, serializing it to JSON twice SHALL produce byte-for-byte identical
output (sorted keys, compact separators, 6-decimal float precision).

**Validates: Requirements 23.2**
"""

from __future__ import annotations

from hypothesis import given, settings

from nlp_processing.serialization.feedback_serializer import (
    FeedbackAnalysisSerializer,
)

from .strategies import feedback_analysis_records


# Feature: nlp-feedback-routing, Property 17
@given(record=feedback_analysis_records())
@settings(max_examples=100)
def test_serialization_determinism(record):
    """Serializing a FeedbackAnalysis record twice produces byte-for-byte
    identical JSON output.

    **Validates: Requirements 23.2**
    """
    serializer = FeedbackAnalysisSerializer()

    output_1 = serializer.serialize(record)
    output_2 = serializer.serialize(record)

    assert output_1 == output_2, (
        f"Serialization is non-deterministic for record {record.feedback_id!r}.\n"
        f"First:  {output_1!r}\n"
        f"Second: {output_2!r}"
    )
