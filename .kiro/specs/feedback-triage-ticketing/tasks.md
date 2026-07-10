# Implementation Plan: Feedback Triage & Ticketing Overhaul

## Overview

This plan converts the design into incremental coding steps that overhaul the existing Spectrum feedback app in place: FastAPI backend (`backend/app`), React + TS + Vite frontend (`frontend/src`), and the `nlp_processing` pipeline. Each task builds on the previous ones, starting from schema and models, moving up through services (FeedbackStore, Triage_Engine, ticketing, comments), enrichment wiring, the public and admin API surface, the non-destructive migration, and finally the frontend. The last epic wires all 12 correctness properties into property-based tests mapped to the exact files named in the design's Testing Strategy.

Testing follows the project's established approach: **Hypothesis** property/unit tests in `backend/tests/`, **fast-check + React Testing Library** in `frontend/src/__tests__/`. Gemini/enrichment is always faked (no network) via a stubbed pipeline returning canned `EnrichmentResult`s or raising/timeouts on demand. Legacy tables (`submissions`, `state_transitions`, `admin_review_queue`, `marketing_log`) are preserved throughout so migration stays non-destructive.

## Tasks

- [x] 1. Schema and Pydantic models for the unified feedback model
  - [x] 1.1 Add new tables to `backend/app/schema.sql`
    - Add `feedback` table (feedback_id PK, text, source_type direct/social CHECK, channel, platform reddit/x/facebook CHECK, created_at, enrichment_status pending/completed/failed/timeout CHECK, enrichment_result JSON, sentiment CHECK nullable, triage_outcome action_required/no_action CHECK nullable, triage_decision_source automated/admin CHECK nullable, needs_review INTEGER default 0, ticket_id nullable FK → tickets)
    - Redefine `tickets` as independent (ticket_id PK, issue_category, description, priority, status open/in_progress/resolved CHECK, created_at); drop the mandatory 1:1 `submission_id` FK
    - Add `ticket_comments` table (id AUTOINCREMENT PK, ticket_id FK NOT NULL, author, created_at, text)
    - Add indexes `idx_feedback_ticket`, `idx_feedback_needs_review`, `idx_ticket_comments_ticket`
    - Keep legacy tables (`submissions`, `state_transitions`, `admin_review_queue`, `marketing_log`) intact
    - _Requirements: 1.1, 2.3, 2.5, 3.1, 3.8, 4.1, 4.3, 5.1, 5.2, 5.7, 6.1, 6.5, 7.6_

  - [x] 1.2 Create `backend/app/models/feedback.py`
    - Define `FeedbackCreate` (text with `min_length=1`, `max_length=10000`; optional `contact`; NO `sentiment` field)
    - Define `Feedback` (all persisted fields incl. `source_type`, `channel`, `platform`, `enrichment_status`, `enrichment_result`, `sentiment`, `triage_outcome`, `triage_decision_source`, `needs_review`, `ticket_id`)
    - Define `TicketComment`, `TriageRequest` (outcome + optional ticket_id), `CommentCreate` (text `min_length=1`)
    - Define a `StatusView` model for the status payload (enrichment_status, triage_outcome, ticket, comments, analysis_in_progress)
    - Reuse `EnrichmentResult` unchanged from `models/submission.py`
    - _Requirements: 1.4, 1.5, 2.4, 3.8, 5.6, 7.1, 9.1_

  - [ ]* 1.3 Write unit tests for the feedback models
    - Verify `FeedbackCreate` has no `sentiment` attribute and rejects empty/oversized text
    - Verify `Feedback` defaults (enrichment_status=pending, needs_review=False, nullable triage fields)
    - _Requirements: 1.4, 1.5, 2.4_

