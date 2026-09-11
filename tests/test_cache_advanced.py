"""Advanced cache engine tests: filters, invalidation cascades, temporal, stats, concurrency.

# TODO: Add threading.Thread-based concurrency tests to verify thread safety of
# cache reads/writes under contention (e.g., concurrent store_answer + lookup).
"""

import json
import threading

import pytest

from bitmod.cache_engine import (
    compute_answer_key,
    double_verify,
    get_cache_stats,
    invalidate_by_section,
    is_temporal_query,
    normalize_for_key,
    store_answer,
    try_cache,
)
from bitmod.interfaces.database import AnswerCacheRecord, DocumentRecord, SectionRecord


class TestMultipleFilterCombinations:
    """Test cache keying with various filter combinations."""

    def test_single_filter(self):
        """Single filter produces a unique key."""
        k1 = compute_answer_key("employment law", filters={"jurisdiction": "CA"})
        k2 = compute_answer_key("employment law", filters={"jurisdiction": "TX"})
        assert k1 != k2

    def test_multiple_filters(self):
        """Multiple filters produce a different key from single filter."""
        k1 = compute_answer_key("law", filters={"jurisdiction": "CA"})
        k2 = compute_answer_key("law", filters={"jurisdiction": "CA", "document_type": "statute"})
        assert k1 != k2

    def test_filter_order_irrelevant(self):
        """Filter insertion order does not affect the key (sorted internally)."""
        from collections import OrderedDict
        k1 = compute_answer_key("law", filters={"a": "1", "b": "2"})
        k2 = compute_answer_key("law", filters={"b": "2", "a": "1"})
        assert k1 == k2

    def test_empty_filter_values_ignored(self):
        """Filters with empty values do not affect the key."""
        k1 = compute_answer_key("law", filters={})
        k2 = compute_answer_key("law", filters={"jurisdiction": ""})
        assert k1 == k2

    def test_no_filters_vs_none_filters(self):
        """None filters and empty dict produce the same key."""
        k1 = compute_answer_key("law", filters=None)
        k2 = compute_answer_key("law", filters={})
        assert k1 == k2

    def test_temporal_scope_filter(self):
        """Temporal scope creates distinct key."""
        k1 = compute_answer_key("law")
        k2 = compute_answer_key("law", temporal_scope="2023-01-01")
        assert k1 != k2

    def test_language_filter(self):
        """Non-English language creates distinct key; English is default."""
        k_en = compute_answer_key("law", language="en")
        k_none = compute_answer_key("law")
        k_es = compute_answer_key("law", language="es")
        assert k_en == k_none
        assert k_en != k_es


class TestCacheInvalidationCascade:
    """Test that section changes cascade to invalidate referencing answers."""

    def _setup_doc_and_section(self, backend, section_id="sec-cas-001", version_hash="hash_v1"):
        """Helper to insert a document and section."""
        doc = DocumentRecord(
            id="doc-cas-001", document_type="test", source="test",
            title="Cascade Doc", source_format="text",
        )
        sec = SectionRecord(
            id=section_id, document_id="doc-cas-001",
            text_content="Original content.", version_hash=version_hash,
            is_current=True,
        )
        with backend.session() as session:
            backend.store_document(session, doc)
            backend.store_section(session, sec)

    def test_single_answer_invalidated(self, backend):
        """One answer referencing a changed section is invalidated."""
        self._setup_doc_and_section(backend)
        with backend.session() as session:
            store_answer(
                backend, session, answer_key="cas-key-1",
                question_raw="q", question_normalized="q", filters={},
                answer_text="answer", model_used="test", generation_ms=100,
                source_sections=[{"section_id": "sec-cas-001", "version_hash": "hash_v1"}],
            )
        with backend.session() as session:
            count = invalidate_by_section(backend, session, "sec-cas-001")
            assert count == 1
        with backend.session() as session:
            assert backend.cache_lookup(session, "cas-key-1") is None

    def test_multiple_answers_invalidated(self, backend):
        """All answers referencing the section are invalidated, others untouched."""
        self._setup_doc_and_section(backend)
        with backend.session() as session:
            store_answer(
                backend, session, answer_key="cas-multi-1",
                question_raw="q1", question_normalized="q1", filters={},
                answer_text="a1", model_used="test", generation_ms=100,
                source_sections=[{"section_id": "sec-cas-001", "version_hash": "hash_v1"}],
            )
            store_answer(
                backend, session, answer_key="cas-multi-2",
                question_raw="q2", question_normalized="q2", filters={},
                answer_text="a2", model_used="test", generation_ms=100,
                source_sections=[{"section_id": "sec-cas-001", "version_hash": "hash_v1"}],
            )
            store_answer(
                backend, session, answer_key="cas-multi-3",
                question_raw="q3", question_normalized="q3", filters={},
                answer_text="a3", model_used="test", generation_ms=100,
                source_sections=[{"section_id": "sec-other", "version_hash": "other"}],
            )
        with backend.session() as session:
            count = invalidate_by_section(backend, session, "sec-cas-001")
            assert count == 2
        with backend.session() as session:
            assert backend.cache_lookup(session, "cas-multi-1") is None
            assert backend.cache_lookup(session, "cas-multi-2") is None
            assert backend.cache_lookup(session, "cas-multi-3") is not None

    def test_no_matching_section(self, backend):
        """Invalidating a section with no referencing answers returns 0."""
        with backend.session() as session:
            count = invalidate_by_section(backend, session, "nonexistent-section")
            assert count == 0


