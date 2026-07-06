# Requirements Document

## Introduction

This document specifies the requirements for an NLP-powered customer feedback processing and routing system. The system ingests customer feedback from two streams (social media scraping and direct widget/form submissions), preprocesses and standardizes input, applies NLP analysis (sentiment, theme detection, clustering, priority scoring, intent detection, entity extraction), routes feedback through a decision engine, and persists all data in a relational model with full ticket lifecycle support. The architecture encompasses five layers: Data Ingestion, Preprocessing/Standardization, NLP Processing, Decision Engine/Routing, and Database Persistence. The system aims to surface the most important customer problems quickly and reduce the need for customers to escalate issues to get resolution.

## Glossary

- **Ingestion_Service**: The backend service responsible for capturing and receiving raw customer feedback from social media sources and direct widget/form submissions.
- **Social_Listener**: The sub-component of the Ingestion_Service that scrapes and captures public feedback from social media platforms (Reddit, X, Facebook) and produces Social_Feedback records.
- **Widget_Intake**: The sub-component of the Ingestion_Service that receives direct customer feedback from app feedback widgets, website forms, and support intake forms, producing Widget_Feedback records.
- **Social_Feedback**: A raw feedback record originating from the Social_Listener, containing platform-specific metadata, engagement metrics, and message text.
- **Widget_Feedback**: A raw feedback record originating from the Widget_Intake, containing customer-provided structured input (category selection) and free-text message.
- **Preprocessor**: The intermediate processing layer that cleans, deduplicates, and standardizes raw feedback from all sources into a unified Canonical_Feedback schema.
- **Canonical_Feedback**: The standardized feedback record produced by the Preprocessor, serving as the uniform input to the NLP_Pipeline.
- **NLP_Pipeline**: The processing layer that applies sentiment analysis, theme detection, similarity clustering, priority scoring, intent detection, and entity extraction to Canonical_Feedback records.
- **Sentiment_Analyzer**: The NLP_Pipeline sub-component that classifies feedback sentiment as positive, neutral, or negative with a numeric score from -1.0 to +1.0.
- **Theme_Detector**: The NLP_Pipeline sub-component that maps feedback to business categories, producing a primary_theme and optional secondary_theme.
- **Similarity_Clusterer**: The NLP_Pipeline sub-component that groups related feedback records into clusters based on content similarity, shared theme, and geographic proximity.
- **Priority_Scorer**: The NLP_Pipeline sub-component that computes a priority level (low, medium, high, critical) based on multiple weighted signals.
- **Intent_Classifier**: The NLP_Pipeline sub-component that classifies the customer intent of a feedback record.
- **Entity_Extractor**: The optional NLP_Pipeline sub-component that identifies named entities within feedback text.
- **Decision_Engine**: The business logic layer that evaluates NLP analysis results and determines the routing action for each feedback record. Evaluates rules in priority order: escalate, route_to_existing, create_ticket, auto_resolve.
- **Routing_Action**: The output decision of the Decision_Engine: auto_resolve, route_to_existing, create_ticket, or escalate.
- **Ticket**: An operational record created by the Decision_Engine for feedback requiring human intervention, with assigned department, priority, and lifecycle phase.
- **Cluster**: An aggregated group of related feedback records sharing common themes or characteristics, used to identify systemic issues such as regional outages or billing confusion patterns.
- **Feedback_Store**: The relational database layer that persists raw feedback, NLP analysis results, tickets, feedback-ticket links, and clusters.
- **Pipeline_Orchestrator**: The coordination layer that manages the end-to-end flow of feedback records through ingestion, preprocessing, NLP analysis, and decision routing stages.
- **Theme_Category**: One of the predefined business categories: outage, billing, speed_performance, installation, technician_visit, support_experience, app_usability, equipment, cancellation_retention.
- **Intent_Type**: One of the predefined intent classifications: complaint, request_for_help, outage_report, billing_dispute, feature_suggestion, praise, cancellation_risk.
- **Ticket_Phase**: One of the lifecycle states a Ticket passes through: new, triaged, routed, in_progress, waiting, resolved, closed, auto_closed.
- **Routing_Department**: One of the departments to which tickets are assigned: Network_Operations, Billing_Support, Technical_Support, Field_Operations, Digital_Product, Customer_Care, Retention, Social_Media_Care, Executive_Escalations.
- **Processing_Status**: The state of a feedback record in the pipeline: ingested, preprocessing, preprocessed, analyzing, analyzed, routing, routed, retrying, failed.

## Requirements

### Requirement 1: Social Media Feedback Ingestion

**User Story:** As a product analyst, I want public customer feedback from social media platforms captured automatically, so that the organization can monitor brand sentiment and respond to issues surfacing online.

#### Acceptance Criteria

1. WHEN the Social_Listener detects a new public post or comment that matches at least one entry in the configured brand keyword list (exact or substring match, case-insensitive) on a monitored platform (Reddit, X, or Facebook), THE Ingestion_Service SHALL create a Social_Feedback record containing feedback_id (UUID), source_type set to "social", platform identifier, username_handle (maximum 320 characters), post_id or comment_id, message_text (truncated to a maximum of 10,000 characters if longer), post_url (when available), created_at_original (original post timestamp in ISO 8601 UTC), ingested_at (current timestamp in ISO 8601 UTC), language code, and engagement_metrics (likes, replies, reposts or upvotes as integer values).
2. THE Ingestion_Service SHALL assign a recency_score between 0.0 and 1.0 to each Social_Feedback record, calculated as max(0.0, 1.0 minus (elapsed_hours_since_created_at_original divided by 720)), where elapsed_hours is the number of hours between created_at_original and ingested_at, such that a score of 1.0 represents a post ingested at the moment of creation and a score of 0.0 represents a post 30 days or older.
3. WHEN a Social_Feedback record originates from a platform that provides a geotag or location field on the post, THE Ingestion_Service SHALL store the location as a string containing the city and country code (e.g., "Seattle, US") on the Social_Feedback record.
4. IF the Social_Listener encounters a rate limit or connectivity failure from a monitored platform, THEN THE Ingestion_Service SHALL log the failure with platform name and timestamp, and SHALL retry ingestion with exponential backoff starting at 30 seconds up to a maximum interval of 15 minutes, and SHALL cease retrying after 10 consecutive failed attempts for that platform, logging a final failure event.
5. IF the message_text of a detected post is empty or contains fewer than 3 characters, THEN THE Ingestion_Service SHALL discard the record without creating a Social_Feedback entry.

