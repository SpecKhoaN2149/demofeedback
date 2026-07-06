"""Demo seed: populate sample submissions with fake NLP enrichment.

FOR LOCAL DEMO / UI PREVIEW ONLY. This does NOT call the real NLP pipeline —
it writes plausible-looking enrichment data directly so you can see how the
NLP output renders across the admin UI (Review Queue, Submission Detail,
Dashboard "NLP Insights"). Real enrichment requires GEMINI_API_KEY and runs
automatically on new submissions.

All demo rows are tagged with the `@demo.spectrum.local` email domain so they
can be removed cleanly with --clear.

Usage (from the backend/ directory, with a venv that has the app deps):
    # Seeding is gated behind an env flag to avoid polluting a real DB:
    ALLOW_DEMO_SEED=1 .venv/bin/python scripts/seed_demo_enrichment.py
    ALLOW_DEMO_SEED=1 .venv/bin/python scripts/seed_demo_enrichment.py --seed

    # Remove all demo rows (no env flag required):
    .venv/bin/python scripts/seed_demo_enrichment.py --clear
"""

import argparse
import os
import sys

# Ensure the app package is importable when run from backend/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_connection, init_db
from app.models.submission import EnrichmentResult, SubmissionCreate
from app.services.admin_review_queue import AdminReviewQueue
from app.services.marketing_engine import MarketingEngine
from app.services.submission_store import SubmissionStore
from app.services.ticketing_pipeline import TicketingPipeline

# Sentinel domain that marks a row as demo-only so --clear can find it.
DEMO_EMAIL_DOMAIN = "demo.spectrum.local"
# Environment flag that must be truthy to allow seeding.
_SEED_ENV_FLAG = "ALLOW_DEMO_SEED"

store = SubmissionStore()
queue = AdminReviewQueue()
tickets = TicketingPipeline()
marketing = MarketingEngine()


def _demo_email(name: str) -> str:
    return f"{name.split()[0].lower()}@{DEMO_EMAIL_DOMAIN}"


def _enrich(submission_id, result: EnrichmentResult) -> None:
    store.update_enrichment(submission_id, result)


def seed() -> None:
    """Create representative submissions and fill in sample NLP enrichment."""
    init_db()

    # 1) Neutral submissions -> review queue (shows NLP in the queue table)
    neutral_specs = [
        (
            "Jordan Vega",
            "The installation was fine but the tech showed up an hour late and "
            "didn't explain the equipment.",
            EnrichmentResult(
                themes=[
                    {"theme": "support_experience", "confidence": 0.82},
                    {"theme": "installation", "confidence": 0.64},
                ],
                sentiment_confidence=0.58,
                severity_score=3,
                severity_factors=[
                    "Late technician arrival",
                    "Insufficient equipment walkthrough",
                ],
                language_code="en",
                language_confidence=0.99,
            ),
        ),
        (
            "Priya Nair",
            "El servicio es aceptable pero la factura cambia cada mes sin aviso.",
            EnrichmentResult(
                themes=[
                    {"theme": "billing", "confidence": 0.91},
                    {"theme": "pricing", "confidence": 0.55},
                ],
                sentiment_confidence=0.61,
                severity_score=4,
                severity_factors=["Unexpected monthly billing changes"],
                language_code="es",
                language_confidence=0.97,
            ),
        ),
    ]
    for name, comment, result in neutral_specs:
        sub = store.create(
            SubmissionCreate(
                customer_name=name,
                email=_demo_email(name),
                core_request=comment,
                sentiment="neutral",
                comment_text=comment,
            )
        )
        queue.enqueue(str(sub.id))
        _enrich(sub.id, result)
        print(f"neutral queued + enriched: {sub.id} ({name})")

    # 2) Negative submission -> ticket (NLP reachable from Tickets list)
    neg = store.create(
        SubmissionCreate(
            customer_name="Marcus Lee",
            email=_demo_email("Marcus Lee"),
            core_request="Internet keeps dropping every evening for the past week.",
            sentiment="negative",
            issue_category="network_speed",
            detailed_description=(
                "Every night around 8pm the connection drops for 10-15 minutes. "
                "This has happened for 7 straight days and I work from home."
            ),
        )
    )
    tickets.create_ticket(
        submission_id=str(neg.id),
        category="network_speed",
        description=neg.detailed_description or neg.core_request,
    )
    _enrich(
        neg.id,
        EnrichmentResult(
            themes=[
                {"theme": "network_speed", "confidence": 0.94},
                {"theme": "outage", "confidence": 0.71},
            ],
            sentiment_confidence=0.88,
            severity_score=5,
            severity_factors=[
                "Recurring nightly outages",
                "Impacts work-from-home",
                "Sustained over 7 days",
            ],
            language_code="en",
            language_confidence=0.99,
        ),
    )
    print(f"negative ticket + enriched: {neg.id}")

    # 3) Positive submission -> marketing log
    pos = store.create(
        SubmissionCreate(
            customer_name="Dana Cole",
            email=_demo_email("Dana Cole"),
            core_request="Support was fantastic.",
            sentiment="positive",
            praise_text="Your support agent Sam solved my issue in five minutes. Amazing!",
            social_sharing=True,
        )
    )
    marketing.log_praise(
        submission_id=str(pos.id),
        customer_name=pos.customer_name,
        praise_text=pos.praise_text,
        social_sharing=pos.social_sharing,
    )
    _enrich(
        pos.id,
        EnrichmentResult(
            themes=[{"theme": "support_experience", "confidence": 0.96}],
            sentiment_confidence=0.97,
            severity_score=1,
            severity_factors=[],
            language_code="en",
            language_confidence=0.99,
        ),
    )
    print(f"positive marketing + enriched: {pos.id}")

    print("\nDemo enrichment seeded. Log into the admin UI to view NLP Insights.")


def clear() -> None:
    """Remove every demo row (identified by the demo email domain) and its
    related ticket / marketing / queue / state-transition records."""
    init_db()
    like = f"%@{DEMO_EMAIL_DOMAIN}"
    with get_connection() as conn:
        ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM submissions WHERE email LIKE ?", (like,)
            ).fetchall()
        ]
        if not ids:
            print("No demo rows found — nothing to clear.")
            return

        placeholders = ",".join("?" for _ in ids)
        for table, col in (
            ("state_transitions", "submission_id"),
            ("tickets", "submission_id"),
            ("marketing_log", "submission_id"),
            ("admin_review_queue", "submission_id"),
            ("submissions", "id"),
        ):
            conn.execute(
                f"DELETE FROM {table} WHERE {col} IN ({placeholders})", ids
            )
        conn.commit()

    print(f"Cleared {len(ids)} demo submission(s) and related records.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo NLP enrichment seeder (local UI preview only).")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--seed",
        action="store_true",
        help="Create demo submissions with sample enrichment (default action).",
    )
    group.add_argument(
        "--clear",
        action="store_true",
        help="Remove all previously seeded demo rows.",
    )
    args = parser.parse_args()

    if args.clear:
        clear()
        return

    # Default action is seeding, which is gated behind the env flag.
    if not os.environ.get(_SEED_ENV_FLAG):
        print(
            f"Refusing to seed: set {_SEED_ENV_FLAG}=1 to write demo data.\n"
            f"  {_SEED_ENV_FLAG}=1 python scripts/seed_demo_enrichment.py\n"
            "Use --clear to remove any existing demo rows (no flag required).",
            file=sys.stderr,
        )
        sys.exit(1)

    seed()


if __name__ == "__main__":
    main()
