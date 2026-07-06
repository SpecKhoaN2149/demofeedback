"""Async NLP enrichment background task for customer submissions.

This module implements the background enrichment flow described in Requirements
13.1–13.6. When a submission is created, the enrichment task runs asynchronously
to invoke the existing NLPProcessor, extract insight data, and update the
submission record.

The enrichment is designed to be graceful: if the NLP package is unavailable,
the API key is missing, or any processing error occurs, the submission is marked
with an appropriate failure status rather than crashing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from app.models.submission import EnrichmentResult
from app.services.submission_store import SubmissionStore

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# The `nlp_processing` package lives at the repository root, one level above the
# backend/ directory. When the API is started from backend/ (the documented way
# to run uvicorn), that root is not on sys.path, so `import nlp_processing`
# fails with ModuleNotFoundError. Add the repo root to sys.path here so the
# enrichment pipeline is importable regardless of the working directory.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if (_REPO_ROOT / "nlp_processing").is_dir() and str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Environment variable names for NLP configuration
_ENV_API_KEY = "GEMINI_API_KEY"
_ENV_MODEL_NAME = "GEMINI_MODEL_NAME"
_ENV_MODEL_PRIORITY = "GEMINI_MODEL_PRIORITY"
# Default priority order: the pipeline tries these models in turn and uses the
# first that returns usable insights, falling back automatically when a model
# is unavailable, out of quota, or temporarily overloaded (503/504).
_DEFAULT_MODEL_PRIORITY = [
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]
_DEFAULT_SIMILARITY_THRESHOLD = 0.75

# Maximum time (seconds) to wait for NLP processing before marking as timeout
_ENRICHMENT_TIMEOUT_SECONDS = 30

# Module-level store instance (matches the one used by routes)
_submission_store = SubmissionStore()


def _model_priority() -> list[str]:
    """Resolve the ordered list of models to try, highest priority first.

    Resolution order:
      1. ``GEMINI_MODEL_PRIORITY`` — comma-separated list (explicit ordering).
      2. ``GEMINI_MODEL_NAME`` — a single model (backward compatible).
      3. The built-in default priority list.
    """
    raw_priority = os.environ.get(_ENV_MODEL_PRIORITY, "").strip()
    if raw_priority:
        models = [m.strip() for m in raw_priority.split(",") if m.strip()]
        if models:
            return models

    single = os.environ.get(_ENV_MODEL_NAME, "").strip()
    if single:
        return [single]

    return list(_DEFAULT_MODEL_PRIORITY)


def _do_nlp_processing(text: str) -> dict:
    """Synchronous NLP processing wrapper with model fallback.

    Tries each model in the configured priority order and returns the first
    run that produces at least one insight. If no model yields insights, the
    last attempt's result is returned so the caller can record the failure.

    Returns a dict with either:
      - {"success": True, "output": BatchOutput, "model_used": str}
      - {"error": str}  (exception or configuration issue)
    """
    try:
        from nlp_processing.models import RawFeedback  # noqa: F401
        from nlp_processing.orchestrator import NLPProcessor
    except ImportError as e:
        return {"error": f"nlp_processing package not available: {e}"}

    api_key = os.environ.get(_ENV_API_KEY, "").strip()
    if not api_key:
        return {"error": "GEMINI_API_KEY environment variable is not set"}

    models = _model_priority()
    # With multiple candidate models, keep per-model retries low so a stuck
    # model (503/504) falls back quickly instead of exhausting the timeout.
    max_attempts = 2 if len(models) > 1 else 5

    raw_feedback = RawFeedback(
        source_channel="social_post",
        text=text,
        metadata={},
    )

    last_result: dict | None = None
    for model_name in models:
        try:
            processor = NLPProcessor.from_settings(
                api_key=api_key,
                model_name=model_name,
                similarity_threshold=_DEFAULT_SIMILARITY_THRESHOLD,
                max_attempts=max_attempts,
            )
        except Exception as e:
            last_result = {
                "error": f"Failed to initialize NLPProcessor for {model_name}: {e}"
            }
            continue

        try:
            output = processor.process_batch([raw_feedback])
        except Exception as e:
            last_result = {
                "error": (
                    f"NLPProcessor.process_batch raised for {model_name}: "
                    f"{type(e).__name__}: {e}"
                )
            }
            continue

        if output.insights:
            logger.info("NLP enrichment succeeded using model %s", model_name)
            return {"success": True, "output": output, "model_used": model_name}

        # No insights (model unavailable, quota, or transient overload). Keep as
        # a fallback candidate and try the next model in priority order.
        logger.warning(
            "Model %s produced no insights; falling back to next priority model",
            model_name,
        )
        last_result = {"success": True, "output": output, "model_used": model_name}

    return last_result or {"error": "no NLP models configured"}


def _extract_enrichment_result(output) -> EnrichmentResult | None:
    """Extract EnrichmentResult from the first InsightRecord in a BatchOutput.

    Returns None if no InsightRecords are present.
    Implements requirement 13.2.
    """
    if not output.insights:
        return None

    insight = output.insights[0]

    # Extract themes as list of dicts with theme and confidence
    themes = [
        {"theme": ta.theme, "confidence": ta.confidence}
        for ta in insight.themes
    ]

    # Extract severity factors as list of description strings
    severity_factors = [sf.description for sf in insight.severity_factors]

    return EnrichmentResult(
        themes=themes,
        sentiment_confidence=insight.sentiment_confidence,
        severity_score=insight.severity_score,
        severity_factors=severity_factors,
        language_code=insight.language_code,
        language_confidence=insight.language_confidence,
    )


async def run_enrichment(submission_id: str, text: str) -> None:
    """Background task that performs NLP enrichment on a submission.

    This function:
    1. Constructs RawFeedback with source_channel="social_post" (Req 13.1)
    2. Invokes NLPProcessor.process_batch() with a 30s timeout (Req 13.5)
    3. Extracts EnrichmentResult from first InsightRecord (Req 13.2, 13.6)
    4. Handles failures and timeout appropriately (Req 13.3, 13.4, 13.5)
    5. Updates the submission via SubmissionStore (Req 13.6)

    Args:
        submission_id: UUID string of the submission to enrich.
        text: The combined text to send to the NLP pipeline.
    """
    sid = uuid.UUID(submission_id)

    try:
        # Run NLP processing in a thread with timeout (Req 13.5)
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _do_nlp_processing, text),
            timeout=_ENRICHMENT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        # Requirement 13.5: mark as timeout after 30 seconds
        logger.warning("NLP enrichment timed out for submission %s", submission_id)
        _submission_store.mark_enrichment_failed(
            sid, "NLP processing exceeded 30 second timeout", "timeout"
        )
        return
    except Exception as e:
        # Unexpected error during async execution
        logger.exception("Unexpected error during enrichment for %s", submission_id)
        _submission_store.mark_enrichment_failed(
            sid, f"Unexpected error: {type(e).__name__}: {e}", "failed"
        )
        return

    # Check if NLP processing returned an error (config/import issues)
    if "error" in result and "success" not in result:
        logger.warning(
            "NLP enrichment failed for submission %s: %s",
            submission_id,
            result["error"],
        )
        _submission_store.mark_enrichment_failed(sid, result["error"], "failed")
        return

    # We have a successful BatchOutput
    output = result["output"]

    # Requirement 13.2: Extract from first InsightRecord if present
    enrichment_result = _extract_enrichment_result(output)

    if enrichment_result is not None:
        # Requirement 13.6: Store enrichment and mark as completed
        _submission_store.update_enrichment(sid, enrichment_result)
        logger.info("NLP enrichment completed for submission %s", submission_id)
        return

    # Requirement 13.3: BatchOutput has zero InsightRecords
    if output.failures:
        # At least one FailureEntry — store stage and reason
        failure = output.failures[0]
        reason = f"[{failure.stage}] {failure.reason}"
        logger.warning(
            "NLP enrichment produced failure for submission %s: %s",
            submission_id,
            reason,
        )
        _submission_store.mark_enrichment_failed(sid, reason, "failed")
    else:
        # Requirement 13.4: Zero InsightRecords and zero FailureEntries
        reason = "NLP processing produced no insight records"
        logger.warning(
            "NLP enrichment produced no insights for submission %s", submission_id
        )
        _submission_store.mark_enrichment_failed(sid, reason, "failed")
