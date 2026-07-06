"""Unit tests for FeedbackAnalysisSerializer.

Tests cover:
- Deterministic serialization (sorted keys, compact separators, float precision)
- Round-trip fidelity (serialize → deserialize produces identical record)
- Malformed JSON rejection
- Schema constraint violation rejection with field-specific errors
"""

from __future__ import annotations

import json

import pytest

from nlp_processing.models.feedback_routing import (
    ExtractedEntity,
    FeedbackAnalysis,
)
from nlp_processing.serialization.feedback_serializer import (
    DeserializationError,
    FeedbackAnalysisSerializer,
)


@pytest.fixture
def serializer() -> FeedbackAnalysisSerializer:
    return FeedbackAnalysisSerializer()


@pytest.fixture
def sample_record() -> FeedbackAnalysis:
    return FeedbackAnalysis(
        feedback_id="abc-123",
        sentiment_label="negative",
        sentiment_score=-0.75,
        priority_score=0.82,
        priority_level="critical",
        theme_primary="outage",
        theme_secondary="billing",
        intent="complaint",
        cluster_id="cluster-001",
        requires_action=True,
        entities=[
            ExtractedEntity(
                entity_type="service_area",
                entity_value="Downtown Portland",
                confidence=0.95,
            ),
            ExtractedEntity(
                entity_type="dollar_amount",
                entity_value="49.99",
                confidence=0.88,
            ),
        ],
        processed_at="2024-01-15T10:30:00Z",
    )


@pytest.fixture
def minimal_record() -> FeedbackAnalysis:
    """A record with no optional fields populated."""
    return FeedbackAnalysis(
        feedback_id="min-001",
        sentiment_label="neutral",
        sentiment_score=0.0,
        priority_score=0.1,
        priority_level="low",
        theme_primary="unclassified",
        theme_secondary=None,
        intent="unclassified",
        cluster_id=None,
        requires_action=False,
        entities=[],
        processed_at="2024-06-01T00:00:00Z",
    )


class TestSerialize:
    """Tests for the serialize method."""

    def test_produces_valid_json(
        self, serializer: FeedbackAnalysisSerializer, sample_record: FeedbackAnalysis
    ) -> None:
        result = serializer.serialize(sample_record)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_sorted_keys(
        self, serializer: FeedbackAnalysisSerializer, sample_record: FeedbackAnalysis
    ) -> None:
        result = serializer.serialize(sample_record)
        parsed = json.loads(result)
        keys = list(parsed.keys())
        assert keys == sorted(keys)

    def test_compact_separators(
        self, serializer: FeedbackAnalysisSerializer, sample_record: FeedbackAnalysis
    ) -> None:
        result = serializer.serialize(sample_record)
        # No spaces after colons or commas at the top level
        assert ": " not in result
        assert ", " not in result

    def test_determinism(
        self, serializer: FeedbackAnalysisSerializer, sample_record: FeedbackAnalysis
    ) -> None:
        """Serializing the same record twice produces identical output."""
        result1 = serializer.serialize(sample_record)
        result2 = serializer.serialize(sample_record)
        assert result1 == result2

    def test_float_precision_six_decimals(
        self, serializer: FeedbackAnalysisSerializer
    ) -> None:
        """Float values are rounded to 6-decimal precision."""
        record = FeedbackAnalysis(
            feedback_id="precision-test",
            sentiment_label="positive",
            sentiment_score=0.1234567890,  # More than 6 decimals
            priority_score=0.9999999,  # More than 6 decimals
            priority_level="critical",
            theme_primary="billing",
            intent="praise",
            requires_action=False,
            entities=[],
            processed_at="2024-01-01T00:00:00Z",
        )
        result = serializer.serialize(record)
        parsed = json.loads(result)
        # Values should be rounded to 6 decimal precision
        assert abs(parsed["sentiment_score"] - 0.123457) < 1e-7
        assert abs(parsed["priority_score"] - 1.0) < 1e-7

    def test_includes_all_fields(
        self, serializer: FeedbackAnalysisSerializer, sample_record: FeedbackAnalysis
    ) -> None:
        result = serializer.serialize(sample_record)
        parsed = json.loads(result)
        expected_fields = {
            "feedback_id",
            "sentiment_label",
            "sentiment_score",
            "priority_score",
            "priority_level",
            "theme_primary",
            "theme_secondary",
            "intent",
            "cluster_id",
            "requires_action",
            "entities",
            "processed_at",
        }
        assert set(parsed.keys()) == expected_fields

    def test_entities_serialized_with_sorted_keys(
        self, serializer: FeedbackAnalysisSerializer, sample_record: FeedbackAnalysis
    ) -> None:
        result = serializer.serialize(sample_record)
        parsed = json.loads(result)
        for entity in parsed["entities"]:
            keys = list(entity.keys())
            assert keys == sorted(keys)

    def test_minimal_record(
        self, serializer: FeedbackAnalysisSerializer, minimal_record: FeedbackAnalysis
    ) -> None:
        """Serializes a record with null optional fields."""
        result = serializer.serialize(minimal_record)
        parsed = json.loads(result)
        assert parsed["theme_secondary"] is None
        assert parsed["cluster_id"] is None
        assert parsed["entities"] == []


