# Implementation Plan: Sentiment-Routed Frontend

## Overview

This plan implements a customer-facing, sentiment-routed feedback intake system with a FastAPI REST API backend and React SPA frontend. The backend introduces four new services (SubmissionStore, TicketingPipeline, MarketingEngine, AdminReviewQueue) persisting to a separate SQLite database, plus an AuthService for admin session management. The frontend implements a multi-page form flow with real-time status polling and an admin panel.

## Tasks

- [x] 1. Project scaffolding and core setup
  - [x] 1.1 Create FastAPI backend project structure
    - Create `backend/` directory with `app/`, `app/models/`, `app/services/`, `app/routes/`, `app/middleware/` packages
    - Add `backend/requirements.txt` with fastapi, uvicorn, pydantic>=2, httpx, python-multipart
    - Create `backend/app/main.py` with FastAPI app instance, CORS middleware, and router includes
    - _Requirements: 11.1, 11.7_

  - [x] 1.2 Create React frontend project structure
    - Initialize React project in `frontend/` with Vite and TypeScript template
    - Install react-router-dom for routing
    - Set up `src/pages/`, `src/components/`, `src/hooks/`, `src/context/`, `src/api/` directory structure
    - Configure proxy to FastAPI backend in vite.config.ts
    - _Requirements: 1.1, 2.1_

  - [x] 1.3 Define backend Pydantic v2 data models
    - Create `backend/app/models/submission.py` with SubmissionCreate, Submission, StatusResponse, StateTransition, EnrichmentResult models
    - Create `backend/app/models/ticket.py` with Ticket model
    - Create `backend/app/models/marketing.py` with MarketingEntry, ShareResult models
    - Create `backend/app/models/auth.py` with SessionToken, AdminUser models
    - Create `backend/app/models/requests.py` with pagination, sort, trend analysis request/response models
    - _Requirements: 11.1, 11.7, 14.1_

  - [x] 1.4 Create SQLite database schema and initialization
    - Create `backend/app/database.py` with connection factory, WAL mode enabled
    - Create `backend/app/schema.sql` with all 7 tables (submissions, state_transitions, tickets, marketing_log, admin_review_queue, admin_users, sessions)
    - Implement `init_db()` function that creates tables if not exists
    - Integrate `init_db()` into FastAPI startup event
    - _Requirements: 14.1, 14.2_

- [x] 2. Implement SubmissionStore service
  - [x] 2.1 Implement SubmissionStore core CRUD operations
    - Create `backend/app/services/submission_store.py` with the SubmissionStore class
    - Implement `create()` method: generates UUID, sets initial progress based on sentiment (negative→50, positive→100, neutral→25), persists to SQLite, records initial state transition
    - Implement `get()` method: retrieves full submission with state transitions
    - Implement `get_status()` method: returns StatusResponse with progress, sentiment, message mapping
    - _Requirements: 3.3, 4.2, 5.2, 14.1, 14.4_

  - [x] 2.2 Implement SubmissionStore state management and queries
    - Implement `update_progress()`: updates progress_state, records state transition with timestamp
    - Implement `update_enrichment()`: stores EnrichmentResult JSON, sets enrichment_status to "completed"
    - Implement `mark_enrichment_failed()`: sets enrichment_status to "failed" or "timeout" with reason
    - Implement `list_by_sentiment()`: paginated query filtered by sentiment
    - Implement `count_by_sentiment()`: aggregate counts grouped by sentiment and progress_state
    - _Requirements: 14.3, 13.6, 15.1_

  - [x] 2.3 Write property test for initial progress state assignment (Property 1)
    - **Property 1: Sentiment determines initial progress state**
    - Test that for any valid SubmissionCreate, the resulting progress_state matches sentiment mapping: negative→50, positive→100, neutral→25
    - **Validates: Requirements 3.3, 4.2, 5.2**

  - [x] 2.4 Write property test for submission persistence round-trip (Property 23)
    - **Property 23: Submission persistence round-trip**
    - Test that creating a submission and retrieving it by ID returns all fields matching the original payload
    - **Validates: Requirements 14.1, 14.4**

  - [x] 2.5 Write property test for state transition audit trail (Property 24)
    - **Property 24: State transition audit trail**
    - Test that every progress state change records a StateTransition with correct previous/new states and chronological ordering
    - **Validates: Requirements 14.3**

