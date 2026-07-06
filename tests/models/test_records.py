"""Unit tests for the core pydantic data models (task 1.2)."""

import pytest
from pydantic import ValidationError

from nlp_processing.models import (
    DEFAULT_THEME_SET,
    BatchOutput,
    BatchSummary,
    Cluster,
    FailureEntry,
    FeedbackRecord,
    InsightRecord,
    RawFeedback,
    SeverityFactor,
    ThemeAssignment,
)


def _valid_insight(**overrides):
    base = dict(
        feedback_id="f1",
        themes=[ThemeAssignment(theme="billing", confidence=0.9)],
        sentiment="negative",
        sentiment_confidence=0.8,
        severity_score=3,
        severity_factors=[SeverityFactor(description="repeated outage")],
        cluster_id="c1",
        model_name="gemini-x",
    )
    base.update(overrides)
    return base


class TestThemeSet:
    def test_default_theme_set_has_seven_standard_themes(self):
        assert DEFAULT_THEME_SET == {
            "billing",
            "network_speed",
            "outage",
            "support_experience",
            "device_hardware",
            "pricing",
            "other",
        }


class TestRawFeedback:
    def test_metadata_defaults_to_empty_dict(self):
        raw = RawFeedback(source_channel="email", text="hi")
        assert raw.metadata == {}

    def test_accepts_arbitrary_channel_string(self):
        # Validation against the allowed set happens in ingestion, not here.
        raw = RawFeedback(source_channel="carrier_pigeon", text="hi")
        assert raw.source_channel == "carrier_pigeon"


class TestFeedbackRecord:
    def test_valid_record(self):
        rec = FeedbackRecord(
            id="1", source_channel="survey", cleaned_text="great", metadata={"k": "v"}
        )
        assert rec.metadata == {"k": "v"}

    def test_rejects_empty_cleaned_text(self):
        with pytest.raises(ValidationError):
            FeedbackRecord(id="1", source_channel="survey", cleaned_text="")

    def test_rejects_text_over_10000_chars(self):
        with pytest.raises(ValidationError):
            FeedbackRecord(id="1", source_channel="survey", cleaned_text="a" * 10_001)

    def test_accepts_text_at_10000_chars(self):
        rec = FeedbackRecord(id="1", source_channel="survey", cleaned_text="a" * 10_000)
        assert len(rec.cleaned_text) == 10_000

    def test_rejects_invalid_channel(self):
        with pytest.raises(ValidationError):
            FeedbackRecord(id="1", source_channel="fax", cleaned_text="hi")


class TestThemeAssignment:
    @pytest.mark.parametrize("conf", [0.0, 0.5, 1.0])
    def test_accepts_confidence_in_range(self, conf):
        assert ThemeAssignment(theme="pricing", confidence=conf).confidence == conf

    @pytest.mark.parametrize("conf", [-0.01, 1.01])
    def test_rejects_confidence_out_of_range(self, conf):
        with pytest.raises(ValidationError):
            ThemeAssignment(theme="pricing", confidence=conf)

    def test_rejects_unknown_theme(self):
        with pytest.raises(ValidationError):
            ThemeAssignment(theme="weather", confidence=0.5)


class TestSeverityFactor:
    def test_rejects_empty_description(self):
        with pytest.raises(ValidationError):
            SeverityFactor(description="")

    def test_accepts_500_char_description(self):
        assert len(SeverityFactor(description="x" * 500).description) == 500

    def test_rejects_over_500_char_description(self):
        with pytest.raises(ValidationError):
            SeverityFactor(description="x" * 501)


class TestInsightRecord:
    def test_valid_insight(self):
        insight = InsightRecord(**_valid_insight())
        assert insight.review_flag is False
        assert insight.notes == []

    def test_requires_at_least_one_theme(self):
        with pytest.raises(ValidationError):
            InsightRecord(**_valid_insight(themes=[]))

    def test_requires_at_least_one_severity_factor(self):
        with pytest.raises(ValidationError):
            InsightRecord(**_valid_insight(severity_factors=[]))

    @pytest.mark.parametrize("score", [0, 6])
    def test_rejects_severity_out_of_range(self, score):
        with pytest.raises(ValidationError):
            InsightRecord(**_valid_insight(severity_score=score))

    def test_rejects_sentiment_confidence_out_of_range(self):
        with pytest.raises(ValidationError):
            InsightRecord(**_valid_insight(sentiment_confidence=1.5))

    def test_rejects_invalid_sentiment(self):
        with pytest.raises(ValidationError):
            InsightRecord(**_valid_insight(sentiment="angry"))


class TestCluster:
    def test_valid_cluster_defaults(self):
        c = Cluster(cluster_id="c1", label="billing issues")
        assert c.member_ids == []
        assert c.priority_score == 0.0

    def test_rejects_empty_label(self):
        with pytest.raises(ValidationError):
            Cluster(cluster_id="c1", label="")

    def test_rejects_label_over_120_chars(self):
        with pytest.raises(ValidationError):
            Cluster(cluster_id="c1", label="x" * 121)

    def test_rejects_negative_priority(self):
        with pytest.raises(ValidationError):
            Cluster(cluster_id="c1", label="ok", priority_score=-1.0)


class TestFailureEntry:
    def test_valid_entry(self):
        fe = FailureEntry(feedback_id="f1", stage="ingestion", reason="empty text")
        assert fe.stage == "ingestion"

    def test_rejects_unknown_stage(self):
        with pytest.raises(ValidationError):
            FailureEntry(feedback_id="f1", stage="banana", reason="x")


class TestBatchOutput:
    def test_minimal_batch_output(self):
        out = BatchOutput(
            summary=BatchSummary(submitted=0, successful=0, failures=0),
            model_name="gemini-x",
        )
        assert out.insights == []
        assert out.clusters == []
        assert out.classification_accuracy is None

    def test_rejects_accuracy_out_of_range(self):
        with pytest.raises(ValidationError):
            BatchOutput(
                summary=BatchSummary(submitted=0, successful=0, failures=0),
                model_name="gemini-x",
                classification_accuracy=1.5,
            )
