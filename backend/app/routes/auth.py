"""Authentication routes for the admin panel.

Provides login and logout endpoints for session-based authentication.

Validates: Requirements 9.2, 9.3, 9.4
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app.middleware.auth import get_auth_service, require_admin
from app.models.auth import AdminUser, SessionToken
from app.services.auth_service import AuthService

router = APIRouter()


class LoginRequest(BaseModel):
    """Request body for POST /login."""

    username: str
    password: str


class LogoutResponse(BaseModel):
    """Response body for POST /logout."""

    detail: str


@router.post("/login", response_model=SessionToken)
async def login(
    body: LoginRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> SessionToken:
    """Authenticate admin user and issue a session token.

    Returns a SessionToken on success. Sets session_token cookie for
    browser-based clients.

    Returns 401 for any authentication failure (wrong username, wrong
    password, or locked account) with the same generic message to avoid
    leaking information about valid usernames.

    Validates: Requirements 9.2, 9.3, 9.6
    """
    # Check lockout first
    if auth_service.is_locked(body.username):
        raise HTTPException(status_code=401, detail="Authentication failed")

    # Attempt login
    session = auth_service.login(body.username, body.password)

    if session is None:
        raise HTTPException(status_code=401, detail="Authentication failed")

    # Set cookie for browser-based clients
    response.set_cookie(
        key="session_token",
        value=session.token,
        httponly=True,
        samesite="lax",
        expires=int(session.expires_at.timestamp()),
    )

    return session


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    admin: AdminUser = Depends(require_admin),
    auth_service: AuthService = Depends(get_auth_service),
) -> LogoutResponse:
    """Invalidate the current session token.

    Requires a valid session token (via header or cookie). Invalidates
    the token so it can no longer be used for authentication.

    Validates: Requirements 9.4
    """
    auth_service.logout(admin.token)
    return LogoutResponse(detail="Logged out successfully")
