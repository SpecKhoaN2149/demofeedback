"""Async NLP enrichment background task for customer feedback.

This module implements the background enrichment flow for the unified feedback
model (Requirements 2.x). When a feedback record is created, the enrichment task
runs asynchronously to invoke the existing NLPProcessor, extract insight data,
record the NLP-derived sentiment, and update the feedback record via
``FeedbackStore``. After any terminal status is written (completed/failed/
timeout) it invokes the Triage_Engine (Requirement 3.1).

The enrichment is designed to be graceful: if the NLP package is unavailable,
the API key is missing, or any processing error occurs, the feedback record is
marked with an appropriate failure status (failed/timeout) rather than crashing.
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
from app.services.feedback_store import FeedbackStore

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

# Maximum time (seconds) to wait for the best-effort location extraction call.
_LOCATION_TIMEOUT_SECONDS = 15

# Default location applied when no location is mentioned in the feedback (or the
# user is anonymous): Greenwood Village, Colorado.
_DEFAULT_LOCATION = {
    "city": "Greenwood Village",
    "state": "CO",
    "latitude": 39.6172,
    "longitude": -104.9508,
}

# Module-level store instance (matches the one used by routes)
_feedback_store = FeedbackStore()


# --------------------------------------------------------------------------- #
# Demo safety net
#
# For a single scripted demo message, use a canned, deterministic enrichment
# instead of a live Gemini call — so a live demo never fails/stalls on the
# network. It matches ONLY this exact contrived sentence (normalized for case,
# whitespace, and dash style), so it can never affect real customer feedback.
# --------------------------------------------------------------------------- #
DEMO_FEEDBACK_TEXT = (
    "My internet has been completely down for three days in Denver, Colorado, "
    "and I've called support four times with no fix. I work from home and this "
    "is costing me money - I'm beyond frustrated."
)
_DEMO_LOCATION = {
    "city": "Denver",
    "state": "CO",
    "latitude": 39.7392,
    "longitude": -104.9903,
}


def _normalize_demo(text: str) -> str:
    """Normalize text for demo matching: lowercase, unify dashes, collapse spaces."""
    t = text.strip().lower().replace("\u2014", "-").replace("\u2013", "-")
    return " ".join(t.split())


def _demo_enrichment(text: str):
    """Return a canned (EnrichmentResult, sentiment) for the demo text, else None."""
    if _normalize_demo(text) != _normalize_demo(DEMO_FEEDBACK_TEXT):
        return None
    result = EnrichmentResult(
        themes=[
            {"theme": "outage", "confidence": 0.98},
            {"theme": "support_experience", "confidence": 0.95},
        ],
        sentiment_confidence=0.99,
        severity_score=5,
        severity_factors=[
            "Complete loss of service sustained over multiple days.",
            "Repeated failed support contacts; work-from-home and financial impact.",
        ],
        language_code="en",
        language_confidence=0.99,
    )
    return result, "negative"


def _extract_location_sync(text: str) -> dict | None:
    """Best-effort extraction of a US location mentioned in the feedback text.

    Uses a single lightweight Gemini call (first model in the priority order)
    asking for a strict JSON object. Returns a dict with ``city``, ``state``
    (2-letter USPS code), ``latitude`` and ``longitude`` only when a specific US
    location is explicitly mentioned; returns ``None`` otherwise or on any error
    so the caller can apply the default location.
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None

    api_key = os.environ.get(_ENV_API_KEY, "").strip()
    if not api_key:
        return None

    models = _model_priority()
    model_name = models[0] if models else "gemini-2.5-flash-lite"

    system_instruction = (
        "You extract a single US location from customer feedback about an "
        "internet/cable provider. Only report a location when the text clearly "
        "mentions a specific US city, town, or state. If no location is clearly "
        "mentioned, or it is ambiguous or non-US, set mentioned to false. When "
        "mentioned is true, return the city name, the 2-letter USPS state code, "
        "and the approximate latitude and longitude (decimal degrees) of that "
        "place. Respond with JSON only."
    )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=f"Feedback text:\n{text}",
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                http_options=types.HttpOptions(
                    timeout=_LOCATION_TIMEOUT_SECONDS * 1000
                ),
            ),
        )
        import json

        data = json.loads(response.text)
    except Exception as e:  # pragma: no cover - network/parse errors are non-fatal
        logger.warning("Location extraction failed: %s", e)
        return None

    if not isinstance(data, dict) or not data.get("mentioned"):
        return None

    city = data.get("city")
    state = data.get("state")
    lat = data.get("latitude")
    lng = data.get("longitude")

    # Require a usable state code + coordinates to plot on the map.
    if not (isinstance(state, str) and len(state.strip()) == 2):
        return None
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        return None

    return {
        "city": str(city).strip() if city else None,
        "state": state.strip().upper(),
        "latitude": float(lat),
        "longitude": float(lng),
    }


async def _apply_location(feedback_id: uuid.UUID, text: str) -> None:
    """Attach a location to the feedback: extracted when mentioned, else default.

    Best-effort and never fatal — enrichment is already persisted before this
    runs, so any failure just falls back to the default location.
    """
    location: dict | None = None
    try:
        loop = asyncio.get_event_loop()
        location = await asyncio.wait_for(
            loop.run_in_executor(None, _extract_location_sync, text),
            timeout=_LOCATION_TIMEOUT_SECONDS + 2,
        )
    except Exception:
        location = None

    if not location:
        location = _DEFAULT_LOCATION

    try:
        _feedback_store.update_location(feedback_id, **location)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to persist location for feedback %s", feedback_id)


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