### Requirement 2: Widget and Form Feedback Ingestion

**User Story:** As a customer, I want to submit feedback through an in-app widget, website form, or support intake form, so that I can report issues or share comments directly with the company.

#### Acceptance Criteria

1. WHEN a customer submits feedback through any direct channel (app widget, website form, or support intake form), THE Ingestion_Service SHALL create a Widget_Feedback record containing feedback_id (UUID), source_type set to "widget", submission_channel identifier (one of "app_widget", "website_form", or "support_intake_form"), message_text, created_at (submission timestamp in ISO 8601 UTC), and consent_to_contact flag (boolean).
2. WHERE the customer provides optional fields (customer_id, account_type, service_type, user_name maximum 100 characters, contact_info maximum 320 characters, selected_category, location or service address maximum 500 characters, attachment_flag), THE Ingestion_Service SHALL store those values on the Widget_Feedback record.
3. THE Ingestion_Service SHALL accept both structured input (category selection from the predefined Theme_Category list: outage, billing, speed_performance, installation, technician_visit, support_experience, app_usability, equipment, cancellation_retention) and free-text message input simultaneously on each submission.
4. IF the message_text field is empty or contains only whitespace, THEN THE Ingestion_Service SHALL reject the submission and return an error response indicating that message text is required.
5. IF the message_text exceeds 10000 characters, THEN THE Ingestion_Service SHALL reject the submission and return an error response indicating the maximum character limit.
6. IF the consent_to_contact field is not explicitly provided as true or false on a Widget_Feedback submission, THEN THE Ingestion_Service SHALL reject the submission and return an error response indicating that the consent_to_contact field is required.
7. IF the selected_category is provided but does not match a value in the predefined Theme_Category list, THEN THE Ingestion_Service SHALL reject the submission and return an error response indicating the category is invalid.

### Requirement 3: Text Preprocessing and Standardization

**User Story:** As a data engineer, I want all ingested feedback cleaned, deduplicated, and converted into a single schema, so that downstream NLP processing receives consistent input regardless of source.

#### Acceptance Criteria

1. WHEN the Preprocessor receives a Social_Feedback or Widget_Feedback record, THE Preprocessor SHALL produce a Canonical_Feedback record containing a unified feedback_id, source_type, original_source_id, cleaned_text, detected_language code, ingested_at timestamp (ISO 8601 UTC), and all metadata fields defined in the source-to-canonical field mapping configuration.
2. THE Preprocessor SHALL clean message text by removing HTML tags, normalizing Unicode characters to NFC form, collapsing multiple whitespace characters into single spaces, and trimming leading and trailing whitespace.
3. THE Preprocessor SHALL detect the language of each message and store the ISO 639-1 language code on the Canonical_Feedback record.
4. IF the Preprocessor cannot determine the language with sufficient confidence or the cleaned_text contains fewer than 3 characters, THEN THE Preprocessor SHALL set the detected_language code to "und" (undetermined) on the Canonical_Feedback record.
5. WHEN the Preprocessor detects that a feedback record is a duplicate of an existing record (case-insensitive match on cleaned_text from the same source within a 24-hour window based on ingested_at timestamp), THE Preprocessor SHALL discard the duplicate and increment the duplicate_count on the original Canonical_Feedback record.
6. THE Preprocessor SHALL mask personally identifiable information (email addresses, phone numbers, and social security number patterns) in the cleaned_text field by replacing matched patterns with placeholder tokens ("[EMAIL]", "[PHONE]", "[SSN]") while preserving the original unmasked text in a separate secured field accessible only to authorized processes.
7. IF the Preprocessor encounters a word present in the configured profanity word list within the message text, THEN THE Preprocessor SHALL flag the record with a profanity_detected boolean set to true without removing or altering the profane content.
8. THE Preprocessor SHALL validate and standardize all timestamps to ISO 8601 UTC format, converting from source-specific formats where necessary.
9. IF the Preprocessor encounters a timestamp that cannot be parsed into a valid date-time value, THEN THE Preprocessor SHALL set the ingested_at field to the current UTC time and mark the record with a metadata flag "timestamp_parse_failed" set to true.
10. THE Preprocessor SHALL tag each Canonical_Feedback record with its originating source_type and platform identifier for downstream filtering.
11. IF the cleaned_text is empty after all cleaning operations (HTML removal, whitespace trimming), THEN THE Preprocessor SHALL mark the record with Processing_Status "failed" and reason "empty_after_cleaning" and SHALL NOT pass it to the NLP_Pipeline.

### Requirement 4: Sentiment Analysis

**User Story:** As a product analyst, I want each piece of feedback scored for sentiment, so that the system can quantify customer satisfaction and route accordingly.

#### Acceptance Criteria

1. WHEN the NLP_Pipeline processes a Canonical_Feedback record, THE Sentiment_Analyzer SHALL classify the sentiment as one of "positive", "neutral", or "negative".
2. THE Sentiment_Analyzer SHALL assign a numeric sentiment_score between -1.0 and +1.0 (inclusive) with a precision of at least 2 decimal places, where -1.0 represents most negative and +1.0 represents most positive sentiment.
3. THE Sentiment_Analyzer SHALL store both the sentiment_label and sentiment_score on the corresponding feedback_analysis record within 5 seconds of classification completing.
4. IF the Canonical_Feedback cleaned_text contains fewer than 5 characters after preprocessing (including empty or whitespace-only text), THEN THE Sentiment_Analyzer SHALL assign a sentiment_label of "neutral" and a sentiment_score of 0.0 without invoking the underlying language model.
5. THE Sentiment_Analyzer SHALL enforce that the sentiment_label is consistent with the sentiment_score by applying the following rule after model inference: assign "positive" for scores above 0.2, "negative" for scores below -0.2, and "neutral" for scores between -0.2 and 0.2 inclusive, overriding the model-returned label if it conflicts with the score range.
6. IF the Sentiment_Analyzer fails to produce a sentiment_score due to a model error or timeout, THEN THE Sentiment_Analyzer SHALL assign a sentiment_label of "neutral", a sentiment_score of 0.0, and record the enrichment status as "failed" with the failure reason on the feedback_analysis record.

