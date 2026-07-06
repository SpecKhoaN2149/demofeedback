"""Enrichment layer: Classifier, Sentiment_Analyzer, Severity_Scorer, LanguageDetector, EntityExtractor, and PriorityScorer."""

from .classifier import (
    OTHER_THEME,
    THEME_CONFIDENCE_THRESHOLD,
    ClassificationError,
    ClassificationOutcome,
    ClassificationResponse,
    ClassificationTheme,
    Classifier,
)
from .entity_extractor import (
    EXTRACTION_TIMEOUT_SECONDS,
    MAX_ENTITIES_PER_RECORD,
    MAX_ENTITY_VALUE_LENGTH,
    MIN_CONFIDENCE_THRESHOLD,
    VALID_ENTITY_TYPES,
    EntityCandidate,
    EntityExtractionResponse,
    EntityExtractionResult,
    EntityExtractor,
)
from .language import (
    CONFIDENCE_THRESHOLD,
    DEFAULT_LANGUAGE,
    DEFAULT_SUPPORTED_LANGUAGES,
    LanguageDetectionResponse,
    LanguageDetector,
)
from .language_prompts import apply_language_override, build_language_instruction
from .priority_scorer import (
    ESCALATION_KEYWORDS,
    MEDIUM_INTENTS,
    OUTAGE_KEYWORDS,
    SCORE_RANGES,
    PriorityScorer,
)
from .sentiment import (
    ALLOWED_SENTIMENTS,
    DEFAULT_SENTIMENT,
    SentimentAnalyzer,
    SentimentError,
    SentimentOutcome,
    SentimentResponse,
)
from .severity import (
    DEFAULT_SEVERITY,
    SeverityError,
    SeverityOutcome,
    SeverityResponse,
    SeverityScorer,
)

__all__ = [
    # Classifier
    "Classifier",
    "ClassificationOutcome",
    "ClassificationError",
    "ClassificationResponse",
    "ClassificationTheme",
    "THEME_CONFIDENCE_THRESHOLD",
    "OTHER_THEME",
    # Entity Extractor
    "EntityExtractor",
    "EntityExtractionResult",
    "EntityExtractionResponse",
    "EntityCandidate",
    "MAX_ENTITIES_PER_RECORD",
    "MIN_CONFIDENCE_THRESHOLD",
    "MAX_ENTITY_VALUE_LENGTH",
    "EXTRACTION_TIMEOUT_SECONDS",
    "VALID_ENTITY_TYPES",
    # Language
    "LanguageDetector",
    "LanguageDetectionResponse",
    "DEFAULT_SUPPORTED_LANGUAGES",
    "CONFIDENCE_THRESHOLD",
    "DEFAULT_LANGUAGE",
    # Language Prompts
    "build_language_instruction",
    "apply_language_override",
    # Priority Scorer
    "PriorityScorer",
    "OUTAGE_KEYWORDS",
    "ESCALATION_KEYWORDS",
    "MEDIUM_INTENTS",
    "SCORE_RANGES",
    # Sentiment
    "SentimentAnalyzer",
    "SentimentOutcome",
    "SentimentError",
    "SentimentResponse",
    "DEFAULT_SENTIMENT",
    "ALLOWED_SENTIMENTS",
    # Severity
    "SeverityScorer",
    "SeverityOutcome",
    "SeverityError",
    "SeverityResponse",
    "DEFAULT_SEVERITY",
]
