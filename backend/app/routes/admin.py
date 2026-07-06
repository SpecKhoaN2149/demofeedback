"""Admin API endpoints for queue management, tickets, dashboard, marketing, and trends.

Provides authenticated endpoints for Spectrum staff to manage the review queue,
sort neutral submissions, view operational data, and run trend analysis.

Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.6, 11.4, 11.5, 11.6, 15.1, 15.2, 15.3, 15.4, 15.5, 16.2, 16.5, 16.6, 17.4
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.middleware.auth import require_admin
from app.models.auth import AdminUser
from app.models.requests import (
    DashboardSummary,
    PaginatedResponse,
    SortRequest,
    TrendAnalysisRequest,
)
from app.models.ticket import Ticket
from app.database import get_connection
from app.services.admin_review_queue import AdminReviewQueue
from app.services.marketing_engine import MarketingEngine
from app.services.submission_store import SubmissionStore
from app.services.ticketing_pipeline import TicketingPipeline

router = APIRouter()

# Service instances
_submission_store = SubmissionStore()
_marketing_engine = MarketingEngine()
_admin_review_queue = AdminReviewQueue()
_ticketing_pipeline = TicketingPipeline()

# Valid issue categories for negative sorting
_VALID_CATEGORIES = {
    "billing",
    "network_speed",
    "outage",
    "support_experience",
    "device_hardware",
    "pricing",
}


# =============================================================================
# Queue Endpoints
# =============================================================================


@router.get("/queue")
async def list_queue(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    admin: AdminUser = Depends(require_admin),
):
    """List all submissions in the admin review queue.

    Returns a paginated list ordered by queued_at ascending (oldest first),
    with submission details including enrichment summaries.

    Validates: Requirements 10.1, 11.4
    """
    items = _admin_review_queue.list_queue(limit=limit, offset=offset)
    return {"items": items, "limit": limit, "offset": offset}


@router.patch("/queue/{submission_id}/sort")
async def sort_submission(
    submission_id: str,
    body: SortRequest,
    admin: AdminUser = Depends(require_admin),
):
    """Sort a neutral submission to negative or positive.

    For sort-to-negative: creates a high-priority ticket, sets progress to 50%,
    and removes the submission from the queue.

    For sort-to-positive: logs praise in marketing engine, sets progress to 100%,
    and removes the submission from the queue.

    Returns 409 if the submission has already been sorted (not in queue).

    Validates: Requirements 10.3, 10.4, 10.6, 11.5, 11.6
    """
    # Validate UUID format
    try:
        parsed_id = uuid.UUID(submission_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    # Check if submission is in the queue
    if not _admin_review_queue.is_queued(submission_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Submission already sorted",
        )

    # Retrieve the submission for details needed by downstream services
    submission = _submission_store.get(parsed_id)
    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    if body.target_sentiment == "negative":
        # Validate issue_category is provided and valid
        if not body.issue_category:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="issue_category is required when sorting to negative",
            )
        if body.issue_category not in _VALID_CATEGORIES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid issue category. Must be one of: {', '.join(sorted(_VALID_CATEGORIES))}",
            )

        # Sort to negative: create ticket, update progress, remove from queue
        try:
            description = submission.comment_text or submission.detailed_description or submission.core_request
            _ticketing_pipeline.create_ticket(
                submission_id=submission_id,
                category=body.issue_category,
                description=description,
            )
        except Exception as e:
            # Requirement 10.6: leave submission in queue with progress unchanged
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create ticket. Submission remains in queue.",
            ) from e

        # Update progress to 50% and remove from queue
        _submission_store.update_progress(parsed_id, 50)
        _admin_review_queue.remove(submission_id)

    else:  # target_sentiment == "positive"
        # Sort to positive: log marketing, update progress, remove from queue
        try:
            praise_text = submission.praise_text or submission.comment_text or submission.core_request
            _marketing_engine.log_praise(
                submission_id=submission_id,
                customer_name=submission.customer_name,
                praise_text=praise_text,
                social_sharing=submission.social_sharing,
            )
        except Exception as e:
            # Requirement 10.6: leave submission in queue with progress unchanged
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to log marketing. Submission remains in queue.",
            ) from e

        # Update progress to 100% and remove from queue
        _submission_store.update_progress(parsed_id, 100)
        _admin_review_queue.remove(submission_id)

    # Return success with updated submission info
    updated_submission = _submission_store.get(parsed_id)
    return {
        "submission_id": submission_id,
        "target_sentiment": body.target_sentiment,
        "progress_state": updated_submission.progress_state if updated_submission else None,
        "detail": f"Submission sorted to {body.target_sentiment}",
    }


# =============================================================================
# Ticket Endpoints
# =============================================================================


@router.get("/tickets", response_model=list[Ticket])
async def list_tickets(admin: AdminUser = Depends(require_admin)):
    """List all active tickets (open or in_progress).

    Returns tickets ordered by creation timestamp ascending.

    Validates: Requirements 16.5
    """
    return _ticketing_pipeline.list_active()


@router.patch("/tickets/{ticket_id}/advance", response_model=Ticket)
async def advance_ticket(ticket_id: str, admin: AdminUser = Depends(require_admin)):
    """Advance a ticket to the next valid status.

    Status transitions follow the sequence: open → in_progress → resolved.
    Updates the linked submission's progress state accordingly.

    Returns 409 Conflict if the ticket is not found or the transition is invalid
    (e.g., ticket is already resolved).

    Validates: Requirements 16.2, 16.5, 16.6
    """
    # Validate ticket_id format
    try:
        uuid.UUID(ticket_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid ticket ID format: {ticket_id}",
        )

    try:
        updated_ticket = _ticketing_pipeline.advance_status(ticket_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    return updated_ticket


# =============================================================================
# Dashboard Endpoint
# =============================================================================


@router.get("/dashboard", response_model=DashboardSummary)
async def get_dashboard(admin: AdminUser = Depends(require_admin)):
    """Return admin dashboard summary statistics.

    Aggregates submission counts by sentiment and progress state,
    plus the top 5 issue categories by frequency for negative submissions.

    Validates: Requirements 15.1, 15.5
    """
    # Get counts grouped by sentiment and progress state
    counts = _submission_store.count_by_sentiment()

    # Compute totals
    total_submissions = sum(entry["total"] for entry in counts.values())

    # Build by_sentiment: {sentiment: count}
    by_sentiment: dict[str, int] = {}
    for sentiment, data in counts.items():
        by_sentiment[sentiment] = data["total"]

    # Build by_progress_state: {progress_state: count}
    by_progress_state: dict[str, int] = {}
    for data in counts.values():
        for progress, count in data["by_progress"].items():
            key = str(progress)
            by_progress_state[key] = by_progress_state.get(key, 0) + count

    # Query top 5 issue categories by frequency (negative submissions only)
    top_categories: list[dict] = []
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT issue_category, COUNT(*) as count
            FROM submissions
            WHERE sentiment = 'negative' AND issue_category IS NOT NULL
            GROUP BY issue_category
            ORDER BY COUNT(*) DESC
            LIMIT 5
            """
        ).fetchall()
        top_categories = [
            {"category": row["issue_category"], "count": row["count"]}
            for row in rows
        ]

    # NLP enrichment analytics (Requirement: surface NLP output in the UI)
    analytics = _submission_store.enrichment_analytics()

    return DashboardSummary(
        total_submissions=total_submissions,
        by_sentiment=by_sentiment,
        by_progress_state=by_progress_state,
        top_categories=top_categories,
        enrichment_status_counts=analytics["status_counts"],
        top_themes=analytics["top_themes"],
        average_severity=analytics["average_severity"],
        by_language=analytics["by_language"],
    )


