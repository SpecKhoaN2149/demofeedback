# Requirements Document

## Introduction

This document specifies the requirements for a customer-facing, sentiment-routed feedback and support intake frontend for Spectrum. The system extends the existing NLP feedback processing pipeline (which provides theme classification, sentiment analysis, severity scoring, language detection, and trend analysis via Google Gemini) with a multi-page web application that routes customers through different workflows based on their self-reported sentiment. A REST API layer bridges the frontend to the existing NLPProcessor backend and introduces new capabilities: submission lifecycle tracking, a ticketing pipeline, a marketing/logging engine, and an admin review queue. An admin panel allows staff to manage neutral submissions, view NLP-enriched insights, and trigger dynamic status updates visible to customers in real time.

## Glossary

- **Frontend_App**: The customer-facing single-page application built with a modern JavaScript framework (React or Vue) that presents the multi-page feedback workflow.
- **API_Server**: The FastAPI-based REST API layer that exposes endpoints for submission, status tracking, admin operations, and NLP enrichment, wrapping the existing NLPProcessor.
- **NLPProcessor**: The existing Python orchestrator that drives ingestion, enrichment (classification, sentiment, severity), clustering, and prioritization of feedback using the Google Gemini API.
- **Submission**: A customer feedback entry consisting of contact information, sentiment selection, form-specific details, and a lifecycle Progress_State. Stored in the Submission_Store.
- **Submission_Store**: A new SQLite-backed persistence layer for customer submissions, distinct from the existing NLP batch persistence. Tracks submission metadata, sentiment route, and progress state.
- **Ticket**: A high-priority support record created in the Ticketing_Pipeline when a customer reports a negative experience.
- **Ticketing_Pipeline**: The backend processing path for negative-sentiment submissions that creates prioritized support tickets and tracks their resolution progress.
- **Marketing_Engine**: The backend processing path for positive-sentiment submissions that logs praise and optionally fires outbound social or email communications.
- **Admin_Review_Queue**: The backend queue where neutral-sentiment submissions are held pending manual classification by an admin.
- **Admin_Panel**: The authenticated interface for Spectrum staff to view the review queue, sort neutral submissions, view NLP-enriched insights, and monitor trend data.
- **Status_Tracker**: The frontend component that displays real-time progress to the customer after submission.
- **Sentiment_Route**: One of three workflow paths (negative, positive, neutral) determined by the customer's explicit sentiment selection on Page 2.
- **Progress_State**: A percentage value (25%, 50%, 75%, or 100%) representing the current resolution status of a submission.
- **Issue_Category**: A label drawn from the existing NLP theme set (billing, network_speed, outage, support_experience, device_hardware, pricing) used to categorize negative feedback.
- **Enrichment_Result**: The NLP analysis output for a submission containing themes, sentiment confidence, severity score, severity factors, and language detection.

## Requirements

### Requirement 1: Landing Page Data Collection

**User Story:** As a customer, I want to provide my contact information and describe my issue on a landing page, so that Spectrum can identify me and understand my request.

#### Acceptance Criteria

1. THE Frontend_App SHALL display a landing page with input fields for customer name (maximum 100 characters), an email field, a phone number field, and a free-text core request description (maximum 2000 characters).
2. WHEN the customer submits the landing page form, THE Frontend_App SHALL trim leading and trailing whitespace from all fields and then validate that the name field contains at least 1 character, at least one of the email or phone fields is filled, the email field (if provided) contains a value matching the pattern local@domain.tld, the phone field (if provided) contains between 7 and 15 digits (optionally prefixed with +), and the core request field contains at least 1 character.
3. IF the customer submits the landing page form with invalid or missing required fields, THEN THE Frontend_App SHALL display a field-level error message adjacent to each invalid field indicating the specific validation failure, and SHALL preserve all previously entered field values.
4. WHEN all landing page fields pass validation, THE Frontend_App SHALL navigate the customer to the sentiment selection page.

### Requirement 2: Sentiment Selection Routing

**User Story:** As a customer, I want to select my sentiment explicitly, so that the system routes me to the appropriate feedback form.

#### Acceptance Criteria

