"""Example-based unit tests for Gemini_Client transport wiring and fault paths.

Covers (task 8.6):

* API key attached as the auth credential and the configured model used on
  every request (Req 2.1, 2.3).
* The request instructs the API to return JSON matching the response schema
  (Req 4.1, 11.1).
* Auth errors (401/403) are not retried; the operation fails (Req 2.5).
* Timeouts abort the request, discard any partial response, and produce a
  timeout failure keyed by the originating record id (Req 3.3).

These are example-based tests (not property tests). The SDK is exercised via
its injectable seam / a fake genai client so nothing touches the network.
"""

from __future__ import annotations

import pytest

from nlp_processing.transport import client as client_module
from nlp_processing.transport.client import (
    GeminiClient,
    GeminiErrorKind,
    GeminiRequest,
    _SdkTransport,
)
from nlp_processing.transport.redaction import get_default_registry


@pytest.fixture(autouse=True)
def _clean_registry():
    """Keep the shared default secret registry clean across these tests."""
    yield
    get_default_registry().clear()


# ---------------------------------------------------------------------------
# Fakes for the google-genai SDK
# ---------------------------------------------------------------------------


class _FakeModels:
    def __init__(self, recorder: dict) -> None:
        self._recorder = recorder

    def generate_content(self, *, model, contents, config):
        self._recorder["model"] = model
        self._recorder["contents"] = contents
        self._recorder["config"] = config

        class _Resp:
            text = "raw-response-text"

        return _Resp()


class _FakeGenaiClient:
    def __init__(self, recorder: dict) -> None:
        self.models = _FakeModels(recorder)


# ===========================================================================
# Req 2.3 / 4.1 / 11.1 -- configured model + response-schema instruction
# ===========================================================================
def test_sdk_transport_uses_configured_model_and_response_schema():
    """The SDK transport sends the configured model and schema instruction.

    Req 2.3 (configured model on every request), Req 4.1 / 11.1 (instruct the
    API to return JSON matching the response schema).
    """
    recorder: dict = {}
    transport = _SdkTransport(api_key="AIza-secret", model_name="gemini-1.5-pro")
    # Bypass real SDK client construction by injecting a fake.
    transport._client = _FakeGenaiClient(recorder)

    schema = {"type": "object", "properties": {"theme": {"type": "string"}}}
    request = GeminiRequest(
        record_id="rec-7",
        contents="classify this feedback",
        response_schema=schema,
        system_instruction="You are a classifier.",
    )

    text = transport(request, timeout_s=12)

    assert text == "raw-response-text"
    # Configured model used on the request (Req 2.3).
    assert recorder["model"] == "gemini-1.5-pro"
    assert recorder["contents"] == "classify this feedback"
    config = recorder["config"]
    # Response-schema instruction present (Req 4.1, 11.1).
    assert config.response_mime_type == "application/json"
    assert config.response_schema == schema
    assert config.system_instruction == "You are a classifier."
    # Per-request timeout expressed in milliseconds (Req 3.3).
    assert config.http_options.timeout == 12_000


def test_sdk_transport_attaches_api_key_as_credential(monkeypatch):
    """The API key is passed as the auth credential when building the client.

    Req 2.1: attach the API key as the auth credential.
    """
    captured: dict = {}

    class _FakeGenaiModule:
        @staticmethod
        def Client(*, api_key):
            captured["api_key"] = api_key
            return _FakeGenaiClient({})

    # _ensure_client does `from google import genai`; patch that symbol.
    import google

    monkeypatch.setattr(google, "genai", _FakeGenaiModule, raising=False)

    transport = _SdkTransport(api_key="AIza-the-key", model_name="gemini-1.5-flash")
    transport._ensure_client()

    assert captured["api_key"] == "AIza-the-key"


def test_sdk_transport_omits_schema_when_not_provided():
    """When no response_schema is given, the SDK call omits it cleanly."""
    recorder: dict = {}
    transport = _SdkTransport(api_key="AIza-secret", model_name="gemini-1.5-flash")
    transport._client = _FakeGenaiClient(recorder)

    transport(GeminiRequest(record_id="rec-8", contents="hi"), timeout_s=5)

    config = recorder["config"]
    assert config.response_schema is None
    assert config.system_instruction is None


