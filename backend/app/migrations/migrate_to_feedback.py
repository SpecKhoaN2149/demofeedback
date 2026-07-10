"""Non-destructive migration from the legacy submissions/tickets model into the
unified ``feedback`` model (Requirement 12).

Run as a module::

    python -m app.migrations.migrate_to_feedback

Design (see .kiro/specs/feedback-triage-ticketing/design.md "Migration Plan"):

* ``init_db()`` runs first so the new tables (``feedback``, ``tickets``,
  ``ticket_comments``) exist alongside the legacy tables.
* Each legacy ``submissions`` row is copied into ``feedback`` via
  ``INSERT OR IGNORE`` reusing the legacy UUID as ``feedback_id``. Reusing the
  id is what makes the migration idempotent: re-running never duplicates a row.
* Legacy ``tickets`` rows are copied into the new-shape ``tickets`` table
  reusing the legacy id as ``ticket_id``, and the originating feedback (mapped
  from the legacy ticket's ``submission_id``) is linked via
  ``feedback.ticket_id``.
* Legacy tables ``submissions``, ``state_transitions``, ``admin_review_queue``
  and ``marketing_log`` are NEVER dropped or mutated (Requirement 12.7).

Legacy-vs-new tickets detection
-------------------------------
The current ``schema.sql`` REPLACED the legacy ``tickets`` table with a new,
independent shape (``ticket_id`` PK, no ``submission_id``). A pre-existing older
database may still contain the LEGACY ``tickets`` shape (``id`` PK,
``submission_id``, ...). We inspect ``PRAGMA table_info(tickets)`` at runtime:

* If the ``tickets`` table has a ``submission_id`` column -> it is legacy. Its
  rows are read into memory, the legacy table is preserved verbatim by copying
  it to ``tickets_legacy`` (so no data is lost), the ``tickets`` name is then
  rebuilt into the new shape, and the legacy rows are migrated in.
* If it only has ``ticket_id`` (the new/empty shape) -> there is nothing legacy
  to migrate and the ticket transform is skipped. This is also the state on any
  re-run, which is what keeps the migration idempotent.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.database import get_connection, init_db


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_columns(conn, table: str) -> set[str]:
    """Return the set of column names for ``table`` (empty if it doesn't exist)."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def _table_names(conn) -> set[str]:
    """Return the set of table names present in the database."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {row["name"] for row in rows}


def _tickets_is_legacy(conn) -> bool:
    """A ``tickets`` table is legacy when it carries a ``submission_id`` column."""
    cols = _table_columns(conn, "tickets")
    return "submission_id" in cols


def _extract_and_rebuild_legacy_tickets() -> list[dict]:
    """If ``tickets`` is legacy-shaped, read its rows, preserve them verbatim in
    ``tickets_legacy``, then rebuild ``tickets`` in the new shape.

    Returns the list of legacy ticket rows (as dicts) to migrate. Returns an
    empty list when ``tickets`` is already the new shape (nothing to do), which
    is the normal state on any re-run.
    """
    with get_connection() as conn:
        if not _tickets_is_legacy(conn):
            return []

        legacy_rows = [dict(r) for r in conn.execute("SELECT * FROM tickets").fetchall()]

        # Preserve the legacy table verbatim so no data is lost (non-destructive).
        if "tickets_legacy" not in _table_names(conn):
            conn.execute("CREATE TABLE tickets_legacy AS SELECT * FROM tickets")

        # Drop the legacy `tickets` so the new-shape table can take the name.
        # feedback.ticket_id is NULL for every row at this point (links are set
        # later), so no foreign-key rows are orphaned.
        conn.execute("DROP TABLE tickets")
        conn.commit()

    # Recreate the new-shape `tickets` (and any other missing tables) from schema.
    init_db()
    return legacy_rows


def migrate() -> dict:
    """Perform the non-destructive, idempotent migration.

    Returns a report dict with rows read vs written for submissions and tickets.
    """
    # 1. Ensure new tables coexist with legacy ones (Req 12 general).
    init_db()

    # 2. Handle a legacy-shaped `tickets` table (older DBs). No-op on re-run.
    legacy_ticket_rows = _extract_and_rebuild_legacy_tickets()

    submissions_read = 0
    feedback_written = 0
    tickets_read = 0
    tickets_written = 0

    with get_connection() as conn:
        # --------------------------------------------------------------
        # 3. Migrate legacy tickets into the new-shape `tickets` table and
        #    build a submission_id -> ticket_id map. Insert tickets BEFORE the
        #    feedback that references them (feedback.ticket_id is a FK).
        # --------------------------------------------------------------
        ticket_by_submission: dict[str, str] = {}
        for trow in legacy_ticket_rows:
            tickets_read += 1
            new_ticket_id = str(trow["id"])          # reuse legacy id as ticket_id
            sub_id = trow.get("submission_id")
            created_at = trow.get("created_at") or _utcnow_iso()

            cur = conn.execute(
                """
                INSERT OR IGNORE INTO tickets (
                    ticket_id, issue_category, description, priority, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    new_ticket_id,
                    trow.get("issue_category"),
                    trow.get("description"),
                    trow.get("priority") or "high",
                    trow.get("status") or "open",
                    created_at,
                ),
            )
            tickets_written += cur.rowcount

            if sub_id is not None:
                ticket_by_submission[str(sub_id)] = new_ticket_id
        conn.commit()

        # --------------------------------------------------------------
        # 4. Which submissions are in the legacy admin review queue?
        # --------------------------------------------------------------
        queued_ids: set[str] = set()
        if "admin_review_queue" in _table_names(conn):
            for qrow in conn.execute(
                "SELECT submission_id FROM admin_review_queue"
            ).fetchall():
                queued_ids.add(str(qrow["submission_id"]))

        # --------------------------------------------------------------
        # 5. submissions -> feedback (INSERT OR IGNORE, reuse legacy UUID).
        # --------------------------------------------------------------
        if "submissions" in _table_names(conn):
            for srow in conn.execute("SELECT * FROM submissions").fetchall():
                submissions_read += 1
                sub_id = str(srow["id"])

                linked_ticket_id = ticket_by_submission.get(sub_id)
                if sub_id in queued_ids:
                    # Preserve pending-review state exactly (Req 12.6).
                    needs_review = 1
                    triage_outcome = None
                    ticket_id = None
                elif linked_ticket_id is not None:
                    # Derived from a legacy ticket link (Req 12.4).
                    needs_review = 0
                    triage_outcome = "action_required"
                    ticket_id = linked_ticket_id
                else:
                    # Safe default: route to admin review; don't trust the
                    # self-selected sentiment to make a triage decision.
                    needs_review = 1
                    triage_outcome = None
                    ticket_id = None

                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO feedback (
                        feedback_id, text, source_type, channel, platform, created_at,
                        enrichment_status, enrichment_result, sentiment, triage_outcome,
                        triage_decision_source, needs_review, ticket_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sub_id,                     # feedback_id = legacy id (Req 12.1)
                        srow["core_request"],       # text (Req 12.2)
                        "direct",                   # source_type (Req 12.5)
                        "web_form",                 # channel (Req 12.5)
                        None,                       # platform (no social attribution)
                        srow["created_at"],         # created_at preserved (Req 12.2)
                        srow["enrichment_status"],  # enrichment_status preserved (Req 12.2)
                        srow["enrichment_result"],  # enrichment_result preserved (Req 12.2)
                        srow["sentiment"],          # retain self-selected sentiment (Req 12.3)
                        triage_outcome,
                        None,                       # decision_source NULL on migration (Req 12.6)
                        needs_review,
                        ticket_id,
                    ),
                )
                feedback_written += cur.rowcount
            conn.commit()

        # --------------------------------------------------------------
        # 6. Link step (Req 12.4): ensure feedback.ticket_id points at the
        #    migrated ticket. Idempotent, and repairs the link if the feedback
        #    row pre-existed from a partial prior run.
        # --------------------------------------------------------------
        for sub_id, new_ticket_id in ticket_by_submission.items():
            conn.execute(
                """
                UPDATE feedback
                SET ticket_id = ?
                WHERE feedback_id = ? AND ticket_id IS NULL
                """,
                (new_ticket_id, sub_id),
            )
        conn.commit()

    report = {
        "submissions_read": submissions_read,
        "feedback_written": feedback_written,
        "tickets_read": tickets_read,
        "tickets_written": tickets_written,
    }
    _print_report(report)
    return report


def _print_report(report: dict) -> None:
    print("Migration to unified feedback model complete (non-destructive).")
    print(
        f"  submissions read: {report['submissions_read']:>5}  ->  "
        f"feedback written: {report['feedback_written']:>5}"
    )
    print(
        f"  tickets read:     {report['tickets_read']:>5}  ->  "
        f"tickets written:  {report['tickets_written']:>5}"
    )
    print(
        "  legacy tables left intact (submissions, state_transitions, "
        "admin_review_queue, marketing_log)."
    )


if __name__ == "__main__":
    migrate()
