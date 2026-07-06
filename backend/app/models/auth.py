"""Pydantic v2 models for admin authentication."""

from datetime import datetime

from pydantic import BaseModel


class SessionToken(BaseModel):
    """Issued on successful login."""

    token: str
    expires_at: datetime
    username: str


class AdminUser(BaseModel):
    """Decoded session identity."""

    username: str
    token: str
