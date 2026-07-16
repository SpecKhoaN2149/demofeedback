"""Mock 50 realistic feedback records for the internal dashboard.

FOR LOCAL DEMO / UI PREVIEW ONLY. This writes fabricated feedback directly to
the database so the internal dashboard (charts, US map clustering, source
attribution, severity 1-10, department routing) has realistic data to render.
It does NOT call the real NLP pipeline.

The data intentionally includes geographic CLUSTERS (e.g. a regional outage in
Austin generating many reports that all link to one ticket) so the map and
trend views show meaningful clustering, plus scattered singletons across the US.

All rows use deterministic UUIDv5 ids so seeding is idempotent (re-running
replaces rather than duplicating) and `--clear` can remove exactly these rows.

Usage (from backend/, with a venv that has the app deps):
    ALLOW_MOCK_SEED=1 .venv/bin/python scripts/seed_mock_feedback.py
    .venv/bin/python scripts/seed_mock_feedback.py --clear
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_connection, init_db

_MOCK_ENV_FLAG = "ALLOW_MOCK_SEED"
# Stable namespace so mock ids are deterministic across runs.
_NS = uuid.UUID("00000000-0000-0000-0000-00000000feed")

# New columns this mock relies on; added defensively for pre-existing DBs.
_NEW_COLUMNS = [
    ("department", "TEXT"),
    ("severity", "INTEGER"),
    ("severity_reasoning", "TEXT"),
    ("location_city", "TEXT"),
    ("location_state", "TEXT"),
    ("latitude", "REAL"),
    ("longitude", "REAL"),
]

# US metros used for map clustering: (city, state, lat, lng).
METROS = {
    "austin": ("Austin", "TX", 30.2672, -97.7431),
    "la": ("Los Angeles", "CA", 34.0522, -118.2437),
    "orlando": ("Orlando", "FL", 28.5383, -81.3792),
    "nyc": ("New York", "NY", 40.7128, -74.0060),
    "charlotte": ("Charlotte", "NC", 35.2271, -80.8431),
    "denver": ("Denver", "CO", 39.7392, -104.9903),
    "stlouis": ("St. Louis", "MO", 38.6270, -90.1994),
    "columbus": ("Columbus", "OH", 39.9612, -82.9988),
    "sanantonio": ("San Antonio", "TX", 29.4241, -98.4936),
    "cincinnati": ("Cincinnati", "OH", 39.1031, -84.5120),
    "tampa": ("Tampa", "FL", 27.9506, -82.4572),
    "raleigh": ("Raleigh", "NC", 35.7796, -78.6382),
}

DEPARTMENTS = {
    "outage": "Network Operations",
    "network_speed": "Technical Support",
    "billing": "Billing",
    "pricing": "Retention",
    "support_experience": "Customer Support",
    "device_hardware": "Field Services",
    "installation": "Field Services",
    "praise": "Marketing",
    "general": "Customer Support",
}


def _mid(key: str) -> str:
    return str(uuid.uuid5(_NS, key))


def _ensure_columns(conn) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(feedback)").fetchall()}
    for name, decl in _NEW_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE feedback ADD COLUMN {name} {decl}")


def _sev5(sev10: int) -> int:
    """Map a 1-10 severity to the legacy 1-5 enrichment scale for existing UI."""
    return max(1, min(5, round(sev10 / 2)))


def _enrichment_json(themes: list[str], sentiment_conf: float, sev10: int, reasoning: str, lang="en") -> str:
    return json.dumps(
        {
            "themes": [{"theme": t, "confidence": round(random.uniform(0.7, 0.98), 2)} for t in themes],
            "sentiment_confidence": round(sentiment_conf, 2),
            "severity_score": _sev5(sev10),
            "severity_factors": [reasoning],
            "language_code": lang,
            "language_confidence": 0.99,
        }
    )


def _build_records() -> tuple[list[dict], list[dict], list[dict]]:
    """Return (feedback_rows, ticket_rows, comment_rows)."""
    random.seed(42)
    now = datetime.now(timezone.utc)
    feedback: list[dict] = []
    tickets: list[dict] = []
    comments: list[dict] = []
    idx = 0

    def add_ticket(key: str, category: str, description: str, status: str, days_ago: int) -> str:
        tid = _mid(f"ticket-{key}")
        tickets.append(
            {
                "ticket_id": tid,
                "issue_category": category,
                "description": description[:5000],
                "priority": "high",
                "status": status,
                "created_at": (now - timedelta(days=days_ago, hours=2)).isoformat(),
            }
        )
        return tid

    def add(
        *,
        text: str,
        theme: str,
        sentiment: str,
        sev10: int,
        reasoning: str,
        metro: str,
        source_type: str,
        platform: str | None = None,
        channel: str | None = None,
        triage: str | None,
        ticket_id: str | None = None,
        needs_review: bool = False,
        status: str = "completed",
        days_ago: float = 0.0,
    ) -> str:
        nonlocal idx
        fid = _mid(f"feedback-{idx}")
        city, state, lat, lng = METROS[metro]
        # Jitter markers slightly so clustered points don't perfectly overlap.
        jlat = lat + random.uniform(-0.06, 0.06)
        jlng = lng + random.uniform(-0.06, 0.06)
        sentiment_conf = random.uniform(0.72, 0.97)
        feedback.append(
            {
                "feedback_id": fid,
                "text": text,
                "source_type": source_type,
                "channel": channel,
                "platform": platform,
                "created_at": (now - timedelta(days=days_ago)).isoformat(),
                "enrichment_status": status,
                "enrichment_result": _enrichment_json([theme], sentiment_conf, sev10, reasoning)
                if status == "completed"
                else None,
                "sentiment": sentiment if status == "completed" else None,
                "triage_outcome": triage,
                "triage_decision_source": ("automated" if triage else None),
                "needs_review": 1 if needs_review else 0,
                "ticket_id": ticket_id,
                "department": DEPARTMENTS.get(theme, "Customer Support") if status == "completed" else None,
                "severity": sev10 if status == "completed" else None,
                "severity_reasoning": reasoning if status == "completed" else None,
                "location_city": city,
                "location_state": state,
                "latitude": round(jlat, 4),
                "longitude": round(jlng, 4),
            }
        )
        idx += 1
        return fid

    # ── Cluster A: Austin regional outage — 8 reports → ONE ticket ───────────
    austin_ticket = add_ticket(
        "austin-outage", "outage",
        "Widespread service outage reported across the Austin metro since this morning.",
        "in_progress", days_ago=1,
    )
    austin_texts = [
        ("Internet has been completely down in south Austin since 7am. Nothing works.", "x"),
        ("Anyone else in Austin with no service right now? Third hour of downtime.", "reddit"),
        ("No internet, no cable, nothing. Austin 78704. This is unacceptable.", None),
        ("Spectrum outage in Austin AGAIN. I work from home and this is killing me.", "x"),
        ("Whole neighborhood is down in Austin. Please give us an ETA.", "facebook"),
        ("Outage map shows nothing but my Austin connection is dead since morning.", "reddit"),
        ("Been on hold for an hour about the Austin outage. Still down.", None),
        ("Service dropped across Austin — this is the second outage this month.", "x"),
    ]
    for i, (t, plat) in enumerate(austin_texts):
        add(
            text=t, theme="outage", sentiment="negative", sev10=random.choice([8, 9, 9, 10]),
            reasoning="Widespread outage affecting many customers in one metro; work-from-home and business impact; sustained multi-hour downtime.",
            metro="austin",
            source_type="social" if plat else "direct",
            platform=plat, channel=None if plat else "web_form",
            triage="action_required", ticket_id=austin_ticket, days_ago=random.uniform(0.5, 1.5),
        )
    comments.append({"ticket_id": austin_ticket, "author": "admin",
                     "text": "Field team dispatched to the Austin hub; fiber cut suspected. ETA 3 hours.",
                     "created_at": (now - timedelta(hours=6)).isoformat()})
    comments.append({"ticket_id": austin_ticket, "author": "admin",
                     "text": "Rerouted traffic; ~60% of customers restored. Monitoring.",
                     "created_at": (now - timedelta(hours=2)).isoformat()})

    # ── Cluster B: LA billing spike — 5 reports → ONE ticket ─────────────────
    la_ticket = add_ticket(
        "la-billing", "billing",
        "Multiple customers in the Los Angeles area report unexpected billing increases.",
        "open", days_ago=3,
    )
    la_texts = [
        ("My bill jumped $40 with no explanation. LA. Nobody can tell me why.", None),
        ("Charged twice this month in Los Angeles. Want a refund.", "x"),
        ("Promo expired and my LA bill doubled overnight. Feels like a bait and switch.", "reddit"),
        ("Why did my autopay take out more than my statement said? LA area.", "facebook"),
        ("Billing is a mess. Third month of surprise fees in Los Angeles.", None),
    ]
    for t, plat in la_texts:
        add(
            text=t, theme="billing", sentiment="negative", sev10=random.choice([5, 6, 7]),
            reasoning="Recurring billing discrepancies across multiple customers; financial impact and churn risk; no single-customer safety issue.",
            metro="la",
            source_type="social" if plat else "direct",
            platform=plat, channel=None if plat else "web_form",
            triage="action_required", ticket_id=la_ticket, days_ago=random.uniform(1, 4),
        )

    # ── Cluster C: Orlando slow speeds — 4 reports → ONE ticket ──────────────
    orl_ticket = add_ticket(
        "orlando-speed", "network_speed",
        "Degraded speeds reported by several customers in the Orlando area during evenings.",
        "open", days_ago=2,
    )
    orl_texts = [
        ("Paying for gig speed, getting 40mbps every evening in Orlando.", "reddit"),
        ("Speeds crawl after 7pm in Orlando. Unusable for streaming.", "x"),
        ("Constant buffering at night, Orlando. Speed tests are a joke.", None),
        ("Evening slowdowns in Orlando again. Please fix congestion.", "facebook"),
    ]
    for t, plat in orl_texts:
        add(
            text=t, theme="network_speed", sentiment="negative", sev10=random.choice([6, 7]),
            reasoning="Evening congestion degrading speeds for multiple customers in one area; quality-of-service impact, not a full outage.",
            metro="orlando",
            source_type="social" if plat else "direct",
            platform=plat, channel=None if plat else "web_form",
            triage="action_required", ticket_id=orl_ticket, days_ago=random.uniform(0.5, 3),
        )

    # ── Cluster D: Denver storm outage — 6 reports → ONE ticket ──────────────
    # NOTE: kept at "open" with NO seeded comments so the live demo can show an
    # admin advancing this ticket to in_progress and leaving the first comment.
    den_ticket = add_ticket(
        "denver-outage", "outage",
        "Storm-related outage affecting the Denver metro; multiple reports of total loss of service.",
        "open", days_ago=1,
    )
    den_texts = [
        ("Power flickered and now internet is totally out in Denver. Storm damage?", "x"),
        ("No service across my Denver block since the storm rolled through.", "reddit"),
        ("Denver 80202 — completely down for hours after the storm.", None),
        ("Cable and internet both dead in Denver after last night's weather.", "facebook"),
        ("Storm knocked out our Denver connection, still no ETA.", None),
        ("Third outage this winter in Denver, down again since this morning.", "x"),
    ]
    for t, plat in den_texts:
        add(
            text=t, theme="outage", sentiment="negative", sev10=random.choice([8, 9, 10]),
            reasoning="Weather-driven outage impacting many customers in one metro; sustained downtime; high household/business impact.",
            metro="denver",
            source_type="social" if plat else "direct",
            platform=plat, channel=None if plat else "web_form",
            triage="action_required", ticket_id=den_ticket, days_ago=random.uniform(0.5, 1.5),
        )
    # Intentionally NO seeded comment on the Denver ticket for the demo.

    # ── Cluster E: NYC installation backlog — 4 reports → ONE ticket ─────────
    nyc_ticket = add_ticket(
        "nyc-install", "installation",
        "Installation appointment backlog in the New York area; multiple missed/late appointments.",
        "open", days_ago=4,
    )
    nyc_texts = [
        ("Third rescheduled install in NYC. No one shows up.", None),
        ("Waited all day in Manhattan, installer never arrived.", "x"),
        ("NYC install pushed out two more weeks with no explanation.", "reddit"),
        ("Booked an install in New York, got cancelled by text last minute.", "facebook"),
    ]
    for t, plat in nyc_texts:
        add(
            text=t, theme="installation", sentiment="negative", sev10=random.choice([6, 7]),
            reasoning="Repeated installation failures for several customers in one metro; scheduling/operations issue requiring coordination.",
            metro="nyc",
            source_type="social" if plat else "direct",
            platform=plat, channel=None if plat else "web_form",
            triage="action_required", ticket_id=nyc_ticket, days_ago=random.uniform(1, 5),
        )

    # ── Cluster F: San Antonio price-hike complaints — 4 reports → ONE ticket ─
    sa_ticket = add_ticket(
        "sanantonio-pricing", "pricing",
        "Cluster of price-increase complaints from the San Antonio area after a regional promo ended.",
        "open", days_ago=5,
    )
    sa_texts = [
        ("Everyone in my San Antonio building got a price hike at once.", "reddit"),
        ("Promo ended and my San Antonio bill went up $35. Not okay.", None),
        ("San Antonio neighbors all complaining about the same rate increase.", "x"),
        ("Loyalty means nothing — San Antonio prices up again with no notice.", None),
    ]
    for t, plat in sa_texts:
        add(
            text=t, theme="pricing", sentiment="negative", sev10=random.choice([5, 6]),
            reasoning="Correlated pricing complaints across one metro; retention risk; not a service-availability emergency.",
            metro="sanantonio",
            source_type="social" if plat else "direct",
            platform=plat, channel=None if plat else "web_form",
            triage="action_required", ticket_id=sa_ticket, days_ago=random.uniform(1, 6),
        )

    # ── Positive praise (no_action) — scattered, various metros ──────────────
    praise = [
        ("The technician who set up my service was fantastic and super friendly!", "charlotte", "facebook"),
        ("Support fixed my issue in five minutes. Best experience I've had.", "denver", None),
        ("Love the new app — so easy to pay my bill now.", "nyc", "x"),
        ("Speeds have been rock solid since the upgrade. Thank you!", "columbus", "reddit"),
        ("Shoutout to the Raleigh install crew, on time and professional.", "raleigh", None),
        ("Customer service actually called me back. Impressed.", "tampa", None),
        ("Switched from a competitor and the difference is night and day. Great job.", "sanantonio", "facebook"),
        ("Tech went above and beyond to hide the cabling. Very happy.", "stlouis", None),
        ("Billing question got resolved on the first call, thank you.", "cincinnati", None),
        ("Rock-solid uptime this month, zero complaints.", "tampa", "x"),
        ("The retention offer they gave me was actually fair. Staying.", "la", None),
        ("Huge thanks to Marcus Bell, the technician in Denver — he went above and beyond!", "denver", "x"),
        ("Shoutout to Priya Nair in support, she resolved my issue in minutes.", "nyc", "reddit"),
        ("Our installer James Whitfield was fantastic and super professional. Give that person a raise!", "charlotte", None),
        ("Kudos to Sofia Alvarez for walking me through the setup so patiently.", "tampa", None),
        ("Big thanks to Daniel Reyes on the support team — quick and friendly.", "columbus", "reddit"),
    ]
    for t, metro, plat in praise:
        add(
            text=t, theme="praise", sentiment="positive", sev10=random.choice([1, 2]),
            reasoning="Positive sentiment; no operational issue; suitable for marketing and no action required.",
            metro=metro, source_type="social" if plat else "direct",
            platform=plat, channel=None if plat else "web_form",
            triage="no_action", days_ago=random.uniform(0, 12),
        )

    # ── Neutral comments / suggestions (no_action) ───────────────────────────
    neutral = [
        ("It would be nice if the app showed data usage per device.", "denver", None),
        ("Please add a dark mode to the customer portal.", "nyc", "reddit"),
        ("Just switched plans, everything is fine so far.", "stlouis", None),
        ("Can you offer paperless billing reminders by text?", "columbus", None),
        ("The outage map is helpful but could refresh faster.", "cincinnati", "x"),
        ("Setup instructions were clear, no complaints.", "sanantonio", None),
        ("Would love a loyalty discount for long-time customers.", "charlotte", "reddit"),
        ("Appointment window of 4 hours is a little long, but it worked out.", "orlando", None),
        ("Any plans to expand gigabit service to my area?", "raleigh", None),
        ("Portal works fine, though I wish it kept me logged in longer.", "charlotte", "reddit"),
        ("Moved recently and the service transfer was smooth enough.", "orlando", None),
    ]
    for t, metro, plat in neutral:
        add(
            text=t, theme="general", sentiment="neutral", sev10=random.choice([2, 3]),
            reasoning="Neutral suggestion/comment; low urgency; retained for trend analysis, no action required.",
            metro=metro, source_type="social" if plat else "direct",
            platform=plat, channel=None if plat else "web_form",
            triage="no_action", days_ago=random.uniform(0, 20),
        )

    # ── Negative singletons that each become their own ticket ────────────────
    singles = [
        ("My modem keeps rebooting every few hours, swapped cables already.", "device_hardware", "charlotte", None, 7),
        ("Support hung up on me twice trying to cancel. Terrible experience.", "support_experience", "nyc", "x", 8),
        ("Installer never showed up and no one called. Wasted my whole day.", "installation", "denver", None, 7),
        ("Prices keep creeping up while service gets worse. Considering leaving.", "pricing", "stlouis", "reddit", 6),
        ("Router provided is ancient and can't handle my plan speeds.", "device_hardware", "columbus", None, 6),
        ("Rude agent refused to escalate my repeated outage complaint.", "support_experience", "cincinnati", "facebook", 7),
        ("Signed up for a price and got billed a totally different amount.", "pricing", "tampa", None, 7),
        ("Cable box freezes constantly, replacement also defective.", "device_hardware", "raleigh", None, 5),
        ("Repeated dropped connections during work calls, escalating now.", "network_speed", "denver", "x", 7),
        ("Was promised a callback about my outage credit and never got one.", "support_experience", "austin", "reddit", 6),
    ]
    for t, theme, metro, plat, sev in singles:
        tid = add_ticket(f"single-{idx}", theme, t, random.choice(["open", "in_progress", "resolved"]), days_ago=random.randint(1, 8))
        add(
            text=t, theme=theme, sentiment="negative", sev10=sev,
            reasoning="Single-customer issue requiring follow-up; moderate severity based on impact and repeat contacts.",
            metro=metro, source_type="social" if plat else "direct",
            platform=plat, channel=None if plat else "web_form",
            triage="action_required", ticket_id=tid, days_ago=random.uniform(0.5, 8),
        )

    # ── Ambiguous → routed to admin review (needs_review, no outcome yet) ────
    ambiguous = [
        ("Service is okay but the price is a bit much for what I get.", "pricing", "denver", "reddit", 5),
        ("Had a brief outage but it came back. Just flagging it.", "outage", "columbus", None, 4),
        ("Not sure if this is billing or a plan issue, my discount vanished.", "billing", "nyc", None, 5),
        ("Speeds are fine most of the time, occasional hiccups.", "network_speed", "tampa", "x", 4),
        ("The new agent was fine, previous one wasn't. Mixed feelings.", "support_experience", "charlotte", None, 4),
    ]
    for t, theme, metro, plat, sev in ambiguous:
        add(
            text=t, theme=theme, sentiment=random.choice(["neutral", "negative"]), sev10=sev,
            reasoning="Automated triage confidence below threshold (borderline severity / mixed signal); routed to an admin for a manual decision.",
            metro=metro, source_type="social" if plat else "direct",
            platform=plat, channel=None if plat else "web_form",
            triage=None, needs_review=True, days_ago=random.uniform(0, 6),
        )

    # ── A couple still being analyzed / failed, for realism ──────────────────
    add(text="Just submitted this, curious what happens.", theme="general", sentiment="neutral",
        sev10=2, reasoning="", metro="stlouis", source_type="direct", channel="web_form",
        triage=None, needs_review=False, status="pending", days_ago=0.05)
    add(text="asdf test message ignore", theme="general", sentiment="neutral",
        sev10=1, reasoning="", metro="cincinnati", source_type="direct", channel="web_form",
        triage=None, needs_review=True, status="failed", days_ago=0.1)

    return feedback, tickets, comments


def seed() -> None:
    init_db()
    feedback, tickets, comments = _build_records()

    with get_connection() as conn:
        _ensure_columns(conn)

        # Tickets first so feedback.ticket_id FKs resolve.
        for t in tickets:
            conn.execute(
                "INSERT OR REPLACE INTO tickets (ticket_id, issue_category, description, priority, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (t["ticket_id"], t["issue_category"], t["description"], t["priority"], t["status"], t["created_at"]),
            )

        for f in feedback:
            conn.execute(
                """
                INSERT OR REPLACE INTO feedback (
                    feedback_id, text, source_type, channel, platform, created_at,
                    enrichment_status, enrichment_result, sentiment, triage_outcome,
                    triage_decision_source, needs_review, ticket_id,
                    department, severity, severity_reasoning,
                    location_city, location_state, latitude, longitude
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f["feedback_id"], f["text"], f["source_type"], f["channel"], f["platform"],
                    f["created_at"], f["enrichment_status"], f["enrichment_result"], f["sentiment"],
                    f["triage_outcome"], f["triage_decision_source"], f["needs_review"], f["ticket_id"],
                    f["department"], f["severity"], f["severity_reasoning"],
                    f["location_city"], f["location_state"], f["latitude"], f["longitude"],
                ),
            )

        # Comments: clear existing mock-ticket comments first (idempotent), then insert.
        mock_ticket_ids = [t["ticket_id"] for t in tickets]
        placeholders = ",".join("?" for _ in mock_ticket_ids)
        if mock_ticket_ids:
            conn.execute(
                f"DELETE FROM ticket_comments WHERE ticket_id IN ({placeholders})", mock_ticket_ids
            )
        for c in comments:
            conn.execute(
                "INSERT INTO ticket_comments (ticket_id, author, created_at, text) VALUES (?, ?, ?, ?)",
                (c["ticket_id"], c["author"], c["created_at"], c["text"]),
            )
        conn.commit()

    print(f"Seeded {len(feedback)} mock feedback, {len(tickets)} tickets, {len(comments)} comments.")
    print(
        "Multi-feedback clusters: Austin outage (8→1 ticket), LA billing (5→1), "
        "Orlando speeds (4→1), Denver outage (6→1), NYC installs (4→1), "
        "San Antonio pricing (4→1)."
    )


