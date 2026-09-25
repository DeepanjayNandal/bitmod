#!/usr/bin/env python3
"""BitMod Overnight Test Runner.

Runs progressive test batches through the night, each targeting deeper database
features. Results are logged to tests/overnight_results/.

Batches:
  1. Chat API basics (200 prompts) — cache hit/miss, response structure
  2. Cache validation (replay batch 1) — 100% cache hits expected
  3. Filter variations (200 prompts) — same questions with different filters
  4. Composable cache (50 multi-part questions) — sub-query decomposition
  5. Search endpoint (100 queries) — hybrid search, no LLM
  6. Fuzzy matching (200 near-duplicate prompts) — typos, rewordings
  7. Cache stats + admin metrics verification
  8. Streaming responses (50 prompts) — SSE validation
  9. Cache invalidation + re-generation (50 prompts)
 10. Sustained throughput (500 prompts, 5 concurrent) — stability
 11. Repeat batches 1-3 with fresh prompts (scale to 2000)
 12. Final stats snapshot + full report

Usage:
    python tests/overnight_runner.py
    python tests/overnight_runner.py --api-url https://test.bitmod.io
    python tests/overnight_runner.py --start-batch 5  # resume from batch 5
    python tests/overnight_runner.py --timeout 60
"""

import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def _gateway_auth_headers() -> dict:
    """Credentials for the gateway, empty when BITMOD_API_KEY is unset.

    The gateway accepts one of its BITMOD_API_KEYS as `Authorization: ApiKey
    <key>`. Sending nothing when unset keeps this runnable against a gateway
    with auth disabled.
    """
    import os

    key = os.getenv("BITMOD_API_KEY", "")
    return {"Authorization": f"ApiKey {key}"} if key else {}


try:
    import httpx
except ImportError:
    print("ERROR: httpx is required. Install with: pip install httpx")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_URL = os.getenv("BITMOD_TEST_API_URL", "https://test.bitmod.io")
RESULTS_DIR = Path(__file__).parent / "overnight_results"
TIMEOUT = 120.0  # per-request timeout seconds

# ---------------------------------------------------------------------------
# Prompt generators
# ---------------------------------------------------------------------------

TOPICS = [
    "quantum computing", "blockchain", "machine learning", "climate change",
    "renewable energy", "gene therapy", "artificial intelligence", "nuclear fusion",
    "cybersecurity", "cloud computing", "data privacy", "GDPR", "contract law",
    "supply chain management", "monetary policy", "venture capital", "neural networks",
    "natural language processing", "computer vision", "robotics", "5G networks",
    "edge computing", "IoT", "autonomous vehicles", "cryptocurrency",
    "deep learning", "bioinformatics", "inflation", "antitrust regulation",
    "intellectual property", "behavioral economics", "nanotechnology", "CRISPR",
    "space exploration", "virtual reality", "augmented reality", "3D printing",
]

QUESTION_TEMPLATES = [
    "What is {topic}?",
    "Explain {topic} in simple terms.",
    "What are the main benefits of {topic}?",
    "What are the risks associated with {topic}?",
    "How does {topic} work?",
    "Compare {topic1} and {topic2}.",
    "What is the future of {topic}?",
    "List the top 5 applications of {topic}.",
    "How is {topic} used in healthcare?",
    "What are the ethical implications of {topic}?",
    "Summarize the current state of {topic}.",
    "What regulations apply to {topic}?",
    "How has {topic} evolved over the past decade?",
    "What are the key challenges in {topic}?",
    "Who are the leading companies in {topic}?",
]

FILTER_SETS = [
    {},
    {"jurisdiction": "US"},
    {"jurisdiction": "EU"},
    {"document_type": "regulation"},
    {"document_type": "whitepaper"},
    {"jurisdiction": "US", "document_type": "regulation"},
    {"jurisdiction": "UK"},
    {"jurisdiction": "CA"},
]

TYPO_CHARS = "abcdefghijklmnopqrstuvwxyz"


def make_prompt(rng: random.Random) -> str:
    tmpl = rng.choice(QUESTION_TEMPLATES)
    if "{topic1}" in tmpl:
        t1, t2 = rng.sample(TOPICS, 2)
        return tmpl.format(topic1=t1, topic2=t2)
    return tmpl.format(topic=rng.choice(TOPICS))


