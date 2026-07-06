"""Unit tests for the ThemeDetector (task 5.4, Req 5.1-5.5).

Tests cover:
* Basic theme detection with valid categories (Req 5.1)
* Secondary theme assignment (Req 5.2)
* Unclassified fallback when confidence < 0.3 (Req 5.3)
* Customer-provided selected_category weighting (Req 5.5)
* Transport failure graceful fallback
* Invalid theme filtering
* Edge cases (empty themes, malformed responses)
"""

from __future__ import annotations

import json

import pytest

from nlp_processing.enrichment.theme_detector import (
    CUSTOMER_CATEGORY_WEIGHT,
    THEME_CONFIDENCE_THRESHOLD,
    UNCLASSIFIED_THEME,
    VALID_THEME_CATEGORIES,
    ThemeDetector,
)
from nlp_processing.models.feedback_routing import CanonicalFeedback, ThemeResult
from nlp_processing.transport.client import (
    GeminiErrorKind,
    GeminiFailure,
    GeminiRequest,
    GeminiResult,
)


# ---------------------------------------------------------------------------
# Helpers / Fakes
# ---------------------------------------------------------------------------


def _make_feedback(
    text: str = "My internet has been really slow lately",
    metadata: dict | None = None,
) -> CanonicalFeedback:
    """Create a CanonicalFeedback record for testing."""
    return CanonicalFeedback(
        feedback_id="test-theme-001",
        source_type="widget",
        original_source_id="widget-sub-001",
        cleaned_text=text,
        detected_language="en",
        ingested_at="2024-01-15T10:00:00Z",
        metadata=metadata or {},
    )


def _make_success_generate(payload: dict):
    """A fake generate that returns a successful result with JSON payload."""
    call_count = {"n": 0}

    def _generate(request: GeminiRequest) -> GeminiResult:
        call_count["n"] += 1
        return GeminiResult(
            record_id=request.record_id, attempts=1, text=json.dumps(payload)
        )

    _generate.call_count = call_count  # type: ignore[attr-defined]
    return _generate


def _make_failure_generate(kind: GeminiErrorKind, message: str = "boom"):
    """A fake generate that returns a transport failure."""

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
# Test: Basic theme detection (Req 5.1)
# ---------------------------------------------------------------------------


class TestBasicThemeDetection:
    """Req 5.1: Assign primary_theme from ThemeCategory set."""

    def test_single_theme_above_threshold(self):
        """Single high-confidence theme → assigned as primary."""
        gen = _make_success_generate(
            {"themes": [{"theme": "billing", "confidence": 0.85}]}
        )
        detector = ThemeDetector(client=gen)
        result = detector.detect(_make_feedback())

        assert result.primary_theme == "billing"
        assert result.confidence == 0.85
        assert isinstance(result, ThemeResult)

    def test_highest_confidence_becomes_primary(self):
        """Multiple themes → highest confidence is primary."""
        gen = _make_success_generate(
            {
                "themes": [
                    {"theme": "equipment", "confidence": 0.5},
                    {"theme": "outage", "confidence": 0.9},
                    {"theme": "billing", "confidence": 0.6},
                ]
            }
        )
        detector = ThemeDetector(client=gen)
        result = detector.detect(_make_feedback())

        assert result.primary_theme == "outage"
        assert result.confidence == 0.9

    def test_all_valid_categories_accepted(self):
        """Each valid ThemeCategory is accepted as a primary theme."""
        for category in VALID_THEME_CATEGORIES:
            gen = _make_success_generate(
                {"themes": [{"theme": category, "confidence": 0.8}]}
            )
            detector = ThemeDetector(client=gen)
            result = detector.detect(_make_feedback())
            assert result.primary_theme == category


# ---------------------------------------------------------------------------
# Test: Secondary theme (Req 5.2)
# ---------------------------------------------------------------------------


