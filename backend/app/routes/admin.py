"""Admin API endpoints for feedback review, triage, tickets, dashboard, marketing, and trends.

Provides authenticated endpoints for Spectrum staff to review feedback routed
to manual triage, record triage decisions, inspect individual feedback records,
view aggregate dashboard counts, and run marketing/trend tooling.

All admin endpoints require a valid session token via ``Depends(require_admin)``
(Requirement 11.4).

Validates: Requirements 3.6, 3.7, 3.8, 10.1, 10.2, 10.3, 11.4
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.middleware.auth import require_admin
from app.models.auth import AdminUser
from app.models.feedback import CommentCreate, Feedback, TicketComment, TriageRequest
from app.models.requests import (
    PaginatedResponse,
    TrendAnalysisRequest,
)
from app.models.ticket import Ticket, TicketDetail, TicketWithCount
from app.services.feedback_store import FeedbackStore
from app.services.ticket_comment_store import TicketCommentStore
from app.services.ticketing_pipeline import TicketingPipeline

router = APIRouter()

# Service instances
_feedback_store = FeedbackStore()
_ticketing_pipeline = TicketingPipeline()
_ticket_comment_store = TicketCommentStore()


def _theme_label(theme: dict) -> str | None:
    """Extract a theme label from an enrichment theme dict, if present."""
    if not isinstance(theme, dict):
        return None
    candidate = theme.get("theme") or theme.get("name") or theme.get("label")
    return str(candidate) if candidate else None


def _aggregate_window(feedback: list[Feedback]) -> dict:
    """Aggregate themes, sentiment, and severity over a window of feedback.

    Includes every supplied feedback record regardless of triage outcome, so
    ``no_action`` feedback still contributes to the aggregation (Req 11.1,
    11.2). Returns theme counts, sentiment counts, average severity and the
    total record count for the window.
    """
    theme_counts: dict[str, int] = {}
    sentiment_counts: dict[str, int] = {}
    department_counts: dict[str, int] = {}
    severity_total = 0
    severity_n = 0

    for fb in feedback:
        # Sentiment counts (NULL sentiment surfaced as "unknown").
        key = fb.sentiment if fb.sentiment is not None else "unknown"
        sentiment_counts[key] = sentiment_counts.get(key, 0) + 1

        # Department routing counts (NULL department is skipped).
        dept = getattr(fb, "department", None)
        if dept:
            department_counts[dept] = department_counts.get(dept, 0) + 1

        result = fb.enrichment_result
        if result is None:
            continue
        for theme in result.themes:
            label = _theme_label(theme)
            if label:
                theme_counts[label] = theme_counts.get(label, 0) + 1
        severity_total += result.severity_score
        severity_n += 1

    average_severity = (severity_total / severity_n) if severity_n else 0.0

    return {
        "count": len(feedback),
        "theme_counts": theme_counts,
        "sentiment_counts": sentiment_counts,
        "department_counts": department_counts,
        "average_severity": average_severity,
    }


def _derive_issue_category(feedback: Feedback) -> str:
    """Derive an issue category for a new ticket from a feedback's enrichment.

    Uses the first detected theme from the NLP enrichment result when available
    (theme dicts carry a ``theme`` key), falling back to ``"general"``.
    """
    result = feedback.enrichment_result
    if result and result.themes:
        first = result.themes[0]
        if isinstance(first, dict):
            candidate = first.get("theme") or first.get("name") or first.get("label")
            if candidate:
                return str(candidate)
    return "general"


# =============================================================================
# Feedback Review & Triage Endpoints
# =============================================================================


@router.get("/review", response_model=list[Feedback])
async def list_review(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    admin: AdminUser = Depends(require_admin),
):
    """List feedback records routed to admin review (``needs_review = 1``).

    Returns hydrated Feedback records (newest first), paginated by
    ``limit``/``offset`` so admins can work through the manual triage queue.

    Validates: Requirements 10.2, 11.4
    """
    return _feedback_store.list_needs_review(limit=limit, offset=offset)


@router.get("/review/count")
async def review_count(admin: AdminUser = Depends(require_admin)):
    """Return the number of feedback records awaiting manual review.

    Powers the sidebar's Review Queue badge. Kept as a lightweight COUNT so it
    can be polled cheaply on navigation.

    Validates: Requirements 10.2, 11.4
    """
    return {"count": _feedback_store.count_needs_review()}


@router.patch("/feedback/{feedback_id}/triage", response_model=Feedback)
async def triage_feedback(
    feedback_id: str,
    body: TriageRequest,
    admin: AdminUser = Depends(require_admin),
):
    """Record a manual admin triage decision for a feedback record.

    For ``action_required``: links the feedback to the admin-selected existing
    ticket (via ``ticket_id``) or, when none is supplied, creates a new ticket
    from the feedback. For ``no_action``: retains the feedback with no ticket
    link. Either way the decision is recorded with ``decision_source = "admin"``
    and the record is cleared from the review queue.

    Validates: Requirements 3.6, 3.7, 3.8, 11.4
    """
    # Validate UUID format
    try:
        parsed_id = uuid.UUID(feedback_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )

    feedback = _feedback_store.get(parsed_id)
    if feedback is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )

    if body.outcome == "action_required":
        if body.ticket_id is not None:
            # Link to an admin-selected existing ticket (Req 3.6, 5.4).
            try:
                _ticketing_pipeline.link_feedback(str(body.ticket_id), feedback_id)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Ticket not found",
                )
        else:
            # Create a new ticket from this feedback (Req 3.6, 5.3).
            _ticketing_pipeline.create_ticket(
                feedback_id=feedback_id,
                issue_category=_derive_issue_category(feedback),
                description=feedback.text[:5000],
            )
        _feedback_store.set_triage(
            parsed_id, "action_required", decision_source="admin", needs_review=False
        )
    else:  # body.outcome == "no_action"
        # Retain feedback with no ticket link (Req 3.7).
        _feedback_store.set_triage(
            parsed_id, "no_action", decision_source="admin", needs_review=False
        )

    return _feedback_store.get(parsed_id)


# =============================================================================
# Feedback Detail & Listing Endpoints
# =============================================================================


@router.get("/feedback", response_model=list[Feedback])
async def list_feedback(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    admin: AdminUser = Depends(require_admin),
):
    """List feedback records for the admin dashboard (newest first).

    Each record includes ``feedback_id``, ``source_type``, ``sentiment``,
    ``enrichment_status``, ``triage_outcome`` and linked ``ticket_id``.

    Validates: Requirements 10.1, 11.4
    """
    return _feedback_store.list_for_admin(limit=limit, offset=offset)


@router.get("/feedback/{feedback_id}", response_model=Feedback)
async def get_feedback(
    feedback_id: str,
    admin: AdminUser = Depends(require_admin),
):
    """Return the full feedback record for ``feedback_id`` (404 if missing).

    Validates: Requirements 10.1, 11.4
    """
    try:
        parsed_id = uuid.UUID(feedback_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )

    feedback = _feedback_store.get(parsed_id)
    if feedback is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )

    return feedback


# =============================================================================
# Ticket Endpoints
# =============================================================================


@router.get("/tickets", response_model=list[TicketWithCount])
async def list_tickets(
    status_filter: str = Query(default="active", alias="status"),
    admin: AdminUser = Depends(require_admin),
):
    """List tickets with linked feedback counts, filtered by status.

    ``status`` accepts ``active`` (default: open + in_progress), ``resolved``,
    or ``all``. Returns tickets ordered by creation timestamp ascending. Each
    result carries ``linked_feedback_count``, the number of feedback records
    whose ``ticket_id`` points at the ticket.

    Validates: Requirements 10.4, 11.4
    """
    if status_filter == "all":
        return _ticketing_pipeline.list_with_counts(None)
    if status_filter == "resolved":
        return _ticketing_pipeline.list_with_counts(("resolved",))
    return _ticketing_pipeline.list_with_counts(("open", "in_progress"))


@router.get("/tickets/{ticket_id}", response_model=TicketDetail)
async def get_ticket_detail(
    ticket_id: str,
    admin: AdminUser = Depends(require_admin),
):
    """Return a single ticket with the ids of all linked feedback records.

    Backs the admin ticket detail view (ticket metadata + linked feedback +
    comments, which are fetched via the comment endpoints). Returns 404 for an
    invalid id format or an unknown ticket.

    Validates: Requirements 10.4, 11.4
    """
    try:
        uuid.UUID(ticket_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )

    detail = _ticketing_pipeline.get_with_feedback_ids(ticket_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )
    return detail


@router.patch("/tickets/{ticket_id}/advance", response_model=Ticket)
async def advance_ticket(ticket_id: str, admin: AdminUser = Depends(require_admin)):
    """Advance a ticket to the next valid status.

    Status transitions follow the sequence: open → in_progress → resolved. The
    new status is surfaced to customers via the feedback status view, so no
    extra work is needed here.

    Returns 409 Conflict if the ticket is not found or the transition is invalid
    (e.g., ticket is already resolved).

    Validates: Requirements 10.5, 11.4
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

    # Post a customer-visible system update reflecting the new status. These
    # comments surface in the customer's feedback status view (Req 7/8), so the
    # customer is automatically notified when work starts or the issue is fixed.
    _post_status_update_comment(ticket_id, updated_ticket.status)

    return updated_ticket


