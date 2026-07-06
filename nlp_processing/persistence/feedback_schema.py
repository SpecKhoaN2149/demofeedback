"""Database schema migration for feedback routing tables.

Implements Requirements 17, 18, 19, 20, 21:
- Feedback table with source metadata, processing status, and constraints.
- Feedback analysis table with NLP output columns and score range checks.
- Tickets table with lifecycle phase, department assignment, and resolution tracking.
- Feedback-ticket link table with unique feedback constraint and cascade deletes.
- Clusters table with volume tracking, status lifecycle, and priority levels.

Uses SQLite with WAL mode for concurrent read/write performance.
"""

from __future__ import annotations

import sqlite3


_FEEDBACK_SCHEMA_SQL = """\
-- Feedback table (Requirement 17)
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id TEXT PRIMARY KEY NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('social', 'widget')),
    platform TEXT CHECK (length(platform) <= 50),
    message_text TEXT NOT NULL CHECK (length(trim(message_text)) >= 1 AND length(message_text) <= 10000),
    customer_id TEXT CHECK (length(customer_id) <= 100),
    created_at_original TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    recency_score REAL CHECK (recency_score IS NULL OR (recency_score >= 0.0 AND recency_score <= 1.0)),
    channel_metadata TEXT,
    processing_status TEXT NOT NULL DEFAULT 'ingested'
        CHECK (processing_status IN ('ingested','preprocessing','preprocessed','analyzing','analyzed','routing','routed','retrying','failed')),
    routing_action TEXT CHECK (length(routing_action) <= 50)
);

CREATE INDEX IF NOT EXISTS idx_feedback_ingested_at ON feedback(ingested_at);

-- Clusters table (Requirement 21) — created before feedback_analysis due to FK reference
CREATE TABLE IF NOT EXISTS clusters (
    cluster_id TEXT PRIMARY KEY NOT NULL,
    theme TEXT NOT NULL CHECK (length(theme) <= 120),
    cluster_summary TEXT CHECK (cluster_summary IS NULL OR length(cluster_summary) <= 500),
    volume_count INTEGER NOT NULL CHECK (volume_count >= 1) DEFAULT 1,
    sentiment_trend TEXT CHECK (sentiment_trend IS NULL OR length(sentiment_trend) <= 50),
    priority_level TEXT NOT NULL CHECK (priority_level IN ('low', 'medium', 'high', 'critical')),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'monitoring', 'resolved')) DEFAULT 'active'
);

-- Feedback Analysis table (Requirement 18)
CREATE TABLE IF NOT EXISTS feedback_analysis (
    feedback_id TEXT PRIMARY KEY NOT NULL REFERENCES feedback(feedback_id),
    sentiment_label TEXT NOT NULL CHECK (sentiment_label IN ('positive', 'neutral', 'negative')),
    sentiment_score REAL NOT NULL CHECK (sentiment_score >= -1.0 AND sentiment_score <= 1.0),
    priority_score REAL NOT NULL CHECK (priority_score >= 0.0 AND priority_score <= 1.0),
    priority_level TEXT NOT NULL CHECK (priority_level IN ('low', 'medium', 'high', 'critical')),
    theme_primary TEXT NOT NULL,
    theme_secondary TEXT,
    intent TEXT NOT NULL,
    cluster_id TEXT REFERENCES clusters(cluster_id),
    requires_action INTEGER NOT NULL,
    entities TEXT,
    processed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feedback_analysis_processed_at ON feedback_analysis(processed_at);

-- Tickets table (Requirement 19)
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id TEXT PRIMARY KEY NOT NULL,
    ticket_phase TEXT NOT NULL CHECK (ticket_phase IN ('new','triaged','routed','in_progress','waiting','resolved','closed','auto_closed')),
    priority_level TEXT NOT NULL CHECK (priority_level IN ('low', 'medium', 'high', 'critical')),
    assigned_department TEXT NOT NULL CHECK (assigned_department IN ('Network_Operations','Billing_Support','Technical_Support','Field_Operations','Digital_Product','Customer_Care','Retention','Social_Media_Care','Executive_Escalations')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolution_type TEXT CHECK (resolution_type IS NULL OR resolution_type IN ('resolved_by_agent','auto_resolved','duplicate','known_resolved','no_action_required','faq_matched')),
    resolution_notes TEXT CHECK (resolution_notes IS NULL OR length(resolution_notes) <= 2000),
    linked_cluster_id TEXT REFERENCES clusters(cluster_id)
);

CREATE INDEX IF NOT EXISTS idx_tickets_dept_phase ON tickets(assigned_department, ticket_phase);

-- Feedback-Ticket Link table (Requirement 20)
CREATE TABLE IF NOT EXISTS feedback_ticket_link (
    feedback_id TEXT NOT NULL UNIQUE REFERENCES feedback(feedback_id) ON DELETE CASCADE,
    ticket_id TEXT NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE
);
"""


def initialize_feedback_schema(conn: sqlite3.Connection) -> None:
    """Create feedback routing tables if they do not already exist.

    Sets WAL journal mode for concurrent read/write performance, enables
    foreign key enforcement, and creates all tables and indexes.

    Parameters
    ----------
    conn : sqlite3.Connection
        An open SQLite connection. The caller is responsible for managing
        the connection lifecycle.
    """
    # Enable WAL mode for better concurrency
    conn.execute("PRAGMA journal_mode=WAL")
    # Enable foreign key constraint enforcement
    conn.execute("PRAGMA foreign_keys=ON")
    # Create all tables and indexes
    conn.executescript(_FEEDBACK_SCHEMA_SQL)
