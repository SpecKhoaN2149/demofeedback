"""Unit tests for the Social Listener ingestion service (task 2.1).

These cover the validation and ingestion rules from Requirement 1:
- Create SocialFeedback records with all required fields (Req 1.1)
- Compute recency_score correctly (Req 1.2)
- Extract location from geotag (Req 1.3)
- Rate limit retry with exponential backoff (Req 1.4)
- Discard posts with message_text < 3 chars (Req 1.5)
- Truncate message_text to 10000 chars (Req 1.1)
"""

import time
from unittest.mock import patch

from nlp_processing.ingestion.social_listener import (
    INITIAL_BACKOFF_SECONDS,
    MAX_CONSECUTIVE_FAILURES,
    MAX_MESSAGE_LENGTH,
    MIN_MESSAGE_LENGTH,
    RECENCY_HOURS_WINDOW,
    RateLimitError,
    SocialListener,
)
from nlp_processing.models.feedback_routing import EngagementMetrics, SocialFeedback


def _post_data(
    platform="reddit",
    message_text="This is a valid post with enough characters",
    created_at_original="2024-01-15T10:00:00Z",
    **kwargs,
):
    """Helper to build a minimal valid post data dict."""
    data = {
        "platform": platform,
        "username_handle": "test_user",
        "post_id": "post_123",
        "message_text": message_text,
        "post_url": "https://reddit.com/r/test/post_123",
        "created_at_original": created_at_original,
        "language_code": "en",
        "engagement_metrics": {"likes": 10, "replies": 5, "reposts": 2},
    }
    data.update(kwargs)
    return data


class TestSuccessfulIngestion:
    """Tests that valid post data produces SocialFeedback records (Req 1.1)."""

    def test_valid_post_produces_social_feedback(self):
        listener = SocialListener()
        result = listener.ingest_social(_post_data())

        assert isinstance(result, SocialFeedback)
        assert result.source_type == "social"
        assert result.platform == "reddit"
        assert result.username_handle == "test_user"
        assert result.post_id == "post_123"
        assert result.message_text == "This is a valid post with enough characters"
        assert result.language_code == "en"

    def test_generates_uuid_feedback_id(self):
        listener = SocialListener()
        result = listener.ingest_social(_post_data())

        assert isinstance(result, SocialFeedback)
        assert result.feedback_id
        assert len(result.feedback_id) == 36  # UUID format

    def test_ingested_at_is_populated_with_iso_utc(self):
        listener = SocialListener()
        result = listener.ingest_social(_post_data())

        assert isinstance(result, SocialFeedback)
        assert result.ingested_at
        assert "T" in result.ingested_at
        assert result.ingested_at.endswith("Z")

    def test_post_url_is_preserved(self):
        listener = SocialListener()
        result = listener.ingest_social(_post_data())

        assert isinstance(result, SocialFeedback)
        assert result.post_url == "https://reddit.com/r/test/post_123"

    def test_accepts_all_valid_platforms(self):
        listener = SocialListener()
        for platform in ("reddit", "x", "facebook"):
            result = listener.ingest_social(_post_data(platform=platform))
            assert isinstance(result, SocialFeedback), (
                f"Expected SocialFeedback for platform '{platform}'"
            )
            assert result.platform == platform


class TestMessageTextValidation:
    """Tests for message_text validation (Req 1.1, 1.5)."""

    def test_discards_empty_message_text(self):
        listener = SocialListener()
        result = listener.ingest_social(_post_data(message_text=""))
        assert result is None

    def test_discards_message_text_one_char(self):
        listener = SocialListener()
        result = listener.ingest_social(_post_data(message_text="a"))
        assert result is None

    def test_discards_message_text_two_chars(self):
        listener = SocialListener()
        result = listener.ingest_social(_post_data(message_text="ab"))
        assert result is None

    def test_accepts_message_text_three_chars(self):
        listener = SocialListener()
        result = listener.ingest_social(_post_data(message_text="abc"))
        assert isinstance(result, SocialFeedback)
        assert result.message_text == "abc"

    def test_truncates_message_text_over_limit(self):
        listener = SocialListener()
        long_text = "x" * (MAX_MESSAGE_LENGTH + 500)
        result = listener.ingest_social(_post_data(message_text=long_text))

        assert isinstance(result, SocialFeedback)
        assert len(result.message_text) == MAX_MESSAGE_LENGTH

    def test_preserves_message_text_at_limit(self):
        listener = SocialListener()
        text = "y" * MAX_MESSAGE_LENGTH
        result = listener.ingest_social(_post_data(message_text=text))

        assert isinstance(result, SocialFeedback)
        assert len(result.message_text) == MAX_MESSAGE_LENGTH


class TestPlatformValidation:
    """Tests for platform validation."""

    def test_rejects_invalid_platform(self):
        listener = SocialListener()
        result = listener.ingest_social(_post_data(platform="tiktok"))
        assert result is None

    def test_rejects_empty_platform(self):
        listener = SocialListener()
        result = listener.ingest_social(_post_data(platform=""))
        assert result is None

    def test_platform_is_case_insensitive(self):
        listener = SocialListener()
        result = listener.ingest_social(_post_data(platform="Reddit"))
        assert isinstance(result, SocialFeedback)
        assert result.platform == "reddit"