1. THE Frontend_App SHALL display a sentiment selection page with exactly three options: Negative (complaint or issue), Positive (praise or compliment), and Neutral (general comment).
2. WHEN the customer selects the Negative option, THE Frontend_App SHALL immediately navigate to the negative feedback form (Page 3A) without requiring a separate submit action.
3. WHEN the customer selects the Positive option, THE Frontend_App SHALL immediately navigate to the positive feedback form (Page 3B) without requiring a separate submit action.
4. WHEN the customer selects the Neutral option, THE Frontend_App SHALL immediately navigate to the neutral feedback form (Page 3C) without requiring a separate submit action.
5. THE Frontend_App SHALL retain the customer name, contact information, and core request text collected on Page 1 and carry them forward through the sentiment-specific form submission.

### Requirement 3: Negative Feedback Submission

**User Story:** As a customer with a complaint, I want to categorize and describe my issue in detail, so that Spectrum can create a prioritized support ticket.

#### Acceptance Criteria

1. THE Frontend_App SHALL display a negative feedback form containing a dropdown for Issue_Category selection and a text area for detailed description with a maximum length of 5000 characters and a visible character counter.
2. THE Frontend_App SHALL populate the Issue_Category dropdown with the categories: billing, network_speed, outage, support_experience, device_hardware, and pricing.
3. WHEN the customer submits the negative feedback form with a selected Issue_Category and a description containing at least 10 characters and no more than 5000 characters, THE API_Server SHALL create a Submission in the Submission_Store with sentiment "negative" and Progress_State 50%.
4. WHEN the Submission is created, THE API_Server SHALL create a Ticket in the Ticketing_Pipeline with high priority, linking the Submission identifier and Issue_Category.
5. WHEN the Submission is created, THE API_Server SHALL invoke the NLPProcessor asynchronously to enrich the submission text with theme classification, sentiment confidence, and severity scoring without blocking the submission response.
6. WHEN the Ticket is created successfully, THE Frontend_App SHALL navigate the customer to the negative status tracking page (Page 4A).
7. IF the customer submits the negative feedback form without a selected Issue_Category or with a description shorter than 10 characters, THEN THE Frontend_App SHALL display field-level error messages indicating which fields require correction and SHALL NOT submit the form to the API_Server.
8. IF the API_Server fails to create the Submission or the Ticket due to a server error or network failure, THEN THE API_Server SHALL return an error response indicating the failure reason and THE Frontend_App SHALL display an error message informing the customer that submission could not be completed and to retry.

### Requirement 4: Positive Feedback Submission

**User Story:** As a customer with praise, I want to share my positive experience and optionally permit social sharing, so that Spectrum can acknowledge my feedback.

#### Acceptance Criteria

1. THE Frontend_App SHALL display a positive feedback form containing a text area for praise (maximum 2000 characters) and a toggle for social sharing permission defaulting to off.
2. WHEN the customer submits the positive feedback form with praise text between 1 and 2000 characters, THE API_Server SHALL create a Submission in the Submission_Store with sentiment "positive", Progress_State 100%, and the social sharing permission flag value.
3. WHEN the Submission is created, THE API_Server SHALL log the submission in the Marketing_Engine.
4. IF the social sharing permission flag is enabled on the Submission, THEN THE Marketing_Engine SHALL generate an outbound social link or email communication referencing the praise.
5. IF the social sharing permission flag is not enabled on the Submission, THEN THE Marketing_Engine SHALL log the praise for internal use only without generating outbound communications.
6. WHEN the Submission is created, THE API_Server SHALL invoke the NLPProcessor to enrich the submission text with theme classification and sentiment confidence.
7. WHEN the positive submission is logged successfully in the Marketing_Engine, THE Frontend_App SHALL navigate the customer to the positive status tracking page (Page 4B).
8. IF the Marketing_Engine logging fails, THEN THE API_Server SHALL store the Submission without marketing confirmation and THE Frontend_App SHALL navigate the customer to the positive status tracking page (Page 4B) with a warning indicating marketing logging is pending.
9. IF the positive feedback submission fails to create the Submission, THEN THE API_Server SHALL return an error response and THE Frontend_App SHALL display an error message to the customer.

### Requirement 5: Neutral Feedback Submission

