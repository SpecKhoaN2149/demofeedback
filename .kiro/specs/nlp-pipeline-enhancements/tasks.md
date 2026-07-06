# Implementation Plan: NLP Pipeline Enhancements

## Overview

This plan implements four enhancements to the NLP Feedback Processing pipeline in a bottom-up, incremental order: data models first, then persistence, cache, language detection, trend detection, and finally orchestrator integration. Each task is independently testable and builds on previous tasks. The implementation uses Python 3.11+, Pydantic v2, sqlite3, and the existing google-genai transport infrastructure.

## Tasks

- [x] 1. Define new data models and configuration extensions
  - [x] 1.1 Create new Pydantic data models in `nlp_processing/models/enhancements.py`
    - Define `BatchMetadata`, `SaveResult`, `CachedEnrichment`, `CacheEntry`, `LanguageDetectionResult`, `TimeWindow`, `ThemeSpike`, `SentimentShift`, `SeverityEscalation`, and `TrendReport` models
    - Add field constraints matching the design (confidence 0.0..1.0, severity 1..5, ISO 8601 timestamps)
    - Export all new models from `nlp_processing/models/__init__.py`
    - _Requirements: 1.2, 1.6, 1.7, 2.1, 2.9, 3.2, 3.5, 4.1, 4.5, 5.3, 5.5_

  - [x] 1.2 Add `language_code` and `language_confidence` fields to `InsightRecord` in `nlp_processing/models/records.py`
    - Add `language_code: str | None = None` and `language_confidence: float | None = None` as optional fields
    - Ensure backwards compatibility: existing records without language data remain valid
    - _Requirements: 5.5_

  - [x] 1.3 Create configuration classes in `nlp_processing/persistence_config.py`
    - Define `PersistenceConfig` with `backend` (str) and `db_path` (str) fields with fail-fast validation
    - Define `CacheConfig` with `enabled` (bool, default True) and `ttl_hours` (int, 1..720, default 24) with range validation
    - Define `TrendConfig` with `spike_threshold_pct` (int, 1..1000, default 50), `sentiment_shift_ppt` (int, 1..50, default 15), and `severity_escalation` (float, 0.5..4.0, default 1.0)
    - Raise `ConfigurationError` for invalid values
    - _Requirements: 1.5, 1.9, 2.3, 2.4, 3.3, 4.2, 4.4_

- [x] 2. Implement PersistenceStore
  - [x] 2.1 Create `nlp_processing/persistence/store.py` with the `PersistenceStore` class
    - Implement `__init__` with SQLite backend initialization, schema creation (batches and cache_entries tables with indexes)
    - Implement `save_batch(batch_output: BatchOutput) -> SaveResult` that assigns a UUID batch_id, ISO 8601 timestamp, status "completed", and serializes the BatchOutput as JSON
    - Implement `get_batch(batch_id: str) -> BatchOutput | None` that retrieves and deserializes a saved batch, returning None for not-found
    - Implement `list_batches(start: datetime, end: datetime) -> list[BatchMetadata]` for time-range queries
    - Implement `save_cache_entry(key: str, entry: CacheEntry) -> None` and `get_cache_entry(key: str) -> CacheEntry | None`
    - Implement `delete_expired_cache(cutoff: datetime) -> int` for cache cleanup
    - Handle SQLite errors gracefully: write failures return `SaveResult(success=False, error=...)`, read failures return None
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.6_

  - [x] 2.2 Write property test for batch persistence round-trip
    - **Property 1: Batch persistence round-trip**
    - **Validates: Requirements 1.1, 1.3, 1.6, 1.7**
    - Add `valid_batch_output()` strategy to `tests/strategies.py`
    - Create `tests/test_persistence.py` with Hypothesis test: for any valid BatchOutput, save then retrieve produces field-by-field equal results

  - [x] 2.3 Write property test for batch metadata assignment
    - **Property 2: Batch metadata assignment**
    - **Validates: Requirements 1.2**
    - Test that every saved batch gets a non-empty unique batch_id, valid ISO 8601 UTC timestamp, and status "completed"

  - [x] 2.4 Write unit tests for PersistenceStore edge cases
    - Test not-found returns None
    - Test invalid backend config raises ConfigurationError
    - Test SQLite schema creation on fresh database
    - Test save failure returns SaveResult with success=False
    - _Requirements: 1.4, 1.8, 1.9_

