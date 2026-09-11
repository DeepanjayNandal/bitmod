"""Tests for the Bitmod cache engine — the core IP."""

import pytest

from bitmod.cache_engine import (
    compute_answer_key,
    decompose_query,
    double_verify,
    fuzzy_match,
    get_cache_stats,
    invalidate_by_section,
    is_temporal_query,
    normalize_for_key,
    store_answer,
    try_cache,
    try_composable_cache,
)
from bitmod.interfaces.database import AnswerCacheRecord


class TestNormalizeQuery:
    def test_normalize_query(self):
        """Empty words removed, punctuation stripped, order preserved.

        "what" and "is" are kept. They used to be stripped, which made
        "How do scientists work?" and "Where do scientists work?" the same key
        and served one answer for both at confidence 1.0. Only words that
        cannot change the answer are dropped now.
        """
        result = normalize_for_key("What is the employment law?")
        assert result == "what is employment law"
        assert "the" not in result.split()  # article: carries nothing
        assert "what" in result.split()  # interrogative: decides the question

    def test_normalize_removes_punctuation(self):
        result = normalize_for_key("Hello, world! How are you?")
        assert "," not in result
        assert "!" not in result
        assert "?" not in result

    def test_normalize_case_insensitive(self):
        r1 = normalize_for_key("Employment Law")
        r2 = normalize_for_key("employment law")
        assert r1 == r2

    def test_normalize_strips_short_tokens(self):
        result = normalize_for_key("I am a big fan")
        # "I", "a" are single-char and removed; "am" is a stopword
        assert "big" in result
        assert "fan" in result


class TestComputeAnswerKey:
    def test_compute_answer_key(self):
        """Deterministic keying."""
        key1 = compute_answer_key("What is employment law?")
        key2 = compute_answer_key("What is employment law?")
        assert key1 == key2
        assert len(key1) == 64  # SHA-256 hex

    def test_filter_impact(self):
        """Different filters produce different keys."""
        key1 = compute_answer_key("employment law", filters={"jurisdiction": "CA"})
        key2 = compute_answer_key("employment law", filters={"jurisdiction": "TX"})
        assert key1 != key2

    def test_temporal_scope(self):
        """Temporal scope affects key."""
        key1 = compute_answer_key("employment law")
        key2 = compute_answer_key("employment law", temporal_scope="2024-01-01")
        assert key1 != key2

    def test_language_default_english(self):
        """English (default) doesn't change key."""
        key1 = compute_answer_key("employment law")
        key2 = compute_answer_key("employment law", language="en")
        assert key1 == key2

    def test_language_non_english(self):
        """Non-English language changes key."""
        key1 = compute_answer_key("employment law")
        key2 = compute_answer_key("employment law", language="es")
        assert key1 != key2


class TestCacheStoreAndLookup:
    def test_cache_store_and_lookup(self, backend):
        """Round-trip store then lookup."""
        with backend.session() as session:
            record = store_answer(
                backend, session,
                answer_key="test-key-001",
                question_raw="What is tort law?",
                question_normalized="law tort",
                filters={},
                answer_text="Tort law deals with civil wrongs.",
                source_sections=[],
                model_used="test-model",
                generation_ms=100,
                confidence=0.9,
            )

        with backend.session() as session:
            cached = backend.cache_lookup(session, "test-key-001")
            assert cached is not None
            assert cached.answer_text == "Tort law deals with civil wrongs."
            assert cached.model_used == "test-model"


class TestDoubleVerify:
    def test_double_verify_passes(self, backend, sample_document, sample_section):
        """When source hashes match, double verify passes."""
        with backend.session() as session:
            backend.store_document(session, sample_document)
            backend.store_section(session, sample_section)

        cached = AnswerCacheRecord(
            id="dv-pass",
            answer_key="dv-key",
            source_sections=[
                {"section_id": "sec-001", "version_hash": "abc123hash"},
            ],
        )

        with backend.session() as session:
            assert double_verify(backend, session, cached) is True

    def test_double_verify_fails(self, backend, sample_document, sample_section):
        """When source hash changed, double verify fails and auto-invalidates."""
        with backend.session() as session:
            backend.store_document(session, sample_document)
            backend.store_section(session, sample_section)

        # Store the cache record first so invalidation can update it
        cached = AnswerCacheRecord(
            id="dv-fail",
            answer_key="dv-fail-key",
            source_sections=[
                {"section_id": "sec-001", "version_hash": "WRONG_HASH"},
            ],
        )
        with backend.session() as session:
            backend.cache_store(session, cached)

        with backend.session() as session:
            assert double_verify(backend, session, cached) is False

    def test_double_verify_empty_sources(self, backend):
        """No sources means verification passes."""
        cached = AnswerCacheRecord(id="dv-empty", source_sections=[])
        with backend.session() as session:
            assert double_verify(backend, session, cached) is True


