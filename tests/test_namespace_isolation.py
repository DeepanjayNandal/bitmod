"""Tenant isolation, including on the error paths that used to drop it.

Semantic search scoped queries to a namespace by passing namespace_id down to
the backend. Two `except TypeError` handlers then retried the same call
*without* it, so a backend that could not scope produced results from every
tenant instead of none. The guard inside semantic_cache_search is
`if namespace_id and ...`, so passing None disabled the one filter that would
have caught it — the exception handler silently became a cross-tenant read.

These tests force that handler rather than assuming it is unreachable, because
"unreachable" is what it looked like: cache_get_embeddings is not on the
DatabaseBackend interface, so nothing prevents a backend from lacking the
parameter.

Backend-parameterised tests run real SQL. SQLite runs always; PostgreSQL and
MySQL are opt-in (see docker-compose.test.yml).
"""

from __future__ import annotations

import os
import tempfile

import pytest
from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.cache_engine import (
    compute_answer_key,
    normalize_query,
    semantic_cache_match,
    semantic_cache_search,
    store_answer,
)

USE_POSTGRES = os.getenv("BITMOD_TEST_POSTGRES", "0") == "1"
USE_MYSQL = os.getenv("BITMOD_TEST_MYSQL", "0") == "1"

EMBED_DIM = 384
TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
QUESTION = "what is the refund policy"

_BACKEND_IDS = ["sqlite"]
if USE_POSTGRES:
    _BACKEND_IDS.append("postgres")
if USE_MYSQL:
    _BACKEND_IDS.append("mysql")


class _StubEmbedder:
    """Identical vector for every input, so everything matches everything.

    Deliberately maximal: if isolation depends on embeddings being dissimilar,
    it is not isolation. Only the namespace filter should keep tenants apart.
    """

    def embed(self, text: str) -> list[float]:
        return [1.0] + [0.0] * (EMBED_DIM - 1)


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


@pytest.fixture
def two_tenants(backend):
    """One cached answer per tenant, both semantically identical."""
    embedder = _StubEmbedder()
    for tenant, answer in ((TENANT_A, "Tenant A: refunds in 5 days."), (TENANT_B, "Tenant B: refunds in 30 days.")):
        with backend.session() as session:
            store_answer(
                backend=backend,
                session=session,
                answer_key=compute_answer_key(QUESTION, {}, namespace_id=tenant),
                question_raw=QUESTION,
                question_normalized=normalize_query(QUESTION),
                filters={},
                answer_text=answer,
                source_sections=[],
                model_used="test",
                generation_ms=10,
                query_embedding=embedder.embed(QUESTION),
                namespace_id=tenant,
            )
    return backend, embedder


class _NoNamespaceBackend:
    """Wraps a backend whose cache_get_embeddings predates namespace scoping.

    Mirrors a third-party backend implementing the documented interface but not
    the extra keyword — the exact situation the removed fallback existed for.
    Everything else delegates.
    """

    def __init__(self, inner):
        self._inner = inner

    def cache_get_embeddings(self, session, limit=2000):  # no namespace_id
        return self._inner.cache_get_embeddings(session, limit=limit)

    def __getattr__(self, name):
        return getattr(self._inner, name)


# ---------------------------------------------------------------------------
# Normal path
# ---------------------------------------------------------------------------


def test_semantic_search_does_not_cross_tenants(two_tenants):
    backend, embedder = two_tenants
    with backend.session() as session:
        matches = semantic_cache_search(
            backend, session, QUESTION, {}, embedder, threshold=0.5, max_results=10, namespace_id=TENANT_A
        )
    assert matches, "tenant A should still find its own entry"
    assert all(m.record.namespace_id == TENANT_A for m in matches), (
        f"leaked across tenants: {[m.record.namespace_id for m in matches]}"
    )


def test_semantic_match_does_not_cross_tenants(two_tenants):
    backend, embedder = two_tenants
    with backend.session() as session:
        hit = semantic_cache_match(backend, session, QUESTION, {}, embedder, threshold=0.5, namespace_id=TENANT_A)
    assert hit is not None
    assert hit.namespace_id == TENANT_A
    assert "Tenant B" not in hit.answer_text


# ---------------------------------------------------------------------------
# The fallback path, forced
# ---------------------------------------------------------------------------


def test_search_fails_closed_when_backend_cannot_scope(two_tenants):
    """REGRESSION GUARD — must return nothing, not everything.

    A backend that cannot filter by namespace used to be handled by retrying
    the search unscoped, which returned both tenants' answers. Refusing to
    search is the only safe response: a miss costs a generation, a cross-tenant
    hit costs trust.
    """
    backend, embedder = two_tenants
    unscoped = _NoNamespaceBackend(backend)

    with pytest.raises(TypeError):
        with backend.session() as session:
            unscoped.cache_get_embeddings(session, limit=10, namespace_id=TENANT_A)

    with backend.session() as session:
        matches = semantic_cache_search(
            unscoped, session, QUESTION, {}, embedder, threshold=0.5, max_results=10, namespace_id=TENANT_A
        )
    assert matches == [], f"searched unscoped instead of failing closed: {matches}"


def test_match_fails_closed_when_backend_cannot_scope(two_tenants):
    """Same guarantee for the single-match variant.

    This one had no namespace post-filter at all, so the fallback had nothing
    standing between it and another tenant's answer.
    """
    backend, embedder = two_tenants
    unscoped = _NoNamespaceBackend(backend)

    with backend.session() as session:
        hit = semantic_cache_match(unscoped, session, QUESTION, {}, embedder, threshold=0.5, namespace_id=TENANT_A)
    assert hit is None, f"served a match from an unscoped search: {hit.namespace_id if hit else None}"


def test_unscoped_backend_still_works_for_single_tenant(two_tenants):
    """Failing closed must not break deployments that use no namespaces.

    With no namespace requested there is no boundary to cross, so the
    compatibility path still runs and the backend remains usable.
    """
    backend, embedder = two_tenants
    unscoped = _NoNamespaceBackend(backend)

    with backend.session() as session:
        matches = semantic_cache_search(
            unscoped, session, QUESTION, {}, embedder, threshold=0.5, max_results=10, namespace_id=None
        )
    assert matches, "a single-tenant deployment should still get results"


# ---------------------------------------------------------------------------
# Defence in depth
# ---------------------------------------------------------------------------


def test_match_rechecks_namespace_on_the_resolved_record(two_tenants, monkeypatch):
    """Do not trust the backend to have filtered.

    Even if a backend returns an out-of-namespace candidate — through a bug, a
    stale index, or a filter that silently did nothing — the resolved record is
    re-checked before it is served.
    """
    backend, embedder = two_tenants

    with backend.session() as session:
        b_key = compute_answer_key(QUESTION, {}, namespace_id=TENANT_B)
        b_record = backend.cache_lookup(session, b_key)
    assert b_record is not None and b_record.namespace_id == TENANT_B

    # Force resolution to tenant B's row while tenant A is the one asking.
    monkeypatch.setattr(type(backend), "cache_lookup_by_id", lambda self, session, cache_id: b_record)

    with backend.session() as session:
        hit = semantic_cache_match(backend, session, QUESTION, {}, embedder, threshold=0.5, namespace_id=TENANT_A)
    assert hit is None, "served tenant B's answer to tenant A despite the namespace mismatch"
