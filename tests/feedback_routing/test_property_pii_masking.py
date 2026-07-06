# Feature: nlp-feedback-routing, Property 3
"""Property-based test for PII Masking Round-Trip (Property 3).

**Property 3: PII Masking Round-Trip** — For any input text containing email
addresses, phone numbers, or SSN patterns, the masked output SHALL contain the
corresponding placeholder tokens ("[EMAIL]", "[PHONE]", "[SSN]") in place of
each PII occurrence, AND the separately stored original text SHALL allow
reconstruction of the pre-masked content exactly.

**Validates: Requirements 3.6**
"""

from __future__ import annotations

import re

from hypothesis import given, settings, strategies as st

from nlp_processing.preprocessing.preprocessor import Preprocessor


# ---------------------------------------------------------------------------
# Hypothesis strategies for generating text with embedded PII patterns
# ---------------------------------------------------------------------------

# Email components
_email_local = st.from_regex(r"[a-z][a-z0-9._%+]{1,10}", fullmatch=True)
_email_domain = st.from_regex(r"[a-z][a-z0-9]{1,8}\.[a-z]{2,4}", fullmatch=True)


@st.composite
def email_addresses(draw: st.DrawFn) -> str:
    """Generate realistic email address strings."""
    local = draw(_email_local)
    domain = draw(_email_domain)
    return f"{local}@{domain}"


@st.composite
def phone_numbers(draw: st.DrawFn) -> str:
    """Generate US phone numbers in various formats."""
    fmt = draw(st.sampled_from([
        "({area}) {exch}-{sub}",
        "{area}-{exch}-{sub}",
        "{area}.{exch}.{sub}",
    ]))
    area = draw(st.from_regex(r"[2-9]\d{2}", fullmatch=True))
    exch = draw(st.from_regex(r"[2-9]\d{2}", fullmatch=True))
    sub = draw(st.from_regex(r"\d{4}", fullmatch=True))
    return fmt.format(area=area, exch=exch, sub=sub)


@st.composite
def ssn_patterns(draw: st.DrawFn) -> str:
    """Generate SSN-formatted strings (xxx-xx-xxxx)."""
    part1 = draw(st.from_regex(r"\d{3}", fullmatch=True))
    part2 = draw(st.from_regex(r"\d{2}", fullmatch=True))
    part3 = draw(st.from_regex(r"\d{4}", fullmatch=True))
    return f"{part1}-{part2}-{part3}"


# Surrounding text that does not accidentally look like PII
_safe_words = st.sampled_from([
    "please", "contact", "my", "info", "is", "the", "send", "to",
    "about", "help", "with", "regarding", "issue", "feedback",
    "service", "account", "problem", "thanks", "hello", "hi",
])

_surrounding_text = st.lists(_safe_words, min_size=1, max_size=6).map(" ".join)


@st.composite
def text_with_email(draw: st.DrawFn) -> str:
    """Generate text containing at least one email address."""
    prefix = draw(_surrounding_text)
    email = draw(email_addresses())
    suffix = draw(_surrounding_text)
    return f"{prefix} {email} {suffix}"


@st.composite
def text_with_phone(draw: st.DrawFn) -> str:
    """Generate text containing at least one phone number."""
    prefix = draw(_surrounding_text)
    phone = draw(phone_numbers())
    suffix = draw(_surrounding_text)
    return f"{prefix} {phone} {suffix}"


@st.composite
def text_with_ssn(draw: st.DrawFn) -> str:
    """Generate text containing at least one SSN pattern."""
    prefix = draw(_surrounding_text)
    ssn = draw(ssn_patterns())
    suffix = draw(_surrounding_text)
    return f"{prefix} {ssn} {suffix}"


@st.composite
def text_with_mixed_pii(draw: st.DrawFn) -> str:
    """Generate text containing a mix of email, phone, and/or SSN patterns."""
    parts: list[str] = []
    parts.append(draw(_surrounding_text))

    # Include at least one PII type, potentially all three
    pii_types = draw(st.lists(
        st.sampled_from(["email", "phone", "ssn"]),
        min_size=1,
        max_size=3,
        unique=True,
    ))

    for pii_type in pii_types:
        if pii_type == "email":
            parts.append(draw(email_addresses()))
        elif pii_type == "phone":
            parts.append(draw(phone_numbers()))
        else:
            parts.append(draw(ssn_patterns()))
        parts.append(draw(_surrounding_text))

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

