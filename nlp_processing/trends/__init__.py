"""Trend detection package for the NLP pipeline.

Provides the TrendDetector class that identifies theme frequency spikes,
sentiment shifts, and severity escalations by comparing historical and
current time windows of persisted batch data.
"""

from .detector import TrendDetector

__all__ = ["TrendDetector"]
