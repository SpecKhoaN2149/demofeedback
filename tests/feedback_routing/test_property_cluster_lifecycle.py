# Feature: nlp-feedback-routing, Property 15
"""Property test for Cluster Lifecycle Transitions.

**Property 15: Cluster Lifecycle Transitions** — For any cluster with status
"active" whose last_seen_at is more than 7 days before the current evaluation
time, the status SHALL transition to "monitoring". For any cluster with status
"monitoring" whose last_seen_at is more than 21 days before the current
evaluation time, the status SHALL transition to "resolved".

**Validates: Requirements 22.7, 22.8**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from nlp_processing.trends.feedback_trends import ClusterInfo, TrendDetector


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate days inactive as a float (0 to 60 days covers all scenarios)
_days_inactive = st.floats(min_value=0.0, max_value=60.0, allow_nan=False, allow_infinity=False)

# Cluster statuses relevant to lifecycle transitions
_lifecycle_statuses = st.sampled_from(["active", "monitoring", "resolved"])

# Volume counts (valid: >= 1)
_volume_counts = st.integers(min_value=1, max_value=500)


@st.composite
def cluster_info_with_inactivity(
    draw: st.DrawFn,
    *,
    status: str | None = None,
    min_days_inactive: float = 0.0,
    max_days_inactive: float = 60.0,
) -> tuple[ClusterInfo, datetime, float]:
    """Generate a ClusterInfo with a specific inactivity duration.

    Returns (cluster, evaluation_time, days_inactive) tuple.
    """
    chosen_status = status if status is not None else draw(_lifecycle_statuses)
    days_inactive = draw(
        st.floats(
            min_value=min_days_inactive,
            max_value=max_days_inactive,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    volume_count = draw(_volume_counts)

    # Fixed evaluation time for determinism
    evaluation_time = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

    # last_seen_at is days_inactive days before evaluation_time
    last_seen = evaluation_time - timedelta(days=days_inactive)
    last_seen_str = last_seen.strftime("%Y-%m-%dT%H:%M:%SZ")

    # first_seen_at is always before last_seen_at
    first_seen = last_seen - timedelta(days=draw(st.integers(min_value=1, max_value=90)))
    first_seen_str = first_seen.strftime("%Y-%m-%dT%H:%M:%SZ")

    cluster = ClusterInfo(
        cluster_id=str(uuid.uuid4()),
        status=chosen_status,
        first_seen_at=first_seen_str,
        last_seen_at=last_seen_str,
        volume_count=volume_count,
    )

    return cluster, evaluation_time, days_inactive


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    data=cluster_info_with_inactivity(
        status="active",
        min_days_inactive=7.001,
        max_days_inactive=60.0,
    )
)
def test_active_cluster_transitions_to_monitoring_after_7_days(
    data: tuple[ClusterInfo, datetime, float],
) -> None:
    """Active clusters inactive for more than 7 days transition to monitoring.

    **Validates: Requirements 22.7**
    """
    cluster, evaluation_time, days_inactive = data
    detector = TrendDetector()

    changes = detector.evaluate_cluster_lifecycle(
        [cluster], evaluation_time=evaluation_time
    )

    assert len(changes) == 1, (
        f"Expected 1 lifecycle change for active cluster inactive "
        f"{days_inactive:.2f} days, got {len(changes)}"
    )
    change = changes[0]
    assert change.cluster_id == cluster.cluster_id
    assert change.previous_status == "active"
    assert change.new_status == "monitoring"
    assert change.last_seen_at == cluster.last_seen_at


@settings(max_examples=100)
@given(
    data=cluster_info_with_inactivity(
        status="active",
        min_days_inactive=0.0,
        max_days_inactive=7.0,
    )
)
def test_active_cluster_no_transition_within_7_days(
    data: tuple[ClusterInfo, datetime, float],
) -> None:
    """Active clusters inactive for 7 days or fewer do NOT transition.

    **Validates: Requirements 22.7**
    """
    cluster, evaluation_time, days_inactive = data
    detector = TrendDetector()

    changes = detector.evaluate_cluster_lifecycle(
        [cluster], evaluation_time=evaluation_time
    )

    assert len(changes) == 0, (
        f"Expected no lifecycle change for active cluster inactive "
        f"{days_inactive:.2f} days, but got {len(changes)} change(s)"
    )


@settings(max_examples=100)
@given(
    data=cluster_info_with_inactivity(
        status="monitoring",
        min_days_inactive=21.001,
        max_days_inactive=60.0,
    )
)
def test_monitoring_cluster_transitions_to_resolved_after_21_days(
    data: tuple[ClusterInfo, datetime, float],
) -> None:
    """Monitoring clusters inactive for more than 21 days transition to resolved.

    **Validates: Requirements 22.8**
    """
    cluster, evaluation_time, days_inactive = data
    detector = TrendDetector()

    changes = detector.evaluate_cluster_lifecycle(
        [cluster], evaluation_time=evaluation_time
    )

    assert len(changes) == 1, (
        f"Expected 1 lifecycle change for monitoring cluster inactive "
        f"{days_inactive:.2f} days, got {len(changes)}"
    )
    change = changes[0]
    assert change.cluster_id == cluster.cluster_id
    assert change.previous_status == "monitoring"
    assert change.new_status == "resolved"
    assert change.last_seen_at == cluster.last_seen_at


@settings(max_examples=100)
@given(
    data=cluster_info_with_inactivity(
        status="monitoring",
        min_days_inactive=0.0,
        max_days_inactive=21.0,
    )
)
def test_monitoring_cluster_no_transition_within_21_days(
    data: tuple[ClusterInfo, datetime, float],
) -> None:
    """Monitoring clusters inactive for 21 days or fewer do NOT transition.

    **Validates: Requirements 22.8**
    """
    cluster, evaluation_time, days_inactive = data
    detector = TrendDetector()

    changes = detector.evaluate_cluster_lifecycle(
        [cluster], evaluation_time=evaluation_time
    )

    assert len(changes) == 0, (
        f"Expected no lifecycle change for monitoring cluster inactive "
        f"{days_inactive:.2f} days, but got {len(changes)} change(s)"
    )


@settings(max_examples=100)
@given(
    data=cluster_info_with_inactivity(
        status="resolved",
        min_days_inactive=0.0,
        max_days_inactive=60.0,
    )
)
def test_resolved_cluster_never_transitions(
    data: tuple[ClusterInfo, datetime, float],
) -> None:
    """Resolved clusters never have lifecycle transitions regardless of inactivity.

    **Validates: Requirements 22.7, 22.8**
    """
    cluster, evaluation_time, days_inactive = data
    detector = TrendDetector()

    changes = detector.evaluate_cluster_lifecycle(
        [cluster], evaluation_time=evaluation_time
    )

    assert len(changes) == 0, (
        f"Expected no lifecycle change for resolved cluster, "
        f"but got {len(changes)} change(s)"
    )
