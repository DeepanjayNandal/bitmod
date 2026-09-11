"""The qualification gate — which routes it guards, and how it draws the line.

Two separate problems are covered here.

The gate consulted only exact match and composable, never the accumulated
confidence decision, so a query it refused an exact hit could still be served
once several weaker layers summed past the threshold.

Separately, it flagged long specific questions as context-dependent because they
happened to open with an anaphoric phrase. The bound that fixes this counts
substantive words rather than raw ones, for the reason spelled out in
test_raw_word_count_cannot_make_this_call.

Backend-parameterised tests drive the real pipeline. SQLite runs always;
PostgreSQL and MySQL are opt-in (see docker-compose.test.yml).
"""

from __future__ import annotations

import os
import tempfile

import pytest
from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.cache_engine import compute_answer_key, normalize_for_key, store_answer
from bitmod.cache_qualify import is_context_dependent, substantive_words
from bitmod.interfaces.llm import LLMProvider, LLMResponse
from bitmod.proxy import BitmodProxy
from bitmod.router import LLMRouter

USE_POSTGRES = os.getenv("BITMOD_TEST_POSTGRES", "0") == "1"
USE_MYSQL = os.getenv("BITMOD_TEST_MYSQL", "0") == "1"

EMBED_DIM = 384  # pgvector columns are Vector(384)

_BACKEND_IDS = ["sqlite"]
if USE_POSTGRES:
    _BACKEND_IDS.append("postgres")
if USE_MYSQL:
    _BACKEND_IDS.append("mysql")


class _StubEmbedder:
    """Identical vector for every input, so cosine similarity is always 1.0.

    Guarantees the semantic layer produces high-confidence evidence, which the
    accumulated-confidence path needs in order to be exercised at all.
    """

    def embed(self, text: str) -> list[float]:
        return [1.0] + [0.0] * (EMBED_DIM - 1)


class _StubLLM(LLMProvider):
    async def generate(self, messages, model="", tools=None, temperature=0.0, max_tokens=4096):
        return LLMResponse(content="generated answer", model=model or "stub", usage={})

    async def stream(self, messages, model="", temperature=0.0, max_tokens=4096):
        yield "generated answer"


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
def proxy(backend):
    p = BitmodProxy(backend=backend, llm_router=LLMRouter(primary=_StubLLM()), default_model="stub")
    p._embedder = _StubEmbedder()
    return p


def _seed_cached_answer(backend, question: str, answer: str) -> None:
    with backend.session() as session:
        store_answer(
            backend=backend,
            session=session,
            answer_key=compute_answer_key(question, {}),
            question_raw=question,
            question_normalized=normalize_for_key(question),
            filters={},
            answer_text=answer,
            source_sections=[],
            model_used="test",
            generation_ms=10,
            query_embedding=_StubEmbedder().embed(question),
        )


def _actions(result, mechanism: str) -> list[str]:
    return [s["action"] for s in result.trace if s["mechanism"] == mechanism]


# ---------------------------------------------------------------------------
# The hole: accumulated confidence bypassed the gate
# ---------------------------------------------------------------------------


def test_context_dependent_query_cannot_serve_via_accumulated_confidence(proxy, backend):
    """REGRESSION GUARD — the gate has to cover every route out of the pipeline.

    qualify_cache_hit guarded exact match and composable, but not the decision
    that serves once accumulated confidence clears 0.95. So "tell me more" was
    correctly refused an exact hit, then served anyway when layers 4, 6 and 7
    summed past the threshold. Blocking one door is not blocking the room.

    The stub embedder makes every semantic comparison a 1.0 match, so the
    accumulated path is guaranteed to be reached rather than incidentally
    avoided by low confidence.
    """
    _seed_cached_answer(backend, "what is the refund policy", "Refunds take five business days.")

    messages = [
        {"role": "user", "content": "what is the refund policy"},
        {"role": "assistant", "content": "Refunds take five business days."},
        {"role": "user", "content": "tell me more"},
    ]
    state = proxy._session_tracker.get_or_create(messages)
    state.record("what is the refund policy", "Refunds take five business days.", "k1")

    result = proxy._run_cache_pipeline(messages[-1]["content"], messages)

    assert result.hit is False, (
        "REGRESSION: a context-dependent query was served from cache through the "
        "accumulated-confidence path, which did not consult the qualification gate."
    )
    assert "SKIP_QUALIFIED" in _actions(result, "accumulated_serve"), (
        "the gate — not merely insufficient confidence — must be what stopped it"
    )