- [x] 2. FeedbackStore service (evolution of SubmissionStore)
  - [x] 2.1 Create `backend/app/services/feedback_store.py` with core CRUD
    - Implement `create(data, *, source_type="direct", channel="web_form", platform=None)` assigning a UUID `feedback_id`, sentiment starts NULL, never accepts a client sentiment
    - Implement `get(feedback_id)` and `create_from_social(sf: SocialFeedback)` (source_type="social", platform from record, channel NULL)
    - Initialize DB from `schema.sql`; mirror the existing `SubmissionStore` connection handling
    - _Requirements: 1.7, 2.4, 4.1, 4.2, 4.3, 4.4, 6.1, 6.5_

  - [ ]* 2.2 Write property test for unique feedback_id
    - **Feature: feedback-triage-ticketing, Property 1: Unique feedback_id for every created feedback**
    - **Validates: Requirements 4.1, 4.2, 4.3**
    - File: `backend/tests/test_feedback_store_props.py` (Hypothesis, in-memory SQLite)

  - [x] 2.3 Add enrichment, triage, and linkage persistence methods to FeedbackStore
    - `update_enrichment(feedback_id, result, sentiment)`, `mark_enrichment_failed(feedback_id, reason, status)`
    - `set_triage(feedback_id, outcome, *, decision_source, needs_review)`
    - `link_ticket(feedback_id, ticket_id)` enforcing at most one ticket per feedback (replace-or-reject atomically)
    - _Requirements: 2.2, 2.3, 2.6, 2.7, 3.3, 3.8, 5.3, 5.4, 5.5, 5.7_

  - [ ]* 2.4 Write property test for no_action ⇒ no ticket (store side)
    - **Feature: feedback-triage-ticketing, Property 4: no_action feedback never has a ticket link**
    - **Validates: Requirements 3.3, 5.5**
    - File: `backend/tests/test_feedback_store_props.py`

  - [x] 2.5 Add admin query and status-view methods to FeedbackStore
    - `get_status_view(feedback_id)` (enrichment_status, triage_outcome, linked ticket, analysis_in_progress)
    - `list_for_admin(limit, offset)`, `list_needs_review(limit, offset)`, `aggregate_counts()` (by sentiment and triage_outcome)
    - _Requirements: 9.1, 9.2, 9.4, 10.1, 10.2, 10.3_

- [x] 3. Triage_Engine
  - [x] 3.1 Implement the pure decision core in `backend/app/services/triage_engine.py`
    - Define `TriageInput`, `TriageDecision` dataclasses
    - Implement `decide(inp)` with the four-branch rule and env-overridable thresholds (`ACTION_SEVERITY_THRESHOLD=3`, `NO_ACTION_SEVERITY_MAX=2`)
    - Non-completed enrichment (failed/timeout) → `needs_review=True`, `outcome=None`; ambiguous → needs_review
    - _Requirements: 3.1, 3.5, 3.9_

  - [ ]* 3.2 Write property test for decide() totality and determinism
    - **Feature: feedback-triage-ticketing, Property 7: Triage decide() is total and deterministic**
    - **Validates: Requirements 3.1, 3.5, 3.9**
    - File: `backend/tests/test_triage_props.py` (Hypothesis, pure core, no DB/network)

  - [ ]* 3.3 Write unit tests for each decide() branch
    - Worked examples for action_required, no_action, ambiguous needs_review, and failed/timeout → needs_review
    - File: `backend/tests/test_triage_engine.py`
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.9_

  - [x] 3.4 Implement the `run_triage(feedback_id)` persistence wrapper
    - Load feedback, build `TriageInput`, call `decide`
    - action_required → `TicketingPipeline.create_ticket` + link, set outcome + `decision_source=automated`, `needs_review=0`
    - no_action → set outcome, leave ticket_id NULL
    - needs_review → `needs_review=1`, `decision_source=automated`, outcome NULL
    - Wrap all DB/ticket ops in try/except → on any exception set `needs_review=1`
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.8, 3.9, 5.3_

  - [ ]* 3.5 Write property test for decision_source recording
    - **Feature: feedback-triage-ticketing, Property 8: Triage decision_source recording**
    - **Validates: Requirements 3.8**
    - File: `backend/tests/test_triage_props.py` (automated route-to-review then admin decision)

