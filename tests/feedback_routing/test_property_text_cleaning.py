"""Property 2: Text Cleaning Invariants.

# Feature: nlp-feedback-routing, Property 2

**Validates: Requirements 3.2**

For any input string, after the Preprocessor's clean_text operation:
(a) no HTML tags remain in the output,
(b) the output is in Unicode NFC form,
(c) no sequence of two or more consecutive whitespace characters exists in the interior,
(d) no leading or trailing whitespace exists.
"""

from __future__ import annotations

import re
import unicodedata

from hypothesis import given, settings
from hypothesis import strategies as st

from nlp_processing.preprocessing.preprocessor import Preprocessor

# ---------------------------------------------------------------------------
# Strategies: generate strings with HTML tags, unicode variants, mixed whitespace
# ---------------------------------------------------------------------------

# HTML tag fragments to inject into generated text
_HTML_TAGS = st.sampled_from([
    "<b>", "</b>", "<i>", "</i>", "<p>", "</p>", "<br>", "<br/>",
    "<div>", "</div>", "<span>", "</span>", "<a href='x'>", "</a>",
    "<script>alert('x')</script>", "<img src='x'>", "<!-- comment -->",
    "<h1>", "</h1>", "<ul>", "<li>", "</li>", "</ul>",
    "<strong>", "</strong>", "<em>", "</em>",
])

# Unicode characters that have NFC/NFD decomposition variants
_UNICODE_VARIANTS = st.sampled_from([
    "\u00e9",       # é (NFC precomposed)
    "e\u0301",      # é (NFD decomposed: e + combining acute)
    "\u00f1",       # ñ (NFC)
    "n\u0303",      # ñ (NFD: n + combining tilde)
    "\u00fc",       # ü (NFC)
    "u\u0308",      # ü (NFD: u + combining diaeresis)
    "\u00e0",       # à (NFC)
    "a\u0300",      # à (NFD: a + combining grave)
    "\u1e0b",       # ḋ (NFC: d with dot above)
    "d\u0307",      # ḋ (NFD: d + combining dot above)
    "\u01d5",       # Ǖ (NFC: U with diaeresis and macron)
    "\ufb01",       # fi ligature (NFC compatible)
    "\u2126",       # Ω (ohm sign, NFC normalizes to Ω U+03A9)
])

# Various whitespace characters for mixed whitespace testing
_WHITESPACE_CHARS = st.sampled_from([
    " ", "  ", "   ", "\t", "\n", "\r\n", "\r", "\t\t",
    " \t ", "\n\n", "  \t\n  ", "\u00a0",  # non-breaking space
    "\u2003",  # em space
    "\u2002",  # en space
    "\u2009",  # thin space
])


@st.composite
def text_with_html_and_whitespace(draw: st.DrawFn) -> str:
    """Generate strings mixing normal text, HTML tags, unicode variants, and whitespace.

    This strategy creates realistic dirty input that exercises all branches
    of the clean_text method.
    """
    # Number of segments to combine
    num_segments = draw(st.integers(min_value=1, max_value=8))
    parts: list[str] = []

    for _ in range(num_segments):
        segment_type = draw(st.sampled_from([
            "text", "html", "unicode", "whitespace",
        ]))

        if segment_type == "text":
            parts.append(draw(st.text(
                alphabet=st.characters(
                    min_codepoint=32, max_codepoint=126,
                    blacklist_categories=("Cs",),
                ),
                min_size=1,
                max_size=30,
            )))
        elif segment_type == "html":
            parts.append(draw(_HTML_TAGS))
        elif segment_type == "unicode":
            parts.append(draw(_UNICODE_VARIANTS))
        else:
            parts.append(draw(_WHITESPACE_CHARS))

    return "".join(parts)


# Also test with completely arbitrary text (including surrogates filtered out)
_arbitrary_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=0,
    max_size=200,
)

# HTML tag detection pattern (same regex used in the implementation)
_HTML_TAG_RE = re.compile(r"<[^>]*>")

# Multiple consecutive whitespace in interior (not at boundaries)
_INTERIOR_MULTI_WS_RE = re.compile(r"(?<=\S)\s{2,}(?=\S)")


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

preprocessor = Preprocessor()


@settings(max_examples=100)
@given(raw_text=text_with_html_and_whitespace())
def test_no_html_tags_in_output(raw_text: str) -> None:
    """Property 2a: No HTML tags remain in the cleaned output.

    # Feature: nlp-feedback-routing, Property 2
    **Validates: Requirements 3.2**
    """
    cleaned = preprocessor.clean_text(raw_text)
    assert not _HTML_TAG_RE.search(cleaned), (
        f"HTML tags found in cleaned output: {cleaned!r} (input: {raw_text!r})"
    )


@settings(max_examples=100)
@given(raw_text=text_with_html_and_whitespace())
def test_output_is_nfc_normalized(raw_text: str) -> None:
    """Property 2b: The output is in Unicode NFC form.

    # Feature: nlp-feedback-routing, Property 2
    **Validates: Requirements 3.2**
    """
    cleaned = preprocessor.clean_text(raw_text)
    assert cleaned == unicodedata.normalize("NFC", cleaned), (
        f"Output is not NFC normalized: {cleaned!r} "
        f"(NFC form: {unicodedata.normalize('NFC', cleaned)!r})"
    )


@settings(max_examples=100)
@given(raw_text=text_with_html_and_whitespace())
def test_no_consecutive_whitespace_in_interior(raw_text: str) -> None:
    """Property 2c: No consecutive whitespace in the interior of the output.

    # Feature: nlp-feedback-routing, Property 2
    **Validates: Requirements 3.2**
    """
    cleaned = preprocessor.clean_text(raw_text)
    if cleaned:  # only check non-empty output
        # There should be no occurrence of 2+ whitespace chars anywhere in output
        assert not re.search(r"\s{2,}", cleaned), (
            f"Consecutive whitespace found in output: {cleaned!r}"
        )


@settings(max_examples=100)
@given(raw_text=text_with_html_and_whitespace())
def test_no_leading_or_trailing_whitespace(raw_text: str) -> None:
    """Property 2d: No leading or trailing whitespace in the output.

    # Feature: nlp-feedback-routing, Property 2
    **Validates: Requirements 3.2**
    """
    cleaned = preprocessor.clean_text(raw_text)
    if cleaned:  # only check non-empty output
        assert cleaned == cleaned.strip(), (
            f"Leading/trailing whitespace found: {cleaned!r} vs stripped: {cleaned.strip()!r}"
        )


@settings(max_examples=100)
@given(raw_text=_arbitrary_text)
def test_all_invariants_on_arbitrary_text(raw_text: str) -> None:
    """Property 2 (all invariants): Combined check on arbitrary text input.

    # Feature: nlp-feedback-routing, Property 2
    **Validates: Requirements 3.2**
    """
    cleaned = preprocessor.clean_text(raw_text)

    # (a) No HTML tags
    assert not _HTML_TAG_RE.search(cleaned), (
        f"HTML tags found: {cleaned!r}"
    )

    # (b) NFC normalized
    assert cleaned == unicodedata.normalize("NFC", cleaned), (
        f"Not NFC: {cleaned!r}"
    )

    # (c) No consecutive whitespace in interior
    if cleaned:
        assert not re.search(r"\s{2,}", cleaned), (
            f"Consecutive whitespace: {cleaned!r}"
        )

    # (d) No leading/trailing whitespace
    if cleaned:
        assert cleaned == cleaned.strip(), (
            f"Leading/trailing ws: {cleaned!r}"
        )
