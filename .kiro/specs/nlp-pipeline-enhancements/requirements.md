# Requirements Document

## Introduction

This document defines the requirements for three targeted enhancements to the existing NLP Feedback Processing pipeline: a persistence and caching layer for durable storage and reduced API costs, trend detection for identifying emerging issues over time, and multi-language support for processing international customer feedback. These enhancements build on the current system which processes telecom customer feedback through ingestion, enrichment (classification, sentiment, severity via Google Gemini), clustering, and prioritization in a single in-memory batch with no persistence between sessions.

## Glossary

- **Pipeline**: The end-to-end NLP feedback processing system from ingestion through output assembly
- **Enrichment_Engine**: The subsystem responsible for classification, sentiment, and severity scoring of individual records via Gemini API calls
- **Persistence_Store**: The storage backend that durably saves pipeline inputs, intermediate results, and final outputs across sessions
- **Cache_Layer**: The component responsible for storing and retrieving previously computed enrichment results to avoid redundant Gemini API calls
- **Trend_Detector**: The component that identifies statistically significant changes in theme frequency, sentiment distribution, or severity over configurable time windows
- **Language_Detector**: The component that identifies the natural language of incoming feedback text
- **Gemini_Client**: The existing transport layer that issues authenticated, schema-constrained requests to the Google Gemini API with retry and backoff
- **Batch_Orchestrator**: The existing component that drives the processing pipeline from ingestion through output assembly
- **FeedbackRecord**: A validated, normalized feedback record produced by ingestion with a unique id, source channel, cleaned text, and metadata
- **InsightRecord**: A fully enriched record carrying themes, sentiment, severity, cluster assignment, and review flag
- **BatchOutput**: The assembled output object containing insights, clusters, failures, system errors, summary accounting, and model name
- **TrendReport**: The output object produced by the Trend_Detector containing identified theme spikes, sentiment shifts, and severity escalations
- **Baseline_Window**: A configurable historical time range used as the reference period for trend comparison
- **Current_Window**: A configurable recent time range compared against the Baseline_Window to detect trends

## Requirements

### Requirement 1: Batch Persistence

**User Story:** As a pipeline operator, I want processed batch results to be saved durably, so that results survive application restarts and historical batches can be retrieved without reprocessing.

#### Acceptance Criteria

1. WHEN a batch completes processing, THE Persistence_Store SHALL save the full BatchOutput keyed by a unique batch identifier
2. THE Persistence_Store SHALL assign each persisted batch a unique identifier, a timestamp recording when processing completed in ISO 8601 UTC format, and a status of "completed"
3. WHEN requested to retrieve a batch by identifier, THE Persistence_Store SHALL return the previously saved BatchOutput without reprocessing
4. WHEN requested to retrieve a batch identifier that does not exist, THE Persistence_Store SHALL return a not-found indication rather than an error
5. THE Persistence_Store SHALL support a configurable storage backend specified at startup, with at least a local SQLite option
6. THE Persistence_Store SHALL persist all InsightRecords, Clusters, FailureEntries, and the BatchSummary as part of the saved BatchOutput
7. FOR ALL completed batches, saving then retrieving a BatchOutput by its identifier SHALL produce an object whose InsightRecords, Clusters, FailureEntries, BatchSummary, timestamp, and status are field-by-field equal to those of the originally saved BatchOutput (round-trip property)
8. IF the Persistence_Store fails to save a BatchOutput due to a storage backend error, THEN THE Persistence_Store SHALL return a save-failure indication identifying the batch identifier and the failure reason, and SHALL NOT record the batch as "completed"
9. IF the storage backend configuration is absent or specifies an unrecognized backend at startup, THEN THE Persistence_Store SHALL stop initialization and report a configuration error identifying the invalid or missing backend setting

### Requirement 2: Enrichment Result Caching

**User Story:** As a pipeline operator, I want repeated enrichment of identical feedback text to be served from a cache, so that redundant Gemini API calls are eliminated and processing cost is reduced.