### Requirement 5: Theme Detection and Topic Classification

**User Story:** As a product analyst, I want feedback automatically mapped to business categories, so that the organization can identify which product areas are generating the most feedback.

#### Acceptance Criteria

1. WHEN the NLP_Pipeline processes a Canonical_Feedback record, THE Theme_Detector SHALL assign a primary_theme from the set of Theme_Categories: outage, billing, speed_performance, installation, technician_visit, support_experience, app_usability, equipment, cancellation_retention.
2. WHERE the feedback text relates to multiple business categories, THE Theme_Detector SHALL assign a secondary_theme from the same Theme_Category set, distinct from the primary_theme.
3. IF the Theme_Detector cannot confidently map the feedback to any Theme_Category (confidence below 0.3), THEN THE Theme_Detector SHALL assign primary_theme as "unclassified".
4. THE Theme_Detector SHALL store primary_theme and secondary_theme (or null if no secondary applies) on the corresponding feedback_analysis record.
5. WHERE the Widget_Feedback record includes a selected_category from the customer, THE Theme_Detector SHALL use the customer-provided category as an input signal, weighting it alongside the NLP-derived classification to produce the final primary_theme.

### Requirement 6: Similarity Clustering

**User Story:** As an operations analyst, I want related complaints grouped together, so that systemic issues (like regional outages or billing confusion patterns) are identified and tracked as a single incident.

#### Acceptance Criteria

1. WHEN the NLP_Pipeline processes a Canonical_Feedback record, THE Similarity_Clusterer SHALL evaluate whether the feedback belongs to an existing Cluster based on a weighted combination of text similarity, shared theme, and geographic proximity (when both the feedback and the Cluster contain location data within 50 km of the Cluster centroid).
2. WHEN the Similarity_Clusterer determines that the feedback matches one or more existing Clusters with a similarity score above 0.7, THE Similarity_Clusterer SHALL assign the cluster_id of the highest-scoring matching Cluster to the feedback_analysis record and increment that Cluster's volume_count by 1.
3. WHEN the Similarity_Clusterer determines that no existing Cluster matches with a similarity score above 0.7, THE Similarity_Clusterer SHALL create a new Cluster record with a unique cluster_id (UUID), status "active", priority_level "low", assign the feedback to it, and set the Cluster volume_count to 1.
4. THE Similarity_Clusterer SHALL update the Cluster last_seen_at timestamp (ISO 8601 UTC) each time a new feedback record is assigned to the Cluster.
5. THE Similarity_Clusterer SHALL compute and store a cluster_summary (maximum 500 characters) describing the common topic of all feedback in the Cluster, updating the summary when the volume_count has increased by more than 20% since the last summary computation.
6. WHEN a Cluster volume_count exceeds 20 and the Cluster status is "active", THE Similarity_Clusterer SHALL update the Cluster priority_level to at least "high" if it is currently lower.
7. THE Similarity_Clusterer SHALL only consider Clusters with status "active" or "monitoring" as candidates for matching; Clusters with status "resolved" SHALL NOT receive new feedback assignments.
8. IF the Canonical_Feedback record does not contain location data, THEN THE Similarity_Clusterer SHALL evaluate cluster membership using text similarity and shared theme only, excluding geographic proximity from the similarity calculation.

### Requirement 7: Priority Scoring

**User Story:** As a support manager, I want feedback automatically prioritized based on severity signals, so that critical issues receive immediate attention and resources are allocated efficiently.

#### Acceptance Criteria

1. WHEN the NLP_Pipeline processes a Canonical_Feedback record, THE Priority_Scorer SHALL compute a priority_level of "low", "medium", "high", or "critical" based on weighted evaluation of the following signals: sentiment severity (absolute sentiment_score), presence of urgent keywords, customer account value (when available from account_type), engagement volume from engagement_metrics, duplicate cluster size (volume_count of assigned Cluster), outage indicators in the text, executive escalation language, and repeated contact history for the same customer_id.
2. IF the feedback contains outage indicator keywords (including "outage", "service down", "system down", "not working for everyone", "widespread issue") combined with a sentiment_score below -0.7, OR if executive escalation language is detected (keywords including "CEO", "executive", "lawyer", "attorney", "FCC", "regulatory", "lawsuit"), THEN THE Priority_Scorer SHALL assign priority_level "critical".
3. IF the feedback does not meet "critical" criteria, AND the sentiment_score is below -0.5 (exclusive) OR the assigned Cluster volume_count exceeds 10, THEN THE Priority_Scorer SHALL assign priority_level "high".
4. IF the feedback does not meet "critical" or "high" criteria, AND the sentiment_score is between -0.5 (inclusive) and -0.2 (exclusive) OR the intent indicates a request_for_help or billing_dispute, THEN THE Priority_Scorer SHALL assign priority_level "medium".
5. IF the feedback does not meet "critical", "high", or "medium" criteria, THEN THE Priority_Scorer SHALL assign priority_level "low".
6. THE Priority_Scorer SHALL evaluate priority levels in descending precedence order (critical, high, medium, low) and assign the highest matching level when multiple criteria are satisfied simultaneously.
7. THE Priority_Scorer SHALL store the computed priority_level on the feedback_analysis record.
8. WHEN the Priority_Scorer computes a priority_level, THE Priority_Scorer SHALL also store a numeric priority_score (0.0 to 1.0, where 1.0 is highest priority) representing the normalized aggregate of all input signals, with the priority_score falling within the range 0.75–1.0 for "critical", 0.50–0.74 for "high", 0.25–0.49 for "medium", and 0.0–0.24 for "low".