class TestTemporalQueries:
    """Test temporal (permanently valid) query handling."""

    def test_is_temporal_query_true(self):
        """Record with temporal_scope filter is recognized as temporal."""
        rec = AnswerCacheRecord(
            id="t1", filters={"temporal_scope": "2020-01-01"},
        )
        assert is_temporal_query(rec) is True

    def test_is_temporal_query_false(self):
        """Record without temporal_scope is not temporal."""
        rec = AnswerCacheRecord(id="t2", filters={"jurisdiction": "CA"})
        assert is_temporal_query(rec) is False

    def test_is_temporal_query_empty_filters(self):
        """Record with empty filters is not temporal."""
        rec = AnswerCacheRecord(id="t3", filters={})
        assert is_temporal_query(rec) is False

    def test_temporal_skips_double_verify(self, backend):
        """Temporal queries bypass double-verification (permanently valid)."""
        query = "law trends in 2019"
        filters = {"temporal_scope": "2019"}
        answer_key = compute_answer_key(query, filters)
        with backend.session() as session:
            store_answer(
                backend, session, answer_key=answer_key,
                question_raw=query, question_normalized=normalize_for_key(query),
                filters=filters, answer_text="Historical data.",
                source_sections=[{"section_id": "ghost-section", "version_hash": "ghost"}],
                model_used="test", generation_ms=50,
            )
        # Section doesn't exist, but temporal query should still return the cached answer
        with backend.session() as session:
            result = try_cache(backend, session, query, filters)
            assert result is not None
            assert result.answer_text == "Historical data."


class TestCacheStatsAccuracy:
    """Test that cache_stats returns accurate numbers."""

    def test_empty_cache_stats(self, backend):
        """Empty cache returns zeroed stats."""
        with backend.session() as session:
            stats = get_cache_stats(backend, session)
            assert stats["total_entries"] == 0
            assert stats["valid_entries"] == 0
            assert stats["invalidated_entries"] == 0
            assert stats["total_serves"] == 0

    def test_stats_after_store(self, backend):
        """Stats update after storing entries."""
        with backend.session() as session:
            store_answer(
                backend, session, answer_key="stat-1",
                question_raw="q", question_normalized="q", filters={},
                answer_text="a", model_used="m", generation_ms=200,
                source_sections=[],
            )
            store_answer(
                backend, session, answer_key="stat-2",
                question_raw="q2", question_normalized="q2", filters={},
                answer_text="a2", model_used="m", generation_ms=300,
                source_sections=[],
            )
        with backend.session() as session:
            stats = get_cache_stats(backend, session)
            assert stats["total_entries"] == 2
            assert stats["valid_entries"] == 2
            assert stats["avg_generation_ms"] == 250.0

    def test_stats_after_invalidation(self, backend):
        """Invalidated entries are counted separately."""
        with backend.session() as session:
            store_answer(
                backend, session, answer_key="stat-inv-1",
                question_raw="q", question_normalized="q", filters={},
                answer_text="a", model_used="m", generation_ms=100,
                source_sections=[],
            )
        with backend.session() as session:
            rec = backend.cache_lookup(session, "stat-inv-1")
            backend.cache_invalidate(session, rec.id, "test")
        with backend.session() as session:
            stats = get_cache_stats(backend, session)
            assert stats["total_entries"] == 1
            assert stats["valid_entries"] == 0
            assert stats["invalidated_entries"] == 1

    def test_stats_serve_count(self, backend):
        """Total serves accumulates with cache_increment_serve."""
        with backend.session() as session:
            store_answer(
                backend, session, answer_key="stat-serve",
                question_raw="q", question_normalized="q", filters={},
                answer_text="a", model_used="m", generation_ms=100,
                source_sections=[],
            )
        with backend.session() as session:
            rec = backend.cache_lookup(session, "stat-serve")
            backend.cache_increment_serve(session, rec.id)
            backend.cache_increment_serve(session, rec.id)
            backend.cache_increment_serve(session, rec.id)
        with backend.session() as session:
            stats = get_cache_stats(backend, session)
            assert stats["total_serves"] == 3


