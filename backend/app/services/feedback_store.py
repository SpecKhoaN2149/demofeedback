"""FeedbackStore service for the unified feedback model (SQLite).

Evolution of :class:`SubmissionStore`. Mirrors the same connection handling
(``app.database.get_connection``), JSON parsing of enrichment results, and
timestamp conventions (ISO 8601 UTC text).

This module implements ONLY the core CRUD surface: ``create``, ``get`` and
``create_from_social``. Enrichment/triage/linkage persistence and admin query
methods are added in later tasks.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

from app.database import get_connection
from app.models.feedback import (
    Feedback,
    FeedbackCreate,
    StatusTicket,
    StatusView,
)
from app.models.submission import EnrichmentResult


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalize a datetime to naive UTC for safe comparison.

    Aware datetimes are converted to UTC then stripped of tzinfo; naive
    datetimes are assumed to already be in UTC and returned unchanged.
    """
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _severity_to_ten(score) -> int | None:
    """Map the NLP 1-5 ``severity_score`` onto the dashboard's 1-10 scale.

    Returns ``None`` when no score is available. A score of 5 → 10, 3 → 6,
    1 → 2, clamped to the valid 1-10 range.
    """
    if not isinstance(score, (int, float)):
        return None
    return max(1, min(10, round(score * 2)))


# Maps NLP theme labels (substring-matched, case-insensitive) to the internal
# department that should own the feedback. Order matters: earlier entries win.
_THEME_DEPARTMENT: list[tuple[str, str]] = [
    ("outage", "Network Operations"),
    ("connectivity", "Network Operations"),
    ("network", "Network Operations"),
    ("speed", "Network Operations"),
    ("slow", "Network Operations"),
    ("latency", "Network Operations"),
    ("bill", "Billing"),
    ("charge", "Billing"),
    ("payment", "Billing"),
    ("price", "Billing"),
    ("pricing", "Billing"),
    ("refund", "Billing"),
    ("install", "Field Services"),
    ("appointment", "Field Services"),
    ("technician", "Field Services"),
    ("equipment", "Technical Support"),
    ("router", "Technical Support"),
    ("modem", "Technical Support"),
    ("device", "Technical Support"),
    ("cancel", "Retention"),
    ("retention", "Retention"),
    ("churn", "Retention"),
    ("promotion", "Marketing"),
    ("praise", "Marketing"),
    ("compliment", "Marketing"),
    ("support", "Customer Support"),
    ("service", "Customer Support"),
]

_DEFAULT_DEPARTMENT = "Customer Support"


def department_for_themes(themes) -> str:
    """Route feedback to a department from its detected NLP themes.

    Themes are the enrichment ``themes`` list (dicts carrying a ``theme`` key,
    or plain strings). Each theme label is substring-matched (case-insensitive)
    against ``_THEME_DEPARTMENT``; the first match wins. Falls back to
    ``Customer Support`` when nothing matches.
    """
    for theme in themes or []:
        label = ""
        if isinstance(theme, dict):
            label = str(theme.get("theme") or theme.get("name") or theme.get("label") or "")
        else:
            label = str(theme)
        label = label.lower()
        if not label:
            continue
        for keyword, dept in _THEME_DEPARTMENT:
            if keyword in label:
                return dept
    return _DEFAULT_DEPARTMENT