### Requirement 8: Intent Detection

**User Story:** As a routing operator, I want the customer's intent automatically classified, so that the Decision_Engine can determine the appropriate action without manual triage.

#### Acceptance Criteria

1. WHEN the NLP_Pipeline processes a Canonical_Feedback record, THE Intent_Classifier SHALL assign exactly one intent from the set of Intent_Types: complaint, request_for_help, outage_report, billing_dispute, feature_suggestion, praise, cancellation_risk.
2. WHEN the Intent_Classifier assigns an intent to a Canonical_Feedback record, THE Intent_Classifier SHALL store the detected intent and its confidence score on the corresponding feedback_analysis record within 5 seconds of classification completing.
3. IF the Intent_Classifier cannot classify the intent with a confidence score strictly greater than 0.4, THEN THE Intent_Classifier SHALL assign intent as "unclassified" and store the confidence score of the highest-scoring candidate intent.
4. WHEN the Intent_Classifier assigns an intent of complaint, request_for_help, outage_report, billing_dispute, or cancellation_risk, THE Intent_Classifier SHALL set the requires_action field on the feedback_analysis record to true.
5. WHEN the Intent_Classifier assigns an intent of feature_suggestion, praise, or unclassified, THE Intent_Classifier SHALL set the requires_action field on the feedback_analysis record to false.
6. IF the Intent_Classifier encounters an error or does not return a result within 10 seconds, THEN THE Intent_Classifier SHALL assign intent as "unclassified", set requires_action to false, and log the failure reason on the feedback_analysis record.

### Requirement 9: Entity Extraction

**User Story:** As a data analyst, I want structured entities extracted from free-text feedback, so that reports can be filtered by service area, product, dollar amount, and other dimensions.

#### Acceptance Criteria

1. WHERE entity extraction is enabled, THE Entity_Extractor SHALL identify and extract the following entity types from Canonical_Feedback cleaned_text: service_area, product_name, time_reference, dollar_amount, equipment_name, outage_mention (boolean), and competitor_mention, storing a maximum of 50 entities per feedback record with each entity_value containing no more than 200 characters.
2. THE Entity_Extractor SHALL store extracted entities as a structured list on the feedback_analysis record, with each entity containing entity_type, entity_value, and a confidence score between 0.0 and 1.0 indicating extraction certainty, and SHALL only include entities with a confidence score of 0.5 or higher.
3. IF the Entity_Extractor identifies no entities with confidence at or above 0.5 in a feedback record, THEN THE Entity_Extractor SHALL store an empty entity list on the feedback_analysis record.
4. WHEN the Entity_Extractor identifies a dollar_amount entity, THE Entity_Extractor SHALL normalize the value to a numeric decimal representation with exactly 2 decimal places within the range 0.01 to 999999999.99 (e.g., "$50" becomes 50.00, "$1,200.5" becomes 1200.50).
5. IF the Entity_Extractor encounters an error during extraction for a feedback record (such as an NLP service timeout after 30 seconds or an unavailable upstream dependency), THEN THE Entity_Extractor SHALL mark the entity extraction status as "failed" on the feedback_analysis record, store an empty entity list, and make the record available for retry.
6. IF the Entity_Extractor identifies a dollar_amount string that cannot be parsed into a valid numeric value within the range 0.01 to 999999999.99, THEN THE Entity_Extractor SHALL discard that entity and SHALL NOT include it in the stored entity list.

### Requirement 10: Decision Engine Evaluation Order

**User Story:** As a support operations lead, I want the decision engine to evaluate routing rules in a consistent priority order, so that critical issues are never missed and the most appropriate action is always selected.

#### Acceptance Criteria

1. THE Decision_Engine SHALL evaluate routing rules in the following priority order for each Canonical_Feedback record: first check escalation criteria, then check route_to_existing criteria, then check create_ticket criteria, then check auto_resolve criteria.
2. WHEN a Canonical_Feedback record matches escalation criteria, THE Decision_Engine SHALL assign Routing_Action "escalate" and SHALL NOT evaluate lower-priority rules.
3. WHEN a Canonical_Feedback record does not match escalation criteria but matches route_to_existing criteria, THE Decision_Engine SHALL assign Routing_Action "route_to_existing" and SHALL NOT evaluate lower-priority rules.
4. WHEN a Canonical_Feedback record does not match escalation or route_to_existing criteria but matches create_ticket criteria, THE Decision_Engine SHALL assign Routing_Action "create_ticket" and SHALL NOT evaluate lower-priority rules.
5. WHEN a Canonical_Feedback record does not match escalation, route_to_existing, or create_ticket criteria but matches auto_resolve criteria, THE Decision_Engine SHALL assign Routing_Action "auto_resolve".
6. IF a Canonical_Feedback record does not match any of the four rule categories (escalation, route_to_existing, create_ticket, auto_resolve), THEN THE Decision_Engine SHALL assign Routing_Action "create_ticket" with priority_level "medium" as the default fallback and SHALL assign Routing_Department "Customer_Care".
7. THE Decision_Engine SHALL store the assigned Routing_Action and evaluation timestamp in ISO 8601 UTC format on the feedback record.
8. THE Decision_Engine SHALL complete evaluation of all applicable rules for a single Canonical_Feedback record within 5 seconds of receiving the record.
9. IF the Decision_Engine encounters missing or invalid NLP analysis fields required for rule evaluation (such as absent priority_level, intent, or cluster assignment), THEN THE Decision_Engine SHALL assign Routing_Action "create_ticket" with priority_level "medium", assign Routing_Department "Customer_Care", and record the evaluation failure reason on the feedback record.

### Requirement 11: Decision Engine Auto-Resolve

