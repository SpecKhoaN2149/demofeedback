"""Shared Hypothesis strategies for the NLP Feedback Processing test suite.

Strategy generators are added next to the components they exercise, for example:

- ``raw_feedback()``                 (task 2.2)
- ``enrichment_response()``          (task 3.3)
- ``insight_record()``               (task 3.3)
- ``record_set_with_similarity()``   (task 5.2)
- ``cluster()``                      (task 6.2)

Centralizing them here lets property tests across modules reuse smart,
input-space-constrained generators.
"""

from __future__ import annotations

from typing import get_args

from hypothesis import strategies as st

from nlp_processing.ingestion import MAX_TEXT_LENGTH
from nlp_processing.models import RawFeedback, SourceChannel

# ---------------------------------------------------------------------------
# Ingestion strategies (task 2.2)
# ---------------------------------------------------------------------------
#
# Generate RawFeedback items with controllable surrounding whitespace and text
# length near the 10,000-character boundary, plus valid and invalid source
# channels and arbitrary JSON-like metadata.

# The four whitespace characters the Ingestion_Component trims (Req 1.2).
TRIM_WHITESPACE = " \t\r\n"

# Valid channels, taken straight from the SourceChannel literal (Req 1.4).
VALID_CHANNELS: tuple[str, ...] = tuple(get_args(SourceChannel))


def valid_channels() -> st.SearchStrategy[str]:
    """A source_channel value that is in the allowed set."""
    return st.sampled_from(VALID_CHANNELS)


def invalid_channels() -> st.SearchStrategy[str]:
    """A source_channel value that is NOT in the allowed set."""
    return st.text(min_size=0, max_size=20).filter(lambda s: s not in VALID_CHANNELS)


def channels() -> st.SearchStrategy[str]:
    """A mix of valid and invalid channels."""
    return st.one_of(valid_channels(), invalid_channels())


def _trim_whitespace_runs(max_size: int = 6) -> st.SearchStrategy[str]:
    """A (possibly empty) run built only of the trimmed whitespace chars."""
    return st.text(alphabet=TRIM_WHITESPACE, min_size=0, max_size=max_size)


@st.composite
def core_text(draw: st.DrawFn, min_size: int = 1, max_size: int = 80) -> str:
    """Non-empty text whose first and last characters are NOT trim whitespace.

    This is the "interior content" that must survive trimming unchanged. The
    first and last characters are drawn from non-trim characters so the core is
    well defined; interior characters (including trim whitespace) are arbitrary.

    Surrogate codepoints (U+D800–U+DFFF) are excluded because Pydantic v2
    rejects lone surrogates as invalid unicode in strict string fields.
    """
    non_trim = st.characters(
        blacklist_characters=TRIM_WHITESPACE,
        blacklist_categories=("Cs",),
    )
    # Interior text also excludes surrogates for the same reason.
    interior_chars = st.characters(blacklist_categories=("Cs",))
    first = draw(non_trim)
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    if n <= 1:
        return first
    middle = draw(st.text(alphabet=interior_chars, min_size=n - 2, max_size=n - 2))
    last = draw(non_trim)
    return first + middle + last


@st.composite
def text_with_surrounding_whitespace(draw: st.DrawFn) -> tuple[str, str]:
    """Return ``(raw_text, expected_core)`` for whitespace-trimming tests.

    ``raw_text`` is ``expected_core`` wrapped in arbitrary leading/trailing
    runs of the four trimmed whitespace characters; ``expected_core`` is what a
    correct trim must yield.
    """
    core = draw(core_text())
    lead = draw(_trim_whitespace_runs())
    trail = draw(_trim_whitespace_runs())
    return lead + core + trail, core


def blank_text() -> st.SearchStrategy[str]:
    """Text that is empty or made up solely of trimmed whitespace (Req 1.3)."""
    return st.text(alphabet=TRIM_WHITESPACE, min_size=0, max_size=8)


def metadata() -> st.SearchStrategy[dict]:
    """Arbitrary JSON-like metadata dictionaries."""
    scalars = st.one_of(
        st.none(),
        st.booleans(),
        st.integers(),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(max_size=20),
    )
    values = st.recursive(
        scalars,
        lambda children: st.one_of(
            st.lists(children, max_size=3),
            st.dictionaries(st.text(max_size=8), children, max_size=3),
        ),
        max_leaves=5,
    )
    return st.dictionaries(st.text(max_size=8), values, max_size=4)


def boundary_length_text() -> st.SearchStrategy[str]:
    """Core text whose length sits near the 10,000-character boundary (Req 1.7).

    Generates lengths in ``{1, MAX-1, MAX, MAX+1, MAX+2}`` so trimming and the
    length check are exercised on both sides of the limit.
    """
    lengths = st.sampled_from(
        [1, MAX_TEXT_LENGTH - 1, MAX_TEXT_LENGTH, MAX_TEXT_LENGTH + 1, MAX_TEXT_LENGTH + 2]
    )
    return lengths.map(lambda n: "a" * n)


@st.composite
def raw_feedback(
    draw: st.DrawFn,
    *,
    channel_strategy: st.SearchStrategy[str] | None = None,
    text_strategy: st.SearchStrategy[str] | None = None,
) -> RawFeedback:
    """Generate a :class:`RawFeedback` item.

    By default the channel mixes valid and invalid values and the text is a
    core wrapped in arbitrary trimmed-whitespace runs. Callers can override
    ``channel_strategy`` or ``text_strategy`` to focus the input space (e.g.
    only valid channels, only blank text, or boundary-length text). Metadata is
    arbitrary JSON-like data.
    """
    channel = draw(channel_strategy if channel_strategy is not None else channels())
    if text_strategy is not None:
        text = draw(text_strategy)
    else:
        lead = draw(_trim_whitespace_runs())
        trail = draw(_trim_whitespace_runs())
        core = draw(core_text())
        text = lead + core + trail
    meta = draw(metadata())
    return RawFeedback(source_channel=channel, text=text, metadata=meta)


