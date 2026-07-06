"""Clustering_Component: groups semantically similar records (Req 8).

This module implements :class:`ClusteringComponent`, which partitions a set of
enriched records into mutually exclusive clusters using cosine similarity over
text embeddings with single-linkage agglomerative grouping at a configurable
threshold.

Design decisions (see design.md, "Clustering_Component"):

- **Input shape (``EnrichedRecord``):** clustering only needs a stable
  identifier and the text used for similarity. Rather than coupling to the full
  enriched-record type produced by later orchestration tasks, this component
  accepts anything satisfying the :class:`EnrichedRecord` protocol — an object
  exposing ``id: str`` and ``text: str``. ``FeedbackRecord`` exposes
  ``cleaned_text`` rather than ``text``; :func:`as_enriched_record` adapts such
  objects so the orchestrator can pass them through cheaply.

- **Injectable embeddings:** similarity is computed over embedding vectors
  produced by an ``EmbeddingFn``. The default is :func:`local_embedding`, a
  deterministic token-hashing bag-of-words embedding that requires no network,
  so clustering never aborts the batch when Gemini embeddings are unavailable
  (Req 8 fallback). The orchestrator can later inject a Gemini-backed embedding
  function with the same signature.

- **Determinism:** given a fixed embedding function the similarity matrix is
  deterministic, so the threshold co-membership guarantee (Req 8.3, 8.5) and
  the covering-partition guarantee (Req 8.1, 8.4) hold reproducibly.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Callable, Protocol, Sequence, runtime_checkable

from ..models.records import Cluster

# An embedding function maps a list of texts to a list of equal-length vectors.
EmbeddingFn = Callable[[Sequence[str]], list[list[float]]]

# Default dimensionality of the local hashing embedding.
_LOCAL_EMBEDDING_DIM = 256

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_LABEL_MAX_CHARS = 120


@runtime_checkable
class EnrichedRecord(Protocol):
    """Minimal input contract required for clustering.

    Any object exposing a stable ``id`` and the ``text`` used for similarity
    satisfies this protocol. The full enriched record produced by later
    orchestration tasks is a superset of this shape.
    """

    @property
    def id(self) -> str:  # pragma: no cover - structural protocol
        ...

    @property
    def text(self) -> str:  # pragma: no cover - structural protocol
        ...


class _AdaptedRecord:
    """Lightweight ``EnrichedRecord`` adapter exposing ``id`` and ``text``."""

    __slots__ = ("id", "text")

    def __init__(self, id: str, text: str) -> None:
        self.id = id
        self.text = text


def as_enriched_record(obj: object) -> EnrichedRecord:
    """Adapt a record-like object to the :class:`EnrichedRecord` shape.

    Accepts objects exposing ``id``/``text`` directly, or a ``FeedbackRecord``
    style object exposing ``id``/``cleaned_text``. Raises ``TypeError`` if no
    usable identifier/text pair can be found.
    """

    rid = getattr(obj, "id", None) or getattr(obj, "feedback_id", None)
    text = getattr(obj, "text", None)
    if text is None:
        text = getattr(obj, "cleaned_text", None)
    if rid is None or text is None:
        raise TypeError(
            "object cannot be adapted to EnrichedRecord: needs id/feedback_id "
            "and text/cleaned_text attributes"
        )
    return _AdaptedRecord(str(rid), str(text))


def _tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokenization used for embeddings and labels."""

    return _TOKEN_RE.findall(text.lower())


def local_embedding(
    texts: Sequence[str], dim: int = _LOCAL_EMBEDDING_DIM
) -> list[list[float]]:
    """Deterministic, network-free bag-of-words hashing embedding.

    Each token is hashed to a fixed bucket and contributes to that dimension's
    weight. Texts sharing tokens produce vectors with higher cosine similarity.
    The mapping is a pure function of the input text, so the embedding (and any
    similarity derived from it) is fully deterministic and reproducible.
    """

    vectors: list[list[float]] = []
    for text in texts:
        vec = [0.0] * dim
        for token in _tokenize(text):
            # Stable, process-independent hashing (avoids PYTHONHASHSEED noise).
            bucket = _stable_hash(token) % dim
            vec[bucket] += 1.0
        vectors.append(vec)
    return vectors


