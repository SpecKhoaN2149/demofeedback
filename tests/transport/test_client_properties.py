"""Property-based tests for the Gemini_Client transport layer.

Covers three correctness properties from the design (each implemented as a
single Hypothesis property test, minimum 100 iterations):

* Property 4: API key never leaks (Req 2.6)
* Property 5: Retry backoff schedule is correct for retryable errors (Req 3.1, 3.2)
* Property 6: Retries resend identical content (Req 3.5)

All tests inject fakes (transport / sleep_fn) so they run without a network and
without real delays. The shared default :class:`SecretRegistry` is cleaned up
after each example so these tests never pollute the process-wide registry.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from hypothesis import given, settings
from hypothesis import strategies as st

from nlp_processing.transport.client import (
    GeminiClient,
    GeminiRequest,
    backoff_delay,
)
from nlp_processing.transport.redaction import get_default_registry

CLIENT_LOGGER_NAME = "nlp_processing.transport.client"


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# API-key-like strings: alphanumeric + a few key punctuation characters, long
# enough that they are redactable and won't be an accidental substring of
# unrelated text. Keys never contain whitespace.
_KEY_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789-_"
)


def api_key_like() -> st.SearchStrategy[str]:
    """Realistic, non-trivial API-key-like strings (no whitespace)."""
    body = st.text(alphabet=_KEY_ALPHABET, min_size=12, max_size=40)
    return body.map(lambda s: "AIza" + s)


def json_like_contents() -> st.SearchStrategy[Any]:
    """Simple JSON-like request payloads to use as ``contents``."""
    scalars = st.one_of(
        st.text(max_size=30),
        st.integers(),
        st.booleans(),
    )
    return st.recursive(
        scalars,
        lambda children: st.one_of(
            st.lists(children, max_size=4),
            st.dictionaries(st.text(max_size=8), children, max_size=4),
        ),
        max_leaves=6,
    )


# A retryable error category: rate-limit (429), transient server (5xx), or a
# network/connection failure. ``classify_exception`` treats all of these as
# retryable (Req 3.1).
class _CodedError(Exception):
    """An exception carrying an HTTP-like ``code`` attribute."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def retryable_error_factory() -> st.SearchStrategy[Any]:
    """A callable that produces a fresh retryable exception when invoked."""
    coded = st.sampled_from([429, 500, 502, 503, 504]).map(
        lambda code: (lambda: _CodedError("transient failure", code))
    )
    network = st.just(lambda: ConnectionError("connection reset"))
    return st.one_of(coded, network)


# ---------------------------------------------------------------------------
# Log-capture helper
# ---------------------------------------------------------------------------


@contextmanager
def _capture_client_logs() -> Iterator[list[str]]:
    """Capture formatted log output from the transport client's logger.

    The client logger already carries a ``RedactingFilter`` applied at the
    logger level (before handlers run), so captured messages reflect exactly
    what would reach any real handler.
    """
    logger = logging.getLogger(CLIENT_LOGGER_NAME)
    messages: list[str] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(record.getMessage())

    handler = _Collector(level=logging.DEBUG)
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield messages
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


# ===========================================================================
# Property 4: API key never leaks (Req 2.6)
# ===========================================================================
# Feature: nlp-feedback-processing, Property 4: For any operation - including
# failing and error-producing ones - the configured API key value never
# appears in captured log output or in any reported error message.
@settings(max_examples=200, deadline=None)
@given(
    api_key=api_key_like(),
    suffix=st.text(alphabet=_KEY_ALPHABET, min_size=4, max_size=20),
    code=st.sampled_from([400, 401, 403, 404, 429, 500, 503]),
    use_timeout=st.booleans(),
    max_attempts=st.integers(min_value=1, max_value=4),
)
def test_property_4_api_key_never_leaks(
    api_key, suffix, code, use_timeout, max_attempts
):
    """Validates: Requirements 2.6"""
    registry = get_default_registry()
    # Distinct key per example so a stale registration can never mask a leak.
    api_key = f"{api_key}{suffix}"

    # Build an error whose message embeds the secret key, across every fault
    # category (auth, timeout, retryable, non-retryable).
    leaky_message = f"upstream rejected request with key={api_key} (do not log)"

    def transport(request: GeminiRequest, timeout_s: int) -> str:
        if use_timeout:
            raise TimeoutError(leaky_message)
        raise _CodedError(leaky_message, code)

    sleeps: list[float] = []

    try:
        client = GeminiClient(
            api_key=api_key,
            model_name="gemini-1.5-flash",
            max_attempts=max_attempts,
            timeout_s=5,
            transport=transport,
            sleep_fn=sleeps.append,
        )

        with _capture_client_logs() as log_messages:
            result = client.generate(
                GeminiRequest(record_id="rec-1", contents="hello")
            )

        # The operation must fail (we always raise), and nothing it produces or
        # logs may contain the secret key.
        assert not result.ok
        assert result.failure is not None
        assert api_key not in result.failure.message
        for message in log_messages:
            assert api_key not in message
    finally:
        # Clean up the shared default registry to avoid cross-test pollution.
        registry.unregister(api_key)


