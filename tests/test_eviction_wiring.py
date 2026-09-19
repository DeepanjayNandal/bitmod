"""Does a configured eviction limit actually reach the eviction?

The mechanism was never in doubt: SQLiteBackend.cache_evict_lru works and is
covered elsewhere. What nothing asserted was that the CONFIGURED limit reaches
it. store_answer declared max_cache_entries with a literal default, _maybe_evict
only consults CacheConfig when it receives None, and no production caller passed
either argument — so cache.max_entries resolved correctly and was discarded one
frame later. Eviction ran at 100,000 regardless of configuration.

This test exists because 7be7059 argued that an untested wiring is exactly how a
feature stays uncalled with a green suite. Fixing this one without a test would
have made that argument selectively applied.

Verified the way the TTL wiring was: revert max_cache_entries and
eviction_interval to their literal defaults and this test fails, while nothing
else in the suite does.
"""

from __future__ import annotations

import os
import tempfile

import bitmod.cache_engine as engine
import pytest
from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.cache_engine import compute_answer_key, store_answer

# Small on purpose. The interval is configurable and this test exercises it
# being configured, so tripping it in a handful of writes is the point rather
# than a shortcut — driving 100 writes would test the same line more slowly.
MAX_ENTRIES = 5
EVICTION_INTERVAL = 2


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("BITMOD_CACHE_MAX_ENTRIES", str(MAX_ENTRIES))
    monkeypatch.setenv("BITMOD_CACHE_EVICTION_INTERVAL", str(EVICTION_INTERVAL))
    engine._cache_config = None
    engine._write_counter = 0
    yield
    engine._cache_config = None
    engine._write_counter = 0


@pytest.fixture
def backend():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    be = SQLiteBackend(path)
    be.initialize()
    yield be
    if os.path.exists(path):
        os.unlink(path)


def _write(be, n: int) -> None:
    """n cache writes through store_answer, passing no eviction arguments.

    Passing none is the whole point: that is what every production caller does,
    and it is the path on which the configured limit was being discarded.
    """
    for i in range(n):
        question = f"question number {i}"
        with be.session() as session:
            store_answer(
                backend=be,
                session=session,
                answer_key=compute_answer_key(question, {}),
                question_raw=question,
                question_normalized=question,
                filters={},
                answer_text=f"answer number {i}",
                source_sections=[],
                model_used="test-model",
                generation_ms=1,
                estimated_cost=0.001,
            )


def _count(be) -> int:
    with be.session() as session:
        return session.execute("SELECT COUNT(*) FROM answer_cache WHERE is_valid = 1").fetchone()[0]


def test_configured_max_entries_is_enforced(configured, backend):
    """THE TEST THAT CATCHES THE SHADOWED DEFAULT.

    With BITMOD_CACHE_MAX_ENTRIES=5, writing 12 distinct answers must leave the
    cache at or below 5. Before the fix it stayed at 12: store_answer sent the
    literal 100_000 into _maybe_evict, cache.max_entries was never read, and
    eviction had nothing to do.
    """
    _write(backend, 12)

    remaining = _count(backend)
    assert remaining <= MAX_ENTRIES, (
        f"{remaining} entries survived with max_entries={MAX_ENTRIES}. The configured "
        "limit is not reaching evict_lru_cache — store_answer is shadowing it with a "
        "literal default."
    )


def test_eviction_does_not_run_below_the_limit(configured, backend):
    """Under the ceiling, nothing is evicted.

    Without this, a test asserting only "count <= 5" would also pass against a
    cache that evicted everything, which is a different bug wearing the same
    number.
    """
    _write(backend, 4)
    assert _count(backend) == 4, "entries below max_entries must survive untouched"
