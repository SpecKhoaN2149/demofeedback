"""Property-based test for deduplication detection.

# Feature: nlp-feedback-routing, Property 4

**Validates: Requirements 3.5**

Property 4: Deduplication Detection — For any cleaned_text string and
source_type, submitting the same (case-insensitive) text from the same source
within 24 hours SHALL result in the second submission being discarded and the
original record's duplicate_count being incremented by 1.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from nlp_processing.preprocessing.preprocessor import Preprocessor


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty printable text for cleaned_text (Preprocessor expects non-empty strings)
_PRINTABLE = st.characters(min_codepoint=32, max_codepoint=126)

_cleaned_text_strategy = st.text(
    alphabet=_PRINTABLE,
    min_size=1,
    max_size=200,
)

_source_type_strategy = st.sampled_from(["social", "widget"])


@given(
    cleaned_text=_cleaned_text_strategy,
    source_type=_source_type_strategy,
)
@settings(max_examples=100)
def test_deduplication_detection(cleaned_text: str, source_type: str) -> None:
    """Verify duplicate submissions are detected and duplicate_count increments.

    # Feature: nlp-feedback-routing, Property 4
    **Validates: Requirements 3.5**

    For any cleaned_text and source_type:
    1. First submission via check_duplicate returns None (not a duplicate)
    2. After registering, second submission with same text (case-insensitive)
       from same source within 24h returns the original feedback_id
    3. The original record's duplicate_count is incremented by 1
    """
    pp = Preprocessor()

    # Use a fixed timestamp within the 24h window
    base_time = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    base_time_iso = base_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Second submission within 24h window (e.g., 1 hour later)
    second_time = base_time + timedelta(hours=1)
    second_time_iso = second_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    original_id = str(uuid.uuid4())

    # 1. First check: no prior entry → not a duplicate
    result_first = pp.check_duplicate(
        cleaned_text, source_type, current_ingested_at=base_time_iso
    )
    assert result_first is None, (
        f"First submission should not be a duplicate, got {result_first}"
    )

    # Register the first submission in the dedup store
    pp._register_for_dedup(cleaned_text, source_type, original_id, base_time_iso)

    # 2. Second submission with same text (case-insensitive) within 24h
    result_second = pp.check_duplicate(
        cleaned_text, source_type, current_ingested_at=second_time_iso
    )
    assert result_second == original_id, (
        f"Second submission should be detected as duplicate of {original_id}, "
        f"got {result_second} (text={cleaned_text!r}, source={source_type})"
    )

    # 3. Verify duplicate_count was incremented by 1
    key = (source_type, cleaned_text.lower())
    assert key in pp._duplicate_store, (
        f"Dedup store should contain key {key}"
    )
    assert pp._duplicate_store[key]["duplicate_count"] == 1, (
        f"duplicate_count should be 1 after first duplicate, "
        f"got {pp._duplicate_store[key]['duplicate_count']}"
    )


@given(
    cleaned_text=_cleaned_text_strategy,
    source_type=_source_type_strategy,
)
@settings(max_examples=100)
def test_deduplication_case_insensitive(cleaned_text: str, source_type: str) -> None:
    """Verify deduplication is case-insensitive on cleaned_text.

    # Feature: nlp-feedback-routing, Property 4
    **Validates: Requirements 3.5**

    Submitting the same text with different casing from the same source within
    24h should be detected as a duplicate.
    """
    pp = Preprocessor()

    base_time = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    base_time_iso = base_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    second_time = base_time + timedelta(hours=2)
    second_time_iso = second_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    original_id = str(uuid.uuid4())

    # Register with original casing
    pp._register_for_dedup(cleaned_text, source_type, original_id, base_time_iso)

    # Submit with swapped case (upper ↔ lower)
    swapped_text = cleaned_text.swapcase()

    result = pp.check_duplicate(
        swapped_text, source_type, current_ingested_at=second_time_iso
    )
    assert result == original_id, (
        f"Case-insensitive duplicate not detected: "
        f"original={cleaned_text!r}, swapped={swapped_text!r}, source={source_type}"
    )

    # Verify duplicate_count incremented
    key = (source_type, cleaned_text.lower())
    assert pp._duplicate_store[key]["duplicate_count"] == 1


@given(
    cleaned_text=_cleaned_text_strategy,
    source_type=_source_type_strategy,
)
@settings(max_examples=100)
def test_deduplication_outside_window_not_detected(
    cleaned_text: str, source_type: str
) -> None:
    """Verify submissions outside the 24h window are NOT duplicates.

    # Feature: nlp-feedback-routing, Property 4
    **Validates: Requirements 3.5**

    If the same text is submitted from the same source but more than 24h
    after the original, it should NOT be considered a duplicate.
    """
    pp = Preprocessor()

    base_time = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    base_time_iso = base_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 25 hours later — outside the 24h window
    late_time = base_time + timedelta(hours=25)
    late_time_iso = late_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    original_id = str(uuid.uuid4())

    # Register original
    pp._register_for_dedup(cleaned_text, source_type, original_id, base_time_iso)

    # Submit after 25h — should NOT be a duplicate
    result = pp.check_duplicate(
        cleaned_text, source_type, current_ingested_at=late_time_iso
    )
    assert result is None, (
        f"Submission 25h later should not be a duplicate, got {result} "
        f"(text={cleaned_text!r}, source={source_type})"
    )


@given(
    cleaned_text=_cleaned_text_strategy,
)
@settings(max_examples=100)
def test_deduplication_different_source_not_detected(cleaned_text: str) -> None:
    """Verify same text from different source is NOT a duplicate.

    # Feature: nlp-feedback-routing, Property 4
    **Validates: Requirements 3.5**

    The deduplication check matches on (cleaned_text, source_type) pair.
    Same text from a different source should not be flagged as duplicate.
    """
    pp = Preprocessor()

    base_time = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    base_time_iso = base_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    second_time = base_time + timedelta(hours=1)
    second_time_iso = second_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    original_id = str(uuid.uuid4())

    # Register as "social"
    pp._register_for_dedup(cleaned_text, "social", original_id, base_time_iso)

    # Submit same text as "widget" — different source
    result = pp.check_duplicate(
        cleaned_text, "widget", current_ingested_at=second_time_iso
    )
    assert result is None, (
        f"Same text from different source should not be duplicate, got {result} "
        f"(text={cleaned_text!r})"
    )
