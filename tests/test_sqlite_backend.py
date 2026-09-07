"""Tests for the SQLite database backend."""

import struct

import pytest

from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.interfaces.database import (
    AnswerCacheRecord,
    ChunkRecord,
    DocumentRecord,
    SectionRecord,
)


class TestInitialize:
    def test_initialize_creates_tables(self, backend):
        """Tables and FTS5 are created on initialize."""
        with backend.session() as session:
            tables = session.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = {row["name"] for row in tables}

            assert "documents" in table_names
            assert "sections" in table_names
            assert "chunks" in table_names
            assert "answer_cache" in table_names
            assert "sections_fts" in table_names


class TestDocuments:
    def test_store_and_get_document(self, backend, sample_document):
        """Document round-trip: store then read back."""
        with backend.session() as session:
            backend.store_document(session, sample_document)

        with backend.session() as session:
            row = session.execute(
                "SELECT * FROM documents WHERE id = ?", (sample_document.id,)
            ).fetchone()
            assert row is not None
            assert row["title"] == "Test Statute"
            assert row["document_type"] == "statute"
            assert row["jurisdiction"] == "US"


class TestSections:
    def test_store_and_get_section(self, backend, sample_document, sample_section):
        """Section round-trip: store then get by ID."""
        with backend.session() as session:
            backend.store_document(session, sample_document)
            backend.store_section(session, sample_section)

        with backend.session() as session:
            section = backend.get_section(session, "sec-001")
            assert section is not None
            assert section.id == "sec-001"
            assert section.text_content == sample_section.text_content
            assert section.version_hash == "abc123hash"
            assert section.is_current is True

    def test_get_section_by_citation(self, backend, sample_document, sample_section):
        """Citation lookup returns the correct section."""
        with backend.session() as session:
            backend.store_document(session, sample_document)
            backend.store_section(session, sample_section)

        with backend.session() as session:
            section = backend.get_section_by_citation(session, "42 U.S.C. § 1983")
            assert section is not None
            assert section.id == "sec-001"

    def test_get_section_by_citation_not_found(self, backend):
        """Citation lookup returns None for non-existent citation."""
        with backend.session() as session:
            section = backend.get_section_by_citation(session, "nonexistent")
            assert section is None

    def test_get_section_version_hash(self, backend, sample_document, sample_section):
        """Hash-only lookup returns just the version_hash."""
        with backend.session() as session:
            backend.store_document(session, sample_document)
            backend.store_section(session, sample_section)

        with backend.session() as session:
            h = backend.get_section_version_hash(session, "sec-001")
            assert h == "abc123hash"

    def test_get_section_version_hash_not_found(self, backend):
        """Hash lookup returns None for non-existent section."""
        with backend.session() as session:
            h = backend.get_section_version_hash(session, "nonexistent")
            assert h is None


class TestChunks:
    def test_store_chunk_with_embedding(self, backend, sample_document, sample_section, sample_chunk):
        """Chunk with float vector stores and can be read back."""
        with backend.session() as session:
            backend.store_document(session, sample_document)
            backend.store_section(session, sample_section)
            backend.store_chunk(session, sample_chunk)

        with backend.session() as session:
            row = session.execute(
                "SELECT * FROM chunks WHERE id = ?", (sample_chunk.id,)
            ).fetchone()
            assert row is not None
            assert row["text_content"] == sample_chunk.text_content
            assert row["chunk_index"] == 0
            # Verify the embedding blob can be decoded
            blob = row["embedding"]
            assert blob is not None
            floats = struct.unpack(f"{len(blob)//4}f", blob)
            assert len(floats) == 4
            assert abs(floats[0] - 0.1) < 0.001


class TestHybridSearch:
    def test_hybrid_search(self, backend, sample_document, sample_section):
        """FTS5 search returns results for matching text."""
        with backend.session() as session:
            backend.store_document(session, sample_document)
            backend.store_section(session, sample_section)

        with backend.session() as session:
            results = backend.hybrid_search(session, "employment law")
            assert len(results) >= 1
            assert results[0].section_id == "sec-001"
            assert results[0].score > 0

    def test_hybrid_search_no_results(self, backend):
        """Search returns empty list when no matches."""
        with backend.session() as session:
            results = backend.hybrid_search(session, "xyznonexistent")
            assert results == []


