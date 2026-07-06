"""Submission API endpoints for creating and retrieving customer submissions."""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel

from app.middleware.auth import require_admin
from app.models.auth import AdminUser
from app.models.submission import StatusResponse, Submission, SubmissionCreate
from app.services.admin_review_queue import AdminReviewQueue
from app.services.marketing_engine import MarketingEngine
from app.services.submission_store import SubmissionStore
from app.services.ticketing_pipeline import TicketingPipeline

router = APIRouter()

# Service instances
_submission_store = SubmissionStore()
_ticketing_pipeline = TicketingPipeline()
_marketing_engine = MarketingEngine()
_admin_review_queue = AdminReviewQueue()

# Valid issue categories for negative submissions
_VALID_CATEGORIES = {
    "billing",
    "network_speed",
    "outage",
    "support_experience",
    "device_hardware",
    "pricing",
}


class SubmissionResponse(BaseModel):
    """Response returned on successful submission creation."""

    submission_id: str
    progress_state: int
    message: str


def _validate_negative_fields(data: SubmissionCreate) -> list[dict]:
    """Validate fields specific to negative sentiment submissions."""
    errors = []
    if not data.issue_category:
        errors.append(
            {
                "field": "issue_category",
                "message": "Issue category is required for negative submissions.",
            }
        )
    elif data.issue_category not in _VALID_CATEGORIES:
        errors.append(
            {
                "field": "issue_category",
                "message": f"Invalid issue category. Must be one of: {', '.join(sorted(_VALID_CATEGORIES))}",
            }
        )

    if not data.detailed_description:
        errors.append(
            {
                "field": "detailed_description",
                "message": "Detailed description is required for negative submissions.",
            }
        )
    elif len(data.detailed_description) < 10:
        errors.append(
            {
                "field": "detailed_description",
                "message": "Detailed description must be at least 10 characters.",
            }
        )

    return errors


def _validate_positive_fields(data: SubmissionCreate) -> list[dict]:
    """Validate fields specific to positive sentiment submissions."""
    errors = []
    if not data.praise_text:
        errors.append(
            {
                "field": "praise_text",
                "message": "Praise text is required for positive submissions.",
            }
        )
    elif len(data.praise_text) > 2000:
        errors.append(
            {
                "field": "praise_text",
                "message": "Praise text must not exceed 2000 characters.",
            }
        )

    return errors


def _validate_neutral_fields(data: SubmissionCreate) -> list[dict]:
    """Validate fields specific to neutral sentiment submissions."""
    errors = []
    if not data.comment_text or not data.comment_text.strip():
        errors.append(
            {
                "field": "comment_text",
                "message": "Comment text with at least 1 non-whitespace character is required for neutral submissions.",
            }
        )

    return errors


async def _run_nlp_enrichment(submission_id: str, text: str) -> None:
    """Background task for NLP enrichment.

    Delegates to the enrichment service which invokes NLPProcessor
    asynchronously with a 30s timeout, extracts EnrichmentResult from
    the first InsightRecord, and updates the submission accordingly.

    Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5, 13.6
    """
    from app.services.enrichment import run_enrichment

    await run_enrichment(submission_id, text)


@router.post(
    "/submissions",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_submission(
    data: SubmissionCreate,
    background_tasks: BackgroundTasks,
):
    """Create a new customer submission.

    Routes the submission to the appropriate downstream service based on sentiment:
    - negative: TicketingPipeline creates a high-priority ticket
    - positive: MarketingEngine logs the praise
    - neutral: AdminReviewQueue enqueues for admin review

    Enqueues a background task for NLP enrichment on all submissions.
    """
    # Sentiment-specific field validation
    if data.sentiment == "negative":
        errors = _validate_negative_fields(data)
    elif data.sentiment == "positive":
        errors = _validate_positive_fields(data)
    else:  # neutral
        errors = _validate_neutral_fields(data)

    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=errors,
        )

    # Create the submission in the store
    try:
        submission = _submission_store.create(data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create submission. Please try again.",
        ) from e

    submission_id = str(submission.id)

    # Route to sentiment-specific service
    try:
        if data.sentiment == "negative":
            _ticketing_pipeline.create_ticket(
                submission_id=submission_id,
                category=data.issue_category,  # type: ignore[arg-type]
                description=data.detailed_description,  # type: ignore[arg-type]
            )
        elif data.sentiment == "positive":
            _marketing_engine.log_praise(
                submission_id=submission_id,
                customer_name=data.customer_name,
                praise_text=data.praise_text,  # type: ignore[arg-type]
                social_sharing=data.social_sharing,
            )
        else:  # neutral
            _admin_review_queue.enqueue(submission_id=submission_id)
    except Exception as e:
        # For negative: ticket creation failure is critical per requirement 3.8
        # For positive: marketing failure is non-critical per requirement 4.8
        # For neutral: queue failure is critical per requirement 5.8
        if data.sentiment == "positive":
            # Non-critical: proceed with a warning (requirement 4.8)
            pass
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to process submission. Please try again.",
            ) from e

    # Enqueue background NLP enrichment (requirements 3.5, 4.6, 5.5)
    enrichment_text = data.core_request
    if data.sentiment == "negative" and data.detailed_description:
        enrichment_text = f"{data.core_request}\n{data.detailed_description}"
    elif data.sentiment == "positive" and data.praise_text:
        enrichment_text = f"{data.core_request}\n{data.praise_text}"
    elif data.sentiment == "neutral" and data.comment_text:
        enrichment_text = f"{data.core_request}\n{data.comment_text}"

    background_tasks.add_task(_run_nlp_enrichment, submission_id, enrichment_text)

    # Build response message
    messages = {
        "negative": "Submission received. A support ticket has been created.",
        "positive": "Thank you for your praise! Feedback noted.",
        "neutral": "Submission received. Your comment is awaiting review.",
    }

    return SubmissionResponse(
        submission_id=submission_id,
        progress_state=submission.progress_state,
        message=messages[data.sentiment],
    )


@router.get("/submissions/{submission_id}/status", response_model=StatusResponse)
async def get_submission_status(submission_id: str):
    """Poll the current status of a submission.

    Returns progress state, sentiment, message, and enrichment status.
    """
    # Validate UUID format
    try:
        parsed_id = uuid.UUID(submission_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    # Retrieve status from store
    result = _submission_store.get_status(parsed_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    return result


@router.get("/submissions/{submission_id}", response_model=Submission)
async def get_submission(submission_id: str, admin: AdminUser = Depends(require_admin)):
    """Retrieve the full submission record (admin-only).

    Returns the complete Submission model including state transitions
    and enrichment result.

    Validates: Requirements 14.4
    """
    # Validate UUID format
    try:
        parsed_id = uuid.UUID(submission_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    # Retrieve submission from store
    result = _submission_store.get(parsed_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    return result
