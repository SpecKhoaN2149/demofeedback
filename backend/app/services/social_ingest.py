"""Social ingestion adapter bridging the NLP SocialListener into the backend.

This adapter is the thin seam between the ``nlp_processing`` social listener
and the backend's unified feedback model. It takes a raw social ``post_data``
dict, runs it through :class:`SocialListener.ingest_social` to obtain a
validated ``SocialFeedback`` record, and persists it via
:meth:`FeedbackStore.create_from_social` (source_type="social", platform
preserved, channel=NULL) (Requirements 6.1, 6.5).

Enrichment + triage are triggered the same way as for direct feedback; this
module deliberately does not run them so persistence mapping stays decoupled
from the async enrichment pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.models.feedback import Feedback
from app.services.feedback_store import FeedbackStore

# The `nlp_processing` package lives at the repository root, one level above the
# backend/ directory. When the API is started from backend/, that root is not on
# sys.path, so `import nlp_processing` fails. Mirror enrichment.py and add the
# repo root to sys.path here so the social listener is importable regardless of
# the working directory.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if (_REPO_ROOT / "nlp_processing").is_dir() and str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


class SocialIngestAdapter:
    """Maps social listener output into persisted feedback records.

    Dependencies are injected for testability: a :class:`FeedbackStore` and a
    ``SocialListener``-like object. Both default to real instances when omitted.
    """

    def __init__(self, store: FeedbackStore | None = None, listener=None) -> None:
        self._store = store if store is not None else FeedbackStore()

        if listener is not None:
            self._listener = listener
        else:
            # Local import so importing this backend module does not hard-depend
            # on nlp_processing being importable at module load time.
            from nlp_processing.ingestion.social_listener import SocialListener

            self._listener = SocialListener()

    def ingest(self, post_data: dict) -> Feedback | None:
        """Ingest a raw social post and persist it as a feedback record.

        Runs ``post_data`` through the listener. If the listener discards the
        post (returns ``None`` for empty/short text or an invalid platform),
        this returns ``None`` and nothing is persisted. Otherwise the resulting
        ``SocialFeedback`` is persisted via
        :meth:`FeedbackStore.create_from_social` (source_type="social",
        platform preserved, channel=NULL) and the created :class:`Feedback` is
        returned (Requirements 6.1, 6.5).

        Args:
            post_data: Raw social post dict accepted by
                ``SocialListener.ingest_social``.

        Returns:
            The persisted :class:`Feedback`, or ``None`` if the post was
            discarded by the listener.
        """
        sf = self._listener.ingest_social(post_data)
        if sf is None:
            return None

        return self._store.create_from_social(sf)

    def enqueue_enrichment(self, feedback) -> None:
        """Convenience hook for triggering enrichment on ingested feedback.

        Intentionally a no-op here. Enrichment (and the triage that follows it)
        is triggered the same way as for direct feedback, via the backend's
        ``run_enrichment`` background task keyed by ``feedback.feedback_id``.
        Keeping ingestion decoupled from the async enrichment pipeline lets this
        adapter focus solely on the social → feedback persistence mapping.
        """
        return None
