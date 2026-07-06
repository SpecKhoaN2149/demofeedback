"""Pydantic v2 models for the ticketing pipeline."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class Ticket(BaseModel):
    """Support ticket for negative submissions."""

    id: UUID
    submission_id: UUID
    issue_category: str
    description: str = Field(max_length=5000)
    priority: Literal["high"] = "high"
    status: Literal["open", "in_progress", "resolved"]
    created_at: datetime
