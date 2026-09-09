"""Layer 9 — resolving follow-up queries against conversation history.

Layer 9 used to add a flat +0.25 confidence whenever a session had prior turns,
which pushed exactly the context-dependent queries the qualification gate exists
to block. It now rewrites the query instead, so the two are sequential rather
than opposed: resolution repairs what it can, and the gate catches the rest.

Rules only. An LLM rewrite could resolve references into the text of a previous
answer, which these rules cannot, but it would put a model call on the cache
read path — see test_rewriting_costs_no_io.

Backend-parameterised tests drive the real pipeline. SQLite runs always;
PostgreSQL and MySQL are opt-in (see docker-compose.test.yml).
"""

from __future__ import annotations

import inspect
import os
import tempfile

import pytest
from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.cache_engine import compute_answer_key, normalize_query, store_answer
from bitmod.interfaces.llm import LLMProvider, LLMResponse
from bitmod.proxy import BitmodProxy
from bitmod.router import LLMRouter
from bitmod.session import SessionState, resolve_against_history

USE_POSTGRES = os.getenv("BITMOD_TEST_POSTGRES", "0") == "1"
USE_MYSQL = os.getenv("BITMOD_TEST_MYSQL", "0") == "1"

EMBED_DIM = 384  # pgvector columns are Vector(384)

_BACKEND_IDS = ["sqlite"]
if USE_POSTGRES:
    _BACKEND_IDS.append("postgres")
if USE_MYSQL:
    _BACKEND_IDS.append("mysql")


class _StubEmbedder:
    """Identical vector for every input, so cosine similarity is always 1.0."""

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
            question_normalized=normalize_query(question),
            filters={},
            answer_text=answer,
            source_sections=[],
            model_used="test",
            generation_ms=10,
            query_embedding=_StubEmbedder().embed(question),
        )


def _conversation(followup: str) -> list[dict]:
    return [
        {"role": "user", "content": "what is the refund policy"},
        {"role": "assistant", "content": "Refunds take five business days."},
        {"role": "user", "content": followup},
    ]


OPENING = "what is the refund policy"
OPENING_ANSWER = "Refunds take five business days."


def _ask_opening_turn(proxy):
    """Send turn 1 the way a client would, and store its answer.

    This replaces a _prime() helper that seeded the tracker by calling
    get_or_create with the same message list the pipeline was about to use —
    including the follow-up. No client can produce that state: it requires the
    follow-up to have been seen before it was asked. Because the session id was
    derived from every message, that was the only way to make turn_count > 0,
    so the tests passed while the layer could not engage in a real
    conversation.

    Driving the real first turn is the difference between testing that
    resolution works when handed a session and testing that a conversation
    produces one.
    """
    messages = [{"role": "user", "content": OPENING}]
    result = proxy._run_cache_pipeline(OPENING, list(messages))
    proxy._store_response(
        user_message=OPENING,
        answer_text=OPENING_ANSWER,
        model_used="test",
        elapsed_ms=0,
        filters=result.filters or {},
        norm=result.norm,
        answer_key=result.answer_key,
        evidence=result.evidence,
        messages_for_context=list(messages),
    )
    return messages + [{"role": "assistant", "content": OPENING_ANSWER}]


def _followup(proxy, question: str):
    """Turn 1, then turn 2 — the follow-up runs against a session it built."""
    messages = _ask_opening_turn(proxy)
    messages.append({"role": "user", "content": question})
    return proxy._run_cache_pipeline(question, list(messages)), messages


def _actions(result, mechanism: str) -> list[str]:
    return [s["action"] for s in result.trace if s["mechanism"] == mechanism]


# ---------------------------------------------------------------------------
# The rewriter in isolation
# ---------------------------------------------------------------------------


@pytest.fixture
def state():
    s = SessionState(session_id="s1")
    s.record("what is the refund policy", "Refunds take five business days.", "k1")
    return s


@pytest.mark.parametrize(
    "query,expected",
    [
        ("what about electronics?", "refund policy electronics"),
        ("and shipping?", "refund policy shipping"),
        ("how does it work", "refund policy work"),
    ],
)
def test_rewrites_followups_that_introduce_a_subject(state, query, expected):
    """Grafts the previous topic onto whatever new subject the query brings."""
    assert resolve_against_history(query, state) == expected


@pytest.mark.parametrize(
    "query",
    ["tell me more", "go on", "yes", "what about the second one", "why is that", "continue"],
)
def test_declines_to_rewrite_elaboration_requests(state, query):
    """Unrewritable by any means, including an LLM.

    Resolving "tell me more" to the previous question returns the answer the user
    has already been shown — the opposite of what was asked. Declining so the LLM
    generates is the correct outcome, not a shortfall of using rules.
    """
    assert resolve_against_history(query, state) is None


def test_declines_when_no_prior_turn():
    assert resolve_against_history("what about electronics?", SessionState(session_id="empty")) is None


def test_declines_when_query_already_shares_the_topic(state):
    """A query that already names its subject needs no resolution."""
    assert resolve_against_history("what is the refund policy for damaged goods", state) is None