class TestCacheOperations:
    def test_cache_operations(self, backend, sample_cache_record, sample_document, sample_section):
        """Full CRUD on answer cache: store, lookup, increment serve, invalidate."""
        with backend.session() as session:
            backend.store_document(session, sample_document)
            backend.store_section(session, sample_section)
            backend.cache_store(session, sample_cache_record)

        # Lookup
        with backend.session() as session:
            cached = backend.cache_lookup(session, "testkey123")
            assert cached is not None
            assert cached.answer_text == sample_cache_record.answer_text
            assert cached.serve_count == 0

        # Increment serve
        with backend.session() as session:
            backend.cache_increment_serve(session, "cache-001")

        with backend.session() as session:
            cached = backend.cache_lookup(session, "testkey123")
            assert cached.serve_count == 1

        # Invalidate
        with backend.session() as session:
            backend.cache_invalidate(session, "cache-001", "test reason")

        with backend.session() as session:
            cached = backend.cache_lookup(session, "testkey123")
            assert cached is None  # invalidated records not returned

    def test_cache_invalidate_by_section(self, backend, sample_document, sample_section):
        """Cascade invalidation: invalidate all answers referencing a section."""
        with backend.session() as session:
            backend.store_document(session, sample_document)
            backend.store_section(session, sample_section)

            record1 = AnswerCacheRecord(
                id="ci-1", answer_key="ci-key-1",
                source_sections=[{"section_id": "sec-001", "version_hash": "abc123hash"}],
                answer_text="answer 1",
            )
            record2 = AnswerCacheRecord(
                id="ci-2", answer_key="ci-key-2",
                source_sections=[{"section_id": "sec-999", "version_hash": "other"}],
                answer_text="answer 2",
            )
            backend.cache_store(session, record1)
            backend.cache_store(session, record2)

        with backend.session() as session:
            count = backend.cache_invalidate_by_section(session, "sec-001")
            assert count == 1

        # First record should be invalidated, second still valid
        with backend.session() as session:
            assert backend.cache_lookup(session, "ci-key-1") is None
            assert backend.cache_lookup(session, "ci-key-2") is not None

    def _store_entries(self, backend, count, prefix="cc"):
        for i in range(count):
            with backend.session() as session:
                backend.cache_store(
                    session,
                    AnswerCacheRecord(
                        id=f"{prefix}-{i}",
                        answer_key=f"{prefix}-key-{i}",
                        source_sections=[{"section_id": "sec-001", "version_hash": "abc123hash"}],
                        answer_text=f"answer {i}",
                    ),
                )

    def test_cache_clear_all(self, backend, sample_document, sample_section):
        """Clearing removes every valid entry and reports how many were cleared."""
        with backend.session() as session:
            backend.store_document(session, sample_document)
            backend.store_section(session, sample_section)
        self._store_entries(backend, 3)

        with backend.session() as session:
            assert backend.cache_clear_all(session) == 3

        with backend.session() as session:
            for i in range(3):
                assert backend.cache_lookup(session, f"cc-key-{i}") is None

    def test_cache_clear_all_on_empty_cache(self, backend):
        """Clearing an empty cache is a no-op reporting zero, not an error."""
        with backend.session() as session:
            assert backend.cache_clear_all(session) == 0

    def test_cache_clear_all_skips_already_invalidated(self, backend, sample_document, sample_section):
        """Entries invalidated earlier are not counted a second time."""
        with backend.session() as session:
            backend.store_document(session, sample_document)
            backend.store_section(session, sample_section)
        self._store_entries(backend, 2, prefix="ci2")

        with backend.session() as session:
            backend.cache_invalidate(session, "ci2-0", "already gone")

        with backend.session() as session:
            assert backend.cache_clear_all(session) == 1

    def test_cache_clear_all_persists_reason(self, backend, sample_document, sample_section):
        """The supplied reason is written to the invalidated rows."""
        with backend.session() as session:
            backend.store_document(session, sample_document)
            backend.store_section(session, sample_section)
        self._store_entries(backend, 1, prefix="cr")

        with backend.session() as session:
            backend.cache_clear_all(session, reason="demo reset")

        with backend.session() as session:
            row = session.execute(
                "SELECT is_valid, invalidation_reason FROM answer_cache WHERE id = ?", ("cr-0",)
            ).fetchone()
            assert row["is_valid"] == 0
            assert row["invalidation_reason"] == "demo reset"


class TestSessionRollback:
    def test_session_rollback_on_error(self, backend, sample_document):
        """Transaction safety: rollback on error."""
        with backend.session() as session:
            backend.store_document(session, sample_document)

        # Try to insert a duplicate — should fail and rollback
        with pytest.raises(Exception):
            with backend.session() as session:
                backend.store_document(session, sample_document)

        # Original document should still be there
        with backend.session() as session:
            row = session.execute(
                "SELECT * FROM documents WHERE id = ?", (sample_document.id,)
            ).fetchone()
            assert row is not None