**User Story:** As a support operations lead, I want low-priority feedback that requires no human action automatically closed, so that the support team focuses on actionable items.

#### Acceptance Criteria

1. WHEN the Decision_Engine evaluates a Canonical_Feedback record and determines the record is a duplicate (duplicate_count greater than 0 on the original Canonical_Feedback record), THE Decision_Engine SHALL assign Routing_Action "auto_resolve", create a Ticket with Ticket_Phase "auto_closed" and resolution_type "duplicate", and create a feedback_ticket_link record associating the feedback_id with the new Ticket.
2. WHEN the Decision_Engine evaluates a Canonical_Feedback record with priority_level "low", intent "praise", and requires_action set to false, THE Decision_Engine SHALL assign Routing_Action "auto_resolve" with resolution_type "no_action_required".
3. WHEN the Decision_Engine evaluates a Canonical_Feedback record whose assigned cluster_id references a Cluster that has all linked Tickets in Ticket_Phase "resolved" or "closed", THE Decision_Engine SHALL assign Routing_Action "auto_resolve" with resolution_type "known_resolved".
4. WHEN the Decision_Engine evaluates a Canonical_Feedback record with intent "request_for_help", primary_theme matching an entry in the configured FAQ topic list, and priority_level "low", THE Decision_Engine SHALL assign Routing_Action "auto_resolve" with resolution_type "faq_matched".
5. WHEN the Decision_Engine assigns Routing_Action "auto_resolve", THE Decision_Engine SHALL create a Ticket with Ticket_Phase "auto_closed", store the resolution_type on the Ticket, and create a feedback_ticket_link record associating the feedback_id with the auto_closed Ticket.
6. IF a Canonical_Feedback record does not match escalation, route_to_existing, or create_ticket criteria and also does not match any auto_resolve criteria, THEN THE Decision_Engine SHALL assign Routing_Action "auto_resolve" with resolution_type "no_action_required".

### Requirement 12: Decision Engine Route to Existing Issue

**User Story:** As a support operations lead, I want new feedback linked to open incidents or tickets when a match exists, so that related reports are consolidated rather than creating redundant tickets.

#### Acceptance Criteria

1. WHEN the Decision_Engine evaluates a Canonical_Feedback record assigned to a Cluster that has an existing open Ticket (Ticket_Phase not "resolved" and not "closed" and not "auto_closed"), THE Decision_Engine SHALL assign Routing_Action "route_to_existing" and link the feedback to the existing Ticket via a feedback_ticket_link record.
2. WHEN the Decision_Engine links feedback to an existing Ticket, THE Decision_Engine SHALL update the existing Ticket updated_at timestamp (ISO 8601 UTC).
3. THE Decision_Engine SHALL NOT create a new Ticket when Routing_Action is "route_to_existing".
4. WHEN a Cluster has multiple open Tickets (Ticket_Phase not "resolved", "closed", or "auto_closed"), THE Decision_Engine SHALL link the feedback to the Ticket with the most recent updated_at timestamp among those open Tickets.
5. IF the feedback_ticket_link insert fails due to a storage error, THEN THE Decision_Engine SHALL mark the feedback record with Processing_Status "failed" and reason "link_creation_failed", and SHALL NOT assign the Routing_Action.

### Requirement 13: Decision Engine Create New Ticket

**User Story:** As a support operations lead, I want new actionable feedback to generate tickets assigned to the correct department, so that issues are tracked and resolved by the responsible team.

#### Acceptance Criteria

1. WHEN the Decision_Engine evaluates a Canonical_Feedback record that does not qualify for escalation or route_to_existing, and the requires_action field is true with priority_level "medium" or "high", THE Decision_Engine SHALL assign Routing_Action "create_ticket".
2. WHEN the Decision_Engine assigns Routing_Action "create_ticket", THE Decision_Engine SHALL create a Ticket with a unique ticket_id (UUID), Ticket_Phase "new", the computed priority_level, linked_cluster_id (if assigned), created_at timestamp (ISO 8601 UTC), and an assigned Routing_Department determined by applying the department mapping rules in criteria 3 and 4.
3. THE Decision_Engine SHALL assign Routing_Department based on the following mapping applied to primary_theme and intent: outage and outage_report map to Network_Operations; billing and billing_dispute map to Billing_Support; speed_performance and request_for_help map to Technical_Support; installation and technician_visit map to Field_Operations; app_usability and feature_suggestion map to Digital_Product; support_experience maps to Customer_Care; cancellation_retention and cancellation_risk map to Retention. A match on primary_theme SHALL take precedence over a match on intent when both yield different departments.
4. IF the Canonical_Feedback record has source_type "social" and engagement_metrics total (likes + replies + reposts) exceeding 100, THEN THE Decision_Engine SHALL assign Routing_Department "Social_Media_Care", overriding the theme-and-intent-based mapping in criterion 3.
5. WHEN a Ticket is created, THE Decision_Engine SHALL create a feedback_ticket_link record associating the feedback_id with the new ticket_id.
6. IF the primary_theme is "unclassified" and the intent does not match any intent value listed in the mapping in criterion 3 (outage_report, billing_dispute, request_for_help, technician_visit, feature_suggestion, cancellation_risk), THEN THE Decision_Engine SHALL assign Routing_Department "Customer_Care" as the default department.
7. IF the Decision_Engine fails to persist the Ticket or the feedback_ticket_link record due to a storage error, THEN THE Decision_Engine SHALL mark the feedback record with Processing_Status "failed" and reason "ticket_creation_failed", and SHALL NOT assign a Routing_Action on the record.

### Requirement 14: Decision Engine Escalation

**User Story:** As a support operations lead, I want critical issues escalated immediately, so that high-severity problems are handled by senior staff or executive support.

#### Acceptance Criteria

