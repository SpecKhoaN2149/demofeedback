"""Similarity Clusterer for feedback routing.

Implements Requirements 6.1–6.8:
- Evaluates cluster membership using weighted text similarity, shared theme,
  and geographic proximity (50km).
- Creates new clusters when no existing cluster exceeds 0.7 similarity.
- Assigns to highest-scoring matching cluster otherwise.
- Updates cluster volume_count and last_seen_at on assignment.
- Updates cluster_summary when volume grows by more than 20%.
- Upgrades cluster priority_level to "high" when volume > 20.
- Only considers "active" or "monitoring" clusters for matching.
- Excludes geographic proximity when location data is absent.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone

from nlp_processing.aggregation.clustering import cosine_similarity, local_embedding
from nlp_processing.models.feedback_routing import (
    CanonicalFeedback,
    ClusterRecord,
    FeedbackAnalysis,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SIMILARITY_THRESHOLD = 0.7
_GEO_PROXIMITY_KM = 50.0
_VOLUME_GROWTH_THRESHOLD = 0.20  # 20%
_HIGH_VOLUME_THRESHOLD = 20
_EARTH_RADIUS_KM = 6371.0

# Weights for composite similarity score
_WEIGHT_TEXT = 0.5
_WEIGHT_THEME = 0.3
_WEIGHT_GEO = 0.2


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute the haversine distance in kilometres between two lat/lon points."""
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return _EARTH_RADIUS_KM * c


def _parse_location(location: str | None) -> tuple[float, float] | None:
    """Parse a location string to lat/lon coordinates.

    Accepts formats:
    - "lat,lon" (numeric)
    - "City, CC" (returns None as geocoding is not implemented in-process)

    Returns None if location data is absent or cannot be parsed as coordinates.
    """
    if not location:
        return None
    parts = location.split(",")
    if len(parts) == 2:
        try:
            lat = float(parts[0].strip())
            lon = float(parts[1].strip())
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return (lat, lon)
        except ValueError:
            pass
    return None