_preprocessor = Preprocessor()


@given(text=text_with_email())
@settings(max_examples=100)
def test_email_masked_and_original_preserved(text: str):
    """Masking text with an email produces [EMAIL] token and original is preserved.

    **Validates: Requirements 3.6**
    """
    masked, original = _preprocessor.mask_pii(text)

    # The masked output must contain the [EMAIL] placeholder
    assert "[EMAIL]" in masked, (
        f"Expected [EMAIL] in masked output but got: {masked!r}"
    )

    # The original text must be exactly the input (allows reconstruction)
    assert original == text, (
        f"Original text should allow exact reconstruction. "
        f"Expected: {text!r}, Got: {original!r}"
    )

    # The masked text should NOT contain the raw email pattern
    email_pattern = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
    assert not email_pattern.search(masked), (
        f"Masked output still contains email pattern: {masked!r}"
    )


@given(text=text_with_phone())
@settings(max_examples=100)
def test_phone_masked_and_original_preserved(text: str):
    """Masking text with a phone number produces [PHONE] token and original is preserved.

    **Validates: Requirements 3.6**
    """
    masked, original = _preprocessor.mask_pii(text)

    # The masked output must contain the [PHONE] placeholder
    assert "[PHONE]" in masked, (
        f"Expected [PHONE] in masked output but got: {masked!r}"
    )

    # The original text must be exactly the input (allows reconstruction)
    assert original == text, (
        f"Original text should allow exact reconstruction. "
        f"Expected: {text!r}, Got: {original!r}"
    )


@given(text=text_with_ssn())
@settings(max_examples=100)
def test_ssn_masked_and_original_preserved(text: str):
    """Masking text with an SSN produces [SSN] token and original is preserved.

    **Validates: Requirements 3.6**
    """
    masked, original = _preprocessor.mask_pii(text)

    # The masked output must contain the [SSN] placeholder
    assert "[SSN]" in masked, (
        f"Expected [SSN] in masked output but got: {masked!r}"
    )

    # The original text must be exactly the input (allows reconstruction)
    assert original == text, (
        f"Original text should allow exact reconstruction. "
        f"Expected: {text!r}, Got: {original!r}"
    )

    # The masked text should NOT contain the raw SSN pattern
    ssn_regex = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    assert not ssn_regex.search(masked), (
        f"Masked output still contains SSN pattern: {masked!r}"
    )


@given(text=text_with_mixed_pii())
@settings(max_examples=100)
def test_mixed_pii_masked_and_original_preserved(text: str):
    """Masking text with mixed PII types produces correct tokens and original is preserved.

    **Validates: Requirements 3.6**
    """
    masked, original = _preprocessor.mask_pii(text)

    # The original text must always equal the input exactly
    assert original == text, (
        f"Original text should allow exact reconstruction. "
        f"Expected: {text!r}, Got: {original!r}"
    )

    # At least one placeholder token must be present
    has_placeholder = (
        "[EMAIL]" in masked or "[PHONE]" in masked or "[SSN]" in masked
    )
    assert has_placeholder, (
        f"Expected at least one placeholder token in masked output: {masked!r}"
    )


@given(text=text_with_email())
@settings(max_examples=100)
def test_round_trip_reconstruction_from_original(text: str):
    """The preserved original text allows exact reconstruction of the pre-masked content.

    Given the (masked, original) tuple, we can verify that the original is
    identical to the input, meaning authorized processes can always reconstruct
    the full unmasked text.

    **Validates: Requirements 3.6**
    """
    masked, original = _preprocessor.mask_pii(text)

    # Round-trip: re-masking the original should produce the same masked output
    re_masked, re_original = _preprocessor.mask_pii(original)
    assert re_masked == masked, (
        f"Re-masking the original should produce the same masked output. "
        f"First mask: {masked!r}, Re-mask: {re_masked!r}"
    )
    assert re_original == original, (
        f"Re-masking original should preserve original again. "
        f"Expected: {original!r}, Got: {re_original!r}"
    )
