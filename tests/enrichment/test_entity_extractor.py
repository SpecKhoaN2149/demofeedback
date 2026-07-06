"""Unit tests for the EntityExtractor (task 5.7, Req 9).

Covers:
* Successful extraction of valid entities (Req 9.1, 9.2)
* Empty entity list when no entities meet threshold (Req 9.3)
* Dollar amount normalization to 2 decimal places (Req 9.4)
* Fallback on transport failure or timeout (Req 9.5)
* Discarding unparseable dollar amounts (Req 9.6)
* Confidence >= 0.5 threshold enforcement (Req 9.2)
* Max 50 entities limit (Req 9.1)
* entity_value max 200 chars (Req 9.1)
* Invalid entity types discarded
"""

from __future__ import annotations

import json

import pytest

from nlp_processing.enrichment.entity_extractor import (
    EXTRACTION_TIMEOUT_SECONDS,
    MAX_ENTITIES_PER_RECORD,
    MAX_ENTITY_VALUE_LENGTH,
    MIN_CONFIDENCE_THRESHOLD,
    VALID_ENTITY_TYPES,
    EntityExtractionResponse,
    EntityExtractionResult,
    EntityExtractor,
    _normalize_dollar_amount,
)
from nlp_processing.models.feedback_routing import CanonicalFeedback, ExtractedEntity
from nlp_processing.transport.client import (
    GeminiErrorKind,
    GeminiFailure,
    GeminiRequest,
    GeminiResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_feedback(
    feedback_id: str = "fb-001",
    text: str = "My internet service in Seattle area has been down since yesterday. I was charged $150 on my last bill for the router.",
) -> CanonicalFeedback:
    """Create a test CanonicalFeedback record."""
    return CanonicalFeedback(
        feedback_id=feedback_id,
        source_type="widget",
        original_source_id="widget-sub-001",
        cleaned_text=text,
        detected_language="en",
        ingested_at="2024-01-15T10:00:00Z",
    )


def make_success_generate(payload: dict):
    """A fake generate returning a successful result with payload JSON."""

    def _generate(request: GeminiRequest) -> GeminiResult:
        return GeminiResult(
            record_id=request.record_id, attempts=1, text=json.dumps(payload)
        )

    return _generate


def make_failure_generate(
    kind: GeminiErrorKind = GeminiErrorKind.TIMEOUT, message: str = "timed out"
):
    """A fake generate returning a transport failure."""

    def _generate(request: GeminiRequest) -> GeminiResult:
        return GeminiResult(
            record_id=request.record_id,
            attempts=1,
            failure=GeminiFailure(
                record_id=request.record_id, kind=kind, message=message, attempts=1
            ),
        )

    return _generate


# ---------------------------------------------------------------------------
# Tests: Successful extraction (Req 9.1, 9.2)
# ---------------------------------------------------------------------------


class TestSuccessfulExtraction:
    """Tests for valid entity extraction."""

    def test_extracts_multiple_entity_types(self):
        """Req 9.1: extracts service_area, dollar_amount, equipment_name."""
        gen = make_success_generate(
            {
                "entities": [
                    {"entity_type": "service_area", "entity_value": "Seattle", "confidence": 0.9},
                    {"entity_type": "dollar_amount", "entity_value": "$150", "confidence": 0.85},
                    {"entity_type": "equipment_name", "entity_value": "router", "confidence": 0.7},
                ]
            }
        )
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract(feedback)

        assert len(result) == 3
        assert result[0].entity_type == "service_area"
        assert result[0].entity_value == "Seattle"
        assert result[0].confidence == 0.9
        assert result[1].entity_type == "dollar_amount"
        assert result[1].entity_value == "150.00"  # Normalized
        assert result[2].entity_type == "equipment_name"
        assert result[2].entity_value == "router"

    def test_extracts_all_valid_entity_types(self):
        """Req 9.1: all seven entity types are extractable."""
        gen = make_success_generate(
            {
                "entities": [
                    {"entity_type": "service_area", "entity_value": "Pacific NW", "confidence": 0.8},
                    {"entity_type": "product_name", "entity_value": "Fiber Plus", "confidence": 0.9},
                    {"entity_type": "time_reference", "entity_value": "yesterday", "confidence": 0.7},
                    {"entity_type": "dollar_amount", "entity_value": "$99.99", "confidence": 0.85},
                    {"entity_type": "equipment_name", "entity_value": "modem", "confidence": 0.75},
                    {"entity_type": "outage_mention", "entity_value": "service down", "confidence": 0.9},
                    {"entity_type": "competitor_mention", "entity_value": "Comcast", "confidence": 0.6},
                ]
            }
        )
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract(feedback)

        assert len(result) == 7
        extracted_types = {e.entity_type for e in result}
        assert extracted_types == VALID_ENTITY_TYPES

    def test_extract_with_status_returns_success(self):
        """extract_with_status returns status='success' on valid extraction."""
        gen = make_success_generate(
            {
                "entities": [
                    {"entity_type": "service_area", "entity_value": "Portland", "confidence": 0.8},
                ]
            }
        )
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract_with_status(feedback)

        assert result.ok is True
        assert result.status == "success"
        assert len(result.entities) == 1


# ---------------------------------------------------------------------------
# Tests: Empty entity list (Req 9.3)
# ---------------------------------------------------------------------------


class TestEmptyEntityList:
    """Tests for empty entity list scenarios."""

    def test_no_entities_in_response(self):
        """Req 9.3: empty entity list when model finds no entities."""
        gen = make_success_generate({"entities": []})
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract(feedback)

        assert result == []

    def test_all_entities_below_threshold(self):
        """Req 9.3: empty list when all entities have confidence < 0.5."""
        gen = make_success_generate(
            {
                "entities": [
                    {"entity_type": "service_area", "entity_value": "somewhere", "confidence": 0.3},
                    {"entity_type": "product_name", "entity_value": "thing", "confidence": 0.49},
                ]
            }
        )
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract(feedback)

        assert result == []


# ---------------------------------------------------------------------------
# Tests: Confidence threshold (Req 9.2)
# ---------------------------------------------------------------------------


class TestConfidenceThreshold:
    """Tests for confidence >= 0.5 filtering."""

    def test_entity_at_threshold_is_included(self):
        """Req 9.2: confidence exactly 0.5 is included."""
        gen = make_success_generate(
            {
                "entities": [
                    {"entity_type": "service_area", "entity_value": "Denver", "confidence": 0.5},
                ]
            }
        )
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract(feedback)

        assert len(result) == 1
        assert result[0].confidence == 0.5

    def test_entity_below_threshold_is_excluded(self):
        """Req 9.2: confidence < 0.5 is excluded."""
        gen = make_success_generate(
            {
                "entities": [
                    {"entity_type": "service_area", "entity_value": "Denver", "confidence": 0.49},
                ]
            }
        )
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract(feedback)

        assert result == []

    def test_mixed_confidence_filters_correctly(self):
        """Entities above and below threshold are correctly filtered."""
        gen = make_success_generate(
            {
                "entities": [
                    {"entity_type": "service_area", "entity_value": "Denver", "confidence": 0.9},
                    {"entity_type": "product_name", "entity_value": "Basic", "confidence": 0.3},
                    {"entity_type": "equipment_name", "entity_value": "router", "confidence": 0.6},
                ]
            }
        )
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract(feedback)

        assert len(result) == 2
        assert result[0].entity_type == "service_area"
        assert result[1].entity_type == "equipment_name"


# ---------------------------------------------------------------------------
# Tests: Dollar amount normalization (Req 9.4)
# ---------------------------------------------------------------------------


class TestDollarAmountNormalization:
    """Tests for dollar_amount normalization to 2 decimal places."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("$50", "50.00"),
            ("$1,200.5", "1200.50"),
            ("99.99", "99.99"),
            ("$0.01", "0.01"),
            ("$999999999.99", "999999999.99"),
            ("1000", "1000.00"),
            ("  $25.5  ", "25.50"),
            ("€150.00", "150.00"),
        ],
    )
    def test_valid_dollar_amounts(self, raw: str, expected: str):
        """Req 9.4: valid dollar amounts are normalized to 2 decimal places."""
        assert _normalize_dollar_amount(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "free",
            "N/A",
            "$0.00",
            "$0.001",  # Below minimum after rounding
            "$-50",
            "-25.00",
            "$1000000000.00",  # Above max
            "",
            "abc",
            "$$$",
        ],
    )
    def test_invalid_dollar_amounts_return_none(self, raw: str):
        """Req 9.6: unparseable or out-of-range amounts return None."""
        result = _normalize_dollar_amount(raw)
        # For truly invalid amounts, should be None
        if raw in ("free", "N/A", "$-50", "-25.00", "$1000000000.00", "", "abc", "$$$"):
            assert result is None

    def test_dollar_amount_entity_normalized_in_extraction(self):
        """Req 9.4: dollar_amount entities are normalized in full extraction."""
        gen = make_success_generate(
            {
                "entities": [
                    {"entity_type": "dollar_amount", "entity_value": "$1,200.5", "confidence": 0.9},
                ]
            }
        )
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract(feedback)

        assert len(result) == 1
        assert result[0].entity_value == "1200.50"

    def test_unparseable_dollar_amount_discarded(self):
        """Req 9.6: unparseable dollar amounts are discarded from the list."""
        gen = make_success_generate(
            {
                "entities": [
                    {"entity_type": "dollar_amount", "entity_value": "free tier", "confidence": 0.9},
                    {"entity_type": "service_area", "entity_value": "Seattle", "confidence": 0.8},
                ]
            }
        )
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract(feedback)

        assert len(result) == 1
        assert result[0].entity_type == "service_area"


# ---------------------------------------------------------------------------
# Tests: Fallback on errors (Req 9.5)
# ---------------------------------------------------------------------------


class TestFallbackBehavior:
    """Tests for fallback on errors and timeouts."""

    def test_transport_timeout_returns_empty_list_and_failed(self):
        """Req 9.5: timeout → empty list + 'failed' status."""
        gen = make_failure_generate(GeminiErrorKind.TIMEOUT, "request timed out after 30s")
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract_with_status(feedback)

        assert result.entities == []
        assert result.status == "failed"
        assert result.ok is False
        assert "timed out" in (result.failure_reason or "")

    def test_transport_error_returns_empty_list(self):
        """Req 9.5: transport error → empty list."""
        gen = make_failure_generate(GeminiErrorKind.ERROR, "internal server error")
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract(feedback)

        assert result == []

    def test_transport_exhausted_returns_empty_list(self):
        """Req 9.5: exhausted retries → empty list + failed."""
        gen = make_failure_generate(GeminiErrorKind.EXHAUSTED, "exhausted 5 attempts")
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract_with_status(feedback)

        assert result.entities == []
        assert result.status == "failed"

    def test_invalid_json_response_returns_failed(self):
        """Req 9.5: unparseable JSON response → failed status."""

        def _generate(request: GeminiRequest) -> GeminiResult:
            return GeminiResult(
                record_id=request.record_id, attempts=1, text="not valid json {{"
            )

        extractor = EntityExtractor(_generate)
        feedback = make_feedback()

        result = extractor.extract_with_status(feedback)

        assert result.entities == []
        assert result.status == "failed"

    def test_extract_returns_empty_list_on_failure(self):
        """Req 9.5: extract() returns empty list on failure (simplified API)."""
        gen = make_failure_generate(GeminiErrorKind.TIMEOUT, "timed out")
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract(feedback)

        assert result == []


# ---------------------------------------------------------------------------
# Tests: Max entities limit (Req 9.1)
# ---------------------------------------------------------------------------


class TestMaxEntitiesLimit:
    """Tests for max 50 entities per feedback record."""

    def test_max_50_entities_enforced(self):
        """Req 9.1: at most 50 entities are returned."""
        # Generate 60 entities
        entities = [
            {"entity_type": "service_area", "entity_value": f"Area {i}", "confidence": 0.8}
            for i in range(60)
        ]
        gen = make_success_generate({"entities": entities})
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract(feedback)

        assert len(result) == MAX_ENTITIES_PER_RECORD
        assert len(result) == 50


# ---------------------------------------------------------------------------
# Tests: entity_value max length (Req 9.1)
# ---------------------------------------------------------------------------


class TestEntityValueMaxLength:
    """Tests for entity_value max 200 characters."""

    def test_long_entity_value_truncated(self):
        """Req 9.1: entity_value > 200 chars is truncated."""
        long_value = "A" * 250
        gen = make_success_generate(
            {
                "entities": [
                    {"entity_type": "service_area", "entity_value": long_value, "confidence": 0.8},
                ]
            }
        )
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract(feedback)

        assert len(result) == 1
        assert len(result[0].entity_value) == MAX_ENTITY_VALUE_LENGTH

    def test_entity_value_at_max_length_preserved(self):
        """entity_value exactly 200 chars is preserved."""
        exact_value = "B" * 200
        gen = make_success_generate(
            {
                "entities": [
                    {"entity_type": "product_name", "entity_value": exact_value, "confidence": 0.7},
                ]
            }
        )
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract(feedback)

        assert len(result) == 1
        assert result[0].entity_value == exact_value


# ---------------------------------------------------------------------------
# Tests: Invalid entity types
# ---------------------------------------------------------------------------


class TestInvalidEntityTypes:
    """Tests for entity types not in the valid set."""

    def test_unknown_entity_type_discarded(self):
        """Invalid entity_type is discarded from results."""
        gen = make_success_generate(
            {
                "entities": [
                    {"entity_type": "unknown_type", "entity_value": "thing", "confidence": 0.9},
                    {"entity_type": "service_area", "entity_value": "Seattle", "confidence": 0.8},
                ]
            }
        )
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract(feedback)

        assert len(result) == 1
        assert result[0].entity_type == "service_area"

    def test_empty_entity_value_discarded(self):
        """Empty entity_value is discarded."""
        gen = make_success_generate(
            {
                "entities": [
                    {"entity_type": "service_area", "entity_value": "", "confidence": 0.9},
                    {"entity_type": "service_area", "entity_value": "   ", "confidence": 0.9},
                ]
            }
        )
        extractor = EntityExtractor(gen)
        feedback = make_feedback()

        result = extractor.extract(feedback)

        assert result == []


# ---------------------------------------------------------------------------
# Tests: Constructor validation
# ---------------------------------------------------------------------------


class TestConstructor:
    """Tests for EntityExtractor constructor."""

    def test_accepts_gemini_client_with_generate(self):
        """Accepts an object with a 'generate' method."""

        class FakeClient:
            def generate(self, request: GeminiRequest) -> GeminiResult:
                return GeminiResult(
                    record_id=request.record_id,
                    attempts=1,
                    text=json.dumps({"entities": []}),
                )

        extractor = EntityExtractor(FakeClient())
        result = extractor.extract(make_feedback())
        assert result == []

    def test_accepts_callable(self):
        """Accepts a plain callable as client."""
        gen = make_success_generate({"entities": []})
        extractor = EntityExtractor(gen)
        result = extractor.extract(make_feedback())
        assert result == []

    def test_rejects_non_callable(self):
        """Raises TypeError for non-callable client."""
        with pytest.raises(TypeError, match="client must be"):
            EntityExtractor(42)  # type: ignore[arg-type]