- [x] 4. Ticketing pipeline and comment store
  - [x] 4.1 Rework `backend/app/services/ticketing_pipeline.py` for independent tickets
    - `create_ticket(*, feedback_id, issue_category, description, priority="high")` creating an independent ticket and linking the originating feedback
    - `link_feedback(ticket_id, feedback_id)` (many-to-one; succeeds for any valid ticket incl. zero-linked)
    - `advance_status(ticket_id)`, `list_active_with_counts()` (linked_feedback_count), `get_with_feedback_ids(ticket_id)`
    - Remove old status→progress side effects on `submissions`
    - _Requirements: 5.2, 5.3, 5.4, 5.6, 5.7, 10.4, 10.5_

  - [ ]* 4.2 Write property test for at-most-one-ticket-per-feedback
    - **Feature: feedback-triage-ticketing, Property 5: A feedback links to at most one ticket at any time**
    - **Validates: Requirements 5.1, 5.7**
    - File: `backend/tests/test_ticket_linkage_props.py` (Hypothesis sequence of link calls)

  - [ ]* 4.3 Write property test for linking to any valid ticket
    - **Feature: feedback-triage-ticketing, Property 6: Linking to any valid ticket succeeds regardless of its current link count**
    - **Validates: Requirements 5.2, 5.7**
    - File: `backend/tests/test_ticket_linkage_props.py`

  - [x] 4.4 Create `backend/app/services/ticket_comment_store.py`
    - `add(ticket_id, author, text)` (reject empty/whitespace via strip; raise not-found for unknown ticket)
    - `list_for_ticket(ticket_id)` ordered by created_at ASC, tie-broken by autoincrement id
    - _Requirements: 7.1, 7.2, 7.3, 7.5, 7.6, 8.5_

  - [ ]* 4.5 Write property test for comment ascending order
    - **Feature: feedback-triage-ticketing, Property 9: Ticket comments are returned in ascending created_at order**
    - **Validates: Requirements 7.5, 8.5**
    - File: `backend/tests/test_comment_store_props.py` (Hypothesis, equal-timestamp batches)

  - [ ]* 4.6 Write unit tests for comment store
    - 404 on unknown ticket, 422/rejection on empty/whitespace text, author/timestamp recorded
    - File: `backend/tests/test_comment_store.py`
    - _Requirements: 7.1, 7.2, 7.3, 7.6_

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Enrichment wiring to feedback + triage
  - [x] 6.1 Repoint `backend/app/services/enrichment.py` to FeedbackStore and invoke triage
    - `run_enrichment` calls `FeedbackStore` instead of `SubmissionStore`; on completion records NLP-derived sentiment via `update_enrichment`
    - Preserve 30s timeout, Gemini model-priority fallback, and graceful failure (failed/timeout via `mark_enrichment_failed`)
    - After any terminal status (completed/failed/timeout) invoke `TriageEngine.run_triage(feedback_id)`
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6, 2.7, 2.8, 3.1_

  - [ ]* 6.2 Write unit tests for enrichment wiring with faked pipeline
    - Stub pipeline: completed→sentiment recorded+triage runs; failed/timeout→status set + routed to review
    - File: `backend/tests/test_enrichment_wiring.py`
    - _Requirements: 2.2, 2.6, 2.7, 3.1, 3.9_