#### Acceptance Criteria

1. THE Cache_Layer SHALL store enrichment results (classification themes with confidence scores, sentiment value, sentiment confidence, severity score, and severity factors) keyed by a deterministic hash of the cleaned feedback text
2. WHEN enriching a FeedbackRecord whose cleaned_text hash matches an existing non-expired cache entry, THE Cache_Layer SHALL return the cached enrichment result without issuing a Gemini API call
3. THE Cache_Layer SHALL accept a configurable time-to-live (TTL) in hours, between 1 and 720 inclusive, defaulting to 24 hours
4. IF the configured TTL value is not an integer or falls outside the inclusive range 1 to 720, THEN THE Cache_Layer SHALL reject the configuration at startup and report a configuration error identifying the invalid TTL value
5. WHEN a cached enrichment result has exceeded its TTL, THE Cache_Layer SHALL discard the stale entry and the Enrichment_Engine SHALL issue a fresh Gemini API call
6. THE Cache_Layer SHALL use the same Persistence_Store backend as batch persistence for storing cached entries
7. IF the Cache_Layer is disabled by configuration, THEN THE Enrichment_Engine SHALL bypass caching and call the Gemini API for every record
8. IF the Persistence_Store is unavailable or a cache read or write operation fails, THEN THE Enrichment_Engine SHALL proceed as if no cache entry exists, issue a Gemini API call for the affected FeedbackRecord, and record a cache-failure note identifying the affected FeedbackRecord
9. FOR ALL FeedbackRecords, enriching from a valid (non-expired) cache entry SHALL produce classification, sentiment, and severity results identical to the original enrichment that populated the cache (round-trip property)

### Requirement 3: Trend Detection — Theme Frequency

**User Story:** As a telecom operations manager, I want to detect themes whose frequency has spiked recently compared to a historical baseline, so that emerging issues are identified before they escalate.

#### Acceptance Criteria

1. WHEN requested, THE Trend_Detector SHALL compare theme frequency distributions between a Baseline_Window and a Current_Window drawn from persisted batch data
2. WHEN computing theme frequency, THE Trend_Detector SHALL count each record once per distinct theme assigned to it (a record with multiple themes contributes one count to each theme) and divide by the total number of records in that window to produce relative frequency
3. THE Trend_Detector SHALL identify themes whose relative frequency in the Current_Window exceeds the Baseline_Window frequency by at least a configurable spike threshold expressed as a relative percentage increase ((current − baseline) / baseline × 100), defaulting to 50 percent, with the threshold configurable between 1 and 1000 inclusive
4. IF a theme appears in the Current_Window but has zero occurrences in the Baseline_Window, THEN THE Trend_Detector SHALL include it in the TrendReport as a new-theme spike with baseline frequency of 0 and percentage increase reported as "new"
5. THE Trend_Detector SHALL include each identified theme spike in the TrendReport with the theme label, baseline frequency, current frequency, and computed percentage increase, ordered by percentage increase descending
6. IF fewer than 10 records exist in either the Baseline_Window or Current_Window, THEN THE Trend_Detector SHALL return an empty TrendReport with an insufficient-data note rather than producing unreliable statistics
7. THE Trend_Detector SHALL accept Baseline_Window and Current_Window as start and end timestamps in ISO 8601 format
8. IF the Baseline_Window or Current_Window has a start timestamp equal to or later than its end timestamp, or if the two windows overlap, THEN THE Trend_Detector SHALL reject the request with an error indication describing the invalid window configuration

### Requirement 4: Trend Detection — Sentiment and Severity

**User Story:** As a telecom operations manager, I want to detect shifts in overall sentiment and severity trends, so that system-wide deterioration in customer experience is surfaced promptly.

#### Acceptance Criteria