def make_multi_part(rng: random.Random) -> str:
    parts = [make_prompt(rng) for _ in range(rng.randint(2, 4))]
    return " Also, ".join(parts)


def add_typo(text: str, rng: random.Random) -> str:
    """Introduce 1-2 random typos."""
    chars = list(text)
    for _ in range(rng.randint(1, 2)):
        if len(chars) > 3:
            idx = rng.randint(1, len(chars) - 2)
            action = rng.choice(["swap", "insert", "delete", "replace"])
            if action == "swap" and idx < len(chars) - 1:
                chars[idx], chars[idx + 1] = chars[idx + 1], chars[idx]
            elif action == "insert":
                chars.insert(idx, rng.choice(TYPO_CHARS))
            elif action == "delete":
                chars.pop(idx)
            elif action == "replace":
                chars[idx] = rng.choice(TYPO_CHARS)
    return "".join(chars)


def reword(text: str, rng: random.Random) -> str:
    """Reword by shuffling words slightly and changing case."""
    words = text.split()
    if len(words) > 4:
        i = rng.randint(0, len(words) - 3)
        words[i], words[i + 1] = words[i + 1], words[i]
    if rng.random() < 0.5:
        text = " ".join(words).lower()
    else:
        text = " ".join(words)
    return text


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class Result:
    prompt: str
    status: int
    cached: bool = False
    response_ms: float = 0.0
    generation_ms: int = 0
    answer_len: int = 0
    error: str | None = None
    cache_key: str | None = None
    filters: dict = field(default_factory=dict)
    stream: bool = False
    # Accuracy metrics (0.0–1.0)
    accuracy_score: float = 0.0
    relevance: float = 0.0
    completeness: float = 0.0
    coherence: float = 0.0


@dataclass
class BatchReport:
    batch_num: int
    name: str
    started: str
    finished: str = ""
    total: int = 0
    successes: int = 0
    cache_hits: int = 0
    errors: int = 0
    avg_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    avg_accuracy: float = 0.0
    avg_relevance: float = 0.0
    avg_completeness: float = 0.0
    avg_coherence: float = 0.0
    results: list[Result] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Response accuracy scoring (heuristic, no LLM judge needed)
# ---------------------------------------------------------------------------

# Refusal / low-quality indicators
_REFUSAL_PHRASES = [
    "i don't know", "i cannot", "i'm unable", "i am unable",
    "i don't have", "i do not have", "no information",
    "not able to", "unable to answer", "i can't",
    "as an ai", "as a language model",
]

_FILLER_PHRASES = [
    "it appears you're testing", "to confirm, i've checked",
    "i'm functioning as intended", "if you'd like to test",
]


