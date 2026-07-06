# Implementation Plan: NLP Feedback Routing

## Overview

This plan implements an NLP-powered customer feedback processing and routing system extending the existing `nlp_processing` package. The implementation follows the layered pipeline architecture: Data Ingestion → Preprocessing → NLP Processing → Decision Engine → Persistence, with full ticket lifecycle management, trend detection, and deterministic serialization. All code uses Python with Pydantic v2 models, SQLite with WAL mode, Google Gemini API for NLP inference, and Hypothesis for property-based testing.

## Tasks

- [x] 1. Define core enumerations, data models, and database schema
  - [x] 1.1 Create feedback routing enumerations and Pydantic models
    - Create `nlp_processing/models/feedback_routing.py` with all Literal type enumerations (ThemeCategory, IntentType, TicketPhase, RoutingDepartment, RoutingAction, ProcessingStatus, ClusterStatus, ResolutionType)
    - Implement Pydantic v2 models: SocialFeedback, WidgetFeedback, CanonicalFeedback, EngagementMetrics, FeedbackAnalysis, ExtractedEntity, Ticket, ClusterRecord, RoutingDecision, PriorityResult, SentimentResult, ThemeResult, IntentResult
    - Enforce all Field constraints (ge, le, max_length, min_length) per design specification
    - _Requirements: 1.1, 2.1, 3.1, 4.1, 4.2, 5.1, 7.1, 7.8, 8.1, 9.1, 17.1, 18.1, 19.1, 20.1, 21.1_

  - [x] 1.2 Create database schema migration for feedback routing tables
    - Create `nlp_processing/persistence/feedback_schema.py` with DDL for feedback, feedback_analysis, tickets, feedback_ticket_link, and clusters tables
    - Include all CHECK constraints, foreign keys, indexes (idx_feedback_ingested_at, idx_feedback_analysis_processed_at, idx_tickets_dept_phase)
    - Implement `initialize_feedback_schema(conn)` function that creates tables if not exist
    - Ensure WAL mode is set on connection initialization
    - _Requirements: 17.1, 17.2, 17.3, 17.5, 18.1, 18.2, 18.3, 18.4, 18.6, 19.1, 19.2, 19.4, 19.5, 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 21.1, 21.2, 21.3_

  - [x] 1.3 Implement FeedbackStore persistence layer
    - Create `nlp_processing/persistence/feedback_store.py` with FeedbackStore class
    - Implement `insert_feedback()`, `insert_analysis()`, `insert_ticket()`, `link_feedback_ticket()`, `insert_cluster()`, `update_cluster()`
    - Implement `transition_ticket_phase()` with valid transition matrix enforcement and audit trail recording
    - Implement constraint violation handling with specific error messages for each constraint type
    - Implement cascade delete behavior via ON DELETE CASCADE
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 17.2, 17.3, 17.6, 17.7, 18.2, 18.3, 18.4, 18.5, 19.3, 19.5, 19.6, 20.2, 20.4, 21.3, 21.4, 21.5_

  - [x]* 1.4 Write property test for ticket phase transition validity (Property 13)
    - **Property 13: Ticket Phase Transition Validity**
    - Generate all (current_phase, next_phase) pairs from TicketPhase enum, verify only valid transitions accepted
    - Verify transitions from "closed" and "auto_closed" are always rejected
    - **Validates: Requirements 15.1, 15.2, 15.7**

- [x] 2. Implement data ingestion layer
  - [x] 2.1 Implement Social Listener ingestion service
    - Create `nlp_processing/ingestion/social_listener.py` with SocialListener class
    - Implement `ingest_social(post_data: dict) -> SocialFeedback | None`
    - Implement recency_score calculation: `max(0.0, 1.0 - (elapsed_hours / 720))`
    - Implement validation: discard posts with message_text < 3 chars, truncate to 10000 chars
    - Implement engagement_metrics extraction (likes, replies, reposts/upvotes)
    - Implement location extraction from geotag when available
    - Implement rate limit retry with exponential backoff (30s initial, 15m max, 10 consecutive failure stop)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 2.2 Implement Widget Intake ingestion service
    - Create `nlp_processing/ingestion/widget_intake.py` with WidgetIntake class
    - Implement `ingest_widget(submission: dict) -> WidgetFeedback | ValidationError`
    - Implement validation: reject empty/whitespace message_text, reject > 10000 chars, reject missing consent_to_contact, reject invalid selected_category
    - Store optional fields (customer_id, account_type, location, etc.)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x]* 2.3 Write property test for recency score formula (Property 1)
    - **Property 1: Recency Score Formula Correctness**
    - Generate random (created_at_original, ingested_at) timestamp pairs where ingested_at >= created_at_original
    - Verify computed score equals `max(0.0, 1.0 - (elapsed_hours / 720))` and is always in [0.0, 1.0]
    - **Validates: Requirements 1.2**

