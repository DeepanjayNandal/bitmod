"""The conversation_id column, across every backend that can be started.

    docker compose -f docker-compose.test.yml up -d

    BITMOD_TEST_POSTGRES=1 DATABASE_URL=postgresql://bitmod:bitmod@localhost:5433/bitmod_test \
    BITMOD_TEST_MYSQL=1    MYSQL_URL=mysql+pymysql://bitmod:bitmod@localhost:3307/bitmod_test \
    BITMOD_TEST_MONGO=1    MONGO_URL=mongodb://localhost:27018/bitmod_test \
    pytest tests/test_conversation_id_column.py -q

The column is for retrieval scoping only and must never enter
compute_answer_key — see AnswerCacheRecord.conversation_id. One test here
asserts exactly that, because the constraint is the kind a later change breaks
by analogy with namespace_id.

Round trips through a real engine rather than a mock: 234d23c is what happens
when a backend's only tests mock the driver.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from bitmod.cache_engine import compute_answer_key
from bitmod.interfaces.database import AnswerCacheRecord

USE_POSTGRES = os.getenv("BITMOD_TEST_POSTGRES", "0") == "1"
USE_MYSQL = os.getenv("BITMOD_TEST_MYSQL", "0") == "1"
USE_MONGO = os.getenv("BITMOD_TEST_MONGO", "0") == "1"

_BACKEND_IDS = ["sqlite"]
if USE_POSTGRES:
    _BACKEND_IDS.append("postgres")
if USE_MYSQL:
    _BACKEND_IDS.append("mysql")
if USE_MONGO:
    _BACKEND_IDS.append("mongo")


@pytest.fixture(params=_BACKEND_IDS)
def backend(request):
    kind = request.param
    if kind == "sqlite":
        from bitmod.adapters.db_sqlite import SQLiteBackend

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        be = SQLiteBackend(path)
        be.initialize()
        yield be
        if os.path.exists(path):
            os.unlink(path)
        return

    if kind == "mongo":
        from bitmod.adapters.db_mongodb import MongoDBBackend

        be = MongoDBBackend(os.environ.get("MONGO_URL", "mongodb://localhost:27018/bitmod_test"))
        be.initialize()
        with be.session() as session:
            session.answer_cache.delete_many({})
            session.cache_embeddings.delete_many({})
        yield be
        with be.session() as session:
            session.answer_cache.delete_many({})
            session.cache_embeddings.delete_many({})
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


def _fresh_instance(kind: str, existing):
    """A second backend object pointing at the same database, as a restart would."""
    if kind == "sqlite":
        from bitmod.adapters.db_sqlite import SQLiteBackend

        return SQLiteBackend(existing._path)
    if kind == "mongo":
        from bitmod.adapters.db_mongodb import MongoDBBackend

        return MongoDBBackend(os.environ.get("MONGO_URL", "mongodb://localhost:27018/bitmod_test"))
    if kind == "postgres":
        from bitmod.adapters.db_postgresql import PostgreSQLBackend

        return PostgreSQLBackend(os.environ["DATABASE_URL"])
    from bitmod.adapters.db_mysql import MySQLBackend

    return MySQLBackend(os.environ["MYSQL_URL"])


def _record(**kw) -> AnswerCacheRecord:
    base = {
        "answer_key": "k-" + kw.get("id", "x"),
        "question_raw": "where was he born",
        "question_normalized": "where born",
        "answer_text": "In Boston, Massachusetts.",
        "model_used": "test-model",
    }
    base.update(kw)
    return AnswerCacheRecord(**base)


def test_conversation_id_round_trips(backend):
    """Written and read back. On SQLite this also proves the positional INSERT
    is aligned: the column list and the value tuple at db_sqlite.py are matched
    by order, and adding a column to one and not the other is silent only if
    the counts happen to agree."""
    with backend.session() as session:
        backend.cache_store(session, _record(id="c1", conversation_id="conv-42"))
        got = backend.cache_lookup_by_id(session, "c1")

    assert got is not None
    assert got.conversation_id == "conv-42"
    # The neighbouring positional values must not have shifted.
    assert got.answer_text == "In Boston, Massachusetts."
    assert got.question_raw == "where was he born"
    assert got.model_used == "test-model"


def test_absent_conversation_id_reads_back_as_none(backend):
    """Entries written before this column existed have no conversation.

    None means "we do not know which conversation wrote this", and the
    retrieval filter treats it as a MATCH — excluding on absence of evidence
    would make the whole pre-upgrade cache unreachable via semantic in one
    deploy. The filter's behaviour is asserted where the filter lives; this
    asserts the precondition it rests on.
    """
    with backend.session() as session:
        backend.cache_store(session, _record(id="c2"))
        got = backend.cache_lookup_by_id(session, "c2")

    assert got is not None
    assert got.conversation_id is None


def test_conversation_id_never_enters_the_answer_key():
    """The constraint a later change breaks by analogy with namespace_id.

    namespace_id and project_id are named parameters of compute_answer_key and
    do change the key. conversation_id is deliberately not, because keying on it
    would fragment the exact path per conversation — the filters["_context"]
    behaviour this work exists to stop relying on.
    """
    base = compute_answer_key("where was he born", {"_context": "abc123"})
    # Same query, same filters, and a conversation is nowhere in the signature.
    assert compute_answer_key("where was he born", {"_context": "abc123"}) == base
    # namespace_id DOES change it — the contrast is the point.
    assert compute_answer_key("where was he born", {"_context": "abc123"}, namespace_id="t1") != base
    # And conversation_id is not a parameter at all: passing it would raise.
    with pytest.raises(TypeError):
        compute_answer_key("where was he born", {"_context": "abc123"}, conversation_id="conv-42")  # type: ignore[call-arg]


def test_upgrade_block_is_safe_on_a_database_that_already_has_the_column(backend, request):
    """A FRESH backend instance against the same database — what a restart does.

    Do NOT simplify this to calling backend.initialize() twice. That form fails
    on PostgreSQL and MySQL for an unrelated, pre-existing reason: every Table()
    re-declares into the same MetaData and SQLAlchemy raises
    InvalidRequestError on `documents`, the first table declared, before
    answer_cache is reached. See HANDOFF §4 item 22. SQLite is unaffected
    because it uses raw CREATE TABLE IF NOT EXISTS rather than a registry.

    What matters here is the second process, not the second call: the upgrade
    blocks ALTER a table that already exists, so they must tolerate the column
    already being there. Postgres uses ADD COLUMN IF NOT EXISTS, MySQL 8.4
    rejects that syntax (error 1064) and uses try/except against error 1060,
    SQLite swallows the duplicate-column error.
    """
    kind = request.node.callspec.params["backend"]
    with backend.session() as session:
        backend.cache_store(session, _record(id="c3", conversation_id="conv-9"))

    second = _fresh_instance(kind, backend)
    second.initialize()  # must not raise against a database that already has the column

    with second.session() as session:
        got = second.cache_lookup_by_id(session, "c3")
    assert got is not None, "the row written before the second initialize() must survive it"
    assert got.conversation_id == "conv-9"