class TestRecencyScore:
    """Tests for recency_score calculation (Req 1.2)."""

    def test_score_is_one_when_ingested_at_creation(self):
        listener = SocialListener()
        ts = "2024-01-15T10:00:00Z"
        score = listener._compute_recency_score(ts, ts)
        assert score == 1.0

    def test_score_is_zero_when_30_days_old(self):
        listener = SocialListener()
        created = "2024-01-01T00:00:00Z"
        ingested = "2024-01-31T00:00:00Z"  # 30 days = 720 hours
        score = listener._compute_recency_score(created, ingested)
        assert score == 0.0

    def test_score_is_zero_when_older_than_30_days(self):
        listener = SocialListener()
        created = "2024-01-01T00:00:00Z"
        ingested = "2024-02-15T00:00:00Z"  # 45 days > 720 hours
        score = listener._compute_recency_score(created, ingested)
        assert score == 0.0

    def test_score_is_half_at_15_days(self):
        listener = SocialListener()
        created = "2024-01-01T00:00:00Z"
        ingested = "2024-01-16T00:00:00Z"  # 15 days = 360 hours
        score = listener._compute_recency_score(created, ingested)
        assert abs(score - 0.5) < 0.001

    def test_score_formula_matches_spec(self):
        """Verify: max(0.0, 1.0 - (elapsed_hours / 720))"""
        listener = SocialListener()
        # 12 hours elapsed
        created = "2024-01-15T00:00:00Z"
        ingested = "2024-01-15T12:00:00Z"
        score = listener._compute_recency_score(created, ingested)
        expected = max(0.0, 1.0 - (12.0 / 720.0))
        assert abs(score - expected) < 1e-9

    def test_score_clamped_between_zero_and_one(self):
        listener = SocialListener()
        # Even with negative elapsed (clock skew), should handle gracefully
        created = "2024-01-15T12:00:00Z"
        ingested = "2024-01-15T10:00:00Z"  # ingested before created
        score = listener._compute_recency_score(created, ingested)
        assert 0.0 <= score <= 1.0

    def test_score_in_social_feedback_record(self):
        listener = SocialListener()
        result = listener.ingest_social(
            _post_data(created_at_original="2024-01-15T10:00:00Z")
        )
        assert isinstance(result, SocialFeedback)
        assert 0.0 <= result.recency_score <= 1.0


class TestEngagementMetrics:
    """Tests for engagement_metrics extraction (Req 1.1)."""

    def test_extracts_likes_replies_reposts(self):
        listener = SocialListener()
        result = listener.ingest_social(
            _post_data(engagement_metrics={"likes": 100, "replies": 20, "reposts": 5})
        )

        assert isinstance(result, SocialFeedback)
        assert result.engagement_metrics.likes == 100
        assert result.engagement_metrics.replies == 20
        assert result.engagement_metrics.reposts == 5

    def test_defaults_to_zero_when_missing(self):
        listener = SocialListener()
        result = listener.ingest_social(_post_data(engagement_metrics={}))

        assert isinstance(result, SocialFeedback)
        assert result.engagement_metrics.likes == 0
        assert result.engagement_metrics.replies == 0
        assert result.engagement_metrics.reposts == 0

    def test_handles_none_engagement_metrics(self):
        listener = SocialListener()
        result = listener.ingest_social(_post_data(engagement_metrics=None))

        assert isinstance(result, SocialFeedback)
        assert result.engagement_metrics.likes == 0
        assert result.engagement_metrics.replies == 0
        assert result.engagement_metrics.reposts == 0

    def test_handles_platform_specific_names_upvotes(self):
        listener = SocialListener()
        metrics = {"upvotes": 50, "comments": 10}
        result = listener.ingest_social(_post_data(engagement_metrics=metrics))

        assert isinstance(result, SocialFeedback)
        assert result.engagement_metrics.likes == 50
        assert result.engagement_metrics.replies == 10

    def test_handles_platform_specific_names_retweets(self):
        listener = SocialListener()
        metrics = {"likes": 30, "replies": 5, "retweets": 15}
        result = listener.ingest_social(
            _post_data(platform="x", engagement_metrics=metrics)
        )

        assert isinstance(result, SocialFeedback)
        assert result.engagement_metrics.reposts == 15

    def test_negative_values_clamped_to_zero(self):
        listener = SocialListener()
        metrics = {"likes": -5, "replies": -1, "reposts": -10}
        result = listener.ingest_social(_post_data(engagement_metrics=metrics))

        assert isinstance(result, SocialFeedback)
        assert result.engagement_metrics.likes == 0
        assert result.engagement_metrics.replies == 0
        assert result.engagement_metrics.reposts == 0


