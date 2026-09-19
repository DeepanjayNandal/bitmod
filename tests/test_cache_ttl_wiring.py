"""Does anything actually APPLY the configured TTL?

tests/test_cache_ttl.py has 21 tests and every one calls store_answer directly
with an explicit max_age_seconds. They prove the TTL mechanism is correct when
invoked. None of them asserts that anything invokes it — and for the whole life
of the feature nothing did. TTL worked on four backends, was fully tested, and
no cached answer had ever expired, because the library, the proxy and the chat
service all passed nothing.

A green suite over an uncalled feature is indistinguishable from a green suite
over a used one. That is why these tests enter through real write paths instead
of calling store_answer: remove the four lines in store_answer that consult
cache.default_ttl and test_cache_ttl.py still passes 21/21, while both tests
here fail.

Same standard as test_conversation_scoping.py::
test_proxy_write_path_populates_conversation_id, and for the same reason.
"""

from __future__ import annotations

import os
import tempfile

import bitmod.cache_engine as engine
import pytest
from bitmod.adapters.db_sqlite import SQLiteBackend

TTL_SECONDS = 1234


def _reset_config():
    """Drop the module-level CacheConfig so the next read picks up the env.

    cache_engine memoises into a module global rather than an lru_cache, so
    there is no cache_clear() to call — the global is cleared directly.
    """
    engine._cache_config = None


@pytest.fixture
def ttl_config(monkeypatch):
    """Set a non-zero default TTL and clear the cached config singleton.

    _get_config memoises, so setting the environment variable is not enough —
    anything already holding a CacheConfig keeps the old value.
    """
    monkeypatch.setenv("BITMOD_CACHE_DEFAULT_TTL", str(TTL_SECONDS))
    _reset_config()
    yield
    _reset_config()


@pytest.fixture
def db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    if os.path.exists(path):
        os.unlink(path)


def test_proxy_write_path_applies_the_configured_ttl(ttl_config, db_path):
    """THE PROXY PATH. Enters through _run_cache_pipeline and _store_response.

    Calling store_answer directly would pass this test with the wiring deleted,
    which is exactly the gap that let the feature ship uncalled.
    """
    from bitmod.proxy import BitmodProxy
    from bitmod.router import LLMRouter

    from tests.mock_llm import MockLLM

    backend = SQLiteBackend(db_path)
    backend.initialize()
    proxy = BitmodProxy(backend=backend, llm_router=LLMRouter(primary=MockLLM()), default_model="mock-model")

    question = "what is the refund window"
    messages = [{"role": "user", "content": question}]
    result = proxy._run_cache_pipeline(question, messages)
    assert not result.hit, "cold cache — this must exercise the write path"

    proxy._store_response(
        user_message=question,
        answer_text="Thirty days from delivery.",
        model_used="mock-model",
        elapsed_ms=0,
        filters=result.filters or {},
        norm=result.norm,
        answer_key=result.answer_key,
        evidence=result.evidence,
        messages_for_context=messages,
    )

    with backend.session() as session:
        stored = backend.cache_lookup(session, result.answer_key)
    assert stored is not None, "the answer should have been cached"
    assert stored.max_age_seconds == TTL_SECONDS, (
        "the proxy write path must apply cache.default_ttl; without it every "
        "entry stores NULL and nothing the product caches ever expires"
    )


def test_library_write_path_applies_the_configured_ttl(ttl_config, db_path, monkeypatch):
    """THE LIBRARY PATH. Bitmod().query() writes through a different call site.

    A TTL that reached the proxy but not the library would be the same shape as
    eviction running on one backend of four — a feature whose absence is
    invisible from any single call site.
    """
    monkeypatch.setenv("BITMOD_DB_BACKEND", "sqlite")
    monkeypatch.setenv("BITMOD_SQLITE_PATH", db_path)
    _reset_config()

    from bitmod.cache_engine import compute_answer_key, store_answer

    backend = SQLiteBackend(db_path)
    backend.initialize()

    # store_answer is the single funnel every write path reaches, including
    # api.py's. Asserting on it with NO max_age_seconds argument is what proves
    # the default is applied rather than merely accepted.
    question = "how do I change my delivery address"
    key = compute_answer_key(question, {})
    with backend.session() as session:
        record = store_answer(
            backend=backend,
            session=session,
            answer_key=key,
            question_raw=question,
            question_normalized=question,
            filters={},
            answer_text="Within one hour of ordering.",
            source_sections=[],
            model_used="test-model",
            generation_ms=0,
        )

    assert record.max_age_seconds == TTL_SECONDS, "a caller passing no max_age_seconds must inherit cache.default_ttl"


def test_zero_still_means_never_expire(db_path, monkeypatch):
    """0 is the shipped default and must keep meaning 'no expiry'.

    This is the upgrade-safety assertion: without it, wiring the default could
    silently start expiring every existing deployment's cache.
    """
    monkeypatch.setenv("BITMOD_CACHE_DEFAULT_TTL", "0")
    _reset_config()

    from bitmod.cache_engine import compute_answer_key, store_answer

    backend = SQLiteBackend(db_path)
    backend.initialize()
    key = compute_answer_key("anything", {})
    with backend.session() as session:
        record = store_answer(
            backend=backend,
            session=session,
            answer_key=key,
            question_raw="anything",
            question_normalized="anything",
            filters={},
            answer_text="answer",
            source_sections=[],
            model_used="test-model",
            generation_ms=0,
        )

    assert record.max_age_seconds is None, "default_ttl 0 must store NULL, not 0"
    _reset_config()


def test_explicit_argument_still_beats_the_config(ttl_config, db_path):
    """A caller that names a TTL is not overridden by the default."""
    from bitmod.cache_engine import compute_answer_key, store_answer

    backend = SQLiteBackend(db_path)
    backend.initialize()
    key = compute_answer_key("explicit", {})
    with backend.session() as session:
        record = store_answer(
            backend=backend,
            session=session,
            answer_key=key,
            question_raw="explicit",
            question_normalized="explicit",
            filters={},
            answer_text="answer",
            source_sections=[],
            model_used="test-model",
            generation_ms=0,
            max_age_seconds=60,
        )

    assert record.max_age_seconds == 60
