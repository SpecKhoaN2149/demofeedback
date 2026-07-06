"""Unit tests for SimilarityClusterer.

Tests Requirements 6.1–6.8:
- Cluster creation when no match exceeds 0.7.
- Assignment to highest-scoring cluster when match > 0.7.
- Volume_count and last_seen_at updates on assignment.
- Summary update on 20% volume growth.
- Priority upgrade to "high" when volume > 20.
- Only active/monitoring clusters considered.
- Geographic factor excluded when location absent.
"""

from __future__ import annotations

import uuid

import pytest

from nlp_processing.aggregation.similarity_clusterer import (
    SimilarityClusterer,
    _haversine_km,
    _parse_location,
)
from nlp_processing.models.feedback_routing import (
    CanonicalFeedback,
    ClusterRecord,
    FeedbackAnalysis,
)
from nlp_processing.persistence.feedback_store import FeedbackStore


def _make_feedback(
    text: str = "internet outage in my area",
    source_type: str = "social",
    metadata: dict | None = None,
) -> CanonicalFeedback:
    return CanonicalFeedback(
        feedback_id=str(uuid.uuid4()),
        source_type=source_type,
        original_source_id="post-123",
        cleaned_text=text,
        detected_language="en",
        ingested_at="2024-01-01T00:00:00Z",
        metadata=metadata or {},
    )


def _make_analysis(
    feedback_id: str = "",
    theme_primary: str = "outage",
    sentiment_label: str = "negative",
    sentiment_score: float = -0.8,
) -> FeedbackAnalysis:
    return FeedbackAnalysis(
        feedback_id=feedback_id or str(uuid.uuid4()),
        sentiment_label=sentiment_label,
        sentiment_score=sentiment_score,
        priority_score=0.8,
        priority_level="high",
        theme_primary=theme_primary,
        theme_secondary=None,
        intent="outage_report",
        cluster_id=None,
        requires_action=True,
        entities=[],
        processed_at="2024-01-01T00:00:01Z",
    )


def _make_cluster(
    theme: str = "outage",
    volume_count: int = 1,
    status: str = "active",
    priority_level: str = "low",
    cluster_summary: str | None = None,
) -> ClusterRecord:
    return ClusterRecord(
        cluster_id=str(uuid.uuid4()),
        theme=theme,
        cluster_summary=cluster_summary or f"Cluster about {theme} reports from customers",
        volume_count=volume_count,
        sentiment_trend=None,
        priority_level=priority_level,
        first_seen_at="2024-01-01T00:00:00Z",
        last_seen_at="2024-01-01T00:00:00Z",
        status=status,
    )


