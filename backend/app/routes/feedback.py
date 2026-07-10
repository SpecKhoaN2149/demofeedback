"""Public feedback API endpoints (unified feedback model).

Replaces the retired ``routes/submissions.py`` endpoints:

- ``POST /api/feedback`` — create a Feedback record from free-form text
  (no client-supplied sentiment) and enqueue NLP enrichment.
- ``GET /api/feedback/{feedback_id}/status`` — customer-facing status view.

Both endpoints are public (no auth), matching the design's API surface.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel

from app.models.feedback import FeedbackCreate, StatusView
from app.services.feedback_store import FeedbackStore

router = APIRouter()

_feedback_store = FeedbackStore()


class FeedbackResponse(BaseModel):
    """Response returned on successful feedback creation."""

    feedback_id: str
    message: str


async def _run_nlp_enrichment(feedback_id: str, text: str) -> None:
    """Background task for NLP enrichment on a feedback record.

    Delegates to the enrichment service, which invokes the NLP pipeline
    asynchronously (with the existing timeout / model-priority fallback) and
    updates the feedback record, then runs triage on the terminal status.
    """
    from app.services.enrichment import run_enrichment

    await run_enrichment(feedback_id, text)


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_feedback(
    body: FeedbackCreate,
    background_tasks: BackgroundTasks,
):
    """Create a new Feedback record from a single free-form message.

    Validation (Req 1.4, 1.5, 1.6) runs before any store write so a rejected
    submission never creates a row:

    - Pydantic ``min_length=1`` rejects an empty string with 422.
    - Pydantic ``max_length=10000`` rejects messages over the limit with 422.
    - Whitespace-only text passes ``min_length`` but is rejected here with a
      422 that identifies the ``text`` field.

    On success (Req 1.3, 1.7, 1.8, 2.1) the record is created with
    ``source_type="direct"`` / ``channel="web_form"``, NLP enrichment is
    enqueued as a background task, and the assigned ``feedback_id`` is returned.
    """
    # Whitespace-only guard (Pydantic min_length passes " ") — reject before
    # any store.create call so no row is created (Req 1.4, 1.6).
    if not body.text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[{"field": "text", "message": "Feedback message is required."}],
        )

    feedback = _feedback_store.create(
        FeedbackCreate(text=body.text, contact=body.contact),
        source_type="direct",
        channel="web_form",
    )

    feedback_id = str(feedback.feedback_id)

    # Enqueue NLP enrichment (Req 2.1). Enrichment invokes triage on completion.
    background_tasks.add_task(_run_nlp_enrichment, feedback_id, body.text)

    return FeedbackResponse(
        feedback_id=feedback_id,
        message="Feedback received.",
    )


@router.get("/feedback/{feedback_id}/status", response_model=StatusView)
async def get_feedback_status(feedback_id: str):
    """Return the customer-facing status view for a Feedback record.

    Covers enrichment status, triage outcome, linked ticket status, and the
    linked ticket's comments (Req 8.1, 8.2, 8.3, 9.1, 9.2, 9.4). An invalid or
    unknown ``feedback_id`` yields a 404 (Req 9.3). When the feedback is not
    linked to a ticket, ``ticket`` is null and ``comments`` is empty.
    """
    try:
        parsed_id = uuid.UUID(feedback_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )

    result = _feedback_store.get_status_view(parsed_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )

    return result
