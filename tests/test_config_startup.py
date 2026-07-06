"""Unit/edge tests for configuration startup validation (task 1.4).

Covers fail-fast configuration validation (Req 2.2, 2.4):

- Missing/empty/whitespace ``api_key`` and ``model_name`` are rejected.
- ``max_attempts``, ``request_timeout_seconds``, and the thresholds are
  rejected when out of range.
- Startup smoke test: a valid config constructs; an invalid config refuses.
- Secret hygiene (Req 2.6): the api_key value never appears in error messages.
"""

from __future__ import annotations

import pytest

from nlp_processing.config import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_REVIEW_THRESHOLD,
    Config,
    ConfigurationError,
)

SECRET_KEY = "sk-super-secret-value-1234567890"


def _valid_kwargs(**overrides):
    base = dict(
        api_key=SECRET_KEY,
        model_name="gemini-1.5-pro",
        similarity_threshold=0.8,
    )
    base.update(overrides)
    return base


class TestRequiredCredentials:
    @pytest.mark.parametrize("bad", [None, "", "   ", "\t\n", "  \r "])
    def test_missing_or_blank_api_key_rejected(self, bad):
        with pytest.raises(ConfigurationError) as excinfo:
            Config(**_valid_kwargs(api_key=bad))
        assert excinfo.value.field_name == "api_key"

    @pytest.mark.parametrize("bad", [None, "", "   ", "\t\n"])
    def test_missing_or_blank_model_name_rejected(self, bad):
        with pytest.raises(ConfigurationError) as excinfo:
            Config(**_valid_kwargs(model_name=bad))
        assert excinfo.value.field_name == "model_name"

    def test_non_string_api_key_rejected(self):
        with pytest.raises(ConfigurationError) as excinfo:
            Config(**_valid_kwargs(api_key=12345))
        assert excinfo.value.field_name == "api_key"


class TestNumericRanges:
    @pytest.mark.parametrize("bad", [0, 11, -1, 100])
    def test_max_attempts_out_of_range_rejected(self, bad):
        with pytest.raises(ConfigurationError) as excinfo:
            Config(**_valid_kwargs(max_attempts=bad))
        assert excinfo.value.field_name == "max_attempts"

    @pytest.mark.parametrize("good", [1, 5, 10])
    def test_max_attempts_in_range_accepted(self, good):
        cfg = Config(**_valid_kwargs(max_attempts=good))
        assert cfg.max_attempts == good

    @pytest.mark.parametrize("bad", [0, 121, -5, 1000])
    def test_timeout_out_of_range_rejected(self, bad):
        with pytest.raises(ConfigurationError) as excinfo:
            Config(**_valid_kwargs(request_timeout_seconds=bad))
        assert excinfo.value.field_name == "request_timeout_seconds"

    @pytest.mark.parametrize("good", [1, 30, 120])
    def test_timeout_in_range_accepted(self, good):
        cfg = Config(**_valid_kwargs(request_timeout_seconds=good))
        assert cfg.request_timeout_seconds == good

    @pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0, -1.0])
    def test_similarity_threshold_out_of_range_rejected(self, bad):
        with pytest.raises(ConfigurationError) as excinfo:
            Config(**_valid_kwargs(similarity_threshold=bad))
        assert excinfo.value.field_name == "similarity_threshold"

    @pytest.mark.parametrize("bad", [-0.01, 1.01, 5.0])
    def test_review_threshold_out_of_range_rejected(self, bad):
        with pytest.raises(ConfigurationError) as excinfo:
            Config(**_valid_kwargs(review_threshold=bad))
        assert excinfo.value.field_name == "review_threshold"

    @pytest.mark.parametrize("good", [0.0, 0.5, 1.0])
    def test_thresholds_at_bounds_accepted(self, good):
        cfg = Config(**_valid_kwargs(similarity_threshold=good, review_threshold=good))
        assert cfg.similarity_threshold == good
        assert cfg.review_threshold == good

    def test_max_attempts_rejects_bool(self):
        # bool is a subclass of int and must not be accepted.
        with pytest.raises(ConfigurationError) as excinfo:
            Config(**_valid_kwargs(max_attempts=True))
        assert excinfo.value.field_name == "max_attempts"


class TestStartupSmoke:
    def test_valid_config_constructs_with_defaults(self):
        cfg = Config(**_valid_kwargs())
        assert cfg.api_key == SECRET_KEY
        assert cfg.model_name == "gemini-1.5-pro"
        assert cfg.max_attempts == DEFAULT_MAX_ATTEMPTS
        assert cfg.request_timeout_seconds == DEFAULT_REQUEST_TIMEOUT_SECONDS
        assert cfg.review_threshold == DEFAULT_REVIEW_THRESHOLD

    def test_invalid_config_refuses_to_construct(self):
        with pytest.raises(ConfigurationError):
            Config(api_key="", model_name="", similarity_threshold=0.5)

    def test_from_mapping_round_trips_valid_settings(self):
        cfg = Config.from_mapping(
            {
                "api_key": SECRET_KEY,
                "model_name": "gemini-1.5-flash",
                "similarity_threshold": 0.6,
                "max_attempts": 3,
            }
        )
        assert cfg.model_name == "gemini-1.5-flash"
        assert cfg.max_attempts == 3

    def test_from_mapping_rejects_non_mapping(self):
        with pytest.raises(ConfigurationError):
            Config.from_mapping(["not", "a", "mapping"])  # type: ignore[arg-type]


class TestSecretHygiene:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"model_name": ""},
            {"max_attempts": 99},
            {"request_timeout_seconds": 0},
            {"similarity_threshold": 2.0},
            {"review_threshold": -1.0},
        ],
    )
    def test_api_key_never_appears_in_error_messages(self, overrides):
        # Even when other fields are invalid, a valid secret api_key must never
        # be echoed into the raised error message (Req 2.6).
        with pytest.raises(ConfigurationError) as excinfo:
            Config(**_valid_kwargs(**overrides))
        assert SECRET_KEY not in str(excinfo.value)

    def test_api_key_not_in_repr(self):
        cfg = Config(**_valid_kwargs())
        assert SECRET_KEY not in repr(cfg)
        assert "<redacted>" in repr(cfg)