def valid_raw_feedback() -> st.SearchStrategy[RawFeedback]:
    """A RawFeedback guaranteed to pass ingestion validation.

    Valid channel, non-blank core text whose trimmed length is within the limit
    (1..MAX_TEXT_LENGTH), wrapped in arbitrary trimmed whitespace.
    """
    return raw_feedback(
        channel_strategy=valid_channels(),
        text_strategy=text_with_surrounding_whitespace().map(lambda pair: pair[0]),
    )


# ---------------------------------------------------------------------------
# Prioritization_Component strategies (task 6.2)
# ---------------------------------------------------------------------------
#
# The Prioritization_Component scores a ``Cluster`` from the enriched insights
# of its member records (see ``nlp_processing/aggregation/prioritization.py``).
# A ``Cluster`` only carries ``member_ids``; the severity scores and sentiment
# values that drive the priority score live on the per-record
# ``InsightRecord``s, looked up via an ``insights`` mapping
# (``feedback_id -> InsightRecord``).
#
# ``cluster()`` therefore generates a ``Cluster`` *together with* a matching
# insights mapping so that the three scoring factors are directly
# controllable:
#
#   * ``severity_total``  = sum of member ``severity_score`` (each 1..5)
#   * ``record_count``    = ``len(member_ids)``
#   * ``negative_count``  = number of members with ``sentiment == "negative"``

from hypothesis import strategies as st

from nlp_processing.models.records import (
    Cluster,
    InsightRecord,
    SeverityFactor,
    ThemeAssignment,
)

# Sentiment values that are *not* negative, used when we want to control the
# negative count precisely.
_NON_NEGATIVE_SENTIMENTS = ("positive", "neutral")


@st.composite
def _insight_for_member(
    draw,
    feedback_id: str,
    cluster_id: str,
    *,
    sentiment: str | None = None,
    severity_score: int | None = None,
) -> InsightRecord:
    """Build a minimal valid ``InsightRecord`` for a cluster member.

    Severity score and sentiment may be pinned by the caller so the aggregate
    scoring factors are controllable; otherwise they are drawn freely.
    """
    if severity_score is None:
        severity_score = draw(st.integers(min_value=1, max_value=5))
    if sentiment is None:
        sentiment = draw(st.sampled_from(("positive", "neutral", "negative")))
    return InsightRecord(
        feedback_id=feedback_id,
        themes=[ThemeAssignment(theme="other", confidence=0.5)],
        sentiment=sentiment,
        sentiment_confidence=0.5,
        severity_score=severity_score,
        severity_factors=[SeverityFactor(description="factor")],
        cluster_id=cluster_id,
        model_name="test-model",
    )


@st.composite
def cluster(
    draw,
    *,
    min_members: int = 0,
    max_members: int = 8,
    label: str | None = None,
    cluster_id: str | None = None,
) -> tuple[Cluster, dict[str, InsightRecord]]:
    """Generate a ``Cluster`` plus its matching ``insights`` mapping.

    Returns ``(cluster, insights)`` where ``insights`` is a
    ``feedback_id -> InsightRecord`` mapping covering every member id. The
    generated members give directly controllable aggregate factors:
    ``severity_total`` (sum of 1..5 severities), ``record_count``
    (``len(member_ids)``), and ``negative_count`` (members with negative
    sentiment).

    The returned ``Cluster`` always has ``priority_score`` at its default of
    ``0.0`` so callers can assert that the component records a fresh score.
    """
    if cluster_id is None:
        cluster_id = draw(
            st.text(
                alphabet=st.characters(min_codepoint=97, max_codepoint=122),
                min_size=1,
                max_size=8,
            ).map(lambda s: f"cl-{s}")
        )
    if label is None:
        label = draw(
            st.text(
                alphabet=st.characters(min_codepoint=97, max_codepoint=122),
                min_size=1,
                max_size=20,
            )
        )

    n_members = draw(st.integers(min_value=min_members, max_value=max_members))
    insights: dict[str, InsightRecord] = {}
    member_ids: list[str] = []
    for i in range(n_members):
        feedback_id = f"{cluster_id}-m{i}"
        member_ids.append(feedback_id)
        insights[feedback_id] = draw(_insight_for_member(feedback_id, cluster_id))

    cluster_obj = Cluster(
        cluster_id=cluster_id,
        label=label,
        member_ids=member_ids,
    )
    return cluster_obj, insights


