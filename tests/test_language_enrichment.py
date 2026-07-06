"""Unit and property tests for language-aware prompt utilities (tasks 7.2, 7.3).

Tests:
1. build_language_instruction returns None for English
2. build_language_instruction returns language clause for non-English
3. apply_language_override leaves English prompts unchanged
4. apply_language_override prepends language clause for non-English
5. Output labels (themes, sentiment, severity) remain English-constrained in the override

Property 18: Language-aware prompt construction
- For any language code: if "en", returns None; if not "en" and supported,
  returns a string containing the language name and "English".

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from nlp_processing.enrichment.language_prompts import (
    apply_language_override,
    build_language_instruction,
)

# The supported non-English language codes and their expected names,
# mirroring the module's _LANGUAGE_NAMES mapping.
_SUPPORTED_NON_ENGLISH = {
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
}


# ---------------------------------------------------------------------------
# Test 1: English prompt has no language clause (Req 6.2)
# ---------------------------------------------------------------------------


class TestBuildLanguageInstructionEnglish:
    """Verify that English returns None (no override clause)."""

    def test_english_returns_none(self):
        """build_language_instruction("en") returns None — no override needed."""
        result = build_language_instruction("en")
        assert result is None

    def test_english_returns_none_not_empty_string(self):
        """Ensure None is returned, not an empty string."""
        result = build_language_instruction("en")
        assert result is not ""
        assert result is None


# ---------------------------------------------------------------------------
# Test 2: Non-English prompts include language name (Req 6.1)
# ---------------------------------------------------------------------------


class TestBuildLanguageInstructionNonEnglish:
    """Verify non-English codes produce a language clause with the language name."""

    def test_spanish_includes_language_name(self):
        """build_language_instruction("es") includes "Spanish"."""
        result = build_language_instruction("es")
        assert result is not None
        assert "Spanish" in result

    def test_french_includes_language_name(self):
        """build_language_instruction("fr") includes "French"."""
        result = build_language_instruction("fr")
        assert result is not None
        assert "French" in result

    def test_german_includes_language_name(self):
        """build_language_instruction("de") includes "German"."""
        result = build_language_instruction("de")
        assert result is not None
        assert "German" in result

    def test_portuguese_includes_language_name(self):
        """build_language_instruction("pt") includes "Portuguese"."""
        result = build_language_instruction("pt")
        assert result is not None
        assert "Portuguese" in result

    def test_unknown_language_code_included_in_instruction(self):
        """An unsupported code still produces an instruction with the code mentioned."""
        result = build_language_instruction("ja")
        assert result is not None
        assert "ja" in result

    def test_non_english_mentions_english_output(self):
        """Non-English instruction explicitly mentions English for output labels."""
        result = build_language_instruction("es")
        assert result is not None
        assert "English" in result


# ---------------------------------------------------------------------------
# Test 3: Theme labels, sentiment values, severity scores English-constrained
#          (Req 6.3, 6.4, 6.5)
# ---------------------------------------------------------------------------


class TestOutputLabelsEnglishConstrained:
    """Verify the override instruction constrains themes, sentiment, severity to English."""

    def test_override_mentions_theme_names(self):
        """Non-English instruction references theme names as English-constrained."""
        result = build_language_instruction("fr")
        assert result is not None
        assert "theme" in result.lower()

    def test_override_mentions_sentiment_values(self):
        """Non-English instruction references sentiment values as English-constrained."""
        result = build_language_instruction("de")
        assert result is not None
        assert "sentiment" in result.lower()

    def test_override_mentions_severity_scores(self):
        """Non-English instruction references severity scores as English-constrained."""
        result = build_language_instruction("pt")
        assert result is not None
        assert "severity" in result.lower()

    def test_override_contains_english_output_directive(self):
        """The instruction contains a directive for English-only output labels."""
        result = build_language_instruction("es")
        assert result is not None
        assert "must be in English" in result


# ---------------------------------------------------------------------------
# Test 4: apply_language_override returns unchanged for English (Req 6.2)
# ---------------------------------------------------------------------------


class TestApplyLanguageOverrideEnglish:
    """Verify that apply_language_override returns the instruction unchanged for English."""

    def test_english_returns_unchanged_instruction(self):
        """apply_language_override with "en" returns the original instruction exactly."""
        base = "You are a classification model. Classify the feedback."
        result = apply_language_override(base, "en")
        assert result == base

    def test_english_no_extra_content_prepended(self):
        """English override does not prepend anything to the instruction."""
        base = "Analyze sentiment of the feedback text."
        result = apply_language_override(base, "en")
        assert not result.startswith("The input text")


# ---------------------------------------------------------------------------
# Test 5: apply_language_override prepends clause for non-English (Req 6.1)
# ---------------------------------------------------------------------------


class TestApplyLanguageOverrideNonEnglish:
    """Verify that non-English prepends the language clause to the system instruction."""

    def test_spanish_prepends_language_clause(self):
        """apply_language_override with "es" prepends the language clause."""
        base = "You are a classification model."
        result = apply_language_override(base, "es")
        assert result.startswith("The input text is in Spanish.")
        assert base in result

    def test_french_prepends_language_clause(self):
        """apply_language_override with "fr" prepends the French clause."""
        base = "Analyze sentiment."
        result = apply_language_override(base, "fr")
        assert result.startswith("The input text is in French.")
        assert base in result

    def test_override_includes_english_output_instruction(self):
        """The prepended override mentions English for output labels."""
        base = "Score severity of this feedback."
        result = apply_language_override(base, "de")
        assert "English" in result
        assert base in result

    def test_override_separates_clause_from_base_instruction(self):
        """The override clause is separated from the base instruction by a blank line."""
        base = "You are a classification model."
        result = apply_language_override(base, "pt")
        # The clause and base should be separated by \n\n
        parts = result.split("\n\n")
        assert len(parts) >= 2
        assert base in parts[-1]


# ---------------------------------------------------------------------------
# Property 18: Language-aware prompt construction (task 7.2)
# **Validates: Requirements 6.1, 6.2**
# ---------------------------------------------------------------------------


class TestLanguageAwarePromptConstructionProperty:
    """Property 18: Language-aware prompt construction.

    **Validates: Requirements 6.1, 6.2**

    For any language code:
    - If "en", build_language_instruction returns None (no override clause).
    - If not "en" and a supported non-English code, returns a string containing
      the language name and "English" (output requirement).
    """

    @given(data=st.just("en"))
    @settings(max_examples=100)
    def test_english_returns_none(self, data: str):
        """For language code "en", build_language_instruction returns None.

        Req 6.2: When the detected language is English, no language-override
        clause is present.
        """
        result = build_language_instruction(data)
        assert result is None

    @given(lang_code=st.sampled_from(list(_SUPPORTED_NON_ENGLISH.keys())))
    @settings(max_examples=100)
    def test_non_english_supported_includes_language_name_and_english(self, lang_code: str):
        """For any non-English supported code, the instruction includes the
        language name and "English".

        Req 6.1: The system instruction includes the detected language name
        and instructs output labels to be in English.
        """
        result = build_language_instruction(lang_code)

        # Must return a string (not None)
        assert result is not None
        assert isinstance(result, str)

        # Must contain the expected language name
        expected_name = _SUPPORTED_NON_ENGLISH[lang_code]
        assert expected_name in result, (
            f"Expected language name '{expected_name}' not found in instruction: {result}"
        )

        # Must contain "English" (output requirement — labels must be English)
        assert "English" in result, (
            f"Expected 'English' not found in instruction: {result}"
        )

    @given(
        lang_code=st.text(
            alphabet=st.characters(min_codepoint=97, max_codepoint=122),
            min_size=2,
            max_size=3,
        ).filter(lambda c: c != "en")
    )
    @settings(max_examples=100)
    def test_any_non_english_code_returns_string_not_none(self, lang_code: str):
        """For any language code that is not "en", the function returns a
        non-None string (may or may not contain a known language name, but
        always contains "English" for the output requirement).

        Req 6.1: Non-English language codes produce a language-override clause.
        Req 6.2: Only "en" produces no override (None).
        """
        result = build_language_instruction(lang_code)

        # Must not be None for any non-English code
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0

        # Must always contain "English" as the output language requirement
        assert "English" in result, (
            f"Expected 'English' in instruction for code '{lang_code}': {result}"
        )
