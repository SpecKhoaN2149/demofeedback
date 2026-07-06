"""Unit tests for the Preprocessor class.

Tests cover text cleaning, PII masking, language detection, duplicate
detection, profanity flagging, and full preprocessing orchestration.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from nlp_processing.models.feedback_routing import (
    CanonicalFeedback,
    EngagementMetrics,
    SocialFeedback,
    WidgetFeedback,
)
from nlp_processing.preprocessing.preprocessor import Preprocessor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_social_feedback(
    message_text: str = "This is a test message",
    platform: str = "reddit",
    **kwargs,
) -> SocialFeedback:
    """Create a SocialFeedback instance for testing."""
    defaults = {
        "feedback_id": str(uuid.uuid4()),
        "source_type": "social",
        "platform": platform,
        "username_handle": "test_user",
        "post_id": str(uuid.uuid4()),
        "message_text": message_text,
        "post_url": "https://reddit.com/r/test/123",
        "created_at_original": "2024-01-01T10:00:00Z",
        "ingested_at": "2024-01-01T12:00:00Z",
        "language_code": "en",
        "engagement_metrics": EngagementMetrics(likes=5, replies=2, reposts=1),
        "recency_score": 0.95,
        "location": "Seattle, US",
    }
    defaults.update(kwargs)
    return SocialFeedback(**defaults)


def _make_widget_feedback(
    message_text: str = "This is a test message",
    **kwargs,
) -> WidgetFeedback:
    """Create a WidgetFeedback instance for testing."""
    defaults = {
        "feedback_id": str(uuid.uuid4()),
        "source_type": "widget",
        "submission_channel": "app_widget",
        "message_text": message_text,
        "created_at": "2024-01-01T12:00:00Z",
        "consent_to_contact": True,
        "customer_id": "cust_123",
        "account_type": "premium",
        "selected_category": None,
        "location": "Portland, US",
    }
    defaults.update(kwargs)
    return WidgetFeedback(**defaults)


# ---------------------------------------------------------------------------
# Tests: clean_text
# ---------------------------------------------------------------------------


class TestCleanText:
    """Tests for Preprocessor.clean_text()."""

    def test_removes_html_tags(self):
        pp = Preprocessor()
        result = pp.clean_text("<p>Hello <b>world</b></p>")
        assert result == "Hello world"

    def test_removes_self_closing_tags(self):
        pp = Preprocessor()
        result = pp.clean_text("Line one<br/>Line two")
        assert result == "Line one Line two"

    def test_unicode_nfc_normalization(self):
        pp = Preprocessor()
        # é as combining character (NFD) should become NFC
        nfd_text = "caf\u0065\u0301"  # e + combining acute
        result = pp.clean_text(nfd_text)
        import unicodedata

        assert unicodedata.is_normalized("NFC", result)

    def test_collapses_multiple_spaces(self):
        pp = Preprocessor()
        result = pp.clean_text("hello    world")
        assert result == "hello world"

    def test_collapses_mixed_whitespace(self):
        pp = Preprocessor()
        result = pp.clean_text("hello\t\n  world")
        assert result == "hello world"

    def test_trims_leading_trailing_whitespace(self):
        pp = Preprocessor()
        result = pp.clean_text("  hello world  ")
        assert result == "hello world"

    def test_empty_html_produces_empty_string(self):
        pp = Preprocessor()
        result = pp.clean_text("<p></p>")
        assert result == ""

    def test_preserves_normal_text(self):
        pp = Preprocessor()
        result = pp.clean_text("Normal text without issues")
        assert result == "Normal text without issues"

    def test_combined_cleaning(self):
        pp = Preprocessor()
        result = pp.clean_text("  <div>  Hello   <span>World</span>  </div>  ")
        assert result == "Hello World"


# ---------------------------------------------------------------------------
# Tests: detect_language
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    """Tests for Preprocessor.detect_language()."""

    def test_short_text_returns_und(self):
        pp = Preprocessor()
        assert pp.detect_language("hi") == "und"
        assert pp.detect_language("ab") == "und"
        assert pp.detect_language("") == "und"

    def test_single_char_returns_und(self):
        pp = Preprocessor()
        assert pp.detect_language("x") == "und"

    def test_detects_english(self):
        pp = Preprocessor()
        text = "The service has been very slow and the support team was not helpful"
        result = pp.detect_language(text)
        assert result == "en"

    def test_detects_spanish(self):
        pp = Preprocessor()
        text = "El servicio está muy lento y la conexión es terrible"
        result = pp.detect_language(text)
        assert result == "es"

    def test_no_recognizable_words_returns_und(self):
        pp = Preprocessor()
        # Numbers only
        assert pp.detect_language("12345 67890") == "und"

    def test_three_char_text_attempts_detection(self):
        pp = Preprocessor()
        # Exactly 3 characters - should attempt detection (not return und for length)
        result = pp.detect_language("the")
        assert result == "en"


# ---------------------------------------------------------------------------
# Tests: mask_pii
# ---------------------------------------------------------------------------


class TestMaskPii:
    """Tests for Preprocessor.mask_pii()."""

    def test_masks_email(self):
        pp = Preprocessor()
        text = "Contact me at john.doe@example.com for details"
        masked, original = pp.mask_pii(text)
        assert "[EMAIL]" in masked
        assert "john.doe@example.com" not in masked
        assert original == text

    def test_masks_phone_parentheses(self):
        pp = Preprocessor()
        text = "Call me at (555) 123-4567 please"
        masked, original = pp.mask_pii(text)
        assert "[PHONE]" in masked
        assert "(555) 123-4567" not in masked
        assert original == text

    def test_masks_phone_dashes(self):
        pp = Preprocessor()
        text = "My number is 555-123-4567"
        masked, original = pp.mask_pii(text)
        assert "[PHONE]" in masked
        assert "555-123-4567" not in masked
        assert original == text

    def test_masks_ssn(self):
        pp = Preprocessor()
        text = "My SSN is 123-45-6789"
        masked, original = pp.mask_pii(text)
        assert "[SSN]" in masked
        assert "123-45-6789" not in masked
        assert original == text

    def test_masks_multiple_pii(self):
        pp = Preprocessor()
        text = "Email test@test.com, phone 555-111-2222, SSN 111-22-3333"
        masked, original = pp.mask_pii(text)
        assert "[EMAIL]" in masked
        assert "[PHONE]" in masked
        assert "[SSN]" in masked
        assert original == text

    def test_no_pii_unchanged(self):
        pp = Preprocessor()
        text = "No personal info here"
        masked, original = pp.mask_pii(text)
        assert masked == text
        assert original == text

    def test_preserves_original(self):
        pp = Preprocessor()
        text = "Send to user@mail.com"
        masked, original = pp.mask_pii(text)
        assert original == "Send to user@mail.com"


# ---------------------------------------------------------------------------
# Tests: check_duplicate
# ---------------------------------------------------------------------------


class TestCheckDuplicate:
    """Tests for Preprocessor.check_duplicate()."""

    def test_first_submission_not_duplicate(self):
        pp = Preprocessor()
        result = pp.check_duplicate("hello world", "social")
        assert result is None

    def test_same_text_same_source_is_duplicate(self):
        pp = Preprocessor()
        # Register first
        pp._register_for_dedup(
            "hello world",
            "social",
            "id-1",
            datetime.now(timezone.utc).isoformat(),
        )
        # Check duplicate
        result = pp.check_duplicate("hello world", "social")
        assert result == "id-1"

    def test_case_insensitive_match(self):
        pp = Preprocessor()
        pp._register_for_dedup(
            "Hello World",
            "social",
            "id-1",
            datetime.now(timezone.utc).isoformat(),
        )
        # Different case should still match
        result = pp.check_duplicate("hello world", "social")
        assert result == "id-1"

    def test_different_source_not_duplicate(self):
        pp = Preprocessor()
        pp._register_for_dedup(
            "hello world",
            "social",
            "id-1",
            datetime.now(timezone.utc).isoformat(),
        )
        # Different source type - not a duplicate
        result = pp.check_duplicate("hello world", "widget")
        assert result is None

    def test_outside_window_not_duplicate(self):
        pp = Preprocessor()
        # Register with a timestamp 25 hours ago
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        pp._register_for_dedup("hello world", "social", "id-1", old_time)
        result = pp.check_duplicate("hello world", "social")
        assert result is None

    def test_increments_duplicate_count(self):
        pp = Preprocessor()
        pp._register_for_dedup(
            "hello world",
            "social",
            "id-1",
            datetime.now(timezone.utc).isoformat(),
        )
        pp.check_duplicate("hello world", "social")
        key = ("social", "hello world")
        assert pp._duplicate_store[key]["duplicate_count"] == 1

        # Second duplicate increments again
        pp.check_duplicate("HELLO WORLD", "social")
        assert pp._duplicate_store[key]["duplicate_count"] == 2


# ---------------------------------------------------------------------------
# Tests: profanity detection
# ---------------------------------------------------------------------------


class TestProfanityDetection:
    """Tests for profanity detection."""

    def test_detects_profanity(self):
        pp = Preprocessor()
        assert pp._check_profanity("This is a damn shame") is True

    def test_no_profanity(self):
        pp = Preprocessor()
        assert pp._check_profanity("This is a wonderful service") is False

    def test_case_insensitive(self):
        pp = Preprocessor()
        assert pp._check_profanity("What the HELL is going on") is True

    def test_custom_profanity_list(self):
        custom_list = frozenset({"badword", "verybad"})
        pp = Preprocessor(profanity_list=custom_list)
        assert pp._check_profanity("This contains badword") is True
        assert pp._check_profanity("This is fine") is False


# ---------------------------------------------------------------------------
# Tests: preprocess (full orchestration)
# ---------------------------------------------------------------------------


class TestPreprocess:
    """Tests for Preprocessor.preprocess() orchestration."""

    def test_social_feedback_produces_canonical(self):
        pp = Preprocessor()
        social = _make_social_feedback(message_text="The internet service is very slow today")
        result = pp.preprocess(social)
        assert result is not None
        assert isinstance(result, CanonicalFeedback)
        assert result.source_type == "social"
        assert result.processing_status == "preprocessed"
        assert result.cleaned_text == "The internet service is very slow today"

    def test_widget_feedback_produces_canonical(self):
        pp = Preprocessor()
        widget = _make_widget_feedback(message_text="The billing is wrong on my account")
        result = pp.preprocess(widget)
        assert result is not None
        assert isinstance(result, CanonicalFeedback)
        assert result.source_type == "widget"
        assert result.processing_status == "preprocessed"

    def test_empty_after_cleaning_marks_failed(self):
        pp = Preprocessor()
        social = _make_social_feedback(message_text="<p>  </p>")
        result = pp.preprocess(social)
        assert result is not None
        assert result.processing_status == "failed"
        assert result.metadata.get("reason") == "empty_after_cleaning"

    def test_pii_masked_in_output(self):
        pp = Preprocessor()
        widget = _make_widget_feedback(
            message_text="Email me at test@example.com about my bill"
        )
        result = pp.preprocess(widget)
        assert result is not None
        assert "[EMAIL]" in result.cleaned_text
        assert "test@example.com" not in result.cleaned_text
        # Original preserved in metadata
        assert "test@example.com" in result.metadata["original_text"]

    def test_duplicate_returns_none(self):
        pp = Preprocessor()
        fb1 = _make_social_feedback(message_text="Duplicate message here")
        fb2 = _make_social_feedback(message_text="Duplicate message here")

        result1 = pp.preprocess(fb1)
        assert result1 is not None

        result2 = pp.preprocess(fb2)
        assert result2 is None  # Duplicate discarded

    def test_profanity_flagged(self):
        pp = Preprocessor()
        widget = _make_widget_feedback(message_text="This damn service is broken")
        result = pp.preprocess(widget)
        assert result is not None
        assert result.profanity_detected is True

    def test_html_cleaned_in_output(self):
        pp = Preprocessor()
        social = _make_social_feedback(message_text="<b>Bold</b> and <i>italic</i> text")
        result = pp.preprocess(social)
        assert result is not None
        assert "<b>" not in result.cleaned_text
        assert "<i>" not in result.cleaned_text
        assert "Bold" in result.cleaned_text

    def test_detected_language_set(self):
        pp = Preprocessor()
        social = _make_social_feedback(
            message_text="The internet has been very slow and the support was not helpful"
        )
        result = pp.preprocess(social)
        assert result is not None
        assert result.detected_language == "en"

    def test_short_text_language_und(self):
        pp = Preprocessor()
        social = _make_social_feedback(message_text="hi")
        result = pp.preprocess(social)
        assert result is not None
        assert result.detected_language == "und"

    def test_metadata_includes_source_info(self):
        pp = Preprocessor()
        social = _make_social_feedback(message_text="The service is down in my area")
        result = pp.preprocess(social)
        assert result is not None
        assert "platform" in result.metadata
        assert result.metadata["platform"] == "reddit"