# ===========================================================================
# Req 2.5 -- auth errors are not retried; the operation fails
# ===========================================================================
class _CodedError(Exception):
    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


@pytest.mark.parametrize("status", [401, 403])
def test_auth_error_is_not_retried_and_fails(status):
    """Auth errors (401/403) fail immediately without retry (Req 2.5)."""
    attempts: list[int] = []
    sleeps: list[float] = []

    def transport(request, timeout_s):
        attempts.append(1)
        raise _CodedError("forbidden", status)

    client = GeminiClient(
        api_key="AIza-secret",
        model_name="gemini-1.5-flash",
        max_attempts=5,
        timeout_s=5,
        transport=transport,
        sleep_fn=sleeps.append,
    )

    result = client.generate(GeminiRequest(record_id="rec-9", contents="x"))

    assert not result.ok
    assert result.failure is not None
    assert result.failure.kind is GeminiErrorKind.AUTH
    assert result.failure.record_id == "rec-9"
    # No retry: exactly one attempt and no backoff sleep.
    assert len(attempts) == 1
    assert result.attempts == 1
    assert sleeps == []


# ===========================================================================
# Req 3.3 -- timeout aborts, discards partial, keyed by record id
# ===========================================================================
def test_timeout_aborts_and_is_keyed_by_record_id():
    """A timeout aborts immediately with a timeout failure keyed by id (Req 3.3)."""
    attempts: list[int] = []
    sleeps: list[float] = []

    def transport(request, timeout_s):
        attempts.append(1)
        raise TimeoutError("deadline exceeded")

    client = GeminiClient(
        api_key="AIza-secret",
        model_name="gemini-1.5-flash",
        max_attempts=5,
        timeout_s=7,
        transport=transport,
        sleep_fn=sleeps.append,
    )

    result = client.generate(GeminiRequest(record_id="rec-10", contents="x"))

    assert not result.ok
    assert result.failure is not None
    assert result.failure.kind is GeminiErrorKind.TIMEOUT
    # Keyed by the originating record id (Req 3.3).
    assert result.failure.record_id == "rec-10"
    assert "7s" in result.failure.message
    # Aborted on the first timeout: no retry, no partial text retained.
    assert len(attempts) == 1
    assert result.attempts == 1
    assert sleeps == []
    assert result.text is None


def test_timeout_by_class_name_is_also_aborted():
    """A non-stdlib timeout (class name contains 'Timeout') is treated as timeout."""

    class ReadTimeout(Exception):
        pass

    def transport(request, timeout_s):
        raise ReadTimeout("read timed out")

    client = GeminiClient(
        api_key="AIza-secret",
        model_name="gemini-1.5-flash",
        max_attempts=3,
        timeout_s=4,
        transport=transport,
        sleep_fn=lambda _d: None,
    )

    result = client.generate(GeminiRequest(record_id="rec-11", contents="x"))

    assert result.failure is not None
    assert result.failure.kind is GeminiErrorKind.TIMEOUT
    assert result.attempts == 1


# ===========================================================================
# Req 2.3 -- configured model used on EACH request (success path, multiple calls)
# ===========================================================================
def test_configured_model_used_on_each_request():
    """Every successful request goes through with the same configured model."""
    recorder: dict = {}
    transport = _SdkTransport(api_key="AIza-secret", model_name="gemini-2.0-flash")
    transport._client = _FakeGenaiClient(recorder)

    client = GeminiClient(
        api_key="AIza-secret",
        model_name="gemini-2.0-flash",
        max_attempts=2,
        timeout_s=5,
        transport=transport,
        sleep_fn=lambda _d: None,
    )

    for rid in ("a", "b", "c"):
        result = client.generate(GeminiRequest(record_id=rid, contents=f"c-{rid}"))
        assert result.ok
        assert result.text == "raw-response-text"
        assert recorder["model"] == "gemini-2.0-flash"
        assert recorder["contents"] == f"c-{rid}"
