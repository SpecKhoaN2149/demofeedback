# Requirements Document

## Introduction

This feature is an overhaul of the existing Spectrum feedback application. Today the application requires customers to self-select a sentiment ("complaint / praise / comment") through a multi-step frontend flow (LandingPage → SentimentSelect → Positive/Negative/NeutralForm), stores each entry as a `submission` with a user-supplied `sentiment` field, and creates downstream artifacts (tickets, marketing log entries, review-queue entries) directly based on that self-selected sentiment.

This overhaul replaces that model with an NLP-first, triage-driven model:

- Customers submit free-form text through a single feedback form. The application no longer asks the customer to classify their own feedback.
- The existing NLP enrichment pipeline (themes, sentiment, severity, and language via Google Gemini with model-priority fallback and graceful failure handling) determines the sentiment and other attributes automatically.
- Every submission becomes a **Feedback** record with a stable `feedback_id`, regardless of whether it needs action.
- Feedback can be ingested directly (web form) or from social media (Reddit, X, Facebook). Admin views display source/platform attribution.
- After NLP analysis, a **triage/decision step** determines whether action is required. If so, a **Ticket** is created (or the feedback is linked to an existing ticket); otherwise the feedback is retained as feedback-only for trend and sentiment analysis.
- Ticket linkage is optional and many-to-one: each Feedback links to at most one Ticket, and each Ticket can have many Feedback records linked to it.
- Staff can leave internal comments on tickets, and customers can view the comments left on the ticket associated with their feedback.

This document specifies the functional requirements for the overhaul. It also flags migration considerations for existing data, since the schema changes significantly from the current `submissions` / `tickets` / `admin_review_queue` / `marketing_log` structure.

## Glossary

- **System**: The Spectrum feedback application as a whole (FastAPI backend, React/TypeScript frontend, and NLP enrichment pipeline).
- **Feedback**: A unified record representing a single piece of customer feedback, identified by a `feedback_id`. Replaces the current `submission` entity. Every ingested piece of feedback becomes exactly one Feedback record.
- **feedback_id**: A globally unique identifier (UUID) assigned to every Feedback record at creation.
- **Ticket**: An actionable work item identified by a `ticket_id`. Created only when triage determines action is required. A Ticket may have many linked Feedback records.
- **ticket_id**: A globally unique identifier (UUID) assigned to a Ticket at creation.
- **Feedback_Form**: The single free-form submission form presented to customers, replacing the LandingPage → SentimentSelect → typed-form flow.
- **NLP_Pipeline**: The existing enrichment pipeline that derives themes, sentiment, severity, and language from feedback text using Google Gemini with model-priority fallback.
- **Enrichment_Result**: The structured NLP output stored on a Feedback record (themes, sentiment, sentiment confidence, severity score, severity factors, language code, language confidence).
- **Sentiment**: An NLP-derived classification of feedback tone, one of "positive", "neutral", or "negative". No longer supplied by the customer.
- **Triage_Engine**: The decision component that, after NLP analysis, determines whether a Feedback record requires action and produces a Triage_Outcome.
- **Triage_Outcome**: The result of triage for a Feedback record, one of "action_required" or "no_action". Recorded on the Feedback record.
- **Source_Type**: The origin category of a Feedback record, one of "direct" (submitted by a customer through the application) or "social" (ingested from social media).
- **Channel**: For direct feedback, the specific intake method (e.g., "web_form").
- **Platform**: For social feedback, the originating social media platform, one of "reddit", "x", or "facebook".
- **Social_Listener**: The existing ingestion service (`nlp_processing/ingestion/social_listener.py`) that produces SocialFeedback records with platform attribution.
- **Ticket_Comment**: An internal note left by staff on a Ticket, consisting of author (admin username), timestamp, and text.
- **Admin**: An authenticated Spectrum staff member with a valid session token.
- **Admin_Dashboard**: The authenticated internal interface used by staff to review feedback, tickets, and comments.
- **Status_View**: The customer-facing interface where a customer looks up the current status of their feedback and any associated ticket.
- **Trend_Analysis**: The existing analytics capability that aggregates feedback attributes (themes, sentiment, severity) over time windows.

## Requirements

### Requirement 1: Single free-form feedback submission

**User Story:** As a customer, I want to describe my feedback in a single free-form text box, so that I do not have to categorize my own feedback before submitting.

