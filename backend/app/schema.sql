-- Spectrum Feedback Submissions Database Schema
-- All timestamps stored as ISO 8601 UTC text

CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY,               -- UUID
    created_at TEXT NOT NULL,           -- ISO 8601 UTC
    customer_name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    core_request TEXT NOT NULL,
    sentiment TEXT NOT NULL CHECK(sentiment IN ('negative','positive','neutral')),
    progress_state INTEGER NOT NULL CHECK(progress_state IN (25,50,75,100)),
    issue_category TEXT,
    detailed_description TEXT,
    praise_text TEXT,
    social_sharing INTEGER NOT NULL DEFAULT 0,
    comment_text TEXT,
    enrichment_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(enrichment_status IN ('pending','completed','failed','timeout')),
    enrichment_result TEXT              -- JSON blob
);

CREATE TABLE IF NOT EXISTS state_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT NOT NULL REFERENCES submissions(id),
    previous_state INTEGER NOT NULL,
    new_state INTEGER NOT NULL,
    timestamp TEXT NOT NULL             -- ISO 8601 UTC
);

-- Feedback Triage & Ticketing Overhaul: unified feedback model.
-- The `tickets` table is redefined here as an independent, feedback-linked
-- entity (ticket_id PK, no mandatory submission_id FK). This replaces the
-- legacy 1:1 tickets shape because after this overhaul all runtime code uses
-- the new model; the non-destructive migration reads legacy rows via a
-- separate mechanism. The other legacy tables (submissions, state_transitions,
-- admin_review_queue, marketing_log) are intentionally kept intact.

-- Independent tickets (many feedback -> one ticket). Defined before `feedback`
-- so the feedback.ticket_id foreign key resolves cleanly.
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id TEXT PRIMARY KEY,                  -- UUID
    issue_category TEXT NOT NULL,
    description TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'high',
    status TEXT NOT NULL DEFAULT 'open'
        CHECK(status IN ('open','in_progress','resolved')),
    created_at TEXT NOT NULL                     -- ISO 8601 UTC
);

-- Unified feedback record (replaces the role of `submissions`)
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id TEXT PRIMARY KEY,                -- UUID
    text TEXT NOT NULL,                          -- free-form message
    source_type TEXT NOT NULL DEFAULT 'direct'
        CHECK(source_type IN ('direct','social')),
    channel TEXT,                                -- e.g. 'web_form' for direct
    platform TEXT
        CHECK(platform IS NULL OR platform IN ('reddit','x','facebook')),
    created_at TEXT NOT NULL,                    -- ISO 8601 UTC
    enrichment_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(enrichment_status IN ('pending','completed','failed','timeout')),
    enrichment_result TEXT,                      -- JSON blob
    sentiment TEXT
        CHECK(sentiment IS NULL OR sentiment IN ('positive','neutral','negative')),
    triage_outcome TEXT
        CHECK(triage_outcome IS NULL OR triage_outcome IN ('action_required','no_action')),
    triage_decision_source TEXT
        CHECK(triage_decision_source IS NULL OR triage_decision_source IN ('automated','admin')),
    needs_review INTEGER NOT NULL DEFAULT 0,     -- routed to admin triage
    ticket_id TEXT REFERENCES tickets(ticket_id), -- 0..1 ticket per feedback
    -- NLP-derived routing/analytics fields surfaced on the internal dashboard.
    department TEXT,                             -- assigned team, e.g. 'Network Operations'
    severity INTEGER,                            -- 1..10 severity (dashboard scale)
    severity_reasoning TEXT,                     -- why the NLP assigned that severity (ⓘ tooltip)
    location_city TEXT,                          -- best-effort city for map clustering
    location_state TEXT,                         -- 2-letter US state code
    latitude REAL,                               -- map marker latitude
    longitude REAL                               -- map marker longitude
);
CREATE INDEX IF NOT EXISTS idx_feedback_ticket ON feedback(ticket_id);
CREATE INDEX IF NOT EXISTS idx_feedback_needs_review ON feedback(needs_review);

-- Internal staff comments on tickets
CREATE TABLE IF NOT EXISTS ticket_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,        -- tie-breaker for equal timestamps
    ticket_id TEXT NOT NULL REFERENCES tickets(ticket_id),
    author TEXT NOT NULL,                        -- admin username
    created_at TEXT NOT NULL,                    -- ISO 8601 UTC
    text TEXT NOT NULL                           -- non-empty enforced in service
);
CREATE INDEX IF NOT EXISTS idx_ticket_comments_ticket ON ticket_comments(ticket_id, created_at);

CREATE TABLE IF NOT EXISTS marketing_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT NOT NULL REFERENCES submissions(id),
    customer_name TEXT NOT NULL,
    praise_text TEXT NOT NULL,
    social_sharing INTEGER NOT NULL DEFAULT 0,
    social_status TEXT NOT NULL DEFAULT 'internal_only'
        CHECK(social_status IN ('shared','internal_only','generation_failed')),
    shareable_url TEXT,
    logged_at TEXT NOT NULL             -- ISO 8601 UTC
);

CREATE TABLE IF NOT EXISTS admin_review_queue (
    submission_id TEXT PRIMARY KEY REFERENCES submissions(id),
    queued_at TEXT NOT NULL             -- ISO 8601 UTC
);

CREATE TABLE IF NOT EXISTS admin_users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT                   -- ISO 8601 UTC or NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    username TEXT NOT NULL REFERENCES admin_users(username),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    invalidated INTEGER NOT NULL DEFAULT 0
);
