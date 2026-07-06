"""Shared type literals and the configured theme set.

These literals define the closed value sets used across the NLP feedback
processing pipeline. They are referenced by the pydantic data models for
field-level validation.
"""

from __future__ import annotations

from typing import Literal

# Allowed source channels for incoming raw feedback (Req 1.4).
SourceChannel = Literal["email", "survey", "call_transcript", "social_post"]

# Configured theme set used by the classifier (Req 5.2). ``other`` is the
# catch-all assigned when no configured theme qualifies (Req 5.5).
ThemeLabel = Literal[
    "billing",
    "network_speed",
    "outage",
    "support_experience",
    "device_hardware",
    "pricing",
    "other",
]

# Sentiment polarity values (Req 6.1).
SentimentValue = Literal["positive", "neutral", "negative"]

# The default configured theme set (the seven standard themes). The classifier
# may be configured with a subset/superset, but this is the startup default.
DEFAULT_THEME_SET: frozenset[str] = frozenset(
    {
        "billing",
        "network_speed",
        "outage",
        "support_experience",
        "device_hardware",
        "pricing",
        "other",
    }
)

# Stage labels used to key failure entries to the pipeline stage that produced
# them (see ``FailureEntry``).
FailureStage = Literal[
    "ingestion",
    "classification",
    "sentiment",
    "severity",
    "parsing",
    "serialization",
    "clustering",
]

__all__ = [
    "SourceChannel",
    "ThemeLabel",
    "SentimentValue",
    "FailureStage",
    "DEFAULT_THEME_SET",
]