- [x] 3. Checkpoint — Ensure persistence tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement CacheLayer
  - [x] 4.1 Create `nlp_processing/persistence/cache.py` with the `CacheLayer` class
    - Implement `__init__(store: PersistenceStore, ttl_hours: int = 24, enabled: bool = True)` with TTL range validation (1..720)
    - Implement `compute_key(cleaned_text: str, language_code: str) -> str` using SHA-256 hash of text + language_code
    - Implement `get(cleaned_text: str, language_code: str) -> CachedEnrichment | None` that checks TTL expiry and returns None for disabled/expired/missing entries
    - Implement `put(cleaned_text: str, language_code: str, result: CachedEnrichment) -> None` that stores the entry with computed expiry, is a no-op when disabled
    - Handle store unavailability gracefully: return None on read failure, log warning on write failure
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 6.7_

  - [x] 4.2 Write property test for cache key determinism
    - **Property 3: Cache key determinism**
    - **Validates: Requirements 2.1**
    - For any cleaned_text and language_code, compute_key called multiple times produces the same hash

  - [x] 4.3 Write property test for cache enrichment round-trip
    - **Property 4: Cache enrichment round-trip**
    - **Validates: Requirements 2.2, 2.9**
    - Add `valid_cached_enrichment()` strategy to `tests/strategies.py`
    - For any valid CachedEnrichment, put then get with the same text and language returns field-by-field identical data

  - [x] 4.4 Write property test for cache TTL validation
    - **Property 5: Cache TTL validation**
    - **Validates: Requirements 2.3, 2.4**
    - For any int in 1..720 construction succeeds; for any value outside that range construction raises ConfigurationError

  - [x] 4.5 Write property test for cache TTL expiry
    - **Property 6: Cache TTL expiry**
    - **Validates: Requirements 2.5**
    - For any CachedEnrichment whose creation time + TTL < now, get returns None

  - [x] 4.6 Write property test for disabled cache bypass
    - **Property 7: Disabled cache bypass**
    - **Validates: Requirements 2.7**
    - When enabled=False, get always returns None regardless of stored entries

  - [x] 4.7 Write property test for cache key language differentiation
    - **Property 19: Cache key language differentiation**
    - **Validates: Requirements 6.7**
    - For any cleaned_text and two distinct language codes, compute_key produces different keys

