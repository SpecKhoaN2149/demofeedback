# Implementation Plan: NLP Feedback Processing

## Overview

This plan implements the NLP processing layer in Python 3.11+ using `google-genai`, `pydantic` v2, and `Hypothesis`. Work proceeds bottom-up: project scaffolding and data models first, then the pure-logic layers (ingestion, parsing/serialization, clustering, prioritization) that can be property-tested without a network, then the transport layer (`Gemini_Client`) and enrichment components (classifier, sentiment, severity) against a mocked Gemini API, and finally the batch orchestrator that wires everything together and assembles schema-conforming output.

Each correctness property from the design maps to exactly one Hypothesis property-based test (minimum 100 iterations, tagged `Feature: nlp-feedback-processing, Property N`). Property and test sub-tasks are placed next to the implementation they validate to catch errors early. Test sub-tasks are marked optional with `*`.

## Tasks

- [x] 1. Set up project structure, configuration, and core data models
  - [x] 1.1 Create project skeleton and dependencies
    - Create package directory structure (e.g. `nlp_processing/` with `models/`, `transport/`, `enrichment/`, `aggregation/`, `serialization/`, `config.py`) and a `tests/` tree
    - Add `pyproject.toml` declaring Python 3.11+, `google-genai`, `pydantic>=2`, and `hypothesis` (test dependency); configure `pytest`
    - Add a `tests/strategies.py` placeholder module for shared Hypothesis strategies
    - _Requirements: 2.3_

  - [x] 1.2 Implement core pydantic data models
    - Define `SourceChannel`, `ThemeLabel`, `SentimentValue` literals and the configured theme set
    - Implement `RawFeedback`, `FeedbackRecord`, `ThemeAssignment`, `SeverityFactor`, `InsightRecord`, `Cluster`, `FailureEntry`, `BatchSummary`, and `BatchOutput` with field types and range constraints (confidence 0.0–1.0, severity 1–5, label ≤120 chars, factor 1–500 chars)
    - _Requirements: 1.1, 4.3, 5.3, 6.2, 7.2, 8.2_

  - [x] 1.3 Implement configuration validation with fail-fast startup
    - Implement a `Config` loader/validator for `api_key`, `model_name`, `max_attempts` (1–10, default 5), `request_timeout_seconds` (1–120, default 30), `similarity_threshold` (0.0–1.0), `review_threshold` (0.0–1.0, default 0.70), and `theme_set`
    - Raise configuration errors that stop initialization before any record is processed, identifying the offending value by name only (never the key value)
    - _Requirements: 2.2, 2.4_

  - [ ]* 1.4 Write unit/edge tests for configuration startup
    - Missing/empty/whitespace API key and model name at startup are rejected (Req 2.2, 2.4)
    - `max_attempts`, `timeout`, and threshold out-of-range values are rejected
    - Startup smoke test: processor initializes with valid config, refuses without it
    - _Requirements: 2.2, 2.4_

- [x] 2. Implement Ingestion_Component
  - [x] 2.1 Implement batch ingestion and normalization
    - Reject the whole batch when `len(raw_items) > 1000` with a batch-size validation error; process nothing
    - Assign a unique identifier to every item up front, including rejected ones
    - Trim only leading/trailing whitespace (space, tab, CR, LF), preserving interior characters
    - Reject empty/whitespace-only text, out-of-set `source_channel`, and cleaned text > 10,000 chars, each producing a validation error keyed by the assigned id and no `Feedback_Record`
    - Copy original metadata unchanged onto the `Feedback_Record`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [ ]* 2.2 Add `raw_feedback()` Hypothesis strategy
    - Generate valid and invalid channels, text with controllable surrounding whitespace and length near the 10,000 boundary, and arbitrary metadata
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [ ]* 2.3 Write property test for ingestion identity preservation
    - **Property 1: Ingestion preserves identity, channel, and metadata**
    - **Validates: Requirements 1.1, 1.5**

  - [ ]* 2.4 Write property test for whitespace trimming
    - **Property 2: Whitespace trimming preserves interior content**
    - **Validates: Requirements 1.2**

  - [ ]* 2.5 Write property test for invalid-item rejection
    - **Property 3: Invalid items are rejected with an error and no record**
    - **Validates: Requirements 1.3, 1.4**

  - [ ]* 2.6 Write edge/boundary tests for ingestion limits
    - Batch size at 1000 / 1001 (Req 1.6); cleaned text length at 10000 / 10001 (Req 1.7)
    - _Requirements: 1.6, 1.7_

