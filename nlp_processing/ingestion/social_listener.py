"""Social Listener ingestion service for NLP feedback routing.

Ingests public social media feedback from monitored platforms (Reddit, X, Facebook)
and produces validated SocialFeedback records. Implements recency scoring,
engagement metrics extraction, location extraction, and rate limit retry logic.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Literal

from ..models.feedback_routing import EngagementMetrics, SocialFeedback

logger = logging.getLogger(__name__)

# Maximum message text length before truncation (Req 1.1).
MAX_MESSAGE_LENGTH = 10_000

# Minimum message text length; posts shorter are discarded (Req 1.5).
MIN_MESSAGE_LENGTH = 3

# Recency score denominator: 720 hours = 30 days (Req 1.2).
RECENCY_HOURS_WINDOW = 720

# Rate limit retry configuration (Req 1.4).
INITIAL_BACKOFF_SECONDS = 30
MAX_BACKOFF_SECONDS = 15 * 60  # 15 minutes
MAX_CONSECUTIVE_FAILURES = 10

# Valid platforms for social ingestion.
VALID_PLATFORMS = frozenset({"reddit", "x", "facebook"})


class SocialListener:
    """Ingests public social media posts into SocialFeedback records.

    Responsibilities:
    - Validate incoming post data (platform, message length)
    - Compute recency_score based on post age
    - Extract engagement metrics (likes, replies, reposts/upvotes)
    - Extract location from geotag when available
    - Handle rate limit failures with exponential backoff retry
    """

    def __init__(self) -> None:
        self._consecutive_failures: dict[str, int] = {}
        self._platform_stopped: dict[str, bool] = {}

    def ingest_social(self, post_data: dict) -> SocialFeedback | None:
        """Ingest a single social media post and produce a SocialFeedback record.

        Args:
            post_data: Dictionary containing post information with keys:
                - platform: One of "reddit", "x", "facebook"
                - username_handle: Author handle (max 320 chars)
                - post_id: Unique post/comment identifier
                - message_text: The post content
                - post_url: Optional URL to the post
                - created_at_original: ISO 8601 UTC timestamp of original post
                - language_code: ISO 639-1 language code
                - engagement_metrics: Dict with likes, replies, reposts keys
                - geotag: Optional dict with city and country_code keys

        Returns:
            SocialFeedback record if validation passes, None if the post
            should be discarded (empty/short text, invalid platform).
        """
        # Validate platform
        platform = post_data.get("platform", "").lower()
        if platform not in VALID_PLATFORMS:
            logger.warning("Invalid platform '%s', discarding post", platform)
            return None

        # Extract and validate message_text (Req 1.5)
        message_text = post_data.get("message_text", "")
        if not message_text or len(message_text) < MIN_MESSAGE_LENGTH:
            # Discard silently for posts with < 3 chars (Req 1.5)
            return None

        # Truncate to max length (Req 1.1)
        if len(message_text) > MAX_MESSAGE_LENGTH:
            message_text = message_text[:MAX_MESSAGE_LENGTH]

        # Generate feedback_id
        feedback_id = str(uuid.uuid4())

        # Timestamps
        created_at_original = post_data.get("created_at_original", "")
        ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Compute recency_score (Req 1.2)
        recency_score = self._compute_recency_score(created_at_original, ingested_at)

        # Extract engagement metrics (Req 1.1)
        engagement_metrics = self._extract_engagement_metrics(
            post_data.get("engagement_metrics", {})
        )

        # Extract location from geotag (Req 1.3)
        location = self._extract_location(post_data.get("geotag"))

        # Extract username_handle (truncate to 320 chars per model constraint)
        username_handle = post_data.get("username_handle", "unknown")
        if len(username_handle) > 320:
            username_handle = username_handle[:320]

        # Build and return SocialFeedback record
        return SocialFeedback(
            feedback_id=feedback_id,
            source_type="social",
            platform=platform,  # type: ignore[arg-type]
            username_handle=username_handle,
            post_id=post_data.get("post_id", ""),
            message_text=message_text,
            post_url=post_data.get("post_url"),
            created_at_original=created_at_original,
            ingested_at=ingested_at,
            language_code=post_data.get("language_code", "und"),
            engagement_metrics=engagement_metrics,
            recency_score=recency_score,
            location=location,
        )

    def retry_with_backoff(
        self, platform: str, operation: callable
    ) -> object | None:
        """Execute an operation with exponential backoff retry on rate limit failures.

        Implements retry logic per Req 1.4:
        - Initial backoff: 30 seconds
        - Maximum backoff: 15 minutes
        - Stops after 10 consecutive failures for the platform

        Args:
            platform: The platform being accessed (for per-platform tracking).
            operation: A callable that may raise RateLimitError or ConnectionError.

        Returns:
            The result of the operation if successful, None if all retries exhausted.
        """
        if self._platform_stopped.get(platform, False):
            logger.error(
                "Platform '%s' has been stopped due to %d consecutive failures",
                platform,
                MAX_CONSECUTIVE_FAILURES,
            )
            return None

        backoff = INITIAL_BACKOFF_SECONDS

        while True:
            try:
                result = operation()
                # Reset failure counter on success
                self._consecutive_failures[platform] = 0
                return result
            except (RateLimitError, ConnectionError) as exc:
                failures = self._consecutive_failures.get(platform, 0) + 1
                self._consecutive_failures[platform] = failures

                logger.warning(
                    "Platform '%s' failure %d/%d: %s",
                    platform,
                    failures,
                    MAX_CONSECUTIVE_FAILURES,
                    exc,
                )

                if failures >= MAX_CONSECUTIVE_FAILURES:
                    self._platform_stopped[platform] = True
                    logger.error(
                        "Platform '%s' stopped after %d consecutive failures",
                        platform,
                        MAX_CONSECUTIVE_FAILURES,
                    )
                    return None

                # Exponential backoff with cap
                logger.info(
                    "Retrying platform '%s' in %d seconds", platform, backoff
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    def reset_platform(self, platform: str) -> None:
        """Reset failure tracking for a platform, allowing retries again."""
        self._consecutive_failures.pop(platform, None)
        self._platform_stopped.pop(platform, None)

    def is_platform_stopped(self, platform: str) -> bool:
        """Check if a platform has been stopped due to consecutive failures."""
        return self._platform_stopped.get(platform, False)

    @staticmethod
    def _compute_recency_score(
        created_at_original: str, ingested_at: str
    ) -> float:
        """Compute recency score: max(0.0, 1.0 - (elapsed_hours / 720)).

        A score of 1.0 means the post was ingested at creation time.
        A score of 0.0 means the post is 30+ days old.

        Args:
            created_at_original: ISO 8601 UTC timestamp of original post.
            ingested_at: ISO 8601 UTC timestamp of ingestion.

        Returns:
            Recency score clamped to [0.0, 1.0].
        """
        try:
            created_dt = _parse_iso_timestamp(created_at_original)
            ingested_dt = _parse_iso_timestamp(ingested_at)

            elapsed_seconds = (ingested_dt - created_dt).total_seconds()
            # If ingested_at is before created_at (clock skew), treat as 0 elapsed
            if elapsed_seconds < 0:
                elapsed_seconds = 0

            elapsed_hours = elapsed_seconds / 3600.0
            score = max(0.0, 1.0 - (elapsed_hours / RECENCY_HOURS_WINDOW))
            return score
        except (ValueError, TypeError):
            # If timestamps can't be parsed, default to 0.5 (middle score)
            logger.warning(
                "Could not parse timestamps for recency score: "
                "created_at='%s', ingested_at='%s'",
                created_at_original,
                ingested_at,
            )
            return 0.5

    @staticmethod
    def _extract_engagement_metrics(
        metrics_data: dict | None,
    ) -> EngagementMetrics:
        """Extract engagement metrics from post data.

        Handles platform-specific naming:
        - likes: likes, favorites, upvotes
        - replies: replies, comments
        - reposts: reposts, retweets, shares, upvotes (for reposts context)

        Args:
            metrics_data: Dictionary with engagement counts.

        Returns:
            EngagementMetrics with non-negative integer values.
        """
        if not metrics_data:
            return EngagementMetrics(likes=0, replies=0, reposts=0)

        likes = _safe_int(
            metrics_data.get("likes")
            or metrics_data.get("favorites")
            or metrics_data.get("upvotes", 0)
        )

        replies = _safe_int(
            metrics_data.get("replies") or metrics_data.get("comments", 0)
        )

        reposts = _safe_int(
            metrics_data.get("reposts")
            or metrics_data.get("retweets")
            or metrics_data.get("shares", 0)
        )

        return EngagementMetrics(
            likes=max(0, likes),
            replies=max(0, replies),
            reposts=max(0, reposts),
        )

    @staticmethod
    def _extract_location(geotag: dict | None) -> str | None:
        """Extract location string from geotag data (Req 1.3).

        Args:
            geotag: Optional dict with 'city' and 'country_code' keys.

        Returns:
            Location string in "City, CC" format, or None if geotag unavailable.
        """
        if not geotag:
            return None

        city = geotag.get("city", "").strip()
        country_code = geotag.get("country_code", "").strip()

        if city and country_code:
            return f"{city}, {country_code}"
        elif city:
            return city
        elif country_code:
            return country_code

        return None


class RateLimitError(Exception):
    """Raised when a platform API returns a rate limit response."""

    pass


def _parse_iso_timestamp(timestamp_str: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp string into a datetime object.

    Handles formats:
    - 2024-01-15T10:30:00Z
    - 2024-01-15T10:30:00+00:00
    - 2024-01-15T10:30:00.123456Z

    Args:
        timestamp_str: ISO 8601 formatted string.

    Returns:
        Timezone-aware datetime in UTC.

    Raises:
        ValueError: If the string cannot be parsed.
    """
    if not timestamp_str:
        raise ValueError("Empty timestamp string")

    # Normalize 'Z' suffix to '+00:00' for fromisoformat compatibility
    normalized = timestamp_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)

    # Ensure timezone awareness
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt


def _safe_int(value: object) -> int:
    """Convert a value to a non-negative integer, defaulting to 0.

    Args:
        value: Any value that might be an integer, string, or None.

    Returns:
        Non-negative integer representation of the value.
    """
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


__all__ = [
    "SocialListener",
    "RateLimitError",
    "MAX_MESSAGE_LENGTH",
    "MIN_MESSAGE_LENGTH",
    "RECENCY_HOURS_WINDOW",
    "INITIAL_BACKOFF_SECONDS",
    "MAX_BACKOFF_SECONDS",
    "MAX_CONSECUTIVE_FAILURES",
    "VALID_PLATFORMS",
]