@st.composite
def cluster_with_factors(
    draw,
    *,
    severity_total: int,
    record_count: int,
    negative_count: int,
    label: str | None = None,
    cluster_id: str | None = None,
) -> tuple[Cluster, dict[str, InsightRecord]]:
    """Build a ``(cluster, insights)`` pair with *exact* aggregate factors.

    Useful for monotonicity checks where one factor must be varied while the
    others are held equal. Constraints:

    * ``record_count >= 0``
    * ``0 <= negative_count <= record_count``
    * ``record_count <= severity_total <= 5 * record_count`` (each member has
      a severity score in 1..5), or ``severity_total == 0`` when
      ``record_count == 0``.
    """
    assert record_count >= 0
    assert 0 <= negative_count <= record_count
    if record_count == 0:
        assert severity_total == 0
    else:
        assert record_count <= severity_total <= 5 * record_count

    if cluster_id is None:
        cluster_id = draw(
            st.text(
                alphabet=st.characters(min_codepoint=97, max_codepoint=122),
                min_size=1,
                max_size=8,
            ).map(lambda s: f"cf-{s}")
        )
    if label is None:
        label = draw(
            st.text(
                alphabet=st.characters(min_codepoint=97, max_codepoint=122),
                min_size=1,
                max_size=20,
            )
        )

    # Distribute the severity_total across record_count members, each in 1..5.
    severities = _distribute_severity(severity_total, record_count)

    insights: dict[str, InsightRecord] = {}
    member_ids: list[str] = []
    for i in range(record_count):
        feedback_id = f"{cluster_id}-m{i}"
        member_ids.append(feedback_id)
        sentiment = "negative" if i < negative_count else "neutral"
        insights[feedback_id] = draw(
            _insight_for_member(
                feedback_id,
                cluster_id,
                sentiment=sentiment,
                severity_score=severities[i],
            )
        )

    cluster_obj = Cluster(
        cluster_id=cluster_id,
        label=label,
        member_ids=member_ids,
    )
    return cluster_obj, insights


def _distribute_severity(severity_total: int, record_count: int) -> list[int]:
    """Split ``severity_total`` into ``record_count`` integers each in 1..5."""
    if record_count == 0:
        return []
    severities = [1] * record_count
    remaining = severity_total - record_count
    idx = 0
    while remaining > 0 and idx < record_count:
        add = min(4, remaining)  # each member can take up to +4 (1 -> 5)
        severities[idx] += add
        remaining -= add
        idx += 1
    return severities


# ---------------------------------------------------------------------------
# Clustering_Component strategies (task 5.2)
# ---------------------------------------------------------------------------
#
# ``record_set_with_similarity()`` generates a set of records together with a
# *controlled* embedding function so that pairwise cosine similarity — and
# therefore threshold co-membership — is fully deterministic.
#
# Approach (documented per task 5.2):
#   - Each record is assigned to a generated "group" index.
#   - The companion ``embedding_fn`` maps each record's (unique) text to a
#     one-hot vector indexed by that record's group.
#   - Two records in the SAME group share an identical one-hot vector, giving
#     cosine similarity 1.0.
#   - Two records in DIFFERENT groups have orthogonal one-hot vectors, giving
#     cosine similarity 0.0.
#
# Consequently, for any threshold in (0.0, 1.0]:
#   - same-group pairs are always >= threshold (co-members), and
#   - different-group pairs are always < threshold (not directly linked).
# Because cross-group similarity is always 0.0, single-linkage grouping cannot
# transitively merge distinct groups, so the resulting clusters correspond
# exactly to the generated groups. This makes co-membership deterministic and
# lets a group of size 1 act as a guaranteed singleton.

from dataclasses import dataclass
from typing import Callable, Sequence

from hypothesis import strategies as st


@dataclass(frozen=True)
class SimRecord:
    """Minimal ``EnrichedRecord``-shaped record (exposes ``id`` and ``text``)."""

    id: str
    text: str


@dataclass(frozen=True)
class RecordSetWithSimilarity:
    """A generated record set plus a deterministic embedding function.

    Attributes
    ----------
    records:
        The generated records (each exposing ``id`` and ``text``).
    groups:
        Parallel list giving the group index of each record. Records sharing a
        group index are mutually similar (cosine 1.0); records in different
        groups are dissimilar (cosine 0.0).
    embedding_fn:
        Embedding function to inject into ``ClusteringComponent`` so similarity
        is governed by ``groups``.
    num_groups:
        Number of distinct group slots (the embedding dimensionality).
    """

    records: list[SimRecord]
    groups: list[int]
    embedding_fn: Callable[[Sequence[str]], list[list[float]]]
    num_groups: int


@st.composite
def record_set_with_similarity(draw, min_size: int = 1, max_size: int = 8):
    """Generate a record set with a controllable pairwise similarity matrix.

    The returned :class:`RecordSetWithSimilarity` carries an ``embedding_fn``
    that yields one-hot vectors keyed by each record's group, so co-membership
    at any threshold in ``(0.0, 1.0]`` is deterministic (see module notes).
    """

    n = draw(st.integers(min_value=min_size, max_value=max_size))
    num_groups = draw(st.integers(min_value=1, max_value=n))
    groups = draw(
        st.lists(
            st.integers(min_value=0, max_value=num_groups - 1),
            min_size=n,
            max_size=n,
        )
    )

    # Unique ids and unique texts so the embedding lookup is unambiguous.
    records = [SimRecord(id=f"r{i}", text=f"r{i}-text") for i in range(n)]
    text_to_group = {rec.text: groups[i] for i, rec in enumerate(records)}

    def embedding_fn(
        texts: Sequence[str],
        _t2g: dict[str, int] = text_to_group,
        _dim: int = num_groups,
    ) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vec = [0.0] * _dim
            vec[_t2g[text]] = 1.0
            vectors.append(vec)
        return vectors

    return RecordSetWithSimilarity(
        records=records,
        groups=groups,
        embedding_fn=embedding_fn,
        num_groups=num_groups,
    )

# ---------------------------------------------------------------------------
# Serialization strategies (task 3.3): Response_Parser / Response_Serializer.
#
# These generators feed the serialization property tests (Properties 8-11).
# They are intentionally "smart": valid generators stay inside the schema's
# input space, and invalid generators each inject exactly one guaranteed
# violation so rejection tests are deterministic.
# ---------------------------------------------------------------------------

