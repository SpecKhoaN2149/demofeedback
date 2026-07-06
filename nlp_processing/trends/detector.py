"""Trend detection component for the NLP pipeline.

Implements Requirements 3.1, 3.6, 3.7, 3.8, 4.6:
- Compare theme frequency distributions between baseline and current windows.
- Validate time windows (start < end, no overlap).
- Enforce minimum 10-record threshold per window.
- Query PersistenceStore for InsightRecords within each window.

Theme spike computation, sentiment shift detection, and severity escalation
detection are stubbed for implementation in tasks 9.2 and 9.3.
"""

from __future__ import annotations

from datetime import datetime, timezone

from nlp_processing.models.enhancements import (
    SentimentShift,
    SeverityEscalation,
    ThemeSpike,
    TimeWindow,
    TrendReport,
)
from nlp_processing.models.records import InsightRecord
from nlp_processing.persistence.store import PersistenceStore
from nlp_processing.persistence_config import TrendConfig

# Minimum number of records required in each window for reliable statistics.
_MIN_RECORDS = 10


class TrendDetector:
    """Identifies theme frequency spikes, sentiment shifts, and severity escalations.

    Reads persisted InsightRecords within specified time windows from the
    PersistenceStore and applies configurable thresholds to identify
    significant changes between a baseline and current period.
    """

    def __init__(self, store: PersistenceStore, config: TrendConfig) -> None:
        """Initialize the TrendDetector.

        Parameters
        ----------
        store : PersistenceStore
            The persistence backend used to retrieve historical batch data.
        config : TrendConfig
            Configuration containing detection thresholds (spike_threshold_pct,
            sentiment_shift_ppt, severity_escalation).
        """
        self._store = store
        self._config = config

    def detect_trends(
        self, baseline: TimeWindow, current: TimeWindow
    ) -> TrendReport:
        """Detect trends by comparing baseline and current time windows.

        Validates the windows, retrieves InsightRecords from each window,
        and (once implemented) computes theme spikes, sentiment shifts,
        and severity escalations.

        Parameters
        ----------
        baseline : TimeWindow
            The historical reference period (ISO 8601 start/end).
        current : TimeWindow
            The recent period to compare against the baseline.

        Returns
        -------
        TrendReport
            The trend analysis results, which may be empty with a note
            if insufficient data is available.

        Raises
        ------
        ValueError
            If either window has start >= end, or if the windows overlap.
        """
        # 1. Parse and validate individual windows.
        baseline_start = self._parse_timestamp(baseline.start, "baseline.start")
        baseline_end = self._parse_timestamp(baseline.end, "baseline.end")
        current_start = self._parse_timestamp(current.start, "current.start")
        current_end = self._parse_timestamp(current.end, "current.end")

        if baseline_start >= baseline_end:
            raise ValueError(
                "Invalid baseline window: start must be before end "
                f"(start={baseline.start}, end={baseline.end})"
            )
        if current_start >= current_end:
            raise ValueError(
                "Invalid current window: start must be before end "
                f"(start={current.start}, end={current.end})"
            )

        # 2. Check for window overlap.
        # Two windows overlap if max(start_a, start_b) < min(end_a, end_b).
        overlap_start = max(baseline_start, current_start)
        overlap_end = min(baseline_end, current_end)
        if overlap_start < overlap_end:
            raise ValueError(
                "Baseline and current windows must not overlap "
                f"(overlap detected between {overlap_start.isoformat()} "
                f"and {overlap_end.isoformat()})"
            )

        # 3. Query PersistenceStore for batches in each window.
        baseline_records = self._collect_records(baseline_start, baseline_end)
        current_records = self._collect_records(current_start, current_end)

        # 4. Enforce minimum record threshold.
        notes: list[str] = []
        if len(baseline_records) < _MIN_RECORDS:
            notes.append(
                f"Insufficient data in baseline window: "
                f"{len(baseline_records)} records (minimum {_MIN_RECORDS} required)"
            )
        if len(current_records) < _MIN_RECORDS:
            notes.append(
                f"Insufficient data in current window: "
                f"{len(current_records)} records (minimum {_MIN_RECORDS} required)"
            )

        if notes:
            return TrendReport(notes=notes)

        # 5. Compute trends (stubs — implemented in tasks 9.2 and 9.3).
        theme_spikes = self._detect_theme_spikes(baseline_records, current_records)
        sentiment_shifts = self._detect_sentiment_shifts(
            baseline_records, current_records
        )
        severity_escalations = self._detect_severity_escalations(
            baseline_records, current_records
        )

        return TrendReport(
            theme_spikes=theme_spikes,
            sentiment_shifts=sentiment_shifts,
            severity_escalations=severity_escalations,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_timestamp(value: str, label: str) -> datetime:
        """Parse an ISO 8601 timestamp string into a timezone-aware datetime.

        Parameters
        ----------
        value : str
            The ISO 8601 timestamp string to parse.
        label : str
            A human-readable label for error messages (e.g. "baseline.start").

        Returns
        -------
        datetime
            The parsed, timezone-aware datetime (defaults to UTC if naive).

        Raises
        ------
        ValueError
            If the timestamp cannot be parsed.
        """
        try:
            dt = datetime.fromisoformat(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"Cannot parse {label} as ISO 8601 timestamp: {value!r}"
            ) from exc

        # Ensure timezone-aware (assume UTC if naive).
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt

    def _collect_records(
        self, start: datetime, end: datetime
    ) -> list[InsightRecord]:
        """Collect all InsightRecords from batches within a time range.

        Queries PersistenceStore.list_batches for metadata in the range,
        then retrieves each batch and extracts its InsightRecords.

        Parameters
        ----------
        start : datetime
            Inclusive start of the time range (UTC).
        end : datetime
            Exclusive end of the time range (UTC).

        Returns
        -------
        list[InsightRecord]
            All InsightRecords from batches in the given time range.
        """
        batch_metadata_list = self._store.list_batches(start, end)
        records: list[InsightRecord] = []

        for meta in batch_metadata_list:
            batch = self._store.get_batch(meta.batch_id)
            if batch is not None:
                records.extend(batch.insights)

        return records

    def _detect_theme_spikes(
        self,
        baseline_records: list[InsightRecord],
        current_records: list[InsightRecord],
    ) -> list[ThemeSpike]:
        """Detect themes whose relative frequency spiked between windows.

        Computes per-theme relative frequency in each window (count of records
        with that theme / total records) and identifies spikes where the
        percentage increase meets the configured threshold.

        New themes (present in current but absent in baseline) are reported with
        percentage_increase="new". Results are ordered by percentage increase
        descending, with new themes first.

        Implements Requirements 3.2, 3.3, 3.4, 3.5.
        """
        # 1. Compute relative frequency for each theme in each window.
        baseline_freq = self._compute_theme_frequencies(baseline_records)
        current_freq = self._compute_theme_frequencies(current_records)

        # 2. Identify spikes.
        spikes: list[ThemeSpike] = []
        all_themes = set(baseline_freq.keys()) | set(current_freq.keys())

        for theme in all_themes:
            b_freq = baseline_freq.get(theme, 0.0)
            c_freq = current_freq.get(theme, 0.0)

            if c_freq == 0.0:
                continue  # Theme disappeared or not present in current — not a spike

            if b_freq == 0.0:
                # New theme (Req 3.4)
                spikes.append(
                    ThemeSpike(
                        theme=theme,
                        baseline_frequency=0.0,
                        current_frequency=c_freq,
                        percentage_increase="new",
                    )
                )
            else:
                # Compute percentage increase: (current - baseline) / baseline × 100
                pct_increase = (c_freq - b_freq) / b_freq * 100
                if pct_increase >= self._config.spike_threshold_pct:
                    spikes.append(
                        ThemeSpike(
                            theme=theme,
                            baseline_frequency=b_freq,
                            current_frequency=c_freq,
                            percentage_increase=pct_increase,
                        )
                    )

        # 3. Order by percentage increase descending.
        # "new" themes sort first, then numeric percentage descending (Req 3.5).
        def sort_key(spike: ThemeSpike) -> tuple[int, float]:
            if spike.percentage_increase == "new":
                return (0, 0.0)
            return (1, -spike.percentage_increase)  # type: ignore[operator]

        spikes.sort(key=sort_key)
        return spikes

    def _compute_theme_frequencies(
        self, records: list[InsightRecord]
    ) -> dict[str, float]:
        """Compute relative theme frequency (count / total_records).

        Each record contributes one count per distinct theme assigned to it
        (Req 3.2). Returns an empty dict when there are no records.
        """
        if not records:
            return {}
        total = len(records)
        theme_counts: dict[str, int] = {}
        for record in records:
            for theme_assignment in record.themes:
                theme = theme_assignment.theme
                theme_counts[theme] = theme_counts.get(theme, 0) + 1
        return {theme: count / total for theme, count in theme_counts.items()}

    def _detect_sentiment_shifts(
        self,
        baseline_records: list[InsightRecord],
        current_records: list[InsightRecord],
    ) -> list[SentimentShift]:
        """Detect sentiment shifts between windows.

        Computes negative/neutral/positive proportions (summing to 1.0) in
        each window (excluding records without a sentiment value) and
        identifies a shift when the current negative proportion exceeds the
        baseline by at least the configured threshold in percentage points.

        Implements Requirements 4.1, 4.2, 4.5, 4.7.
        """
        # Filter records that have a sentiment value
        baseline_with_sentiment = [r for r in baseline_records if r.sentiment is not None]
        current_with_sentiment = [r for r in current_records if r.sentiment is not None]

        # Need minimum 10 records with sentiment in each window
        if len(baseline_with_sentiment) < _MIN_RECORDS or len(current_with_sentiment) < _MIN_RECORDS:
            return []

        # Compute proportions
        baseline_props = self._compute_sentiment_proportions(baseline_with_sentiment)
        current_props = self._compute_sentiment_proportions(current_with_sentiment)

        # Check if negative proportion increased by >= threshold (in percentage points)
        baseline_neg = baseline_props["negative"]
        current_neg = current_props["negative"]
        diff_ppt = (current_neg - baseline_neg) * 100  # Convert to percentage points

        if diff_ppt >= self._config.sentiment_shift_ppt:
            return [SentimentShift(
                baseline_negative_proportion=baseline_neg,
                current_negative_proportion=current_neg,
                difference_ppt=diff_ppt,
            )]
        return []

    def _compute_sentiment_proportions(
        self, records: list[InsightRecord]
    ) -> dict[str, float]:
        """Compute sentiment proportions (negative, neutral, positive) summing to 1.0.

        Each record's sentiment value is counted and divided by the total
        number of records. Implements Requirement 4.1.
        """
        total = len(records)
        if total == 0:
            return {"negative": 0.0, "neutral": 0.0, "positive": 0.0}
        counts: dict[str, int] = {"negative": 0, "neutral": 0, "positive": 0}
        for record in records:
            sentiment = record.sentiment
            if sentiment in counts:
                counts[sentiment] += 1
        return {k: v / total for k, v in counts.items()}

    def _detect_severity_escalations(
        self,
        baseline_records: list[InsightRecord],
        current_records: list[InsightRecord],
    ) -> list[SeverityEscalation]:
        """Detect severity escalations between windows.

        Computes mean severity score in each window (excluding records without
        a severity_score) and identifies an escalation when the current mean
        exceeds the baseline mean by at least the configured threshold.

        Implements Requirements 4.3, 4.4, 4.5, 4.7.
        """
        # Filter records that have a severity_score
        baseline_with_severity = [r for r in baseline_records if r.severity_score is not None]
        current_with_severity = [r for r in current_records if r.severity_score is not None]

        # Need minimum 10 records with severity in each window
        if len(baseline_with_severity) < _MIN_RECORDS or len(current_with_severity) < _MIN_RECORDS:
            return []

        # Compute mean severity
        baseline_mean = sum(r.severity_score for r in baseline_with_severity) / len(baseline_with_severity)
        current_mean = sum(r.severity_score for r in current_with_severity) / len(current_with_severity)

        diff = current_mean - baseline_mean
        if diff >= self._config.severity_escalation:
            return [SeverityEscalation(
                baseline_mean_severity=baseline_mean,
                current_mean_severity=current_mean,
                difference=diff,
            )]
        return []