**User Story:** As a customer with a general comment, I want to submit my feedback for review, so that Spectrum staff can evaluate and act on it.

#### Acceptance Criteria

1. THE Frontend_App SHALL display a neutral feedback form containing a text area for the raw comment with a maximum input length of 5000 characters.
2. WHEN the customer submits the neutral feedback form with comment text containing at least 1 non-whitespace character and not exceeding 5000 characters, THE API_Server SHALL create a Submission in the Submission_Store with sentiment "neutral" and Progress_State 25%.
3. IF the customer submits the neutral feedback form with an empty or whitespace-only comment, THEN THE Frontend_App SHALL display a field-level error message indicating that a comment is required.
4. WHEN the Submission is created, THE API_Server SHALL place the Submission identifier in the Admin_Review_Queue.
5. WHEN the Submission is created, THE API_Server SHALL invoke the NLPProcessor to enrich the submission text with theme classification, sentiment confidence, and severity scoring.
6. WHEN the neutral submission is queued successfully, THE Frontend_App SHALL navigate the customer to the neutral status tracking page (Page 4C).
7. IF the API_Server encounters a validation error on the neutral feedback payload, THEN THE API_Server SHALL return a 422 response and THE Frontend_App SHALL display an error message indicating which fields are invalid.
8. IF the API_Server encounters an internal failure while creating the neutral Submission, THEN THE API_Server SHALL return an error response and THE Frontend_App SHALL display an error message indicating that submission could not be completed and the customer should retry.

### Requirement 6: Negative Status Tracking

**User Story:** As a customer who reported an issue, I want to see live progress on my ticket, so that I know Spectrum is working on my case.

#### Acceptance Criteria

1. WHEN the customer reaches the negative status tracking page, THE Frontend_App SHALL display a progress bar at 50% with the message "Spectrum is working on this."
2. THE Frontend_App SHALL poll the API_Server at intervals between 3 seconds and 10 seconds for Progress_State updates on the submitted Submission.
3. WHEN the API_Server reports Progress_State 75%, THE Frontend_App SHALL update the progress bar to 75% with the message "Almost there — resolution in progress."
4. WHEN the API_Server reports Progress_State 100%, THE Frontend_App SHALL update the progress bar to 100% with a completion message indicating the ticket has been resolved and SHALL stop polling the API_Server.
5. IF a polling request fails due to a network error or non-success response, THEN THE Frontend_App SHALL retry with exponential backoff starting at 5 seconds up to a maximum interval of 60 seconds, while continuing to display the last known Progress_State.
6. IF the customer reaches the negative status tracking page without a valid Submission identifier, THEN THE Frontend_App SHALL display an error message indicating the submission could not be found and SHALL not initiate polling.

### Requirement 7: Positive Status Tracking

**User Story:** As a customer who shared praise, I want immediate confirmation that my feedback was received.

#### Acceptance Criteria

1. WHEN the customer reaches the positive status tracking page, THE Frontend_App SHALL display a progress bar at 100% with the message "Praise received & noted!"
2. THE Frontend_App SHALL display the positive status tracking page without initiating repeated polling to the API_Server.
3. IF the customer reaches the positive status tracking page without a valid Submission identifier, THEN THE Frontend_App SHALL display an error message indicating the submission could not be found.

### Requirement 8: Neutral Status Tracking with Dynamic Updates

**User Story:** As a customer who submitted a general comment, I want to see my submission status update dynamically after admin review, so that I know my feedback is being handled.

#### Acceptance Criteria

1. WHEN the customer reaches the neutral status tracking page, THE Frontend_App SHALL display a pulsing progress bar at 25% with the message "Awaiting Review."
2. THE Frontend_App SHALL poll the API_Server at intervals between 3 seconds and 10 seconds for status updates on the neutral Submission.
3. WHEN an admin sorts the neutral Submission to negative, THE Frontend_App SHALL update the progress bar to 50% and display the message "Spectrum is working on this." and SHALL continue polling for further Progress_State changes.
4. WHEN an admin sorts the neutral Submission to positive, THE Frontend_App SHALL update the progress bar to 100% and display the message "Praise received & noted!" and SHALL stop polling the API_Server.
5. WHILE the neutral Submission remains unsorted, THE Frontend_App SHALL continue displaying the pulsing 25% progress bar.
6. WHEN the API_Server reports Progress_State 75% for a neutral Submission previously sorted to negative, THE Frontend_App SHALL update the progress bar to 75% and display the message "Almost there — resolution in progress."
7. WHEN the API_Server reports Progress_State 100% for a neutral Submission previously sorted to negative, THE Frontend_App SHALL update the progress bar to 100%, display a completion message indicating the issue has been resolved, and stop polling the API_Server.