def _stable_hash(token: str) -> int:
    """A small deterministic string hash (FNV-1a, 32-bit)."""

    h = 0x811C9DC5
    for ch in token.encode("utf-8"):
        h ^= ch
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity between two equal-length vectors.

    Returns 1.0 when both vectors are zero-vectors (treated as identical) and
    0.0 when exactly one is a zero-vector, avoiding division by zero.
    """

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 and norm_b == 0.0:
        return 1.0
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


class _UnionFind:
    """Disjoint-set structure for single-linkage component grouping."""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))

    def find(self, x: int) -> int:
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        # Path compression.
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Keep the smaller index as root for stable, deterministic grouping.
            if ra < rb:
                self._parent[rb] = ra
            else:
                self._parent[ra] = rb


class ClusteringComponent:
    """Groups semantically similar records into mutually exclusive clusters.

    Parameters
    ----------
    embedding_fn:
        Function producing one embedding vector per input text. Defaults to the
        deterministic :func:`local_embedding` fallback. Inject a Gemini-backed
        embedding function with the same signature for production use.
    """

    def __init__(self, embedding_fn: EmbeddingFn | None = None) -> None:
        self._embedding_fn = embedding_fn or local_embedding

    def cluster(
        self, records: Sequence[EnrichedRecord], threshold: float
    ) -> list[Cluster]:
        """Partition ``records`` into clusters at the given similarity threshold.

        Guarantees:
        - Every input record appears in exactly one cluster; clusters are
          mutually exclusive and cover the input (Req 8.1, 8.4).
        - Any pair of records with cosine similarity >= ``threshold`` ends up in
          the same cluster (Req 8.3); a record below threshold against every
          other record becomes a singleton (Req 8.5).
        - Each cluster has a non-empty representative label <= 120 chars derived
          from member text (Req 8.2).
        - Empty input yields zero clusters but still returns clustering output
          (Req 8.6).
        """

        n = len(records)
        if n == 0:
            return []

        texts = [r.text for r in records]
        embeddings = self._embedding_fn(texts)
        if len(embeddings) != n:
            raise ValueError(
                "embedding_fn returned %d vectors for %d records"
                % (len(embeddings), n)
            )

        # Single-linkage grouping: union any pair meeting the threshold.
        uf = _UnionFind(n)
        for i in range(n):
            for j in range(i + 1, n):
                if cosine_similarity(embeddings[i], embeddings[j]) >= threshold:
                    uf.union(i, j)

        # Collect members per component, preserving input order within a group.
        components: dict[int, list[int]] = {}
        for idx in range(n):
            components.setdefault(uf.find(idx), []).append(idx)

        # Order clusters deterministically by the smallest member index so the
        # output is stable for a fixed input ordering.
        ordered_roots = sorted(components, key=lambda root: min(components[root]))

        clusters: list[Cluster] = []
        for cluster_index, root in enumerate(ordered_roots):
            member_indices = components[root]
            member_ids = [records[i].id for i in member_indices]
            member_texts = [records[i].text for i in member_indices]
            clusters.append(
                Cluster(
                    cluster_id=f"cluster-{cluster_index}",
                    label=_derive_label(member_texts, fallback=member_ids[0]),
                    member_ids=member_ids,
                )
            )
        return clusters


def _derive_label(member_texts: Sequence[str], fallback: str) -> str:
    """Build a non-empty representative label (<= 120 chars) from member text.

    Uses the most frequent significant tokens across members; falls back to a
    truncated member text, then to ``fallback`` (a member id) so the label is
    always non-empty even for degenerate input.
    """

    counter: Counter[str] = Counter()
    for text in member_texts:
        counter.update(_tokenize(text))

    if counter:
        # Most frequent tokens first; ties broken alphabetically for determinism.
        ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        label = " ".join(token for token, _ in ranked)
        label = _truncate(label, _LABEL_MAX_CHARS)
        if label:
            return label

    # No alphanumeric tokens: fall back to the first non-empty raw member text.
    for text in member_texts:
        stripped = text.strip()
        if stripped:
            return _truncate(stripped, _LABEL_MAX_CHARS)

    # Degenerate case (all members empty/whitespace): use the member id.
    return _truncate(fallback, _LABEL_MAX_CHARS) or "cluster"


def _truncate(text: str, limit: int) -> str:
    """Trim ``text`` to at most ``limit`` characters."""

    return text if len(text) <= limit else text[:limit]


__all__ = [
    "EnrichedRecord",
    "EmbeddingFn",
    "ClusteringComponent",
    "local_embedding",
    "cosine_similarity",
    "as_enriched_record",
]
