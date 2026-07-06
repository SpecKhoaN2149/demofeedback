"""Preprocessor: text cleaning, PII masking, deduplication, and standardization.

This module implements the Preprocessor class which transforms raw
SocialFeedback and WidgetFeedback records into unified CanonicalFeedback
records (Requirements 3.1–3.11).

Operations performed:
- HTML tag removal (Req 3.2)
- Unicode NFC normalization (Req 3.2)
- Whitespace collapse and trim (Req 3.2)
- Language detection with ISO 639-1 codes (Req 3.3, 3.4)
- PII masking for email, phone, SSN (Req 3.6)
- Duplicate detection within 24h window (Req 3.5)
- Profanity detection flag (Req 3.7)
- Timestamp standardization (Req 3.8, 3.9)
- Empty-after-cleaning failure marking (Req 3.11)
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from ..models.feedback_routing import (
    CanonicalFeedback,
    SocialFeedback,
    WidgetFeedback,
)

# ---------------------------------------------------------------------------
# Default profanity word list (configurable)
# ---------------------------------------------------------------------------

DEFAULT_PROFANITY_LIST: frozenset[str] = frozenset(
    {
        "fuck",
        "shit",
        "ass",
        "damn",
        "bitch",
        "bastard",
        "crap",
        "dick",
        "piss",
        "hell",
    }
)

# ---------------------------------------------------------------------------
# PII regex patterns
# ---------------------------------------------------------------------------

# Email: standard RFC-5322 simplified pattern
_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# Phone: US phone numbers in various formats
# Matches: (xxx) xxx-xxxx, xxx-xxx-xxxx, xxx.xxx.xxxx, +1xxxxxxxxxx, etc.
_PHONE_PATTERN = re.compile(
    r"(?:\+?1[-.\s]?)?"  # optional country code
    r"(?:\(?\d{3}\)?[-.\s]?)"  # area code
    r"\d{3}[-.\s]?"  # exchange
    r"\d{4}\b"  # subscriber
)

# SSN: xxx-xx-xxxx pattern
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# HTML tag removal
_HTML_TAG_PATTERN = re.compile(r"<[^>]*>")

# Multiple whitespace collapse
_MULTI_WHITESPACE_PATTERN = re.compile(r"\s{2,}")

# ---------------------------------------------------------------------------
# Language detection heuristics
# ---------------------------------------------------------------------------

# Common words by language for lightweight detection
_LANGUAGE_HINTS: dict[str, set[str]] = {
    "en": {
        "the", "is", "are", "was", "were", "have", "has", "been", "will",
        "would", "could", "should", "this", "that", "with", "from", "they",
        "been", "your", "what", "when", "where", "which", "their", "about",
        "just", "like", "very", "some", "more", "also", "than", "other",
        "into", "only", "come", "made", "after", "back", "much", "then",
    },
    "es": {
        "el", "la", "los", "las", "es", "son", "está", "están", "fue",
        "ser", "una", "uno", "que", "por", "con", "para", "como", "pero",
        "más", "este", "esta", "esto", "todo", "todos", "otra", "otro",
        "muy", "también", "puede", "desde", "donde", "cuando", "porque",
    },
    "fr": {
        "le", "la", "les", "est", "sont", "une", "des", "que", "pour",
        "avec", "dans", "sur", "pas", "plus", "par", "mais", "être",
        "fait", "tout", "aussi", "comme", "bien", "très", "cette", "ces",
    },
    "de": {
        "der", "die", "das", "ist", "sind", "ein", "eine", "und", "für",
        "mit", "von", "auf", "nicht", "sich", "auch", "noch", "wie",
        "oder", "aber", "nach", "wenn", "nur", "kann", "dem", "den",
    },
    "pt": {
        "o", "os", "uma", "que", "não", "para", "com", "por", "mais",
        "como", "mas", "foi", "está", "ser", "tem", "seu", "sua", "isso",
        "são", "quando", "muito", "também", "pode", "entre", "depois",
    },
}


class Preprocessor:
    """Transforms raw feedback records into unified CanonicalFeedback.

    Parameters
    ----------
    profanity_list:
        Set of profanity words to check against. Defaults to a built-in list.
    duplicate_store:
        Optional external store for deduplication. If None, uses an in-memory
        dict for tracking recent submissions.
    """

    def __init__(
        self,
        profanity_list: frozenset[str] | None = None,
        duplicate_store: dict[str, Any] | None = None,
    ) -> None:
        self._profanity_list = (
            profanity_list if profanity_list is not None else DEFAULT_PROFANITY_LIST
        )
        # In-memory dedup store: key = (source_type, cleaned_text_lower) -> {feedback_id, ingested_at, count}
        self._duplicate_store: dict[tuple[str, str], dict[str, Any]] = (
            duplicate_store if duplicate_store is not None else {}
        )

    def preprocess(
        self, feedback: SocialFeedback | WidgetFeedback
    ) -> CanonicalFeedback | None:
        """Orchestrate all preprocessing steps and produce CanonicalFeedback.

        Returns None if the record should be discarded (duplicate).
        Marks Processing_Status "failed" if empty after cleaning (Req 3.11).
        """
        # Extract raw text
        raw_text = feedback.message_text

        # Step 1: Clean text (Req 3.2)
        cleaned = self.clean_text(raw_text)

        # Step 2: Check if empty after cleaning (Req 3.11)
        if not cleaned:
            return self._build_canonical(
                feedback=feedback,
                cleaned_text="empty",  # placeholder to pass validation
                detected_language="und",
                profanity_detected=False,
                metadata={"reason": "empty_after_cleaning", "timestamp_parse_failed": False},
                processing_status="failed",
                original_text=raw_text,
            )

        # Step 3: PII masking (Req 3.6)
        masked_text, original_unmasked = self.mask_pii(cleaned)

        # Step 4: Language detection (Req 3.3, 3.4)
        detected_language = self.detect_language(masked_text)

        # Step 5: Profanity detection (Req 3.7)
        profanity_detected = self._check_profanity(masked_text)

        # Step 6: Timestamp handling (Req 3.8, 3.9)
        ingested_at, timestamp_parse_failed = self._resolve_ingested_at(feedback)

        # Step 7: Check duplicate (Req 3.5)
        source_type = feedback.source_type
        existing_id = self.check_duplicate(
            masked_text, source_type, current_ingested_at=ingested_at
        )
        if existing_id is not None:
            # Duplicate detected - discard
            return None

        # Step 8: Register in dedup store
        self._register_for_dedup(masked_text, source_type, feedback.feedback_id, ingested_at)

        # Step 9: Build metadata (Req 3.10)
        metadata = self._build_metadata(feedback, original_unmasked, timestamp_parse_failed)

        # Produce CanonicalFeedback
        return self._build_canonical(
            feedback=feedback,
            cleaned_text=masked_text,
            detected_language=detected_language,
            profanity_detected=profanity_detected,
            metadata=metadata,
            processing_status="preprocessed",
            original_text=original_unmasked,
            ingested_at_override=ingested_at,
        )

    def clean_text(self, raw_text: str) -> str:
        """Clean text by removing HTML, normalizing Unicode, collapsing whitespace.

        Operations (Req 3.2):
        1. Remove HTML tags
        2. Normalize Unicode to NFC form
        3. Collapse multiple whitespace into single spaces
        4. Trim leading and trailing whitespace

        Returns empty string if the result is empty after all operations.
        """
        # Remove HTML tags (replace with space to avoid joining adjacent words)
        text = _HTML_TAG_PATTERN.sub(" ", raw_text)

        # Unicode NFC normalization
        text = unicodedata.normalize("NFC", text)

        # Collapse multiple whitespace (including newlines, tabs) into single space
        text = _MULTI_WHITESPACE_PATTERN.sub(" ", text)

        # Trim leading and trailing whitespace
        text = text.strip()

        return text

    def detect_language(self, text: str) -> str:
        """Detect language of text, returning ISO 639-1 code.

        Returns "und" (undetermined) when:
        - Text has fewer than 3 characters (Req 3.4)
        - Confidence is too low to determine language (Req 3.4)
        """
        # Short text cannot be reliably detected (Req 3.4)
        if len(text) < 3:
            return "und"

        # Tokenize into lowercase words
        words = set(re.findall(r"\b[a-zA-ZÀ-ÿ]+\b", text.lower()))

        if not words:
            return "und"

        # Score each language by overlap with its hint words
        best_lang = "und"
        best_score = 0.0

        for lang, hints in _LANGUAGE_HINTS.items():
            matches = words & hints
            if len(matches) > 0:
                # Score = proportion of text words that match this language's hints
                score = len(matches) / len(words)
                if score > best_score:
                    best_score = score
                    best_lang = lang

        # Require a minimum confidence threshold
        if best_score < 0.1:
            return "und"

        return best_lang

    def mask_pii(self, text: str) -> tuple[str, str]:
        """Mask PII patterns in text (Req 3.6).

        Replaces email, phone, and SSN patterns with placeholder tokens.
        Returns (masked_text, original_text) tuple where original_text
        preserves the unmasked content for authorized access.
        """
        original = text

        # Order matters: SSN before phone (SSN is more specific)
        masked = _SSN_PATTERN.sub("[SSN]", text)
        masked = _EMAIL_PATTERN.sub("[EMAIL]", masked)
        masked = _PHONE_PATTERN.sub("[PHONE]", masked)

        return masked, original

    def check_duplicate(
        self,
        cleaned_text: str,
        source_type: str,
        window_hours: int = 24,
        current_ingested_at: str | None = None,
    ) -> str | None:
        """Check for duplicate text from same source within time window (Req 3.5).

        Returns the feedback_id of the original record if a duplicate is found,
        incrementing its duplicate_count. Returns None if not a duplicate.

        Parameters
        ----------
        cleaned_text:
            The cleaned text to check.
        source_type:
            The source type ("social" or "widget").
        window_hours:
            Time window in hours for deduplication (default 24).
        current_ingested_at:
            ISO 8601 timestamp of the current submission. If None, uses now().
        """
        key = (source_type, cleaned_text.lower())
        existing = self._duplicate_store.get(key)

        if existing is None:
            return None

        # Determine the reference time for the new submission
        if current_ingested_at:
            try:
                current_dt = datetime.fromisoformat(
                    current_ingested_at.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                current_dt = datetime.now(timezone.utc)
        else:
            current_dt = datetime.now(timezone.utc)

        # Ensure timezone-aware
        if current_dt.tzinfo is None:
            current_dt = current_dt.replace(tzinfo=timezone.utc)

        # Parse the stored timestamp
        existing_time = existing["ingested_at"]
        if isinstance(existing_time, str):
            try:
                existing_dt = datetime.fromisoformat(
                    existing_time.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                existing_dt = current_dt
        elif isinstance(existing_time, datetime):
            existing_dt = existing_time
        else:
            existing_dt = current_dt

        # Ensure timezone-aware comparison
        if existing_dt.tzinfo is None:
            existing_dt = existing_dt.replace(tzinfo=timezone.utc)

        elapsed_hours = abs((current_dt - existing_dt).total_seconds()) / 3600

        if elapsed_hours <= window_hours:
            # Duplicate found within window - increment count
            existing["duplicate_count"] = existing.get("duplicate_count", 0) + 1
            return existing["feedback_id"]

        # Outside window - not a duplicate; remove stale entry
        del self._duplicate_store[key]
        return None

    def _check_profanity(self, text: str) -> bool:
        """Check if text contains any word from the profanity list (Req 3.7).

        Case-insensitive word boundary matching. Does NOT alter the text.
        """
        text_lower = text.lower()
        words = set(re.findall(r"\b\w+\b", text_lower))
        return bool(words & self._profanity_list)

    def _resolve_ingested_at(
        self, feedback: SocialFeedback | WidgetFeedback
    ) -> tuple[str, bool]:
        """Resolve and standardize ingested_at timestamp (Req 3.8, 3.9).

        Returns (iso_timestamp_str, timestamp_parse_failed).
        """
        timestamp_parse_failed = False

        if isinstance(feedback, SocialFeedback):
            raw_ts = feedback.ingested_at
        else:
            raw_ts = feedback.created_at

        # Try to parse and validate the timestamp
        try:
            dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            # Convert to UTC ISO 8601 format
            utc_dt = dt.astimezone(timezone.utc)
            return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ"), False
        except (ValueError, TypeError, AttributeError):
            # Cannot parse - use current time and flag (Req 3.9)
            timestamp_parse_failed = True
            now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return now_utc, True

    def _register_for_dedup(
        self, cleaned_text: str, source_type: str, feedback_id: str, ingested_at: str
    ) -> None:
        """Register a processed record for future duplicate detection."""
        key = (source_type, cleaned_text.lower())
        self._duplicate_store[key] = {
            "feedback_id": feedback_id,
            "ingested_at": ingested_at,
            "duplicate_count": 0,
        }

    def _build_metadata(
        self,
        feedback: SocialFeedback | WidgetFeedback,
        original_unmasked: str,
        timestamp_parse_failed: bool,
    ) -> dict[str, Any]:
        """Build metadata dict for CanonicalFeedback (Req 3.10)."""
        metadata: dict[str, Any] = {
            "original_text": original_unmasked,
            "timestamp_parse_failed": timestamp_parse_failed,
        }

        if isinstance(feedback, SocialFeedback):
            metadata["platform"] = feedback.platform
            metadata["username_handle"] = feedback.username_handle
            metadata["post_id"] = feedback.post_id
            metadata["post_url"] = feedback.post_url
            metadata["engagement_metrics"] = feedback.engagement_metrics.model_dump()
            metadata["recency_score"] = feedback.recency_score
            metadata["location"] = feedback.location
        else:
            metadata["submission_channel"] = feedback.submission_channel
            metadata["consent_to_contact"] = feedback.consent_to_contact
            metadata["customer_id"] = feedback.customer_id
            metadata["account_type"] = feedback.account_type
            metadata["selected_category"] = feedback.selected_category
            metadata["location"] = feedback.location

        return metadata

    def _build_canonical(
        self,
        feedback: SocialFeedback | WidgetFeedback,
        cleaned_text: str,
        detected_language: str,
        profanity_detected: bool,
        metadata: dict[str, Any],
        processing_status: str,
        original_text: str,
        ingested_at_override: str | None = None,
    ) -> CanonicalFeedback:
        """Construct a CanonicalFeedback record."""
        # Determine ingested_at
        if ingested_at_override:
            ingested_at = ingested_at_override
        elif isinstance(feedback, SocialFeedback):
            ingested_at = feedback.ingested_at
        else:
            ingested_at = feedback.created_at

        # Determine original_source_id (Req 3.10)
        if isinstance(feedback, SocialFeedback):
            original_source_id = feedback.post_id
        else:
            original_source_id = feedback.feedback_id

        return CanonicalFeedback(
            feedback_id=feedback.feedback_id,
            source_type=feedback.source_type,
            original_source_id=original_source_id,
            cleaned_text=cleaned_text,
            detected_language=detected_language,
            ingested_at=ingested_at,
            duplicate_count=0,
            profanity_detected=profanity_detected,
            metadata=metadata,
            processing_status=processing_status,
        )


__all__ = ["Preprocessor", "DEFAULT_PROFANITY_LIST"]