- [x] 3. Implement preprocessing and standardization layer
  - [x] 3.1 Implement Preprocessor with text cleaning
    - Create `nlp_processing/preprocessing/preprocessor.py` with Preprocessor class
    - Implement `clean_text()`: HTML tag removal, Unicode NFC normalization, whitespace collapse, trim
    - Implement `detect_language()`: return ISO 639-1 code, "und" for < 3 chars or low confidence
    - Implement `mask_pii()`: regex patterns for email, phone, SSN → placeholder tokens ("[EMAIL]", "[PHONE]", "[SSN]"), preserve original in separate field
    - Implement `check_duplicate()`: case-insensitive match on cleaned_text from same source within 24h window, increment duplicate_count
    - Implement profanity detection flag (check against configured word list)
    - Implement `preprocess()`: orchestrate all steps, produce CanonicalFeedback, mark "failed" if empty after cleaning
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11_

  - [x]* 3.2 Write property test for text cleaning invariants (Property 2)
    - **Property 2: Text Cleaning Invariants**
    - Generate strings with HTML tags, unicode variants, mixed whitespace
    - Verify: no HTML tags in output, output is NFC, no consecutive whitespace in interior, no leading/trailing whitespace
    - **Validates: Requirements 3.2**

  - [x]* 3.3 Write property test for PII masking round-trip (Property 3)
    - **Property 3: PII Masking Round-Trip**
    - Generate text with embedded email/phone/SSN patterns
    - Verify masked output contains placeholder tokens AND preserved original allows exact reconstruction
    - **Validates: Requirements 3.6**

  - [x]* 3.4 Write property test for deduplication detection (Property 4)
    - **Property 4: Deduplication Detection**
    - Generate duplicate submissions (same cleaned_text, same source, within 24h)
    - Verify second submission is discarded and original's duplicate_count increments by 1
    - **Validates: Requirements 3.5**

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement NLP processing layer
  - [x] 5.1 Implement Sentiment Analyzer
    - Create `nlp_processing/enrichment/sentiment_routing.py` with SentimentAnalyzer class
    - Implement `analyze(feedback: CanonicalFeedback) -> SentimentResult`
    - Implement short-text sentinel: < 5 chars → neutral/0.0 without model call
    - Implement label/score consistency enforcement: > 0.2 → positive, < -0.2 → negative, else neutral (override model label)
    - Implement error fallback: neutral/0.0 on model error or timeout
    - Use existing GeminiClient for inference
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x]* 5.2 Write property test for sentiment label-score consistency (Property 5)
    - **Property 5: Sentiment Label-Score Consistency**
    - Generate sentiment_score values in [-1.0, +1.0]
    - Verify label assignment: > 0.2 → "positive", < -0.2 → "negative", else "neutral"
    - **Validates: Requirements 4.5**

  - [x]* 5.3 Write property test for short text sentinel behavior (Property 6)
    - **Property 6: Short Text Sentinel Behavior**
    - Generate strings of 0-4 characters
    - Verify SentimentAnalyzer returns "neutral" and 0.0 without model invocation
    - **Validates: Requirements 4.4**

  - [x] 5.4 Implement Theme Detector
    - Create `nlp_processing/enrichment/theme_detector.py` with ThemeDetector class
    - Implement `detect(feedback: CanonicalFeedback) -> ThemeResult`
    - Return primary_theme and optional secondary_theme from ThemeCategory set
    - Assign "unclassified" when confidence < 0.3
    - Weight customer-provided selected_category alongside NLP classification
    - Use existing GeminiClient for inference
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 5.5 Implement Intent Classifier
    - Create `nlp_processing/enrichment/intent_classifier.py` with IntentClassifier class
    - Implement `classify(feedback: CanonicalFeedback) -> IntentResult`
    - Assign exactly one intent from IntentType set
    - Assign "unclassified" when confidence <= 0.4
    - Set requires_action=true for {complaint, request_for_help, outage_report, billing_dispute, cancellation_risk}
    - Set requires_action=false for {feature_suggestion, praise, unclassified}
    - Implement 10-second timeout with fallback to unclassified/false
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [x]* 5.6 Write property test for intent to requires_action mapping (Property 9)
    - **Property 9: Intent to Requires-Action Mapping**
    - Generate all valid intent values
    - Verify requires_action mapping: {complaint, request_for_help, outage_report, billing_dispute, cancellation_risk} → true; {feature_suggestion, praise, unclassified} → false
    - **Validates: Requirements 8.4, 8.5**

  - [x] 5.7 Implement Entity Extractor
    - Create `nlp_processing/enrichment/entity_extractor.py` with EntityExtractor class
    - Implement `extract(feedback: CanonicalFeedback) -> list[ExtractedEntity]`
    - Extract entity types: service_area, product_name, time_reference, dollar_amount, equipment_name, outage_mention, competitor_mention
    - Enforce max 50 entities, confidence >= 0.5 threshold, entity_value max 200 chars
    - Normalize dollar_amount to 2 decimal places, discard unparseable amounts
    - Implement 30-second timeout with fallback to empty list + "failed" status
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [x] 5.8 Implement Priority Scorer
    - Create `nlp_processing/enrichment/priority_scorer.py` with PriorityScorer class
    - Implement `score(feedback: CanonicalFeedback, analysis: FeedbackAnalysis) -> PriorityResult`
    - Implement precedence evaluation: critical → high → medium → low
    - Critical: outage keywords + sentiment < -0.7 OR escalation language
    - High: sentiment < -0.5 OR cluster volume > 10
    - Medium: sentiment in [-0.5, -0.2) OR intent in {request_for_help, billing_dispute}
    - Low: all else
    - Enforce priority_score within level range: critical 0.75–1.0, high 0.50–0.74, medium 0.25–0.49, low 0.0–0.24
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_

  - [x]* 5.9 Write property test for priority level precedence rules (Property 7)
    - **Property 7: Priority Level Follows Precedence Rules**
    - Generate FeedbackAnalysis with various signal combinations (sentiment scores, cluster volumes, keywords, intents)
    - Verify highest applicable priority level is assigned in descending order
    - **Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6**

  - [x]* 5.10 Write property test for priority score-level range consistency (Property 8)
    - **Property 8: Priority Score-Level Range Consistency**
    - Generate priority computation results
    - Verify numeric priority_score falls within: critical 0.75–1.0, high 0.50–0.74, medium 0.25–0.49, low 0.0–0.24
    - **Validates: Requirements 7.8**

  - [x] 5.11 Implement Similarity Clusterer
    - Create `nlp_processing/aggregation/similarity_clusterer.py` with SimilarityClusterer class
    - Implement `assign_cluster(feedback: CanonicalFeedback, analysis: FeedbackAnalysis) -> str`
    - Implement weighted similarity: text similarity + shared theme + geographic proximity (50km)
    - Create new cluster if no match > 0.7; assign to highest-scoring match otherwise
    - Update cluster volume_count, last_seen_at on assignment
    - Update cluster_summary on 20% volume growth
    - Upgrade cluster priority_level to "high" when volume > 20
    - Only match against "active" or "monitoring" clusters
    - Exclude geographic factor when location data is absent
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement decision engine
  - [x] 7.1 Implement Decision Engine core with evaluation order
    - Create `nlp_processing/routing/decision_engine.py` with DecisionEngine class
    - Implement `evaluate(feedback: CanonicalFeedback, analysis: FeedbackAnalysis) -> RoutingDecision`
    - Implement evaluation order: `_check_escalation()` → `_check_route_to_existing()` → `_check_create_ticket()` → `_check_auto_resolve()`
    - Stop at first matching rule (short-circuit)
    - Implement fallback: create_ticket, priority "medium", department "Customer_Care" when no rules match or when NLP fields are missing/invalid
    - Record evaluation_timestamp on routing decision
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9_

  - [x] 7.2 Implement escalation logic
    - Implement `_check_escalation()` in DecisionEngine
    - Check criteria: priority_level "critical", legal/regulatory keywords (case-insensitive: "lawyer", "attorney", "lawsuit", "fcc", "regulatory", "legal action", "class action"), high_value account with 3+ open tickets, viral social post (engagement > 1000)
    - Create single Ticket with priority "critical", department "Executive_Escalations", phase "new"
    - Create feedback_ticket_link, produce exactly one ticket regardless of how many criteria match
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7_

  - [x] 7.3 Implement route-to-existing logic
    - Implement `_check_route_to_existing()` in DecisionEngine
    - Check if feedback's cluster has an existing open ticket (phase not resolved/closed/auto_closed)
    - Link to most recently updated open ticket when multiple exist
    - Update existing ticket's updated_at timestamp
    - Do NOT create a new ticket
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [x] 7.4 Implement create-ticket logic with department mapping
    - Implement `_check_create_ticket()` in DecisionEngine
    - Trigger when requires_action=true and priority "medium" or "high"
    - Apply department mapping: theme/intent → department per mapping table
    - Apply social engagement override (> 100 → Social_Media_Care)
    - Fallback to Customer_Care for unclassified theme + unmapped intent
    - Create Ticket with phase "new", create feedback_ticket_link
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7_

  - [x] 7.5 Implement auto-resolve logic
    - Implement `_check_auto_resolve()` in DecisionEngine
    - Check criteria: duplicate (duplicate_count > 0) → "duplicate", praise + low + no action → "no_action_required", cluster all tickets resolved → "known_resolved", FAQ match + low + request_for_help → "faq_matched"
    - Default fallback (no other rule matches): auto_resolve with "no_action_required"
    - Create Ticket with phase "auto_closed" + resolution_type, create feedback_ticket_link
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [x]* 7.6 Write property test for decision engine evaluation order (Property 10)
    - **Property 10: Decision Engine Evaluation Order**
    - Generate FeedbackAnalysis matching multiple rules simultaneously
    - Verify highest-priority rule wins: escalate > route_to_existing > create_ticket > auto_resolve
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5**

  - [x]* 7.7 Write property test for department assignment mapping (Property 11)
    - **Property 11: Department Assignment Mapping**
    - Generate (primary_theme, intent, source_type, engagement_metrics) combinations
    - Verify correct department: social engagement > 100 overrides; theme precedence over intent; Customer_Care fallback
    - **Validates: Requirements 13.3, 13.4, 13.6**

  - [x]* 7.8 Write property test for escalation produces single critical ticket (Property 12)
    - **Property 12: Escalation Produces Single Critical Ticket**
    - Generate feedback matching multiple escalation criteria simultaneously
    - Verify exactly one Ticket with priority "critical", department "Executive_Escalations", exactly one feedback_ticket_link
    - **Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7**

