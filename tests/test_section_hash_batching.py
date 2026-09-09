"""Batched section-hash lookups.

double_verify needs one hash per source section, so verifying several candidates
issued a query per section per candidate. A per-request memo collapses that only
when candidates cite the same documents; when they cite different ones it gives
no benefit at all, which is why batching was worth adding on top of it.

Backend-parameterised tests run real SQL. SQLite runs always; PostgreSQL and
MySQL are opt-in (see docker-compose.test.yml).
"""

from __future__ import annotations

import os
import tempfile

import pytest
from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.cache_engine import double_verify
from bitmod.interfaces.database import AnswerCacheRecord, DocumentRecord, SectionRecord

USE_POSTGRES = os.getenv("BITMOD_TEST_POSTGRES", "0") == "1"
USE_MYSQL = os.getenv("BITMOD_TEST_MYSQL", "0") == "1"

_BACKEND_IDS = ["sqlite"]
if USE_POSTGRES:
    _BACKEND_IDS.append("postgres")
if USE_MYSQL:
    _BACKEND_IDS.append("mysql")

CORPUS = [
    (
        "sec-1",
        "Refunds are processed within five business days after approval. Electronics carry a 14 day return window.",
    ),
    ("sec-2", "Shipping costs are calculated by weight and destination. International shipping takes 7-10 days."),
    (
        "sec-3",
        "To cancel a subscription, open account settings and select cancel plan. Cancellation is immediate.",
    ),
]

# Realistic questions: none appears verbatim in the corpus, and each carries
# words the target document does not contain ("what", "how", "my").
QUESTIONS = [
    ("what is the refund policy for electronics", "sec-1"),
    ("how long does international shipping take", "sec-2"),
    ("how do i cancel my subscription", "sec-3"),
    ("shipping costs", "sec-2"),
]


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
def corpus(backend):
    with backend.session() as session:
        backend.store_document(session, DocumentRecord(id="d1", source="kb.md", title="KB"))
        for sid, txt in CORPUS:
            backend.store_section(
                session,
                SectionRecord(id=sid, document_id="d1", text_content=txt, section_title=sid, version_hash=f"H-{sid}"),
            )
    return backend


# ---------------------------------------------------------------------------
# Batched section-hash lookups
# ---------------------------------------------------------------------------


def test_batch_hash_lookup_returns_only_existing_ids(corpus):
    with corpus.session() as session:
        got = corpus.get_section_version_hashes(session, ["sec-1", "sec-3", "does-not-exist"])
    assert got == {"sec-1": "H-sec-1", "sec-3": "H-sec-3"}


def test_batch_hash_lookup_handles_empty_input(corpus):
    with corpus.session() as session:
        assert corpus.get_section_version_hashes(session, []) == {}


def _count_queries(backend_cls, monkeypatch):
    counts = {"single": 0, "batch": 0}
    single, batch = backend_cls.get_section_version_hash, backend_cls.get_section_version_hashes

    def c_single(self, session, sid):
        counts["single"] += 1
        return single(self, session, sid)

    def c_batch(self, session, ids):
        counts["batch"] += 1
        return batch(self, session, ids)

    monkeypatch.setattr(backend_cls, "get_section_version_hash", c_single)
    monkeypatch.setattr(backend_cls, "get_section_version_hashes", c_batch)
    return counts


def _verify_candidates(backend, section_ids_per_candidate):
    records = [
        AnswerCacheRecord(
            id=f"c{i}",
            answer_key=f"k{i}",
            answer_text="a",
            source_sections=[{"section_id": sid, "version_hash": f"H-{sid}"} for sid in ids],
        )
        for i, ids in enumerate(section_ids_per_candidate)
    ]
    memo: dict = {}
    with backend.session() as session:
        return [double_verify(backend, session, r, hash_cache=memo) for r in records]


def test_verification_is_one_query_per_candidate_not_one_per_section(corpus, monkeypatch):
    """The memo and the batch cover different cases; neither subsumes the other.

    A memo alone collapses candidates that cite the same documents and does
    nothing for candidates that cite different ones — 40 queries stayed 40.
    Batching bounds the disjoint case at one query per candidate.
    """
    counts = _count_queries(type(corpus), monkeypatch)
    disjoint = [["sec-1"], ["sec-2"], ["sec-3"]]
    assert all(_verify_candidates(corpus, disjoint))

    assert counts["single"] == 0, "verification should not fall back to single-row lookups"
    assert counts["batch"] == len(disjoint), f"expected one batch query per candidate, got {counts['batch']}"


def test_memo_still_collapses_candidates_sharing_sections(corpus, monkeypatch):
    """Overlapping candidates should need a single query in total."""
    counts = _count_queries(type(corpus), monkeypatch)
    shared = [["sec-1", "sec-2"], ["sec-1", "sec-2"], ["sec-1", "sec-2"]]
    assert all(_verify_candidates(corpus, shared))

    assert counts["batch"] == 1, (
        f"the memo should satisfy every candidate after the first, got {counts['batch']} queries"
    )


def test_batching_preserves_verification_outcomes(corpus):
    """Fewer queries must not mean weaker checking."""
    with corpus.session() as session:
        valid = AnswerCacheRecord(
            id="ok",
            answer_key="ok",
            answer_text="a",
            source_sections=[{"section_id": "sec-1", "version_hash": "H-sec-1"}],
        )
        stale = AnswerCacheRecord(
            id="stale",
            answer_key="stale",
            answer_text="a",
            source_sections=[{"section_id": "sec-1", "version_hash": "OLD"}],
        )
        unverifiable = AnswerCacheRecord(
            id="unver",
            answer_key="unver",
            answer_text="a",
            source_sections=[{"section_id": "sec-1"}],
        )
        for rec in (valid, stale, unverifiable):
            corpus.cache_store(session, rec)

        assert double_verify(corpus, session, valid, hash_cache={}) is True
        assert double_verify(corpus, session, stale, hash_cache={}) is False
        assert double_verify(corpus, session, unverifiable, hash_cache={}) is False