def reset_demo_data() -> dict:
    """Wipe ALL feedback/tickets/comments, then re-seed the mock demo set.

    This is the "overwrite whatever is there" reset used by the admin
    Reset Demo Data button: it removes any data accumulated during a previous
    demo run (submitted feedback, advanced tickets, manual comments) and
    restores the deterministic mock dataset to its fresh state (Denver outage
    ticket open, no comments, ready to be advanced live).

    Returns a dict of the row counts that were removed and re-seeded.
    """
    init_db()

    with get_connection() as conn:
        removed = {
            "feedback": conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0],
            "tickets": conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0],
            "comments": conn.execute("SELECT COUNT(*) FROM ticket_comments").fetchone()[0],
        }
        # Full wipe. Clear comments and unlink feedback first so no FK dangles,
        # then remove feedback and tickets outright.
        conn.execute("DELETE FROM ticket_comments")
        conn.execute("UPDATE feedback SET ticket_id = NULL")
        conn.execute("DELETE FROM feedback")
        conn.execute("DELETE FROM tickets")
        conn.commit()

    feedback, tickets, comments = _build_records()
    with get_connection() as conn:
        _ensure_columns(conn)
        for t in tickets:
            conn.execute(
                "INSERT OR REPLACE INTO tickets (ticket_id, issue_category, description, priority, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (t["ticket_id"], t["issue_category"], t["description"], t["priority"], t["status"], t["created_at"]),
            )
        for f in feedback:
            conn.execute(
                """
                INSERT OR REPLACE INTO feedback (
                    feedback_id, text, source_type, channel, platform, created_at,
                    enrichment_status, enrichment_result, sentiment, triage_outcome,
                    triage_decision_source, needs_review, ticket_id,
                    department, severity, severity_reasoning,
                    location_city, location_state, latitude, longitude
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f["feedback_id"], f["text"], f["source_type"], f["channel"], f["platform"],
                    f["created_at"], f["enrichment_status"], f["enrichment_result"], f["sentiment"],
                    f["triage_outcome"], f["triage_decision_source"], f["needs_review"], f["ticket_id"],
                    f["department"], f["severity"], f["severity_reasoning"],
                    f["location_city"], f["location_state"], f["latitude"], f["longitude"],
                ),
            )
        for c in comments:
            conn.execute(
                "INSERT INTO ticket_comments (ticket_id, author, created_at, text) VALUES (?, ?, ?, ?)",
                (c["ticket_id"], c["author"], c["created_at"], c["text"]),
            )
        conn.commit()

    return {
        "removed": removed,
        "seeded": {
            "feedback": len(feedback),
            "tickets": len(tickets),
            "comments": len(comments),
        },
    }


def clear() -> None:
    init_db()
    feedback_ids = [_mid(f"feedback-{i}") for i in range(300)]  # generous upper bound
    ticket_ids = [
        _mid("ticket-austin-outage"),
        _mid("ticket-la-billing"),
        _mid("ticket-orlando-speed"),
        _mid("ticket-denver-outage"),
        _mid("ticket-nyc-install"),
        _mid("ticket-sanantonio-pricing"),
    ]
    ticket_ids += [_mid(f"ticket-single-{i}") for i in range(300)]

    with get_connection() as conn:
        fph = ",".join("?" for _ in feedback_ids)
        tph = ",".join("?" for _ in ticket_ids)
        conn.execute(f"DELETE FROM ticket_comments WHERE ticket_id IN ({tph})", ticket_ids)
        conn.execute(f"UPDATE feedback SET ticket_id = NULL WHERE ticket_id IN ({tph})", ticket_ids)
        conn.execute(f"DELETE FROM feedback WHERE feedback_id IN ({fph})", feedback_ids)
        removed_tickets = conn.execute(
            f"DELETE FROM tickets WHERE ticket_id IN ({tph})", ticket_ids
        ).rowcount
        conn.commit()
    print(f"Cleared mock feedback and {removed_tickets} mock tickets.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed 50 mock feedback for the internal dashboard (local demo only).")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--seed", action="store_true", help="Insert the 50 mock feedback (default).")
    group.add_argument("--clear", action="store_true", help="Remove all mock feedback and tickets.")
    args = parser.parse_args()

    if args.clear:
        clear()
        return

    if not os.environ.get(_MOCK_ENV_FLAG):
        print(
            f"Refusing to seed: set {_MOCK_ENV_FLAG}=1 to write mock data.\n"
            f"  {_MOCK_ENV_FLAG}=1 python scripts/seed_mock_feedback.py\n"
            "Use --clear to remove any existing mock rows (no flag required).",
            file=sys.stderr,
        )
        sys.exit(1)

    seed()


if __name__ == "__main__":
    main()
