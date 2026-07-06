"""Secret redaction utilities for the transport layer.

The guiding principle from the design is to *never leak secrets*: the
configured API key (and any other registered secret value) must never appear in
log output or in reported error messages (Req 2.6, Property 4).

This module provides three pieces of public API:

* :class:`SecretRegistry` -- a registry of secret strings to redact. The
  ``GeminiClient`` registers its ``api_key`` here so every log line and error
  message routed through these helpers is scrubbed.
* :class:`RedactingFilter` -- a :class:`logging.Filter` that redacts registered
  secrets from a log record's message and arguments before it is emitted.
* :func:`redact` / :func:`redact_error` -- helpers that scrub secrets from an
  arbitrary string or from an exception/error message.

Empty or ``None`` secrets are ignored so that registering an unset key never
causes the empty string to be "redacted" out of every message.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

# The text substituted in place of a secret value.
REDACTION_PLACEHOLDER = "[REDACTED]"


class SecretRegistry:
    """A mutable set of secret values that should be redacted from strings.

    The registry is intentionally simple: secrets are stored as a set of
    non-empty strings. Registering ``None``, ``""``, or a whitespace-only value
    is a no-op so that an unset API key never turns into a redaction of the
    empty string (which would otherwise corrupt every message).
    """

    def __init__(self, secrets: Optional[Iterable[str]] = None) -> None:
        self._secrets: set[str] = set()
        if secrets is not None:
            for secret in secrets:
                self.register(secret)

    def register(self, secret: Optional[str]) -> None:
        """Register ``secret`` for redaction.

        ``None`` and empty/whitespace-only values are ignored.
        """
        if self._is_redactable(secret):
            self._secrets.add(secret)  # type: ignore[arg-type]

    def unregister(self, secret: Optional[str]) -> None:
        """Remove ``secret`` from the registry if present (no error if absent)."""
        if secret:
            self._secrets.discard(secret)

    def clear(self) -> None:
        """Remove all registered secrets."""
        self._secrets.clear()

    @property
    def secrets(self) -> frozenset[str]:
        """An immutable snapshot of the currently registered secrets."""
        return frozenset(self._secrets)

    def redact(self, text: object) -> str:
        """Return ``str(text)`` with every registered secret replaced.

        Longer secrets are replaced first so that a secret which is a substring
        of another secret cannot leave a fragment behind.
        """
        result = text if isinstance(text, str) else str(text)
        # Replace longest secrets first to avoid partial-overlap leakage.
        for secret in sorted(self._secrets, key=len, reverse=True):
            if secret in result:
                result = result.replace(secret, REDACTION_PLACEHOLDER)
        return result

    @staticmethod
    def _is_redactable(secret: Optional[str]) -> bool:
        return isinstance(secret, str) and secret.strip() != ""


# A process-wide default registry. The ``GeminiClient`` registers its API key
# here, and the module-level :func:`redact` / :func:`redact_error` helpers and
# :class:`RedactingFilter` use it by default.
_default_registry = SecretRegistry()


def get_default_registry() -> SecretRegistry:
    """Return the shared process-wide :class:`SecretRegistry`."""
    return _default_registry


def register_secret(secret: Optional[str]) -> None:
    """Register ``secret`` with the shared default registry.

    Convenience wrapper used by the transport client to register its API key.
    """
    _default_registry.register(secret)


def redact(text: object, registry: Optional[SecretRegistry] = None) -> str:
    """Redact registered secrets from ``text``.

    Uses the shared default registry unless an explicit ``registry`` is given.
    """
    return (registry or _default_registry).redact(text)


def redact_error(
    error: BaseException, registry: Optional[SecretRegistry] = None
) -> str:
    """Return a redacted string representation of ``error``.

    The message is built from the exception type and its ``str()`` form, then
    scrubbed of any registered secret so error messages never leak the API key.
    """
    reg = registry or _default_registry
    message = str(error)
    rendered = f"{type(error).__name__}: {message}" if message else type(error).__name__
    return reg.redact(rendered)


class RedactingFilter(logging.Filter):
    """A logging filter that redacts registered secrets from log records.

    Attach this filter to any handler or logger that might emit a string
    containing the API key. It rewrites ``record.msg`` and ``record.args`` (the
    pre-formatting components) so the secret is gone regardless of how the
    record is later formatted.
    """

    def __init__(
        self, registry: Optional[SecretRegistry] = None, name: str = ""
    ) -> None:
        super().__init__(name)
        self._registry = registry or _default_registry

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact the message template itself.
        if isinstance(record.msg, str):
            record.msg = self._registry.redact(record.msg)
        elif record.msg is not None:
            record.msg = self._registry.redact(record.msg)

        # Redact positional formatting arguments.
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: self._redact_arg(value)
                    for key, value in record.args.items()
                }
            else:
                record.args = tuple(
                    self._redact_arg(value) for value in record.args
                )

        return True

    def _redact_arg(self, value: object) -> object:
        # Only string-like args can carry a secret; leave others untouched so
        # numeric format specifiers (e.g. %d) keep working.
        if isinstance(value, str):
            return self._registry.redact(value)
        return value


__all__ = [
    "REDACTION_PLACEHOLDER",
    "SecretRegistry",
    "RedactingFilter",
    "get_default_registry",
    "register_secret",
    "redact",
    "redact_error",
]