def score_response(prompt: str, answer: str) -> tuple[float, float, float, float]:
    """Score a response on relevance, completeness, and coherence.

    Returns (overall, relevance, completeness, coherence) — each 0.0 to 1.0.
    """
    if not answer or not answer.strip():
        return 0.0, 0.0, 0.0, 0.0

    answer_lower = answer.lower()

    # --- Relevance: do the answer's words overlap with the question's topic? ---
    # Extract topic words from the prompt (>3 chars, not stopwords)
    stop = {"what", "which", "where", "when", "does", "how", "that", "this",
            "with", "from", "about", "have", "been", "will", "would", "could",
            "should", "also", "than", "then", "into", "your", "their", "there",
            "some", "other", "more", "most", "very", "just", "like", "over"}
    prompt_words = set()
    for w in prompt.lower().split():
        clean = "".join(c for c in w if c.isalnum())
        if len(clean) > 3 and clean not in stop:
            prompt_words.add(clean)

    if prompt_words:
        answer_words = set()
        for w in answer_lower.split():
            clean = "".join(c for c in w if c.isalnum())
            if len(clean) > 3:
                answer_words.add(clean)
        topic_hits = len(prompt_words & answer_words)
        relevance = min(1.0, topic_hits / max(len(prompt_words), 1))
    else:
        relevance = 0.5  # can't judge without topic words

    # --- Completeness: is it a real answer or a refusal/filler? ---
    is_refusal = any(phrase in answer_lower for phrase in _REFUSAL_PHRASES)
    is_filler = any(phrase in answer_lower for phrase in _FILLER_PHRASES)

    if is_refusal:
        completeness = 0.1
    elif is_filler:
        completeness = 0.2
    elif len(answer) < 50:
        completeness = 0.3
    elif len(answer) < 150:
        completeness = 0.6
    elif len(answer) < 500:
        completeness = 0.8
    else:
        completeness = 1.0

    # --- Coherence: basic structure checks ---
    sentences = [s.strip() for s in answer.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    has_sentences = len(sentences) >= 2
    has_structure = any(c in answer for c in [".", "\n", ":", "-", "1."])
    avg_word_len = sum(len(w) for w in answer.split()) / max(len(answer.split()), 1)
    not_garbled = 2.0 < avg_word_len < 15.0  # reasonable word lengths

    coherence_score = 0.0
    if not_garbled:
        coherence_score += 0.4
    if has_sentences:
        coherence_score += 0.3
    if has_structure:
        coherence_score += 0.3
    coherence = min(1.0, coherence_score)

    # --- Overall: weighted average ---
    overall = 0.4 * relevance + 0.35 * completeness + 0.25 * coherence

    return overall, relevance, completeness, coherence


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

async def chat_request(
    client: httpx.AsyncClient, url: str, prompt: str,
    filters: dict | None = None, stream: bool = False,
    timeout: float = TIMEOUT,
) -> Result:
    payload = {"message": prompt, "stream": stream}
    if filters:
        payload["filters"] = filters

    start = time.perf_counter()
    try:
        resp = await client.post(f"{url}/v1/chat", json=payload, headers=_gateway_auth_headers(), timeout=timeout)
        elapsed = (time.perf_counter() - start) * 1000

        if resp.status_code == 200:
            if stream:
                # For SSE, just check we got data
                body = resp.text
                return Result(
                    prompt=prompt, status=200, cached=False,
                    response_ms=elapsed, answer_len=len(body),
                    stream=True, filters=filters or {},
                )
            data = resp.json()
            answer_text = data.get("answer", "")
            overall, rel, comp, coh = score_response(prompt, answer_text)
            return Result(
                prompt=prompt, status=200,
                cached=data.get("cached", False),
                response_ms=elapsed,
                generation_ms=data.get("generation_ms", 0),
                answer_len=len(answer_text),
                cache_key=data.get("cache_key"),
                filters=filters or {},
                accuracy_score=overall,
                relevance=rel,
                completeness=comp,
                coherence=coh,
            )
        return Result(
            prompt=prompt, status=resp.status_code,
            response_ms=elapsed, error=resp.text[:200],
            filters=filters or {},
        )
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        return Result(
            prompt=prompt, status=0, response_ms=elapsed,
            error=str(e)[:200], filters=filters or {},
        )


async def search_request(
    client: httpx.AsyncClient, url: str, query: str,
    limit: int = 10, jurisdiction: str | None = None,
    document_type: str | None = None,
    timeout: float = TIMEOUT,
) -> Result:
    payload = {"query": query, "limit": limit}
    if jurisdiction:
        payload["jurisdiction"] = jurisdiction
    if document_type:
        payload["document_type"] = document_type

    start = time.perf_counter()
    try:
        resp = await client.post(f"{url}/v1/search", json=payload, timeout=timeout)
        elapsed = (time.perf_counter() - start) * 1000
        if resp.status_code == 200:
            data = resp.json()
            return Result(
                prompt=query, status=200, response_ms=elapsed,
                answer_len=data.get("total", 0),
            )
        return Result(prompt=query, status=resp.status_code, response_ms=elapsed, error=resp.text[:200])
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        return Result(prompt=query, status=0, response_ms=elapsed, error=str(e)[:200])


async def get_json(client: httpx.AsyncClient, url: str, path: str) -> dict:
    try:
        resp = await client.get(f"{url}{path}", timeout=30)
        return resp.json() if resp.status_code == 200 else {"error": resp.status_code}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Batch definitions
# ---------------------------------------------------------------------------

def compute_report(batch_num: int, name: str, results: list[Result], started: str) -> BatchReport:
    times = [r.response_ms for r in results if r.status == 200]
    sorted_times = sorted(times) if times else [0]
    scored = [r for r in results if r.status == 200 and r.accuracy_score > 0]
    return BatchReport(
        batch_num=batch_num, name=name, started=started,
        finished=datetime.now(timezone.utc).isoformat(),
        total=len(results),
        successes=sum(1 for r in results if r.status == 200),
        cache_hits=sum(1 for r in results if r.cached),
        errors=sum(1 for r in results if r.status != 200),
        avg_ms=statistics.mean(times) if times else 0,
        p50_ms=sorted_times[len(sorted_times) // 2] if sorted_times else 0,
        p95_ms=sorted_times[int(len(sorted_times) * 0.95)] if len(sorted_times) > 1 else sorted_times[0],
        p99_ms=sorted_times[int(len(sorted_times) * 0.99)] if len(sorted_times) > 1 else sorted_times[0],
        avg_accuracy=statistics.mean(r.accuracy_score for r in scored) if scored else 0,
        avg_relevance=statistics.mean(r.relevance for r in scored) if scored else 0,
        avg_completeness=statistics.mean(r.completeness for r in scored) if scored else 0,
        avg_coherence=statistics.mean(r.coherence for r in scored) if scored else 0,
        results=results,
    )


def save_report(report: BatchReport, results_dir: Path):
    fname = results_dir / f"batch_{report.batch_num:02d}_{report.name.replace(' ', '_').lower()}.json"
    data = {
        "batch_num": report.batch_num,
        "name": report.name,
        "started": report.started,
        "finished": report.finished,
        "total": report.total,
        "successes": report.successes,
        "cache_hits": report.cache_hits,
        "errors": report.errors,
        "avg_ms": round(report.avg_ms, 1),
        "p50_ms": round(report.p50_ms, 1),
        "p95_ms": round(report.p95_ms, 1),
        "p99_ms": round(report.p99_ms, 1),
        "accuracy": {
            "avg_score": round(report.avg_accuracy, 3),
            "avg_relevance": round(report.avg_relevance, 3),
            "avg_completeness": round(report.avg_completeness, 3),
            "avg_coherence": round(report.avg_coherence, 3),
        },
        "results": [
            {
                "prompt": r.prompt[:100],
                "status": r.status,
                "cached": r.cached,
                "response_ms": round(r.response_ms, 1),
                "generation_ms": r.generation_ms,
                "answer_len": r.answer_len,
                "accuracy": round(r.accuracy_score, 3),
                "error": r.error,
                "filters": r.filters,
            }
            for r in report.results
        ],
    }
    fname.write_text(json.dumps(data, indent=2))
    print(f"  -> Saved: {fname.name}")


def print_batch_summary(report: BatchReport):
    print(f"\n{'='*60}")
    print(f"  Batch {report.batch_num}: {report.name}")
    print(f"  Total: {report.total} | OK: {report.successes} | "
          f"Cached: {report.cache_hits} | Errors: {report.errors}")
    print(f"  Avg: {report.avg_ms:.0f}ms | P50: {report.p50_ms:.0f}ms | "
          f"P95: {report.p95_ms:.0f}ms | P99: {report.p99_ms:.0f}ms")
    if report.avg_accuracy > 0:
        print(f"  Accuracy: {report.avg_accuracy:.0%} | Relevance: {report.avg_relevance:.0%} | "
              f"Completeness: {report.avg_completeness:.0%} | Coherence: {report.avg_coherence:.0%}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Batch runners
# ---------------------------------------------------------------------------

async def batch_1_chat_basics(client: httpx.AsyncClient, url: str, rng: random.Random) -> tuple[BatchReport, list[tuple[str, dict]]]:
    """200 unique chat prompts — test basic generation + caching."""
    started = datetime.now(timezone.utc).isoformat()
    results = []
    sent = []  # (prompt, filters) for replay in batch 2

    print("\n[Batch 1] Chat API Basics — 200 prompts")
    for i in range(200):
        prompt = make_prompt(rng)
        filt = rng.choice(FILTER_SETS[:3])  # simple filters only
        r = await chat_request(client, url, prompt, filters=filt)
        sent.append((prompt, filt))
        results.append(r)
        status = "CACHE" if r.cached else "GEN" if r.status == 200 else "ERR"
        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/200] Last: {status} {r.response_ms:.0f}ms")

    report = compute_report(1, "Chat Basics", results, started)
    return report, sent


async def batch_2_cache_replay(client: httpx.AsyncClient, url: str, sent: list[tuple[str, dict]]) -> BatchReport:
    """Replay all batch 1 queries — expect 100% cache hits."""
    started = datetime.now(timezone.utc).isoformat()
    results = []

    print(f"\n[Batch 2] Cache Replay — {len(sent)} prompts (expect 100% cache hits)")
    for i, (prompt, filt) in enumerate(sent):
        r = await chat_request(client, url, prompt, filters=filt)
        results.append(r)
        if not r.cached and r.status == 200:
            print(f"  WARNING: Cache miss on replay #{i}: {prompt[:50]}...")
        if (i + 1) % 40 == 0:
            hits = sum(1 for r in results if r.cached)
            print(f"  [{i+1}/{len(sent)}] Cache hit rate: {hits}/{i+1} ({100*hits/(i+1):.0f}%)")

    return compute_report(2, "Cache Replay", results, started)


async def batch_3_filter_variations(client: httpx.AsyncClient, url: str, rng: random.Random, base_prompts: list[str]) -> BatchReport:
    """Same prompts with different filters — tests cache key differentiation."""
    started = datetime.now(timezone.utc).isoformat()
    results = []

    # Take 25 base prompts and test with all 8 filter sets = 200 requests
    prompts = base_prompts[:25]
    print(f"\n[Batch 3] Filter Variations — 25 prompts x 8 filter sets = {25 * len(FILTER_SETS)} requests")

    for i, prompt in enumerate(prompts):
        for filt in FILTER_SETS:
            r = await chat_request(client, url, prompt, filters=filt)
            results.append(r)
        if (i + 1) % 5 == 0:
            hits = sum(1 for r in results if r.cached)
            print(f"  [{(i+1)*len(FILTER_SETS)}/{25*len(FILTER_SETS)}] Cache hits: {hits}")

    return compute_report(3, "Filter Variations", results, started)


async def batch_4_composable(client: httpx.AsyncClient, url: str, rng: random.Random) -> BatchReport:
    """Multi-part questions — tests composable cache decomposition."""
    started = datetime.now(timezone.utc).isoformat()
    results = []

    print("\n[Batch 4] Composable Cache — 50 multi-part questions")
    for i in range(50):
        prompt = make_multi_part(rng)
        r = await chat_request(client, url, prompt)
        results.append(r)
        status = "CACHE" if r.cached else "GEN" if r.status == 200 else "ERR"
        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/50] Last: {status} {r.response_ms:.0f}ms, answer_len={r.answer_len}")

    return compute_report(4, "Composable Cache", results, started)


async def batch_5_search(client: httpx.AsyncClient, url: str, rng: random.Random) -> BatchReport:
    """Search endpoint — no LLM, tests hybrid search."""
    started = datetime.now(timezone.utc).isoformat()
    results = []

    queries = [rng.choice(TOPICS) for _ in range(100)]
    print("\n[Batch 5] Search Endpoint — 100 queries")
    for i, q in enumerate(queries):
        jur = rng.choice([None, "US", "EU", "UK"])
        doc_type = rng.choice([None, "regulation", "whitepaper"])
        r = await search_request(client, url, q, jurisdiction=jur, document_type=doc_type)
        results.append(r)
        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/100] Last: status={r.status}, results={r.answer_len}")

    return compute_report(5, "Search Endpoint", results, started)


