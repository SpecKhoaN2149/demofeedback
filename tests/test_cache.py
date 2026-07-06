"""Property-based tests for the CacheLayer.

Tests validate cache correctness properties from the design document
for the nlp-pipeline-enhancements feature.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from nlp_processing.config import ConfigurationError
from nlp_processing.persistence.cache import CacheLayer
from nlp_processing.persistence.store import PersistenceStore
from tests.strategies import valid_cached_enrichment


# Feature: nlp-pipeline-enhancements, Property 3: Cache key determinism
# **Validates: Requirements 2.1**
@given(
    cleaned_text=st.text(min_size=0, max_size=500),
    language_code=st.sampled_from(["en", "es", "fr", "de", "pt"]),
)
@settings(max_examples=100)
def test_cache_key_determinism(cleaned_text, language_code):
    """For any cleaned_text string and language_code, calling
    compute_key(cleaned_text, language_code) multiple times SHALL always
    produce the same hash value.
    """
    store = PersistenceStore(backend="sqlite", db_path=":memory:")
    cache = CacheLayer(store=store)

    key1 = cache.compute_key(cleaned_text, language_code)
    key2 = cache.compute_key(cleaned_text, language_code)
    key3 = cache.compute_key(cleaned_text, language_code)

    assert key1 == key2
    assert key2 == key3


# Feature: nlp-pipeline-enhancements, Property 5: Cache TTL validation
# **Validates: Requirements 2.3, 2.4**
@given(valid_ttl=st.integers(min_value=1, max_value=720))
@settings(max_examples=100)
def test_cache_ttl_validation_valid(valid_ttl):
    """For any integer value in the inclusive range 1 to 720, constructing
    the CacheLayer with that TTL SHALL succeed.
    """
    store = PersistenceStore(backend="sqlite", db_path=":memory:")
    cache = CacheLayer(store=store, ttl_hours=valid_ttl)
    assert cache._ttl_hours == valid_ttl


@given(
    invalid_ttl=st.one_of(
        st.integers(max_value=0),
        st.integers(min_value=721),
    )
)
@settings(max_examples=100)
def test_cache_ttl_validation_invalid_integers(invalid_ttl):
    """For any integer value outside the range 1 to 720, constructing
    the CacheLayer SHALL raise a ConfigurationError.
    """
    store = PersistenceStore(backend="sqlite", db_path=":memory:")
    with pytest.raises(ConfigurationError):
        CacheLayer(store=store, ttl_hours=invalid_ttl)


def test_cache_ttl_validation_non_integer():
    """For any value that is not an integer, constructing the CacheLayer
    SHALL raise a ConfigurationError.
    """
    store = PersistenceStore(backend="sqlite", db_path=":memory:")
    with pytest.raises(ConfigurationError):
        CacheLayer(store=store, ttl_hours=3.5)  # type: ignore
    with pytest.raises(ConfigurationError):
        CacheLayer(store=store, ttl_hours="24")  # type: ignore
    with pytest.raises(ConfigurationError):
        CacheLayer(store=store, ttl_hours=True)  # type: ignore


# Feature: nlp-pipeline-enhancements, Property 4: Cache enrichment round-trip
# **Validates: Requirements 2.2, 2.9**
@given(
    enrichment=valid_cached_enrichment(),
    cleaned_text=st.text(min_size=1, max_size=200),
    language_code=st.sampled_from(["en", "es", "fr", "de", "pt"]),
)
@settings(max_examples=100)
def test_cache_enrichment_round_trip(enrichment, cleaned_text, language_code):
    """For any valid CachedEnrichment, storing it via put and then retrieving
    it via get with the same cleaned_text and language_code (before TTL expiry)
    SHALL produce classification themes, sentiment, sentiment_confidence,
    severity_score, and severity_factors that are field-by-field identical to
    the originally stored enrichment.
    """
    store = PersistenceStore(backend="sqlite", db_path=":memory:")
    cache = CacheLayer(store=store, ttl_hours=24)

    cache.put(cleaned_text, language_code, enrichment)
    retrieved = cache.get(cleaned_text, language_code)

    assert retrieved is not None

    # Field-by-field comparison of enrichment data
    assert retrieved.themes == enrichment.themes
    assert retrieved.sentiment == enrichment.sentiment
    assert retrieved.sentiment_confidence == enrichment.sentiment_confidence
    assert retrieved.severity_score == enrichment.severity_score
    assert retrieved.severity_factors == enrichment.severity_factors



# Feature: nlp-pipeline-enhancements, Property 7: Disabled cache bypass
# **Validates: Requirements 2.7**
@given(
    enrichment=valid_cached_enrichment(),
    cleaned_text=st.text(min_size=1, max_size=200),
    language_code=st.sampled_from(["en", "es", "fr", "de", "pt"]),
)
@settings(max_examples=100)
def test_disabled_cache_bypass(enrichment, cleaned_text, language_code):
    """For any cleaned_text and language_code, when the CacheLayer is
    constructed with enabled=False, calling get SHALL always return None.
    """
    store = PersistenceStore(backend="sqlite", db_path=":memory:")

    # First, populate the store directly using an enabled cache
    enabled_cache = CacheLayer(store=store, ttl_hours=24, enabled=True)
    enabled_cache.put(cleaned_text, language_code, enrichment)

    # Verify it's actually stored
    assert enabled_cache.get(cleaned_text, language_code) is not None

    # Now create a disabled cache on the same store
    disabled_cache = CacheLayer(store=store, ttl_hours=24, enabled=False)

    # get should always return None when disabled
    assert disabled_cache.get(cleaned_text, language_code) is None


# Feature: nlp-pipeline-enhancements, Property 6: Cache TTL expiry
# **Validates: Requirements 2.5**
@given(enrichment=valid_cached_enrichment())
@settings(max_examples=100)
def test_cache_ttl_expiry(enrichment):
    """For any CachedEnrichment whose creation time plus the configured TTL
    is earlier than the current time, calling get SHALL return None
    (the stale entry is discarded).
    """
    store = PersistenceStore(backend="sqlite", db_path=":memory:")
    cache = CacheLayer(store=store, ttl_hours=1)
    cache.put("test text", "en", enrichment)

    # Manually set the expires_at to the past in the database
    key = cache.compute_key("test text", "en")
    past_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    store._conn.execute(
        "UPDATE cache_entries SET expires_at = ? WHERE key = ?",
        (past_time, key),
    )
    store._conn.commit()

    # Now get should return None because entry is expired
    result = cache.get("test text", "en")
    assert result is None


# Feature: nlp-pipeline-enhancements, Property 19: Cache key language differentiation
# **Validates: Requirements 6.7**
@given(
    cleaned_text=st.text(min_size=0, max_size=500),
    lang_a=st.sampled_from(["en", "es", "fr", "de", "pt"]),
    lang_b=st.sampled_from(["en", "es", "fr", "de", "pt"]),
)
@settings(max_examples=100)
def test_cache_key_language_differentiation(cleaned_text, lang_a, lang_b):
    """For any cleaned_text and two distinct language_code values,
    compute_key(cleaned_text, lang_a) SHALL produce a different key than
    compute_key(cleaned_text, lang_b).
    """
    assume(lang_a != lang_b)
    store = PersistenceStore(backend="sqlite", db_path=":memory:")
    cache = CacheLayer(store=store)
    key_a = cache.compute_key(cleaned_text, lang_a)
    key_b = cache.compute_key(cleaned_text, lang_b)
    assert key_a != key_b
