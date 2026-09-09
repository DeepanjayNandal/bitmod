"""Namespace, TTL and eviction fields must survive storage.

answer_cache declared namespace_id, max_age_seconds, last_served_at and
estimated_cost on SQLite and on neither of the other two backends. store_answer
passed them, SQLAlchemy dropped the unknown columns silently, and they read back
as None — so tenant isolation, TTL expiry and both eviction strategies were
inert on those backends while the code above them looked correct.

These assert on stored data rather than on adapter code, because inspecting the
adapter is exactly what failed to catch it: the filtering SQL was right, and the
column it filtered on did not exist.

SQLite runs always; PostgreSQL and MySQL are opt-in (see docker-compose.test.yml).
"""

from __future__ import annotations

import os
import tempfile

import pytest
from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.cache_engine import compute_answer_key, normalize_query, store_answer

USE_POSTGRES = os.getenv("BITMOD_TEST_POSTGRES", "0") == "1"
USE_MYSQL = os.getenv("BITMOD_TEST_MYSQL", "0") == "1"

TENANT_A = "tenant-a"
QUESTION = "what is the refund policy"

_BACKEND_IDS = ["sqlite"]
if USE_POSTGRES:
    _BACKEND_IDS.append("postgres")
if USE_MYSQL:
    _BACKEND_IDS.append("mysql")

@pytest.fixture(params=_BACKEND_IDS)
def backend(request):
    kind = request.param
    if kind == "sqlite":
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        be = SQLiteBackend(path)
        be.initialize()
        yield be
        if os.path.exists(path):
            os.unlink(path)
        return

    from sqlalchemy import text

    if kind == "postgres":
        from bitmod.adapters.db_postgresql import PostgreSQLBackend

        be = PostgreSQLBackend(os.environ["DATABASE_URL"])
        with be._engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    else:
        from bitmod.adapters.db_mysql import MySQLBackend

        be = MySQLBackend(os.environ["MYSQL_URL"])
        with be._engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for (table,) in conn.execute(text("SHOW TABLES")).fetchall():
                conn.execute(text(f"DROP TABLE IF EXISTS `{table}`"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    be.initialize()
    yield be


# ---------------------------------------------------------------------------
# Round trip — the check that would have caught this originally
# ---------------------------------------------------------------------------


def test_namespace_survives_a_storage_round_trip(backend):
    """REGRESSION GUARD — assert on stored data, not on adapter code.

    answer_cache.namespace_id was declared on SQLite and on neither of the
    other two. store_answer passed it, SQLAlchemy dropped the unknown column
    silently, and it read back as None: every entry on those backends was
    unscoped while the filtering code above it looked correct. Reading the
    adapter showed a proper WHERE namespace_id = :ns clause — against a column
    that did not exist.

    Inspecting an adapter cannot catch that. Writing a value and reading it
    back can.
    """
    key = compute_answer_key(QUESTION, {}, namespace_id=TENANT_A)
    with backend.session() as session:
        store_answer(
            backend=backend,
            session=session,
            answer_key=key,
            question_raw=QUESTION,
            question_normalized=normalize_query(QUESTION),
            filters={},
            answer_text="scoped answer",
            source_sections=[],
            model_used="test",
            generation_ms=10,
            namespace_id=TENANT_A,
        )

    with backend.session() as session:
        record = backend.cache_lookup(session, key)

    assert record is not None, "entry should be retrievable"
    assert record.namespace_id == TENANT_A, (
        f"namespace was lost in storage: wrote {TENANT_A!r}, read back {record.namespace_id!r}. "
        "Every entry on this backend is unscoped."
    )


def test_ttl_and_eviction_fields_survive_a_storage_round_trip(backend):
    """The same missing-column bug also silently disabled TTL and eviction.

    max_age_seconds drives expiry, last_served_at drives LRU eviction, and
    estimated_cost drives cost-aware eviction. All three were dropped on the
    same two backends, so those features did nothing there.
    """
    key = compute_answer_key("ttl probe", {})
    with backend.session() as session:
        store_answer(
            backend=backend,
            session=session,
            answer_key=key,
            question_raw="ttl probe",
            question_normalized=normalize_query("ttl probe"),
            filters={},
            answer_text="a",
            source_sections=[],
            model_used="test",
            generation_ms=10,
            max_age_seconds=3600,
            estimated_cost=0.0125,
        )

    with backend.session() as session:
        record = backend.cache_lookup(session, key)

    assert record is not None
    assert record.max_age_seconds == 3600, f"TTL lost in storage: read back {record.max_age_seconds!r}"
    assert abs(record.estimated_cost - 0.0125) < 1e-6, (
        f"cost lost in storage: read back {record.estimated_cost!r}"
    )


def test_serving_records_last_served_at(backend):
    """last_served_at is written by cache_increment_serve, not by the insert."""
    key = compute_answer_key("lru probe", {})
    with backend.session() as session:
        store_answer(
            backend=backend,
            session=session,
            answer_key=key,
            question_raw="lru probe",
            question_normalized=normalize_query("lru probe"),
            filters={},
            answer_text="a",
            source_sections=[],
            model_used="test",
            generation_ms=10,
        )
    with backend.session() as session:
        record = backend.cache_lookup(session, key)
        backend.cache_increment_serve(session, record.id)

    with backend.session() as session:
        served = backend.cache_lookup(session, key)

    assert served.serve_count == 1
    assert served.last_served_at is not None, (
        "last_served_at was not persisted — LRU eviction has nothing to sort on"
    )