### Requirement 9: Admin Authentication

**User Story:** As a Spectrum staff member, I want the admin panel to require authentication, so that only authorized personnel can manage the review queue.

#### Acceptance Criteria

1. WHEN an unauthenticated user attempts to access any admin-only endpoint, THE API_Server SHALL return a 401 Unauthorized response and SHALL NOT execute the requested operation.
2. WHEN a staff member provides a valid username and password, THE API_Server SHALL issue a session token granting access to admin endpoints with an expiration time of no longer than 8 hours from issuance.
3. IF a staff member provides invalid credentials, THEN THE API_Server SHALL return a 401 Unauthorized response with an error message indicating that authentication failed, without revealing whether the username or password was incorrect.
4. THE Admin_Panel SHALL include a logout action that invalidates the current session token and returns the user to the login prompt.
5. IF a request includes an expired or invalidated session token, THEN THE API_Server SHALL return a 401 Unauthorized response and require re-authentication.
6. IF a staff member fails authentication 5 consecutive times for the same username, THEN THE API_Server SHALL reject further login attempts for that username for at least 60 seconds.

### Requirement 10: Admin Review Queue Management

**User Story:** As a Spectrum staff member, I want to view neutral submissions and sort them into negative or positive categories, so that customer feedback is properly routed.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display a list of all Submissions in the Admin_Review_Queue sorted by submission timestamp in ascending order (oldest first), showing submission timestamp, customer name, comment text, and Enrichment_Result summary (detected themes and severity score).
2. WHEN an admin selects a neutral Submission, THE Admin_Panel SHALL display the full Submission details including contact information, core request text, and complete Enrichment_Result (themes with confidence, sentiment confidence, severity score with contributing factors).
3. WHEN an admin sorts a neutral Submission to negative and selects an Issue_Category from the available set (billing, network_speed, outage, support_experience, device_hardware, pricing), THE API_Server SHALL create a Ticket in the Ticketing_Pipeline with high priority using the selected Issue_Category, update the Submission Progress_State to 50%, and remove the Submission from the Admin_Review_Queue.
4. WHEN an admin sorts a neutral Submission to positive, THE API_Server SHALL log the Submission in the Marketing_Engine, update the Submission Progress_State to 100%, and remove the Submission from the Admin_Review_Queue.
5. WHEN the Progress_State of a Submission changes, THE API_Server SHALL make the updated state available to polling clients within 5 seconds.
6. IF the Ticketing_Pipeline or Marketing_Engine fails during a sort operation, THEN THE API_Server SHALL return an error response indicating the failure reason, leave the Submission in the Admin_Review_Queue with its Progress_State unchanged, and not remove the Submission from the queue.

### Requirement 11: REST API Layer

**User Story:** As a system integrator, I want a REST API wrapping the existing NLPProcessor and new submission capabilities, so that the frontend can communicate with the backend over HTTP.

#### Acceptance Criteria

1. THE API_Server SHALL expose a POST endpoint for creating a Submission that accepts customer name (1–100 characters), email or phone, core request text (1–5000 characters), sentiment selection (one of "negative", "positive", "neutral"), and form-specific fields (Issue_Category for negative, praise text for positive with social sharing flag, comment text for neutral) and SHALL return a 201 Created response containing the new submission identifier.
2. THE API_Server SHALL expose a GET endpoint for retrieving the current Progress_State and Enrichment_Result of a Submission by submission identifier.
3. IF the submission identifier provided to the GET endpoint does not match any existing Submission, THEN THE API_Server SHALL return a 404 Not Found response.
4. THE API_Server SHALL expose an admin-only GET endpoint for listing the Admin_Review_Queue with pagination using limit (default 20, maximum 100) and offset (default 0) parameters.
5. THE API_Server SHALL expose an admin-only PATCH endpoint for sorting a neutral Submission to negative or positive.
6. IF the PATCH sort endpoint is called on a Submission whose sentiment is not "neutral", THEN THE API_Server SHALL return a 409 Conflict response indicating the Submission has already been sorted.
7. THE API_Server SHALL validate all incoming request payloads using Pydantic v2 models and return 422 Unprocessable Entity responses for invalid payloads.
8. IF the NLPProcessor raises an exception during enrichment, THEN THE API_Server SHALL log the exception, store the Submission without Enrichment_Result, and return a success response with a warning indicating enrichment is pending.