import json as _json

from hypothesis import strategies as st

from nlp_processing.models import InsightRecord, SeverityFactor, ThemeAssignment

# Configured value sets mirrored from nlp_processing.models.types.
_THEME_LABELS = [
    "billing",
    "network_speed",
    "outage",
    "support_experience",
    "device_hardware",
    "pricing",
    "other",
]
_SENTIMENTS = ["positive", "neutral", "negative"]

# Printable-ASCII text keeps JSON round-trips unambiguous (no surrogate or
# control-character edge cases) while still exercising punctuation/whitespace.
_PRINTABLE = st.characters(min_codepoint=32, max_codepoint=126)

# Confidence values live in the inclusive unit interval; never NaN/inf so that
# canonical-JSON idempotence (Property 11) and float round-trips (Property 10)
# hold.
_unit_float = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Free text in the schema's bounds (1..500 for severity factors).
_factor_text = st.text(alphabet=_PRINTABLE, min_size=1, max_size=500)
# General-purpose short text (theme labels in raw responses, model names, etc.).
_short_text = st.text(alphabet=_PRINTABLE, min_size=1, max_size=40)
# Identifiers are kept non-empty so serialization errors are keyed by a real id.
_id_text = st.text(alphabet=_PRINTABLE, min_size=1, max_size=24)


# --- Gemini enrichment-response strategies (raw, untrusted JSON) -----------

@st.composite
def valid_enrichment_payload(draw):
    """A dict that conforms to the strict ``EnrichmentResponse`` schema."""
    themes = draw(
        st.lists(
            st.fixed_dictionaries({"theme": _short_text, "confidence": _unit_float}),
            min_size=1,
            max_size=5,
        )
    )
    return {
        "themes": themes,
        "sentiment": draw(st.sampled_from(_SENTIMENTS)),
        "sentiment_confidence": draw(_unit_float),
        "severity_score": draw(st.integers(min_value=1, max_value=5)),
        "severity_factors": draw(st.lists(_factor_text, min_size=1, max_size=4)),
    }


def valid_enrichment_json():
    """A JSON string the ``ResponseParser`` accepts."""
    return valid_enrichment_payload().map(_json.dumps)


@st.composite
def invalid_enrichment_json(draw):
    """A JSON string the strict ``ResponseParser`` must reject.

    Each draw injects exactly one violation drawn from the parser-rejection
    categories: bad syntax, non-object root, dropped required field (including
    omitted sentiment/severity), empty required arrays, out-of-range numbers,
    wrong types, an out-of-set sentiment, an unexpected property, or an
    out-of-bounds severity factor. (Unknown *theme* labels are intentionally
    excluded: the parser accepts any theme string; discarding out-of-set labels
    is the Classifier's job, not the parser's.)
    """
    kind = draw(
        st.sampled_from(
            [
                "bad_syntax",
                "not_object",
                "missing_field",
                "empty_themes",
                "empty_factors",
                "out_of_range",
                "wrong_type",
                "bad_sentiment",
                "extra_property",
                "factor_too_long",
                "factor_empty",
            ]
        )
    )

    if kind == "bad_syntax":
        # Drop the closing brace of an otherwise-valid object -> invalid JSON.
        return _json.dumps(draw(valid_enrichment_payload()))[:-1]

    if kind == "not_object":
        # Valid JSON, but the root is not an object -> schema validation fails.
        non_object = draw(
            st.one_of(
                st.integers(),
                st.floats(allow_nan=False, allow_infinity=False),
                st.text(alphabet=_PRINTABLE, max_size=20),
                st.booleans(),
                st.none(),
                st.lists(st.integers(), max_size=4),
            )
        )
        return _json.dumps(non_object)

    payload = draw(valid_enrichment_payload())

    if kind == "missing_field":
        field = draw(
            st.sampled_from(
                [
                    "themes",
                    "sentiment",
                    "sentiment_confidence",
                    "severity_score",
                    "severity_factors",
                ]
            )
        )
        payload.pop(field, None)
    elif kind == "empty_themes":
        payload["themes"] = []
    elif kind == "empty_factors":
        payload["severity_factors"] = []
    elif kind == "out_of_range":
        target = draw(st.sampled_from(["sentiment_confidence", "severity_score", "theme_conf"]))
        if target == "sentiment_confidence":
            payload["sentiment_confidence"] = draw(
                st.one_of(
                    st.floats(min_value=1.0001, max_value=10.0, allow_nan=False, allow_infinity=False),
                    st.floats(min_value=-10.0, max_value=-0.0001, allow_nan=False, allow_infinity=False),
                )
            )
        elif target == "severity_score":
            payload["severity_score"] = draw(st.sampled_from([0, 6, -1, 100]))
        else:
            payload["themes"][0]["confidence"] = draw(st.sampled_from([1.5, -0.5, 2.0]))
    elif kind == "wrong_type":
        target = draw(st.sampled_from(["severity_str", "severity_float", "conf_str", "themes_str"]))
        if target == "severity_str":
            payload["severity_score"] = "three"
        elif target == "severity_float":
            payload["severity_score"] = 3.5  # strict int rejects non-integers
        elif target == "conf_str":
            payload["sentiment_confidence"] = "high"
        else:
            payload["themes"] = "billing"
    elif kind == "bad_sentiment":
        payload["sentiment"] = draw(
            st.sampled_from(["angry", "mixed", "happy", "POSITIVE", ""])
        )
    elif kind == "extra_property":
        payload["unexpected_field"] = draw(_short_text)
    elif kind == "factor_too_long":
        payload["severity_factors"] = ["x" * draw(st.integers(min_value=501, max_value=600))]
    elif kind == "factor_empty":
        payload["severity_factors"] = [""]

    return _json.dumps(payload)