- [x] 3. Implement Response_Parser and Response_Serializer
  - [x] 3.1 Implement strict Response_Parser
    - Parse JSON and validate every required field, type, and range against the pydantic enrichment schema
    - On invalid JSON, missing required field, or out-of-range/wrong-type value, record a parse error keyed by `record_id` and produce no partial object (all-or-nothing)
    - _Requirements: 4.1, 4.2_

  - [x] 3.2 Implement canonical Response_Serializer
    - Serialize only schema-valid, complete `Insight_Record`s; invalid/incomplete records produce a serialization error keyed by id and no output
    - Produce canonical JSON: lexicographically sorted keys, normalized whitespace, stable number formatting
    - Implement `serialize_batch` for the published `BatchOutput` schema
    - _Requirements: 4.3, 4.4_

  - [ ]* 3.3 Add `enrichment_response()` and `insight_record()` Hypothesis strategies
    - `enrichment_response()`: valid and malformed Gemini JSON (bad syntax, dropped required fields, out-of-range values, unknown themes, omitted sentiment/severity)
    - `insight_record()`: valid insights for round-trip; invalid/incomplete insights for rejection
    - _Requirements: 4.2, 4.4, 4.5, 4.6_

  - [ ]* 3.4 Write property test for strict parsing
    - **Property 8: Strict parsing rejects invalid responses with no partial output**
    - **Validates: Requirements 4.2**

  - [ ]* 3.5 Write property test for serializer rejection
    - **Property 9: Serializer rejects invalid insights**
    - **Validates: Requirements 4.4**

  - [ ]* 3.6 Write property test for insight round-trip
    - **Property 10: Insight serialization round-trip**
    - **Validates: Requirements 4.1, 4.3, 4.5**

  - [ ]* 3.7 Write property test for JSON normalization round-trip
    - **Property 11: JSON normalization round-trip**
    - **Validates: Requirements 4.6**

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement Clustering_Component
  - [x] 5.1 Implement clustering partition logic
    - Partition input into mutually exclusive clusters; every input record in exactly one cluster
    - Produce a non-empty representative label ≤ 120 chars derived from member text per cluster
    - Place records whose similarity STRICTLY EXCEEDS the threshold in the same cluster; a record whose similarity to every other record does not strictly exceed the threshold (including similarity exactly equal to the threshold) becomes a singleton
    - Empty input produces zero clusters but still produces clustering output
    - Use cosine similarity over embeddings with agglomerative grouping, and a deterministic local-embedding fallback so clustering never aborts the batch
    - In any merge post-processing step, preserve the strict-exceeds invariant: every pair whose similarity strictly exceeds the threshold stays in the same cluster, and equality-at-threshold never forces a merge
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [ ]* 5.2 Add `record_set_with_similarity()` Hypothesis strategy
    - Generate record sets with a controllable pairwise similarity matrix so threshold co-membership is deterministic, including similarity values exactly equal to the threshold and values just above and just below it
    - _Requirements: 8.1, 8.3, 8.4, 8.5, 8.7_

  - [ ]* 5.3 Write property test for covering partition
    - **Property 21: Clustering is a covering partition**
    - **Validates: Requirements 8.1, 8.4**

  - [ ]* 5.4 Write property test for cluster labels
    - **Property 22: Cluster labels are bounded and non-empty**
    - **Validates: Requirements 8.2**

  - [ ]* 5.5 Write property test for similarity co-membership
    - **Property 23: Similarity strictly governs cluster co-membership**
    - Include similarity-exactly-at-threshold cases (must yield singletons) plus just-above (co-cluster) and just-below (singleton), and assert the strict-exceeds invariant holds after merge post-processing
    - **Validates: Requirements 8.3, 8.5, 8.7**

  - [ ]* 5.6 Write edge test for empty clustering input
    - Empty input → zero clusters, valid output (Req 8.6)
    - _Requirements: 8.6_

