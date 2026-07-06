"""Prioritization_Component: deterministic priority scoring and ranking (Req 9).

This module ranks :class:`~nlp_processing.models.records.Cluster` objects by a
pure, deterministic priority score so that downstream teams address the most
important problems first.

Input interface
---------------
A :class:`Cluster` carries only its identity, label, and member feedback ids;
it does **not** itself carry severity scores or sentiment values. Those live on
the per-record :class:`~nlp_processing.models.records.InsightRecord`s produced
by the enrichment layer. Computing a priority score therefore requires both:

* the clusters to rank, and
* a way to look up the enriched insight for each member id.

`prioritize` accepts the clusters plus an ``insights`` mapping
(``feedback_id -> InsightRecord``). The orchestrator already holds the batch's
insights keyed by id, so this is a clean, side-effect-free contract that keeps
the component pure and trivially testable without a network.

Scoring function (Req 9.1, 9.4, 9.6, 9.7, 9.8)
----------------------------------------------
::

    priority(cluster) = max(0,
          w_sev * sum(severity_scores)
        + w_vol * count(records)
        + w_neg * count(negative_sentiments))

With fixed, strictly positive weights, this is:

* **deterministic** — identical cluster contents yield an identical score
  (Req 9.1);
* **non-negative** — clamped at zero (Req 9.4);
* **monotonic** — increasing any single factor never decreases the score
  (Req 9.6, 9.7, 9.8).

Ordering (Req 9.2, 9.3)
-----------------------
Descending priority, then descending member (record) count, then ascending
cluster label. The computed score is recorded on each returned cluster
(Req 9.5).
"""

from __future__ import annotations

from collections.abc import Mapping

from ..models.records import Cluster, InsightRecord

# Fixed, strictly positive weights. Positivity is what guarantees the scoring
# function is monotonic in each contributing factor (Req 9.6, 9.7, 9.8).
W_SEV: float = 2.0  # weight on total severity within the cluster
W_VOL: float = 1.0  # weight on the number of records (volume) in the cluster
W_NEG: float = 3.0  # weight on the number of negative-sentiment records

assert W_SEV > 0 and W_VOL > 0 and W_NEG > 0, "priority weights must be positive"


def compute_priority(
    severity_total: int,
    record_count: int,
    negative_count: int,
) -> float:
    """Return the non-negative priority score for the given cluster factors.

    Pure and deterministic: the same factors always produce the same score
    (Req 9.1). The result is clamped to a minimum of zero (Req 9.4).
    """
    raw = (
        W_SEV * severity_total
        + W_VOL * record_count
        + W_NEG * negative_count
    )
    return max(0.0, raw)


def aggregate_factors(
    cluster: Cluster,
    insights: Mapping[str, InsightRecord],
) -> tuple[int, int, int]:
    """Aggregate the scoring factors for a single cluster.

    Returns ``(severity_total, record_count, negative_count)`` where:

    * ``severity_total`` is the sum of ``severity_score`` over the cluster's
      member insights,
    * ``record_count`` is the number of member records in the cluster
      (``len(member_ids)``), used for both scoring volume and the tie-breaker,
    * ``negative_count`` is the number of member insights with negative
      sentiment.

    Member ids without a matching insight contribute nothing to the severity
    and negative totals but still count toward ``record_count``.
    """
    severity_total = 0
    negative_count = 0
    for member_id in cluster.member_ids:
        insight = insights.get(member_id)
        if insight is None:
            continue
        severity_total += insight.severity_score
        if insight.sentiment == "negative":
            negative_count += 1
    return severity_total, len(cluster.member_ids), negative_count


class PrioritizationComponent:
    """Ranks clusters by a deterministic, non-negative, monotonic score (Req 9)."""

    def prioritize(
        self,
        clusters: list[Cluster],
        insights: Mapping[str, InsightRecord],
    ) -> list[Cluster]:
        """Score and rank ``clusters`` using their member ``insights``.

        For each cluster, computes its priority score (Req 9.1, 9.4), records
        the score on a copy of the cluster (Req 9.5), and returns the clusters
        ordered by descending priority, then descending record count, then
        ascending label (Req 9.2, 9.3).

        Does not mutate the input clusters; returns new ``Cluster`` instances.
        """
        scored: list[Cluster] = []
        for cluster in clusters:
            severity_total, record_count, negative_count = aggregate_factors(
                cluster, insights
            )
            score = compute_priority(severity_total, record_count, negative_count)
            scored.append(cluster.model_copy(update={"priority_score": score}))

        # Sort key: descending priority, descending record count, ascending label.
        # Negating the numeric keys yields descending order while keeping the
        # label ascending, all within a single stable, deterministic sort.
        scored.sort(
            key=lambda c: (-c.priority_score, -len(c.member_ids), c.label)
        )
        return scored


__all__ = [
    "PrioritizationComponent",
    "compute_priority",
    "aggregate_factors",
    "W_SEV",
    "W_VOL",
    "W_NEG",
]