# =============================================================================
# Marketing Endpoint
# =============================================================================


@router.get("/marketing", response_model=PaginatedResponse)
async def get_marketing_log(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    admin: AdminUser = Depends(require_admin),
):
    """Return paginated marketing log entries.

    Validates: Requirements 17.4
    """
    entries = _marketing_engine.list_entries(limit=limit, offset=offset)

    # Get total count for pagination metadata
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) as total FROM marketing_log").fetchone()
        total = row["total"] if row else 0

    return PaginatedResponse(
        items=[entry.model_dump(mode="json") for entry in entries],
        total=total,
        limit=limit,
        offset=offset,
    )


# =============================================================================
# Trends Endpoint
# =============================================================================


@router.post("/trends")
async def run_trend_analysis(
    request: TrendAnalysisRequest,
    admin: AdminUser = Depends(require_admin),
):
    """Run trend analysis comparing baseline and current time windows.

    Validates each window's start < end and ensures windows do not overlap.
    Returns a TrendReport from the NLPProcessor or a placeholder structure.

    Validates: Requirements 15.2, 15.3, 15.4
    """
    # Validate baseline window: start must be before end
    if request.baseline_window.start >= request.baseline_window.end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid time window configuration: baseline window start must be before end",
        )

    # Validate current window: start must be before end
    if request.current_window.start >= request.current_window.end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid time window configuration: current window start must be before end",
        )

    # Validate no overlap: windows must not overlap
    # Overlap occurs if one window starts before the other ends and ends after the other starts
    if (
        request.baseline_window.start < request.current_window.end
        and request.current_window.start < request.baseline_window.end
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid time window configuration: baseline and current windows must not overlap",
        )

    # Placeholder response — actual NLP integration will be wired in task 10.1
    # When NLPProcessor is integrated, this will call:
    #   from nlp_processing.models.enhancements import TimeWindow as NLPTimeWindow
    #   nlp_baseline = NLPTimeWindow(start=..., end=...)
    #   nlp_current = NLPTimeWindow(start=..., end=...)
    #   report = nlp_processor.detect_trends(nlp_baseline, nlp_current)
    #   return report.model_dump()
    return {
        "theme_spikes": [],
        "sentiment_shifts": [],
        "severity_escalations": [],
        "notes": ["Trend analysis integration pending — placeholder response"],
    }
