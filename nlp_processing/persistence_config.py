"""Configuration classes for persistence, caching, and trend detection.

Provides fail-fast validated configuration models using Pydantic v2.
Invalid values raise :class:`~nlp_processing.config.ConfigurationError`
at construction time, preventing the pipeline from running with bad settings.

Implements Requirements 1.5, 1.9, 2.3, 2.4, 3.3, 4.2, 4.4.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from .config import ConfigurationError

# Recognized persistence backends (extensible later).
_SUPPORTED_BACKENDS = frozenset({"sqlite"})


class PersistenceConfig(BaseModel):
    """Configuration for the durable persistence backend.

    Validates that ``backend`` is a recognized value and ``db_path`` is
    non-empty. Raises :class:`ConfigurationError` on invalid input.
    """

    backend: str
    db_path: str

    @field_validator("backend", mode="before")
    @classmethod
    def _validate_backend(cls, v: str) -> str:
        if not isinstance(v, str) or v.strip() == "":
            raise ConfigurationError(
                "backend", "value is required and must be a non-empty string"
            )
        if v not in _SUPPORTED_BACKENDS:
            raise ConfigurationError(
                "backend",
                f"unrecognized backend '{v}'; supported backends: {sorted(_SUPPORTED_BACKENDS)}",
            )
        return v

    @field_validator("db_path", mode="before")
    @classmethod
    def _validate_db_path(cls, v: str) -> str:
        if not isinstance(v, str) or v.strip() == "":
            raise ConfigurationError(
                "db_path", "value is required and must be a non-empty string"
            )
        return v


class CacheConfig(BaseModel):
    """Configuration for the enrichment result cache.

    Validates that ``ttl_hours`` is an integer in the inclusive range 1..720.
    Raises :class:`ConfigurationError` on invalid input.
    """

    enabled: bool = True
    ttl_hours: int = 24

    @field_validator("ttl_hours", mode="before")
    @classmethod
    def _validate_ttl_hours(cls, v: int) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ConfigurationError(
                "ttl_hours", "value must be an integer between 1 and 720"
            )
        if not (1 <= v <= 720):
            raise ConfigurationError(
                "ttl_hours", "value must be between 1 and 720 (inclusive)"
            )
        return v


class TrendConfig(BaseModel):
    """Configuration for trend detection thresholds.

    Validates:
    - ``spike_threshold_pct``: integer in 1..1000 (relative % increase for theme spikes)
    - ``sentiment_shift_ppt``: integer in 1..50 (percentage points for sentiment shift)
    - ``severity_escalation``: float in 0.5..4.0 (points on the 1-5 severity scale)

    Raises :class:`ConfigurationError` on invalid input.
    """

    spike_threshold_pct: int = 50
    sentiment_shift_ppt: int = 15
    severity_escalation: float = 1.0

    @field_validator("spike_threshold_pct", mode="before")
    @classmethod
    def _validate_spike_threshold_pct(cls, v: int) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ConfigurationError(
                "spike_threshold_pct",
                "value must be an integer between 1 and 1000",
            )
        if not (1 <= v <= 1000):
            raise ConfigurationError(
                "spike_threshold_pct",
                "value must be between 1 and 1000 (inclusive)",
            )
        return v

    @field_validator("sentiment_shift_ppt", mode="before")
    @classmethod
    def _validate_sentiment_shift_ppt(cls, v: int) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ConfigurationError(
                "sentiment_shift_ppt",
                "value must be an integer between 1 and 50",
            )
        if not (1 <= v <= 50):
            raise ConfigurationError(
                "sentiment_shift_ppt",
                "value must be between 1 and 50 (inclusive)",
            )
        return v

    @field_validator("severity_escalation", mode="before")
    @classmethod
    def _validate_severity_escalation(cls, v: float) -> float:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ConfigurationError(
                "severity_escalation",
                "value must be a number between 0.5 and 4.0",
            )
        numeric = float(v)
        if not (0.5 <= numeric <= 4.0):
            raise ConfigurationError(
                "severity_escalation",
                "value must be between 0.5 and 4.0 (inclusive)",
            )
        return numeric


__all__ = [
    "CacheConfig",
    "PersistenceConfig",
    "TrendConfig",
]