def _now_iso() -> str:
    """Return current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SimilarityClusterer:
    """Groups feedback into clusters based on weighted similarity.

    Uses text similarity (cosine over bag-of-words embeddings), shared theme,
    and geographic proximity to assign feedback to existing clusters or create
    new ones.

    This prototype uses an in-memory store of clusters. Optionally accepts a
    FeedbackStore for database persistence.

    Parameters
    ----------
    store : object | None
        Optional persistence layer (FeedbackStore) for cluster operations.
        When provided, clusters are also persisted to the database.
        When None, clusters are maintained only in memory.
    """

    def __init__(self, store: object | None = None) -> None:
        self._store = store
        # In-memory cluster store: cluster_id -> ClusterRecord
        self._clusters: dict[str, ClusterRecord] = {}
        # Track the volume at which summary was last computed per cluster
        self._last_summary_volume: dict[str, int] = {}
        # Track location metadata per cluster (centroid coordinates)
        self._cluster_locations: dict[str, tuple[float, float]] = {}

    @property
    def clusters(self) -> dict[str, ClusterRecord]:
        """Access the in-memory cluster store (read-only)."""
        return dict(self._clusters)

    def assign_cluster(
        self, feedback: CanonicalFeedback, analysis: FeedbackAnalysis
    ) -> str:
        """Assign feedback to a cluster, creating one if no match exceeds threshold.

        Parameters
        ----------
        feedback : CanonicalFeedback
            The preprocessed feedback record.
        analysis : FeedbackAnalysis
            The NLP analysis result (used for theme matching).

        Returns
        -------
        str
            The cluster_id of the assigned (or newly created) cluster.
        """
        # Load clusters from store if available and in-memory is empty
        if not self._clusters and self._store is not None:
            self._load_clusters_from_store()

        # Get active/monitoring clusters
        active_clusters = [
            c for c in self._clusters.values()
            if c.status in ("active", "monitoring")
        ]

        if not active_clusters:
            return self._create_new_cluster(feedback, analysis)

        # Compute similarity scores against all active clusters
        best_score = 0.0
        best_cluster: ClusterRecord | None = None

        feedback_embedding = local_embedding([feedback.cleaned_text])[0]
        feedback_location = self._extract_location(feedback)
        has_location = feedback_location is not None

        for cluster in active_clusters:
            score = self._compute_similarity(
                feedback_embedding=feedback_embedding,
                feedback_theme=analysis.theme_primary,
                feedback_location=feedback_location,
                has_location=has_location,
                cluster=cluster,
            )
            if score > best_score:
                best_score = score
                best_cluster = cluster

        if best_score > _SIMILARITY_THRESHOLD and best_cluster is not None:
            return self._assign_to_cluster(best_cluster, feedback, analysis)
        else:
            return self._create_new_cluster(feedback, analysis)

    def _load_clusters_from_store(self) -> None:
        """Load clusters from the persistence store into memory."""
        if self._store is None:
            return
        conn = self._store._conn
        cursor = conn.execute(
            "SELECT cluster_id, theme, cluster_summary, volume_count, "
            "sentiment_trend, priority_level, first_seen_at, last_seen_at, status "
            "FROM clusters WHERE status IN ('active', 'monitoring')"
        )
        for row in cursor.fetchall():
            cluster = ClusterRecord(
                cluster_id=row[0],
                theme=row[1],
                cluster_summary=row[2],
                volume_count=row[3],
                sentiment_trend=row[4],
                priority_level=row[5],
                first_seen_at=row[6],
                last_seen_at=row[7],
                status=row[8],
            )
            self._clusters[cluster.cluster_id] = cluster
            # Initialize last summary volume to current volume
            self._last_summary_volume[cluster.cluster_id] = cluster.volume_count

    def _compute_similarity(
        self,
        *,
        feedback_embedding: list[float],
        feedback_theme: str,
        feedback_location: tuple[float, float] | None,
        has_location: bool,
        cluster: ClusterRecord,
    ) -> float:
        """Compute weighted similarity between feedback and a cluster.

        Weights:
        - Text similarity (cosine): 50%
        - Shared theme: 30%
        - Geographic proximity (50km): 20% (excluded when location is absent)

        When location is absent, text and theme are renormalized to sum to 1.0.
        """
        # Text similarity: embed the cluster summary (or theme if no summary)
        cluster_text = cluster.cluster_summary or cluster.theme
        cluster_embedding = local_embedding([cluster_text])[0]
        text_sim = cosine_similarity(feedback_embedding, cluster_embedding)

        # Theme match (binary: 1.0 if same theme, 0.0 otherwise)
        theme_sim = 1.0 if feedback_theme == cluster.theme else 0.0

        # Geographic proximity
        geo_available = False
        geo_sim = 0.0

        if has_location and feedback_location is not None:
            cluster_location = self._cluster_locations.get(cluster.cluster_id)
            if cluster_location is not None:
                distance = _haversine_km(
                    feedback_location[0],
                    feedback_location[1],
                    cluster_location[0],
                    cluster_location[1],
                )
                # Score is 1.0 at 0km, linearly decreasing to 0.0 at 50km+
                geo_sim = max(0.0, 1.0 - (distance / _GEO_PROXIMITY_KM))
                geo_available = True

        # Compute weighted score
        if has_location and geo_available:
            score = (
                _WEIGHT_TEXT * text_sim
                + _WEIGHT_THEME * theme_sim
                + _WEIGHT_GEO * geo_sim
            )
        else:
            # Renormalize without geographic factor
            total_weight = _WEIGHT_TEXT + _WEIGHT_THEME
            score = (
                _WEIGHT_TEXT * text_sim + _WEIGHT_THEME * theme_sim
            ) / total_weight

        return score

    def _assign_to_cluster(
        self,
        cluster: ClusterRecord,
        feedback: CanonicalFeedback,
        analysis: FeedbackAnalysis,
    ) -> str:
        """Assign feedback to an existing cluster, updating metadata."""
        cluster_id = cluster.cluster_id
        old_volume = cluster.volume_count
        now = _now_iso()

        # Update volume_count and last_seen_at (Req 6.2, 6.4)
        new_volume = old_volume + 1
        updated_cluster = ClusterRecord(
            cluster_id=cluster.cluster_id,
            theme=cluster.theme,
            cluster_summary=cluster.cluster_summary,
            volume_count=new_volume,
            sentiment_trend=cluster.sentiment_trend,
            priority_level=cluster.priority_level,
            first_seen_at=cluster.first_seen_at,
            last_seen_at=now,
            status=cluster.status,
        )
        self._clusters[cluster_id] = updated_cluster

        # Persist to store if available
        if self._store is not None:
            self._store.update_cluster(cluster_id, volume_increment=1)

        # Update cluster_summary on 20% volume growth (Req 6.5)
        self._check_summary_update(cluster_id, new_volume, analysis)

        # Upgrade priority to "high" when volume > 20 (Req 6.6)
        if new_volume > _HIGH_VOLUME_THRESHOLD:
            current = self._clusters[cluster_id]
            if current.priority_level in ("low", "medium"):
                self._upgrade_priority(cluster_id, "high")

        return cluster_id

    def _create_new_cluster(
        self, feedback: CanonicalFeedback, analysis: FeedbackAnalysis
    ) -> str:
        """Create a new cluster for the feedback (Req 6.3)."""
        cluster_id = str(uuid.uuid4())
        now = _now_iso()

        # Generate initial summary from feedback text
        summary = feedback.cleaned_text[:500] if feedback.cleaned_text else None

        new_cluster = ClusterRecord(
            cluster_id=cluster_id,
            theme=analysis.theme_primary[:120],
            cluster_summary=summary,
            volume_count=1,
            sentiment_trend=None,
            priority_level="low",
            first_seen_at=now,
            last_seen_at=now,
            status="active",
        )

        # Store in memory
        self._clusters[cluster_id] = new_cluster
        self._last_summary_volume[cluster_id] = 1

        # Store location if available
        feedback_location = self._extract_location(feedback)
        if feedback_location is not None:
            self._cluster_locations[cluster_id] = feedback_location

        # Persist to store if available
        if self._store is not None:
            self._store.insert_cluster(new_cluster)

        return cluster_id

    def _check_summary_update(
        self,
        cluster_id: str,
        new_volume: int,
        analysis: FeedbackAnalysis,
    ) -> None:
        """Update cluster_summary if volume has grown by more than 20%.

        Tracks the volume at which the summary was last computed. When the
        current volume exceeds 120% of that baseline, regenerate the summary.
        """
        last_volume = self._last_summary_volume.get(cluster_id, 1)
        growth_ratio = (new_volume - last_volume) / max(last_volume, 1)

        if growth_ratio > _VOLUME_GROWTH_THRESHOLD:
            cluster = self._clusters[cluster_id]
            # Generate updated summary based on theme and volume
            new_summary = (
                f"Cluster of {new_volume} feedback items about "
                f"{cluster.theme}"
            )[:500]

            # Update in-memory cluster
            updated = ClusterRecord(
                cluster_id=cluster.cluster_id,
                theme=cluster.theme,
                cluster_summary=new_summary,
                volume_count=cluster.volume_count,
                sentiment_trend=cluster.sentiment_trend,
                priority_level=cluster.priority_level,
                first_seen_at=cluster.first_seen_at,
                last_seen_at=cluster.last_seen_at,
                status=cluster.status,
            )
            self._clusters[cluster_id] = updated
            self._last_summary_volume[cluster_id] = new_volume

            # Persist to store if available
            if self._store is not None:
                self._update_cluster_summary_in_store(cluster_id, new_summary)

    def _update_cluster_summary_in_store(
        self, cluster_id: str, summary: str
    ) -> None:
        """Update the cluster_summary field in the database."""
        if self._store is None:
            return
        conn = self._store._conn
        conn.execute(
            "UPDATE clusters SET cluster_summary = ? WHERE cluster_id = ?",
            (summary, cluster_id),
        )
        conn.commit()

    def _upgrade_priority(self, cluster_id: str, priority_level: str) -> None:
        """Upgrade the priority_level of a cluster."""
        cluster = self._clusters[cluster_id]
        updated = ClusterRecord(
            cluster_id=cluster.cluster_id,
            theme=cluster.theme,
            cluster_summary=cluster.cluster_summary,
            volume_count=cluster.volume_count,
            sentiment_trend=cluster.sentiment_trend,
            priority_level=priority_level,
            first_seen_at=cluster.first_seen_at,
            last_seen_at=cluster.last_seen_at,
            status=cluster.status,
        )
        self._clusters[cluster_id] = updated

        # Persist to store if available
        if self._store is not None:
            conn = self._store._conn
            conn.execute(
                "UPDATE clusters SET priority_level = ? WHERE cluster_id = ?",
                (priority_level, cluster_id),
            )
            conn.commit()

    def _extract_location(
        self, feedback: CanonicalFeedback
    ) -> tuple[float, float] | None:
        """Extract location coordinates from feedback metadata."""
        location = feedback.metadata.get("location")
        return _parse_location(location)


__all__ = ["SimilarityClusterer"]