- [x] 8. Implement pipeline orchestration
  - [x] 8.1 Implement Pipeline Orchestrator
    - Create `nlp_processing/routing/pipeline_orchestrator.py` with PipelineOrchestrator class
    - Implement `process_feedback(feedback: SocialFeedback | WidgetFeedback) -> ProcessingResult`
    - Orchestrate stages in order: ingestion → preprocessing → NLP analysis → decision routing
    - Track ProcessingStatus through stages: ingested → preprocessing → preprocessed → analyzing → analyzed → routing → routed
    - Implement retry logic: 3 attempts, exponential backoff (5s, 10s, 20s, max 60s)
    - Implement 120-second total timeout per record
    - Implement per-record isolation: one failure does not block others
    - Persist final results to FeedbackStore on "routed" status
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7_

- [x] 9. Implement trend detection and cluster lifecycle
  - [x] 9.1 Implement Trend Detector
    - Create `nlp_processing/trends/feedback_trends.py` with TrendDetector class
    - Implement volume spike detection: theme volume > 2x rolling 7-day average (require 7+ days of data)
    - Implement sentiment trend computation for clusters with 20+ records: compare avg of 10 most recent vs 10 oldest, > 0.1 diff → improving/deteriorating, else stable
    - Set sentiment_trend to "stable" for clusters with < 20 records
    - Implement cluster lifecycle evaluation: active → monitoring after 7 days no activity, monitoring → resolved after 21 days total
    - Implement theme frequency distribution over configurable window (1–90 days, default 7)
    - Implement new cluster emergence rate tracking
    - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5, 22.6, 22.7, 22.8_

  - [x]* 9.2 Write property test for cluster sentiment trend computation (Property 14)
    - **Property 14: Cluster Sentiment Trend Computation**
    - Generate clusters with known sentiment scores (>= 20 records)
    - Verify: recent avg > oldest avg + 0.1 → "improving"; oldest avg > recent avg + 0.1 → "deteriorating"; else "stable"
    - Verify clusters with < 20 records always get "stable"
    - **Validates: Requirements 22.3, 22.4**

  - [x]* 9.3 Write property test for cluster lifecycle transitions (Property 15)
    - **Property 15: Cluster Lifecycle Transitions**
    - Generate clusters with various last_seen_at timestamps relative to evaluation time
    - Verify: active + 7 days no activity → monitoring; monitoring + 21 days total → resolved
    - **Validates: Requirements 22.7, 22.8**