- [x] 3. Implement TicketingPipeline service
  - [x] 3.1 Implement TicketingPipeline service
    - Create `backend/app/services/ticketing_pipeline.py` with the TicketingPipeline class
    - Implement `create_ticket()`: generates UUID, links submission_id, sets priority "high", status "open"
    - Implement `advance_status()`: validates transition (open→in_progress→resolved), updates ticket, updates linked submission progress (in_progress→75%, resolved→100%)
    - Implement `list_active()`: returns tickets with status "open" or "in_progress"
    - Implement `get_ticket()`: retrieves single ticket by ID
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5_

  - [x] 3.2 Write property test for ticket creation from negative submissions (Property 4)
    - **Property 4: Negative submission always creates high-priority ticket**
    - Test that any valid negative submission results in a ticket with priority "high", status "open", unique UUID, correct Issue_Category, and linked submission_id
    - **Validates: Requirements 3.4, 16.1**

  - [x] 3.3 Write property test for ticket state machine transitions (Property 28)
    - **Property 28: Ticket state machine valid transitions**
    - Test that only open→in_progress and in_progress→resolved are accepted; all other transitions are rejected
    - **Validates: Requirements 16.2, 16.6**

  - [x] 3.4 Write property test for ticket state driving submission progress (Property 29)
    - **Property 29: Ticket state drives submission progress**
    - Test that in_progress sets linked submission to 75% and resolved sets it to 100%
    - **Validates: Requirements 16.3, 16.4**

- [x] 4. Implement MarketingEngine service
  - [x] 4.1 Implement MarketingEngine service
    - Create `backend/app/services/marketing_engine.py` with the MarketingEngine class
    - Implement `log_praise()`: stores marketing_log entry with customer_name, praise_text, social_sharing flag, social_status ("shared" or "internal_only")
    - Implement `generate_share()`: generates shareable URL and email template with PII removed (name, email, phone stripped from template text)
    - Implement `list_entries()`: paginated marketing log query
    - _Requirements: 17.1, 17.2, 17.3, 17.4_

  - [x] 4.2 Write property test for social sharing behavior (Property 5)
    - **Property 5: Social sharing controls marketing outbound behavior**
    - Test that social_sharing=true triggers URL+template generation; social_sharing=false logs as "internal_only" with no shareable URL
    - **Validates: Requirements 4.4, 4.5, 17.2, 17.3**

  - [x] 4.3 Write property test for PII removal from share templates (Property 30)
    - **Property 30: PII removed from share templates**
    - Test that generated email templates never contain customer name, email, or phone
    - **Validates: Requirements 17.2**

- [x] 5. Implement AdminReviewQueue service
  - [x] 5.1 Implement AdminReviewQueue service
    - Create `backend/app/services/admin_review_queue.py` with the AdminReviewQueue class
    - Implement `enqueue()`: inserts submission_id with queued_at timestamp
    - Implement `list_queue()`: paginated query ordered by queued_at ascending (oldest first)
    - Implement `remove()`: deletes entry from queue
    - Implement `is_queued()`: checks if submission_id exists in queue
    - _Requirements: 5.4, 10.1_

  - [x] 5.2 Write property test for neutral queue invariant (Property 6)
    - **Property 6: Neutral submissions always queued for admin review**
    - Test that any valid neutral submission appears in the AdminReviewQueue immediately after creation
    - **Validates: Requirements 5.4**

  - [x] 5.3 Write property test for queue ordering (Property 13)
    - **Property 13: Review queue ordered by submission timestamp ascending**
    - Test that list_queue always returns entries ordered by queued_at ascending
    - **Validates: Requirements 10.1**