def _invoke_triage(feedback_id: str) -> None:
    """Invoke the Triage_Engine after enrichment reaches a terminal status.

    Requirement 3.1: triage runs after enrichment reaches a terminal status
    (completed/failed/timeout). Imported locally to avoid an import cycle
    (``triage_engine`` imports ``feedback_store``, and enrichment imports both).
    Any error inside triage must never crash this background task, so failures
    are caught and logged; ``run_triage`` itself already routes internal errors
    to admin review.
    """
    try:
        from app.services.triage_engine import run_triage

        run_triage(feedback_id)
    except Exception:  # pragma: no cover - defensive, triage never crashes enrichment
        logger.exception(
            "Triage invocation failed for feedback %s (enrichment already recorded)",
            feedback_id,
        )


async def run_enrichment(feedback_id: str, text: str) -> None:
    """Background task that performs NLP enrichment on a feedback record.

    This function:
    1. Invokes NLPProcessor.process_batch() with a 30s timeout and Gemini
       model-priority fallback (Req 2.8)
    2. On success, extracts EnrichmentResult from the first InsightRecord and
       records the NLP-derived sentiment via FeedbackStore.update_enrichment
       (Req 2.2, 2.3)
    3. Handles failures and timeout by marking the record failed/timeout
       (Req 2.6, 2.7)
    4. After writing ANY terminal status (completed/failed/timeout), invokes the
       Triage_Engine (Req 3.1). Triage routes failed/timeout records to review.

    Args:
        feedback_id: UUID string of the feedback record to enrich.
        text: The combined text to send to the NLP pipeline.
    """
    fid = uuid.UUID(feedback_id)

    # Demo safety net: for the scripted demo message, use a canned result and a
    # fixed location so the live demo is instant and can't fail on the network.
    demo = _demo_enrichment(text)
    if demo is not None:
        result_obj, sentiment = demo
        _feedback_store.update_enrichment(fid, result_obj, sentiment)
        try:
            _feedback_store.update_location(fid, **_DEMO_LOCATION)
        except Exception:  # pragma: no cover - location is best-effort
            pass
        logger.info("NLP enrichment: used scripted demo result for feedback %s", feedback_id)
        _invoke_triage(feedback_id)
        return

    try:
        # Run NLP processing in a thread with timeout (Req 2.8)
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _do_nlp_processing, text),
            timeout=_ENRICHMENT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        # Requirement 2.7: mark as timeout after 30 seconds, then triage.
        logger.warning("NLP enrichment timed out for feedback %s", feedback_id)
        _feedback_store.mark_enrichment_failed(
            fid, "NLP processing exceeded 30 second timeout", "timeout"
        )
        _invoke_triage(feedback_id)
        return
    except Exception as e:
        # Unexpected error during async execution (Req 2.6).
        logger.exception("Unexpected error during enrichment for %s", feedback_id)
        _feedback_store.mark_enrichment_failed(
            fid, f"Unexpected error: {type(e).__name__}: {e}", "failed"
        )
        _invoke_triage(feedback_id)
        return

    # Check if NLP processing returned an error (config/import issues) (Req 2.6).
    if "error" in result and "success" not in result:
        logger.warning(
            "NLP enrichment failed for feedback %s: %s",
            feedback_id,
            result["error"],
        )
        _feedback_store.mark_enrichment_failed(fid, result["error"], "failed")
        _invoke_triage(feedback_id)
        return

    # We have a successful BatchOutput.
    output = result["output"]

    # Requirement 2.2/2.3: Extract from first InsightRecord if present.
    enrichment_result = _extract_enrichment_result(output)

    if enrichment_result is not None:
        # The NLP-derived sentiment is recorded alongside the enrichment result;
        # it is never client-supplied (Req 2.3, 2.4). InsightRecord.sentiment is
        # a Literal["positive","neutral","negative"] plain string.
        sentiment = output.insights[0].sentiment
        _feedback_store.update_enrichment(fid, enrichment_result, sentiment)
        logger.info("NLP enrichment completed for feedback %s", feedback_id)
        # Best-effort location (extracted when mentioned, else default). Runs
        # after enrichment is persisted so it can never affect the core result.
        await _apply_location(fid, text)
        _invoke_triage(feedback_id)
        return

    # BatchOutput has zero InsightRecords.
    if output.failures:
        # At least one FailureEntry — store stage and reason (Req 2.6).
        failure = output.failures[0]
        reason = f"[{failure.stage}] {failure.reason}"
        logger.warning(
            "NLP enrichment produced failure for feedback %s: %s",
            feedback_id,
            reason,
        )
        _feedback_store.mark_enrichment_failed(fid, reason, "failed")
    else:
        # Zero InsightRecords and zero FailureEntries (Req 2.6).
        reason = "NLP processing produced no insight records"
        logger.warning(
            "NLP enrichment produced no insights for feedback %s", feedback_id
        )
        _feedback_store.mark_enrichment_failed(fid, reason, "failed")

    _invoke_triage(feedback_id)
