"""Full-text search recall, and the escaping that has to survive it.

SQLite wrapped the whole query in quotes to escape FTS5 operators, which also
made every search a phrase match. Recall on natural questions was 0 out of 4,
so the BM25 half of hybrid search contributed nothing and all retrieval came
from the vector branch.

The three backends also disagreed on what searching meant: SQLite matched a
phrase, PostgreSQL ANDed every term, MySQL ORed them with relevance ranking.
Same corpus, same question, three different answers behind one interface.

Backend-parameterised tests run real SQL. SQLite runs always; PostgreSQL and
MySQL are opt-in (see docker-compose.test.yml).
"""

from __future__ import annotations

import os
import tempfile

import pytest
from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.interfaces.database import DocumentRecord, SectionRecord

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
# Recall
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("question,expected", QUESTIONS)
def test_multi_word_questions_retrieve(corpus, question, expected):
    """REGRESSION GUARD — do not restore whole-query quoting.

    SQLite wrapped the entire query in quotes to escape FTS5 operators, which
    also made it a phrase match: a question retrieved only if the document
    repeated it verbatim. Recall on questions like these was 0 out of 4, which
    left the BM25 half of hybrid search contributing nothing and all retrieval
    coming from the vector branch.

    The escaping still has to happen — see test_fts_operators_are_escaped — but
    per token, not around the whole query.
    """
    with corpus.session() as session:
        ids = [r.section_id for r in corpus.hybrid_search(session, question, limit=5)]
    assert expected in ids, f"{question!r} should retrieve {expected}, got {ids}"


def test_unrelated_question_does_not_rank_first(corpus):
    """OR semantics widen recall, so ranking has to carry precision."""
    with corpus.session() as session:
        ids = [r.section_id for r in corpus.hybrid_search(session, "cancel my subscription plan", limit=3)]
    assert ids and ids[0] == "sec-3"


@pytest.mark.parametrize(
    "malicious",
    [
        'refund" OR 1=1 --',
        "policy AND NOT shipping",
        '"unbalanced quote',
        "refund*",
        "col:value ^anchor",
        "NEAR(a b, 3)",
        "((()))",
        "; DROP TABLE sections; --",
    ],
)
def test_fts_operators_are_escaped(corpus, malicious):
    """The reason the quoting existed. Removing it entirely would be a hole.

    FTS5 and tsquery both have operator syntax that a raw user question can
    trip: unbalanced quotes are a syntax error, and AND/OR/NOT/NEAR/*/:/^ change
    the query's meaning. Each token is quoted individually so operators are
    matched as literal text rather than parsed.
    """
    with corpus.session() as session:
        corpus.hybrid_search(session, malicious, limit=3)  # must not raise
    with corpus.session() as session:
        remaining = len(corpus.hybrid_search(session, "shipping costs", limit=5))
    assert remaining > 0, "corpus should be intact and still searchable"


def test_all_backends_agree_on_recall(corpus):
    """The interface promises identical behaviour; three engines have to deliver it."""
    with corpus.session() as session:
        hits = sum(
            1 for q, exp in QUESTIONS if exp in [r.section_id for r in corpus.hybrid_search(session, q, limit=5)]
        )
    assert hits == len(QUESTIONS), f"recall {hits}/{len(QUESTIONS)} — backends have diverged again"
