"""Unit tests for TicketingPipeline service."""

import os
import tempfile
import uuid
from datetime import datetime, timezone

import pytest

# Set the DB path before importing app modules
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["SUBMISSIONS_DB_PATH"] = _tmp_db.name
_tmp_db.close()

from app.database import get_connection, init_db
from app.services.ticketing_pipeline import TicketingPipeline


@pytest.fixture(autouse=True)
def setup_db():
    """Initialize a fresh database for each test."""
    init_db()
    with get_connection() as conn:
        conn.execute("DELETE FROM state_transitions")
        conn.execute("DELETE FROM tickets")
        conn.execute("DELETE FROM submissions")
        conn.commit()
    yield


def _create_submission(submission_id: str | None = None, progress: int = 50) -> str:
    """Helper to insert a negative submission record for FK constraints."""
    if submission_id is None:
        submission_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO submissions
            (id, created_at, customer_name, core_request, sentiment, progress_state,
             issue_category, detailed_description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                submission_id,
                now,
                "Test User",
                "test request",
                "negative",
                progress,
                "billing",
                "Detailed description of the billing issue.",
            ),
        )
        conn.commit()
    return submission_id


class TestCreateTicket:
    def test_create_ticket_returns_ticket_with_correct_fields(self):
        pipeline = TicketingPipeline()
        sub_id = _create_submission()

        ticket = pipeline.create_ticket(sub_id, "billing", "Customer billing issue")

        assert isinstance(ticket.id, uuid.UUID)
        assert str(ticket.submission_id) == sub_id
        assert ticket.issue_category == "billing"
        assert ticket.description == "Customer billing issue"
        assert ticket.priority == "high"
        assert ticket.status == "open"
        assert isinstance(ticket.created_at, datetime)

    def test_create_ticket_generates_unique_uuid(self):
        pipeline = TicketingPipeline()
        sub_id1 = _create_submission()
        sub_id2 = _create_submission()

        ticket1 = pipeline.create_ticket(sub_id1, "billing", "Issue 1")
        ticket2 = pipeline.create_ticket(sub_id2, "outage", "Issue 2")

        assert ticket1.id != ticket2.id

    def test_create_ticket_persists_to_database(self):
        pipeline = TicketingPipeline()
        sub_id = _create_submission()

        ticket = pipeline.create_ticket(sub_id, "network_speed", "Slow connection")

        retrieved = pipeline.get_ticket(str(ticket.id))
        assert retrieved is not None
        assert retrieved.id == ticket.id
        assert retrieved.issue_category == "network_speed"
        assert retrieved.description == "Slow connection"

    def test_create_ticket_sets_priority_high(self):
        pipeline = TicketingPipeline()
        sub_id = _create_submission()

        ticket = pipeline.create_ticket(sub_id, "outage", "Service down")

        assert ticket.priority == "high"

    def test_create_ticket_sets_status_open(self):
        pipeline = TicketingPipeline()
        sub_id = _create_submission()

        ticket = pipeline.create_ticket(sub_id, "pricing", "Too expensive")

        assert ticket.status == "open"