- [x] 5. Checkpoint — Ensure persistence and cache tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement LanguageDetector
  - [x] 6.1 Create `nlp_processing/enrichment/language.py` with the `LanguageDetector` class
    - Implement `__init__(client: GeminiClient | GenerateFn, supported_languages: frozenset[str] | None = None)` defaulting to `{"en", "es", "fr", "de", "pt"}`
    - Implement `detect(record: FeedbackRecord) -> LanguageDetectionResult` using a focused Gemini prompt returning ISO 639-1 code + confidence
    - Apply fallback rules: confidence < 0.6 or unsupported language → default to "en", set is_uncertain=True, include note
    - Handle transport failures gracefully: default to "en" with confidence 0.0, is_uncertain=True, and a failure note
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 6.2 Write property test for language detection fallback
    - **Property 17: Language detection fallback**
    - **Validates: Requirements 5.4**
    - For any detection result with confidence < 0.6 or unsupported language, language_code is "en", is_uncertain is True, and a note is present

  - [x] 6.3 Write unit tests for LanguageDetector
    - Test supported language set configuration
    - Test English text detection with high confidence
    - Test unsupported language fallback
    - Test transport failure graceful degradation
    - Test output format of LanguageDetectionResult
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [x] 7. Implement language-aware enrichment prompts
  - [x] 7.1 Create `nlp_processing/enrichment/language_prompts.py` with prompt-building utilities
    - Implement `build_language_instruction(language_code: str) -> str | None` that returns the language override clause for non-English, None for English
    - Modify existing system instructions in Classifier, SentimentAnalyzer, and SeverityScorer to accept an optional language override
    - Ensure all output labels remain English regardless of input language (themes, sentiment values, severity scores)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 7.2 Write property test for language-aware prompt construction
    - **Property 18: Language-aware prompt construction**
    - **Validates: Requirements 6.1, 6.2**
    - For any language code: if not "en", system instruction includes language name; if "en", no language-override clause is present

  - [x] 7.3 Write unit tests for language-aware prompts
    - Test English prompt has no language clause
    - Test non-English prompts include language name and English-output instruction
    - Verify theme labels, sentiment values, and severity scores remain English-constrained
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 8. Checkpoint — Ensure language detection and prompt tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implement TrendDetector
  - [x] 9.1 Create `nlp_processing/trends/detector.py` with the `TrendDetector` class
    - Implement `__init__(store: PersistenceStore, config: TrendConfig)`
    - Implement `detect_trends(baseline: TimeWindow, current: TimeWindow) -> TrendReport`
    - Validate windows: reject if start >= end or windows overlap
    - Query PersistenceStore for InsightRecords within each window
    - Apply minimum 10-record threshold per window; return empty findings with note if insufficient
    - _Requirements: 3.1, 3.6, 3.7, 3.8, 4.6_

  - [x] 9.2 Implement theme frequency spike detection in `TrendDetector`
    - Compute relative theme frequency per window (count per theme / total records)
    - Identify spikes where percentage increase >= configured threshold
    - Handle new themes (baseline frequency = 0) with "new" label
    - Order spikes by percentage increase descending
    - _Requirements: 3.2, 3.3, 3.4, 3.5_

  - [x] 9.3 Implement sentiment shift and severity escalation detection in `TrendDetector`
    - Compute negative/neutral/positive proportions per window (summing to 1.0)
    - Identify sentiment shift when current negative exceeds baseline by threshold (percentage points)
    - Compute mean severity per window (range 1.0..5.0)
    - Identify severity escalation when current mean exceeds baseline mean by threshold
    - Exclude records without sentiment from sentiment metrics; exclude records without severity from severity metrics
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.7_

  - [x] 9.4 Write property test for theme frequency computation
    - **Property 8: Theme frequency computation**
    - **Validates: Requirements 3.2**
    - Add `insight_records_with_themes()` strategy to `tests/strategies.py`
    - For any set of InsightRecords, relative frequency of a theme = count of records with that theme / total records

  - [x] 9.5 Write property test for theme spike detection
    - **Property 9: Theme spike detection**
    - **Validates: Requirements 3.3, 3.4**
    - For any baseline and current distributions plus threshold, a theme is a spike iff percentage increase >= threshold or it is a new theme

  - [x] 9.6 Write property test for spike ordering
    - **Property 10: Spike ordering**
    - **Validates: Requirements 3.5**
    - Spikes in a TrendReport are ordered by percentage increase descending

  - [x] 9.7 Write property test for insufficient data guard
    - **Property 11: Insufficient data guard**
    - **Validates: Requirements 3.6, 4.6**
    - Add `time_window_pair()` and `invalid_time_windows()` strategies to `tests/strategies.py`
    - When either window has < 10 records, return no findings and include insufficient-data note

  - [x] 9.8 Write property test for window validation
    - **Property 12: Window validation**
    - **Validates: Requirements 3.8**
    - For invalid windows (start >= end or overlap), TrendDetector raises ValueError

  - [x] 9.9 Write property test for sentiment proportion computation
    - **Property 13: Sentiment proportion computation**
    - **Validates: Requirements 4.1**
    - For any set of InsightRecords, negative + neutral + positive proportions are each in [0, 1] and sum to 1.0

  - [x] 9.10 Write property test for sentiment shift detection
    - **Property 14: Sentiment shift detection**
    - **Validates: Requirements 4.2**
    - A shift is identified iff current negative proportion exceeds baseline by >= threshold ppt

  - [x] 9.11 Write property test for severity computation and escalation
    - **Property 15: Mean severity computation and escalation detection**
    - **Validates: Requirements 4.3, 4.4**
    - Mean severity is in [1.0, 5.0]; escalation iff current mean exceeds baseline mean by >= threshold

  - [x] 9.12 Write property test for incomplete record exclusion
    - **Property 16: Incomplete record exclusion from metrics**
    - **Validates: Requirements 4.7**
    - Records without sentiment are excluded from sentiment metrics; records without severity from severity metrics