- [x] 10. Implement serialization for feedback routing
  - [x] 10.1 Implement FeedbackAnalysis serializer
    - Create `nlp_processing/serialization/feedback_serializer.py` with FeedbackAnalysisSerializer class
    - Implement `serialize(record: FeedbackAnalysis) -> str`: sorted keys, compact separators, 6-decimal float precision
    - Implement `deserialize(json_str: str) -> FeedbackAnalysis`: validate all constraints (scores in range, enums valid, timestamp format)
    - Reject malformed JSON with parsing error
    - Reject records violating schema constraints with field-specific validation error
    - _Requirements: 23.1, 23.2, 23.3, 23.4, 23.5, 23.6_

  - [x]* 10.2 Write property test for serialization round-trip fidelity (Property 16)
    - **Property 16: Serialization Round-Trip Fidelity**
    - Generate valid FeedbackAnalysis records via Hypothesis
    - Verify serialize → deserialize produces identical record (floats within 6-decimal precision)
    - **Validates: Requirements 23.6**

  - [x]* 10.3 Write property test for serialization determinism (Property 17)
    - **Property 17: Serialization Determinism**
    - Generate valid FeedbackAnalysis records
    - Verify serializing twice produces byte-for-byte identical JSON output
    - **Validates: Requirements 23.2**

