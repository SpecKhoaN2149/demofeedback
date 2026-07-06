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

CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,               -- UUID
    submission_id TEXT NOT NULL REFERENCES submissions(id),
    issue_category TEXT NOT NULL,
    description TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'high',
    status TEXT NOT NULL DEFAULT 'open'
        CHECK(status IN ('open','in_progress','resolved')),
    created_at TEXT NOT NULL            -- ISO 8601 UTC
);

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