# ===========================================================================
# Property 5: Retry backoff schedule is correct for retryable errors
# (Req 3.1, 3.2)
# ===========================================================================
# Feature: nlp-feedback-processing, Property 5: For any retryable error
# category (rate-limit, transient server error, network failure) and any
# configured max_attempts in 1..10, the client makes exactly max_attempts
# attempts and the delay before attempt n equals min(60, 2**(n-1)) seconds.
@settings(max_examples=200, deadline=None)
@given(
    make_error=retryable_error_factory(),
    max_attempts=st.integers(min_value=1, max_value=10),
)
def test_property_5_retry_backoff_schedule(make_error, max_attempts):
    """Validates: Requirements 3.1, 3.2"""
    api_key = "AIza-prop5-key-value"
    registry = get_default_registry()

    attempts: list[int] = []
    sleeps: list[float] = []

    def transport(request: GeminiRequest, timeout_s: int) -> str:
        attempts.append(1)
        raise make_error()

    try:
        client = GeminiClient(
            api_key=api_key,
            model_name="gemini-1.5-flash",
            max_attempts=max_attempts,
            timeout_s=5,
            transport=transport,
            sleep_fn=sleeps.append,
        )
        result = client.generate(
            GeminiRequest(record_id="rec-5", contents="payload")
        )

        # Exactly max_attempts attempts were made (Req 3.1).
        assert len(attempts) == max_attempts
        assert result.attempts == max_attempts

        # The first attempt is immediate; the delay before attempt n (n >= 2)
        # is min(60, 2**(n-1)) (Req 3.2).
        expected_delays = [backoff_delay(n) for n in range(2, max_attempts + 1)]
        assert sleeps == expected_delays
        # Cross-check the cap and doubling schedule explicitly.
        for n, delay in enumerate(sleeps, start=2):
            assert delay == min(60, 2 ** (n - 1))
    finally:
        registry.unregister(api_key)


# ===========================================================================
# Property 6: Retries resend identical content (Req 3.5)
# ===========================================================================
# Feature: nlp-feedback-processing, Property 6: For any request that is
# retried, every retry attempt sends content byte-for-byte identical to the
# original request.
@settings(max_examples=200, deadline=None)
@given(
    record_id=st.text(alphabet=_KEY_ALPHABET, min_size=1, max_size=20),
    contents=json_like_contents(),
    schema=st.one_of(st.none(), st.dictionaries(st.text(max_size=6), st.text(max_size=6), max_size=3)),
    system_instruction=st.one_of(st.none(), st.text(max_size=40)),
    max_attempts=st.integers(min_value=2, max_value=6),
)
def test_property_6_retries_resend_identical_content(
    record_id, contents, schema, system_instruction, max_attempts
):
    """Validates: Requirements 3.5"""
    api_key = "AIza-prop6-key-value"
    registry = get_default_registry()

    original = GeminiRequest(
        record_id=record_id,
        contents=contents,
        response_schema=schema,
        system_instruction=system_instruction,
    )

    # Snapshot the field tuple of each attempt's request so we compare the
    # actual content sent, not just object identity.
    def snapshot(req: GeminiRequest) -> tuple:
        return (
            req.record_id,
            repr(req.contents),
            repr(req.response_schema),
            req.response_mime_type,
            req.system_instruction,
        )

    sent: list[tuple] = []

    def transport(request: GeminiRequest, timeout_s: int) -> str:
        sent.append(snapshot(request))
        # Always retryable so every attempt is exercised.
        raise _CodedError("temporary", 503)

    try:
        client = GeminiClient(
            api_key=api_key,
            model_name="gemini-1.5-flash",
            max_attempts=max_attempts,
            timeout_s=5,
            transport=transport,
            sleep_fn=lambda _delay: None,
        )
        client.generate(original)

        # Every attempt (including the first) sent identical content.
        assert len(sent) == max_attempts
        baseline = snapshot(original)
        assert all(entry == baseline for entry in sent)
    finally:
        registry.unregister(api_key)
