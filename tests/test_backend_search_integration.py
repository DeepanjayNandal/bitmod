"""Server-backed integration tests for hybrid_search across all four backends.

These verify that SearchResult.version_hash is populated from the sections
table, which cache writers depend on to record source_sections entries that
double_verify can later check. A backend that drops the hash silently produces
unverifiable cache entries rather than failing loudly, so it needs a real
server to catch.

SQLite runs always. PostgreSQL and MySQL are opt-in:

    docker compose -f docker-compose.test.yml up -d

    BITMOD_TEST_POSTGRES=1 \
    DATABASE_URL=postgresql://bitmod:bitmod@localhost:5433/bitmod_test \
    BITMOD_TEST_MYSQL=1 \
    MYSQL_URL=mysql+pymysql://bitmod:bitmod@localhost:3307/bitmod_test \
    pytest tests/test_backend_search_integration.py -v

This file deliberately does not reuse the fixtures in test_integration_500.py,
whose _make_backend() is broken independently of anything tested here.
"""

from __future__ import annotations

import os
import tempfile
import uuid

import pytest
from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.interfaces.database import DocumentRecord, SectionRecord

USE_POSTGRES = os.getenv("BITMOD_TEST_POSTGRES", "0") == "1"
USE_MYSQL = os.getenv("BITMOD_TEST_MYSQL", "0") == "1"

# Text is chosen so every searchable token is >= 4 chars: MySQL InnoDB
# full-text indexing ignores tokens shorter than innodb_ft_min_token_size (3).
SECTION_TEXT = "Refunds are processed within five business days after approval."
SEARCH_TERM = "refunds"
KNOWN_HASH = "sha256:deadbeefcafe1234"


def _seed_and_search(backend, section_id: str, doc_id: str, version_hash: str):
    """Store one section with a known hash, then search for it."""
    with backend.session() as session:
        backend.store_document(
            session,
            DocumentRecord(id=doc_id, source="policy.pdf", title="Refund Policy"),
        )
        backend.store_section(
            session,
            SectionRecord(
                id=section_id,
                document_id=doc_id,
                text_content=SECTION_TEXT,
                section_title="Refunds",
                citation="Policy 2.1",
                version_hash=version_hash,
            ),
        )
    with backend.session() as session:
        return backend.hybrid_search(session, SEARCH_TERM, limit=5)


def _assert_hash_round_trips(results, section_id: str, expected_hash: str):
    match = next((r for r in results if r.section_id == section_id), None)
    assert match is not None, f"hybrid_search did not return seeded section {section_id}"
    assert match.version_hash == expected_hash, (
        f"version_hash lost in transit: expected {expected_hash!r}, got {match.version_hash!r}. "
        "The adapter is not carrying sections.version_hash into SearchResult, so cache "
        "writers cannot record it and every entry becomes unverifiable."
    )


# ---------------------------------------------------------------------------
# SQLite — always runs
# ---------------------------------------------------------------------------


class TestSQLiteSearchCarriesVersionHash:
    @pytest.fixture
    def backend(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        be = SQLiteBackend(path)
        be.initialize()
        yield be
        if os.path.exists(path):
            os.unlink(path)

    def test_hybrid_search_returns_version_hash(self, backend):
        results = _seed_and_search(backend, "sec-sqlite", "doc-sqlite", KNOWN_HASH)
        _assert_hash_round_trips(results, "sec-sqlite", KNOWN_HASH)

    def test_missing_hash_yields_empty_string_not_none(self, backend):
        """A section stored without a hash must give "" — never None.

        double_verify distinguishes falsy (unverifiable) from mismatched
        (stale); None would still be falsy but breaks string comparisons
        downstream in the writers.
        """
        results = _seed_and_search(backend, "sec-nohash", "doc-nohash", "")
        match = next((r for r in results if r.section_id == "sec-nohash"), None)
        assert match is not None
        assert match.version_hash == ""
        assert match.version_hash is not None


# ---------------------------------------------------------------------------
# PostgreSQL — opt-in
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not USE_POSTGRES, reason="PostgreSQL not configured (set BITMOD_TEST_POSTGRES=1)")
class TestPostgreSQLSearchCarriesVersionHash:
    @pytest.fixture(scope="class")
    def backend(self):
        from bitmod.adapters.db_postgresql import PostgreSQLBackend
        from sqlalchemy import text

        be = PostgreSQLBackend(os.environ["DATABASE_URL"])
        # Start from a clean schema so column type changes actually take effect —
        # CREATE TABLE IF NOT EXISTS will not alter an existing table.
        with be._engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        be.initialize()
        return be

    def test_hybrid_search_returns_version_hash(self, backend):
        sid = f"sec-pg-{uuid.uuid4().hex[:8]}"
        did = f"doc-pg-{uuid.uuid4().hex[:8]}"
        results = _seed_and_search(backend, sid, did, KNOWN_HASH)
        _assert_hash_round_trips(results, sid, KNOWN_HASH)

    def test_hybrid_search_text_only_branch(self, backend):
        """The no-embedding branch is separate SQL and must also carry the hash."""
        sid = f"sec-pgt-{uuid.uuid4().hex[:8]}"
        did = f"doc-pgt-{uuid.uuid4().hex[:8]}"
        with backend.session() as session:
            backend.store_document(session, DocumentRecord(id=did, source="p.pdf", title="P"))
            backend.store_section(
                session,
                SectionRecord(
                    id=sid,
                    document_id=did,
                    text_content=SECTION_TEXT,
                    section_title="Refunds",
                    version_hash=KNOWN_HASH,
                ),
            )
        with backend.session() as session:
            results = backend.hybrid_search(session, SEARCH_TERM, embedding=None, limit=5)
        _assert_hash_round_trips(results, sid, KNOWN_HASH)


# ---------------------------------------------------------------------------
# MySQL — opt-in
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not USE_MYSQL, reason="MySQL not configured (set BITMOD_TEST_MYSQL=1)")
class TestMySQLSearchCarriesVersionHash:
    @pytest.fixture(scope="class")
    def backend(self):
        from bitmod.adapters.db_mysql import MySQLBackend
        from sqlalchemy import text

        be = MySQLBackend(os.environ["MYSQL_URL"])
        with be._engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            rows = conn.execute(text("SHOW TABLES")).fetchall()
            for (table,) in rows:
                conn.execute(text(f"DROP TABLE IF EXISTS `{table}`"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        be.initialize()
        return be

    def test_hybrid_search_returns_version_hash(self, backend):
        sid = f"sec-my-{uuid.uuid4().hex[:8]}"
        did = f"doc-my-{uuid.uuid4().hex[:8]}"
        results = _seed_and_search(backend, sid, did, KNOWN_HASH)
        _assert_hash_round_trips(results, sid, KNOWN_HASH)
