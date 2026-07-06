"""Authentication middleware for admin-only endpoints.

Provides FastAPI dependencies for extracting and validating session tokens,
and injecting AuthService instances.

Validates: Requirements 9.1, 9.5
"""

from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request

from app.models.auth import AdminUser
from app.services.auth_service import AuthService


def get_auth_service() -> AuthService:
    """Dependency that provides an AuthService instance.

    Usage:
        auth: AuthService = Depends(get_auth_service)
    """
    return AuthService()


def _extract_token(request: Request, session_token: Optional[str] = Cookie(default=None)) -> Optional[str]:
    """Extract session token from Authorization header or session_token cookie.

    Priority:
    1. Authorization: Bearer <token> header
    2. session_token cookie (fallback)

    Returns:
        The token string if found, None otherwise.
    """
    # Try Authorization header first
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
        if token:
            return token

    # Fallback to cookie
    if session_token:
        return session_token

    return None


async def require_admin(
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    auth_service: AuthService = Depends(get_auth_service),
) -> AdminUser:
    """FastAPI dependency that enforces admin authentication.

    Extracts the session token from the Authorization header (Bearer scheme)
    or the session_token cookie, then validates it via AuthService.

    Returns:
        AdminUser on successful validation.

    Raises:
        HTTPException(401): If no token is present, or the token is expired/invalidated/unknown.

    Usage:
        @router.get("/api/admin/queue")
        async def list_queue(admin: AdminUser = Depends(require_admin)):
            ...
    """
    token = _extract_token(request, session_token)

    if token is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    admin_user = auth_service.validate_token(token)

    if admin_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    return admin_user