- [x] 6. Implement Prioritization_Component
  - [x] 6.1 Implement deterministic priority scoring and ranking
    - Compute `priority = max(0, w_sev*sum(severity) + w_vol*count + w_neg*count(negative))` with positive weights; record the score on each cluster
    - Order clusters by descending priority; break ties by higher record count, then ascending cluster label; permit two clusters to carry identical labels and, when score/count/label all tie, preserve their input relative order via a deterministic stable sort
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8_

  - [ ]* 6.2 Add `cluster()` Hypothesis strategy
    - Generate clusters with controllable severity totals, record counts, and negative-sentiment counts
    - _Requirements: 9.1, 9.6, 9.7, 9.8_

  - [ ]* 6.3 Write property test for deterministic non-negative scoring
    - **Property 24: Priority scoring is deterministic and non-negative**
    - **Validates: Requirements 9.1, 9.4, 9.5**

  - [ ]* 6.4 Write property test for ordering and tie-breakers
    - **Property 25: Priority ordering with tie-breakers and stable order for identical labels**
    - Include clusters with identical labels that tie on score and count, asserting the deterministic stable sort preserves their input relative order
    - **Validates: Requirements 9.2, 9.3**

  - [ ]* 6.5 Write property test for monotonicity
    - **Property 26: Priority is monotonic in each contributing factor**
    - **Validates: Requirements 9.6, 9.7, 9.8**

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement Gemini_Client transport layer
  - [x] 8.1 Implement secret redaction utilities
    - Implement a logging filter and error-formatting wrapper that redact the configured API key from any string before it reaches logs or error messages
    - _Requirements: 2.6_

  - [ ]* 8.2 Write property test for API key redaction
    - **Property 4: API key never leaks**
    - **Validates: Requirements 2.6**

  - [x] 8.3 Implement Gemini_Client requests, timeout, and retry/backoff
    - Attach the API key as the auth credential and use the configured model name on every request; instruct the API to return JSON matching the response schema
    - Retry rate-limit (429) and transient server/network errors with exponential backoff `min(60, 2**(n-1))` seconds up to `max_attempts`; resend identical content on retry
    - Do not retry auth errors (401/403): report an auth failure and fail the operation
    - Abort and discard partial response on timeout, recording a timeout error keyed by record id
    - On retry exhaustion, return a failure result for the record so the orchestrator can continue
    - _Requirements: 2.1, 2.3, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 11.1_

  - [ ]* 8.4 Write property test for retry backoff schedule
    - **Property 5: Retry backoff schedule is correct for retryable errors**
    - **Validates: Requirements 3.1, 3.2**

  - [ ]* 8.5 Write property test for identical retry content
    - **Property 6: Retries resend identical content**
    - **Validates: Requirements 3.5**

  - [ ]* 8.6 Write unit tests for transport wiring and fault paths
    - API key attached and configured model used on each request (Req 2.1, 2.3)
    - Auth error → no retry, operation fails (Req 2.5)
    - Timeout → abort, discard partial, timeout error keyed by id (Req 3.3)
    - Request includes the response-schema instruction (Req 4.1, 11.1)
    - _Requirements: 2.1, 2.3, 2.5, 3.3, 4.1, 11.1_