async def batch_6_fuzzy(client: httpx.AsyncClient, url: str, rng: random.Random, base_prompts: list[str]) -> BatchReport:
    """Near-duplicate prompts — typos, rewordings, case changes."""
    started = datetime.now(timezone.utc).isoformat()
    results = []

    # Take 50 base prompts, create 4 variations each = 200
    prompts = base_prompts[:50]
    print("\n[Batch 6] Fuzzy Matching — 50 prompts x 4 variations = 200 requests")

    for i, base in enumerate(prompts):
        # Original should be cached from batch 1
        r0 = await chat_request(client, url, base)
        results.append(r0)

        # Typo version
        r1 = await chat_request(client, url, add_typo(base, rng))
        results.append(r1)

        # Reworded version
        r2 = await chat_request(client, url, reword(base, rng))
        results.append(r2)

        # Lowercase version
        r3 = await chat_request(client, url, base.lower())
        results.append(r3)

        if (i + 1) % 10 == 0:
            hits = sum(1 for r in results if r.cached)
            print(f"  [{(i+1)*4}/200] Cache hits: {hits}/{len(results)} ({100*hits/len(results):.0f}%)")

    return compute_report(6, "Fuzzy Matching", results, started)


async def batch_7_stats(client: httpx.AsyncClient, url: str) -> BatchReport:
    """Verify cache stats and admin metrics endpoints."""
    started = datetime.now(timezone.utc).isoformat()
    results = []

    print("\n[Batch 7] Stats & Admin Metrics")

    # Cache stats
    stats = await get_json(client, url, "/v1/cache/stats")
    ok = "error" not in stats
    results.append(Result(
        prompt="/v1/cache/stats", status=200 if ok else 500,
        answer_len=len(json.dumps(stats)),
    ))
    print(f"  Cache stats: {'OK' if ok else 'FAIL'}")
    if ok:
        for k, v in stats.items():
            print(f"    {k}: {v}")

    # Admin metrics
    metrics = await get_json(client, url, "/v1/admin/metrics")
    ok = "error" not in metrics
    results.append(Result(
        prompt="/v1/admin/metrics", status=200 if ok else 500,
        answer_len=len(json.dumps(metrics)),
    ))
    print(f"  Admin metrics: {'OK' if ok else 'FAIL'}")
    if ok:
        cache_data = metrics.get("cache", {})
        print(f"    Total cached: {cache_data.get('total_cached', 'N/A')}")
        print(f"    Total served: {cache_data.get('total_served', 'N/A')}")
        print(f"    Hit rate: {cache_data.get('hit_rate', 'N/A')}")
        recent = metrics.get("recent_queries", [])
        print(f"    Recent queries: {len(recent)}")
        models = metrics.get("model_comparison", [])
        print(f"    Model comparison entries: {len(models)}")

    # Health
    health = await get_json(client, url, "/health")
    ok = health.get("status") == "ok"
    results.append(Result(prompt="/health", status=200 if ok else 500))
    print(f"  Health: {'OK' if ok else 'FAIL'}")

    return compute_report(7, "Stats Verification", results, started)