class TestLocationExtraction:
    """Tests for location extraction from geotag (Req 1.3)."""

    def test_extracts_city_and_country_code(self):
        listener = SocialListener()
        result = listener.ingest_social(
            _post_data(geotag={"city": "Seattle", "country_code": "US"})
        )

        assert isinstance(result, SocialFeedback)
        assert result.location == "Seattle, US"

    def test_location_is_none_when_no_geotag(self):
        listener = SocialListener()
        result = listener.ingest_social(_post_data())

        assert isinstance(result, SocialFeedback)
        assert result.location is None

    def test_location_is_none_for_empty_geotag(self):
        listener = SocialListener()
        result = listener.ingest_social(_post_data(geotag={}))

        assert isinstance(result, SocialFeedback)
        assert result.location is None

    def test_location_city_only_when_no_country_code(self):
        listener = SocialListener()
        result = listener.ingest_social(
            _post_data(geotag={"city": "London", "country_code": ""})
        )

        assert isinstance(result, SocialFeedback)
        assert result.location == "London"

    def test_location_country_code_only_when_no_city(self):
        listener = SocialListener()
        result = listener.ingest_social(
            _post_data(geotag={"city": "", "country_code": "GB"})
        )

        assert isinstance(result, SocialFeedback)
        assert result.location == "GB"


class TestRateLimitRetry:
    """Tests for rate limit retry with exponential backoff (Req 1.4)."""

    @patch("time.sleep")
    def test_retries_on_rate_limit_error(self, mock_sleep):
        listener = SocialListener()
        call_count = [0]

        def operation():
            call_count[0] += 1
            if call_count[0] < 3:
                raise RateLimitError("Rate limited")
            return "success"

        result = listener.retry_with_backoff("reddit", operation)
        assert result == "success"
        assert call_count[0] == 3
        # Should have slept twice (before 2nd and 3rd attempts)
        assert mock_sleep.call_count == 2

    @patch("time.sleep")
    def test_exponential_backoff_starts_at_30s(self, mock_sleep):
        listener = SocialListener()
        call_count = [0]

        def operation():
            call_count[0] += 1
            if call_count[0] < 4:
                raise RateLimitError("Rate limited")
            return "success"

        listener.retry_with_backoff("reddit", operation)
        # Backoff: 30, 60, 120
        assert mock_sleep.call_args_list[0][0][0] == 30
        assert mock_sleep.call_args_list[1][0][0] == 60
        assert mock_sleep.call_args_list[2][0][0] == 120

    @patch("time.sleep")
    def test_backoff_capped_at_15_minutes(self, mock_sleep):
        listener = SocialListener()
        call_count = [0]

        def operation():
            call_count[0] += 1
            if call_count[0] < 9:
                raise RateLimitError("Rate limited")
            return "success"

        listener.retry_with_backoff("reddit", operation)
        # Backoff sequence: 30, 60, 120, 240, 480, 900, 900, 900
        # (max 15 min = 900s reached at iteration 6)
        for call in mock_sleep.call_args_list:
            assert call[0][0] <= 900

    @patch("time.sleep")
    def test_stops_after_10_consecutive_failures(self, mock_sleep):
        listener = SocialListener()

        def always_fail():
            raise RateLimitError("Rate limited")

        result = listener.retry_with_backoff("reddit", always_fail)
        assert result is None
        assert listener.is_platform_stopped("reddit") is True

    @patch("time.sleep")
    def test_success_resets_failure_counter(self, mock_sleep):
        listener = SocialListener()
        call_count = [0]

        def fail_twice():
            call_count[0] += 1
            if call_count[0] <= 2:
                raise RateLimitError("Rate limited")
            return "success"

        listener.retry_with_backoff("reddit", fail_twice)
        # Counter should be reset after success
        assert listener._consecutive_failures.get("reddit", 0) == 0

    @patch("time.sleep")
    def test_stopped_platform_returns_none_immediately(self, mock_sleep):
        listener = SocialListener()
        listener._platform_stopped["reddit"] = True

        result = listener.retry_with_backoff("reddit", lambda: "should not run")
        assert result is None
        mock_sleep.assert_not_called()

    def test_reset_platform_clears_stopped_state(self):
        listener = SocialListener()
        listener._platform_stopped["reddit"] = True
        listener._consecutive_failures["reddit"] = 10

        listener.reset_platform("reddit")
        assert listener.is_platform_stopped("reddit") is False
        assert listener._consecutive_failures.get("reddit") is None

    @patch("time.sleep")
    def test_retries_on_connection_error(self, mock_sleep):
        listener = SocialListener()
        call_count = [0]

        def operation():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ConnectionError("Connection refused")
            return "success"

        result = listener.retry_with_backoff("x", operation)
        assert result == "success"
        assert call_count[0] == 2


class TestUsernameHandle:
    """Tests for username_handle handling."""

    def test_username_handle_truncated_to_320(self):
        listener = SocialListener()
        long_handle = "u" * 400
        result = listener.ingest_social(_post_data(username_handle=long_handle))

        assert isinstance(result, SocialFeedback)
        assert len(result.username_handle) == 320

    def test_defaults_to_unknown_when_missing(self):
        listener = SocialListener()
        data = _post_data()
        del data["username_handle"]
        result = listener.ingest_social(data)

        assert isinstance(result, SocialFeedback)
        assert result.username_handle == "unknown"