- [x] 10. Checkpoint — Ensure trend detection tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Integrate all components into the Orchestrator
  - [x] 11.1 Extend `NLPProcessor` in `nlp_processing/orchestrator.py` to accept new dependencies
    - Add `PersistenceStore`, `CacheLayer`, and `LanguageDetector` as optional constructor parameters
    - Update `from_config` and `from_settings` to wire new components when configuration is provided
    - Maintain backwards compatibility: all new parameters default to None/disabled
    - _Requirements: 1.1, 2.2, 5.1_

  - [x] 11.2 Integrate language detection into the enrichment pipeline
    - After ingestion produces FeedbackRecords, run LanguageDetector on each record
    - Store detection results (language_code, confidence) for use in enrichment and on InsightRecord
    - Pass language_code to enrichment prompts via the language-aware utilities
    - _Requirements: 5.1, 5.5, 6.1, 6.2_

  - [x] 11.3 Integrate cache lookup and population into the enrichment loop
    - Before calling Gemini for classification/sentiment/severity, check CacheLayer
    - On cache hit, construct enrichment result from cached data without Gemini calls
    - On cache miss and successful enrichment, populate cache with the result
    - Include language_code in cache key via CacheLayer.compute_key
    - _Requirements: 2.1, 2.2, 2.5, 2.7, 2.8, 6.7_

  - [x] 11.4 Integrate batch persistence into process_batch
    - After assembling BatchOutput, call PersistenceStore.save_batch
    - Add `retrieve_batch(batch_id: str) -> BatchOutput | None` method to NLPProcessor
    - Handle save failures gracefully: return BatchOutput to caller regardless, surface SaveResult
    - _Requirements: 1.1, 1.3, 1.4, 1.8_

  - [x] 11.5 Expose TrendDetector via the Orchestrator
    - Add `detect_trends(baseline: TimeWindow, current: TimeWindow) -> TrendReport` method
    - Delegate to TrendDetector with the injected PersistenceStore
    - _Requirements: 3.1, 4.1_

  - [x] 11.6 Write integration tests for the full enhanced pipeline
    - Test: process a batch, verify it is persisted and retrievable
    - Test: process same feedback text twice, verify second call uses cache (no Gemini call)
    - Test: process non-English text, verify language metadata flows through to InsightRecord
    - Test: persist multiple batches, run trend detection, verify TrendReport
    - _Requirements: 1.1, 1.3, 2.2, 3.1, 4.1, 5.5, 6.7_

- [x] 12. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All persistence tests use in-memory SQLite (`:memory:`) for speed and isolation
- The implementation language is Python 3.11+ using the existing project dependencies (google-genai, Pydantic v2, pytest, Hypothesis)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "4.1"] },
    { "id": 3, "tasks": ["4.2", "4.3", "4.4", "4.5", "4.6", "4.7"] },
    { "id": 4, "tasks": ["6.1", "9.1"] },
    { "id": 5, "tasks": ["6.2", "6.3", "7.1", "9.2", "9.3"] },
    { "id": 6, "tasks": ["7.2", "7.3", "9.4", "9.5", "9.6", "9.7", "9.8", "9.9", "9.10", "9.11", "9.12"] },
    { "id": 7, "tasks": ["11.1"] },
    { "id": 8, "tasks": ["11.2", "11.3", "11.4", "11.5"] },
    { "id": 9, "tasks": ["11.6"] }
  ]
}
```