async def batch_8_streaming(client: httpx.AsyncClient, url: str, rng: random.Random) -> BatchReport:
    """Streaming SSE responses."""
    started = datetime.now(timezone.utc).isoformat()
    results = []

    print("\n[Batch 8] Streaming Responses — 50 prompts")
    for i in range(50):
        prompt = make_prompt(rng)
        r = await chat_request(client, url, prompt, stream=True)
        results.append(r)
        if (i + 1) % 10 == 0:
            ok = sum(1 for r in results if r.status == 200)
            print(f"  [{i+1}/50] OK: {ok}/{len(results)}")

    return compute_report(8, "Streaming", results, started)


async def batch_9_invalidation(client: httpx.AsyncClient, url: str, rng: random.Random) -> BatchReport:
    """Cache invalidation + re-generation cycle."""
    started = datetime.now(timezone.utc).isoformat()
    results = []

    print("\n[Batch 9] Invalidation Cycle — 50 prompts (generate, verify cached, invalidate via new filter, regenerate)")

    for i in range(50):
        prompt = make_prompt(rng)

        # First: generate
        r1 = await chat_request(client, url, prompt)
        results.append(r1)

        # Second: should be cached
        r2 = await chat_request(client, url, prompt)
        results.append(r2)
        if r2.status == 200 and not r2.cached:
            print(f"  WARNING: Expected cache hit on prompt #{i}")

        # Third: different filter = different cache key = fresh generation
        r3 = await chat_request(client, url, prompt, filters={"jurisdiction": f"TEST-{i}"})
        results.append(r3)

        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/50] Completed invalidation cycle")

    return compute_report(9, "Invalidation Cycle", results, started)