# Automatic status-change messages shown to the customer on their status page.
_STATUS_UPDATE_MESSAGES: dict[str, str] = {
    "in_progress": (
        "Good news — a support agent is now working on your ticket. "
        "We'll keep you posted here as we make progress."
    ),
    "resolved": (
        "Your ticket has been resolved. Thanks for your patience! "
        "If anything still isn't right, reply or submit new feedback and we'll take another look."
    ),
}

_SYSTEM_COMMENT_AUTHOR = "Spectrum Support"


def _post_status_update_comment(ticket_id: str, new_status: str) -> None:
    """Best-effort automatic comment when a ticket transitions status.

    Never raises: a failure to post the courtesy update must not fail the
    status transition itself.
    """
    message = _STATUS_UPDATE_MESSAGES.get(new_status)
    if not message:
        return
    try:
        _ticket_comment_store.add(
            ticket_id, author=_SYSTEM_COMMENT_AUTHOR, text=message
        )
    except Exception:  # pragma: no cover - defensive; courtesy update is non-critical
        pass


# =============================================================================
# Ticket Comment Endpoints
# =============================================================================


@router.post(
    "/tickets/{ticket_id}/comments",
    response_model=TicketComment,
    status_code=status.HTTP_201_CREATED,
)
async def create_ticket_comment(
    ticket_id: str,
    body: CommentCreate,
    admin: AdminUser = Depends(require_admin),
):
    """Create a customer-facing comment on a ticket, attributed to the team.

    Comments are surfaced to customers in their feedback status view, so the
    ``author`` is recorded as the team brand ("Spectrum Support") rather than
    the internal admin username. Empty/whitespace-only text is rejected with
    422 and an unknown ticket with 404.

    Validates: Requirements 7.1, 7.2, 7.3, 7.4, 11.4
    """
    try:
        # Comments are customer-facing, so they're attributed to the team brand
        # ("Spectrum Support") rather than the internal admin username.
        return _ticket_comment_store.add(
            ticket_id, author=_SYSTEM_COMMENT_AUTHOR, text=body.text
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )


@router.get("/tickets/{ticket_id}/comments", response_model=list[TicketComment])
async def list_ticket_comments(
    ticket_id: str,
    admin: AdminUser = Depends(require_admin),
):
    """List all comments for a ticket ordered by creation time ascending.

    Returns 404 if the ticket does not exist.

    Validates: Requirements 7.5, 7.4, 11.4
    """
    if _ticketing_pipeline.get_ticket(ticket_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )
    return _ticket_comment_store.list_for_ticket(ticket_id)


# =============================================================================
# Dashboard Endpoint
# =============================================================================


@router.get("/dashboard")
async def get_dashboard(admin: AdminUser = Depends(require_admin)):
    """Return admin dashboard aggregate counts over the unified feedback model.

    Reports the total number of feedback records plus counts grouped by NLP
    sentiment and by triage outcome. NULL sentiment is surfaced as ``unknown``
    and NULL triage outcome as ``unclassified`` (see ``FeedbackStore``).

    Validates: Requirements 10.3, 11.4
    """
    counts = _feedback_store.aggregate_counts()
    by_sentiment = counts["by_sentiment"]

    return {
        "total": sum(by_sentiment.values()),
        "by_sentiment": by_sentiment,
        "by_triage_outcome": counts["by_triage_outcome"],
    }