- [x] 11. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Create shared Hypothesis strategies and wire integration
  - [x] 12.1 Create shared Hypothesis strategies module
    - Create `tests/feedback_routing/strategies.py` with reusable generators
    - Implement strategies for: theme_categories, intent_types, sentiment_scores, priority_scores, valid FeedbackAnalysis records, CanonicalFeedback records, timestamp pairs, TicketPhase pairs
    - Configure `@settings(max_examples=100)` for all property tests
    - Tag each test with `# Feature: nlp-feedback-routing, Property N: <description>`
    - _Requirements: All (testing infrastructure)_

  - [x] 12.2 Wire all components together in pipeline integration
    - Update `nlp_processing/__init__.py` to export new modules
    - Create `nlp_processing/routing/__init__.py` package
    - Create `nlp_processing/ingestion/__init__.py` package (if not exists)
    - Create `nlp_processing/preprocessing/__init__.py` package
    - Wire IngestionService → Preprocessor → NLP components → DecisionEngine → FeedbackStore in PipelineOrchestrator
    - Ensure database schema is initialized on first use
    - _Requirements: 16.1, 16.7_

  - [x]* 12.3 Write integration tests for end-to-end pipeline
    - Create `tests/feedback_routing/test_pipeline_integration.py`
    - Test full flow: social post → preprocessing → NLP → decision → ticket
    - Test full flow: widget submission → preprocessing → NLP → decision → ticket
    - Test retry and timeout behavior across stages
    - Test per-record isolation (one failure doesn't block others)
    - _Requirements: 16.1, 16.3, 16.4, 16.5, 16.6_

  - [x]* 12.4 Write unit tests for database schema constraints
    - Create `tests/feedback_routing/test_schema_constraints.py`
    - Test all CHECK constraints on each table (enum values, score ranges, length limits)
    - Test foreign key enforcement (cluster_id, feedback_id, ticket_id references)
    - Test cascade delete behavior on feedback_ticket_link
    - Test duplicate feedback_id rejection
    - _Requirements: 17.2, 17.3, 17.6, 18.2, 18.3, 18.4, 18.5, 19.5, 19.6, 20.2, 20.4, 20.5, 20.6, 21.2, 21.3, 21.5_

- [x] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties defined in the design (17 total)
- Unit tests validate specific examples and edge cases
- The design uses Python with Pydantic v2 — all code examples and implementations use this language
- Existing patterns: GeminiClient (transport/client.py), PersistenceStore (persistence/store.py), ResponseSerializer (serialization/serializer.py), TrendDetector (trends/detector.py)
- New packages to create: `nlp_processing/routing/`, `nlp_processing/ingestion/`, `nlp_processing/preprocessing/`
- Test directory: `tests/feedback_routing/` for all new test files

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "12.1"] },
    { "id": 2, "tasks": ["1.4", "2.1", "2.2"] },
    { "id": 3, "tasks": ["2.3", "3.1"] },
    { "id": 4, "tasks": ["3.2", "3.3", "3.4", "5.1"] },
    { "id": 5, "tasks": ["5.2", "5.3", "5.4", "5.5", "5.7"] },
    { "id": 6, "tasks": ["5.6", "5.8", "5.11"] },
    { "id": 7, "tasks": ["5.9", "5.10", "7.1"] },
    { "id": 8, "tasks": ["7.2", "7.3", "7.4", "7.5"] },
    { "id": 9, "tasks": ["7.6", "7.7", "7.8", "8.1"] },
    { "id": 10, "tasks": ["9.1", "10.1"] },
    { "id": 11, "tasks": ["9.2", "9.3", "10.2", "10.3"] },
    { "id": 12, "tasks": ["12.2"] },
    { "id": 13, "tasks": ["12.3", "12.4"] }
  ]
}
```
