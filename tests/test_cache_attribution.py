"""Which cache layer served a hit, exposed to the caller.

The pipeline computes full attribution — every contributing layer with its own
confidence, and an accumulated total — and then discarded it. One derived label
went to usage_tracking and nothing reached the response, so a surprising cache
hit could not be debugged from outside the process.

That label was also wrong. It came from scanning the trace for an action of
"HIT" or "FULL_HIT", which only exact match and composable emit; every other
layer emits "EVIDENCE". So a serve decided on accumulated confidence reported
the layer that had *missed*. The same defaulting was in the gateway's
X-Bitmod-Cache-Layer header, so production reported it wrongly too.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.cache_engine import CacheEvidence, PipelineEvidence, compute_answer_key, normalize_query, store_answer
from bitmod.interfaces.llm import LLMProvider, LLMResponse
from bitmod.proxy import BitmodProxy
from bitmod.proxy.debug import (
    HEADER_CACHE,
    HEADER_CONFIDENCE,
    HEADER_LAYERS,
    HEADER_SERVED_BY,
    cache_debug_headers,
    debug_enabled,
)
from bitmod.router import LLMRouter

EMBED_DIM = 384
QUESTION = "what is the refund policy"


class _StubEmbedder:
    def embed(self, text: str) -> list[float]:
        return [1.0] + [0.0] * (EMBED_DIM - 1)


class _StubLLM(LLMProvider):
    async def generate(self, messages, model="", tools=None, temperature=0.0, max_tokens=4096):
        return LLMResponse(content="generated", model=model or "stub", usage={})

    async def stream(self, messages, model="", temperature=0.0, max_tokens=4096):
        yield "generated"


class _Request:
    """Minimal stand-in for a Starlette request."""

    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {}


@pytest.fixture
def proxy():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    backend = SQLiteBackend(path)
    backend.initialize()
    p = BitmodProxy(backend=backend, llm_router=LLMRouter(primary=_StubLLM()), default_model="stub")
    p._embedder = _StubEmbedder()
    yield p
    if os.path.exists(path):
        os.unlink(path)


def _seed(proxy, question: str, answer: str) -> None:
    with proxy._backend.session() as session:
        store_answer(
            backend=proxy._backend,
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


# ---------------------------------------------------------------------------
# Attribution is correct, including for accumulated-confidence serves
# ---------------------------------------------------------------------------


def test_exact_hit_is_attributed_to_exact(proxy):
    _seed(proxy, QUESTION, "Five business days.")
    result = proxy._run_cache_pipeline(QUESTION, [{"role": "user", "content": QUESTION}])
    headers = cache_debug_headers(result)

    assert headers[HEADER_CACHE] == "hit"
    assert headers[HEADER_SERVED_BY] == "exact"


def test_semantic_hit_is_not_attributed_to_exact(proxy):
    """REGRESSION GUARD — this is the case the old derivation got wrong.

    Exact match missed. The serve came from accumulated confidence, and the
    previous logic reported "exact" because no trace step carried a HIT action.
    """
    _seed(proxy, QUESTION, "Five business days.")
    other = "how long do refunds take"
    result = proxy._run_cache_pipeline(other, [{"role": "user", "content": other}])

    assert result.hit is True, "precondition: the stub embedder should make this match"
    headers = cache_debug_headers(result)
    assert headers[HEADER_SERVED_BY] == "semantic", (
        f"attributed to {headers.get(HEADER_SERVED_BY)!r}; exact match did not serve this"
    )
    assert headers[HEADER_SERVED_BY] != "exact"


def test_every_contributing_layer_is_listed_with_its_confidence(proxy):
    """A single label loses the point: several layers contribute to one serve."""
    _seed(proxy, QUESTION, "Five business days.")
    other = "how long do refunds take"
    result = proxy._run_cache_pipeline(other, [{"role": "user", "content": other}])

    layers = cache_debug_headers(result)[HEADER_LAYERS]
    assert ":" in layers, f"expected 'layer:confidence' pairs, got {layers!r}"
    for entry in layers.split(","):
        name, _, confidence = entry.partition(":")
        assert name
        float(confidence)  # must parse


def test_confidence_header_matches_the_accumulated_total(proxy):
    _seed(proxy, QUESTION, "Five business days.")
    result = proxy._run_cache_pipeline(QUESTION, [{"role": "user", "content": QUESTION}])
    headers = cache_debug_headers(result)
    assert float(headers[HEADER_CONFIDENCE]) == pytest.approx(result.evidence.total_confidence, abs=1e-4)


def test_miss_is_reported_as_miss(proxy):
    result = proxy._run_cache_pipeline("nothing cached about this", [{"role": "user", "content": "x"}])
    headers = cache_debug_headers(result)
    assert headers[HEADER_CACHE] == "miss"
    assert HEADER_SERVED_BY not in headers


def test_served_by_uses_best_single_answer_not_the_trace():
    """The derivation, isolated from the pipeline.

    best_single_answer() returns the entry that was actually served. Scanning
    the trace cannot: layers other than exact and composable never emit a HIT
    action, so the scan falls through to its default.
    """

    class _Result:
        hit = True
        trace: list = []  # deliberately empty — the old logic had nothing to find

        def __init__(self):
            self.evidence = PipelineEvidence()
            self.evidence.add(CacheEvidence(layer="fuzzy", confidence=0.40, answer_text="a"))
            self.evidence.add(CacheEvidence(layer="similarity_link", confidence=0.55, answer_text="b"))

    headers = cache_debug_headers(_Result())
    assert headers[HEADER_SERVED_BY] == "similarity_link", "should name the highest-confidence contributor"


def test_attribution_never_raises_on_a_malformed_result():
    """Attribution is diagnostic. It must not be able to break a response."""

    class _Broken:
        hit = True
        evidence = None
        trace = None

    assert cache_debug_headers(_Broken())[HEADER_CACHE] == "hit"


# ---------------------------------------------------------------------------
# When it is exposed
# ---------------------------------------------------------------------------


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("BITMOD_DEBUG", raising=False)
    assert debug_enabled(_Request(), authenticated=True) is False


def test_env_var_enables_it_everywhere(monkeypatch):
    monkeypatch.setenv("BITMOD_DEBUG", "true")
    assert debug_enabled(None, authenticated=False) is True


def test_header_enables_it_for_an_authenticated_request(monkeypatch):
    monkeypatch.delenv("BITMOD_DEBUG", raising=False)
    request = _Request({"x-bitmod-debug": "true"})
    assert debug_enabled(request, authenticated=True) is True


def test_header_is_ignored_when_unauthenticated(monkeypatch):
    """The proxy's format endpoints are customer-facing.

    An unauthenticated caller must not be able to probe which cached entries
    exist or how confident the cache was. The environment variable is a
    deployment decision; the header is a request-level one and needs the
    request to have proved who it is first.
    """
    monkeypatch.delenv("BITMOD_DEBUG", raising=False)
    request = _Request({"x-bitmod-debug": "true"})
    assert debug_enabled(request, authenticated=False) is False


def test_header_values_are_single_line():
    """Header injection guard — a layer name reaching a header must not carry CRLF."""

    class _Result:
        hit = True
        trace: list = []

        def __init__(self):
            self.evidence = PipelineEvidence()
            self.evidence.add(CacheEvidence(layer="bad\r\nX-Injected: yes", confidence=0.9, answer_text="a"))

    for value in cache_debug_headers(_Result()).values():
        assert "\r" not in value and "\n" not in value