#### Acceptance Criteria

1. THE Feedback_Form SHALL present a single free-form text input for the customer's feedback message.
2. THE Feedback_Form SHALL NOT require the customer to select a sentiment, complaint, praise, or comment category before submission.
3. WHEN a customer submits the Feedback_Form with a non-empty message, THE System SHALL create one Feedback record.
4. IF a customer submits the Feedback_Form with an empty or whitespace-only message, THEN THE System SHALL reject the submission, return a validation error identifying the message field, and create no Feedback record.
5. WHEN a customer submits the Feedback_Form with a message longer than 10000 characters, THE System SHALL reject the submission and return a validation error identifying the message length limit.
6. IF a submission fails any validation check, including when a message is simultaneously empty and longer than 10000 characters, THEN THE System SHALL reject the submission and create no Feedback record.
7. WHEN the System creates a Feedback record from a direct submission, THE System SHALL set the Source_Type to "direct" and the Channel to "web_form".
8. WHEN the System successfully creates a Feedback record from the Feedback_Form, THE System SHALL return the assigned `feedback_id` to the customer.

### Requirement 2: NLP-derived sentiment and attributes

**User Story:** As a customer, I want the application to analyze my feedback automatically, so that its sentiment, themes, severity, and language are determined without my input.

#### Acceptance Criteria

1. WHEN a Feedback record is created, THE System SHALL enqueue the feedback text for analysis by the NLP_Pipeline.
2. WHEN the NLP_Pipeline completes analysis for a Feedback record, THE System SHALL store the derived Enrichment_Result including themes, Sentiment, sentiment confidence, severity score, severity factors, language code, and language confidence on that Feedback record.
3. WHEN the NLP_Pipeline completes analysis for a Feedback record, THE System SHALL set the Feedback record's Sentiment to the NLP-derived value of "positive", "neutral", or "negative".
4. THE System SHALL derive Sentiment exclusively from the NLP_Pipeline and SHALL NOT accept a customer-supplied Sentiment value.
5. WHILE NLP analysis for a Feedback record has not completed, THE System SHALL record the enrichment status as "pending".
6. IF the NLP_Pipeline fails to analyze a Feedback record, THEN THE System SHALL record the enrichment status as "failed" and retain the Feedback record with its original text.
7. IF the NLP_Pipeline does not complete analysis within the configured timeout, THEN THE System SHALL record the enrichment status as "timeout" and retain the Feedback record with its original text.
8. THE System SHALL preserve the existing NLP_Pipeline behavior for theme detection, sentiment analysis, severity scoring, and language detection, including Gemini model-priority fallback.

### Requirement 3: Triage decision step

**User Story:** As a Spectrum operations lead, I want a triage step after NLP analysis that decides whether feedback needs action, so that only actionable feedback becomes a ticket while all feedback is retained for analysis.

#### Acceptance Criteria

1. WHEN NLP analysis for a Feedback record reaches a terminal enrichment status, THE Triage_Engine SHALL evaluate the Feedback record and produce a Triage_Outcome of "action_required" or "no_action".
2. WHEN the Triage_Outcome for a Feedback record is "action_required", THE System SHALL either create a new Ticket linked to the Feedback record or link the Feedback record to an existing Ticket.
3. WHEN the Triage_Outcome for a Feedback record is "no_action", THE System SHALL retain the Feedback record without a linked Ticket.
4. THE System SHALL retain every Feedback record regardless of Triage_Outcome so that all feedback remains available for Trend_Analysis and sentiment analysis.
5. WHERE automated triage cannot determine a Triage_Outcome with confidence, THE System SHALL route the Feedback record to Admin review for a manual triage decision and record the decision source of the routing-to-review event as "automated".
6. WHEN an Admin makes a manual triage decision of "action_required" for a Feedback record, THE System SHALL create a new Ticket linked to the Feedback record or link it to an Admin-selected existing Ticket.
7. WHEN an Admin makes a manual triage decision of "no_action" for a Feedback record, THE System SHALL retain the Feedback record without a linked Ticket.
8. THE System SHALL record the Triage_Outcome and its decision source ("automated" or "admin") on the Feedback record, where routing to Admin review because automated triage lacked confidence is recorded with the decision source "automated" and a subsequent Admin manual decision is recorded per criteria 6 and 7 with the decision source "admin".
9. IF triage fails to complete for a Feedback record, THEN THE System SHALL retain the Feedback record and route it to Admin review.

