"""Pydantic v2 models for the marketing engine."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class MarketingEntry(BaseModel):
    """Marketing log entry for positive submissions."""

    submission_id: UUID
    customer_name: str
    praise_text: str
    social_sharing: bool
    social_status: Literal["shared", "internal_only", "generation_failed"]
    shareable_url: str | None = None
    logged_at: datetime


class ShareResult(BaseModel):
    """Output of social share generation."""

    shareable_url: str
    email_template: str