- [x] 9. Implement Classifier
  - [x] 9.1 Implement theme classification logic
    - Build the classification prompt + response schema, call the client, parse via Response_Parser
    - Assign at least one theme from the configured set, each with confidence in 0.0–1.0
    - Assign all themes with confidence ≥ 0.5; if none qualify or model indicates none apply, assign `other`
    - Discard theme labels outside the configured set, falling back to `other` when nothing qualifies
    - On API unavailable / >30s, leave the record unclassified, preserve it unchanged, and attach a classification-failure error
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [ ]* 9.2 Write property test for well-formed classifier output
    - **Property 12: Classifier output is well-formed**
    - **Validates: Requirements 5.1, 5.2, 5.3**

  - [ ]* 9.3 Write property test for theme threshold selection and default
    - **Property 13: Theme threshold selection and default**
    - **Validates: Requirements 5.4, 5.5**

  - [ ]* 9.4 Write property test for discarding unknown themes
    - **Property 14: Unknown themes are discarded**
    - **Validates: Requirements 5.6**

  - [ ]* 9.5 Write unit test for classification unavailability
    - API unavailable/timeout → record preserved unchanged, error attached (Req 5.7)
    - _Requirements: 5.7_

- [x] 10. Implement Sentiment_Analyzer
  - [x] 10.1 Implement sentiment analysis logic
    - Assign exactly one of `positive | neutral | negative` with confidence in 0.0–1.0, recorded on the insight regardless of magnitude
    - On omitted sentiment, default `neutral` and record a missing-sentiment note keyed by record id
    - On out-of-set value or out-of-range confidence, reject the record, produce no `Insight_Record`, and record a sentiment-validation error
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ]* 10.2 Write property test for well-formed sentiment
    - **Property 15: Sentiment is well-formed and always recorded**
    - **Validates: Requirements 6.1, 6.2, 6.3**

  - [ ]* 10.3 Write property test for missing-sentiment default
    - **Property 16: Missing sentiment defaults to neutral with a note**
    - **Validates: Requirements 6.4**

  - [ ]* 10.4 Write property test for invalid-sentiment rejection
    - **Property 17: Invalid sentiment is rejected**
    - **Validates: Requirements 6.5**

- [x] 11. Implement Severity_Scorer
  - [x] 11.1 Implement severity scoring logic
    - Assign exactly one integer 1–5 plus at least one contributing factor (1–500 chars)
    - On omitted severity, default 1 and record a missing-severity note
    - On non-integer or out-of-range value, reject the record, produce no `Insight_Record`, and record a severity-range error
    - On >30s no response, default 1 and record a severity-unavailable note
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ]* 11.2 Write property test for well-formed severity
    - **Property 18: Severity is well-formed**
    - **Validates: Requirements 7.1, 7.2**

  - [ ]* 11.3 Write property test for missing-severity default
    - **Property 19: Missing severity defaults to 1 with a note**
    - **Validates: Requirements 7.3**

  - [ ]* 11.4 Write property test for invalid-severity rejection
    - **Property 20: Invalid severity is rejected**
    - **Validates: Requirements 7.4**

  - [ ]* 11.5 Write unit test for severity timeout default
    - Severity timeout (>30s) → default 1 + severity-unavailable note (Req 7.5)
    - _Requirements: 7.5_