### Requirement 4: Feedback identity for all submissions

**User Story:** As a Spectrum operations lead, I want every piece of feedback to have a stable identifier, so that all feedback can be tracked and referenced whether or not it needs action.

#### Acceptance Criteria

1. WHEN the System creates a Feedback record, THE System SHALL assign a unique `feedback_id`.
2. THE System SHALL assign a `feedback_id` to every Feedback record regardless of Source_Type and regardless of Triage_Outcome.
3. THE System SHALL ensure each `feedback_id` is unique across all Feedback records.
4. WHEN a Feedback record is retrieved by its `feedback_id`, THE System SHALL return that Feedback record.

### Requirement 5: Optional many-to-one ticket linkage

**User Story:** As a Spectrum operations lead, I want feedback to optionally link to a shared ticket, so that many reports of the same issue map to a single actionable ticket while non-actionable feedback has no ticket.

#### Acceptance Criteria

1. THE System SHALL allow a Feedback record to have zero or one linked Ticket.
2. THE System SHALL allow a Ticket to have one or more linked Feedback records.
3. WHEN a Ticket is created from a Feedback record, THE System SHALL link that Feedback record to the created Ticket.
4. WHEN a Feedback record is linked to an existing Ticket, THE System SHALL associate the Feedback record's `feedback_id` with that Ticket's `ticket_id` without creating a new Ticket.
5. IF a Feedback record has a Triage_Outcome of "no_action", THEN THE System SHALL leave its ticket linkage empty.
6. WHEN a Ticket is retrieved, THE System SHALL return the set of `feedback_id` values linked to that Ticket.
7. THE System SHALL prevent linking a Feedback record to more than one Ticket at a time, AND SHALL allow linking a Feedback record to any valid existing Ticket regardless of that Ticket's current linked-Feedback count, including a Ticket that currently has zero linked Feedback records.

### Requirement 6: Social media source attribution

**User Story:** As an Admin, I want to see where each piece of feedback came from, so that I can distinguish social media posts and their platforms from directly submitted feedback.

#### Acceptance Criteria

1. WHEN a Feedback record is ingested from Social_Listener, THE System SHALL set the Source_Type to "social" and record the originating Platform of "reddit", "x", or "facebook".
2. WHERE a Feedback record has a Source_Type of "social", THE Admin_Dashboard SHALL display the originating Platform for that Feedback record; IF that Feedback record's Platform data is missing or unavailable, THEN THE Admin_Dashboard SHALL display nothing in the platform field with no error and no placeholder text.
3. WHERE a Feedback record has a Source_Type of "direct", THE Admin_Dashboard SHALL display the Channel for that Feedback record.
4. THE Admin_Dashboard SHALL display the Source_Type for every Feedback record it lists.
5. WHEN Social_Listener provides platform attribution on a SocialFeedback record, THE System SHALL persist that Platform value on the corresponding Feedback record.
6. WHERE a Feedback record has a Source_Type of "direct", THE System SHALL allow that Feedback record to retain a Platform value carried over from a previous state or other source, AND SHALL NOT be required to clear the Platform value when Source_Type is not "social", while the Platform display rules in criteria 2 and 3 continue to govern what the Admin_Dashboard shows.

### Requirement 7: Internal comments on tickets

**User Story:** As an Admin, I want to leave internal comments on a ticket, so that staff can record context and collaborate on resolving the issue.

#### Acceptance Criteria

1. WHEN an authenticated Admin submits a comment on a Ticket with non-empty text, THE System SHALL create a Ticket_Comment recording the Admin username as author, the current timestamp, and the comment text.
2. IF an Admin submits a comment with empty or whitespace-only text, THEN THE System SHALL reject the comment and return a validation error.
3. WHEN an Admin submits a comment on a `ticket_id` that does not exist, THE System SHALL return a not-found error.
4. IF an unauthenticated request attempts to create a Ticket_Comment, THEN THE System SHALL reject the request with an authentication error.
5. WHEN an Admin views a Ticket, THE Admin_Dashboard SHALL display all Ticket_Comments for that Ticket ordered by timestamp ascending.
6. THE System SHALL associate each Ticket_Comment with exactly one Ticket by `ticket_id`.

### Requirement 8: Customer-visible ticket comments

