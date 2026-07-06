"""Configuration loading and fail-fast validation for the NLP_Processor.

This module implements task 1.3: a :class:`Config` loader/validator that
validates all operator-supplied configuration *before* any ``Feedback_Record``
is processed (Req 2.2, 2.4). When a value is missing or out of range, a
:class:`ConfigurationError` is raised that names the offending value only.

Secret hygiene (Req 2.6): the ``api_key`` value is never included in any error
message, ``repr``, or log line. Validation messages reference configuration
values by *name* (e.g. ``"api_key"``), never by value.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .models.types import DEFAULT_THEME_SET

# Defaults from the design's "Configuration and Startup" section.
DEFAULT_MODEL_NAME_REQUIRED = True  # model name has no default; it is required.
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_REVIEW_THRESHOLD = 0.70

# Inclusive bounds for the numeric configuration parameters.
MAX_ATTEMPTS_MIN, MAX_ATTEMPTS_MAX = 1, 10
TIMEOUT_MIN, TIMEOUT_MAX = 1, 120
THRESHOLD_MIN, THRESHOLD_MAX = 0.0, 1.0


class ConfigurationError(Exception):
    """Raised at startup when configuration is missing or invalid.

    This error is fatal and pre-processing: it stops initialization before any
    ``Feedback_Record`` is processed (Req 2.2, 2.4). It identifies the offending
    configuration value by *name* only and never embeds a secret value such as
    the API key (Req 2.6).
    """

    def __init__(self, field_name: str, message: str) -> None:
        self.field_name = field_name
        # The message is composed only from the field name and a static reason;
        # callers must never pass a secret value in ``message``.
        super().__init__(f"Invalid configuration for '{field_name}': {message}")


def _require_non_blank_str(value: Any, field_name: str) -> str:
    """Validate that ``value`` is a present, non-empty, non-whitespace string.

    Never includes ``value`` in the error so secrets cannot leak (Req 2.6).
    """
    if value is None:
        raise ConfigurationError(field_name, "value is required but was not provided")
    if not isinstance(value, str):
        raise ConfigurationError(field_name, "value must be a string")
    if value.strip() == "":
        raise ConfigurationError(
            field_name, "value must not be empty or whitespace-only"
        )
    return value


def _validate_int_in_range(
    value: Any, field_name: str, low: int, high: int
) -> int:
    """Validate that ``value`` is an integer within the inclusive range."""
    # Reject bools explicitly: ``bool`` is a subclass of ``int`` in Python.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(
            field_name, f"value must be an integer between {low} and {high}"
        )
    if not (low <= value <= high):
        raise ConfigurationError(
            field_name,
            f"value must be between {low} and {high} (inclusive)",
        )
    return value


def _validate_threshold(value: Any, field_name: str) -> float:
    """Validate that ``value`` is a real number in the inclusive 0.0..1.0 range."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(
            field_name,
            f"value must be a number between {THRESHOLD_MIN} and {THRESHOLD_MAX}",
        )
    numeric = float(value)
    if not (THRESHOLD_MIN <= numeric <= THRESHOLD_MAX):
        raise ConfigurationError(
            field_name,
            f"value must be between {THRESHOLD_MIN} and {THRESHOLD_MAX} (inclusive)",
        )
    return numeric


def _validate_theme_set(value: Any, field_name: str) -> frozenset[str]:
    """Validate that the theme set is a non-empty collection of non-blank strings."""
    if value is None:
        return frozenset(DEFAULT_THEME_SET)
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise ConfigurationError(
            field_name, "value must be a collection of theme labels"
        )
    themes = set()
    for theme in value:
        if not isinstance(theme, str) or theme.strip() == "":
            raise ConfigurationError(
                field_name, "every theme label must be a non-empty string"
            )
        themes.add(theme)
    if not themes:
        raise ConfigurationError(field_name, "value must contain at least one theme")
    return frozenset(themes)


class Config:
    """Validated NLP_Processor configuration.

    Construction performs fail-fast validation; an invalid argument raises
    :class:`ConfigurationError` before the object is usable, which guarantees no
    record is processed under a bad configuration (Req 2.2, 2.4).

    The ``api_key`` is held in memory only and is never exposed through
    ``repr`` or any error message (Req 2.6).
    """

    __slots__ = (
        "_api_key",
        "model_name",
        "max_attempts",
        "request_timeout_seconds",
        "similarity_threshold",
        "review_threshold",
        "theme_set",
    )

    def __init__(
        self,
        *,
        api_key: Any,
        model_name: Any,
        similarity_threshold: Any,
        max_attempts: Any = DEFAULT_MAX_ATTEMPTS,
        request_timeout_seconds: Any = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        review_threshold: Any = DEFAULT_REVIEW_THRESHOLD,
        theme_set: Any = None,
    ) -> None:
        # Required, non-blank credentials (Req 2.2, 2.4).
        self._api_key: str = _require_non_blank_str(api_key, "api_key")
        self.model_name: str = _require_non_blank_str(model_name, "model_name")

        # Bounded integer parameters with defaults.
        self.max_attempts: int = _validate_int_in_range(
            max_attempts, "max_attempts", MAX_ATTEMPTS_MIN, MAX_ATTEMPTS_MAX
        )
        self.request_timeout_seconds: int = _validate_int_in_range(
            request_timeout_seconds,
            "request_timeout_seconds",
            TIMEOUT_MIN,
            TIMEOUT_MAX,
        )

        # Thresholds in 0.0..1.0.
        self.similarity_threshold: float = _validate_threshold(
            similarity_threshold, "similarity_threshold"
        )
        self.review_threshold: float = _validate_threshold(
            review_threshold, "review_threshold"
        )

        # Configurable theme set, defaulting to the seven standard themes.
        self.theme_set: frozenset[str] = _validate_theme_set(theme_set, "theme_set")

    @property
    def api_key(self) -> str:
        """The configured API key.

        Held in memory only. Callers must never write this value to logs or
        error messages (Req 2.6).
        """
        return self._api_key

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "Config":
        """Build a :class:`Config` from a mapping (e.g. parsed env/JSON config).

        Only known keys are read; missing optional keys fall back to defaults.
        """
        if not isinstance(mapping, Mapping):
            raise ConfigurationError("config", "value must be a mapping of settings")

        kwargs: dict[str, Any] = {
            "api_key": mapping.get("api_key"),
            "model_name": mapping.get("model_name"),
            "similarity_threshold": mapping.get("similarity_threshold"),
        }
        # Optional values: only override the default when explicitly present.
        for optional in (
            "max_attempts",
            "request_timeout_seconds",
            "review_threshold",
            "theme_set",
        ):
            if optional in mapping:
                kwargs[optional] = mapping[optional]
        return cls(**kwargs)

    def __repr__(self) -> str:
        # Never include the API key value (Req 2.6).
        return (
            "Config("
            "api_key=<redacted>, "
            f"model_name={self.model_name!r}, "
            f"max_attempts={self.max_attempts}, "
            f"request_timeout_seconds={self.request_timeout_seconds}, "
            f"similarity_threshold={self.similarity_threshold}, "
            f"review_threshold={self.review_threshold}, "
            f"theme_set={sorted(self.theme_set)!r})"
        )


__all__ = [
    "Config",
    "ConfigurationError",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_REQUEST_TIMEOUT_SECONDS",
    "DEFAULT_REVIEW_THRESHOLD",
]