class TestDeserialize:
    """Tests for the deserialize method."""

    def test_round_trip(
        self, serializer: FeedbackAnalysisSerializer, sample_record: FeedbackAnalysis
    ) -> None:
        """serialize → deserialize produces equivalent record."""
        json_str = serializer.serialize(sample_record)
        restored = serializer.deserialize(json_str)
        assert restored.feedback_id == sample_record.feedback_id
        assert restored.sentiment_label == sample_record.sentiment_label
        assert abs(restored.sentiment_score - sample_record.sentiment_score) < 1e-6
        assert abs(restored.priority_score - sample_record.priority_score) < 1e-6
        assert restored.priority_level == sample_record.priority_level
        assert restored.theme_primary == sample_record.theme_primary
        assert restored.theme_secondary == sample_record.theme_secondary
        assert restored.intent == sample_record.intent
        assert restored.cluster_id == sample_record.cluster_id
        assert restored.requires_action == sample_record.requires_action
        assert restored.processed_at == sample_record.processed_at
        assert len(restored.entities) == len(sample_record.entities)
        for r_ent, s_ent in zip(restored.entities, sample_record.entities):
            assert r_ent.entity_type == s_ent.entity_type
            assert r_ent.entity_value == s_ent.entity_value
            assert abs(r_ent.confidence - s_ent.confidence) < 1e-6

    def test_rejects_malformed_json(
        self, serializer: FeedbackAnalysisSerializer
    ) -> None:
        """Malformed JSON raises DeserializationError with parsing reason."""
        with pytest.raises(DeserializationError) as exc_info:
            serializer.deserialize("{not valid json!!!")
        assert "invalid JSON" in exc_info.value.reason

    def test_rejects_non_object_json(
        self, serializer: FeedbackAnalysisSerializer
    ) -> None:
        """JSON array at top level is rejected."""
        with pytest.raises(DeserializationError) as exc_info:
            serializer.deserialize("[1, 2, 3]")
        assert "expected a JSON object" in exc_info.value.reason

    def test_rejects_sentiment_score_out_of_range(
        self, serializer: FeedbackAnalysisSerializer
    ) -> None:
        """sentiment_score > 1.0 is rejected."""
        data = {
            "feedback_id": "test-001",
            "sentiment_label": "positive",
            "sentiment_score": 1.5,  # Out of range
            "priority_score": 0.5,
            "priority_level": "medium",
            "theme_primary": "billing",
            "intent": "complaint",
            "requires_action": True,
            "entities": [],
            "processed_at": "2024-01-01T00:00:00Z",
        }
        with pytest.raises(DeserializationError) as exc_info:
            serializer.deserialize(json.dumps(data))
        assert exc_info.value.reason == "schema validation failed"
        assert any("sentiment_score" in d for d in exc_info.value.details)

    def test_rejects_invalid_sentiment_label(
        self, serializer: FeedbackAnalysisSerializer
    ) -> None:
        """Invalid sentiment_label is rejected."""
        data = {
            "feedback_id": "test-001",
            "sentiment_label": "very_positive",  # Invalid
            "sentiment_score": 0.5,
            "priority_score": 0.5,
            "priority_level": "medium",
            "theme_primary": "billing",
            "intent": "complaint",
            "requires_action": True,
            "entities": [],
            "processed_at": "2024-01-01T00:00:00Z",
        }
        with pytest.raises(DeserializationError) as exc_info:
            serializer.deserialize(json.dumps(data))
        assert exc_info.value.reason == "schema validation failed"
        assert any("sentiment_label" in d for d in exc_info.value.details)

    def test_rejects_invalid_priority_level(
        self, serializer: FeedbackAnalysisSerializer
    ) -> None:
        """Invalid priority_level is rejected."""
        data = {
            "feedback_id": "test-001",
            "sentiment_label": "neutral",
            "sentiment_score": 0.0,
            "priority_score": 0.5,
            "priority_level": "urgent",  # Invalid
            "theme_primary": "billing",
            "intent": "complaint",
            "requires_action": True,
            "entities": [],
            "processed_at": "2024-01-01T00:00:00Z",
        }
        with pytest.raises(DeserializationError) as exc_info:
            serializer.deserialize(json.dumps(data))
        assert exc_info.value.reason == "schema validation failed"
        assert any("priority_level" in d for d in exc_info.value.details)

    def test_rejects_invalid_timestamp_format(
        self, serializer: FeedbackAnalysisSerializer
    ) -> None:
        """Non-ISO 8601 UTC timestamp is rejected."""
        data = {
            "feedback_id": "test-001",
            "sentiment_label": "neutral",
            "sentiment_score": 0.0,
            "priority_score": 0.5,
            "priority_level": "medium",
            "theme_primary": "billing",
            "intent": "complaint",
            "requires_action": True,
            "entities": [],
            "processed_at": "January 1, 2024",  # Invalid format
        }
        with pytest.raises(DeserializationError) as exc_info:
            serializer.deserialize(json.dumps(data))
        assert "processed_at" in str(exc_info.value.details)

    def test_rejects_priority_score_out_of_range(
        self, serializer: FeedbackAnalysisSerializer
    ) -> None:
        """priority_score < 0.0 is rejected."""
        data = {
            "feedback_id": "test-001",
            "sentiment_label": "neutral",
            "sentiment_score": 0.0,
            "priority_score": -0.1,  # Out of range
            "priority_level": "medium",
            "theme_primary": "billing",
            "intent": "complaint",
            "requires_action": True,
            "entities": [],
            "processed_at": "2024-01-01T00:00:00Z",
        }
        with pytest.raises(DeserializationError) as exc_info:
            serializer.deserialize(json.dumps(data))
        assert any("priority_score" in d for d in exc_info.value.details)

    def test_rejects_entity_confidence_below_minimum(
        self, serializer: FeedbackAnalysisSerializer
    ) -> None:
        """Entity with confidence < 0.5 is rejected."""
        data = {
            "feedback_id": "test-001",
            "sentiment_label": "neutral",
            "sentiment_score": 0.0,
            "priority_score": 0.5,
            "priority_level": "medium",
            "theme_primary": "billing",
            "intent": "complaint",
            "requires_action": True,
            "entities": [
                {
                    "entity_type": "service_area",
                    "entity_value": "test",
                    "confidence": 0.3,  # Below minimum 0.5
                }
            ],
            "processed_at": "2024-01-01T00:00:00Z",
        }
        with pytest.raises(DeserializationError) as exc_info:
            serializer.deserialize(json.dumps(data))
        assert exc_info.value.reason == "schema validation failed"
        assert any("confidence" in d for d in exc_info.value.details)

    def test_rejects_invalid_entity_type(
        self, serializer: FeedbackAnalysisSerializer
    ) -> None:
        """Invalid entity_type is rejected."""
        data = {
            "feedback_id": "test-001",
            "sentiment_label": "neutral",
            "sentiment_score": 0.0,
            "priority_score": 0.5,
            "priority_level": "medium",
            "theme_primary": "billing",
            "intent": "complaint",
            "requires_action": True,
            "entities": [
                {
                    "entity_type": "unknown_type",  # Invalid
                    "entity_value": "test",
                    "confidence": 0.8,
                }
            ],
            "processed_at": "2024-01-01T00:00:00Z",
        }
        with pytest.raises(DeserializationError) as exc_info:
            serializer.deserialize(json.dumps(data))
        assert exc_info.value.reason == "schema validation failed"

    def test_accepts_valid_minimal_record(
        self, serializer: FeedbackAnalysisSerializer
    ) -> None:
        """A valid minimal record (no entities, null optionals) deserializes."""
        data = {
            "feedback_id": "test-001",
            "sentiment_label": "neutral",
            "sentiment_score": 0.0,
            "priority_score": 0.5,
            "priority_level": "medium",
            "theme_primary": "billing",
            "intent": "complaint",
            "requires_action": True,
            "entities": [],
            "processed_at": "2024-01-01T00:00:00Z",
        }
        result = serializer.deserialize(json.dumps(data))
        assert result.feedback_id == "test-001"
        assert result.entities == []