1. WHEN requested, THE Trend_Detector SHALL compute the proportion of negative, neutral, and positive sentiment records in both the Baseline_Window and Current_Window, expressing each proportion as a value between 0.0 and 1.0 inclusive
2. WHEN the proportion of negative sentiment in the Current_Window exceeds the Baseline_Window proportion by at least the configured sentiment shift threshold (between 1 and 50 percentage points inclusive, defaulting to 15 percentage points), THE Trend_Detector SHALL identify a sentiment shift
3. WHEN requested, THE Trend_Detector SHALL compute the mean severity score across all records in both the Baseline_Window and Current_Window, where severity is on the 1–5 integer scale
4. WHEN the mean severity in the Current_Window exceeds the Baseline_Window mean by at least the configured severity escalation threshold (between 0.5 and 4.0 points inclusive, defaulting to 1.0 points on the 1–5 scale), THE Trend_Detector SHALL identify a severity escalation
5. THE Trend_Detector SHALL include each identified sentiment shift in the TrendReport with the baseline negative proportion, current negative proportion, and the difference in percentage points; and each identified severity escalation with the baseline mean severity, current mean severity, and the difference in points
6. IF fewer than 10 records exist in either window, THEN THE Trend_Detector SHALL return no trend findings for that metric and include an insufficient-data note identifying which window lacked sufficient records
7. IF a record in either window has no sentiment value or no severity score, THEN THE Trend_Detector SHALL exclude that record from the respective metric computation without affecting the other metric

### Requirement 5: Language Detection

**User Story:** As a pipeline operator serving international customers, I want the pipeline to identify the language of incoming feedback, so that enrichment can account for the text language and results are traceable by language.

#### Acceptance Criteria

1. WHEN a FeedbackRecord enters the enrichment stage, THE Language_Detector SHALL identify the natural language of the cleaned_text and record it as an ISO 639-1 language code
2. THE Language_Detector SHALL support at least English, Spanish, French, German, and Portuguese
3. THE Language_Detector SHALL assign a detection confidence score between 0.0 and 1.0 inclusive for the identified language and SHALL record that confidence score on the InsightRecord metadata alongside the detected language code
4. IF the Language_Detector cannot determine the language with a confidence of at least 0.6, OR the highest-confidence detected language is not in the supported language set, THEN THE Language_Detector SHALL set the language code to English ("en"), assign the actual computed confidence score, and record a language-detection-uncertain note on the InsightRecord
5. THE Language_Detector SHALL record the detected language code and the detection confidence score on the InsightRecord metadata so downstream consumers can filter or group by language

### Requirement 6: Language-Aware Enrichment

**User Story:** As a pipeline operator, I want classification, sentiment, and severity enrichment to account for the detected language, so that non-English feedback is analyzed correctly using language-appropriate model prompts.

#### Acceptance Criteria

1. IF the detected language is not English, THEN THE Enrichment_Engine SHALL include the detected language name in the Gemini system instruction for classification, sentiment, and severity requests, instructing the model that the input text is in the specified language and that all output labels must be in English
2. IF the detected language is English, THEN THE Enrichment_Engine SHALL issue the Gemini system instruction without a language-override clause
3. THE Enrichment_Engine SHALL produce classification results using only theme labels from the configured English-language theme set regardless of the input language, such that a non-English input never produces a translated or transliterated theme label
4. THE Enrichment_Engine SHALL produce sentiment values only from the set (positive, neutral, negative) regardless of input language, such that a non-English input never produces a translated sentiment label
5. THE Enrichment_Engine SHALL produce severity scores on the same 1-5 integer scale regardless of input language
6. IF the Enrichment_Engine receives a Gemini response containing a theme label not in the configured theme set, or a sentiment value not in the set (positive, neutral, negative), or a severity score outside the 1-5 integer range, THEN THE Enrichment_Engine SHALL apply the same validation and rejection rules defined in the classification, sentiment, and severity requirements regardless of the detected language
7. WHEN the Cache_Layer is enabled, THE Cache_Layer SHALL include the detected ISO 639-1 language code in the cache key so that identical text processed under different language contexts produces separate cache entries
