"""Aggregation layer: Clustering_Component, Prioritization_Component, SimilarityClusterer, and output assembly."""

from .clustering import (
    ClusteringComponent,
    EmbeddingFn,
    EnrichedRecord,
    as_enriched_record,
    cosine_similarity,
    local_embedding,
)
from .prioritization import (
    PrioritizationComponent,
    aggregate_factors,
    compute_priority,
)
from .similarity_clusterer import SimilarityClusterer

__all__ = [
    "ClusteringComponent",
    "EmbeddingFn",
    "EnrichedRecord",
    "as_enriched_record",
    "cosine_similarity",
    "local_embedding",
    "PrioritizationComponent",
    "compute_priority",
    "aggregate_factors",
    "SimilarityClusterer",
]