1. WHEN the Decision_Engine evaluates a Canonical_Feedback record with priority_level "critical", THE Decision_Engine SHALL assign Routing_Action "escalate".
2. WHEN the Decision_Engine detects legal or regulatory risk language in the feedback text by performing a case-insensitive match against the keywords "lawyer", "attorney", "lawsuit", "fcc", "regulatory", "legal action", and "class action", THE Decision_Engine SHALL assign Routing_Action "escalate" regardless of the computed priority_level.
3. WHEN the Decision_Engine evaluates a Canonical_Feedback record from a customer with account_type "high_value" and at least 3 prior Tickets linked to the same customer_id with Ticket_Phase not in ("resolved", "closed", "auto_closed"), THE Decision_Engine SHALL assign Routing_Action "escalate".
4. WHEN the Decision_Engine evaluates a Social_Feedback record where engagement_metrics indicate viral reach (combined likes, replies, and reposts exceeding 1000), THE Decision_Engine SHALL assign Routing_Action "escalate".
5. WHEN the Decision_Engine assigns Routing_Action "escalate", THE Decision_Engine SHALL create a Ticket with a unique ticket_id (UUID), Ticket_Phase "new", priority_level "critical", and assigned Routing_Department "Executive_Escalations".
6. WHEN the Decision_Engine assigns Routing_Action "escalate", THE Decision_Engine SHALL create a feedback_ticket_link record associating the feedback_id with the escalation Ticket.
7. IF a Canonical_Feedback record matches multiple escalation criteria simultaneously, THEN THE Decision_Engine SHALL assign a single Routing_Action "escalate" and create exactly one escalation Ticket.

### Requirement 15: Ticket Lifecycle Management

**User Story:** As a support agent, I want tickets to follow a defined lifecycle with valid phase transitions, so that work is tracked systematically and status is always accurate.

#### Acceptance Criteria

1. THE Feedback_Store SHALL restrict Ticket_Phase transitions to the following valid sequences: "new" to "triaged", "triaged" to "routed", "routed" to "in_progress", "in_progress" to "waiting" or "resolved", "waiting" to "in_progress" or "resolved", "resolved" to "closed". Tickets created with Ticket_Phase "auto_closed" SHALL NOT require a prior transition and SHALL be treated as terminal upon creation.
2. IF a system component or user requests a Ticket_Phase transition that violates the allowed sequences, THEN THE Feedback_Store SHALL reject the transition, leave the Ticket record unchanged, and return an error indicating the current phase and the set of valid next phases.
3. WHEN a Ticket_Phase transition occurs, THE Feedback_Store SHALL record the previous phase, new phase, transition timestamp (ISO 8601 UTC), and the actor (system component or user identifier, maximum 150 characters) that triggered the transition.
4. THE Feedback_Store SHALL store creation timestamp (created_at) and last modification timestamp (updated_at) on each Ticket, updating updated_at on every phase transition or change to any mutable Ticket field (priority_level, assigned_department, resolution_type, resolution_notes, linked_cluster_id).
5. WHEN a Ticket transitions to "resolved", THE Feedback_Store SHALL require a resolution_type (one of "resolved_by_agent", "auto_resolved", "duplicate", "known_resolved", "no_action_required", "faq_matched") and optional resolution_notes (maximum 2000 characters).
6. IF a transition to "resolved" is requested without a valid resolution_type or with a resolution_type not in the allowed set, THEN THE Feedback_Store SHALL reject the transition, leave the Ticket record unchanged, and return an error indicating that a valid resolution_type is required.
7. THE Feedback_Store SHALL NOT allow transitions from "closed" or "auto_closed" to any other phase.

### Requirement 16: Pipeline Orchestration and Error Handling

**User Story:** As a system operator, I want the end-to-end processing pipeline to manage feedback flow reliably with clear status tracking and graceful failure recovery, so that no feedback is lost even when individual processing stages fail.

#### Acceptance Criteria

1. THE Pipeline_Orchestrator SHALL process each feedback record through the stages in order: ingestion, preprocessing, NLP analysis (sentiment, theme, clustering, priority, intent, entity extraction), and decision routing.
2. THE Pipeline_Orchestrator SHALL track the Processing_Status of each feedback record as it moves through stages: "ingested", "preprocessing", "preprocessed", "analyzing", "analyzed", "routing", "routed", "retrying", or "failed".
3. IF any processing stage fails for a feedback record and the record has not yet exhausted its retry attempts, THEN THE Pipeline_Orchestrator SHALL set the Processing_Status to "retrying", record the failed stage name and error message, and retry the failed stage up to 3 times with exponential backoff (initial delay 5 seconds, doubling each attempt, maximum delay 60 seconds) before proceeding.
4. IF a processing stage still fails after 3 retry attempts, THEN THE Pipeline_Orchestrator SHALL mark the record with Processing_Status "failed", record the failed stage name and final error message, and SHALL NOT pass the record to subsequent stages.
5. THE Pipeline_Orchestrator SHALL process feedback records independently so that a failure in one record does not prevent other records from progressing through the pipeline.
6. IF the cumulative processing time for a single feedback record across all stages and retry attempts exceeds 120 seconds, THEN THE Pipeline_Orchestrator SHALL immediately halt processing of that record, mark its Processing_Status as "failed" with reason "processing_timeout", and SHALL NOT retry the record further.
7. WHEN a feedback record reaches Processing_Status "routed", THE Pipeline_Orchestrator SHALL persist the record with all stage outputs and make it available for retrieval through the API_Server status endpoint.

### Requirement 17: Database Schema - Feedback Table

**User Story:** As a data engineer, I want raw feedback stored in a structured table with all source metadata, so that the system preserves the original submission context for audit and reprocessing.

#### Acceptance Criteria