- [x] 7. Public feedback API and social ingestion adapter
  - [x] 7.1 Add feedback routes in `backend/app/routes/feedback.py` and register in `main.py`
    - `POST /api/feedback` (text + optional contact, NO sentiment): validate empty/whitespace (422 naming `text`) and >10000 (422 naming length limit) before any store call; create with source_type=direct, channel=web_form; enqueue `run_enrichment` background task; return 201 `{ feedback_id }`
    - `GET /api/feedback/{id}/status`: return status view (enrichment_status, triage_outcome, ticket, comments, analysis_in_progress); 404 for unknown id; "no ticket associated" + empty comments when unlinked
    - Retire `routes/submissions.py` endpoints (replace with the above)
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.1, 8.1, 8.2, 8.3, 9.1, 9.2, 9.3, 9.4_

  - [ ]* 7.2 Write property test: sentiment never client-supplied
    - **Feature: feedback-triage-ticketing, Property 2: Sentiment is never client-supplied and starts NULL**
    - **Validates: Requirements 2.3, 2.4**
    - File: `backend/tests/test_feedback_api_props.py` (Hypothesis + FastAPI TestClient, enrichment not yet run)

  - [ ]* 7.3 Write property test: validation failures create no row
    - **Feature: feedback-triage-ticketing, Property 3: Validation failures create no row**
    - **Validates: Requirements 1.4, 1.5, 1.6**
    - File: `backend/tests/test_feedback_api_props.py` (whitespace, oversized, empty+oversized)

  - [ ]* 7.4 Write unit tests for feedback API happy path and status view
    - 201 returns feedback_id; direct feedback gets source_type/channel; status 404 and pending → analysis-in-progress
    - Files: `backend/tests/test_feedback_api.py`, `backend/tests/test_status_view.py`
    - _Requirements: 1.3, 1.7, 1.8, 9.1, 9.3, 9.4_

  - [x] 7.5 Add the social ingestion adapter
    - Map a `SocialFeedback` from `nlp_processing/ingestion/social_listener.py` into `FeedbackStore.create_from_social` (source_type=social, platform, channel NULL); enrichment + triage run identically
    - _Requirements: 6.1, 6.5_

  - [ ]* 7.6 Write property test for status comment visibility and shared-ticket sharing (backend)
    - **Feature: feedback-triage-ticketing, Property 10: Customer status comment visibility and shared-ticket sharing**
    - **Validates: Requirements 8.1, 8.2, 8.4**
    - File: `backend/tests/test_status_view_props.py` (Hypothesis feedback/ticket/comment graphs)

- [x] 8. Admin API over the unified model
  - [x] 8.1 Rework `backend/app/routes/admin.py` review, triage, feedback detail, and dashboard endpoints
    - `GET /api/admin/review` → feedback where needs_review=1
    - `PATCH /api/admin/feedback/{id}/triage` (body `{ outcome, ticket_id? }`): create/link ticket for action_required, retain feedback-only for no_action; set decision_source=admin
    - `GET /api/admin/feedback/{id}` full record; `GET /api/admin/feedback` list rows with feedback_id, source_type, sentiment, enrichment status, triage_outcome, ticket_id
    - `GET /api/admin/dashboard` counts by sentiment and triage_outcome
    - All admin endpoints keep `Depends(require_admin)` session-token auth
    - _Requirements: 3.6, 3.7, 3.8, 10.1, 10.2, 10.3, 11.4_

  - [x] 8.2 Add ticket listing/advance and comment endpoints to admin routes
    - `GET /api/admin/tickets` including linked_feedback_count; `PATCH /api/admin/tickets/{id}/advance` reflected in all linked feedback status
    - `POST /api/admin/tickets/{id}/comments` (404 unknown ticket, 422 empty/whitespace) and `GET /api/admin/tickets/{id}/comments` (ascending order)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 10.4, 10.5_

  - [ ]* 8.3 Write unit tests for admin auth and triage endpoints
    - 401 on admin endpoints without valid session token; admin triage sets decision_source=admin and links/omits ticket per outcome
    - File: `backend/tests/test_admin_auth.py`
    - _Requirements: 3.6, 3.7, 7.4, 11.4_

- [x] 9. Preserve marketing and trend analysis over the unified model
  - [x] 9.1 Repoint marketing and trends to feedback records
    - `GET /api/admin/marketing` sourced from positive-sentiment feedback; `POST /api/admin/trends` aggregates themes/sentiment/severity over all feedback incl. no_action
    - Update `services/marketing_engine.py` consumers as needed
    - _Requirements: 11.1, 11.2, 11.3_

  - [ ]* 9.2 Write unit tests for marketing/trend sourcing
    - Positive feedback surfaces in marketing; no_action feedback still included in trend aggregation
    - File: `backend/tests/test_analytics_unified.py`
    - _Requirements: 11.1, 11.2, 11.3_

