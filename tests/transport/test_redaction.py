"""Unit tests for the secret redaction utilities (Req 2.6)."""

from __future__ import annotations

import logging

from nlp_processing.transport.redaction import (
    REDACTION_PLACEHOLDER,
    RedactingFilter,
    SecretRegistry,
    redact,
    redact_error,
    register_secret,
)


def test_registry_redacts_registered_secret():
    reg = SecretRegistry()
    reg.register("super-secret-key")
    out = reg.redact("calling api with super-secret-key now")
    assert "super-secret-key" not in out
    assert REDACTION_PLACEHOLDER in out


def test_registry_ignores_empty_and_none_secrets():
    reg = SecretRegistry()
    reg.register("")
    reg.register("   ")
    reg.register(None)  # type: ignore[arg-type]
    # No secrets registered -> empty string is NOT redacted out of text.
    assert reg.secrets == frozenset()
    assert reg.redact("nothing to redact here") == "nothing to redact here"


def test_registry_redacts_multiple_and_overlapping_secrets():
    reg = SecretRegistry(["abc", "abcdef"])
    # Longer secret replaced first so no fragment leaks.
    out = reg.redact("token=abcdef and short=abc")
    assert "abcdef" not in out
    assert "abc" not in out


def test_registry_handles_non_string_input():
    reg = SecretRegistry(["secret"])
    assert reg.redact(12345) == "12345"


def test_redact_error_scrubs_secret_from_exception():
    reg = SecretRegistry(["KEY123"])
    err = ValueError("auth failed for KEY123")
    rendered = redact_error(err, registry=reg)
    assert "KEY123" not in rendered
    assert "ValueError" in rendered
    assert REDACTION_PLACEHOLDER in rendered


def test_redact_error_without_message():
    reg = SecretRegistry(["KEY123"])
    rendered = redact_error(RuntimeError(), registry=reg)
    assert rendered == "RuntimeError"


def test_logging_filter_redacts_message(caplog):
    reg = SecretRegistry(["TOPSECRET"])
    logger = logging.getLogger("test.redaction.message")
    logger.setLevel(logging.INFO)
    logger.addFilter(RedactingFilter(registry=reg))

    with caplog.at_level(logging.INFO, logger="test.redaction.message"):
        logger.info("using api key TOPSECRET for request")

    assert "TOPSECRET" not in caplog.text
    assert REDACTION_PLACEHOLDER in caplog.text


def test_logging_filter_redacts_args(caplog):
    reg = SecretRegistry(["TOPSECRET"])
    logger = logging.getLogger("test.redaction.args")
    logger.setLevel(logging.INFO)
    logger.addFilter(RedactingFilter(registry=reg))

    with caplog.at_level(logging.INFO, logger="test.redaction.args"):
        logger.info("key=%s attempt=%d", "TOPSECRET", 3)

    record = caplog.records[-1]
    assert "TOPSECRET" not in record.getMessage()
    assert "attempt=3" in record.getMessage()


def test_default_registry_helpers():
    register_secret("DEFAULTKEY")
    try:
        assert "DEFAULTKEY" not in redact("value DEFAULTKEY end")
    finally:
        # Clean up the shared default registry to avoid cross-test bleed.
        from nlp_processing.transport.redaction import get_default_registry

        get_default_registry().unregister("DEFAULTKEY")