class TestConcurrentCacheOperations:
    """Test cache behavior under concurrent access."""

    def test_concurrent_stores(self, backend):
        """Sequential stores all succeed (SQLite single-writer)."""
        for idx in range(10):
            with backend.session() as session:
                store_answer(
                    backend, session, answer_key=f"conc-{idx}",
                    question_raw=f"q{idx}", question_normalized=f"q{idx}",
                    filters={}, answer_text=f"a{idx}", model_used="m",
                    generation_ms=100, source_sections=[],
                )

        with backend.session() as session:
            count = session.execute("SELECT COUNT(*) FROM answer_cache").fetchone()[0]
            assert count == 10


class TestRecentCachedQueries:
    """Test recent_cached_queries method."""

    def test_returns_recent_queries(self, backend):
        """Returns stored queries in recency order."""
        with backend.session() as session:
            store_answer(
                backend, session, answer_key="recent-1",
                question_raw="First question", question_normalized="first",
                filters={}, answer_text="a", model_used="m",
                generation_ms=100, source_sections=[],
            )
            store_answer(
                backend, session, answer_key="recent-2",
                question_raw="Second question", question_normalized="second",
                filters={}, answer_text="b", model_used="m",
                generation_ms=200, source_sections=[],
            )
        with backend.session() as session:
            recent = backend.recent_cached_queries(session, limit=10)
            assert len(recent) == 2
            assert recent[0]["question"] in ("First question", "Second question")
            assert "generation_ms" in recent[0]
            assert "is_valid" in recent[0]

    def test_limit_respected(self, backend):
        """Limit parameter caps the number of results."""
        with backend.session() as session:
            for i in range(5):
                store_answer(
                    backend, session, answer_key=f"lim-{i}",
                    question_raw=f"q{i}", question_normalized=f"q{i}",
                    filters={}, answer_text=f"a{i}", model_used="m",
                    generation_ms=100, source_sections=[],
                )
        with backend.session() as session:
            recent = backend.recent_cached_queries(session, limit=3)
            assert len(recent) == 3


class TestDocumentStats:
    """Test document_stats method."""

    def test_document_stats_empty(self, backend):
        """Empty database returns zero totals."""
        with backend.session() as session:
            stats = backend.document_stats(session)
            assert stats["totals"]["document_count"] == 0
            assert stats["totals"]["total_sections"] == 0
            assert stats["totals"]["total_chunks"] == 0

    def test_document_stats_after_ingest(self, backend):
        """Stats reflect ingested documents with sections and chunks."""
        from bitmod.ingestion.pipeline import ingest_text
        ingest_text(
            text="Test content for document stats with enough text to be meaningful. " * 10,
            title="Stats Doc",
            document_type="test",
            backend=backend,
        )
        with backend.session() as session:
            stats = backend.document_stats(session)
            assert stats["totals"]["document_count"] == 1
            assert stats["totals"]["total_sections"] >= 1
            assert stats["totals"]["total_chunks"] >= 1
            doc = stats["documents"][0]
            assert doc["title"] == "Stats Doc"
            assert doc["document_type"] == "test"
            assert doc["section_count"] >= 1