- [x] 6. Checkpoint - Backend services complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement AuthService and authentication middleware
  - [x] 7.1 Implement AuthService
    - Create `backend/app/services/auth_service.py` with the AuthService class
    - Implement `login()`: verify credentials, check lockout, issue signed session token with 8-hour expiry
    - Implement `logout()`: invalidate token (set invalidated=1)
    - Implement `validate_token()`: check token exists, not invalidated, not expired
    - Implement `is_locked()`: check failed_attempts >= 5 and locked_until > now
    - Implement `record_failure()`: increment failed_attempts, set locked_until if threshold reached
    - Implement `clear_failures()`: reset failed_attempts on successful login
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [x] 7.2 Implement auth middleware and dependency injection
    - Create `backend/app/middleware/auth.py` with FastAPI dependency `require_admin`
    - Dependency extracts session token from cookie/header, validates via AuthService
    - Returns 401 if missing, expired, or invalidated
    - Wire dependency into admin-only route groups
    - _Requirements: 9.1, 9.5_

  - [x] 7.3 Write property test for session token expiry (Property 10)
    - **Property 10: Session token expires within 8 hours**
    - Test that any issued token has expires_at ≤ login_time + 8 hours
    - **Validates: Requirements 9.2**

  - [x] 7.4 Write property test for auth error uniformity (Property 11)
    - **Property 11: Authentication error uniformity**
    - Test that wrong username, wrong password, or both all return the same 401 response body
    - **Validates: Requirements 9.3**

  - [x] 7.5 Write property test for account lockout (Property 12)
    - **Property 12: Account lockout after 5 consecutive failures**
    - Test that after 5 consecutive failures, login is rejected for 60+ seconds even with correct credentials
    - **Validates: Requirements 9.6**

  - [x] 7.6 Write property test for admin endpoint protection (Property 9)
    - **Property 9: Admin endpoints require valid authentication**
    - Test that requests without token, with expired token, or with invalidated token all get 401
    - **Validates: Requirements 9.1, 9.5**

- [x] 8. Implement public API endpoints
  - [x] 8.1 Implement submission creation endpoint (POST /api/submissions)
    - Create `backend/app/routes/submissions.py`
    - Implement POST handler: validate payload, route to SubmissionStore.create(), invoke sentiment-specific service (TicketingPipeline for negative, MarketingEngine for positive, AdminReviewQueue for neutral), enqueue background NLP enrichment, return 201 with submission_id
    - _Requirements: 3.3, 3.4, 3.5, 4.2, 4.3, 5.2, 5.4, 5.5, 11.1_

  - [x] 8.2 Implement status polling endpoint (GET /api/submissions/{id}/status)
    - Implement GET handler: validate UUID format, retrieve from SubmissionStore.get_status(), return 404 if not found, return StatusResponse with progress and enrichment_status
    - _Requirements: 11.2, 11.3, 14.5_

  - [x] 8.3 Implement full submission retrieval (GET /api/submissions/{id})
    - Implement admin-only GET handler: returns full Submission record with state transitions and enrichment result
    - _Requirements: 14.4_

  - [x] 8.4 Write property test for payload validation (Property 18)
    - **Property 18: API payload validation returns 422**
    - Test that invalid payloads (missing fields, type errors, constraint violations) return 422 with field-level errors
    - **Validates: Requirements 11.7**

  - [x] 8.5 Write property test for non-existent submission IDs (Property 19)
    - **Property 19: Non-existent submission IDs return 404**
    - Test that non-existent or malformed UUIDs return 404
    - **Validates: Requirements 11.3, 14.5**

- [x] 9. Implement admin API endpoints
  - [x] 9.1 Implement auth endpoints (POST /api/auth/login, POST /api/auth/logout)
    - Create `backend/app/routes/auth.py`
    - Implement login: validate credentials via AuthService, return session token or 401
    - Implement logout: invalidate session via AuthService
    - _Requirements: 9.2, 9.3, 9.4_

  - [x] 9.2 Implement admin queue endpoints (GET /api/admin/queue, PATCH /api/admin/queue/{id}/sort)
    - Create `backend/app/routes/admin.py`
    - Implement GET queue: paginated list from AdminReviewQueue with enrichment summaries
    - Implement PATCH sort: validate submission is neutral/queued, execute sort-to-negative (create ticket, set progress 50%) or sort-to-positive (log marketing, set progress 100%), remove from queue atomically using DB transaction
    - Return 409 if already sorted
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.6, 11.4, 11.5, 11.6_

  - [x] 9.3 Implement admin ticket endpoints (GET /api/admin/tickets, PATCH /api/admin/tickets/{id}/advance)
    - Implement GET tickets: list active tickets (open/in_progress)
    - Implement PATCH advance: advance ticket status via TicketingPipeline, return 409 for invalid transitions
    - _Requirements: 16.2, 16.5, 16.6_

  - [x] 9.4 Implement admin dashboard and marketing endpoints
    - Implement GET /api/admin/dashboard: aggregate submission counts by sentiment and progress
    - Implement GET /api/admin/marketing: paginated marketing log
    - Implement POST /api/admin/trends: validate TimeWindows, invoke NLPProcessor.detect_trends(), return TrendReport
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 17.4_

  - [x] 9.5 Write property test for sort-to-negative atomicity (Property 14)
    - **Property 14: Sort-to-negative atomicity**
    - Test that sorting neutral to negative atomically creates ticket, sets progress to 50%, and removes from queue
    - **Validates: Requirements 10.3**

  - [x] 9.6 Write property test for sort-to-positive atomicity (Property 15)
    - **Property 15: Sort-to-positive atomicity**
    - Test that sorting neutral to positive atomically logs marketing, sets progress to 100%, and removes from queue
    - **Validates: Requirements 10.4**

  - [x] 9.7 Write property test for sort failure rollback (Property 16)
    - **Property 16: Sort failure leaves queue unchanged**
    - Test that if downstream service fails, submission stays in queue with progress unchanged
    - **Validates: Requirements 10.6**

  - [x] 9.8 Write property test for 409 on already-sorted submissions (Property 17)
    - **Property 17: 409 Conflict on already-sorted submission**
    - Test that PATCH sort on non-neutral submission returns 409
    - **Validates: Requirements 11.6**