- [x] 12. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Implement Batch_Orchestrator and output assembly
  - [x] 13.1 Implement batch orchestration pipeline
    - Validate batch size: empty or > 10,000 → no insights, batch-validation error naming the violated bound
    - Run ingestion, then per-record enrichment (classification, sentiment, severity) with per-record isolation so one failure never aborts the batch; record `FailureEntry(id, stage, reason)` for failures
    - Mark a record successful only when classification, sentiment, severity, and cluster assignment all complete without error
    - Invoke clustering then prioritization on enriched records
    - _Requirements: 3.4, 10.1, 10.2, 10.5_

  - [x] 13.2 Implement output assembly, review flags, model name, and accuracy
    - Assemble `BatchOutput` with insights, ranked clusters, failures, and a summary where `submitted == successful + failures` and `successful == len(insights)`; always produce output even when zero insights succeed
    - Set the review flag on any insight with a theme/sentiment confidence below `review_threshold`; if a below-threshold score is detected but flagging fails, record a system error and retain the insight unflagged
    - Record the configured Gemini model name on every insight
    - When a ground-truth labeled dataset is supplied, compute classification accuracy as the proportion of records whose assigned themes exactly match the labels (in 0.0–1.0) and include it in the output; omit it otherwise
    - Emit the assembled output as canonical schema-conforming JSON via Response_Serializer
    - _Requirements: 10.3, 10.4, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [ ]* 13.3 Write property test for per-record failure isolation
    - **Property 7: Per-record failures are isolated**
    - **Validates: Requirements 3.4**

  - [ ]* 13.4 Write property test for batch accounting conservation
    - **Property 27: Batch accounting is conserved**
    - **Validates: Requirements 10.1, 10.2, 10.3**

  - [ ]* 13.5 Write property test for output schema conformance
    - **Property 28: Batch output conforms to the published schema**
    - **Validates: Requirements 10.4**

  - [ ]* 13.6 Write property test for review-flag low-confidence behavior
    - **Property 29: Review flag reflects low confidence**
    - **Validates: Requirements 11.2**

  - [ ]* 13.7 Write property test for model name recording
    - **Property 30: Model name is recorded on every insight**
    - **Validates: Requirements 11.4**

  - [ ]* 13.8 Write property test for classification accuracy computation
    - **Property 31: Classification accuracy computation and reporting**
    - **Validates: Requirements 11.5, 11.6**

  - [ ]* 13.9 Write unit/edge tests for orchestrator behavior
    - Processing batch size at 0 / 1 / 10000 / 10001 (Req 10.5)
    - Below-threshold detected but flag-set fails → system error, insight retained unflagged (Req 11.3, fault injection)
    - _Requirements: 10.5, 11.3_

- [x] 14. Integration and final wiring
  - [x] 14.1 Wire the public NLP_Processor entry point
    - Expose `NLPProcessor.process_batch` that validates config at construction and drives ingestion → enrichment → clustering → prioritization → assembly → serialization end to end
    - Ensure all components are constructed from a single validated `Config`
    - _Requirements: 2.2, 2.4, 10.4_

  - [ ]* 14.2 Write integration/smoke tests
    - Startup smoke test: processor initializes with valid config and refuses to start without it
    - Recorded/mock-response end-to-end test exercising one enrichment round-trip (SDK wiring, response-schema request, parse, assemble); a real-API variant gated behind an API-key env var, outside the fast suite
    - _Requirements: 4.1, 10.4, 11.1_

- [x] 15. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP, though they carry the correctness guarantees.
- Each property-based test uses Hypothesis with a minimum of 100 iterations (`@settings(max_examples=100)` or higher) and a tag comment in the format `Feature: nlp-feedback-processing, Property N: {property_text}`.
- The Gemini API is mocked in property and unit tests so iterations are cheap and deterministic; the transport's retry/backoff is tested against a mock that records attempts and delays.
- Each task references specific requirements for traceability; checkpoints ensure incremental validation.
- Pure-logic layers (ingestion, parsing/serialization, clustering, prioritization) are built and property-tested before the network-dependent transport and enrichment layers.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "2.1", "3.1", "3.2", "5.1", "6.1", "8.1"] },
    { "id": 3, "tasks": ["1.4", "2.2", "2.6", "3.3", "5.2", "5.6", "6.2", "8.2", "8.3", "8.4", "8.5"] },
    { "id": 4, "tasks": ["2.3", "2.4", "2.5", "3.4", "3.5", "3.6", "3.7", "5.3", "5.4", "5.5", "6.3", "6.4", "6.5", "9.1", "10.1", "11.1"] },
    { "id": 5, "tasks": ["9.2", "9.3", "9.4", "9.5", "10.2", "10.3", "10.4", "11.2", "11.3", "11.4", "11.5"] },
    { "id": 6, "tasks": ["13.1"] },
    { "id": 7, "tasks": ["13.2"] },
    { "id": 8, "tasks": ["13.3", "13.4", "13.5", "13.6", "13.7", "13.8", "13.9", "14.1"] },
    { "id": 9, "tasks": ["14.2"] }
  ]
}
```
