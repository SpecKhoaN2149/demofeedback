"""Trend detection for the feedback routing pipeline.

Implements Requirement 22: Trend Detection and Insights
- 22.1: Theme frequency distribution, volume spike detection, new cluster emergence rate
- 22.2: Volume spike recording with theme label, volume, baseline, timestamp
- 22.3: Sentiment trend computation for clusters with 20+ records
- 22.4: Sentiment trend "stable" for clusters with < 20 records
- 22.5: Time-range queries for trend computation
- 22.6: Cluster activity evaluation every 24 hours
- 22.7: Active → monitoring after 7 days no activity
- 22.8: Monitoring → resolved after 21 days total no activity

Uses FeedbackAnalysis and ClusterRecord models from the feedback routing schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass
class VolumeSpikeEvent:
    """Record of a volume spike for a specific theme.

    Attributes
    ----------
    theme : str
        The theme that experienced the spike.
    current_volume : int
        The current volume count for the theme.
    rolling_average : float
        The 7-day rolling average volume for the theme.
    detection_timestamp : str
        ISO 8601 UTC timestamp when the spike was detected.
    """

    theme: str
    current_volume: int
    rolling_average: float
    detection_timestamp: str


@dataclass
class ThemeFrequency:
    """Theme frequency data within a time window.

    Attributes
    ----------
    theme : str
        The theme label.
    count : int
        Number of feedback records with this theme in the window.
    proportion : float
        Proportion relative to total feedback in the window.
    """

    theme: str
    count: int
    proportion: float


@dataclass
class ClusterLifecycleChange:
    """Record of a cluster lifecycle transition.

    Attributes
    ----------
    cluster_id : str
        The cluster that transitioned.
    previous_status : str
        Status before the transition.
    new_status : str
        Status after the transition.
    last_seen_at : str
        The cluster's last_seen_at timestamp.
    evaluation_timestamp : str
        ISO 8601 UTC timestamp when the evaluation occurred.
    """

    cluster_id: str
    previous_status: str
    new_status: str
    last_seen_at: str
    evaluation_timestamp: str


@dataclass
class TrendResult:
    """Aggregated trend detection results.

    Attributes
    ----------
    volume_spikes : list[VolumeSpikeEvent]
        Detected volume spikes.
    theme_frequencies : list[ThemeFrequency]
        Theme frequency distribution for the current window.
    sentiment_trends : dict[str, str]
        Mapping of cluster_id to sentiment trend ("improving", "stable", "deteriorating").
    lifecycle_changes : list[ClusterLifecycleChange]
        Cluster lifecycle transitions applied.
    new_cluster_count : int
        Number of new clusters created within the time window.
    notes : list[str]
        Informational notes about the computation.
    """

    volume_spikes: list[VolumeSpikeEvent] = field(default_factory=list)
    theme_frequencies: list[ThemeFrequency] = field(default_factory=list)
    sentiment_trends: dict[str, str] = field(default_factory=dict)
    lifecycle_changes: list[ClusterLifecycleChange] = field(default_factory=list)
    new_cluster_count: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class FeedbackRecord:
    """Lightweight record for trend computation input.

    Represents a feedback analysis result with the fields needed
    for trend detection. Can be constructed from FeedbackAnalysis
    model or from raw query results.

    Attributes
    ----------
    feedback_id : str
        Unique feedback identifier.
    theme_primary : str
        Primary theme assigned to the feedback.
    sentiment_score : float
        Sentiment score from -1.0 to 1.0.
    cluster_id : str | None
        Associated cluster identifier, if any.
    processed_at : str
        ISO 8601 UTC timestamp when the feedback was processed.
    """

    feedback_id: str
    theme_primary: str
    sentiment_score: float
    cluster_id: str | None
    processed_at: str


@dataclass
class ClusterInfo:
    """Lightweight record for cluster lifecycle evaluation.

    Attributes
    ----------
    cluster_id : str
        Unique cluster identifier.
    status : str
        Current cluster status ("active", "monitoring", "resolved").
    first_seen_at : str
        ISO 8601 UTC timestamp when the cluster was first seen.
    last_seen_at : str
        ISO 8601 UTC timestamp of most recent activity.
    volume_count : int
        Total number of feedback records in the cluster.
    """

    cluster_id: str
    status: str
    first_seen_at: str
    last_seen_at: str
    volume_count: int


class TrendDetector:
    """Detects trends in feedback data for the routing pipeline.

    Implements volume spike detection, sentiment trend computation,
    cluster lifecycle evaluation, theme frequency distribution, and
    new cluster emergence rate tracking.

    Parameters
    ----------
    window_days : int
        Time window for theme frequency distribution (1–90 days, default 7).
    """

    def __init__(self, window_days: int = 7) -> None:
        """Initialize the TrendDetector with a configurable window.

        Parameters
        ----------
        window_days : int
            Time window for theme frequency computation.
            Must be between 1 and 90 (inclusive). Default is 7.

        Raises
        ------
        ValueError
            If window_days is outside the valid range [1, 90].
        """
        if not (1 <= window_days <= 90):
            raise ValueError(
                f"window_days must be between 1 and 90, got {window_days}"
            )
        self._window_days = window_days

    @property
    def window_days(self) -> int:
        """The configured time window in days."""
        return self._window_days

    # ------------------------------------------------------------------
    # Volume Spike Detection (Req 22.1, 22.2)
    # ------------------------------------------------------------------

    def detect_volume_spikes(
        self,
        daily_theme_volumes: dict[str, list[int]],
        *,
        evaluation_time: datetime | None = None,
    ) -> list[VolumeSpikeEvent]:
        """Detect themes whose current volume exceeds 2x the 7-day rolling average.

        Parameters
        ----------
        daily_theme_volumes : dict[str, list[int]]
            Mapping of theme label to a list of daily volume counts,
            ordered chronologically. The last element is the current day.
            Requires at least 8 entries (7 days history + 1 current day)
            per theme for spike detection.
        evaluation_time : datetime | None
            The evaluation timestamp. Defaults to current UTC time.

        Returns
        -------
        list[VolumeSpikeEvent]
            List of spike events for themes exceeding the threshold.
        """
        if evaluation_time is None:
            evaluation_time = datetime.now(timezone.utc)

        timestamp = evaluation_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        spikes: list[VolumeSpikeEvent] = []

        for theme, volumes in daily_theme_volumes.items():
            # Need at least 7 days of prior data + 1 current day
            if len(volumes) < 8:
                continue

            # Rolling 7-day average is computed from the 7 days before the current day
            rolling_window = volumes[-8:-1]  # 7 days before current
            rolling_avg = sum(rolling_window) / 7.0
            current_volume = volumes[-1]

            # Spike: current volume > 2x rolling average
            if rolling_avg > 0 and current_volume > 2.0 * rolling_avg:
                spikes.append(
                    VolumeSpikeEvent(
                        theme=theme,
                        current_volume=current_volume,
                        rolling_average=rolling_avg,
                        detection_timestamp=timestamp,
                    )
                )

        return spikes

    # ------------------------------------------------------------------
    # Sentiment Trend Computation (Req 22.3, 22.4)
    # ------------------------------------------------------------------

    def compute_sentiment_trend(
        self, records: list[FeedbackRecord]
    ) -> str:
        """Compute sentiment trend for a cluster's feedback records.

        For clusters with 20+ records: compares the average sentiment_score
        of the 10 most recent records (by processed_at) to the average of
        the 10 oldest records.

        - "improving": recent avg exceeds oldest avg by more than 0.1
        - "deteriorating": oldest avg exceeds recent avg by more than 0.1
        - "stable": difference is 0.1 or less

        For clusters with fewer than 20 records: always returns "stable".

        Parameters
        ----------
        records : list[FeedbackRecord]
            All feedback records belonging to a single cluster,
            ordered by processed_at timestamp.

        Returns
        -------
        str
            One of "improving", "stable", or "deteriorating".
        """
        if len(records) < 20:
            return "stable"

        # Sort by processed_at to ensure correct ordering
        sorted_records = sorted(records, key=lambda r: r.processed_at)

        # 10 oldest and 10 most recent
        oldest_10 = sorted_records[:10]
        recent_10 = sorted_records[-10:]

        oldest_avg = sum(r.sentiment_score for r in oldest_10) / 10.0
        recent_avg = sum(r.sentiment_score for r in recent_10) / 10.0

        diff = recent_avg - oldest_avg

        if diff > 0.1:
            return "improving"
        elif diff < -0.1:
            return "deteriorating"
        else:
            return "stable"

    def compute_cluster_sentiment_trends(
        self, cluster_records: dict[str, list[FeedbackRecord]]
    ) -> dict[str, str]:
        """Compute sentiment trends for multiple clusters.

        Parameters
        ----------
        cluster_records : dict[str, list[FeedbackRecord]]
            Mapping of cluster_id to the list of feedback records
            belonging to that cluster.

        Returns
        -------
        dict[str, str]
            Mapping of cluster_id to sentiment trend string.
        """
        return {
            cluster_id: self.compute_sentiment_trend(records)
            for cluster_id, records in cluster_records.items()
        }

    # ------------------------------------------------------------------
    # Cluster Lifecycle Evaluation (Req 22.6, 22.7, 22.8)
    # ------------------------------------------------------------------

    def evaluate_cluster_lifecycle(
        self,
        clusters: list[ClusterInfo],
        *,
        evaluation_time: datetime | None = None,
    ) -> list[ClusterLifecycleChange]:
        """Evaluate cluster lifecycle status transitions.

        Rules:
        - Active clusters with no activity for 7+ days → "monitoring"
        - Monitoring clusters with no activity for 21+ days total → "resolved"

        Parameters
        ----------
        clusters : list[ClusterInfo]
            The clusters to evaluate.
        evaluation_time : datetime | None
            The evaluation timestamp. Defaults to current UTC time.

        Returns
        -------
        list[ClusterLifecycleChange]
            List of lifecycle transitions that should be applied.
        """
        if evaluation_time is None:
            evaluation_time = datetime.now(timezone.utc)

        timestamp = evaluation_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        changes: list[ClusterLifecycleChange] = []

        for cluster in clusters:
            last_seen = self._parse_timestamp(cluster.last_seen_at)
            days_inactive = (evaluation_time - last_seen).total_seconds() / 86400.0

            if cluster.status == "active" and days_inactive > 7:
                changes.append(
                    ClusterLifecycleChange(
                        cluster_id=cluster.cluster_id,
                        previous_status="active",
                        new_status="monitoring",
                        last_seen_at=cluster.last_seen_at,
                        evaluation_timestamp=timestamp,
                    )
                )
            elif cluster.status == "monitoring" and days_inactive > 21:
                changes.append(
                    ClusterLifecycleChange(
                        cluster_id=cluster.cluster_id,
                        previous_status="monitoring",
                        new_status="resolved",
                        last_seen_at=cluster.last_seen_at,
                        evaluation_timestamp=timestamp,
                    )
                )

        return changes

    # ------------------------------------------------------------------
    # Theme Frequency Distribution (Req 22.1)
    # ------------------------------------------------------------------

    def compute_theme_frequencies(
        self, records: list[FeedbackRecord]
    ) -> list[ThemeFrequency]:
        """Compute theme frequency distribution over the configured window.

        Parameters
        ----------
        records : list[FeedbackRecord]
            Feedback records within the configured time window.

        Returns
        -------
        list[ThemeFrequency]
            Theme frequency distribution sorted by count descending.
        """
        if not records:
            return []

        total = len(records)
        theme_counts: dict[str, int] = {}

        for record in records:
            theme = record.theme_primary
            theme_counts[theme] = theme_counts.get(theme, 0) + 1

        frequencies = [
            ThemeFrequency(
                theme=theme,
                count=count,
                proportion=count / total,
            )
            for theme, count in theme_counts.items()
        ]

        # Sort by count descending
        frequencies.sort(key=lambda f: f.count, reverse=True)
        return frequencies

    # ------------------------------------------------------------------
    # New Cluster Emergence Rate (Req 22.1)
    # ------------------------------------------------------------------

    def compute_new_cluster_count(
        self,
        clusters: list[ClusterInfo],
        *,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> int:
        """Count clusters created within the specified time window.

        Parameters
        ----------
        clusters : list[ClusterInfo]
            All clusters to evaluate.
        window_start : datetime | None
            Start of the window. Defaults to (now - window_days).
        window_end : datetime | None
            End of the window. Defaults to now.

        Returns
        -------
        int
            Number of new clusters created within the window.
        """
        now = datetime.now(timezone.utc)
        if window_end is None:
            window_end = now
        if window_start is None:
            window_start = window_end - timedelta(days=self._window_days)

        count = 0
        for cluster in clusters:
            first_seen = self._parse_timestamp(cluster.first_seen_at)
            if window_start <= first_seen <= window_end:
                count += 1

        return count

    # ------------------------------------------------------------------
    # Full Trend Analysis (combines all detectors)
    # ------------------------------------------------------------------

    def analyze(
        self,
        records: list[FeedbackRecord],
        clusters: list[ClusterInfo],
        daily_theme_volumes: dict[str, list[int]],
        *,
        evaluation_time: datetime | None = None,
    ) -> TrendResult:
        """Run full trend analysis combining all detection methods.

        Parameters
        ----------
        records : list[FeedbackRecord]
            Feedback records within the configured time window.
        clusters : list[ClusterInfo]
            All clusters to evaluate for lifecycle and emergence.
        daily_theme_volumes : dict[str, list[int]]
            Daily volume data per theme for spike detection.
        evaluation_time : datetime | None
            The evaluation timestamp. Defaults to current UTC time.

        Returns
        -------
        TrendResult
            Aggregated trend detection results.
        """
        if evaluation_time is None:
            evaluation_time = datetime.now(timezone.utc)

        # Volume spike detection
        volume_spikes = self.detect_volume_spikes(
            daily_theme_volumes, evaluation_time=evaluation_time
        )

        # Theme frequency distribution
        theme_frequencies = self.compute_theme_frequencies(records)

        # Sentiment trends per cluster
        cluster_records: dict[str, list[FeedbackRecord]] = {}
        for record in records:
            if record.cluster_id is not None:
                cluster_records.setdefault(record.cluster_id, []).append(record)

        sentiment_trends = self.compute_cluster_sentiment_trends(cluster_records)

        # Cluster lifecycle evaluation
        lifecycle_changes = self.evaluate_cluster_lifecycle(
            clusters, evaluation_time=evaluation_time
        )

        # New cluster emergence rate
        window_end = evaluation_time
        window_start = window_end - timedelta(days=self._window_days)
        new_cluster_count = self.compute_new_cluster_count(
            clusters, window_start=window_start, window_end=window_end
        )

        # Notes
        notes: list[str] = []
        for cluster_id, trend in sentiment_trends.items():
            cr = cluster_records.get(cluster_id, [])
            if len(cr) < 20:
                notes.append(
                    f"Cluster '{cluster_id}': insufficient data for trend "
                    f"calculation ({len(cr)} records, minimum 20 required)"
                )

        return TrendResult(
            volume_spikes=volume_spikes,
            theme_frequencies=theme_frequencies,
            sentiment_trends=sentiment_trends,
            lifecycle_changes=lifecycle_changes,
            new_cluster_count=new_cluster_count,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        """Parse an ISO 8601 timestamp string into a timezone-aware datetime.

        Parameters
        ----------
        value : str
            The ISO 8601 timestamp string to parse.

        Returns
        -------
        datetime
            The parsed, timezone-aware datetime (defaults to UTC if naive).
        """
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