### Requirement 12: Real-Time Status Polling

**User Story:** As a customer, I want my status page to update without manual refresh, so that I always see the latest progress on my submission.

#### Acceptance Criteria

1. THE Frontend_App SHALL poll the status endpoint starting at an initial interval of 5 seconds, with subsequent intervals no shorter than 3 seconds and no longer than 10 seconds.
2. WHEN the API_Server responds with a Progress_State that differs from the currently displayed Progress_State, THE Frontend_App SHALL re-render the progress bar and status message within 1 second of receiving the response.
3. WHEN the progress bar reaches 100%, THE Frontend_App SHALL stop polling the API_Server.
4. IF the polling request fails due to a network error, THEN THE Frontend_App SHALL retry with exponential backoff starting at 5 seconds, up to a maximum interval of 60 seconds and a maximum of 10 consecutive failed attempts.
5. IF the Frontend_App reaches 10 consecutive failed polling attempts, THEN THE Frontend_App SHALL stop polling and display an error message indicating that the connection to the server has been lost.

### Requirement 13: NLP Enrichment Integration

**User Story:** As a system operator, I want customer submissions to be enriched by the existing NLP pipeline, so that admins can see AI-generated insights alongside raw feedback.

#### Acceptance Criteria

1. WHEN the API_Server invokes the NLPProcessor for a Submission, THE API_Server SHALL construct a RawFeedback object with source_channel "social_post" for web submissions, the submission text as the feedback text, and an empty metadata dictionary.
2. WHEN the NLPProcessor returns a BatchOutput with at least one InsightRecord, THE API_Server SHALL extract the themes (with confidence values), sentiment confidence, severity score, severity factors, language code, and language confidence from the first InsightRecord and store them as the Enrichment_Result on the Submission.
3. IF the NLPProcessor returns a BatchOutput with zero InsightRecords and at least one FailureEntry, THEN THE API_Server SHALL store the FailureEntry stage and reason on the Submission and mark the enrichment status as "failed".
4. IF the NLPProcessor returns a BatchOutput with zero InsightRecords and zero FailureEntries, THEN THE API_Server SHALL mark the enrichment status as "failed" with a reason indicating no insight was produced.
5. THE API_Server SHALL invoke NLP enrichment asynchronously so that Submission creation does not block on the Gemini API response, and SHALL enforce a maximum enrichment timeout of 30 seconds after which the enrichment status is marked as "timeout".
6. WHEN enrichment completes successfully after the Submission was already created, THE API_Server SHALL update the Submission record with the Enrichment_Result and set the enrichment status to "completed".

### Requirement 14: Submission Persistence

**User Story:** As a system operator, I want all customer submissions stored durably with full lifecycle tracking, so that no feedback is lost and audit history is maintained.

#### Acceptance Criteria

1. THE Submission_Store SHALL persist each Submission with a unique identifier (UUID), creation timestamp (ISO 8601 UTC), customer name (maximum 200 characters), contact information (maximum 320 characters), core request text (maximum 5000 characters), sentiment route, form-specific fields, Progress_State, and Enrichment_Result.
2. THE Submission_Store SHALL use SQLite as the storage backend with write-ahead logging enabled, consistent with the existing NLP persistence layer.
3. WHEN the Progress_State of a Submission changes, THE Submission_Store SHALL record the previous state, new state, and timestamp of the transition in ISO 8601 UTC format, preserving all prior transitions in chronological order.
4. WHEN the API_Server receives a GET request with a valid submission identifier that exists in the Submission_Store, THE API_Server SHALL return the full Submission record including all state transition history ordered chronologically.
5. IF the API_Server receives a GET request with a submission identifier that does not exist in the Submission_Store or is not a valid UUID format, THEN THE API_Server SHALL return a 404 Not Found response with an error message indicating the submission was not found.
6. IF the Submission_Store fails to persist a Submission due to a storage error, THEN THE API_Server SHALL return an error response indicating the submission was not saved and SHALL NOT acknowledge the submission as created.