def test_self_contained_query_is_unaffected(proxy, backend):
    """Guarding the extra route must not block ordinary cache hits."""
    question = "what is the refund policy"
    _seed_cached_answer(backend, question, "Refunds take five business days.")

    result = proxy._run_cache_pipeline(question, [{"role": "user", "content": question}])
    assert result.hit is True
    assert "SKIP_QUALIFIED" not in _actions(result, "accumulated_serve")


# ---------------------------------------------------------------------------
# Where the line falls
# ---------------------------------------------------------------------------

HISTORY = [{"role": "user", "content": "what is the refund policy"}]

STILL_BLOCKED = [
    "tell me more",
    "go on",
    "continue",
    "what about that",
    "explain that",
    "why is that",
    "what do you mean",
    "can you clarify",
    "how does it work",
    "is that still valid",
    "does that cover it",
    "what about the other one",
    "and the second one",
    "summarize this",
    "yes",
    "can you tell me more about that topic?",
]

NO_LONGER_BLOCKED = [
    "How does it work when a customer disputes a charge after 60 days?",
    "Is that regulation about data retention still in force in the EU?",
    "Does that policy cover international shipping for enterprise customers?",
    "Are those exemptions still valid under the 2026 amendment?",
    "Why is that clause included in the enterprise service agreement?",
]


@pytest.mark.parametrize("query", STILL_BLOCKED)
def test_true_positives_are_still_blocked(query):
    """Relaxing the gate must not let genuinely dependent queries through."""
    assert is_context_dependent(query, HISTORY), (
        f"{query!r} depends on the previous turn and must stay blocked "
        f"(substantive words: {substantive_words(query)})"
    )


@pytest.mark.parametrize("query", NO_LONGER_BLOCKED)
def test_specific_long_queries_are_not_blocked(query):
    """A question carrying its own subject is not context-dependent.

    Each of these opens with an anaphoric phrase and was blocked for that alone,
    despite supplying more than enough detail to be matched on its own terms.
    """
    assert not is_context_dependent(query, HISTORY), (
        f"{query!r} is self-contained and should not be blocked "
        f"(substantive words: {substantive_words(query)})"
    )


def test_raw_word_count_cannot_make_this_call():
    """Why the bound counts substantive words instead of raw length.

    Do not "simplify" this back to len(query.split()). These two are one word
    apart in raw length and opposite in classification, so length is inverted
    between them and any raw threshold gets at least one of them wrong.
    """
    dependent = "can you tell me more about that topic?"  # 8 raw words
    standalone = "Does that policy cover international shipping for enterprise customers?"  # 9 raw words

    assert len(dependent.split()) < len(standalone.split()), (
        "premise: the context-dependent query is the *shorter* of the two"
    )
    assert len(substantive_words(dependent)) < len(substantive_words(standalone)), (
        "but it carries fewer substantive words, which is the signal that works"
    )

    assert is_context_dependent(dependent, HISTORY)
    assert not is_context_dependent(standalone, HISTORY)


def test_substantive_words_ignores_stopwords_and_elaboration_markers():
    assert substantive_words("can you tell me more about that topic?") == []
    assert substantive_words("does that policy cover international shipping") == [
        "policy",
        "cover",
        "international",
        "shipping",
    ]