- [x] 10. Implement NLP enrichment background tasks
  - [x] 10.1 Implement async NLP enrichment task
    - Create `backend/app/services/enrichment.py`
    - Implement background task: construct RawFeedback with source_channel="social_post", invoke NLPProcessor.process_batch(), extract EnrichmentResult from first InsightRecord, handle failures and timeout (30s), update submission via SubmissionStore
    - Wire into FastAPI BackgroundTasks in submission creation endpoint
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

  - [x] 10.2 Write property test for RawFeedback construction (Property 20)
    - **Property 20: RawFeedback constructed with source_channel "social_post"**
    - Test that constructed RawFeedback always has source_channel="social_post" and correct text
    - **Validates: Requirements 13.1**

  - [x] 10.3 Write property test for enrichment result extraction (Property 21)
    - **Property 21: Enrichment result extraction from BatchOutput**
    - Test that themes, confidence, severity, factors, language are correctly extracted from InsightRecord
    - **Validates: Requirements 13.2, 13.6**

  - [x] 10.4 Write property test for enrichment failure classification (Property 22)
    - **Property 22: Enrichment failure classification**
    - Test that BatchOutput with no insights but FailureEntries sets status to "failed" with stage and reason
    - **Validates: Requirements 13.3**

- [x] 11. Checkpoint - Backend API complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Implement frontend core and landing page
  - [x] 12.1 Set up React app shell, routing, and API client
    - Configure React Router in `src/App.tsx` with routes for all pages (/, /sentiment, /negative, /positive, /neutral, /status/:id, /admin/login, /admin/*)
    - Create `src/api/client.ts` with typed fetch wrapper for all API endpoints
    - Create `src/context/AuthContext.tsx` for session token state management
    - _Requirements: 2.1, 9.1_

  - [x] 12.2 Implement LandingPage component (Page 1)
    - Create `src/pages/LandingPage.tsx` with controlled inputs for name, email, phone, core request
    - Implement client-side validation: name non-empty after trim (max 100), at least one of email/phone, email pattern local@domain.tld, phone 7-15 digits with optional + prefix, core request non-empty (max 2000)
    - Display field-level error messages adjacent to invalid fields
    - Preserve all field values on validation failure
    - Navigate to /sentiment on success, passing form data via React state
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 12.3 Write property test for form validation rules (Property 2)
    - **Property 2: Form validation rejects invalid inputs**
    - Use fast-check to generate invalid inputs and verify rejection
    - **Validates: Requirements 1.2, 3.7, 5.3**

- [x] 13. Implement sentiment selection and form pages
  - [x] 13.1 Implement SentimentSelect component (Page 2)
    - Create `src/pages/SentimentSelect.tsx` with three sentiment cards (Negative, Positive, Neutral)
    - On click, immediately navigate to respective form page without separate submit
    - Carry Page 1 data forward via location state
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 13.2 Implement NegativeForm component (Page 3A)
    - Create `src/pages/NegativeForm.tsx` with Issue_Category dropdown (billing, network_speed, outage, support_experience, device_hardware, pricing) and description textarea (10-5000 chars, character counter)
    - Validate before submission: category selected, description 10+ chars
    - On submit: POST to /api/submissions with all Page 1 data + sentiment + form fields
    - On success: navigate to /status/:id
    - On error: display error message, allow retry
    - _Requirements: 3.1, 3.2, 3.3, 3.6, 3.7, 3.8_

  - [x] 13.3 Implement PositiveForm component (Page 3B)
    - Create `src/pages/PositiveForm.tsx` with praise textarea (1-2000 chars) and social sharing toggle (default off)
    - Validate before submission: praise non-empty
    - On submit: POST to /api/submissions with all data
    - On success: navigate to /status/:id
    - On marketing failure warning: show warning but still navigate
    - _Requirements: 4.1, 4.2, 4.7, 4.8, 4.9_

  - [x] 13.4 Implement NeutralForm component (Page 3C)
    - Create `src/pages/NeutralForm.tsx` with comment textarea (1-5000 chars)
    - Validate: comment has at least 1 non-whitespace character
    - On submit: POST to /api/submissions
    - On success: navigate to /status/:id
    - _Requirements: 5.1, 5.2, 5.3, 5.6, 5.7, 5.8_

  - [x] 13.5 Write property test for data retention across navigation (Property 3)
    - **Property 3: Data retained across page navigation**
    - Use fast-check to verify Page 1 data is preserved through sentiment selection and form submission
    - **Validates: Requirements 2.5**

- [x] 14. Implement status tracking and polling
  - [x] 14.1 Implement usePolling custom hook
    - Create `src/hooks/usePolling.ts` with configurable initial interval (5s), min (3s), max (10s)
    - Implement exponential backoff on failure: 5s base, 60s max, stop after 10 consecutive failures
    - Stop polling when progress reaches 100%
    - Return current status, error state, and manual retry function
    - _Requirements: 12.1, 12.3, 12.4, 12.5_

  - [x] 14.2 Implement StatusTracker component (Pages 4A/4B/4C)
    - Create `src/pages/StatusTracker.tsx` with progress bar, message display, and polling logic
    - Map progress states to messages: 25%→"Awaiting Review", 50%→"Spectrum is working on this.", 75%→"Almost there — resolution in progress.", 100%→sentiment-specific completion
    - Handle missing submission ID (display error, no polling)
    - Render pulsing animation for 25% (neutral waiting)
    - Display connection lost message after 10 failures with manual retry button
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.1, 7.2, 7.3, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [x] 14.3 Write property test for progress state message mapping (Property 7)
    - **Property 7: Progress state maps to correct message and bar percentage**
    - Use fast-check to verify all state/sentiment combinations produce correct message and percentage
    - **Validates: Requirements 6.3, 6.4, 8.3, 8.4, 8.6, 8.7, 12.3**

  - [x] 14.4 Write property test for exponential backoff computation (Property 8)
    - **Property 8: Exponential backoff computation**
    - Use fast-check to verify min(5×2^(n−1), 60) formula for n in 1..10 and stop after 10 failures
    - **Validates: Requirements 6.5, 12.4, 12.5**

- [x] 15. Implement admin panel frontend
  - [x] 15.1 Implement AdminLogin page and auth flow
    - Create `src/pages/admin/AdminLogin.tsx` with username/password form
    - On success: store session token in AuthContext, redirect to admin dashboard
    - On failure: display generic error message
    - Implement protected route wrapper that redirects to login if unauthenticated
    - _Requirements: 9.1, 9.2, 9.3_

  - [x] 15.2 Implement AdminDashboard page
    - Create `src/pages/admin/AdminDashboard.tsx` with summary stats (counts by sentiment and progress)
    - Display top 5 Issue_Categories ranked by frequency
    - Handle empty states (zero counts)
    - _Requirements: 15.1, 15.5, 15.6_

  - [x] 15.3 Implement ReviewQueue page
    - Create `src/pages/admin/ReviewQueue.tsx` with paginated neutral submission list
    - Show timestamp, customer name, comment, enrichment summary (themes, severity)
    - Implement sort-to-negative (with category selector) and sort-to-positive actions
    - Handle sort failures with error display
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.6_

  - [x] 15.4 Implement TicketList page
    - Create `src/pages/admin/TicketList.tsx` with open/in-progress tickets
    - Show ticket ID, submission ID, category, priority, status, created_at
    - Implement advance-status button (open→in_progress, in_progress→resolved)
    - Handle invalid transition errors
    - _Requirements: 16.5, 16.6_

  - [x] 15.5 Implement MarketingLog and TrendAnalysis pages
    - Create `src/pages/admin/MarketingLog.tsx` with paginated positive submissions showing name, praise, timestamp, sharing status labels ("shared"/"internal_only"/"generation_failed")
    - Create `src/pages/admin/TrendAnalysis.tsx` with baseline/current time window selectors (ISO 8601 inputs), submit button, and trend report display
    - Handle validation errors for invalid time windows
    - _Requirements: 15.2, 15.3, 15.4, 17.4_

- [x] 16. Checkpoint - Frontend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 17. Implement dashboard aggregation and trend properties
  - [x] 17.1 Write property test for dashboard aggregation correctness (Property 25)
    - **Property 25: Dashboard aggregation correctness**
    - Test that reported counts exactly match actual data grouped by sentiment and progress
    - **Validates: Requirements 15.1**

  - [x] 17.2 Write property test for invalid TimeWindow rejection (Property 26)
    - **Property 26: Invalid TimeWindow rejection**
    - Test that baseline start≥end, current start≥end, or overlapping windows return validation error without invoking NLP
    - **Validates: Requirements 15.4**

  - [x] 17.3 Write property test for top 5 category ranking (Property 27)
    - **Property 27: Top 5 category ranking by frequency**
    - Test that top 5 categories are ordered by frequency descending with correct counts
    - **Validates: Requirements 15.5**

- [ ] 18. Integration tests and final wiring
  - [x] 18.1 Write backend integration tests for full submission flows
    - Test negative flow: POST submission → verify ticket created → advance ticket → verify progress updates
    - Test positive flow: POST submission → verify marketing logged → verify progress 100%
    - Test neutral flow: POST submission → verify queued → admin sort → verify progress updated
    - Test NLP enrichment: submission → background task → enrichment stored
    - Use pytest + httpx TestClient against FastAPI app
    - _Requirements: 3.3, 3.4, 4.2, 4.3, 5.2, 5.4, 10.3, 10.4, 13.6_

  - [x] 18.2 Wire frontend API client to all backend endpoints and verify end-to-end connectivity
    - Ensure all API client methods match backend endpoint signatures
    - Add error handling for network failures, 4xx, and 5xx responses
    - Add request/response type checking against Pydantic models
    - Verify CORS configuration allows frontend origin
    - _Requirements: 11.1, 11.2, 11.7_

  - [x] 18.3 Write integration tests for admin sort atomicity and error scenarios
    - Test sort-to-negative: queue removal + ticket creation + progress update in single transaction
    - Test sort-to-positive: queue removal + marketing log + progress update
    - Test sort failure rollback: mock service failure, verify queue unchanged
    - Test 409 on re-sort attempt
    - _Requirements: 10.3, 10.4, 10.6, 11.6_

- [x] 19. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties (30 total across Properties 1-30)
- Backend uses Python 3.11+ with FastAPI and Pydantic v2; frontend uses React with TypeScript
- Backend property tests use pytest + Hypothesis; frontend property tests use fast-check
- The existing NLPProcessor, RawFeedback, BatchOutput, and InsightRecord models are reused from `nlp_processing/`
- SQLite database `submissions.db` is separate from existing `nlp_pipeline.db`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4"] },
    { "id": 2, "tasks": ["2.1", "5.1", "7.1"] },
    { "id": 3, "tasks": ["2.2", "3.1", "4.1", "5.2", "5.3", "7.2"] },
    { "id": 4, "tasks": ["2.3", "2.4", "2.5", "3.2", "3.3", "3.4", "4.2", "4.3", "7.3", "7.4", "7.5", "7.6"] },
    { "id": 5, "tasks": ["8.1", "9.1"] },
    { "id": 6, "tasks": ["8.2", "8.3", "9.2", "9.3", "9.4"] },
    { "id": 7, "tasks": ["8.4", "8.5", "9.5", "9.6", "9.7", "9.8", "10.1"] },
    { "id": 8, "tasks": ["10.2", "10.3", "10.4", "12.1"] },
    { "id": 9, "tasks": ["12.2", "12.3"] },
    { "id": 10, "tasks": ["13.1", "13.2", "13.3", "13.4"] },
    { "id": 11, "tasks": ["13.5", "14.1"] },
    { "id": 12, "tasks": ["14.2", "14.3", "14.4"] },
    { "id": 13, "tasks": ["15.1"] },
    { "id": 14, "tasks": ["15.2", "15.3", "15.4", "15.5"] },
    { "id": 15, "tasks": ["17.1", "17.2", "17.3"] },
    { "id": 16, "tasks": ["18.1", "18.2"] },
    { "id": 17, "tasks": ["18.3"] }
  ]
}
```