def enrichment_response():
    """Tagged enrichment responses: ``(raw_json, parser_valid)`` pairs.

    Emits both valid and malformed Gemini JSON so a single strategy can drive
    parser tests that care about either outcome. ``parser_valid`` states
    whether the strict ``ResponseParser`` should accept ``raw_json``.
    """
    valid = valid_enrichment_json().map(lambda s: (s, True))
    invalid = invalid_enrichment_json().map(lambda s: (s, False))
    return st.one_of(valid, invalid)


# --- InsightRecord strategies ----------------------------------------------

@st.composite
def theme_assignment(draw):
    """A valid ``ThemeAssignment`` (configured theme + unit confidence)."""
    return ThemeAssignment(
        theme=draw(st.sampled_from(_THEME_LABELS)),
        confidence=draw(_unit_float),
    )


@st.composite
def severity_factor(draw):
    """A valid ``SeverityFactor`` (1..500 character description)."""
    return SeverityFactor(description=draw(_factor_text))


@st.composite
def valid_insight_record(draw):
    """A schema-valid, complete ``InsightRecord`` for round-trip tests."""
    return InsightRecord(
        feedback_id=draw(_id_text),
        themes=draw(st.lists(theme_assignment(), min_size=1, max_size=4)),
        sentiment=draw(st.sampled_from(_SENTIMENTS)),
        sentiment_confidence=draw(_unit_float),
        severity_score=draw(st.integers(min_value=1, max_value=5)),
        severity_factors=draw(st.lists(severity_factor(), min_size=1, max_size=3)),
        cluster_id=draw(_id_text),
        review_flag=draw(st.booleans()),
        model_name=draw(_short_text),
        notes=draw(st.lists(_short_text, max_size=3)),
    )


def valid_insight_json():
    """JSON-compatible dict form of a valid ``InsightRecord``."""
    return valid_insight_record().map(lambda r: r.model_dump(mode="json"))


@st.composite
def invalid_insight_record(draw):
    """An invalid/incomplete ``InsightRecord`` the serializer must reject.

    Built with ``model_construct`` to bypass pydantic construction-time
    validation, then exactly one field is corrupted so re-validation against
    the published schema fails. ``feedback_id`` is left valid so the resulting
    serialization error is keyed by a real id.
    """
    base = draw(valid_insight_record())
    data = dict(
        feedback_id=base.feedback_id,
        themes=base.themes,
        sentiment=base.sentiment,
        sentiment_confidence=base.sentiment_confidence,
        severity_score=base.severity_score,
        severity_factors=base.severity_factors,
        cluster_id=base.cluster_id,
        review_flag=base.review_flag,
        model_name=base.model_name,
        notes=base.notes,
    )

    kind = draw(
        st.sampled_from(
            [
                "bad_severity",
                "bad_sentiment_confidence",
                "bad_sentiment",
                "empty_themes",
                "empty_factors",
                "bad_theme_confidence",
                "factor_too_long",
            ]
        )
    )

    if kind == "bad_severity":
        data["severity_score"] = draw(st.sampled_from([0, 6, -1, 99]))
    elif kind == "bad_sentiment_confidence":
        data["sentiment_confidence"] = draw(st.sampled_from([-0.5, 1.5, 2.0]))
    elif kind == "bad_sentiment":
        data["sentiment"] = draw(st.sampled_from(["angry", "mixed", "happy"]))
    elif kind == "empty_themes":
        data["themes"] = []
    elif kind == "empty_factors":
        data["severity_factors"] = []
    elif kind == "bad_theme_confidence":
        bad = ThemeAssignment.model_construct(
            theme=draw(st.sampled_from(_THEME_LABELS)),
            confidence=draw(st.sampled_from([1.5, -0.5, 2.0])),
        )
        data["themes"] = [bad]
    elif kind == "factor_too_long":
        long_desc = "x" * draw(st.integers(min_value=501, max_value=600))
        data["severity_factors"] = [SeverityFactor.model_construct(description=long_desc)]

    return InsightRecord.model_construct(**data)


def expected_schema_json():
    """Valid expected-schema JSON values (dicts) for normalization tests.

    Combines raw enrichment-response payloads and serialized ``InsightRecord``
    values; both are valid JSON values conforming to schemas this layer owns.
    """
    return st.one_of(valid_enrichment_payload(), valid_insight_json())


# ---------------------------------------------------------------------------
# Persistence strategies (tasks 2.2, 2.3)
# ---------------------------------------------------------------------------
#
# ``valid_batch_output()`` generates complete, valid ``BatchOutput`` objects
# suitable for persistence round-trip and metadata-assignment property tests.

from datetime import datetime, timezone

from nlp_processing.models.enhancements import CachedEnrichment
from nlp_processing.models.records import (
    BatchOutput,
    BatchSummary,
    Cluster,
    FailureEntry,
    SystemErrorEntry,
)
from nlp_processing.models.types import DEFAULT_THEME_SET, FailureStage

_FAILURE_STAGES: list[FailureStage] = [
    "ingestion",
    "classification",
    "sentiment",
    "severity",
    "parsing",
    "serialization",
    "clustering",
]


# ---------------------------------------------------------------------------
# CacheLayer strategies (task 4.3)
# ---------------------------------------------------------------------------


