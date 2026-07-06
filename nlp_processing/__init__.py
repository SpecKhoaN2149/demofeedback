"""NLP Feedback Processing package.

Enrichment layer that converts normalized telecom customer feedback into
structured, ranked insights using the Google Gemini API.

Public API
----------
The package exposes a single processing entry point plus the configuration and
the public data models needed to call it and read its results:

* :class:`NLPProcessor` -- the batch orchestrator (Req 10). Build it with
  :meth:`NLPProcessor.from_config` (validated :class:`Config`) or
  :meth:`NLPProcessor.from_settings` (raw keyword settings, validated into a
  :class:`Config` first), then call :meth:`NLPProcessor.process_batch` and
  :meth:`NLPProcessor.serialize`.
* :class:`Config` / :class:`ConfigurationError` -- fail-fast configuration that
  validates every operator-supplied value before any record is processed
  (Req 2.2, 2.4).
* :class:`BatchValidationError` -- raised when a submitted batch violates a
  size bound (Req 10.5).
* The public models -- :class:`RawFeedback` (input), and :class:`BatchOutput`,
  :class:`InsightRecord`, :class:`Cluster`, :class:`FailureEntry`,
  :class:`BatchSummary` (output).

Sub-packages for the NLP feedback routing pipeline:

* :mod:`nlp_processing.ingestion` -- Dual-channel ingestion (SocialListener, WidgetIntake)
* :mod:`nlp_processing.preprocessing` -- Text cleaning, PII masking, deduplication (Preprocessor)
* :mod:`nlp_processing.routing` -- Decision engine and pipeline orchestration (DecisionEngine, PipelineOrchestrator)
* :mod:`nlp_processing.persistence` -- FeedbackStore with relational schema
* :mod:`nlp_processing.serialization` -- Deterministic JSON serialization
* :mod:`nlp_processing.trends` -- Trend detection and cluster lifecycle
"""

from .config import Config, ConfigurationError
from .models import (
    BatchOutput,
    BatchSummary,
    Cluster,
    FailureEntry,
    InsightRecord,
    RawFeedback,
)
from .orchestrator import BatchValidationError, NLPProcessor

# Feedback routing pipeline imports
from .ingestion import SocialListener, WidgetIntake
from .preprocessing import Preprocessor
from .routing import DecisionEngine, PipelineOrchestrator, ProcessingResult
from .persistence import FeedbackStore

__all__ = [
    # Entry point
    "NLPProcessor",
    "BatchValidationError",
    # Configuration
    "Config",
    "ConfigurationError",
    # Public models
    "RawFeedback",
    "BatchOutput",
    "InsightRecord",
    "Cluster",
    "FailureEntry",
    "BatchSummary",
    # Feedback routing pipeline
    "SocialListener",
    "WidgetIntake",
    "Preprocessor",
    "DecisionEngine",
    "PipelineOrchestrator",
    "ProcessingResult",
    "FeedbackStore",
]