- [x] 10. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Non-destructive data migration
  - [x] 11.1 Implement `backend/app/migrations/migrate_to_feedback.py`
    - Runnable as `python -m app.migrations.migrate_to_feedback`; `init_db()` first so new tables coexist with legacy
    - Copy submissions → feedback (reuse legacy UUID as feedback_id via `INSERT OR IGNORE`; preserve text, created_at, enrichment_result/status; retain self-selected sentiment only where no NLP sentiment; source_type=direct, channel=web_form)
    - Copy tickets → new tickets and set `feedback.ticket_id` on the originating feedback
    - admin_review_queue rows → needs_review=1, triage_outcome NULL, decision_source NULL
    - Never drop/mutate legacy tables; report rows read vs written
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7_

  - [ ]* 11.2 Write property test for migration parity and idempotency
    - **Feature: feedback-triage-ticketing, Property 12: Migration parity and idempotency**
    - **Validates: Requirements 12.1, 12.2, 12.7**
    - File: `backend/tests/test_migration_props.py` (Hypothesis-seeded legacy DB; run, assert, re-run, assert no growth)

  - [ ]* 11.3 Write migration integration test against a seeded legacy DB
    - Count parity, ticket links established, admin-queue rows preserved as needs_review, legacy tables untouched
    - File: `backend/tests/test_migration_integration.py`
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7_

- [x] 12. Frontend API client
  - [x] 12.1 Update `frontend/src/api/client.ts`
    - Replace `createSubmission`/`getSubmissionStatus` with `createFeedback` (text + optional contact, no sentiment) and `getFeedbackStatus`
    - Add `createComment`, `listComments`, `submitTriage`, `getReviewList`
    - _Requirements: 1.1, 1.8, 7.1, 7.5, 8.1, 9.1, 10.2_

  - [ ]* 12.2 Update `frontend/src/api/client.test.ts`
    - Assert createFeedback payload contains no sentiment field; new methods hit expected endpoints
    - _Requirements: 1.2, 2.4_

- [x] 13. Frontend single feedback form (replace sentiment flow)
  - [x] 13.1 Add `frontend/src/pages/FeedbackForm.tsx` and rewire routes in `App.tsx`
    - Single textarea + optional contact, calling `createFeedback`; no sentiment control
    - Make `LandingPage` render/redirect to the feedback form
    - Remove `SentimentSelect.tsx`, `NegativeForm.tsx`, `PositiveForm.tsx`, `NeutralForm.tsx` and delete `/sentiment`, `/negative`, `/positive`, `/neutral` routes
    - _Requirements: 1.1, 1.2, 2.4_

  - [ ]* 13.2 Write unit/routing tests for the feedback form
    - Single textarea, no sentiment control present, submit calls createFeedback with no sentiment; legacy routes removed
    - File: `frontend/src/__tests__/FeedbackForm.test.tsx`
    - _Requirements: 1.1, 1.2, 2.4_

- [x] 14. Frontend status view with feedback_id, ticket status, and comments
  - [x] 14.1 Update `StatusLookup.tsx` and `StatusTracker.tsx`
    - Key lookup by `feedback_id`; render enrichment status, triage outcome, linked ticket status, and ticket comments (author + timestamp, ascending), or a "no ticket associated" message
    - Add a pure `statusView` render-model mapping used by the component (for property testing)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 9.1, 9.2, 9.4_

  - [ ]* 14.2 Write property test for status comment visibility mapping (frontend)
    - **Feature: feedback-triage-ticketing, Property 10: Customer status comment visibility and shared-ticket sharing**
    - **Validates: Requirements 8.1, 8.2, 8.4**
    - File: `frontend/src/__tests__/StatusTracker.props.test.tsx` (fast-check over render-model mapping)