def test_rewriting_costs_no_io(state):
    """Rules only — no database query, no network call, no model call.

    An LLM rewrite would add 200-800ms to every conversational turn against a
    71ms cached-response target, and would make cache reads depend on the model
    provider being reachable. It is also circular: spending a model call to
    decide whether a model call can be avoided.
    """
    assert inspect.iscoroutinefunction(resolve_against_history) is False
    # Signature takes only a query and session state — there is no backend or
    # client to pass, so no I/O is reachable from here.
    params = list(inspect.signature(resolve_against_history).parameters)
    assert params == ["query", "state"]


# ---------------------------------------------------------------------------
# Resolution inside the pipeline
# ---------------------------------------------------------------------------


def test_pipeline_marks_a_resolved_followup(proxy, backend):
    _seed_cached_answer(backend, "refund policy electronics", "Electronics have a 14 day window.")
    result, _ = _followup(proxy, "what about electronics?")
    assert "REWRITTEN" in _actions(result, "session_resolve")


def test_resolved_query_matches_the_entry_cached_under_that_topic(proxy, backend):
    """The whole point of rewriting: the resolved form is what gets matched.

    Resolution runs at the front of the pipeline rather than at layer 9's old
    position, because the rewritten query has to exist before the exact,
    semantic and fuzzy layers run in order to be what they match on.
    """
    _seed_cached_answer(backend, "refund policy electronics", "Electronics have a 14 day window.")
    result, _ = _followup(proxy, "what about electronics?")
    assert result.hit is True
    assert result.answer_text == "Electronics have a 14 day window."


def test_resolved_query_is_not_then_blocked_by_the_gate(proxy, backend):
    """Resolution removed the anaphora, so there is nothing left to guard.

    Checking the original text would block a query we just repaired; checking
    the rewrite would trip the short-query rule instead, since "refund policy
    electronics" is three words. A successful rewrite skips the gate.
    """
    _seed_cached_answer(backend, "refund policy electronics", "Electronics have a 14 day window.")
    result, _ = _followup(proxy, "what about electronics?")
    assert "SKIP_QUALIFIED" not in _actions(result, "exact_cache")


def test_pipeline_marks_an_unresolvable_followup(proxy, backend):
    """Left for the gate to handle, and recorded as such in the trace."""
    _seed_cached_answer(backend, OPENING, OPENING_ANSWER)
    result, _ = _followup(proxy, "tell me more")
    assert "UNRESOLVED" in _actions(result, "session_resolve")


def test_self_contained_query_still_serves(proxy, backend):
    """Resolution must not interfere with a query that needs none."""
    question = "what is the refund policy"
    _seed_cached_answer(backend, question, "Refunds take five business days.")

    result = proxy._run_cache_pipeline(question, [{"role": "user", "content": question}])
    assert result.hit is True
    assert result.answer_text == "Refunds take five business days."


def test_session_context_no_longer_votes_toward_serving(proxy, backend):
    """The prior exchange is context for the LLM, not evidence for a cache hit.

    It used to arrive as +0.25 confidence, which pushed context-dependent
    queries toward being served. It is now carried at 0.0 — still available to
    context_for_llm() on a miss, but contributing nothing to the decision.
    """
    result, _ = _followup(proxy, "tell me more")
    session_evidence = [e for e in result.evidence.evidences if e.layer == "session"]
    assert session_evidence, "the prior exchange should still be recorded as evidence"
    assert all(e.confidence == 0.0 for e in session_evidence), "session context must not vote"
    assert all(e.answer_text for e in session_evidence), "and must still carry text for the LLM"


def test_the_session_id_is_the_same_on_both_turns(proxy):
    """Continuity is the precondition for everything above.

    If the id changes when the follow-up is appended, turn 2 looks up a session
    that has never seen a turn, turn_count stays 0, and resolution is skipped —
    which is exactly what happened while the id was hashed from every message.
    """
    messages = _ask_opening_turn(proxy)
    first = proxy._session_tracker.get_or_create(list(messages)).session_id

    messages.append({"role": "user", "content": "what about electronics?"})
    second = proxy._session_tracker.get_or_create(list(messages)).session_id

    assert first == second, "the session id changed when a turn was appended"
    assert proxy._session_tracker.get_or_create(list(messages)).turn_count > 0, (
        "the opening turn was recorded against a different session than the follow-up reads"
    )


def test_resolution_does_not_leak_across_namespaces(proxy, backend):
    """The same opening question in two tenants must not build one session.

    Session state feeds query resolution and supplies context to the model, so
    sharing it across tenants is a leak rather than a cache miss.
    """
    _seed_cached_answer(backend, "refund policy electronics", "Electronics have a 14 day window.")

    messages = [{"role": "user", "content": OPENING}]
    result = proxy._run_cache_pipeline(OPENING, list(messages), namespace_id="tenant-a")
    proxy._store_response(
        user_message=OPENING,
        answer_text=OPENING_ANSWER,
        model_used="test",
        elapsed_ms=0,
        filters=result.filters or {},
        norm=result.norm,
        answer_key=result.answer_key,
        evidence=result.evidence,
        messages_for_context=list(messages),
        namespace_id="tenant-a",
    )

    messages += [
        {"role": "assistant", "content": OPENING_ANSWER},
        {"role": "user", "content": "what about electronics?"},
    ]
    other = proxy._run_cache_pipeline("what about electronics?", list(messages), namespace_id="tenant-b")

    assert "REWRITTEN" not in _actions(other, "session_resolve"), (
        "tenant B resolved its follow-up against tenant A's conversation"
    )