@router.get("/analytics")
async def get_analytics(admin: AdminUser = Depends(require_admin)):
    """Return rich analytics for the internal dashboard visuals.

    Aggregates feedback by department, source/platform, US state (with average
    severity), a 1-10 severity distribution, a daily time-series, and per-record
    map points for geographic clustering. Backs the charts and US map.
    """
    return _feedback_store.dashboard_analytics()


# =============================================================================
# Marketing Endpoint
# =============================================================================


@router.get("/marketing", response_model=PaginatedResponse)
async def get_marketing_log(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    admin: AdminUser = Depends(require_admin),
):
    """Surface positive-sentiment feedback for the marketing capability.

    Sourced from the unified ``feedback`` table: only records whose
    NLP-derived sentiment is ``"positive"`` are returned (Req 11.3), newest
    first and paginated. Each item exposes the fields useful for marketing
    (``feedback_id``, ``text``, ``created_at``, ``source_type``, ``platform``).

    Validates: Requirements 11.3, 11.4
    """
    feedback = _feedback_store.list_positive(limit=limit, offset=offset)
    total = _feedback_store.count_positive()

    items = [
        {
            "feedback_id": str(fb.feedback_id),
            "text": fb.text,
            "created_at": fb.created_at.isoformat(),
            "source_type": fb.source_type,
            "platform": fb.platform,
        }
        for fb in feedback
    ]

    return PaginatedResponse(
        items=items,
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

    # Aggregate over the unified feedback model for each window. Every feedback
    # record in a window contributes, including no_action feedback (Req 11.1,
    # 11.2).
    baseline_feedback = _feedback_store.list_in_window(
        request.baseline_window.start, request.baseline_window.end
    )
    current_feedback = _feedback_store.list_in_window(
        request.current_window.start, request.current_window.end
    )

    baseline = _aggregate_window(baseline_feedback)
    current = _aggregate_window(current_feedback)

    # theme_spikes: themes whose current count exceeds baseline count.
    theme_spikes = []
    for theme, cur_count in sorted(current["theme_counts"].items()):
        base_count = baseline["theme_counts"].get(theme, 0)
        if cur_count > base_count:
            theme_spikes.append(
                {"theme": theme, "baseline": base_count, "current": cur_count}
            )

    # sentiment_shifts: change in the share of each sentiment between windows.
    base_total = baseline["count"] or 0
    cur_total = current["count"] or 0
    all_sentiments = sorted(
        set(baseline["sentiment_counts"]) | set(current["sentiment_counts"])
    )
    sentiment_shifts = []
    for sentiment in all_sentiments:
        base_ratio = (
            baseline["sentiment_counts"].get(sentiment, 0) / base_total
            if base_total
            else 0.0
        )
        cur_ratio = (
            current["sentiment_counts"].get(sentiment, 0) / cur_total
            if cur_total
            else 0.0
        )
        sentiment_shifts.append(
            {
                "sentiment": sentiment,
                "baseline_ratio": base_ratio,
                "current_ratio": cur_ratio,
                "delta": cur_ratio - base_ratio,
            }
        )

    # severity_escalations: overall average severity increase across windows.
    severity_escalations = []
    if current["average_severity"] > baseline["average_severity"]:
        severity_escalations.append(
            {
                "scope": "overall",
                "baseline_severity": baseline["average_severity"],
                "current_severity": current["average_severity"],
                "delta": current["average_severity"] - baseline["average_severity"],
            }
        )

    # daily: per-day volume across both windows (for the sparkline), tagged by
    # which window each day belongs to so the frontend can shade the boundary.
    daily_map: dict[str, dict] = {}

    def _bucket(items: list[Feedback], key: str) -> None:
        for fb in items:
            day = fb.created_at.date().isoformat()
            entry = daily_map.setdefault(
                day, {"date": day, "baseline": 0, "current": 0, "total": 0}
            )
            entry[key] += 1
            entry["total"] += 1

    _bucket(baseline_feedback, "baseline")
    _bucket(current_feedback, "current")
    daily = [daily_map[d] for d in sorted(daily_map)]

    return {
        "baseline": baseline,
        "current": current,
        "theme_spikes": theme_spikes,
        "sentiment_shifts": sentiment_shifts,
        "severity_escalations": severity_escalations,
        "daily": daily,
    }
