"""Property 20: RawFeedback constructed with source_channel "social_post".

For any web submission passed to the NLPProcessor, the constructed RawFeedback
object SHALL have source_channel "social_post" and the submission text as the
feedback text.

Feature: sentiment-routed-frontend, Property 20: RawFeedback constructed with source_channel "social_post"
**Validates: Requirements 13.1**
"""

import os
from unittest.mock import patch, MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

# Ensure GEMINI_API_KEY is set so _do_nlp_processing doesn't short-circuit
os.environ.setdefault("GEMINI_API_KEY", "test-key-for-property-testing")


# --- Strategy: generate arbitrary non-empty text strings ---

feedback_texts = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z", "S")),
    min_size=1,
    max_size=500,
)


@settings(max_examples=100)
@given(text=feedback_texts)
def test_raw_feedback_has_social_post_source_channel_and_matching_text(text: str):
    """Property 20: For any text passed to _do_nlp_processing, the constructed
    RawFeedback SHALL have source_channel="social_post" and text matching the input.

    Feature: sentiment-routed-frontend, Property 20: RawFeedback constructed with source_channel "social_post"
    **Validates: Requirements 13.1**
    """
    captured_feedback = []

    # Create a mock processor whose process_batch captures the RawFeedback args
    mock_processor = MagicMock()
    mock_output = MagicMock()
    mock_output.insights = []
    mock_output.failures = []

    def capture_and_return(feedbacks):
        captured_feedback.extend(feedbacks)
        return mock_output

    mock_processor.process_batch.side_effect = capture_and_return

    # Patch NLPProcessor.from_settings to return our mock processor.
    # RawFeedback is a real Pydantic model from nlp_processing.models so it
    # gets constructed normally — we only intercept the processor.
    with patch(
        "nlp_processing.orchestrator.NLPProcessor.from_settings",
        return_value=mock_processor,
    ):
        from app.services.enrichment import _do_nlp_processing

        _do_nlp_processing(text)

    # Verify process_batch was called with exactly one RawFeedback
    assert len(captured_feedback) == 1, (
        f"Expected 1 RawFeedback passed to process_batch, got {len(captured_feedback)}"
    )

    raw_feedback = captured_feedback[0]

    # Property assertion: source_channel must be "social_post"
    assert raw_feedback.source_channel == "social_post", (
        f"Expected source_channel='social_post', got '{raw_feedback.source_channel}'"
    )

    # Property assertion: text must match the input submission text
    assert raw_feedback.text == text, (
        f"Expected text to match input, got '{raw_feedback.text}'"
    )

    # Property assertion: metadata must be an empty dict (per Requirement 13.1)
    assert raw_feedback.metadata == {}, (
        f"Expected empty metadata dict, got {raw_feedback.metadata}"
    )
