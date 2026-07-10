"""Pydantic v2 models for the ticketing pipeline.

Tickets are independent entities in the feedback-triage overhaul: a ticket has
no `submission_id`. The many-to-one link lives on the feedback side
(`feedback.ticket_id`), so a single ticket may have zero or more linked
feedback records.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class Ticket(BaseModel):
    """Independent support ticket (no direct submission/feedback FK)."""

    ticket_id: UUID
    issue_category: str
    description: str = Field(max_length=5000)
    priority: Literal["high"] = "high"
    status: Literal["open", "in_progress", "resolved"]
    created_at: datetime


class TicketWithCount(Ticket):
    """Ticket enriched with the number of feedback records linked to it."""

    linked_feedback_count: int


class TicketDetail(Ticket):
    """Ticket enriched with the ids of all linked feedback records."""

    feedback_ids: list[UUID]