@st.composite
def valid_cached_enrichment(draw) -> CachedEnrichment:
    """Generate a valid ``CachedEnrichment`` for cache round-trip property tests.

    Produces a CachedEnrichment with themes drawn from the default theme set,
    a valid sentiment, confidence in [0, 1], severity in [1, 5], and at least
    one severity factor.
    """
    themes = draw(
        st.lists(
            st.builds(
                ThemeAssignment,
                theme=st.sampled_from(sorted(DEFAULT_THEME_SET)),
                confidence=st.floats(0.0, 1.0, allow_nan=False, allow_infinity=False),
            ),
            min_size=1,
            max_size=3,
        )
    )
    sentiment = draw(st.sampled_from(["positive", "neutral", "negative"]))
    sentiment_confidence = draw(
        st.floats(0.0, 1.0, allow_nan=False, allow_infinity=False)
    )
    severity_score = draw(st.integers(1, 5))
    severity_factors = draw(
        st.lists(
            st.builds(
                SeverityFactor,
                description=st.text(min_size=1, max_size=50),
            ),
            min_size=1,
            max_size=3,
        )
    )
    cached_at = datetime.now(timezone.utc).isoformat()
    return CachedEnrichment(
        themes=themes,
        sentiment=sentiment,
        sentiment_confidence=sentiment_confidence,
        severity_score=severity_score,
        severity_factors=severity_factors,
        cached_at=cached_at,
    )


@st.composite
def valid_cluster(draw) -> Cluster:
    """A valid ``Cluster`` with a non-empty label and member_ids."""
    cluster_id = draw(_id_text)
    label = draw(st.text(alphabet=_PRINTABLE, min_size=1, max_size=40))
    n_members = draw(st.integers(min_value=0, max_value=4))
    member_ids = [draw(_id_text) for _ in range(n_members)]
    priority_score = draw(
        st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)
    )
    return Cluster(
        cluster_id=cluster_id,
        label=label,
        member_ids=member_ids,
        priority_score=priority_score,
    )


@st.composite
def valid_failure_entry(draw) -> FailureEntry:
    """A valid ``FailureEntry``."""
    return FailureEntry(
        feedback_id=draw(_id_text),
        stage=draw(st.sampled_from(_FAILURE_STAGES)),
        reason=draw(st.text(alphabet=_PRINTABLE, min_size=1, max_size=80)),
    )


@st.composite
def valid_system_error(draw) -> SystemErrorEntry:
    """A valid ``SystemErrorEntry``."""
    return SystemErrorEntry(
        feedback_id=draw(_id_text),
        reason=draw(st.text(alphabet=_PRINTABLE, min_size=1, max_size=80)),
    )


@st.composite
def valid_batch_output(draw) -> BatchOutput:
    """Generate a complete, valid ``BatchOutput`` for persistence tests.

    Produces a BatchOutput with a realistic mix of insights, clusters,
    failures, system errors, and a consistent BatchSummary.
    """
    n_insights = draw(st.integers(min_value=0, max_value=5))
    insights = [draw(valid_insight_record()) for _ in range(n_insights)]

    n_clusters = draw(st.integers(min_value=0, max_value=3))
    clusters = [draw(valid_cluster()) for _ in range(n_clusters)]

    n_failures = draw(st.integers(min_value=0, max_value=3))
    failures = [draw(valid_failure_entry()) for _ in range(n_failures)]

    n_sys_errors = draw(st.integers(min_value=0, max_value=2))
    system_errors = [draw(valid_system_error()) for _ in range(n_sys_errors)]

    submitted = n_insights + n_failures
    summary = BatchSummary(
        submitted=submitted,
        successful=n_insights,
        failures=n_failures,
    )

    model_name = draw(_short_text)

    return BatchOutput(
        insights=insights,
        clusters=clusters,
        failures=failures,
        system_errors=system_errors,
        summary=summary,
        model_name=model_name,
    )


# ---------------------------------------------------------------------------
# BatchOutput strategies (task 2.2)
# ---------------------------------------------------------------------------
#
# Generate complete, valid BatchOutput objects for persistence round-trip
# property testing.

from nlp_processing.models.records import (
    BatchOutput,
    BatchSummary,
    FailureEntry,
    SystemErrorEntry,
)
from nlp_processing.models.types import FailureStage

_FAILURE_STAGES: list[str] = list(get_args(FailureStage))


@st.composite
def valid_failure_entry(draw) -> FailureEntry:
    """A valid FailureEntry with a random stage and reason."""
    return FailureEntry(
        feedback_id=draw(_id_text),
        stage=draw(st.sampled_from(_FAILURE_STAGES)),
        reason=draw(st.text(alphabet=_PRINTABLE, min_size=1, max_size=80)),
    )


@st.composite
def valid_system_error_entry(draw) -> SystemErrorEntry:
    """A valid SystemErrorEntry."""
    return SystemErrorEntry(
        feedback_id=draw(_id_text),
        reason=draw(st.text(alphabet=_PRINTABLE, min_size=1, max_size=80)),
    )


@st.composite
def valid_cluster(draw) -> Cluster:
    """A valid Cluster with member IDs and a priority score."""
    cluster_id = draw(_id_text)
    label = draw(st.text(alphabet=_PRINTABLE, min_size=1, max_size=120))
    member_ids = draw(st.lists(_id_text, min_size=0, max_size=5))
    priority_score = draw(
        st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)
    )
    return Cluster(
        cluster_id=cluster_id,
        label=label,
        member_ids=member_ids,
        priority_score=priority_score,
    )