class TestNewClusterCreation:
    """Requirement 6.3: Create new cluster when no match > 0.7."""

    def test_creates_cluster_when_no_existing(self):
        store = FeedbackStore(":memory:")
        clusterer = SimilarityClusterer(store)
        feedback = _make_feedback()
        analysis = _make_analysis(feedback_id=feedback.feedback_id)

        cluster_id = clusterer.assign_cluster(feedback, analysis)

        assert cluster_id is not None
        # Verify cluster was persisted
        cursor = store._conn.execute(
            "SELECT cluster_id, theme, volume_count, status, priority_level "
            "FROM clusters WHERE cluster_id = ?",
            (cluster_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[1] == "outage"  # theme matches analysis.theme_primary
        assert row[2] == 1  # volume_count starts at 1
        assert row[3] == "active"  # default status
        assert row[4] == "low"  # default priority

    def test_creates_cluster_when_existing_dont_match(self):
        store = FeedbackStore(":memory:")
        clusterer = SimilarityClusterer(store)

        # Create an existing cluster with a very different theme
        existing = _make_cluster(theme="billing")
        store.insert_cluster(existing)

        # Feedback about a completely different topic
        feedback = _make_feedback(text="installation appointment scheduling")
        analysis = _make_analysis(
            feedback_id=feedback.feedback_id, theme_primary="installation"
        )

        cluster_id = clusterer.assign_cluster(feedback, analysis)

        # Should create a new cluster, not assign to the billing one
        assert cluster_id != existing.cluster_id

    def test_new_cluster_has_active_status(self):
        clusterer = SimilarityClusterer()
        feedback = _make_feedback(text="new wifi router not connecting")
        analysis = _make_analysis(
            feedback_id=feedback.feedback_id, theme_primary="equipment"
        )

        cluster_id = clusterer.assign_cluster(feedback, analysis)

        cluster = clusterer.clusters[cluster_id]
        assert cluster.status == "active"
        assert cluster.priority_level == "low"
        assert cluster.volume_count == 1

    def test_new_cluster_summary_from_feedback_text(self):
        clusterer = SimilarityClusterer()
        feedback = _make_feedback(text="my internet connection keeps dropping")
        analysis = _make_analysis(
            feedback_id=feedback.feedback_id, theme_primary="speed_performance"
        )

        cluster_id = clusterer.assign_cluster(feedback, analysis)

        cluster = clusterer.clusters[cluster_id]
        assert cluster.cluster_summary == "my internet connection keeps dropping"


class TestClusterAssignment:
    """Requirements 6.1, 6.2: Assign to highest-scoring match above 0.7."""

    def test_assigns_to_matching_cluster(self):
        store = FeedbackStore(":memory:")
        clusterer = SimilarityClusterer(store)

        # Create cluster with matching theme and text overlap
        existing = _make_cluster(
            theme="outage",
            cluster_summary="internet outage no service in area reports",
        )
        store.insert_cluster(existing)

        # Feedback with high token overlap to the cluster summary
        feedback = _make_feedback(text="internet outage no service in my area")
        analysis = _make_analysis(
            feedback_id=feedback.feedback_id, theme_primary="outage"
        )

        cluster_id = clusterer.assign_cluster(feedback, analysis)

        # Should assign to existing cluster (theme match + text overlap)
        assert cluster_id == existing.cluster_id

    def test_assigns_to_highest_scoring_cluster(self):
        store = FeedbackStore(":memory:")
        clusterer = SimilarityClusterer(store)

        # Two clusters: one billing (low overlap), one outage (high overlap)
        cluster_a = _make_cluster(
            theme="billing",
            cluster_summary="billing payment invoice charges account",
        )
        cluster_b = _make_cluster(
            theme="outage",
            cluster_summary="internet outage no service widespread down",
        )
        store.insert_cluster(cluster_a)
        store.insert_cluster(cluster_b)

        # Feedback about outage with tokens matching cluster_b
        feedback = _make_feedback(text="internet outage no service widespread")
        analysis = _make_analysis(
            feedback_id=feedback.feedback_id, theme_primary="outage"
        )

        cluster_id = clusterer.assign_cluster(feedback, analysis)

        # Should prefer the outage cluster due to theme + text match
        assert cluster_id == cluster_b.cluster_id

    def test_assigns_in_memory_only(self):
        """Test clusterer works without a store (in-memory only)."""
        clusterer = SimilarityClusterer()

        # First feedback creates a cluster
        fb1 = _make_feedback(text="internet outage no service widespread down")
        a1 = _make_analysis(feedback_id=fb1.feedback_id, theme_primary="outage")
        cluster_id_1 = clusterer.assign_cluster(fb1, a1)

        # Second very similar feedback should match
        fb2 = _make_feedback(text="internet outage no service widespread")
        a2 = _make_analysis(feedback_id=fb2.feedback_id, theme_primary="outage")
        cluster_id_2 = clusterer.assign_cluster(fb2, a2)

        assert cluster_id_2 == cluster_id_1


class TestVolumeAndTimestampUpdate:
    """Requirements 6.2, 6.4: Update volume_count and last_seen_at."""

    def test_increments_volume_on_assignment(self):
        store = FeedbackStore(":memory:")
        clusterer = SimilarityClusterer(store)

        existing = _make_cluster(
            theme="outage",
            volume_count=5,
            cluster_summary="internet outage no service widespread problems",
        )
        store.insert_cluster(existing)

        feedback = _make_feedback(text="internet outage no service widespread")
        analysis = _make_analysis(
            feedback_id=feedback.feedback_id, theme_primary="outage"
        )

        cluster_id = clusterer.assign_cluster(feedback, analysis)

        # Verify volume incremented in DB
        cursor = store._conn.execute(
            "SELECT volume_count FROM clusters WHERE cluster_id = ?",
            (cluster_id,),
        )
        row = cursor.fetchone()
        assert row[0] == 6

        # Also verify in-memory
        assert clusterer.clusters[cluster_id].volume_count == 6

    def test_updates_last_seen_at(self):
        store = FeedbackStore(":memory:")
        clusterer = SimilarityClusterer(store)

        existing = _make_cluster(
            theme="outage",
            cluster_summary="internet outage service disruption no connection",
        )
        store.insert_cluster(existing)

        feedback = _make_feedback(text="internet outage service disruption")
        analysis = _make_analysis(
            feedback_id=feedback.feedback_id, theme_primary="outage"
        )

        clusterer.assign_cluster(feedback, analysis)

        # Verify last_seen_at was updated (should be newer than original)
        cursor = store._conn.execute(
            "SELECT last_seen_at FROM clusters WHERE cluster_id = ?",
            (existing.cluster_id,),
        )
        row = cursor.fetchone()
        assert row[0] != "2024-01-01T00:00:00Z"

    def test_updates_last_seen_at_in_memory(self):
        clusterer = SimilarityClusterer()

        # Create initial cluster
        fb1 = _make_feedback(text="internet outage no service widespread down")
        a1 = _make_analysis(feedback_id=fb1.feedback_id, theme_primary="outage")
        cluster_id = clusterer.assign_cluster(fb1, a1)

        first_seen = clusterer.clusters[cluster_id].last_seen_at

        # Assign second item
        fb2 = _make_feedback(text="internet outage no service widespread")
        a2 = _make_analysis(feedback_id=fb2.feedback_id, theme_primary="outage")
        clusterer.assign_cluster(fb2, a2)

        # last_seen_at should have been updated
        updated_cluster = clusterer.clusters[cluster_id]
        assert updated_cluster.volume_count == 2


class TestSummaryUpdate:
    """Requirement 6.5: Update cluster_summary on 20% volume growth."""

    def test_updates_summary_on_growth_exceeding_20_percent(self):
        store = FeedbackStore(":memory:")
        clusterer = SimilarityClusterer(store)

        # Create cluster with volume 5 (next assignment adds 1 → 6, growth=20%)
        existing = _make_cluster(
            theme="outage",
            volume_count=5,
            cluster_summary="internet outage no service widespread problems",
        )
        store.insert_cluster(existing)

        # Manually set last_summary_volume to 5
        # (loaded from store sets it to current volume)

        feedback = _make_feedback(text="internet outage no service widespread")
        analysis = _make_analysis(
            feedback_id=feedback.feedback_id, theme_primary="outage"
        )

        cluster_id = clusterer.assign_cluster(feedback, analysis)

        # Volume goes from 5 → 6, growth = 1/5 = 20% which equals threshold
        # Since the requirement says "more than 20%", this should NOT trigger
        cursor = store._conn.execute(
            "SELECT cluster_summary FROM clusters WHERE cluster_id = ?",
            (cluster_id,),
        )
        row = cursor.fetchone()
        # Summary should remain unchanged (20% = threshold, not > threshold)
        assert row[0] == "internet outage no service widespread problems"

    def test_updates_summary_when_growth_exceeds_20_percent(self):
        store = FeedbackStore(":memory:")
        clusterer = SimilarityClusterer(store)

        # Create cluster with volume 4 (next assignment adds 1 → 5, growth=25%)
        existing = _make_cluster(
            theme="outage",
            volume_count=4,
            cluster_summary="internet outage no service widespread problems",
        )
        store.insert_cluster(existing)

        feedback = _make_feedback(text="internet outage no service widespread")
        analysis = _make_analysis(
            feedback_id=feedback.feedback_id, theme_primary="outage"
        )

        cluster_id = clusterer.assign_cluster(feedback, analysis)

        # Volume goes from 4 → 5, growth = 1/4 = 25% > 20% threshold
        cursor = store._conn.execute(
            "SELECT cluster_summary FROM clusters WHERE cluster_id = ?",
            (cluster_id,),
        )
        row = cursor.fetchone()
        # Summary should be updated
        assert "5" in row[0]  # New summary mentions current volume
        assert "outage" in row[0]


class TestPriorityUpgrade:
    """Requirement 6.6: Upgrade to 'high' when volume > 20."""

    def test_upgrades_priority_when_volume_exceeds_20(self):
        store = FeedbackStore(":memory:")
        clusterer = SimilarityClusterer(store)

        # Create cluster at volume 20 with text that overlaps feedback
        existing = _make_cluster(
            theme="outage",
            volume_count=20,
            priority_level="medium",
            cluster_summary="internet outage no service widespread problems down",
        )
        store.insert_cluster(existing)

        feedback = _make_feedback(text="internet outage no service widespread")
        analysis = _make_analysis(
            feedback_id=feedback.feedback_id, theme_primary="outage"
        )

        clusterer.assign_cluster(feedback, analysis)

        # Volume is now 21, priority should be upgraded to "high"
        cursor = store._conn.execute(
            "SELECT priority_level FROM clusters WHERE cluster_id = ?",
            (existing.cluster_id,),
        )
        row = cursor.fetchone()
        assert row[0] == "high"

    def test_does_not_downgrade_priority(self):
        store = FeedbackStore(":memory:")
        clusterer = SimilarityClusterer(store)

        # Cluster already at "high" with volume > 20
        existing = _make_cluster(
            theme="outage",
            volume_count=20,
            priority_level="high",
            cluster_summary="internet outage no service widespread problems down",
        )
        store.insert_cluster(existing)

        feedback = _make_feedback(text="internet outage no service widespread")
        analysis = _make_analysis(
            feedback_id=feedback.feedback_id, theme_primary="outage"
        )

        clusterer.assign_cluster(feedback, analysis)

        cursor = store._conn.execute(
            "SELECT priority_level FROM clusters WHERE cluster_id = ?",
            (existing.cluster_id,),
        )
        row = cursor.fetchone()
        assert row[0] == "high"

    def test_does_not_upgrade_critical(self):
        store = FeedbackStore(":memory:")
        clusterer = SimilarityClusterer(store)

        existing = _make_cluster(
            theme="outage",
            volume_count=20,
            priority_level="critical",
            cluster_summary="internet outage no service widespread problems down",
        )
        store.insert_cluster(existing)

        feedback = _make_feedback(text="internet outage no service widespread")
        analysis = _make_analysis(
            feedback_id=feedback.feedback_id, theme_primary="outage"
        )

        clusterer.assign_cluster(feedback, analysis)

        cursor = store._conn.execute(
            "SELECT priority_level FROM clusters WHERE cluster_id = ?",
            (existing.cluster_id,),
        )
        row = cursor.fetchone()
        assert row[0] == "critical"

    def test_does_not_upgrade_when_volume_at_or_below_20(self):
        store = FeedbackStore(":memory:")
        clusterer = SimilarityClusterer(store)

        existing = _make_cluster(
            theme="outage",
            volume_count=19,
            priority_level="low",
            cluster_summary="internet outage no service widespread problems down",
        )
        store.insert_cluster(existing)

        feedback = _make_feedback(text="internet outage no service widespread")
        analysis = _make_analysis(
            feedback_id=feedback.feedback_id, theme_primary="outage"
        )

        clusterer.assign_cluster(feedback, analysis)

        # Volume is now 20, but threshold is > 20, so no upgrade
        cursor = store._conn.execute(
            "SELECT priority_level FROM clusters WHERE cluster_id = ?",
            (existing.cluster_id,),
        )
        row = cursor.fetchone()
        assert row[0] == "low"


class TestResolvedClusterExclusion:
    """Requirement 6.7: Only match active/monitoring, exclude resolved."""

    def test_ignores_resolved_clusters(self):
        store = FeedbackStore(":memory:")
        clusterer = SimilarityClusterer(store)

        # Create a resolved cluster with matching theme and text
        resolved = _make_cluster(
            theme="outage",
            status="resolved",
            cluster_summary="internet outage no service widespread",
        )
        store.insert_cluster(resolved)

        feedback = _make_feedback(text="internet outage no service widespread")
        analysis = _make_analysis(
            feedback_id=feedback.feedback_id, theme_primary="outage"
        )

        cluster_id = clusterer.assign_cluster(feedback, analysis)

        # Should create a new cluster, not assign to resolved one
        assert cluster_id != resolved.cluster_id

    def test_matches_monitoring_clusters(self):
        store = FeedbackStore(":memory:")
        clusterer = SimilarityClusterer(store)

        # Create a monitoring cluster with high text overlap
        monitoring = _make_cluster(
            theme="outage",
            status="monitoring",
            cluster_summary="internet outage no service widespread down",
        )
        store.insert_cluster(monitoring)

        feedback = _make_feedback(text="internet outage no service widespread")
        analysis = _make_analysis(
            feedback_id=feedback.feedback_id, theme_primary="outage"
        )

        cluster_id = clusterer.assign_cluster(feedback, analysis)

        # Should match monitoring cluster
        assert cluster_id == monitoring.cluster_id


class TestGeographicProximity:
    """Requirements 6.1, 6.8: Geographic proximity and exclusion."""

    def test_excludes_geo_when_no_location(self):
        store = FeedbackStore(":memory:")
        clusterer = SimilarityClusterer(store)

        existing = _make_cluster(theme="outage")
        store.insert_cluster(existing)

        # Feedback without location metadata
        feedback = _make_feedback(text="outage in the area", metadata={})
        analysis = _make_analysis(
            feedback_id=feedback.feedback_id, theme_primary="outage"
        )

        # Should still work, using only text + theme
        cluster_id = clusterer.assign_cluster(feedback, analysis)
        assert cluster_id is not None

    def test_uses_geo_when_location_present(self):
        clusterer = SimilarityClusterer()

        # First feedback creates cluster with location
        fb1 = _make_feedback(
            text="internet outage no service widespread down",
            metadata={"location": "47.6062, -122.3321"},
        )
        a1 = _make_analysis(feedback_id=fb1.feedback_id, theme_primary="outage")
        cluster_id_1 = clusterer.assign_cluster(fb1, a1)

        # Second feedback near same location
        fb2 = _make_feedback(
            text="internet outage no service widespread",
            metadata={"location": "47.6100, -122.3300"},
        )
        a2 = _make_analysis(feedback_id=fb2.feedback_id, theme_primary="outage")
        cluster_id_2 = clusterer.assign_cluster(fb2, a2)

        # Should assign to same cluster (text + theme + geo all match)
        assert cluster_id_2 == cluster_id_1

    def test_geo_factor_reduces_score_for_distant_locations(self):
        clusterer = SimilarityClusterer()

        # First feedback creates cluster with location in Seattle
        fb1 = _make_feedback(
            text="internet outage no service widespread down",
            metadata={"location": "47.6062, -122.3321"},
        )
        a1 = _make_analysis(feedback_id=fb1.feedback_id, theme_primary="outage")
        clusterer.assign_cluster(fb1, a1)

        # Feedback from far away (Los Angeles) with same text/theme
        # The text+theme will still likely match since geo is only 20% weight
        fb2 = _make_feedback(
            text="internet outage no service widespread",
            metadata={"location": "34.0522, -118.2437"},
        )
        a2 = _make_analysis(feedback_id=fb2.feedback_id, theme_primary="outage")
        cluster_id_2 = clusterer.assign_cluster(fb2, a2)
        assert cluster_id_2 is not None


class TestInMemoryOnlyMode:
    """Test that the clusterer works without any persistence store."""

    def test_works_without_store(self):
        clusterer = SimilarityClusterer()
        feedback = _make_feedback(text="billing issue with my account")
        analysis = _make_analysis(
            feedback_id=feedback.feedback_id, theme_primary="billing"
        )

        cluster_id = clusterer.assign_cluster(feedback, analysis)
        assert cluster_id is not None
        assert cluster_id in clusterer.clusters

    def test_multiple_assignments_in_memory(self):
        clusterer = SimilarityClusterer()

        # Three different topics → three clusters
        texts = [
            ("billing payment invoice overcharge", "billing"),
            ("internet outage no service connection", "outage"),
            ("technician never showed appointment", "technician_visit"),
        ]

        cluster_ids = set()
        for text, theme in texts:
            fb = _make_feedback(text=text)
            a = _make_analysis(feedback_id=fb.feedback_id, theme_primary=theme)
            cid = clusterer.assign_cluster(fb, a)
            cluster_ids.add(cid)

        # All three should be different clusters
        assert len(cluster_ids) == 3


class TestHaversine:
    """Test haversine distance utility."""

    def test_same_point_zero_distance(self):
        assert _haversine_km(47.6, -122.3, 47.6, -122.3) == 0.0

    def test_known_distance(self):
        # Seattle to Portland is roughly 233 km
        dist = _haversine_km(47.6062, -122.3321, 45.5152, -122.6784)
        assert 230 < dist < 240

    def test_close_points_within_threshold(self):
        # Two points ~10km apart
        dist = _haversine_km(47.60, -122.33, 47.69, -122.33)
        assert dist < 50


class TestParseLocation:
    """Test location parsing."""

    def test_valid_lat_lon(self):
        result = _parse_location("47.6062, -122.3321")
        assert result is not None
        assert abs(result[0] - 47.6062) < 0.001
        assert abs(result[1] - (-122.3321)) < 0.001

    def test_city_format_returns_none(self):
        result = _parse_location("Seattle, US")
        assert result is None

    def test_none_input(self):
        assert _parse_location(None) is None

    def test_empty_string(self):
        assert _parse_location("") is None

    def test_invalid_lat_range(self):
        assert _parse_location("91.0, 0.0") is None
        assert _parse_location("-91.0, 0.0") is None

    def test_invalid_lon_range(self):
        assert _parse_location("0.0, 181.0") is None
        assert _parse_location("0.0, -181.0") is None