**User Story:** As a customer, I want to see the comments staff have left on my ticket, so that I understand what is being done about my feedback.

#### Acceptance Criteria

1. WHEN a customer views the Status_View for a Feedback record that is linked to a Ticket, THE System SHALL display the Ticket_Comments for that linked Ticket.
2. WHEN a customer views the Status_View for a Feedback record that is not linked to a Ticket, THE System SHALL indicate that no ticket is associated with the feedback.
3. THE Status_View SHALL display each visible Ticket_Comment's author and timestamp alongside its text.
4. WHEN multiple Feedback records are linked to the same Ticket, THE System SHALL display that Ticket's Ticket_Comments to each linked Feedback record's customer through the Status_View.
5. THE Status_View SHALL display Ticket_Comments ordered by timestamp ascending.

### Requirement 9: Feedback and ticket status visibility

**User Story:** As a customer, I want to look up the current status of my feedback, so that I know whether it is under analysis, retained as feedback, or being handled as a ticket.

#### Acceptance Criteria

1. WHEN a customer requests the Status_View using a valid `feedback_id`, THE System SHALL return the current enrichment status and Triage_Outcome for that Feedback record.
2. WHERE a Feedback record is linked to a Ticket, THE Status_View SHALL display the linked Ticket's current status.
3. IF a customer requests the Status_View using a `feedback_id` that does not exist, THEN THE System SHALL return a not-found error.
4. WHILE a Feedback record's enrichment status is "pending", THE Status_View SHALL indicate that analysis is in progress.

### Requirement 10: Admin review and dashboard over the unified model

**User Story:** As an Admin, I want the dashboard and review tools to operate over the unified feedback model, so that I can review, triage, and act on feedback and tickets in one place.

#### Acceptance Criteria

1. THE Admin_Dashboard SHALL list Feedback records with their `feedback_id`, Source_Type, Sentiment, enrichment status, Triage_Outcome, and linked `ticket_id` when present.
2. WHERE a Feedback record is routed to Admin review for triage, THE Admin_Dashboard SHALL present that Feedback record with an action to record a manual triage decision.
3. THE Admin_Dashboard SHALL provide aggregate counts of Feedback records by Sentiment and by Triage_Outcome.
4. THE Admin_Dashboard SHALL list active Tickets with their linked Feedback count.
5. WHEN an Admin advances a Ticket's status, THE System SHALL update that Ticket's status and reflect the change in the Status_View for all linked Feedback records.

### Requirement 11: Preservation of existing analytics and marketing behavior

**User Story:** As a Spectrum operations lead, I want existing trend analysis and marketing capabilities to keep working under the new model, so that the overhaul does not lose current functionality.

#### Acceptance Criteria

1. THE System SHALL make all Feedback records, including "no_action" feedback, available to Trend_Analysis over time windows.
2. WHEN Trend_Analysis is run over a valid time window configuration, THE System SHALL aggregate Feedback attributes including themes, Sentiment, and severity.
3. WHERE a Feedback record's NLP-derived Sentiment is "positive", THE System SHALL make that Feedback record available to the existing marketing capability.
4. THE System SHALL preserve existing Admin authentication using session tokens for all Admin_Dashboard operations.

### Requirement 12: Migration of existing data

**User Story:** As a Spectrum operations lead, I want existing submissions and tickets to be preserved under the new model, so that historical feedback and tickets remain available after the overhaul.

#### Acceptance Criteria

1. WHEN the data migration runs, THE System SHALL convert each existing `submission` record into a Feedback record and assign a `feedback_id`.
2. WHEN migrating an existing `submission`, THE System SHALL preserve the original submission text, creation timestamp, and any existing Enrichment_Result.
3. WHEN migrating an existing `submission` that has a self-selected sentiment, THE System SHALL retain that value as the Feedback record's Sentiment where no NLP-derived Sentiment is available.
4. WHEN migrating an existing `ticket`, THE System SHALL convert it into a Ticket under the new model and link its originating Feedback record by `feedback_id`.
5. WHEN migrating existing records, THE System SHALL set the Source_Type to "direct" and the Channel to "web_form" for records that have no social attribution.
6. IF a migrated `submission` was in the existing admin review queue, THEN THE System SHALL preserve its pending-review state as a Feedback record routed to Admin review for triage.
7. THE System SHALL complete migration without deleting existing feedback or ticket data.
