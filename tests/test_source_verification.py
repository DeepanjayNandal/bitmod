"""Source-version verification across every backend.

Covers the three outcomes double_verify distinguishes, the pipeline behaviour
that depends on them, and a full round trip through the public API.

SQLite runs always. PostgreSQL and MySQL are opt-in:

    make test-db-up

    BITMOD_TEST_POSTGRES=1 \
    DATABASE_URL=postgresql://bitmod:bitmod@localhost:5433/bitmod_test \
    BITMOD_TEST_MYSQL=1 \
    MYSQL_URL=mysql+pymysql://bitmod:bitmod@localhost:3307/bitmod_test \
    pytest tests/test_source_verification.py -v
"""

from __future__ import annotations

import os
import tempfile

import pytest
from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.cache_engine import (
    CacheEvidence,
    PipelineEvidence,
    _similarity_to_confidence,
    compute_answer_key,
    double_verify,
    normalize_for_key,
    semantic_cache_search,
    store_answer,
    try_cache,
)
from bitmod.interfaces.database import DocumentRecord, SectionRecord

USE_POSTGRES = os.getenv("BITMOD_TEST_POSTGRES", "0") == "1"
USE_MYSQL = os.getenv("BITMOD_TEST_MYSQL", "0") == "1"

# Two constraints on this fixture text:
#   - tokens are >= 4 chars, so MySQL InnoDB full-text indexing sees them
#   - QUESTION appears verbatim, because the SQLite FTS branch wraps the query
#     in quotes (db_sqlite.py:488), making it a phrase match rather than AND.
#     A natural multi-word question only retrieves if that phrase is present.
SECTION_TEXT = "How are refunds processed? Refunds are processed within five business days after approval."
SEARCH_TERM = "refunds"
QUESTION = "how are refunds processed"
HASH_V1 = "sha256:version-one"
HASH_V2 = "sha256:version-two"

_BACKEND_IDS = ["sqlite"]
if USE_POSTGRES:
    _BACKEND_IDS.append("postgres")
if USE_MYSQL:
    _BACKEND_IDS.append("mysql")


# pgvector columns are declared Vector(384), so embeddings must be exactly this
# wide. store_answer swallows embedding-write failures, so a wrong-width vector
# is dropped silently and only shows up as an unexplained semantic miss.
EMBED_DIM = 384


class _StubEmbedder:
    """Every text maps to the same vector, so cosine similarity is always 1.0.

    Keeps the semantic test about verification rather than embedding quality.
    """

    def embed(self, text: str) -> list[float]:
        return [1.0] + [0.0] * (EMBED_DIM - 1)


@pytest.fixture(params=_BACKEND_IDS)
def backend(request):
    """A clean backend of each configured kind."""
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


def _seed_section(backend, version_hash: str = HASH_V1) -> None:
    with backend.session() as session:
        backend.store_document(session, DocumentRecord(id="doc-1", source="policy.pdf", title="Policy"))
        backend.store_section(
            session,
            SectionRecord(
                id="sec-1",
                document_id="doc-1",
                text_content=SECTION_TEXT,
                section_title="Refunds",
                citation="Policy 2.1",
                version_hash=version_hash,
            ),
        )


def _cache_answer(backend, sources: list[dict], question: str = QUESTION) -> str:
    key = compute_answer_key(question, {})
    with backend.session() as session:
        store_answer(
            backend=backend,
            session=session,
            answer_key=key,
            question_raw=question,
            question_normalized=normalize_for_key(question),
            filters={},
            answer_text="Five business days.",
            source_sections=sources,
            model_used="test",
            generation_ms=10,
        )
    return key


def _is_valid(backend, answer_key: str) -> bool:
    """Read is_valid straight from storage, bypassing lookup filtering."""
    with backend.session() as session:
        rec = backend.cache_lookup(session, answer_key)
        if rec is not None:
            return True
        # cache_lookup hides invalid rows, so fall back to a direct read.
        return _raw_is_valid(backend, session, answer_key)


