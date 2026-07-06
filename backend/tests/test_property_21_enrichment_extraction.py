"""Property 21: Enrichment result extraction from BatchOutput.

For any BatchOutput containing at least one InsightRecord, the API_Server SHALL
extract themes (with confidence), sentiment_confidence, severity_score,
severity_factors, language_code, and language_confidence from the first
InsightRecord and store them as the Enrichment_Result with status "completed".

Feature: sentiment-routed-frontend, Property 21: Enrichment result extraction from BatchOutput
**Validates: Requirements 13.2, 13.6**
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path so nlp_processing is importable
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from hypothesis import given, settings
from hypothesis import strategies as st

from nlp_processing.models.records import (
    BatchOutput,
    BatchSummary,
    InsightRecord,
    SeverityFactor,
    ThemeAssignment,
)
from nlp_processing.models.types import ThemeLabel, SentimentValue

from app.services.enrichment import _extract_enrichment_result


# --- Strategies ---

theme_labels = st.sampled_from([
    "billing",
    "network_speed",
    "outage",
    "support_experience",
    "device_hardware",
    "pricing",
    "other",
])

confidences = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

theme_assignments = st.builds(
    ThemeAssignment,
    theme=theme_labels,
    confidence=confidences,
)

severity_scores = st.integers(min_value=1, max_value=5)

severity_factor_descriptions = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=100,
).filter(lambda s: len(s.strip()) >= 1)

severity_factors = st.builds(
    SeverityFactor,
    description=severity_factor_descriptions,
)

language_codes = st.one_of(
    st.none(),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=2),
)

language_confidences = st.one_of(
    st.none(),
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)

sentiment_values = st.sampled_from(["positive", "neutral", "negative"])


@st.composite
def insight_record_strategy(draw):
    """Generate a random InsightRecord with valid data."""
    themes = draw(st.lists(theme_assignments, min_size=1, max_size=5))
    sentiment = draw(sentiment_values)
    sentiment_confidence = draw(confidences)
    severity_score = draw(severity_scores)
    sev_factors = draw(st.lists(severity_factors, min_size=1, max_size=3))
    lang_code = draw(language_codes)
    lang_confidence = draw(language_confidences)

    return InsightRecord(
        feedback_id="test-feedback-id",
        themes=themes,
        sentiment=sentiment,
        sentiment_confidence=sentiment_confidence,
        severity_score=severity_score,
        severity_factors=sev_factors,
        cluster_id="test-cluster",
        model_name="test-model",
        language_code=lang_code,
        language_confidence=lang_confidence,
    )


@st.composite
def batch_output_with_insights_strategy(draw):
    """Generate a BatchOutput with at least one InsightRecord."""
    first_insight = draw(insight_record_strategy())
    # Optionally add more insights (1-3 total)
    extra_insights = draw(st.lists(insight_record_strategy(), min_size=0, max_size=2))
    insights = [first_insight] + extra_insights

    return BatchOutput(
        insights=insights,
        clusters=[],
        failures=[],
        system_errors=[],
        summary=BatchSummary(
            submitted=len(insights),
            successful=len(insights),
            failures=0,
        ),
        model_name="test-model",
    )


@settings(max_examples=100)
@given(output=batch_output_with_insights_strategy())
def test_enrichment_result_extraction_from_batch_output(output: BatchOutput):
    """Property 21: For any BatchOutput with at least one InsightRecord,
    _extract_enrichment_result extracts themes, sentiment_confidence,
    severity_score, severity_factors, language_code, and language_confidence
    from the first InsightRecord.

    Feature: sentiment-routed-frontend, Property 21: Enrichment result extraction from BatchOutput
    **Validates: Requirements 13.2, 13.6**
    """
    result = _extract_enrichment_result(output)

    # Must not be None since we have at least one InsightRecord
    assert result is not None, "Expected EnrichmentResult but got None"

    first_insight = output.insights[0]

    # Verify themes are correctly extracted (list of dicts with theme and confidence)
    assert len(result.themes) == len(first_insight.themes)
    for i, theme_dict in enumerate(result.themes):
        assert theme_dict["theme"] == first_insight.themes[i].theme
        assert theme_dict["confidence"] == first_insight.themes[i].confidence

    # Verify sentiment_confidence
    assert result.sentiment_confidence == first_insight.sentiment_confidence

    # Verify severity_score
    assert result.severity_score == first_insight.severity_score

    # Verify severity_factors (list of description strings)
    assert len(result.severity_factors) == len(first_insight.severity_factors)
    for i, factor_str in enumerate(result.severity_factors):
        assert factor_str == first_insight.severity_factors[i].description

    # Verify language_code
    assert result.language_code == first_insight.language_code

    # Verify language_confidence
    assert result.language_confidence == first_insight.language_confidence
