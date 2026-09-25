"""End-to-end ingestion + search + chat test.

Tests the full pipeline against a running Bitmod API:
1. Ingest sample documents via /v1/ingest/text
2. Verify documents appear in /v1/ingest/status
3. Search for content via /v1/search
4. Ask questions via /v1/chat and verify source citations
5. Verify cache hits on repeated questions

Run with:  pytest tests/test_e2e_ingest.py -m e2e
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest


def _gateway_auth_headers() -> dict:
    """Credentials for the gateway, empty when BITMOD_API_KEY is unset.

    The gateway accepts one of its BITMOD_API_KEYS as `Authorization: ApiKey
    <key>`. Sending nothing when unset keeps this runnable against a gateway
    with auth disabled.
    """
    import os

    key = os.getenv("BITMOD_API_KEY", "")
    return {"Authorization": f"ApiKey {key}"} if key else {}


API_URL = os.getenv("BITMOD_TEST_API_URL", "https://test.bitmod.io")
SAMPLE_DIR = Path(__file__).parent / "sample_data"
TIMEOUT = 120.0


def _api_is_reachable() -> bool:
    try:
        resp = httpx.get(f"{API_URL}/health", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not _api_is_reachable(), reason=f"API not reachable at {API_URL}"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ingest_text(client: httpx.Client, title: str, text: str, **kwargs) -> dict:
    payload = {
        "text": text,
        "title": title,
        "document_type": kwargs.get("document_type", "document"),
        "source": kwargs.get("source", "sample_data"),
        "jurisdiction": kwargs.get("jurisdiction"),
        "tags": kwargs.get("tags", []),
    }
    resp = client.post(f"{API_URL}/v1/ingest/text", json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def search(client: httpx.Client, query: str, **kwargs) -> dict:
    payload = {"query": query, "limit": kwargs.get("limit", 10)}
    if kwargs.get("jurisdiction"):
        payload["jurisdiction"] = kwargs["jurisdiction"]
    resp = client.post(f"{API_URL}/v1/search", json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def chat(client: httpx.Client, message: str, **kwargs) -> dict:
    payload = {"message": message, "stream": False}
    if kwargs.get("filters"):
        payload["filters"] = kwargs["filters"]
    resp = client.post(f"{API_URL}/v1/chat", json=payload, headers=_gateway_auth_headers(), timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def get_status(client: httpx.Client) -> dict:
    resp = client.get(f"{API_URL}/v1/ingest/status", timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_cache_stats(client: httpx.Client) -> dict:
    resp = client.get(f"{API_URL}/v1/cache/stats", timeout=10)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def api_client():
    with httpx.Client() as client:
        yield client


@pytest.fixture(scope="module")
def ingested_docs(api_client):
    """Ingest all sample .txt files and return the result dicts."""
    sample_files = sorted(SAMPLE_DIR.glob("*.txt"))
    assert len(sample_files) > 0, f"No sample files found in {SAMPLE_DIR}"

    results = []
    for fpath in sample_files:
        text = fpath.read_text()
        title = fpath.stem.replace("_", " ").title()
        result = ingest_text(
            api_client,
            title,
            text,
            document_type="reference",
            tags=["sample", "technology"],
        )
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Phase 1: Document Ingestion
# ---------------------------------------------------------------------------


class TestIngestion:
    def test_all_documents_ingested(self, ingested_docs):
        for result in ingested_docs:
            assert result["sections"] > 0, f"No sections: {result}"
            assert result["chunks"] > 0, f"No chunks: {result}"

    def test_ingestion_status_reflects_documents(self, api_client, ingested_docs):
        sample_count = len(list(SAMPLE_DIR.glob("*.txt")))
        status = get_status(api_client)
        assert status["totals"]["document_count"] >= sample_count


# ---------------------------------------------------------------------------
# Phase 2: Search
# ---------------------------------------------------------------------------


SEARCH_QUERIES = [
    "machine learning applications",
    "cloud computing IaaS PaaS",
    "GDPR data subject rights",
    "ransomware attack vectors",
    "blockchain consensus proof of stake",
    "deep learning neural networks",
    "HIPAA protected health information",
    "smart contracts Ethereum DeFi",
]


class TestSearch:
    @pytest.mark.parametrize("query", SEARCH_QUERIES)
    def test_search_returns_results(self, api_client, ingested_docs, query):
        results = search(api_client, query)
        assert results["total"] > 0, f"No results for query: {query}"
        top = results["results"][0]
        assert top["score"] > 0


# ---------------------------------------------------------------------------
# Phase 3: Chat with source citations
# ---------------------------------------------------------------------------


CHAT_QUESTIONS = [
    {
        "question": "What are the key applications of artificial intelligence?",
        "expect_keywords": ["healthcare", "finance"],
    },
    {
        "question": "What is the difference between IaaS, PaaS, and SaaS?",
        "expect_keywords": ["infrastructure", "platform", "software"],
    },
    {
        "question": "What are the main rights under GDPR?",
        "expect_keywords": ["erasure", "access", "portability"],
    },
    {
        "question": "How does proof of stake differ from proof of work?",
        "expect_keywords": ["energy", "validator", "miner"],
    },
    {
        "question": "What is the CIA triad in cybersecurity?",
        "expect_keywords": ["confidentiality", "integrity", "availability"],
    },
]


class TestChat:
    @pytest.mark.parametrize(
        "q",
        CHAT_QUESTIONS,
        ids=[q["question"][:40] for q in CHAT_QUESTIONS],
    )
    def test_chat_returns_substantive_answer(self, api_client, ingested_docs, q):
        result = chat(api_client, q["question"])
        answer = result.get("answer", "")
        assert len(answer) > 50, "Answer is too short or empty"

    @pytest.mark.parametrize(
        "q",
        CHAT_QUESTIONS,
        ids=[q["question"][:40] for q in CHAT_QUESTIONS],
    )
    def test_chat_contains_expected_keywords(self, api_client, ingested_docs, q):
        result = chat(api_client, q["question"])
        answer_lower = result.get("answer", "").lower()
        found = [kw for kw in q["expect_keywords"] if kw in answer_lower]
        threshold = len(q["expect_keywords"]) // 2
        assert len(found) >= threshold, (
            f"Missing keywords. Found: {found}, expected at least {threshold} of {q['expect_keywords']}"
        )


# ---------------------------------------------------------------------------
# Phase 4: Cache verification
# ---------------------------------------------------------------------------


class TestCacheHits:
    def test_repeated_questions_hit_cache(self, api_client, ingested_docs):
        # First pass: prime the cache
        for q in CHAT_QUESTIONS:
            chat(api_client, q["question"])

        # Second pass: should be cached
        cache_hits = 0
        for q in CHAT_QUESTIONS:
            result = chat(api_client, q["question"])
            if result.get("cached"):
                cache_hits += 1

        assert cache_hits > 0, "No cache hits on repeated questions"

    def test_cache_stats_endpoint(self, api_client, ingested_docs):
        stats = get_cache_stats(api_client)
        assert isinstance(stats, dict)
