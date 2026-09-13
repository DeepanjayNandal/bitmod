"""Conversation scoping on the semantic layer.

The semantic layer accepted `filters` and never read it, so it retrieved across
every conversation: 185 of 187 measured cross-conversation serves came through
it (tests/benchmark/results/semantic_scoping_classification.json). These tests
cover the filter that closes that, including the case the benchmark structurally
cannot see.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.cache_engine import _other_conversation, semantic_cache_search
from bitmod.interfaces.database import AnswerCacheRecord

EMBED_DIM = 8


class _StubEmbedder:
    """Identical vector for every input, so cosine similarity is always 1.0.

    Similarity is not what is under test here — which candidates survive the
    conversation filter is.
    """

    def embed(self, text: str) -> list[float]:
        return [1.0] + [0.0] * (EMBED_DIM - 1)


@pytest.fixture
def backend():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    be = SQLiteBackend(path)
    be.initialize()
    yield be
    if os.path.exists(path):
        os.unlink(path)


def _seed(backend, cache_id: str, conversation_id: str | None) -> None:
    rec = AnswerCacheRecord(
        id=cache_id,
        answer_key=f"key-{cache_id}",
        question_raw="where was he born",
        question_normalized="where born",
        answer_text=f"answer from {conversation_id or 'no conversation'}",
        model_used="test",
        conversation_id=conversation_id,
    )
    with backend.session() as session:
        backend.cache_store(session, rec)
        backend.cache_store_embedding(session, cache_id, [1.0] + [0.0] * (EMBED_DIM - 1))


def _search(backend, conversation_id):
    with backend.session() as session:
        return semantic_cache_search(
            backend,
            session,
            "where was he born",
            None,
            _StubEmbedder(),
            threshold=0.5,
            max_results=10,
            conversation_id=conversation_id,
        )


# --- the unit the filter turns on ----------------------------------------


def test_null_conversation_on_the_record_is_a_match():
    """THE CASE THE BENCHMARK CANNOT SEE.

    _clear_scratch_db wipes the database before every benchmark run, so every
    entry there has a conversation_id and no benchmark result says anything
    about this. Excluding on absence would make the entire pre-upgrade cache
    unreachable via semantic in one deploy.
    """
    rec = AnswerCacheRecord(conversation_id=None)
    assert _other_conversation(rec, "conv-a") is False


def test_same_conversation_is_a_match():
    assert _other_conversation(AnswerCacheRecord(conversation_id="conv-a"), "conv-a") is False


def test_different_conversation_is_excluded():
    assert _other_conversation(AnswerCacheRecord(conversation_id="conv-b"), "conv-a") is True


def test_caller_without_a_conversation_requests_no_scoping():
    """As with namespace_id: no scope asked for, everything visible."""
    assert _other_conversation(AnswerCacheRecord(conversation_id="conv-b"), None) is False


# --- end to end through the search ---------------------------------------


def test_search_excludes_other_conversations_and_keeps_its_own(backend):
    _seed(backend, "a1", "conv-a")
    _seed(backend, "b1", "conv-b")

    got = {m.record.id for m in _search(backend, "conv-a")}
    assert got == {"a1"}, "conv-b's entry must not reach conv-a"


def test_search_still_returns_entries_with_no_conversation(backend):
    """The pre-upgrade cache keeps working. This is the decision NULL-is-a-match
    encodes, exercised through the real search rather than the helper."""
    _seed(backend, "legacy", None)
    _seed(backend, "b1", "conv-b")

    got = {m.record.id for m in _search(backend, "conv-a")}
    assert got == {"legacy"}, "a NULL-origin entry is servable to any conversation"


def test_unscoped_search_is_unchanged(backend):
    """A caller passing no conversation_id sees what it always saw."""
    _seed(backend, "a1", "conv-a")
    _seed(backend, "b1", "conv-b")
    _seed(backend, "legacy", None)

    got = {m.record.id for m in _search(backend, None)}
    assert got == {"a1", "b1", "legacy"}


# --- through the front door ----------------------------------------------


def test_proxy_write_path_populates_conversation_id(backend):
    """THE TEST THAT WOULD HAVE CAUGHT THE REAL DEFECT.

    Every test above this line passed while the feature did nothing end to end.
    They construct records that already carry a conversation_id and verify the
    filter handles them; none of them verifies that anything SUPPLIES one. The
    proxy write path did not, so every record was written with None, the filter
    treated None as a match as designed, and a full benchmark run came back with
    zero delta on all eight passes.

    A unit test asserts a function is correct when called. Nothing in it asserts
    that anyone calls it. That is this codebase's signature defect — five
    features shipped unreachable with passing tests — and this is the first one
    introduced rather than inherited.

    So this test enters through _run_cache_pipeline and _store_response rather
    than calling store_answer directly. It fails if anyone removes the argument
    at proxy/base.py:1277; a test on store_answer would pass forever regardless
    of whether any caller supplies a conversation.
    """
    from bitmod.proxy.base import BitmodProxy
    from bitmod.router import LLMRouter

    from tests.mock_llm import MockLLM

    proxy = BitmodProxy(backend=backend, llm_router=LLMRouter(primary=MockLLM()), default_model="mock-model")
    question = "where was he born"
    messages = [{"role": "user", "content": question}]

    result = proxy._run_cache_pipeline(question, messages, conversation_id="conv-front-door")
    assert not result.hit, "cold cache — this must be the write path, not a serve"

    proxy._store_response(
        user_message=question,
        answer_text="In Boston, Massachusetts.",
        model_used="mock-model",
        elapsed_ms=0,
        filters=result.filters or {},
        norm=result.norm,
        answer_key=result.answer_key,
        evidence=result.evidence,
        messages_for_context=messages,
        conversation_id="conv-front-door",
    )

    with backend.session() as session:
        stored = backend.cache_lookup(session, result.answer_key)
    assert stored is not None, "the answer should have been cached"
    assert stored.conversation_id == "conv-front-door", (
        "the proxy write path must populate conversation_id; without it the "
        "semantic filter has nothing to act on and silently does nothing"
    )