async def batch_10_throughput(client: httpx.AsyncClient, url: str, rng: random.Random) -> BatchReport:
    """Sustained throughput — 500 prompts, 5 concurrent."""
    started = datetime.now(timezone.utc).isoformat()

    prompts = [make_prompt(rng) for _ in range(500)]
    print("\n[Batch 10] Sustained Throughput — 500 prompts, 5 concurrent")

    sem = asyncio.Semaphore(5)
    results: list[Result] = []

    async def _send(prompt: str, idx: int):
        async with sem:
            r = await chat_request(client, url, prompt)
            results.append(r)
            if (idx + 1) % 50 == 0:
                ok = sum(1 for r in results if r.status == 200)
                print(f"  [{len(results)}/500] OK: {ok}, Errors: {len(results)-ok}")

    tasks = [_send(p, i) for i, p in enumerate(prompts)]
    await asyncio.gather(*tasks)

    return compute_report(10, "Sustained Throughput", results, started)


async def batch_11_scale(client: httpx.AsyncClient, url: str, rng: random.Random) -> BatchReport:
    """Scale run — 2000 fresh prompts, 3 concurrent."""
    started = datetime.now(timezone.utc).isoformat()

    prompts = [make_prompt(rng) for _ in range(2000)]
    print("\n[Batch 11] Scale Run — 2000 prompts, 3 concurrent")

    sem = asyncio.Semaphore(3)
    results: list[Result] = []

    async def _send(prompt: str, idx: int):
        async with sem:
            r = await chat_request(client, url, prompt)
            results.append(r)
            if (idx + 1) % 200 == 0:
                ok = sum(1 for r in results if r.status == 200)
                cached = sum(1 for r in results if r.cached)
                print(f"  [{len(results)}/2000] OK: {ok}, Cached: {cached}, Errors: {len(results)-ok}")

    tasks = [_send(p, i) for i, p in enumerate(prompts)]
    await asyncio.gather(*tasks)

    return compute_report(11, "Scale Run", results, started)


