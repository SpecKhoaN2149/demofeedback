"""Gemini_Client: the transport layer for the NLP feedback pipeline (task 8.3).

This is the *only* component that touches the network. It knows nothing about
themes, sentiment, or severity; it builds an authenticated, schema-constrained
request, applies a per-request timeout, retries retryable failures with bounded
exponential backoff, and returns either the raw response text or a typed
failure keyed by the originating record id (Req 2.1, 2.3, 2.5, 3.1-3.5, 4.1,
11.1).

Design notes / testability
---------------------------
Two seams keep the client fully testable without a network and without real
sleeps (required by property tests 8.4 / 8.5):

* ``sleep_fn`` -- the backoff sleep function (defaults to :func:`time.sleep`).
* ``transport`` -- the callable that actually performs one request attempt
  (defaults to a lazily-constructed ``google-genai`` SDK transport). Tests
  inject a fake that records attempts/payloads and raises chosen errors.

The backoff schedule is a pure function, :func:`backoff_delay`, so it can be
property-tested in isolation.

Secret hygiene (Req 2.6): the API key is registered with the shared
:class:`SecretRegistry`, a :class:`RedactingFilter` is attached to this
module's logger, and every failure message is passed through
:func:`redact_error` so the key can never reach logs or error strings.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Optional, Protocol

from .redaction import RedactingFilter, redact, redact_error, register_secret

logger = logging.getLogger(__name__)
# Ensure anything this logger emits is scrubbed of registered secrets.
logger.addFilter(RedactingFilter())

# Backoff is capped at 60 seconds per the design / Req 3.2.
MAX_BACKOFF_SECONDS = 60

# HTTP status codes the client reacts to specifically.
HTTP_TOO_MANY_REQUESTS = 429
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
_AUTH_STATUS_CODES = frozenset({HTTP_UNAUTHORIZED, HTTP_FORBIDDEN})


def backoff_delay(attempt: int) -> int:
    """Return the backoff delay, in seconds, for a 1-indexed ``attempt``.

    The schedule is ``min(60, 2**(attempt-1))`` (Req 3.1, 3.2): 1, 2, 4, 8, ...
    capped at 60. This is a pure function so the retry schedule can be verified
    independently of any timing or network behaviour.

    The delay *before* making attempt ``n`` (for ``n >= 2``) is
    ``backoff_delay(n)``; the first attempt is always made immediately.
    """
    if attempt < 1:
        raise ValueError("attempt must be a positive, 1-indexed integer")
    return min(MAX_BACKOFF_SECONDS, 2 ** (attempt - 1))


class ErrorCategory(Enum):
    """Classification of a transport exception for retry decision-making."""

    RETRYABLE = "retryable"  # 429, 5xx, network/connection failures (Req 3.1)
    AUTH = "auth"  # 401/403 -- never retried, fails the operation (Req 2.5)
    TIMEOUT = "timeout"  # request exceeded the timeout -- discard partial (Req 3.3)
    NON_RETRYABLE = "non_retryable"  # any other error -- fail without retry


class GeminiErrorKind(str, Enum):
    """The kind of failure carried by a :class:`GeminiResult`."""

    AUTH = "auth"  # authentication failure (Req 2.5)
    TIMEOUT = "timeout"  # request timed out, partial response discarded (Req 3.3)
    EXHAUSTED = "exhausted"  # retryable errors exhausted ``max_attempts`` (Req 3.4)
    ERROR = "error"  # a non-retryable, non-auth error


@dataclass(frozen=True)
class GeminiRequest:
    """A single schema-constrained enrichment request.

    The request carries everything the transport needs to issue an identical
    call on every retry attempt (Req 3.5): the originating ``record_id`` for
    error keying, the prompt ``contents``, an optional ``system_instruction``,
    and the ``response_schema`` plus ``response_mime_type`` used to instruct the
    API to return JSON matching the schema (Req 4.1, 11.1).
    """

    record_id: str
    contents: Any
    response_schema: Any = None
    response_mime_type: str = "application/json"
    system_instruction: Optional[str] = None


@dataclass(frozen=True)
class GeminiFailure:
    """A typed transport failure, keyed to the originating record."""

    record_id: str
    kind: GeminiErrorKind
    message: str
    attempts: int


@dataclass(frozen=True)
class GeminiResult:
    """The outcome of :meth:`GeminiClient.generate`.

    Exactly one of ``text`` (success) or ``failure`` is populated. Use
    :attr:`ok` to discriminate.
    """

    record_id: str
    attempts: int
    text: Optional[str] = None
    failure: Optional[GeminiFailure] = None

    @property
    def ok(self) -> bool:
        """True when the request succeeded and raw response text is available."""
        return self.failure is None

    def __post_init__(self) -> None:
        if (self.text is None) == (self.failure is None):
            raise ValueError(
                "GeminiResult must carry exactly one of text or failure"
            )


class Transport(Protocol):
    """One request attempt against the model.

    Implementations return the raw response text on success or raise an
    exception on failure. Raised exceptions are classified by
    :func:`classify_exception`; in particular a :class:`TimeoutError` (or an
    SDK timeout exception) signals a timeout, and an error exposing an integer
    HTTP ``code``/``status_code`` is classified by that status.
    """

    def __call__(self, request: GeminiRequest, timeout_s: int) -> str: ...


def _status_code_of(exc: BaseException) -> Optional[int]:
    """Best-effort extraction of an HTTP status code from an exception.

    Supports the ``google-genai`` ``APIError.code`` attribute and the common
    ``status_code`` convention without importing the SDK, keeping classification
    testable with lightweight fakes.
    """
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, bool):  # bool is an int subclass; ignore it.
            continue
        if isinstance(value, int):
            return value
    return None


def _looks_like_network_error(exc: BaseException) -> bool:
    """Heuristically detect a transient network/connection failure.

    Matches built-in connection errors and the httpx/requests transport error
    family by class-name suffix so the SDK need not be imported here.
    """
    if isinstance(exc, (ConnectionError, OSError)):
        return True
    name = type(exc).__name__
    network_markers = (
        "ConnectError",
        "ConnectionError",
        "ReadError",
        "WriteError",
        "NetworkError",
        "RemoteProtocolError",
        "ProtocolError",
        "ReadTimeout",  # treated as network-class transient by name only below
    )
    return any(marker in name for marker in network_markers)


def _looks_like_timeout(exc: BaseException) -> bool:
    """Detect a timeout exception across stdlib and httpx-style SDKs."""
    if isinstance(exc, TimeoutError):
        return True
    name = type(exc).__name__
    # httpx raises TimeoutException / ConnectTimeout / ReadTimeout / WriteTimeout.
    return "Timeout" in name


def classify_exception(exc: BaseException) -> ErrorCategory:
    """Classify ``exc`` into a retry category (Req 2.5, 3.1, 3.3).

    Precedence:
      1. Timeouts -> :attr:`ErrorCategory.TIMEOUT` (abort, discard partial).
      2. Auth (HTTP 401/403) -> :attr:`ErrorCategory.AUTH` (never retried).
      3. Rate-limit (429) and server errors (5xx) -> retryable.
      4. Network/connection failures -> retryable.
      5. Anything else -> non-retryable.
    """
    if _looks_like_timeout(exc):
        return ErrorCategory.TIMEOUT

    status = _status_code_of(exc)
    if status is not None:
        if status in _AUTH_STATUS_CODES:
            return ErrorCategory.AUTH
        if status == HTTP_TOO_MANY_REQUESTS:
            return ErrorCategory.RETRYABLE
        if 500 <= status <= 599:
            return ErrorCategory.RETRYABLE
        # Other 4xx (bad request, not found, ...) are not worth retrying.
        return ErrorCategory.NON_RETRYABLE

    if _looks_like_network_error(exc):
        return ErrorCategory.RETRYABLE

    return ErrorCategory.NON_RETRYABLE


class GeminiClient:
    """Authenticated, resilient transport to the Gemini API.

    Parameters
    ----------
    api_key, model_name:
        Credentials and model used on *every* request (Req 2.1, 2.3). The key is
        registered for redaction and never logged or surfaced in errors.
    max_attempts:
        Total attempts for retryable failures (Req 3.1, 3.2).
    timeout_s:
        Per-request timeout in seconds (Req 3.3).
    transport:
        Injectable single-attempt request function. Defaults to a lazily-built
        ``google-genai`` SDK transport. Tests pass a fake to avoid the network.
    sleep_fn:
        Injectable backoff sleep (defaults to :func:`time.sleep`) so tests run
        without real delays.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str,
        max_attempts: int = 5,
        timeout_s: int = 30,
        *,
        transport: Optional[Transport] = None,
        sleep_fn: Callable[[float], Any] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if timeout_s < 1:
            raise ValueError("timeout_s must be >= 1")

        self._api_key = api_key
        self.model_name = model_name
        self.max_attempts = max_attempts
        self.timeout_s = timeout_s
        self._sleep = sleep_fn
        # Register the key so any log line or error string is scrubbed (Req 2.6).
        register_secret(api_key)
        # Default to the real SDK transport, kept behind the injectable seam.
        self._transport: Transport = transport or _SdkTransport(api_key, model_name)

    def generate(self, request: GeminiRequest) -> GeminiResult:
        """Issue ``request`` with timeout and bounded retry/backoff.

        Returns a successful :class:`GeminiResult` carrying the raw response
        text, or a failed result carrying a typed :class:`GeminiFailure`:

        * auth error (401/403) -> fail immediately, no retry (Req 2.5);
        * timeout -> abort, discard any partial response (Req 3.3);
        * retryable error (429/5xx/network) -> exponential backoff up to
          ``max_attempts`` (Req 3.1, 3.2), resending identical content (Req 3.5);
        * retry exhaustion -> a failure result so the orchestrator can continue
          (Req 3.4).
        """
        last_message = "request failed"

        for attempt in range(1, self.max_attempts + 1):
            # Delay *before* attempts 2..n; the first attempt is immediate.
            if attempt > 1:
                self._sleep(backoff_delay(attempt))

            try:
                text = self._transport(request, self.timeout_s)
            except BaseException as exc:  # noqa: BLE001 -- classify, never leak
                category = classify_exception(exc)
                safe_message = redact_error(exc)

                if category is ErrorCategory.AUTH:
                    logger.error(
                        "Authentication failure for record %s: %s",
                        request.record_id,
                        safe_message,
                    )
                    return self._fail(
                        request, GeminiErrorKind.AUTH, safe_message, attempt
                    )

                if category is ErrorCategory.TIMEOUT:
                    logger.warning(
                        "Request for record %s timed out after %ss; "
                        "discarding partial response",
                        request.record_id,
                        self.timeout_s,
                    )
                    return self._fail(
                        request,
                        GeminiErrorKind.TIMEOUT,
                        f"request timed out after {self.timeout_s}s",
                        attempt,
                    )

                if category is ErrorCategory.NON_RETRYABLE:
                    logger.error(
                        "Non-retryable error for record %s: %s",
                        request.record_id,
                        safe_message,
                    )
                    return self._fail(
                        request, GeminiErrorKind.ERROR, safe_message, attempt
                    )

                # Retryable: log and loop (or exhaust below).
                last_message = safe_message
                logger.warning(
                    "Retryable error for record %s on attempt %d/%d: %s",
                    request.record_id,
                    attempt,
                    self.max_attempts,
                    safe_message,
                )
                continue

            # Success.
            return GeminiResult(
                record_id=request.record_id, attempts=attempt, text=text
            )

        # All attempts exhausted on retryable errors (Req 3.4).
        logger.error(
            "Exhausted %d attempts for record %s; last error: %s",
            self.max_attempts,
            request.record_id,
            last_message,
        )
        return self._fail(
            request,
            GeminiErrorKind.EXHAUSTED,
            f"exhausted {self.max_attempts} attempts: {last_message}",
            self.max_attempts,
        )

    @staticmethod
    def _fail(
        request: GeminiRequest,
        kind: GeminiErrorKind,
        message: str,
        attempts: int,
    ) -> GeminiResult:
        return GeminiResult(
            record_id=request.record_id,
            attempts=attempts,
            failure=GeminiFailure(
                record_id=request.record_id,
                kind=kind,
                # Defensive: scrub once more in case a caller-built message
                # ever carried a secret.
                message=redact(message),
                attempts=attempts,
            ),
        )