### Requirement 15: Admin Trend and Insight Dashboard

**User Story:** As a Spectrum staff member, I want to view NLP-derived trends and insights on the admin panel, so that I can identify systemic issues and customer sentiment patterns.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display a summary dashboard showing total submissions by sentiment route (negative, positive, neutral) and their current Progress_States.
2. THE Admin_Panel SHALL expose the existing NLPProcessor trend detection capability, allowing admins to select baseline and current time windows as ISO 8601 UTC date-time values where each window's start is before its end and the two windows do not overlap, and view theme spikes, sentiment shifts, and severity escalations.
3. WHEN the admin requests a trend analysis with valid TimeWindows, THE API_Server SHALL invoke the NLPProcessor detect_trends method with the specified TimeWindows and return the TrendReport within 30 seconds.
4. IF the admin requests a trend analysis with invalid TimeWindows (start after end, overlapping windows, or unparseable date-time values), THEN THE API_Server SHALL return an error response indicating the validation failure without invoking the NLPProcessor.
5. THE Admin_Panel SHALL display the top 5 Issue_Categories ranked by submission frequency across all negative submissions.
6. IF no submissions exist for a given sentiment route or no negative submissions exist, THEN THE Admin_Panel SHALL display a zero-count state for the empty categories and omit the Issue_Category ranking.

### Requirement 16: Ticketing Pipeline

**User Story:** As a system operator, I want negative submissions to create trackable tickets, so that support staff can manage resolution and customers can see progress.

#### Acceptance Criteria

1. WHEN the Ticketing_Pipeline receives a create request, THE Ticketing_Pipeline SHALL create a Ticket with a unique identifier (UUID), linked Submission identifier, Issue_Category, description text (maximum 5000 characters), priority "high", and status "open".
2. THE Ticketing_Pipeline SHALL restrict status transitions to the following sequence: "open" to "in_progress", and "in_progress" to "resolved".
3. WHEN a Ticket transitions to "in_progress", THE Ticketing_Pipeline SHALL update the linked Submission Progress_State to 75%.
4. WHEN a Ticket transitions to "resolved", THE Ticketing_Pipeline SHALL update the linked Submission Progress_State to 100%.
5. THE Admin_Panel SHALL display all Tickets with status "open" or "in_progress", showing ticket identifier, linked Submission identifier, Issue_Category, priority, current status, and creation timestamp, and SHALL allow admins to advance a Ticket to the next valid status.
6. IF an admin or system component requests a status transition that violates the allowed sequence, THEN THE Ticketing_Pipeline SHALL reject the request and return an error response indicating the invalid transition.

### Requirement 17: Marketing Engine

**User Story:** As a system operator, I want positive submissions to be logged for marketing use, so that customer praise can be acknowledged and optionally shared.

#### Acceptance Criteria

1. WHEN the Marketing_Engine receives a positive Submission, THE Marketing_Engine SHALL log the praise text, customer name, and timestamp in the Submission_Store with a "marketing_logged" flag.
2. WHEN the Marketing_Engine receives a positive Submission with social sharing permission granted, THE Marketing_Engine SHALL generate a shareable URL and an email template containing the praise text with customer name and contact information removed.
3. IF the social sharing permission is not granted, THEN THE Marketing_Engine SHALL log the praise for internal use only without generating outbound communications.
4. THE Admin_Panel SHALL display a paginated list of positive submissions showing customer name, praise text, timestamp, and social sharing status indicated as "shared" when sharing permission was granted or "internal_only" when sharing permission was not granted.
5. IF the Marketing_Engine fails to generate the shareable URL or email template, THEN THE Marketing_Engine SHALL retain the marketing log entry, mark the social sharing status as "generation_failed", and make the Submission available for retry from the Admin_Panel.