def _raw_is_valid(backend, session, answer_key: str) -> bool:
    if isinstance(backend, SQLiteBackend):
        row = session.execute("SELECT is_valid FROM answer_cache WHERE answer_key = ?", (answer_key,)).fetchone()
        return bool(row["is_valid"]) if row else False
    from sqlalchemy import text

    row = session.execute(
        text("SELECT is_valid FROM answer_cache WHERE answer_key = :k"), {"k": answer_key}
    ).fetchone()
    return bool(row[0]) if row else False


# ---------------------------------------------------------------------------
# (a) valid hashes serve normally
# ---------------------------------------------------------------------------


def test_a_valid_hashes_serve(backend):
    _seed_section(backend, HASH_V1)
    key = _cache_answer(backend, [{"section_id": "sec-1", "version_hash": HASH_V1}])

    with backend.session() as session:
        hit = try_cache(backend, session, QUESTION, {})

    assert hit is not None, "entry with a matching hash should serve"
    assert hit.answer_text == "Five business days."
    assert _is_valid(backend, key), "serving must not invalidate a valid entry"


def test_a_repeat_lookups_keep_serving(backend):
    """Serving is repeatable — the entry is not consumed by being read."""
    _seed_section(backend, HASH_V1)
    _cache_answer(backend, [{"section_id": "sec-1", "version_hash": HASH_V1}])

    for attempt in range(3):
        with backend.session() as session:
            hit = try_cache(backend, session, QUESTION, {})
        assert hit is not None, f"lookup {attempt + 1} should still hit"


# ---------------------------------------------------------------------------
# (b) changed source is invalidated and not served
# ---------------------------------------------------------------------------


def test_b_changed_source_is_invalidated(backend):
    _seed_section(backend, HASH_V1)
    key = _cache_answer(backend, [{"section_id": "sec-1", "version_hash": HASH_V1}])

    # The document changes underneath the cached answer.
    with backend.session() as session:
        backend.update_section_content(
            session,
            "sec-1",
            "Refunds are processed within ten business days.",
            HASH_V2,
        )

    with backend.session() as session:
        hit = try_cache(backend, session, QUESTION, {})

    assert hit is None, "an answer whose source changed must not be served"
    assert not _is_valid(backend, key), "a genuinely stale entry SHOULD be invalidated"


# ---------------------------------------------------------------------------
# (c) missing hash is not served and NOT invalidated  <-- the original bug
# ---------------------------------------------------------------------------


def test_c_missing_hash_is_not_served_and_not_invalidated(backend):
    """REGRESSION GUARD — do not delete, and do not "simplify" into test (b).

    The bug: double_verify required a version_hash that no write path set.
    A missing hash took the same branch as a genuinely changed document, so it
    called cache_invalidate. Every document-grounded answer was destroyed on
    its first lookup and the cache was write-only on that path.

    Missing evidence is not evidence of staleness. The two assertions below are
    a matched pair and only mean something together:

      - not served      -> we refuse to serve what we could not verify
      - still is_valid  -> we do NOT destroy a row merely because we could not
                           check it

    Dropping the second assertion reintroduces the original bug while the test
    keeps passing.
    """
    _seed_section(backend, HASH_V1)
    # Exactly the shape the writers produced before the fix: no version_hash.
    key = _cache_answer(backend, [{"section_id": "sec-1", "citation": "Policy 2.1", "score": 0.9}])

    with backend.session() as session:
        hit = try_cache(backend, session, QUESTION, {})

    assert hit is None, "an unverifiable entry must not be served"
    assert _is_valid(backend, key), (
        "REGRESSION: an unverifiable entry was invalidated. Missing hash means "
        "'could not check', not 'known stale' — the row must survive."
    )