1. THE Feedback_Store SHALL persist each feedback record in a "feedback" table with columns: feedback_id (UUID, primary key), source_type (enum: "social" or "widget"), platform (string, maximum 50 characters, nullable), message_text (text, maximum 10000 characters), customer_id (string, maximum 100 characters, nullable), created_at_original (ISO 8601 UTC timestamp), ingested_at (ISO 8601 UTC timestamp, auto-populated at insertion time), recency_score (float 0.0 to 1.0, nullable), channel_metadata (JSON, nullable), processing_status (enum matching Processing_Status values, default "ingested"), and routing_action (string, maximum 50 characters, nullable).
2. THE Feedback_Store SHALL enforce that feedback_id is unique across all records.
3. THE Feedback_Store SHALL enforce that message_text is not null and contains at least 1 non-whitespace character.
4. THE Feedback_Store SHALL store user-identifying information (username_handle, user_name, contact_info) as named keys within the channel_metadata JSON field, where each key is optional and each value is a string of maximum 320 characters when present.
5. THE Feedback_Store SHALL create an index on ingested_at for time-range queries.
6. IF a feedback record insertion or update violates any constraint (duplicate feedback_id, null or whitespace-only message_text, source_type not in allowed enum, processing_status not in allowed enum, recency_score outside 0.0–1.0), THEN THE Feedback_Store SHALL reject the operation and return an error indicating the specific constraint that was violated.
7. IF a feedback record is inserted without an explicit ingested_at value, THEN THE Feedback_Store SHALL auto-populate ingested_at with the current UTC timestamp at the moment of insertion.

### Requirement 18: Database Schema - Feedback Analysis Table

**User Story:** As a data engineer, I want NLP outputs stored in a dedicated analysis table linked to feedback, so that raw data and enrichment results are cleanly separated.

#### Acceptance Criteria

1. THE Feedback_Store SHALL persist NLP analysis results in a "feedback_analysis" table with columns: feedback_id (UUID, foreign key to feedback table), sentiment_label (enum: "positive", "neutral", "negative"), sentiment_score (float -1.0 to +1.0), priority_score (float 0.0 to 1.0), priority_level (enum: "low", "medium", "high", "critical"), theme_primary (string), theme_secondary (string, nullable), intent (string), cluster_id (UUID, nullable, foreign key to clusters table), requires_action (boolean), entities (JSON, nullable), processed_at (ISO 8601 UTC timestamp).
2. THE Feedback_Store SHALL enforce a one-to-one relationship between the feedback table and the feedback_analysis table via the feedback_id foreign key.
3. THE Feedback_Store SHALL enforce that sentiment_score is within the range -1.0 to +1.0 inclusive.
4. THE Feedback_Store SHALL enforce that priority_score is within the range 0.0 to 1.0 inclusive.
5. THE Feedback_Store SHALL enforce that sentiment_label, priority_level, and intent contain only values from their respective allowed enum sets, rejecting any insert or update with an invalid value.
6. THE Feedback_Store SHALL create an index on processed_at for efficient time-range queries on analysis results.

### Requirement 19: Database Schema - Tickets Table

**User Story:** As a data engineer, I want ticket operational data stored in a structured table, so that ticket lifecycle, assignment, and resolution are tracked consistently.

#### Acceptance Criteria

1. THE Feedback_Store SHALL persist tickets in a "tickets" table with columns: ticket_id (UUID, primary key, NOT NULL), ticket_phase (enum matching all Ticket_Phase values: "new", "triaged", "routed", "in_progress", "waiting", "resolved", "closed", "auto_closed", NOT NULL), priority_level (enum: "low", "medium", "high", "critical", NOT NULL), assigned_department (enum matching all Routing_Department values: "Network_Operations", "Billing_Support", "Technical_Support", "Field_Operations", "Digital_Product", "Customer_Care", "Retention", "Social_Media_Care", "Executive_Escalations", NOT NULL), created_at (ISO 8601 UTC timestamp, NOT NULL), updated_at (ISO 8601 UTC timestamp, NOT NULL), resolution_type (string, nullable, constrained to one of: "resolved_by_agent", "auto_resolved", "duplicate", "known_resolved", "no_action_required", "faq_matched"), resolution_notes (text, maximum 2000 characters, nullable), linked_cluster_id (UUID, nullable, foreign key to clusters table).
2. THE Feedback_Store SHALL enforce that ticket_id is unique across all records.
3. WHEN any field of a ticket record is modified, THE Feedback_Store SHALL set the updated_at timestamp to the current UTC time before persisting the change.
4. THE Feedback_Store SHALL create an index on (assigned_department, ticket_phase) for efficient queue queries per department.
5. IF an insert or update references a linked_cluster_id that does not exist in the clusters table, THEN THE Feedback_Store SHALL reject the operation and return an error indicating the referenced cluster does not exist.
6. IF an insert or update provides a resolution_type value that is not one of the allowed values, THEN THE Feedback_Store SHALL reject the operation and return an error indicating the invalid resolution_type.

### Requirement 20: Database Schema - Feedback Ticket Link Table

**User Story:** As a data engineer, I want a many-to-one mapping between feedback and tickets, so that multiple feedback records can be associated with a single ticket for consolidated tracking.

#### Acceptance Criteria

1. THE Feedback_Store SHALL persist feedback-to-ticket associations in a "feedback_ticket_link" table with columns: feedback_id (UUID, foreign key to feedback table) and ticket_id (UUID, foreign key to tickets table).
2. THE Feedback_Store SHALL enforce a uniqueness constraint on feedback_id in the feedback_ticket_link table such that each feedback_id appears at most once, and IF an insert or update would result in a duplicate feedback_id, THEN THE Feedback_Store SHALL reject the operation and return an error indicating the feedback record is already linked to a ticket.
3. THE Feedback_Store SHALL allow multiple distinct feedback_id values to reference the same ticket_id in the feedback_ticket_link table (many feedbacks to one ticket).
4. IF an insert into the feedback_ticket_link table references a feedback_id that does not exist in the feedback table or a ticket_id that does not exist in the tickets table, THEN THE Feedback_Store SHALL reject the operation and return an error indicating the referenced record does not exist.
5. WHEN a feedback record that has an entry in the feedback_ticket_link table is deleted from the feedback table, THE Feedback_Store SHALL automatically remove the corresponding row from the feedback_ticket_link table.
6. WHEN a ticket that is referenced by one or more rows in the feedback_ticket_link table is deleted from the tickets table, THE Feedback_Store SHALL automatically remove all corresponding rows from the feedback_ticket_link table.

