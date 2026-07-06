"""Ingestion package for NLP feedback routing.

Provides dual-channel ingestion services:
- SocialListener: ingests public social media feedback (Reddit, X, Facebook)
- WidgetIntake: ingests direct customer submissions (app widget, website form, support intake)

Also re-exports the original batch ingestion component for backward compatibility.
"""

from .batch_ingestion import (
    ALLOWED_CHANNELS,
    MAX_BATCH_SIZE,
    MAX_TEXT_LENGTH,
    IngestionComponent,
    IngestionResult,
)
from .social_listener import SocialListener
from .widget_intake import WidgetIntake

__all__ = [
    # Legacy batch ingestion
    "IngestionComponent",
    "IngestionResult",
    "MAX_BATCH_SIZE",
    "MAX_TEXT_LENGTH",
    "ALLOWED_CHANNELS",
    # New feedback routing ingestion
    "SocialListener",
    "WidgetIntake",
]
