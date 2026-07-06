"""Language-aware prompt utilities for enrichment (Req 6).

This module provides functions to build language override instructions for
the Gemini system prompts used by the Classifier, SentimentAnalyzer, and
SeverityScorer. When feedback text is in a non-English language, the override
clause instructs Gemini that the input is in that language while requiring all
output labels to remain in English.

Key behaviour (Requirements 6.1–6.6):
* If the detected language is English ("en"), no override is applied (Req 6.2).
* If the detected language is non-English, the system instruction includes the
  language name and a directive for English-only output labels (Req 6.1).
* Theme labels, sentiment values, and severity scores remain English-constrained
  regardless of input language (Req 6.3, 6.4, 6.5).
"""

from __future__ import annotations

from typing import Optional

# ISO 639-1 code to human-readable language name mapping.
# Covers the supported language set (Req 5.2) plus a reasonable fallback.
_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
}


def build_language_instruction(language_code: str) -> Optional[str]:
    """Build a language override clause for Gemini system instructions.

    Parameters
    ----------
    language_code:
        An ISO 639-1 two-letter language code (e.g. "en", "es", "fr").

    Returns
    -------
    str | None
        ``None`` for English (no override needed). For non-English, returns an
        instruction clause such as:
        "The input text is in Spanish. All output labels (theme names,
        sentiment values, severity scores) must be in English regardless of
        the input language."
    """
    if language_code == "en":
        return None

    language_name = _LANGUAGE_NAMES.get(
        language_code, f"language code '{language_code}'"
    )
    return (
        f"The input text is in {language_name}. "
        "All output labels (theme names, sentiment values, severity scores) "
        "must be in English regardless of the input language."
    )


def apply_language_override(system_instruction: str, language_code: str) -> str:
    """Prepend a language override clause to a system instruction if needed.

    This is the primary integration point for the Classifier, SentimentAnalyzer,
    and SeverityScorer. Rather than modifying each component's internals, callers
    pass the base system instruction and the detected language code. If the
    language is non-English, the override clause is prepended; otherwise the
    original instruction is returned unchanged.

    Parameters
    ----------
    system_instruction:
        The base system instruction string used by a Gemini enrichment call.
    language_code:
        An ISO 639-1 two-letter language code (e.g. "en", "es").

    Returns
    -------
    str
        The (possibly augmented) system instruction.
    """
    override = build_language_instruction(language_code)
    if override is None:
        return system_instruction
    return f"{override}\n\n{system_instruction}"


__all__ = [
    "build_language_instruction",
    "apply_language_override",
]