async def batch_12_final_stats(client: httpx.AsyncClient, url: str) -> BatchReport:
    """Final stats snapshot."""
    started = datetime.now(timezone.utc).isoformat()
    results = []

    print("\n[Batch 12] Final Stats Snapshot")

    stats = await get_json(client, url, "/v1/cache/stats")
    metrics = await get_json(client, url, "/v1/admin/metrics")

    results.append(Result(prompt="final_stats", status=200, answer_len=len(json.dumps(stats))))
    results.append(Result(prompt="final_metrics", status=200, answer_len=len(json.dumps(metrics))))

    print(f"  Cache stats: {json.dumps(stats, indent=2)}")
    if "cache" in metrics:
        print(f"  Cache total: {metrics['cache'].get('total_cached', 'N/A')}")
        print(f"  Cache served: {metrics['cache'].get('total_served', 'N/A')}")

    return compute_report(12, "Final Stats", results, started)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

BATCH_RUNNERS = {
    1: "batch_1_chat_basics",
    2: "batch_2_cache_replay",
    3: "batch_3_filter_variations",
    4: "batch_4_composable",
    5: "batch_5_search",
    6: "batch_6_fuzzy",
    7: "batch_7_stats",
    8: "batch_8_streaming",
    9: "batch_9_invalidation",
    10: "batch_10_throughput",
    11: "batch_11_scale",
    12: "batch_12_final_stats",
}


