"""Unit tests for the strict Response_Parser (task 3.1).

Covers the all-or-nothing parsing contract (Req 4.1, 4.2): valid responses map
to a typed object, and every invalid-response category yields a parse error
keyed by record_id with no partial object.
"""

import json

import pytest

from nlp_processing.serialization import (
    EnrichmentResponse,
    ParseOutcome,
    ResponseParser,
)
from nlp_processing.serialization.parser import ParseError


def _valid_payload(**overrides) -> dict:
    payload = {
        "themes": [{"theme": "billing", "confidence": 0.9}],
        "sentiment": "negative",
        "sentiment_confidence": 0.8,
        "severity_score": 3,
        "severity_factors": ["repeated billing error"],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def parser() -> ResponseParser:
    return ResponseParser()


class TestValidResponses:
    def test_parses_valid_response(self, parser):
        outcome = parser.parse_enrichment(json.dumps(_valid_payload()), "r1")
        assert outcome.ok
        assert outcome.error is None
        assert isinstance(outcome.value, EnrichmentResponse)
        assert outcome.value.sentiment == "negative"
        assert outcome.value.severity_score == 3
        assert outcome.value.themes[0].theme == "billing"

    def test_record_id_propagated_on_success(self, parser):
        outcome = parser.parse_enrichment(json.dumps(_valid_payload()), "abc")
        assert outcome.record_id == "abc"

    def test_multiple_themes_and_factors(self, parser):
        payload = _valid_payload(
            themes=[
                {"theme": "billing", "confidence": 0.9},
                {"theme": "pricing", "confidence": 0.6},
            ],
            severity_factors=["a", "b", "c"],
        )
        outcome = parser.parse_enrichment(json.dumps(payload), "r1")
        assert outcome.ok
        assert len(outcome.value.themes) == 2
        assert len(outcome.value.severity_factors) == 3

    def test_unknown_theme_string_is_accepted_by_parser(self, parser):
        # The parser validates raw shape only; discarding out-of-set theme
        # labels is the Classifier's job (Req 5.6), not the parser's.
        payload = _valid_payload(themes=[{"theme": "weather", "confidence": 0.5}])
        outcome = parser.parse_enrichment(json.dumps(payload), "r1")
        assert outcome.ok
        assert outcome.value.themes[0].theme == "weather"

    def test_boundary_values_accepted(self, parser):
        payload = _valid_payload(
            themes=[{"theme": "outage", "confidence": 0.0}],
            sentiment_confidence=1.0,
            severity_score=1,
            severity_factors=["x" * 500],
        )
        outcome = parser.parse_enrichment(json.dumps(payload), "r1")
        assert outcome.ok


class TestInvalidResponses:
    def _assert_parse_error(self, outcome: ParseOutcome, record_id: str):
        assert not outcome.ok
        assert outcome.value is None
        assert isinstance(outcome.error, ParseError)
        assert outcome.error.record_id == record_id
        assert outcome.record_id == record_id

    def test_invalid_json(self, parser):
        outcome = parser.parse_enrichment("{not valid json", "r1")
        self._assert_parse_error(outcome, "r1")
        assert "invalid JSON" in outcome.error.reason

    def test_empty_string(self, parser):
        outcome = parser.parse_enrichment("", "r1")
        self._assert_parse_error(outcome, "r1")

    @pytest.mark.parametrize(
        "missing",
        ["themes", "sentiment", "sentiment_confidence", "severity_score", "severity_factors"],
    )
    def test_missing_required_field(self, parser, missing):
        payload = _valid_payload()
        del payload[missing]
        outcome = parser.parse_enrichment(json.dumps(payload), "r1")
        self._assert_parse_error(outcome, "r1")

    def test_empty_themes_rejected(self, parser):
        outcome = parser.parse_enrichment(json.dumps(_valid_payload(themes=[])), "r1")
        self._assert_parse_error(outcome, "r1")

    def test_empty_severity_factors_rejected(self, parser):
        outcome = parser.parse_enrichment(
            json.dumps(_valid_payload(severity_factors=[])), "r1"
        )
        self._assert_parse_error(outcome, "r1")

    @pytest.mark.parametrize("score", [0, 6, -1, 100])
    def test_severity_out_of_range(self, parser, score):
        outcome = parser.parse_enrichment(
            json.dumps(_valid_payload(severity_score=score)), "r1"
        )
        self._assert_parse_error(outcome, "r1")

    def test_severity_non_integer(self, parser):
        outcome = parser.parse_enrichment(
            json.dumps(_valid_payload(severity_score=3.5)), "r1"
        )
        self._assert_parse_error(outcome, "r1")

    @pytest.mark.parametrize("conf", [-0.01, 1.01])
    def test_sentiment_confidence_out_of_range(self, parser, conf):
        outcome = parser.parse_enrichment(
            json.dumps(_valid_payload(sentiment_confidence=conf)), "r1"
        )
        self._assert_parse_error(outcome, "r1")

    def test_invalid_sentiment_value(self, parser):
        outcome = parser.parse_enrichment(
            json.dumps(_valid_payload(sentiment="angry")), "r1"
        )
        self._assert_parse_error(outcome, "r1")

    def test_theme_confidence_out_of_range(self, parser):
        payload = _valid_payload(themes=[{"theme": "billing", "confidence": 1.5}])
        outcome = parser.parse_enrichment(json.dumps(payload), "r1")
        self._assert_parse_error(outcome, "r1")

    def test_wrong_type_for_severity_score(self, parser):
        outcome = parser.parse_enrichment(
            json.dumps(_valid_payload(severity_score="three")), "r1"
        )
        self._assert_parse_error(outcome, "r1")

    def test_severity_factor_too_long(self, parser):
        outcome = parser.parse_enrichment(
            json.dumps(_valid_payload(severity_factors=["x" * 501])), "r1"
        )
        self._assert_parse_error(outcome, "r1")

    def test_additional_property_rejected(self, parser):
        outcome = parser.parse_enrichment(
            json.dumps(_valid_payload(unexpected="nope")), "r1"
        )
        self._assert_parse_error(outcome, "r1")

    def test_json_array_instead_of_object(self, parser):
        outcome = parser.parse_enrichment("[1, 2, 3]", "r1")
        self._assert_parse_error(outcome, "r1")

    def test_no_partial_object_on_failure(self, parser):
        # All-or-nothing: a payload valid except for one field yields no value.
        outcome = parser.parse_enrichment(
            json.dumps(_valid_payload(severity_score=99)), "r1"
        )
        assert outcome.value is None


class TestParseOutcomeInvariant:
    def test_cannot_construct_with_both(self):
        with pytest.raises(ValueError):
            ParseOutcome(record_id="r1", value=object(), error=ParseError("r1", "x"))

    def test_cannot_construct_with_neither(self):
        with pytest.raises(ValueError):
            ParseOutcome(record_id="r1")