class TestSecondaryTheme:
    """Req 5.2: Assign optional secondary_theme distinct from primary."""

    def test_secondary_assigned_when_above_threshold(self):
        """Second-highest theme above threshold → secondary assigned."""
        gen = _make_success_generate(
            {
                "themes": [
                    {"theme": "billing", "confidence": 0.85},
                    {"theme": "support_experience", "confidence": 0.5},
                ]
            }
        )
        detector = ThemeDetector(client=gen)
        result = detector.detect(_make_feedback())

        assert result.primary_theme == "billing"
        assert result.secondary_theme == "support_experience"

    def test_no_secondary_when_only_one_theme(self):
        """Only one theme → no secondary."""
        gen = _make_success_generate(
            {"themes": [{"theme": "outage", "confidence": 0.9}]}
        )
        detector = ThemeDetector(client=gen)
        result = detector.detect(_make_feedback())

        assert result.primary_theme == "outage"
        assert result.secondary_theme is None

    def test_no_secondary_when_second_below_threshold(self):
        """Second theme below confidence threshold → no secondary."""
        gen = _make_success_generate(
            {
                "themes": [
                    {"theme": "outage", "confidence": 0.9},
                    {"theme": "equipment", "confidence": 0.2},
                ]
            }
        )
        detector = ThemeDetector(client=gen)
        result = detector.detect(_make_feedback())

        assert result.primary_theme == "outage"
        assert result.secondary_theme is None


# ---------------------------------------------------------------------------
# Test: Unclassified fallback (Req 5.3)
# ---------------------------------------------------------------------------


class TestUnclassifiedFallback:
    """Req 5.3: confidence < 0.3 → primary_theme 'unclassified'."""

    def test_low_confidence_returns_unclassified(self):
        """Primary confidence below 0.3 → unclassified."""
        gen = _make_success_generate(
            {"themes": [{"theme": "billing", "confidence": 0.2}]}
        )
        detector = ThemeDetector(client=gen)
        result = detector.detect(_make_feedback())

        assert result.primary_theme == UNCLASSIFIED_THEME
        assert result.secondary_theme is None

    def test_exactly_at_threshold_is_classified(self):
        """Confidence exactly 0.3 → theme is assigned (>= threshold)."""
        gen = _make_success_generate(
            {"themes": [{"theme": "billing", "confidence": 0.3}]}
        )
        detector = ThemeDetector(client=gen)
        result = detector.detect(_make_feedback())

        assert result.primary_theme == "billing"

    def test_empty_themes_returns_unclassified(self):
        """Empty themes list → unclassified with 0.0 confidence."""
        gen = _make_success_generate({"themes": []})
        detector = ThemeDetector(client=gen)
        result = detector.detect(_make_feedback())

        assert result.primary_theme == UNCLASSIFIED_THEME
        assert result.confidence == 0.0

    def test_all_themes_below_threshold(self):
        """All candidates below threshold → unclassified."""
        gen = _make_success_generate(
            {
                "themes": [
                    {"theme": "billing", "confidence": 0.1},
                    {"theme": "outage", "confidence": 0.25},
                ]
            }
        )
        detector = ThemeDetector(client=gen)
        result = detector.detect(_make_feedback())

        assert result.primary_theme == UNCLASSIFIED_THEME


# ---------------------------------------------------------------------------
# Test: Customer category weighting (Req 5.5)
# ---------------------------------------------------------------------------