class FeedbackStore:
    """Manages CRUD operations for unified feedback records backed by SQLite."""

    def create(
        self,
        data: FeedbackCreate,
        *,
        source_type: str = "direct",
        channel: str | None = "web_form",
        platform: str | None = None,
    ) -> Feedback:
        """Create a new feedback record.

        Sentiment is NEVER client-supplied (Req 2.4); it starts NULL and is
        only ever populated later by the NLP enrichment pipeline. A fresh UUID
        ``feedback_id`` is generated for every record (Req 4.1, 4.2, 4.3).

        Args:
            data: The validated ``FeedbackCreate`` payload (text + optional contact).
            source_type: ``"direct"`` (default) or ``"social"``.
            channel: Origin channel for direct feedback (default ``"web_form"``).
            platform: Social platform for social feedback (``reddit``/``x``/``facebook``).

        Returns:
            The persisted :class:`Feedback` model.
        """
        feedback_id = str(uuid.uuid4())
        created_at = _utcnow_iso()

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO feedback (
                    feedback_id, text, source_type, channel, platform, created_at,
                    enrichment_status, enrichment_result, sentiment, triage_outcome,
                    triage_decision_source, needs_review, ticket_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    data.text,
                    source_type,
                    channel,
                    platform,
                    created_at,
                    "pending",
                    None,
                    None,
                    None,
                    None,
                    0,
                    None,
                ),
            )
            conn.commit()

        return Feedback(
            feedback_id=uuid.UUID(feedback_id),
            text=data.text,
            source_type=source_type,
            channel=channel,
            platform=platform,
            created_at=datetime.fromisoformat(created_at),
            enrichment_status="pending",
            enrichment_result=None,
            sentiment=None,
            triage_outcome=None,
            triage_decision_source=None,
            needs_review=False,
            ticket_id=None,
        )

    def get(self, feedback_id: uuid.UUID) -> Feedback | None:
        """Retrieve a full feedback record, or None if it does not exist.

        Hydrates the ``enrichment_result`` JSON via :class:`EnrichmentResult`
        (same approach as ``SubmissionStore``), converts the ``needs_review``
        integer to a bool, and parses timestamp/UUID fields.
        """
        fid = str(feedback_id)

        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM feedback WHERE feedback_id = ?", (fid,)
            ).fetchone()

        if row is None:
            return None

        return self._feedback_from_row(row)

    @staticmethod
    def _feedback_from_row(row) -> Feedback:
        """Hydrate a :class:`Feedback` model from a ``feedback`` table row.

        Centralizes the row → model mapping shared by ``get`` and the admin
        list methods: parses the ``enrichment_result`` JSON via
        :class:`EnrichmentResult`, converts ``needs_review`` to a bool, and
        parses timestamp/UUID fields.
        """
        enrichment_result = None
        if row["enrichment_result"]:
            enrichment_result = EnrichmentResult(**json.loads(row["enrichment_result"]))

        ticket_id = uuid.UUID(row["ticket_id"]) if row["ticket_id"] else None

        # Newer analytics columns may be absent on very old rows/DBs; read them
        # defensively so hydration never raises a KeyError.
        keys = set(row.keys())

        def col(name):
            return row[name] if name in keys else None

        return Feedback(
            feedback_id=uuid.UUID(row["feedback_id"]),
            text=row["text"],
            source_type=row["source_type"],
            channel=row["channel"],
            platform=row["platform"],
            created_at=datetime.fromisoformat(row["created_at"]),
            enrichment_status=row["enrichment_status"],
            enrichment_result=enrichment_result,
            sentiment=row["sentiment"],
            triage_outcome=row["triage_outcome"],
            triage_decision_source=row["triage_decision_source"],
            needs_review=bool(row["needs_review"]),
            ticket_id=ticket_id,
            department=col("department"),
            severity=col("severity"),
            severity_reasoning=col("severity_reasoning"),
            location_city=col("location_city"),
            location_state=col("location_state"),
            latitude=col("latitude"),
            longitude=col("longitude"),
        )

    def create_from_social(self, sf) -> Feedback:
        """Create a feedback record from a social listener ``SocialFeedback``.

        A fresh ``feedback_id`` (UUID) is generated for the feedback table; the
        originating record's own id is not reused. Reads attributes defensively
        so any ``SocialFeedback``-like object works.

        Args:
            sf: A ``nlp_processing`` ``SocialFeedback``-like object exposing
                ``message_text`` and ``platform``.

        Returns:
            The persisted :class:`Feedback` model (source_type="social",
            channel=None, platform taken from the record).
        """
        text = getattr(sf, "message_text", None) or ""
        platform = getattr(sf, "platform", None)

        return self.create(
            FeedbackCreate(text=text),
            source_type="social",
            channel=None,
            platform=platform,
        )

    def update_enrichment(
        self, feedback_id: uuid.UUID, result: EnrichmentResult, sentiment: str
    ) -> None:
        """Persist a completed NLP enrichment result and derived sentiment.

        Stores ``result`` as JSON, flips ``enrichment_status`` to ``completed``
        and records the NLP-derived ``sentiment`` (never client-supplied). Also
        derives the dashboard-facing analytics columns from the enrichment:

          - ``severity`` (1-10): the NLP ``severity_score`` (a 1-5 scale) mapped
            onto the dashboard's 1-10 scale.
          - ``severity_reasoning``: the NLP ``severity_factors`` joined into a
            short human-readable explanation (backs the ⓘ tooltip).
          - ``department``: routed from the top detected theme via
            :func:`department_for_themes` so feedback lands with the right team.

        Args:
            feedback_id: The feedback record to update.
            result: The NLP :class:`EnrichmentResult` to persist as JSON.
            sentiment: The NLP-derived sentiment (``positive``/``neutral``/``negative``).
        """
        severity_10 = _severity_to_ten(result.severity_score)
        reasoning = "; ".join(result.severity_factors) if result.severity_factors else None
        department = department_for_themes(result.themes)

        with get_connection() as conn:
            conn.execute(
                """
                UPDATE feedback
                SET enrichment_result = ?, enrichment_status = ?, sentiment = ?,
                    severity = ?, severity_reasoning = ?, department = ?
                WHERE feedback_id = ?
                """,
                (
                    result.model_dump_json(),
                    "completed",
                    sentiment,
                    severity_10,
                    reasoning,
                    department,
                    str(feedback_id),
                ),
            )
            conn.commit()

    def update_location(
        self,
        feedback_id: uuid.UUID,
        *,
        city: str | None,
        state: str | None,
        latitude: float | None,
        longitude: float | None,
    ) -> None:
        """Persist the NLP-derived (or default) geographic location.

        Powers the dashboard's geographic clustering map. Called after
        enrichment with either a location extracted from the feedback text or
        the configured default when none is mentioned.
        """
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE feedback
                SET location_city = ?, location_state = ?, latitude = ?, longitude = ?
                WHERE feedback_id = ?
                """,
                (city, state, latitude, longitude, str(feedback_id)),
            )
            conn.commit()

    def mark_enrichment_failed(
        self, feedback_id: uuid.UUID, reason: str, status: str = "failed"
    ) -> None:
        """Mark enrichment as terminally unsuccessful (``failed`` or ``timeout``).

        There is no error column on the ``feedback`` table, so ``reason`` is not
        persisted; it is accepted for parity with the design signature and may
        be logged by callers. ``status`` is validated to the allowed set and
        defaults to ``failed`` for any unexpected value.

        Args:
            feedback_id: The feedback record to update.
            reason: Human-readable failure reason (not persisted).
            status: Either ``failed`` (default) or ``timeout``.
        """
        if status not in {"failed", "timeout"}:
            status = "failed"

        with get_connection() as conn:
            conn.execute(
                "UPDATE feedback SET enrichment_status = ? WHERE feedback_id = ?",
                (status, str(feedback_id)),
            )
            conn.commit()

    def set_triage(
        self,
        feedback_id: uuid.UUID,
        outcome: str | None,
        *,
        decision_source: str,
        needs_review: bool,
    ) -> None:
        """Record a triage decision on a feedback record (Req 3.8).

        Args:
            feedback_id: The feedback record to update.
            outcome: ``action_required``, ``no_action`` or ``None`` (routed to review).
            decision_source: ``automated`` or ``admin``.
            needs_review: Whether the record still requires manual review.
        """
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE feedback
                SET triage_outcome = ?, triage_decision_source = ?, needs_review = ?
                WHERE feedback_id = ?
                """,
                (
                    outcome,
                    decision_source,
                    1 if needs_review else 0,
                    str(feedback_id),
                ),
            )
            conn.commit()

    def link_ticket(self, feedback_id: uuid.UUID, ticket_id: uuid.UUID) -> None:
        """Link a feedback record to a ticket (Req 5.3, 5.4, 5.7).

        A feedback record holds at most one ticket: the ``ticket_id`` column
        stores a single value, so linking replaces any prior link. This
        naturally enforces the 0..1 ticket-per-feedback invariant.

        Args:
            feedback_id: The feedback record to link.
            ticket_id: The ticket to associate with the feedback.
        """
        with get_connection() as conn:
            conn.execute(
                "UPDATE feedback SET ticket_id = ? WHERE feedback_id = ?",
                (str(ticket_id), str(feedback_id)),
            )
            conn.commit()

    def get_status_view(self, feedback_id: uuid.UUID) -> StatusView | None:
        """Build the customer-facing status payload for a feedback record.

        Returns ``None`` if the feedback does not exist so the route layer can
        translate to a 404 (Req 9.3). Otherwise assembles a :class:`StatusView`
        with enrichment status, triage outcome, and an ``analysis_in_progress``
        flag that is ``True`` while enrichment is still ``pending`` (Req 9.1,
        9.4).

        When the feedback is linked to a ticket, the ticket's current status is
        surfaced via :class:`StatusTicket` and the ticket's comments are
        included ordered by ``created_at`` ascending (tie-broken by id) so all
        customers linked to the same ticket see the same thread (Req 8.1, 8.2,
        8.5, 9.2). When there is no linked ticket, ``ticket`` is ``None`` and
        ``comments`` is empty.
        """
        feedback = self.get(feedback_id)
        if feedback is None:
            return None

        ticket: StatusTicket | None = None
        comments: list = []

        if feedback.ticket_id is not None:
            with get_connection() as conn:
                trow = conn.execute(
                    "SELECT ticket_id, status FROM tickets WHERE ticket_id = ?",
                    (str(feedback.ticket_id),),
                ).fetchone()

            if trow is not None:
                ticket = StatusTicket(
                    ticket_id=uuid.UUID(trow["ticket_id"]),
                    status=trow["status"],
                )
                # Reuse the comment store so ordering rules stay in one place.
                from app.services.ticket_comment_store import TicketCommentStore

                comments = TicketCommentStore().list_for_ticket(trow["ticket_id"])

        return StatusView(
            feedback_id=feedback.feedback_id,
            enrichment_status=feedback.enrichment_status,
            triage_outcome=feedback.triage_outcome,
            ticket=ticket,
            comments=comments,
            analysis_in_progress=(feedback.enrichment_status == "pending"),
        )

    def list_for_admin(self, limit: int = 20, offset: int = 0) -> list[Feedback]:
        """List feedback records for the admin dashboard, newest first (Req 10.1).

        Returns hydrated :class:`Feedback` models ordered by ``created_at``
        descending, paginated by ``limit``/``offset``.
        """
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM feedback
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

        return [self._feedback_from_row(row) for row in rows]

    def list_needs_review(self, limit: int = 20, offset: int = 0) -> list[Feedback]:
        """List feedback routed to admin review, newest first (Req 10.2).

        Same shape as :meth:`list_for_admin` but restricted to records where
        ``needs_review = 1``.
        """
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM feedback
                WHERE needs_review = 1
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

        return [self._feedback_from_row(row) for row in rows]

    def list_positive(self, limit: int = 20, offset: int = 0) -> list[Feedback]:
        """List positive-sentiment feedback for the marketing capability (Req 11.3).

        Returns hydrated :class:`Feedback` models where the NLP-derived
        ``sentiment`` is ``"positive"``, newest first, paginated by
        ``limit``/``offset``.
        """
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM feedback
                WHERE sentiment = 'positive'
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

        return [self._feedback_from_row(row) for row in rows]

    def count_positive(self) -> int:
        """Return the total number of positive-sentiment feedback records (Req 11.3)."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM feedback WHERE sentiment = 'positive'"
            ).fetchone()
        return row["n"] if row else 0

    def count_needs_review(self) -> int:
        """Return the number of feedback records awaiting manual review."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM feedback WHERE needs_review = 1"
            ).fetchone()
        return row["n"] if row else 0

    def list_in_window(self, start: datetime, end: datetime) -> list[Feedback]:
        """List feedback whose ``created_at`` falls within ``[start, end]``.

        Includes every feedback record regardless of triage outcome (so
        ``no_action`` feedback is retained for Trend_Analysis, Req 11.1). Rows
        are filtered in Python so that naive/aware ``datetime`` bounds compare
        safely against the stored ISO 8601 UTC timestamps.
        """
        start_n = _to_naive_utc(start)
        end_n = _to_naive_utc(end)

        with get_connection() as conn:
            rows = conn.execute("SELECT * FROM feedback").fetchall()

        selected: list[Feedback] = []
        for row in rows:
            created = _to_naive_utc(datetime.fromisoformat(row["created_at"]))
            if start_n <= created <= end_n:
                selected.append(self._feedback_from_row(row))
        return selected

    def aggregate_counts(self) -> dict:
        """Aggregate feedback counts by sentiment and triage outcome (Req 10.3).

        Returns a dict of the form::

            {
                "by_sentiment": {"positive": 3, "unknown": 2, ...},
                "by_triage_outcome": {"action_required": 1, "unclassified": 4, ...},
            }

        NULL ``sentiment`` is mapped to ``"unknown"`` and NULL
        ``triage_outcome`` is mapped to ``"unclassified"``.
        """
        by_sentiment: dict[str, int] = {}
        by_triage_outcome: dict[str, int] = {}

        with get_connection() as conn:
            for row in conn.execute(
                "SELECT sentiment, COUNT(*) AS n FROM feedback GROUP BY sentiment"
            ).fetchall():
                key = row["sentiment"] if row["sentiment"] is not None else "unknown"
                by_sentiment[key] = row["n"]

            for row in conn.execute(
                "SELECT triage_outcome, COUNT(*) AS n FROM feedback GROUP BY triage_outcome"
            ).fetchall():
                key = (
                    row["triage_outcome"]
                    if row["triage_outcome"] is not None
                    else "unclassified"
                )
                by_triage_outcome[key] = row["n"]

        return {"by_sentiment": by_sentiment, "by_triage_outcome": by_triage_outcome}

    def dashboard_analytics(self, *, trend_days: int = 30) -> dict:
        """Aggregate feedback for the internal dashboard's visuals.

        Single pass over all feedback producing:
          - totals: overall counts (total, tickets, needs_review)
          - by_sentiment / by_triage_outcome
          - by_department: {department: count}
          - by_source: {"direct"|platform: count} (social split by platform)
          - by_state: [{state, count, avg_severity}] sorted by count desc
          - severity_distribution: {"1".."10": count} over completed records
          - avg_severity: mean 1-10 severity over completed records (or None)
          - time_series: [{date, total, negative, neutral, positive}] for the
            last ``trend_days`` days (ascending)
          - map_points: [{feedback_id, latitude, longitude, city, state,
            severity, sentiment, department, source_type, platform, ticket_id}]
            for records that carry coordinates
        """
        from collections import defaultdict

        by_sentiment: dict[str, int] = defaultdict(int)
        by_triage: dict[str, int] = defaultdict(int)
        by_department: dict[str, int] = defaultdict(int)
        by_source: dict[str, int] = defaultdict(int)
        state_count: dict[str, int] = defaultdict(int)
        state_sev_total: dict[str, int] = defaultdict(int)
        state_sev_n: dict[str, int] = defaultdict(int)
        severity_dist: dict[str, int] = {str(i): 0 for i in range(1, 11)}
        sev_total = 0
        sev_n = 0
        total = 0
        tickets_linked = 0
        needs_review = 0

        # Time-series buckets for the last `trend_days` days.
        today = datetime.now(timezone.utc).date()
        start_day = today - timedelta(days=trend_days - 1)
        series: dict[str, dict[str, int]] = {}
        d = start_day
        while d <= today:
            series[d.isoformat()] = {
                "date": d.isoformat(),
                "total": 0,
                "negative": 0,
                "neutral": 0,
                "positive": 0,
            }
            d = d + timedelta(days=1)

        map_points: list[dict] = []

        with get_connection() as conn:
            rows = conn.execute("SELECT * FROM feedback").fetchall()

        keys = set(rows[0].keys()) if rows else set()

        def col(row, name):
            return row[name] if name in keys else None

        for row in rows:
            total += 1
            sentiment = row["sentiment"]
            by_sentiment[sentiment or "unknown"] += 1
            by_triage[row["triage_outcome"] or "unclassified"] += 1
            if row["needs_review"]:
                needs_review += 1
            if row["ticket_id"]:
                tickets_linked += 1

            dept = col(row, "department")
            if dept:
                by_department[dept] += 1

            # Source: direct → "direct"; social → its platform.
            if row["source_type"] == "social" and row["platform"]:
                by_source[row["platform"]] += 1
            else:
                by_source["direct"] += 1

            sev = col(row, "severity")
            if isinstance(sev, int) and 1 <= sev <= 10:
                severity_dist[str(sev)] += 1
                sev_total += sev
                sev_n += 1

            state = col(row, "location_state")
            if state:
                state_count[state] += 1
                if isinstance(sev, int):
                    state_sev_total[state] += sev
                    state_sev_n[state] += 1

            # Time-series bucket.
            created_date = _to_naive_utc(
                datetime.fromisoformat(row["created_at"])
            ).date().isoformat()
            if created_date in series:
                series[created_date]["total"] += 1
                if sentiment in ("negative", "neutral", "positive"):
                    series[created_date][sentiment] += 1

            lat = col(row, "latitude")
            lng = col(row, "longitude")
            if lat is not None and lng is not None:
                map_points.append(
                    {
                        "feedback_id": row["feedback_id"],
                        "latitude": lat,
                        "longitude": lng,
                        "city": col(row, "location_city"),
                        "state": state,
                        "severity": sev,
                        "sentiment": sentiment,
                        "department": dept,
                        "source_type": row["source_type"],
                        "platform": row["platform"],
                        "ticket_id": row["ticket_id"],
                    }
                )

        by_state = sorted(
            (
                {
                    "state": s,
                    "count": state_count[s],
                    "avg_severity": round(state_sev_total[s] / state_sev_n[s], 1)
                    if state_sev_n[s]
                    else None,
                }
                for s in state_count
            ),
            key=lambda x: x["count"],
            reverse=True,
        )

        return {
            "totals": {
                "total": total,
                "tickets_linked": tickets_linked,
                "needs_review": needs_review,
            },
            "by_sentiment": dict(by_sentiment),
            "by_triage_outcome": dict(by_triage),
            "by_department": dict(by_department),
            "by_source": dict(by_source),
            "by_state": by_state,
            "severity_distribution": severity_dist,
            "average_severity": round(sev_total / sev_n, 1) if sev_n else None,
            "time_series": list(series.values()),
            "map_points": map_points,
        }