- [x] 15. Frontend admin views over the unified model
  - [x] 15.1 Add a source/platform display helper and rework `SubmissionDetail.tsx` → `FeedbackDetail.tsx`
    - Add `frontend/src/utils/sourceDisplay.ts`: social → platform (empty string, no placeholder, when missing); direct → channel; never throws
    - FeedbackDetail: comments panel (list + create) and source/platform/channel display
    - _Requirements: 6.2, 6.3, 6.4, 7.5_

  - [x] 15.2 Update `ReviewQueue.tsx` and `TicketList.tsx`
    - ReviewQueue: list needs_review feedback with a manual triage action (submitTriage)
    - TicketList: show `linked_feedback_count`; AdminDashboard rows show source_type (+platform/channel per rules)
    - _Requirements: 6.2, 6.3, 6.4, 10.1, 10.2, 10.4_

  - [ ]* 15.3 Write property test for platform/channel display selection
    - **Feature: feedback-triage-ticketing, Property 11: Platform/channel display selection**
    - **Validates: Requirements 6.2, 6.3, 6.4**
    - File: `frontend/src/__tests__/sourceDisplay.props.test.ts` (fast-check, incl. null platform)

  - [ ]* 15.4 Write unit tests for admin feedback detail and review queue
    - Comments panel renders/posts; source/platform/channel columns per rules; triage action present for needs_review
    - File: `frontend/src/__tests__/FeedbackDetail.test.tsx`
    - _Requirements: 6.2, 6.3, 6.4, 7.5, 10.2_

- [ ] 16. Integration wiring and end-to-end tests
  - [ ]* 16.1 Write backend end-to-end integration test
    - Submit → faked enrichment completed with chosen sentiment/severity → triage → assert ticket created or feedback-only per outcome → advance ticket → assert Status_View reflects change for all linked feedback; separate case forces failure/timeout → routed to review
    - File: `backend/tests/test_integration_flow.py`
    - _Requirements: 2.1, 3.1, 3.2, 3.3, 3.9, 5.3, 9.2, 10.5_

  - [ ]* 16.2 Write social ingestion integration test
    - Feed a SocialFeedback through the adapter; assert source_type=social, platform persisted, enrichment+triage run identically
    - File: `backend/tests/test_social_ingestion.py`
    - _Requirements: 6.1, 6.5_

  - [ ]* 16.3 Write frontend integration tests (React Testing Library)
    - Status lookup renders enrichment status, triage outcome, linked ticket status, comments, or "no ticket associated"; admin review queue renders triage action for needs_review
    - Files: `frontend/src/pages/StatusLookup.test.tsx`, `frontend/src/pages/admin/ReviewQueue.test.tsx`
    - _Requirements: 8.1, 8.2, 9.1, 9.2, 10.2_

- [~] 17. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (test-related or nice-to-have) and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each task references specific requirement sub-clauses for traceability.
- All 12 correctness properties are implemented as property-based tests (Hypothesis backend, fast-check frontend) in the exact files named in the design's Testing Strategy, each tagged `Feature: feedback-triage-ticketing, Property {n}: ...` and run for a minimum of 100 iterations.
- Gemini/enrichment is faked in every test; no test performs real network I/O.
- Legacy tables are preserved; the migration is non-destructive and idempotent.
- Checkpoints (tasks 5, 10, 17) ensure incremental validation at natural boundaries.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1", "3.1", "4.4"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.2", "3.3", "4.1", "4.5", "4.6"] },
    { "id": 3, "tasks": ["2.4", "2.5", "3.4", "4.2", "4.3"] },
    { "id": 4, "tasks": ["3.5", "6.1"] },
    { "id": 5, "tasks": ["6.2", "7.1", "7.5"] },
    { "id": 6, "tasks": ["7.2", "7.3", "7.4", "7.6", "8.1", "8.2"] },
    { "id": 7, "tasks": ["8.3", "9.1", "11.1"] },
    { "id": 8, "tasks": ["9.2", "11.2", "11.3", "12.1"] },
    { "id": 9, "tasks": ["12.2", "13.1", "14.1", "15.1"] },
    { "id": 10, "tasks": ["13.2", "14.2", "15.2", "15.3", "16.1", "16.2"] },
    { "id": 11, "tasks": ["15.4", "16.3"] }
  ]
}
```