class TestTryCache:
    def test_try_cache_hit(self, backend, sample_document, sample_section):
        """Full flow with valid cache — returns cached answer."""
        with backend.session() as session:
            backend.store_document(session, sample_document)
            backend.store_section(session, sample_section)

        query = "What is employment law?"
        filters = {}
        answer_key = compute_answer_key(query, filters)

        with backend.session() as session:
            store_answer(
                backend, session,
                answer_key=answer_key,
                question_raw=query,
                question_normalized=normalize_for_key(query),
                filters=filters,
                answer_text="Employment law answer.",
                source_sections=[
                    {"section_id": "sec-001", "version_hash": "abc123hash"},
                ],
                model_used="test",
                generation_ms=200,
            )

        with backend.session() as session:
            result = try_cache(backend, session, query, filters)
            assert result is not None
            assert result.answer_text == "Employment law answer."

    def test_try_cache_miss(self, backend):
        """When nothing cached, returns None."""
        with backend.session() as session:
            result = try_cache(backend, session, "nonexistent query")
            assert result is None

    def test_temporal_query_skips_verification(self, backend):
        """Temporal queries are permanently valid — skip double verify."""
        query = "employment law in 2020"
        filters = {"temporal_scope": "2020"}
        answer_key = compute_answer_key(query, filters)

        with backend.session() as session:
            store_answer(
                backend, session,
                answer_key=answer_key,
                question_raw=query,
                question_normalized=normalize_for_key(query),
                filters=filters,
                answer_text="Historical answer.",
                source_sections=[
                    {"section_id": "nonexistent", "version_hash": "whatever"},
                ],
                model_used="test",
                generation_ms=100,
            )

        with backend.session() as session:
            result = try_cache(backend, session, query, filters)
            assert result is not None
            assert result.answer_text == "Historical answer."


class TestCacheInvalidation:
    def test_cache_invalidate_by_section(self, backend, sample_document, sample_section):
        """Section change invalidates answers referencing it."""
        with backend.session() as session:
            backend.store_document(session, sample_document)
            backend.store_section(session, sample_section)
            store_answer(
                backend, session,
                answer_key="inv-key-1",
                question_raw="test",
                question_normalized="test",
                filters={},
                answer_text="answer 1",
                source_sections=[{"section_id": "sec-001", "version_hash": "abc123hash"}],
                model_used="test",
                generation_ms=100,
            )

        with backend.session() as session:
            count = invalidate_by_section(backend, session, "sec-001")
            assert count == 1

        with backend.session() as session:
            result = backend.cache_lookup(session, "inv-key-1")
            assert result is None  # invalidated, so lookup returns None


class TestCacheStats:
    def test_cache_stats(self, backend):
        """Stats computation returns expected keys."""
        with backend.session() as session:
            store_answer(
                backend, session,
                answer_key="stats-key",
                question_raw="test",
                question_normalized="test",
                filters={},
                answer_text="answer",
                source_sections=[],
                model_used="test",
                generation_ms=500,
            )

        with backend.session() as session:
            stats = get_cache_stats(backend, session)
            assert stats["total_entries"] == 1
            assert stats["valid_entries"] == 1
            assert stats["invalidated_entries"] == 0
            assert "total_serves" in stats
            assert "avg_generation_ms" in stats


class TestDecomposeQuery:
    def test_decompose_query_compare(self):
        """'compare X vs Y' decomposition with generic entities."""
        result = decompose_query("Compare employment law vs tax law")
        assert result is not None
        assert len(result) == 2
        entities = {sq.filters.get("entity") for sq in result}
        assert len(entities) == 2

    def test_decompose_query_explicit_compare(self):
        """Explicit comparison with named entities."""
        result = decompose_query("Compare Python vs JavaScript")
        assert result is not None
        assert len(result) == 2
        entities = {sq.filters.get("entity") for sq in result}
        assert "Python" in entities
        assert "JavaScript" in entities

    def test_decompose_query_simple(self):
        """Simple queries return None (not decomposable)."""
        result = decompose_query("what is employment law")
        assert result is None


class TestComposableCache:
    def test_composable_cache(self, backend, sample_document, sample_section):
        """Full composable cache flow — decompose and look up sub-queries."""
        with backend.session() as session:
            backend.store_document(session, sample_document)
            backend.store_section(session, sample_section)

        # Store nothing for sub-queries — expect all misses
        with backend.session() as session:
            result = try_composable_cache(
                backend, session, "Compare Python vs JavaScript"
            )
            assert result is not None
            assert len(result["misses"]) == 2
            assert len(result["hits"]) == 0
            assert result["full_hit"] is False

    def test_composable_cache_simple_query(self, backend):
        """Simple query returns None (not decomposable)."""
        with backend.session() as session:
            result = try_composable_cache(
                backend, session, "what is employment law"
            )
            assert result is None


class TestFuzzyMatch:
    def test_fuzzy_match(self, backend):
        """Fuzzy matching returns similar queries."""
        with backend.session() as session:
            store_answer(
                backend, session,
                answer_key="fuzzy-key",
                question_raw="What is employment law?",
                question_normalized="employment law",
                filters={},
                answer_text="An answer about employment law.",
                source_sections=[],
                model_used="test",
                generation_ms=100,
            )

        with backend.session() as session:
            # Combined Levenshtein + token overlap scoring (60/40 split)
            # produces lower scores than pure token overlap, so use a
            # threshold that reflects the blended scoring.
            results = fuzzy_match(backend, session, "employment law basics",
                                  similarity_threshold=0.70)
            assert isinstance(results, list)
            # SQLite LIKE-based fuzzy should find our record
            assert len(results) >= 1
            assert results[0].record.question_normalized == "employment law"
            # The score the threshold was applied to is now carried on the
            # match rather than discarded, so the fuzzy layer can grade its
            # confidence by it instead of adding a flat constant.
            assert 0.70 <= results[0].similarity <= 1.0