class TestCustomerCategoryWeighting:
    """Req 5.5: Weight customer-provided selected_category."""

    def test_customer_category_boosts_matching_nlp_theme(self):
        """Customer selects same as NLP → confidence boosted."""
        gen = _make_success_generate(
            {"themes": [{"theme": "speed_performance", "confidence": 0.6}]}
        )
        feedback = _make_feedback(metadata={"selected_category": "speed_performance"})
        detector = ThemeDetector(client=gen)
        result = detector.detect(feedback)

        assert result.primary_theme == "speed_performance"
        # Blended: 0.6 * 0.6 + 0.4 * 1.0 = 0.76
        expected_conf = 0.6 * (1 - CUSTOMER_CATEGORY_WEIGHT) + CUSTOMER_CATEGORY_WEIGHT * 1.0
        assert abs(result.confidence - expected_conf) < 1e-9

    def test_customer_category_added_when_nlp_misses_it(self):
        """Customer selects a category NLP didn't detect → added with customer weight."""
        gen = _make_success_generate(
            {"themes": [{"theme": "outage", "confidence": 0.5}]}
        )
        feedback = _make_feedback(metadata={"selected_category": "billing"})
        detector = ThemeDetector(client=gen)
        result = detector.detect(feedback)

        # NLP outage is scaled: 0.6 * 0.5 = 0.3; customer billing: 0.4
        # billing (0.4) > outage (0.3)
        assert result.primary_theme == "billing"
        assert result.confidence == CUSTOMER_CATEGORY_WEIGHT * 1.0

    def test_customer_category_alone_above_threshold(self):
        """No NLP themes + customer category → customer category used."""
        gen = _make_success_generate({"themes": []})
        feedback = _make_feedback(metadata={"selected_category": "installation"})
        detector = ThemeDetector(client=gen)
        result = detector.detect(feedback)

        assert result.primary_theme == "installation"
        assert result.confidence == CUSTOMER_CATEGORY_WEIGHT

    def test_invalid_customer_category_ignored(self):
        """Invalid selected_category in metadata → ignored."""
        gen = _make_success_generate(
            {"themes": [{"theme": "billing", "confidence": 0.7}]}
        )
        feedback = _make_feedback(metadata={"selected_category": "not_a_category"})
        detector = ThemeDetector(client=gen)
        result = detector.detect(feedback)

        # Should use NLP result unmodified
        assert result.primary_theme == "billing"
        assert result.confidence == 0.7

    def test_no_selected_category_in_metadata(self):
        """No selected_category → no customer weighting applied."""
        gen = _make_success_generate(
            {"themes": [{"theme": "billing", "confidence": 0.7}]}
        )
        feedback = _make_feedback(metadata={})
        detector = ThemeDetector(client=gen)
        result = detector.detect(feedback)

        assert result.primary_theme == "billing"
        assert result.confidence == 0.7


# ---------------------------------------------------------------------------
# Test: Transport failure fallback
# ---------------------------------------------------------------------------


class TestTransportFailure:
    """Theme detection gracefully handles transport failures."""

    def test_timeout_returns_unclassified(self):
        gen = _make_failure_generate(GeminiErrorKind.TIMEOUT, "timed out")
        detector = ThemeDetector(client=gen)
        result = detector.detect(_make_feedback())

        assert result.primary_theme == UNCLASSIFIED_THEME
        assert result.confidence == 0.0
        assert result.secondary_theme is None

    def test_auth_error_returns_unclassified(self):
        gen = _make_failure_generate(GeminiErrorKind.AUTH, "401")
        detector = ThemeDetector(client=gen)
        result = detector.detect(_make_feedback())

        assert result.primary_theme == UNCLASSIFIED_THEME
        assert result.confidence == 0.0

    def test_exhausted_retries_returns_unclassified(self):
        gen = _make_failure_generate(GeminiErrorKind.EXHAUSTED, "exhausted")
        detector = ThemeDetector(client=gen)
        result = detector.detect(_make_feedback())

        assert result.primary_theme == UNCLASSIFIED_THEME
        assert result.confidence == 0.0

    def test_malformed_json_returns_unclassified(self):
        """Invalid JSON → unclassified."""

        def _generate(request: GeminiRequest) -> GeminiResult:
            return GeminiResult(
                record_id=request.record_id, attempts=1, text="not valid json {"
            )

        detector = ThemeDetector(client=_generate)
        result = detector.detect(_make_feedback())

        assert result.primary_theme == UNCLASSIFIED_THEME
        assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Test: Invalid themes filtered
# ---------------------------------------------------------------------------


class TestInvalidThemeFiltering:
    """Themes not in ThemeCategory set are discarded."""

    def test_invalid_theme_names_filtered(self):
        """Only valid ThemeCategory values are considered."""
        gen = _make_success_generate(
            {
                "themes": [
                    {"theme": "unknown_category", "confidence": 0.95},
                    {"theme": "billing", "confidence": 0.6},
                ]
            }
        )
        detector = ThemeDetector(client=gen)
        result = detector.detect(_make_feedback())

        assert result.primary_theme == "billing"

    def test_all_invalid_themes_returns_unclassified(self):
        """All themes invalid → unclassified."""
        gen = _make_success_generate(
            {
                "themes": [
                    {"theme": "fake1", "confidence": 0.9},
                    {"theme": "fake2", "confidence": 0.8},
                ]
            }
        )
        detector = ThemeDetector(client=gen)
        result = detector.detect(_make_feedback())

        assert result.primary_theme == UNCLASSIFIED_THEME
        assert result.confidence == 0.0
