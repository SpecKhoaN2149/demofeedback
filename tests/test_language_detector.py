"""Unit tests for LanguageDetector (task 6.3).

Tests:
1. Supported language set configuration (default and custom)
2. English text detection with high confidence
3. Unsupported language fallback
4. Transport failure graceful degradation
5. Output format of LanguageDetectionResult

Requirements: 5.1, 5.2, 5.3, 5.4
"""

from __future__ import annotations

import json

from nlp_processing.enrichment.language import (
    DEFAULT_SUPPORTED_LANGUAGES,
    LanguageDetector,
)
from nlp_processing.models.enhancements import LanguageDetectionResult
from nlp_processing.models.records import FeedbackRecord
from nlp_processing.transport.client import (
    GeminiErrorKind,
    GeminiFailure,
    GeminiRequest,
    GeminiResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_record(record_id: str = "rec-1", text: str = "Hello world") -> FeedbackRecord:
    """Create a minimal FeedbackRecord for testing."""
    return FeedbackRecord(
        id=record_id,
        source_channel="email",
        cleaned_text=text,
        metadata={"origin": "test"},
    )


def make_success_generate(language_code: str, confidence: float):
    """A fake generate function returning a successful language detection result."""

    def _generate(request: GeminiRequest) -> GeminiResult:
        payload = {"language_code": language_code, "confidence": confidence}
        return GeminiResult(
            record_id=request.record_id,
            attempts=1,
            text=json.dumps(payload),
        )

    return _generate


def make_failure_generate(kind: GeminiErrorKind = GeminiErrorKind.TIMEOUT, message: str = "timed out"):
    """A fake generate function returning a transport failure."""

    def _generate(request: GeminiRequest) -> GeminiResult:
        return GeminiResult(
            record_id=request.record_id,
            attempts=1,
            failure=GeminiFailure(
                record_id=request.record_id,
                kind=kind,
                message=message,
                attempts=1,
            ),
        )

    return _generate


# ---------------------------------------------------------------------------
# Test 1: Supported language set configuration (Req 5.2)
# ---------------------------------------------------------------------------


class TestSupportedLanguageSetConfiguration:
    """Verify default and custom supported language sets."""

    def test_default_supported_languages(self):
        """Default supported set is {"en", "es", "fr", "de", "pt"}."""
        detector = LanguageDetector(client=make_success_generate("en", 0.95))
        assert detector.supported_languages == frozenset({"en", "es", "fr", "de", "pt"})

    def test_default_matches_module_constant(self):
        """Default set matches the module-level DEFAULT_SUPPORTED_LANGUAGES."""
        detector = LanguageDetector(client=make_success_generate("en", 0.95))
        assert detector.supported_languages == DEFAULT_SUPPORTED_LANGUAGES

    def test_custom_supported_languages(self):
        """A custom supported set can be passed at construction."""
        custom = frozenset({"en", "ja", "zh"})
        detector = LanguageDetector(
            client=make_success_generate("ja", 0.9),
            supported_languages=custom,
        )
        assert detector.supported_languages == custom


# ---------------------------------------------------------------------------
# Test 2: English text detection with high confidence (Req 5.1, 5.3)
# ---------------------------------------------------------------------------


class TestEnglishDetectionHighConfidence:
    """Verify that English detection with confidence >= 0.6 returns correct result."""

    def test_english_detected_with_high_confidence(self):
        """Fake returns "en" with confidence 0.95 → result has language_code="en", is_uncertain=False."""
        detector = LanguageDetector(client=make_success_generate("en", 0.95))
        record = make_record("rec-en", "This is a test in English")

        result = detector.detect(record)

        assert result.language_code == "en"
        assert result.confidence == 0.95
        assert result.is_uncertain is False
        assert result.note is None
        assert result.record_id == "rec-en"

    def test_supported_non_english_detected_with_high_confidence(self):
        """Fake returns "es" with confidence 0.88 → result has language_code="es", is_uncertain=False."""
        detector = LanguageDetector(client=make_success_generate("es", 0.88))
        record = make_record("rec-es", "Hola mundo")

        result = detector.detect(record)

        assert result.language_code == "es"
        assert result.confidence == 0.88
        assert result.is_uncertain is False
        assert result.note is None


# ---------------------------------------------------------------------------
# Test 3: Unsupported language fallback (Req 5.4)
# ---------------------------------------------------------------------------


class TestUnsupportedLanguageFallback:
    """Verify fallback to English when detected language is not in supported set."""

    def test_unsupported_language_defaults_to_english(self):
        """Fake returns "ja" with confidence 0.9 → result has language_code="en", is_uncertain=True."""
        detector = LanguageDetector(client=make_success_generate("ja", 0.9))
        record = make_record("rec-ja", "こんにちは世界")

        result = detector.detect(record)

        assert result.language_code == "en"
        assert result.confidence == 0.9
        assert result.is_uncertain is True
        assert result.note is not None
        assert "Unsupported" in result.note

    def test_low_confidence_defaults_to_english(self):
        """Fake returns "en" with confidence 0.4 → defaults to "en" with is_uncertain=True."""
        detector = LanguageDetector(client=make_success_generate("en", 0.4))
        record = make_record("rec-low", "ambiguous text")

        result = detector.detect(record)

        assert result.language_code == "en"
        assert result.confidence == 0.4
        assert result.is_uncertain is True
        assert result.note is not None


# ---------------------------------------------------------------------------
# Test 4: Transport failure graceful degradation (Req 5.4)
# ---------------------------------------------------------------------------


class TestTransportFailureGracefulDegradation:
    """Verify graceful degradation when transport fails."""

    def test_timeout_failure_defaults_to_english(self):
        """Fake returns GeminiResult(ok=False) → result has language_code="en", confidence=0.0, is_uncertain=True."""
        detector = LanguageDetector(client=make_failure_generate(GeminiErrorKind.TIMEOUT, "timed out"))
        record = make_record("rec-fail", "Some text")

        result = detector.detect(record)

        assert result.language_code == "en"
        assert result.confidence == 0.0
        assert result.is_uncertain is True
        assert result.note is not None
        assert "failed" in result.note.lower()

    def test_exhausted_failure_defaults_to_english(self):
        """Exhausted retries also gracefully defaults to English."""
        detector = LanguageDetector(
            client=make_failure_generate(GeminiErrorKind.EXHAUSTED, "exhausted 5 attempts")
        )
        record = make_record("rec-exhaust", "Another text")

        result = detector.detect(record)

        assert result.language_code == "en"
        assert result.confidence == 0.0
        assert result.is_uncertain is True
        assert result.note is not None

    def test_auth_failure_defaults_to_english(self):
        """Auth failure also gracefully defaults to English."""
        detector = LanguageDetector(
            client=make_failure_generate(GeminiErrorKind.AUTH, "401 unauthorized")
        )
        record = make_record("rec-auth", "Text here")

        result = detector.detect(record)

        assert result.language_code == "en"
        assert result.confidence == 0.0
        assert result.is_uncertain is True


# ---------------------------------------------------------------------------
# Test 5: Output format of LanguageDetectionResult (Req 5.3, 5.5)
# ---------------------------------------------------------------------------


class TestOutputFormat:
    """Verify returned LanguageDetectionResult has all expected fields."""

    def test_result_is_language_detection_result_instance(self):
        """detect() returns a LanguageDetectionResult instance."""
        detector = LanguageDetector(client=make_success_generate("en", 0.95))
        record = make_record("rec-fmt", "Test text")

        result = detector.detect(record)

        assert isinstance(result, LanguageDetectionResult)

    def test_result_has_all_expected_fields(self):
        """Result has record_id, language_code, confidence, is_uncertain, and note fields."""
        detector = LanguageDetector(client=make_success_generate("fr", 0.85))
        record = make_record("rec-fields", "Bonjour le monde")

        result = detector.detect(record)

        # All five fields are present and accessible
        assert hasattr(result, "record_id")
        assert hasattr(result, "language_code")
        assert hasattr(result, "confidence")
        assert hasattr(result, "is_uncertain")
        assert hasattr(result, "note")

        # Field values match expectations
        assert result.record_id == "rec-fields"
        assert result.language_code == "fr"
        assert result.confidence == 0.85
        assert result.is_uncertain is False
        assert result.note is None

    def test_record_id_propagated_from_feedback_record(self):
        """The result's record_id matches the input FeedbackRecord's id."""
        detector = LanguageDetector(client=make_success_generate("de", 0.75))
        record = make_record("unique-record-123", "Hallo Welt")

        result = detector.detect(record)

        assert result.record_id == "unique-record-123"

    def test_confidence_is_float_in_valid_range(self):
        """Confidence score is a float in [0.0, 1.0]."""
        detector = LanguageDetector(client=make_success_generate("pt", 0.7))
        record = make_record("rec-range", "Olá mundo")

        result = detector.detect(record)

        assert isinstance(result.confidence, float)
        assert 0.0 <= result.confidence <= 1.0