class _SdkTransport:
    """Default transport backed by the ``google-genai`` SDK.

    Kept behind the :class:`Transport` seam so the rest of the client (and its
    tests) never depend on the network. The SDK client is constructed lazily on
    first use so importing this module never requires the SDK or a live key.
    """

    def __init__(self, api_key: str, model_name: str) -> None:
        self._api_key = api_key
        self._model_name = model_name
        self._client: Any = None

    def _ensure_client(self) -> Any:
        if self._client is None:
            from google import genai  # local import: optional at module load

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def __call__(self, request: GeminiRequest, timeout_s: int) -> str:
        from google.genai import types

        client = self._ensure_client()

        config_kwargs: dict[str, Any] = {
            # Instruct the API to return JSON matching the schema (Req 4.1, 11.1).
            "response_mime_type": request.response_mime_type,
            # http_options.timeout is expressed in milliseconds (Req 3.3).
            "http_options": types.HttpOptions(timeout=timeout_s * 1000),
        }
        if request.response_schema is not None:
            # The enrichment response models declare ``extra="forbid"``, which
            # makes Pydantic emit ``additionalProperties: false`` (plus
            # ``$ref``/``$defs`` and ``title`` keys). The Gemini API's
            # ``response_schema`` does not accept those keywords and rejects the
            # request with HTTP 400. We keep the models strict for *parsing* the
            # response but send Gemini a sanitized, self-contained schema dict.
            config_kwargs["response_schema"] = _gemini_response_schema(
                request.response_schema
            )
        if request.system_instruction is not None:
            config_kwargs["system_instruction"] = request.system_instruction

        response = client.models.generate_content(
            model=self._model_name,  # configured model on every request (Req 2.3)
            contents=request.contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        return response.text


# Keys that Pydantic emits but the Gemini ``response_schema`` does not accept.
_UNSUPPORTED_SCHEMA_KEYS = frozenset(
    {"additionalProperties", "title", "$defs", "$schema", "definitions"}
)


def _gemini_response_schema(response_schema: Any) -> Any:
    """Return a Gemini-compatible schema for ``response_schema``.

    Accepts a pydantic ``BaseModel`` subclass (or anything exposing
    ``model_json_schema``) and returns a plain ``dict`` with all ``$ref``/
    ``$defs`` references inlined and every Gemini-unsupported keyword (e.g.
    ``additionalProperties``, ``title``) removed. Any other value (an existing
    dict or an SDK ``types.Schema``) is passed through unchanged.
    """
    to_schema = getattr(response_schema, "model_json_schema", None)
    if not callable(to_schema):
        return response_schema

    raw = to_schema()
    defs = raw.get("$defs") or raw.get("definitions") or {}
    return _sanitize_schema(raw, defs)


def _sanitize_schema(node: Any, defs: Mapping[str, Any]) -> Any:
    """Recursively inline ``$ref`` nodes and drop unsupported schema keywords."""
    if isinstance(node, list):
        return [_sanitize_schema(item, defs) for item in node]
    if not isinstance(node, dict):
        return node

    # Inline a ``$ref`` into the referenced definition before cleaning.
    ref = node.get("$ref")
    if isinstance(ref, str):
        target = _resolve_ref(ref, defs)
        if target is not None:
            merged = {k: v for k, v in node.items() if k != "$ref"}
            merged = {**target, **merged}
            return _sanitize_schema(merged, defs)

    cleaned: dict[str, Any] = {}
    for key, value in node.items():
        if key in _UNSUPPORTED_SCHEMA_KEYS:
            continue
        cleaned[key] = _sanitize_schema(value, defs)
    return cleaned


def _resolve_ref(ref: str, defs: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """Resolve a local ``#/$defs/Name`` (or ``#/definitions/Name``) reference."""
    name = ref.rsplit("/", 1)[-1]
    target = defs.get(name)
    return target if isinstance(target, dict) else None


__all__ = [
    "GeminiClient",
    "GeminiRequest",
    "GeminiResult",
    "GeminiFailure",
    "GeminiErrorKind",
    "ErrorCategory",
    "Transport",
    "backoff_delay",
    "classify_exception",
]
