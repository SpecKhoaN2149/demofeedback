"""Authentication service for admin panel access.

Provides login/logout, session token management, account lockout,
and admin user creation utilities.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.database import get_connection
from app.models.auth import AdminUser, SessionToken


class AuthService:
    """Handles admin authentication, session tokens, and account lockout."""

    # Lockout configuration
    MAX_FAILED_ATTEMPTS: int = 5
    LOCKOUT_DURATION_SECONDS: int = 60
    SESSION_EXPIRY_HOURS: int = 8

    def login(self, username: str, password: str) -> Optional[SessionToken]:
        """Authenticate admin user and issue a session token.

        Flow:
        1. Check if username exists in admin_users
        2. Check if account is locked
        3. Verify password hash
        4. On mismatch: record failure, return None
        5. On match: clear failures, create session, return SessionToken

        Args:
            username: The admin username.
            password: The plaintext password to verify.

        Returns:
            SessionToken on success, None on failure.
        """
        with get_connection() as conn:
            row = conn.execute(
                "SELECT username, password_hash FROM admin_users WHERE username = ?",
                (username,),
            ).fetchone()

            if row is None:
                return None

            if self.is_locked(username):
                return None

            password_hash = hashlib.sha256(password.encode()).hexdigest()
            if row["password_hash"] != password_hash:
                self.record_failure(username)
                return None

            # Successful login
            self.clear_failures(username)

            # Generate session token
            token = secrets.token_urlsafe(32)
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(hours=self.SESSION_EXPIRY_HOURS)

            conn.execute(
                "INSERT INTO sessions (token, username, created_at, expires_at, invalidated) "
                "VALUES (?, ?, ?, ?, 0)",
                (
                    token,
                    username,
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
            conn.commit()

            return SessionToken(
                token=token,
                expires_at=expires_at,
                username=username,
            )

    def logout(self, token: str) -> None:
        """Invalidate a session token.

        Args:
            token: The session token to invalidate.
        """
        with get_connection() as conn:
            conn.execute(
                "UPDATE sessions SET invalidated = 1 WHERE token = ?",
                (token,),
            )
            conn.commit()

    def validate_token(self, token: str) -> Optional[AdminUser]:
        """Validate a session token and return the associated admin user.

        Checks that the token exists, is not invalidated, and has not expired.

        Args:
            token: The session token to validate.

        Returns:
            AdminUser if valid, None otherwise.
        """
        now = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT username, token FROM sessions "
                "WHERE token = ? AND invalidated = 0 AND expires_at > ?",
                (token, now),
            ).fetchone()

            if row is None:
                return None

            return AdminUser(username=row["username"], token=row["token"])

    def is_locked(self, username: str) -> bool:
        """Check if an account is locked due to excessive failed attempts.

        An account is locked if failed_attempts >= 5 AND locked_until > now.

        Args:
            username: The username to check.

        Returns:
            True if locked, False otherwise.
        """
        with get_connection() as conn:
            row = conn.execute(
                "SELECT failed_attempts, locked_until FROM admin_users WHERE username = ?",
                (username,),
            ).fetchone()

            if row is None:
                return False

            failed_attempts = row["failed_attempts"]
            locked_until = row["locked_until"]

            if failed_attempts >= self.MAX_FAILED_ATTEMPTS and locked_until is not None:
                now = datetime.now(timezone.utc)
                lock_expiry = datetime.fromisoformat(locked_until)
                # Ensure lock_expiry is timezone-aware
                if lock_expiry.tzinfo is None:
                    lock_expiry = lock_expiry.replace(tzinfo=timezone.utc)
                return lock_expiry > now

            return False

    def record_failure(self, username: str) -> None:
        """Record a failed login attempt and lock if threshold reached.

        Increments failed_attempts. If the count reaches MAX_FAILED_ATTEMPTS,
        sets locked_until to now + LOCKOUT_DURATION_SECONDS.

        Args:
            username: The username that failed authentication.
        """
        with get_connection() as conn:
            conn.execute(
                "UPDATE admin_users SET failed_attempts = failed_attempts + 1 "
                "WHERE username = ?",
                (username,),
            )
            conn.commit()

            # Check if we need to set lockout
            row = conn.execute(
                "SELECT failed_attempts FROM admin_users WHERE username = ?",
                (username,),
            ).fetchone()

            if row and row["failed_attempts"] >= self.MAX_FAILED_ATTEMPTS:
                locked_until = datetime.now(timezone.utc) + timedelta(
                    seconds=self.LOCKOUT_DURATION_SECONDS
                )
                conn.execute(
                    "UPDATE admin_users SET locked_until = ? WHERE username = ?",
                    (locked_until.isoformat(), username),
                )
                conn.commit()

    def clear_failures(self, username: str) -> None:
        """Reset failed attempts on successful login.

        Args:
            username: The username to clear.
        """
        with get_connection() as conn:
            conn.execute(
                "UPDATE admin_users SET failed_attempts = 0, locked_until = NULL "
                "WHERE username = ?",
                (username,),
            )
            conn.commit()

    def create_admin(self, username: str, password: str) -> None:
        """Create an admin user for seeding purposes.

        Args:
            username: The admin username.
            password: The plaintext password (will be hashed with SHA-256).
        """
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO admin_users (username, password_hash, failed_attempts, locked_until) "
                "VALUES (?, ?, 0, NULL)",
                (username, password_hash),
            )
            conn.commit()
