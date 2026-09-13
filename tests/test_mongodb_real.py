"""Mongo adapter against a real engine, not a mocked driver.

    docker compose -f docker-compose.test.yml up -d test-mongo

    BITMOD_TEST_MONGO=1 \
    MONGO_URL=mongodb://localhost:27018/bitmod_test \
    pytest tests/test_mongodb_real.py -q

WHY THIS EXISTS. The adapter's other tests patch pymongo wholesale
(tests/test_adapters_expanded.py:862) and passed 8/8 against a version of
cache_store that never wrote namespace_id, max_age_seconds, last_served_at or
estimated_cost. A mock accepts any query shape and returns what it is told, so
it cannot detect a field that is never written. That is how those four survived
7a16597, which fixed them on PostgreSQL and MySQL.

Every test here is a round trip through a real mongod: write a record, read it
back, assert the field survived.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from bitmod.interfaces.database import AnswerCacheRecord

USE_MONGO = os.getenv("BITMOD_TEST_MONGO", "0") == "1"
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27018/bitmod_test")

pytestmark = pytest.mark.skipif(not USE_MONGO, reason="BITMOD_TEST_MONGO=1 and a running mongod required")


@pytest.fixture
def backend():
    from bitmod.adapters.db_mongodb import MongoDBBackend

    be = MongoDBBackend(MONGO_URL)
    be.initialize()
    with be.session() as session:
        session.answer_cache.delete_many({})
        session.cache_embeddings.delete_many({})
    yield be
    with be.session() as session:
        session.answer_cache.delete_many({})
        session.cache_embeddings.delete_many({})


def _record(**kw) -> AnswerCacheRecord:
    base = {
        "answer_key": "k-" + kw.get("id", "x"),
        "question_raw": "what is the refund policy",
        "question_normalized": "refund policy",
        "answer_text": "Refunds take five business days.",
        "model_used": "test-model",
    }
    base.update(kw)
    return AnswerCacheRecord(**base)


def test_every_record_field_survives_a_round_trip(backend):
    """The assertion the mocked suite cannot make: it went in, it came back.

    Named fields rather than a loop, so a failure says which one was dropped.
    """
    rec = _record(
        id="rt1",
        namespace_id="tenant-a",
        max_age_seconds=3600,
        last_served_at=datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc),
        estimated_cost=0.0042,
        confidence=0.87,
    )
    with backend.session() as session:
        backend.cache_store(session, rec)
        got = backend.cache_lookup_by_id(session, "rt1")

    assert got is not None
    assert got.namespace_id == "tenant-a"
    assert got.max_age_seconds == 3600
    assert got.last_served_at is not None
    assert got.estimated_cost == pytest.approx(0.0042)
    assert got.created_at is not None, "written by cache_store and previously dropped on read"
    assert got.confidence == pytest.approx(0.87)
    assert got.answer_text == "Refunds take five business days."


def test_invalidation_fields_survive_a_round_trip(backend):
    """cache_invalidate writes these via $set; the read path used to drop them."""
    with backend.session() as session:
        backend.cache_store(session, _record(id="inv1"))
        backend.cache_invalidate(session, "inv1", "source changed")
        doc = session.answer_cache.find_one({"id": "inv1"})
        got = backend._doc_to_cache(doc)

    assert got.is_valid is False
    assert got.invalidated_at is not None
    assert got.invalidation_reason == "source changed"


def test_namespaced_embedding_scan_returns_the_right_tenant(backend):
    """The defect the probe measured: $match on cache.namespace_id against a
    field that was never written matched nothing, so every namespaced semantic
    lookup returned zero candidates. Single-tenant deployments were unaffected,
    which is why it survived."""
    with backend.session() as session:
        for cid, ns in (("a1", "tenant-a"), ("a2", "tenant-a"), ("b1", "tenant-b")):
            backend.cache_store(session, _record(id=cid, answer_key=f"k-{cid}", namespace_id=ns))
            backend.cache_store_embedding(session, cid, [0.1, 0.2, 0.3])

        unscoped = backend.cache_get_embeddings(session, limit=100)
        tenant_a = backend.cache_get_embeddings(session, limit=100, namespace_id="tenant-a")
        tenant_b = backend.cache_get_embeddings(session, limit=100, namespace_id="tenant-b")

    assert len(unscoped) == 3
    assert sorted(cid for cid, _ in tenant_a) == ["a1", "a2"]
    assert sorted(cid for cid, _ in tenant_b) == ["b1"]


def test_initialize_is_idempotent(backend):
    """It runs on the startup path, so running it twice must not raise."""
    backend.initialize()
    backend.initialize()
    with backend.session() as session:
        backend.cache_store(session, _record(id="idem1"))
        assert backend.cache_lookup_by_id(session, "idem1") is not None