@st.composite
def valid_batch_summary(draw) -> BatchSummary:
    """A valid BatchSummary where successful + failures == submitted."""
    successful = draw(st.integers(min_value=0, max_value=50))
    failures = draw(st.integers(min_value=0, max_value=50))
    submitted = successful + failures
    return BatchSummary(
        submitted=submitted,
        successful=successful,
        failures=failures,
    )


@st.composite
def valid_batch_output(draw) -> BatchOutput:
    """Generate a complete, valid BatchOutput for persistence round-trip tests.

    All nested objects (InsightRecords, Clusters, FailureEntries,
    SystemErrorEntries, BatchSummary) are valid and satisfy Pydantic
    constraints.
    """
    insights = draw(st.lists(valid_insight_record(), min_size=0, max_size=5))
    clusters = draw(st.lists(valid_cluster(), min_size=0, max_size=3))
    failures = draw(st.lists(valid_failure_entry(), min_size=0, max_size=3))
    system_errors = draw(st.lists(valid_system_error_entry(), min_size=0, max_size=2))
    summary = draw(valid_batch_summary())
    model_name = draw(_short_text)
    classification_accuracy = draw(
        st.one_of(
            st.none(),
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        )
    )
    return BatchOutput(
        insights=insights,
        clusters=clusters,
        failures=failures,
        system_errors=system_errors,
        summary=summary,
        model_name=model_name,
        classification_accuracy=classification_accuracy,
    )


# ---------------------------------------------------------------------------
# CacheLayer strategies (task 4.6)
# ---------------------------------------------------------------------------
#
# ``valid_cached_enrichment()`` generates valid ``CachedEnrichment`` objects
# suitable for cache property tests.

from datetime import datetime, timezone

from nlp_processing.models.enhancements import CachedEnrichment


@st.composite
def valid_cached_enrichment(draw) -> CachedEnrichment:
    """Generate a valid ``CachedEnrichment`` for cache property tests.

    All fields satisfy Pydantic constraints: confidence in [0.0, 1.0],
    severity_score in [1, 5], and a valid ISO 8601 UTC cached_at timestamp.
    """
    themes = draw(st.lists(theme_assignment(), min_size=1, max_size=4))
    sentiment = draw(st.sampled_from(_SENTIMENTS))
    sentiment_confidence = draw(_unit_float)
    severity_score = draw(st.integers(min_value=1, max_value=5))
    severity_factors = draw(st.lists(severity_factor(), min_size=1, max_size=3))
    cached_at = datetime.now(timezone.utc).isoformat()

    return CachedEnrichment(
        themes=themes,
        sentiment=sentiment,
        sentiment_confidence=sentiment_confidence,
        severity_score=severity_score,
        severity_factors=severity_factors,
        cached_at=cached_at,
    )


# ---------------------------------------------------------------------------
# Trend Detection strategies (task 9.4)
# ---------------------------------------------------------------------------
#
# ``insight_records_with_themes()`` generates sets of InsightRecords with
# controlled theme distributions for theme frequency property tests.

from nlp_processing.models.types import DEFAULT_THEME_SET


_THEME_LABELS_LIST = sorted(DEFAULT_THEME_SET)


@st.composite
def insight_records_with_themes(
    draw,
    *,
    min_records: int = 1,
    max_records: int = 20,
) -> list[InsightRecord]:
    """Generate a list of InsightRecords with controlled theme assignments.

    Each record gets 1..3 distinct themes drawn from the configured theme set.
    This strategy is designed for testing theme frequency computation where the
    relative frequency of a theme = count of records with that theme / total
    records (Req 3.2).

    Each record contributes one count per distinct theme assigned to it.
    """
    n = draw(st.integers(min_value=min_records, max_value=max_records))
    records: list[InsightRecord] = []
    for i in range(n):
        # Draw 1..3 distinct themes for this record
        num_themes = draw(st.integers(min_value=1, max_value=min(3, len(_THEME_LABELS_LIST))))
        themes = draw(
            st.lists(
                st.sampled_from(_THEME_LABELS_LIST),
                min_size=num_themes,
                max_size=num_themes,
                unique=True,
            )
        )
        theme_assignments = [
            ThemeAssignment(
                theme=t,
                confidence=draw(
                    st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
                ),
            )
            for t in themes
        ]
        sentiment = draw(st.sampled_from(["positive", "neutral", "negative"]))
        severity_score = draw(st.integers(min_value=1, max_value=5))
        records.append(
            InsightRecord(
                feedback_id=f"rec-{i}",
                themes=theme_assignments,
                sentiment=sentiment,
                sentiment_confidence=0.8,
                severity_score=severity_score,
                severity_factors=[SeverityFactor(description="test factor")],
                cluster_id="cl-test",
                model_name="test-model",
            )
        )
    return records


# ---------------------------------------------------------------------------
# Trend detection strategies (tasks 9.4, 9.5, 9.6)
# ---------------------------------------------------------------------------
#
# ``insight_records_with_themes()`` generates sets of ``InsightRecord``s with
# controlled theme distributions suitable for testing theme frequency
# computation, spike detection, and spike ordering.

from nlp_processing.models.records import InsightRecord, SeverityFactor, ThemeAssignment

_AVAILABLE_THEMES = [
    "billing",
    "network_speed",
    "outage",
    "support_experience",
    "device_hardware",
    "pricing",
    "other",
]


