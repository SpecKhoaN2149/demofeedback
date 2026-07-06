"""Property-based tests for the Prioritization_Component (Req 9).

Covers:

* Property 24 — Priority scoring is deterministic and non-negative
  (Req 9.1, 9.4, 9.5)
* Property 25 — Priority ordering with tie-breakers (Req 9.2, 9.3)
* Property 26 — Priority is monotonic in each contributing factor
  (Req 9.6, 9.7, 9.8)

Each test exercises a single function and runs at least 100 iterations.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from nlp_processing.aggregation.prioritization import (
    PrioritizationComponent,
    aggregate_factors,
    compute_priority,
)

from tests.strategies import cluster, cluster_with_factors

# Shared settings: minimum 100 iterations as required. ``cluster`` uses nested
# ``draw`` calls inside ``@st.composite``, so suppress the function-scoped
# fixture / data-generation health checks that can fire on composite reuse.
_PBT_SETTINGS = settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Property 24: Priority scoring is deterministic and non-negative
# Feature: nlp-feedback-processing, Property 24: Priority scoring is
# deterministic and non-negative — identical cluster contents always yield an
# identical score, the score is always at least zero, and it is recorded on
# the cluster.
# Validates: Requirements 9.1, 9.4, 9.5
# ---------------------------------------------------------------------------
@_PBT_SETTINGS
@given(data=cluster())
def test_property_24_priority_scoring_deterministic_and_non_negative(data):
    cluster_obj, insights = data
    component = PrioritizationComponent()

    # Determinism: identical contents -> identical score (Req 9.1).
    first = component.prioritize([cluster_obj], insights)
    second = component.prioritize([cluster_obj], insights)
    assert len(first) == 1 and len(second) == 1
    assert first[0].priority_score == second[0].priority_score

    # Pure scoring function is itself deterministic over the same factors.
    sev, count, neg = aggregate_factors(cluster_obj, insights)
    assert compute_priority(sev, count, neg) == compute_priority(sev, count, neg)

    # Non-negative (Req 9.4) and recorded on the returned cluster (Req 9.5).
    assert first[0].priority_score >= 0.0
    assert first[0].priority_score == compute_priority(sev, count, neg)


# ---------------------------------------------------------------------------
# Property 25: Priority ordering with tie-breakers
# Feature: nlp-feedback-processing, Property 25: Priority ordering with
# tie-breakers — output is ordered by descending priority score; ties broken
# by higher record count first, then by ascending cluster label.
# Validates: Requirements 9.2, 9.3
# ---------------------------------------------------------------------------
@_PBT_SETTINGS
@given(pairs=st.lists(cluster(), min_size=1, max_size=8))
def test_property_25_priority_ordering_with_tie_breakers(pairs):
    component = PrioritizationComponent()

    clusters = [c for c, _ in pairs]
    insights: dict = {}
    for _, ins in pairs:
        insights.update(ins)

    ordered = component.prioritize(clusters, insights)

    # Same multiset of clusters back, just reordered and re-scored.
    assert len(ordered) == len(clusters)

    # Verify each adjacent pair respects the ordering contract (Req 9.2, 9.3).
    for left, right in zip(ordered, ordered[1:]):
        left_key = (-left.priority_score, -len(left.member_ids), left.label)
        right_key = (-right.priority_score, -len(right.member_ids), right.label)
        assert left_key <= right_key


# ---------------------------------------------------------------------------
# Property 26: Priority is monotonic in each contributing factor
# Feature: nlp-feedback-processing, Property 26: Priority is monotonic in each
# contributing factor — increasing the total severity, OR the record count, OR
# the negative-sentiment count (holding the others equal) never decreases the
# priority score.
# Validates: Requirements 9.6, 9.7, 9.8
# ---------------------------------------------------------------------------
@_PBT_SETTINGS
@given(data=st.data())
def test_property_26_priority_monotonic_in_each_factor(data):
    component = PrioritizationComponent()

    def score(sev: int, count: int, neg: int) -> float:
        c, ins = data.draw(
            cluster_with_factors(
                severity_total=sev,
                record_count=count,
                negative_count=neg,
            )
        )
        out = component.prioritize([c], ins)
        # The recorded score must equal the pure function (Req 9.5 sanity).
        assert out[0].priority_score == compute_priority(sev, count, neg)
        return out[0].priority_score

    # Base factors, with headroom so each factor can strictly increase while
    # the others stay equal and the cluster constraints remain satisfiable
    # (each member severity is 1..5, so count <= severity_total <= 5*count).
    count = data.draw(st.integers(min_value=1, max_value=6))
    # severity_total in [count + 1, 5*count - 1]: the lower bound leaves room
    # to raise the record count by one while holding severity_total fixed
    # (need severity_total >= count + 1); the upper bound leaves room to add
    # one to severity_total (need severity_total + 1 <= 5*count).
    severity_total = data.draw(
        st.integers(min_value=count + 1, max_value=5 * count - 1)
    )
    negative_count = data.draw(st.integers(min_value=0, max_value=count - 1))

    base = score(severity_total, count, negative_count)

    # (9.6) Strictly higher total severity, others equal -> score >= base.
    higher_sev = score(severity_total + 1, count, negative_count)
    assert higher_sev >= base

    # (9.7) Strictly higher record count, severity_total and negative_count
    # held equal -> score >= base. Valid because count + 1 <= severity_total
    # <= 5*(count + 1).
    higher_count = score(severity_total, count + 1, negative_count)
    assert higher_count >= base

    # (9.8) Strictly higher negative count, others equal -> score >= base.
    higher_neg = score(severity_total, count, negative_count + 1)
    assert higher_neg >= base