class TestAdvanceStatus:
    def test_advance_open_to_in_progress(self):
        pipeline = TicketingPipeline()
        sub_id = _create_submission(progress=50)
        ticket = pipeline.create_ticket(sub_id, "billing", "Issue")

        advanced = pipeline.advance_status(str(ticket.id))

        assert advanced.status == "in_progress"

    def test_advance_in_progress_to_resolved(self):
        pipeline = TicketingPipeline()
        sub_id = _create_submission(progress=50)
        ticket = pipeline.create_ticket(sub_id, "billing", "Issue")

        # First advance: open → in_progress
        pipeline.advance_status(str(ticket.id))
        # Second advance: in_progress → resolved
        resolved = pipeline.advance_status(str(ticket.id))

        assert resolved.status == "resolved"

    def test_advance_resolved_raises_value_error(self):
        pipeline = TicketingPipeline()
        sub_id = _create_submission(progress=50)
        ticket = pipeline.create_ticket(sub_id, "billing", "Issue")

        pipeline.advance_status(str(ticket.id))  # open → in_progress
        pipeline.advance_status(str(ticket.id))  # in_progress → resolved

        with pytest.raises(ValueError, match="cannot advance from 'resolved'"):
            pipeline.advance_status(str(ticket.id))

    def test_advance_nonexistent_ticket_raises_value_error(self):
        pipeline = TicketingPipeline()
        fake_id = str(uuid.uuid4())

        with pytest.raises(ValueError, match="Ticket not found"):
            pipeline.advance_status(fake_id)

    def test_advance_to_in_progress_updates_submission_to_75(self):
        pipeline = TicketingPipeline()
        sub_id = _create_submission(progress=50)
        ticket = pipeline.create_ticket(sub_id, "billing", "Issue")

        pipeline.advance_status(str(ticket.id))

        with get_connection() as conn:
            row = conn.execute(
                "SELECT progress_state FROM submissions WHERE id = ?", (sub_id,)
            ).fetchone()
        assert row["progress_state"] == 75

    def test_advance_to_resolved_updates_submission_to_100(self):
        pipeline = TicketingPipeline()
        sub_id = _create_submission(progress=50)
        ticket = pipeline.create_ticket(sub_id, "billing", "Issue")

        pipeline.advance_status(str(ticket.id))  # → in_progress (75%)
        pipeline.advance_status(str(ticket.id))  # → resolved (100%)

        with get_connection() as conn:
            row = conn.execute(
                "SELECT progress_state FROM submissions WHERE id = ?", (sub_id,)
            ).fetchone()
        assert row["progress_state"] == 100

    def test_advance_records_state_transition(self):
        pipeline = TicketingPipeline()
        sub_id = _create_submission(progress=50)
        ticket = pipeline.create_ticket(sub_id, "billing", "Issue")

        pipeline.advance_status(str(ticket.id))

        with get_connection() as conn:
            transitions = conn.execute(
                "SELECT * FROM state_transitions WHERE submission_id = ? ORDER BY id ASC",
                (sub_id,),
            ).fetchall()

        # Should have at least one transition from advance
        assert len(transitions) >= 1
        last = transitions[-1]
        assert last["previous_state"] == 50
        assert last["new_state"] == 75
        assert last["timestamp"] is not None


class TestListActive:
    def test_list_active_empty(self):
        pipeline = TicketingPipeline()
        result = pipeline.list_active()
        assert result == []

    def test_list_active_returns_open_tickets(self):
        pipeline = TicketingPipeline()
        sub_id = _create_submission()
        ticket = pipeline.create_ticket(sub_id, "billing", "Issue")

        active = pipeline.list_active()
        assert len(active) == 1
        assert active[0].id == ticket.id
        assert active[0].status == "open"

    def test_list_active_returns_in_progress_tickets(self):
        pipeline = TicketingPipeline()
        sub_id = _create_submission(progress=50)
        ticket = pipeline.create_ticket(sub_id, "billing", "Issue")
        pipeline.advance_status(str(ticket.id))

        active = pipeline.list_active()
        assert len(active) == 1
        assert active[0].status == "in_progress"

    def test_list_active_excludes_resolved_tickets(self):
        pipeline = TicketingPipeline()
        sub_id = _create_submission(progress=50)
        ticket = pipeline.create_ticket(sub_id, "billing", "Issue")
        pipeline.advance_status(str(ticket.id))  # → in_progress
        pipeline.advance_status(str(ticket.id))  # → resolved

        active = pipeline.list_active()
        assert len(active) == 0

    def test_list_active_ordered_by_created_at_asc(self):
        pipeline = TicketingPipeline()
        ids = []
        for i in range(3):
            sub_id = _create_submission()
            ticket = pipeline.create_ticket(sub_id, "billing", f"Issue {i}")
            ids.append(ticket.id)

        active = pipeline.list_active()
        assert len(active) == 3
        for i, t in enumerate(active):
            assert t.id == ids[i]


class TestGetTicket:
    def test_get_ticket_returns_ticket(self):
        pipeline = TicketingPipeline()
        sub_id = _create_submission()
        ticket = pipeline.create_ticket(sub_id, "outage", "Service outage")

        retrieved = pipeline.get_ticket(str(ticket.id))
        assert retrieved is not None
        assert retrieved.id == ticket.id
        assert retrieved.issue_category == "outage"
        assert retrieved.description == "Service outage"

    def test_get_ticket_nonexistent_returns_none(self):
        pipeline = TicketingPipeline()
        fake_id = str(uuid.uuid4())

        result = pipeline.get_ticket(fake_id)
        assert result is None
