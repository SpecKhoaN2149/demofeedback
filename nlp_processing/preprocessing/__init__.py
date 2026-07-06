"""Preprocessing layer for the NLP feedback routing pipeline.

This package provides the Preprocessor class which transforms raw
SocialFeedback and WidgetFeedback records into unified CanonicalFeedback
records via text cleaning, PII masking, language detection, deduplication,
and profanity detection.
"""

from .preprocessor import Preprocessor

__all__ = ["Preprocessor"]