### Requirement 21: Database Schema - Clusters Table

**User Story:** As a data engineer, I want cluster data stored in a structured table, so that aggregated issue groups are tracked with volume, trend, and lifecycle information.

#### Acceptance Criteria

1. THE Feedback_Store SHALL persist clusters in a "clusters" table with columns: cluster_id (UUID, primary key), theme (string, maximum 120 characters), cluster_summary (text, maximum 500 characters), volume_count (integer, minimum 1), sentiment_trend (string, nullable, maximum 50 characters), priority_level (enum: "low", "medium", "high", "critical"), first_seen_at (ISO 8601 UTC timestamp), last_seen_at (ISO 8601 UTC timestamp), status (enum: "active", "monitoring", "resolved").
2. THE Feedback_Store SHALL enforce that cluster_id is unique across all records.
3. THE Feedback_Store SHALL enforce that volume_count is a positive integer with a minimum value of 1.
4. WHEN a new feedback record is assigned to a Cluster, THE Feedback_Store SHALL increment the Cluster volume_count by 1 and set the last_seen_at timestamp to the current UTC time, applying both changes atomically so that no intermediate state is visible to concurrent readers.
5. IF the atomic update of volume_count and last_seen_at fails due to a storage error, THEN THE Feedback_Store SHALL leave the Cluster record unchanged and return an error indicating the assignment could not be persisted.

### Requirement 22: Trend Detection and Insights

**User Story:** As a product manager, I want the system to surface emerging themes, sentiment shifts, and volume spikes over time, so that systemic issues are identified before they escalate across the customer base.

#### Acceptance Criteria

1. THE NLP_Pipeline SHALL compute aggregate trend data including: theme frequency distribution across a configurable time window (minimum 1 day, maximum 90 days, default 7 days), sentiment score averages per theme over time, volume spike detection (when feedback volume for a theme exceeds 2x the rolling 7-day average computed from at least 7 days of prior data), and new cluster emergence rate (count of new Clusters created within the current time window).
2. WHEN a volume spike is detected for any Theme_Category, THE NLP_Pipeline SHALL record the spike event with the theme label, current volume count, baseline 7-day rolling average volume, and detection timestamp in ISO 8601 UTC format, and make the spike record available via the trend query interface.
3. IF a Cluster contains 20 or more feedback records, THEN THE NLP_Pipeline SHALL compute a sentiment_trend for that Cluster (one of "improving", "stable", "deteriorating") by comparing the average sentiment_score of the 10 most recent feedback records (by creation timestamp) to the average sentiment_score of the 10 oldest feedback records, where "improving" means the recent average exceeds the oldest average by more than 0.1, "deteriorating" means the oldest average exceeds the recent average by more than 0.1, and "stable" means the difference is 0.1 or less.
4. IF a Cluster contains fewer than 20 feedback records, THEN THE NLP_Pipeline SHALL set the sentiment_trend for that Cluster to "stable" and include a note indicating insufficient data for trend calculation.
5. THE Feedback_Store SHALL support time-range queries on feedback and feedback_analysis tables using ISO 8601 UTC start and end timestamps, returning all records within the specified range to enable trend computation across arbitrary date windows.
6. THE NLP_Pipeline SHALL evaluate Cluster activity status every 24 hours by comparing each Cluster's most recent feedback record creation timestamp against the current time.
7. WHEN the NLP_Pipeline evaluates Cluster activity and determines that a Cluster with status "active" has received no new feedback for 7 consecutive calendar days, THE NLP_Pipeline SHALL transition the Cluster status to "monitoring".
8. WHEN the NLP_Pipeline evaluates Cluster activity and determines that a Cluster with status "monitoring" has received no new feedback for an additional 14 consecutive calendar days (21 days total since last feedback), THE NLP_Pipeline SHALL transition the Cluster status to "resolved".

### Requirement 23: NLP Analysis Record Serialization

**User Story:** As a data engineer, I want NLP analysis records serialized and deserialized consistently, so that data integrity is maintained across storage and retrieval operations.

#### Acceptance Criteria

1. THE NLP_Pipeline SHALL serialize each feedback_analysis record to JSON format for storage, including all fields: sentiment_label, sentiment_score, priority_score, priority_level, theme_primary, theme_secondary, intent, cluster_id, requires_action, entities, and processed_at (ISO 8601 UTC timestamp).
2. THE NLP_Pipeline SHALL produce deterministic JSON output by sorting object keys lexicographically, using compact separators with no insignificant whitespace, and representing floating-point values with a maximum of 6 decimal digits of precision, so that serializing a given record always yields byte-for-byte identical output.
3. WHEN the NLP_Pipeline deserializes a JSON string into a feedback_analysis record, THE NLP_Pipeline SHALL validate that sentiment_score is a float in -1.0 to +1.0, priority_score is a float in 0.0 to 1.0, sentiment_label is one of the allowed values ("positive", "neutral", "negative"), priority_level is one of the allowed values ("low", "medium", "high", "critical"), intent is one of the allowed values (complaint, request_for_help, outage_report, billing_dispute, feature_suggestion, praise, cancellation_risk, unclassified), and processed_at is a valid ISO 8601 UTC timestamp, before accepting the record.
4. IF a deserialized record violates any schema constraint, THEN THE NLP_Pipeline SHALL reject the record, SHALL NOT store or process it further, and SHALL log a validation error identifying the field name and the specific constraint that was violated.
5. IF the JSON input is malformed (unparseable syntax), THEN THE NLP_Pipeline SHALL reject the input and SHALL log a parsing error indicating that the input is not valid JSON.
6. FOR each valid feedback_analysis record, serializing to JSON and then deserializing from JSON SHALL produce a record where every field value is identical to the original, including floating-point values within the 6-decimal-digit precision used during serialization.