def test_c_unverifiable_entry_survives_repeated_lookups(backend):
    """The row must still be intact after several failed lookups, not decay."""
    _seed_section(backend, HASH_V1)
    key = _cache_answer(backend, [{"section_id": "sec-1", "citation": "c", "score": 0.5}])

    for _ in range(3):
        with backend.session() as session:
            assert try_cache(backend, session, QUESTION, {}) is None

    assert _is_valid(backend, key), "repeated lookups must not erode an unverifiable entry"


# ---------------------------------------------------------------------------
# (d) a semantic hit on a stale entry is not served
# ---------------------------------------------------------------------------


def test_d_semantic_hit_on_stale_entry_is_not_served(backend):
    """Semantic candidates are verified at collection, before entering evidence.

    Layer 7 seeds link traversal from evidence.evidences, so a stale candidate
    that reaches the evidence list gets walked for links even when it is never
    served itself. Verification therefore has to happen before the add.
    """
    if not hasattr(backend, "cache_store_embedding"):
        pytest.skip("backend does not support cache embeddings")

    _seed_section(backend, HASH_V1)
    embedder = _StubEmbedder()

    question = QUESTION
    key = compute_answer_key(question, {})
    with backend.session() as session:
        store_answer(
            backend=backend,
            session=session,
            answer_key=key,
            question_raw=question,
            question_normalized=normalize_for_key(question),
            filters={},
            answer_text="Five business days.",
            source_sections=[{"section_id": "sec-1", "version_hash": HASH_V1}],
            model_used="test",
            generation_ms=10,
            query_embedding=embedder.embed(question),
        )

    # Source changes -> the cached answer is now stale.
    with backend.session() as session:
        backend.update_section_content(
            session,
            "sec-1",
            "Refunds now take ten business days.",
            HASH_V2,
        )

    with backend.session() as session:
        matches = semantic_cache_search(
            backend, session, "how long do refunds take", {}, embedder, threshold=0.5, max_results=3
        )
        assert matches, "precondition: semantic search must actually find the stale entry"

        # Mirror the pipeline: verify before adding to evidence.
        evidence = PipelineEvidence()
        memo: dict = {}
        for match in matches:
            if not double_verify(backend, session, match.record, hash_cache=memo):
                continue
            evidence.add(
                CacheEvidence(
                    layer="semantic",
                    confidence=_similarity_to_confidence(match.similarity, "semantic"),
                    answer_text=match.record.answer_text,
                    record_id=match.record.id,
                    similarity=match.similarity,
                )
            )

    assert evidence.total_confidence == 0.0, "a stale semantic candidate must contribute no confidence"
    seeds = [e.record_id for e in evidence.evidences if e.layer == "semantic" and e.record_id]
    assert seeds == [], "a stale candidate must not reach the layer 7 traversal seed set"


# ---------------------------------------------------------------------------
# (e) end to end through the public API
# ---------------------------------------------------------------------------


def test_e_api_query_caches_then_hits(backend, monkeypatch):
    """A full round trip through Bitmod.query — the path that was write-only.

    Exercises api.py's own source_sections builder rather than a copy of it.
    """
    from bitmod.api import Bitmod

    bm = Bitmod()
    bm._backend = backend
    bm._embedder = None

    monkeypatch.setattr(
        Bitmod,
        "_generate_answer",
        lambda self, question, context, **kw: ("Five business days.", "stub-model"),
    )

    _seed_section(backend, HASH_V1)

    first = bm.query(QUESTION)
    assert first.cached is False, "first call should miss and generate"
    assert first.sources, "the answer must record which sections it came from"
    assert all("version_hash" in s for s in first.sources), (
        "every source entry needs a version_hash, otherwise the entry it just "
        "cached is unverifiable and can never be served back"
    )

    second = bm.query(QUESTION)
    assert second.cached is True, (
        "REGRESSION: the entry cached by the first call was not served back. "
        "This is the write-only cache bug."
    )
    assert second.answer == first.answer