async def main(api_url: str, start_batch: int, timeout: float):
    global TIMEOUT
    TIMEOUT = timeout

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"BitMod Overnight Test Runner")
    print(f"API: {api_url}")
    print(f"Results: {RESULTS_DIR}")
    print(f"Start batch: {start_batch}")
    print(f"Timeout: {timeout}s per request")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*60}")

    # Verify API is reachable
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{api_url}/health", timeout=10)
            if resp.status_code != 200:
                print(f"ERROR: API not healthy (status {resp.status_code})")
                sys.exit(1)
            print(f"API healthy: {resp.json()}")
        except Exception as e:
            print(f"ERROR: Cannot reach API at {api_url}: {e}")
            sys.exit(1)

    rng = random.Random(42)
    all_reports: list[BatchReport] = []
    batch1_sent: list[tuple[str, dict]] = []
    batch1_prompts: list[str] = []

    async with httpx.AsyncClient() as client:
        for batch_num in range(start_batch, 13):
            print(f"\n{'#'*60}")
            print(f"# Starting Batch {batch_num}/12")
            print(f"# Time: {datetime.now().strftime('%H:%M:%S')}")
            print(f"{'#'*60}")

            try:
                if batch_num == 1:
                    report, batch1_sent = await batch_1_chat_basics(client, api_url, rng)
                    batch1_prompts = [p for p, _ in batch1_sent]
                elif batch_num == 2:
                    if not batch1_sent:
                        print("  Skipping batch 2 (no batch 1 data for replay)")
                        continue
                    report = await batch_2_cache_replay(client, api_url, batch1_sent)
                elif batch_num == 3:
                    if not batch1_prompts:
                        batch1_prompts = [make_prompt(rng) for _ in range(50)]
                    report = await batch_3_filter_variations(client, api_url, rng, batch1_prompts)
                elif batch_num == 4:
                    report = await batch_4_composable(client, api_url, rng)
                elif batch_num == 5:
                    report = await batch_5_search(client, api_url, rng)
                elif batch_num == 6:
                    if not batch1_prompts:
                        batch1_prompts = [make_prompt(rng) for _ in range(50)]
                    report = await batch_6_fuzzy(client, api_url, rng, batch1_prompts)
                elif batch_num == 7:
                    report = await batch_7_stats(client, api_url)
                elif batch_num == 8:
                    report = await batch_8_streaming(client, api_url, rng)
                elif batch_num == 9:
                    report = await batch_9_invalidation(client, api_url, rng)
                elif batch_num == 10:
                    report = await batch_10_throughput(client, api_url, rng)
                elif batch_num == 11:
                    report = await batch_11_scale(client, api_url, rng)
                elif batch_num == 12:
                    report = await batch_12_final_stats(client, api_url)

                print_batch_summary(report)
                save_report(report, RESULTS_DIR)
                all_reports.append(report)

            except KeyboardInterrupt:
                print("\n\nInterrupted! Saving partial results...")
                break
            except Exception as e:
                print(f"\n  ERROR in batch {batch_num}: {e}")
                import traceback
                traceback.print_exc()
                continue

    # Final summary
    print(f"\n\n{'='*60}")
    print("OVERNIGHT TEST COMPLETE")
    print(f"{'='*60}")
    total_reqs = sum(r.total for r in all_reports)
    total_ok = sum(r.successes for r in all_reports)
    total_cached = sum(r.cache_hits for r in all_reports)
    total_err = sum(r.errors for r in all_reports)
    print(f"Total requests: {total_reqs}")
    print(f"Successes: {total_ok}")
    print(f"Cache hits: {total_cached}")
    print(f"Errors: {total_err}")
    print(f"Finished: {datetime.now(timezone.utc).isoformat()}")

    # Save summary
    summary = {
        "total_requests": total_reqs,
        "successes": total_ok,
        "cache_hits": total_cached,
        "errors": total_err,
        "batches": [
            {
                "batch": r.batch_num,
                "name": r.name,
                "total": r.total,
                "successes": r.successes,
                "cache_hits": r.cache_hits,
                "errors": r.errors,
                "avg_ms": round(r.avg_ms, 1),
                "p95_ms": round(r.p95_ms, 1),
            }
            for r in all_reports
        ],
    }
    summary_path = RESULTS_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\nSummary saved to: {summary_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BitMod Overnight Test Runner")
    parser.add_argument("--api-url", default=API_URL, help="API base URL")
    parser.add_argument("--start-batch", type=int, default=1, help="Start from batch N")
    parser.add_argument("--timeout", type=float, default=TIMEOUT, help="Per-request timeout (seconds)")
    args = parser.parse_args()

    asyncio.run(main(args.api_url, args.start_batch, args.timeout))