@st.composite
def insight_records_with_themes(
    draw,
    min_records: int = 10,
    max_records: int = 30,
    min_themes_per_record: int = 1,
    max_themes_per_record: int = 3,
) -> list[InsightRecord]:
    """Generate a list of InsightRecords with controlled theme distributions.

    Each record gets between ``min_themes_per_record`` and
    ``max_themes_per_record`` distinct theme assignments drawn from the
    available theme set. This is designed for property tests exercising
    theme frequency computation, spike detection, and ordering.

    Returns a list of valid InsightRecords with at least ``min_records``
    entries, suitable for passing directly to ``_detect_theme_spikes`` or
    ``_compute_theme_frequencies``.
    """
    n = draw(st.integers(min_value=min_records, max_value=max_records))
    records: list[InsightRecord] = []

    for i in range(n):
        num_themes = draw(
            st.integers(min_value=min_themes_per_record, max_value=max_themes_per_record)
        )
        # Draw distinct themes for this record
        themes = draw(
            st.lists(
                st.sampled_from(_AVAILABLE_THEMES),
                min_size=num_themes,
                max_size=num_themes,
                unique=True,
            )
        )
        theme_assignments = [
            ThemeAssignment(
                theme=t,
                confidence=draw(
                    st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False)
                ),
            )
            for t in themes
        ]
        sentiment = draw(st.sampled_from(["positive", "neutral", "negative"]))
        severity = draw(st.integers(min_value=1, max_value=5))

        records.append(
            InsightRecord(
                feedback_id=f"fb-{i}",
                themes=theme_assignments,
                sentiment=sentiment,
                sentiment_confidence=0.85,
                severity_score=severity,
                severity_factors=[SeverityFactor(description="generated factor")],
                cluster_id="cl-gen",
                model_name="test-model",
            )
        )

    return records


# ---------------------------------------------------------------------------
# Trend detection strategies (tasks 9.7, 9.8)
# ---------------------------------------------------------------------------
#
# ``time_window_pair()`` generates valid, non-overlapping TimeWindow pairs.
# ``invalid_time_windows()`` generates window pairs that violate constraints.

from nlp_processing.models.enhancements import TimeWindow


@st.composite
def time_window_pair(draw) -> tuple[TimeWindow, TimeWindow]:
    """Generate a pair of valid, non-overlapping TimeWindow objects.

    The baseline window always ends before the current window starts,
    ensuring no overlap and valid ordering (start < end for each window).
    """
    # Generate four ordered timestamps to form two non-overlapping windows:
    # baseline_start < baseline_end <= current_start < current_end
    # Use year offsets from 2020 to keep timestamps reasonable
    base_year = 2020
    # baseline_start: day offset from epoch
    b_start_day = draw(st.integers(min_value=0, max_value=365))
    # baseline duration: at least 1 day
    b_duration = draw(st.integers(min_value=1, max_value=90))
    # gap between windows: 0 or more days (0 means adjacent)
    gap = draw(st.integers(min_value=0, max_value=60))
    # current duration: at least 1 day
    c_duration = draw(st.integers(min_value=1, max_value=90))

    from datetime import timedelta

    baseline_start = datetime(base_year, 1, 1, tzinfo=timezone.utc) + timedelta(days=b_start_day)
    baseline_end = baseline_start + timedelta(days=b_duration)
    current_start = baseline_end + timedelta(days=gap)
    current_end = current_start + timedelta(days=c_duration)

    return (
        TimeWindow(start=baseline_start.isoformat(), end=baseline_end.isoformat()),
        TimeWindow(start=current_start.isoformat(), end=current_end.isoformat()),
    )


@st.composite
def invalid_time_windows(draw) -> tuple[TimeWindow, TimeWindow]:
    """Generate TimeWindow pairs that violate validation constraints.

    Produces one of three violations:
    - Baseline start >= end
    - Current start >= end
    - Windows overlap
    """
    from datetime import timedelta

    kind = draw(st.sampled_from(["baseline_invalid", "current_invalid", "overlap"]))
    base_year = 2020

    if kind == "baseline_invalid":
        # Baseline start >= end
        b_start = datetime(base_year, 6, 15, tzinfo=timezone.utc)
        offset = draw(st.integers(min_value=0, max_value=30))
        b_end = b_start - timedelta(days=offset)  # end <= start
        # Current is valid
        c_start = datetime(base_year, 9, 1, tzinfo=timezone.utc)
        c_end = c_start + timedelta(days=draw(st.integers(min_value=1, max_value=30)))
    elif kind == "current_invalid":
        # Current start >= end
        b_start = datetime(base_year, 1, 1, tzinfo=timezone.utc)
        b_end = b_start + timedelta(days=draw(st.integers(min_value=1, max_value=30)))
        c_start = datetime(base_year, 6, 15, tzinfo=timezone.utc)
        offset = draw(st.integers(min_value=0, max_value=30))
        c_end = c_start - timedelta(days=offset)  # end <= start
    else:
        # Overlapping windows
        b_start = datetime(base_year, 1, 1, tzinfo=timezone.utc)
        b_duration = draw(st.integers(min_value=10, max_value=60))
        b_end = b_start + timedelta(days=b_duration)
        # Current starts before baseline ends (overlap)
        overlap_amount = draw(st.integers(min_value=1, max_value=b_duration - 1))
        c_start = b_end - timedelta(days=overlap_amount)
        c_end = c_start + timedelta(days=draw(st.integers(min_value=overlap_amount + 1, max_value=90)))

    return (
        TimeWindow(start=b_start.isoformat(), end=b_end.isoformat()),
        TimeWindow(start=c_start.isoformat(), end=c_end.isoformat()),
    )
