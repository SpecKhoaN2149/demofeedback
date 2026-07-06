"""Property-based and edge tests for the Clustering_Component (Req 8).

These tests validate the clustering correctness properties from the design:

- Property 21: Clustering is a covering partition (Req 8.1, 8.4)
- Property 22: Cluster labels are bounded and non-empty (Req 8.2)
- Property 23: Similarity governs cluster co-membership (Req 8.3, 8.5)
- Edge: empty input -> zero clusters, valid output (Req 8.6)

Determinism of similarity is achieved by injecting the controlled
``embedding_fn`` produced by :func:`tests.strategies.record_set_with_similarity`,
which yields one-hot vectors keyed by each record's group: same-group pairs have
cosine similarity 1.0 and different-group pairs have 0.0. This makes threshold
co-membership exact and reproducible (see the strategy module for details).
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from nlp_processing.aggregation.clustering import ClusteringComponent
from tests.strategies import record_set_with_similarity


def test_empty_input_produces_zero_clusters():
    """Edge (Req 8.6): empty input -> zero clusters, still a valid list output."""

    component = ClusteringComponent()
    clusters = component.cluster([], threshold=0.5)
    assert clusters == []


# Feature: nlp-feedback-processing, Property 21: Clustering is a covering
# partition - for any set of >=1 records, clusters are mutually exclusive and
# every input record is in exactly one cluster; total clustered count equals
# the input count.
# Validates: Requirements 8.1, 8.4
@settings(max_examples=200)
@given(
    data=record_set_with_similarity(min_size=1, max_size=8),
    threshold=st.floats(min_value=0.01, max_value=1.0),
)
def test_property_21_clustering_is_a_covering_partition(data, threshold):
    component = ClusteringComponent(embedding_fn=data.embedding_fn)
    clusters = component.cluster(data.records, threshold=threshold)

    input_ids = [r.id for r in data.records]
    clustered_ids = [mid for c in clusters for mid in c.member_ids]

    # Covering: total clustered count equals input count (Req 8.4).
    assert len(clustered_ids) == len(input_ids)
    # Mutually exclusive: no id appears in more than one cluster (Req 8.1).
    assert len(set(clustered_ids)) == len(clustered_ids)
    # Every input record appears exactly once (covering partition).
    assert set(clustered_ids) == set(input_ids)


# Feature: nlp-feedback-processing, Property 22: Cluster labels are bounded and
# non-empty - every produced cluster label is non-empty and at most 120 chars.
# Validates: Requirements 8.2
@settings(max_examples=200)
@given(
    data=record_set_with_similarity(min_size=1, max_size=8),
    threshold=st.floats(min_value=0.01, max_value=1.0),
)
def test_property_22_cluster_labels_are_bounded_and_non_empty(data, threshold):
    component = ClusteringComponent(embedding_fn=data.embedding_fn)
    clusters = component.cluster(data.records, threshold=threshold)

    for cluster in clusters:
        assert len(cluster.label) >= 1
        assert len(cluster.label) <= 120


# Feature: nlp-feedback-processing, Property 23: Similarity governs cluster
# co-membership - pairs with similarity >= threshold land in the same cluster;
# a record below threshold against all others is a singleton.
# Validates: Requirements 8.3, 8.5
@settings(max_examples=200)
@given(
    data=record_set_with_similarity(min_size=1, max_size=8),
    threshold=st.floats(min_value=0.01, max_value=1.0),
)
def test_property_23_similarity_governs_cluster_co_membership(data, threshold):
    component = ClusteringComponent(embedding_fn=data.embedding_fn)
    clusters = component.cluster(data.records, threshold=threshold)

    # Map each record id to the cluster index it landed in.
    id_to_cluster: dict[str, int] = {}
    for cluster_index, cluster in enumerate(clusters):
        for member_id in cluster.member_ids:
            id_to_cluster[member_id] = cluster_index

    records = data.records
    groups = data.groups

    # Req 8.3: any pair with similarity >= threshold (same group, cosine 1.0,
    # and threshold <= 1.0) must be in the same cluster. Cross-group pairs have
    # cosine 0.0 < threshold, so they are never forced together.
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            if groups[i] == groups[j]:
                assert id_to_cluster[records[i].id] == id_to_cluster[records[j].id]

    # Req 8.5: a record dissimilar to every other record (its group index is
    # unique) must be assigned to a singleton cluster.
    for idx, rec in enumerate(records):
        below_all_others = all(
            groups[other] != groups[idx]
            for other in range(len(records))
            if other != idx
        )
        if below_all_others:
            cluster = clusters[id_to_cluster[rec.id]]
            assert cluster.member_ids == [rec.id]
