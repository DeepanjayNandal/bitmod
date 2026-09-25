#!/usr/bin/env python3
"""BitMod Mega Test — Conductor

Orchestrates a massive end-to-end test with 5 concurrent agents:
  1. Data Loader   — Ingests training Q&A pairs into BitMod
  2. Query Runner   — Fires queries in waves (exact, rephrase, novel, mixed)
  3. Monitor        — Tracks real-time metrics every 5 seconds
  4. Fixer          — Watches for failures and auto-restarts services
  5. Conductor      — This script: coordinates phases, pacing, final report

Usage:
  cd /Users/ryan/Project/bitmod
  .venv/bin/python tests/mega/run_mega_test.py [--concurrency 5] [--skip-download]
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx


def _gateway_auth_headers() -> dict:
    """Credentials for the gateway, empty when BITMOD_API_KEY is unset.

    The gateway accepts one of its BITMOD_API_KEYS as `Authorization: ApiKey
    <key>`. Sending nothing when unset keeps this runnable against a gateway
    with auth disabled.
    """
    import os

    key = os.getenv("BITMOD_API_KEY", "")
    return {"Authorization": f"ApiKey {key}"} if key else {}


# ─── Config ───────────────────────────────────────────────────────

BASE_URL = os.getenv("BITMOD_URL", "http://localhost:8000")
DATA_DIR = Path(__file__).parent / "data"
REPORT_DIR = Path(__file__).parent / "reports"
REPORT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("conductor")

# ─── Shared State ─────────────────────────────────────────────────

@dataclass
class TestMetrics:
    """Thread-safe-ish metrics accumulator (single event loop, no lock needed)."""
    # Ingestion
    ingested: int = 0
    ingest_errors: int = 0
    # Queries
    queries_sent: int = 0
    queries_ok: int = 0
    queries_error: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    # Latency buckets
    latencies: list = field(default_factory=list)
    # Per-wave results
    wave_results: dict = field(default_factory=dict)
    # Layer hit tracking
    layer_hits: dict = field(default_factory=lambda: {
        "exact_cache": 0, "semantic_cache": 0, "composable_cache": 0,
        "fuzzy_match": 0, "skip_llm": 0, "intent_detection": 0,
        "role_assignment": 0, "llm_generation": 0, "double_verify": 0,
    })
    # Errors
    errors: list = field(default_factory=list)
    # Service restarts
    restarts: int = 0
    # Timing
    start_time: float = 0.0
    end_time: float = 0.0

    def hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        return round(self.cache_hits / total * 100, 1) if total > 0 else 0.0

    def avg_latency(self) -> float:
        return round(sum(self.latencies) / len(self.latencies), 1) if self.latencies else 0.0

    def p50(self) -> float:
        if not self.latencies:
            return 0.0
        s = sorted(self.latencies)
        return s[len(s) // 2]

    def p95(self) -> float:
        if not self.latencies:
            return 0.0
        s = sorted(self.latencies)
        return s[int(len(s) * 0.95)]

    def p99(self) -> float:
        if not self.latencies:
            return 0.0
        s = sorted(self.latencies)
        return s[int(len(s) * 0.99)]

metrics = TestMetrics()

# ─── Agent 1: Data Loader ────────────────────────────────────────

async def data_loader(client: httpx.AsyncClient):
    """Ingest training Q&A pairs into BitMod's cache via the chat endpoint."""
    log.info("DATA LOADER — Starting ingestion of training pairs")

    training_file = DATA_DIR / "training_pairs.jsonl"
    if not training_file.exists():
        log.error("Training data not found. Run download_dataset.py first.")
        return

    pairs = [json.loads(line) for line in training_file.read_text().splitlines() if line.strip()]
    log.info(f"DATA LOADER — Loaded {len(pairs)} training pairs")

    # Ingest in batches: send each question through the chat endpoint
    # The response gets cached automatically by the pipeline
    batch_size = 10
    for i in range(0, len(pairs), batch_size):
        batch = pairs[i:i + batch_size]
        tasks = []
        for pair in batch:
            tasks.append(_ingest_one(client, pair))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                metrics.ingest_errors += 1
                metrics.errors.append(f"ingest: {r}")
            else:
                metrics.ingested += 1

        if (i + batch_size) % 100 == 0:
            log.info(f"DATA LOADER — Ingested {metrics.ingested}/{len(pairs)} (errors: {metrics.ingest_errors})")

    log.info(f"DATA LOADER — Complete: {metrics.ingested} ingested, {metrics.ingest_errors} errors")

async def _ingest_one(client: httpx.AsyncClient, pair: dict):
    """Send a single Q&A pair through the chat endpoint to seed the cache."""
    try:
        resp = await client.post(
            f"{BASE_URL}/v1/chat",
            json={"message": pair["question"], "stream": False},
            headers=_gateway_auth_headers(),
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.ReadTimeout:
        # For ingestion, timeouts are OK — the answer still gets cached
        return {"status": "timeout_ok"}

# ─── Agent 2: Query Runner ───────────────────────────────────────

async def query_runner(client: httpx.AsyncClient, concurrency: int):
    """Fire queries in 4 waves, tracking cache behavior."""

    waves = [
        ("exact", DATA_DIR / "exact_queries.jsonl", "Exact repeats — expect ~100% cache hits (Layer 1: Exact Cache + Layer 2: Double Verify)"),
        ("rephrase", DATA_DIR / "rephrase_queries.jsonl", "Paraphrases — testing semantic/fuzzy matching (Layer 3: Semantic Cache + Layer 4: Fuzzy Match)"),
        ("composable", DATA_DIR / "composable_queries.jsonl", "Comparison queries — CA vs TX decomposition (Layer 5: Composable Cache)"),
        ("skip_llm", DATA_DIR / "skip_llm_queries.jsonl", "Deterministic intents — extract/count/list (Layer 6: Skip-LLM)"),
        ("novel", DATA_DIR / "novel_queries.jsonl", "Novel queries — full pipeline (Layer 7: Intent + Layer 8: Role + Layer 9: LLM Generation)"),
    ]

    for wave_name, data_file, description in waves:
        if not data_file.exists():
            log.warning(f"QUERY RUNNER — Skipping wave '{wave_name}': {data_file} not found")
            continue

        queries = [json.loads(line) for line in data_file.read_text().splitlines() if line.strip()]
        log.info(f"\nQUERY RUNNER — Wave '{wave_name}': {len(queries)} queries — {description}")

        wave_metrics = {"hits": 0, "misses": 0, "errors": 0, "latencies": []}
        sem = asyncio.Semaphore(concurrency)

        async def _run_query(q, wm):
            async with sem:
                return await _execute_query(client, q, wm)

        tasks = [_run_query(q, wave_metrics) for q in queries]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Store wave results
        total = wave_metrics["hits"] + wave_metrics["misses"]
        hit_rate = round(wave_metrics["hits"] / total * 100, 1) if total > 0 else 0.0
        avg_lat = round(sum(wave_metrics["latencies"]) / len(wave_metrics["latencies"]), 1) if wave_metrics["latencies"] else 0.0

        metrics.wave_results[wave_name] = {
            "total": total,
            "hits": wave_metrics["hits"],
            "misses": wave_metrics["misses"],
            "errors": wave_metrics["errors"],
            "hit_rate": hit_rate,
            "avg_latency_ms": avg_lat,
        }

        log.info(
            f"QUERY RUNNER — Wave '{wave_name}' complete: "
            f"{total} queries, {hit_rate}% hit rate, {avg_lat}ms avg latency, "
            f"{wave_metrics['errors']} errors"
        )

    # Wave 4: Mixed load (re-run a shuffled mix of all queries)
    log.info("\nQUERY RUNNER — Wave 'mixed': Combined stress test")
    import random
    all_queries = []
    for _, data_file, _ in waves:
        if data_file.exists():
            all_queries.extend(json.loads(line) for line in data_file.read_text().splitlines() if line.strip())
    random.shuffle(all_queries)
    mixed_sample = all_queries[:200]  # 200 mixed queries at higher concurrency

    wave_metrics = {"hits": 0, "misses": 0, "errors": 0, "latencies": []}
    sem = asyncio.Semaphore(concurrency * 2)  # double concurrency for stress

    async def _run_mixed(q, wm):
        async with sem:
            return await _execute_query(client, q, wm)

    tasks = [_run_mixed(q, wave_metrics) for q in mixed_sample]
    await asyncio.gather(*tasks, return_exceptions=True)

    total = wave_metrics["hits"] + wave_metrics["misses"]
    hit_rate = round(wave_metrics["hits"] / total * 100, 1) if total > 0 else 0.0
    avg_lat = round(sum(wave_metrics["latencies"]) / len(wave_metrics["latencies"]), 1) if wave_metrics["latencies"] else 0.0
    metrics.wave_results["mixed"] = {
        "total": total,
        "hits": wave_metrics["hits"],
        "misses": wave_metrics["misses"],
        "errors": wave_metrics["errors"],
        "hit_rate": hit_rate,
        "avg_latency_ms": avg_lat,
    }
    log.info(
        f"QUERY RUNNER — Wave 'mixed' complete: "
        f"{total} queries, {hit_rate}% hit rate, {avg_lat}ms avg latency"
    )

async def _execute_query(client: httpx.AsyncClient, query_record: dict, wave_metrics: dict):
    """Execute a single query and record metrics."""
    question = query_record.get("question", query_record.get("query", ""))
    if not question:
        return

    metrics.queries_sent += 1
    t0 = time.monotonic()

    try:
        resp = await client.post(
            f"{BASE_URL}/v1/chat",
            json={"message": question, "stream": False},
            headers={"X-Bitmod-Debug": "true", **_gateway_auth_headers()},
            timeout=120.0,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000

        if resp.status_code == 200:
            metrics.queries_ok += 1
            data = resp.json()
            cached = data.get("cached", False)

            if cached:
                metrics.cache_hits += 1
                wave_metrics["hits"] += 1
            else:
                metrics.cache_misses += 1
                wave_metrics["misses"] += 1

            metrics.latencies.append(elapsed_ms)
            wave_metrics["latencies"].append(elapsed_ms)

            # Track which pipeline layers were activated
            for step in data.get("pipeline_trace", []):
                mechanism = step.get("mechanism", "")
                action = step.get("action", "")
                if mechanism == "exact_cache" and action == "HIT":
                    metrics.layer_hits["exact_cache"] += 1
                elif mechanism == "semantic_cache" and action in ("HIT", "HIT_DEFERRED"):
                    metrics.layer_hits["semantic_cache"] += 1
                elif mechanism == "composable_cache" and action in ("FULL_HIT", "PARTIAL"):
                    metrics.layer_hits["composable_cache"] += 1
                elif mechanism == "fuzzy_match" and action == "HIT":
                    metrics.layer_hits["fuzzy_match"] += 1
                elif mechanism == "skip_llm" and action == "HANDLED":
                    metrics.layer_hits["skip_llm"] += 1
                elif mechanism == "intent_detection":
                    metrics.layer_hits["intent_detection"] += 1
                elif mechanism == "llm_generation":
                    metrics.layer_hits["llm_generation"] += 1
                elif mechanism == "double_verify":
                    metrics.layer_hits["double_verify"] += 1
        else:
            metrics.queries_error += 1
            wave_metrics["errors"] += 1
            metrics.errors.append(f"HTTP {resp.status_code}: {question[:50]}")

    except Exception as e:
        elapsed_ms = (time.monotonic() - t0) * 1000
        metrics.queries_error += 1
        wave_metrics["errors"] += 1
        metrics.errors.append(f"{type(e).__name__}: {question[:50]}")

# ─── Agent 3: Monitor ────────────────────────────────────────────

async def monitor(stop_event: asyncio.Event):
    """Print real-time metrics every 10 seconds."""
    log.info("MONITOR — Starting real-time metrics collection")

    snapshots = []
    while not stop_event.is_set():
        await asyncio.sleep(10)

        elapsed = time.monotonic() - metrics.start_time if metrics.start_time else 0
        qps = metrics.queries_ok / elapsed if elapsed > 0 else 0

        snapshot = {
            "elapsed_s": round(elapsed, 1),
            "ingested": metrics.ingested,
            "queries_sent": metrics.queries_sent,
            "queries_ok": metrics.queries_ok,
            "cache_hits": metrics.cache_hits,
            "cache_misses": metrics.cache_misses,
            "hit_rate": metrics.hit_rate(),
            "avg_latency_ms": metrics.avg_latency(),
            "qps": round(qps, 2),
            "errors": metrics.queries_error,
        }
        snapshots.append(snapshot)

        log.info(
            f"MONITOR — [{elapsed:.0f}s] "
            f"sent={metrics.queries_sent} ok={metrics.queries_ok} "
            f"hits={metrics.cache_hits} misses={metrics.cache_misses} "
            f"rate={metrics.hit_rate()}% "
            f"lat={metrics.avg_latency():.0f}ms "
            f"qps={qps:.1f} "
            f"err={metrics.queries_error}"
        )

    # Save snapshots
    snapshots_file = REPORT_DIR / "monitor_snapshots.jsonl"
    with open(snapshots_file, "w") as f:
        for s in snapshots:
            f.write(json.dumps(s) + "\n")
    log.info(f"MONITOR — Saved {len(snapshots)} snapshots to {snapshots_file}")

# ─── Agent 4: Fixer ──────────────────────────────────────────────

async def fixer(stop_event: asyncio.Event):
    """Watch for service failures and auto-restart."""
    log.info("FIXER — Watching services for failures")

    while not stop_event.is_set():
        await asyncio.sleep(15)

        # Check gateway
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{BASE_URL}/health", timeout=5.0)
                if resp.status_code != 200:
                    raise Exception(f"Gateway unhealthy: {resp.status_code}")
        except Exception as e:
            log.warning(f"FIXER — Gateway down: {e}. Attempting restart...")
            await _restart_service("gateway", 8000)
            metrics.restarts += 1

        # Check chat service
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get("http://localhost:8001/health", timeout=5.0)
                if resp.status_code != 200:
                    raise Exception(f"Chat service unhealthy: {resp.status_code}")
        except Exception as e:
            log.warning(f"FIXER — Chat service down: {e}. Attempting restart...")
            await _restart_service("chat", 8001)
            metrics.restarts += 1

async def _restart_service(name: str, port: int):
    """Kill and restart a service."""
    log.info(f"FIXER — Restarting {name} on port {port}")
    try:
        # Kill existing
        subprocess.run(["bash", "-c", f"kill $(lsof -ti :{port}) 2>/dev/null"], capture_output=True)
        await asyncio.sleep(2)

        # Restart
        service_dir = f"/Users/ryan/Project/bitmod/services/{name}"
        subprocess.Popen(
            ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(port), "--log-level", "warning"],
            cwd=service_dir,
            stdout=open(f"/tmp/{name}.log", "w"),
            stderr=subprocess.STDOUT,
        )
        await asyncio.sleep(3)
        log.info(f"FIXER — {name} restarted successfully")
    except Exception as e:
        log.error(f"FIXER — Failed to restart {name}: {e}")

# ─── Agent 5: Conductor (main) ───────────────────────────────────

async def run_test(concurrency: int, skip_download: bool):
    """Orchestrate the full mega test."""

    # Phase 0: Verify services are running
    log.info("=" * 70)
    log.info("CONDUCTOR — BitMod Mega Test Starting")
    log.info("=" * 70)

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{BASE_URL}/health", timeout=5.0)
            r.raise_for_status()
            log.info(f"CONDUCTOR — Gateway healthy: {r.json()}")
    except Exception as e:
        log.error(f"CONDUCTOR — Gateway not responding: {e}")
        log.error("Start the gateway first: cd services/gateway && python3 -m uvicorn app.main:app --port 8000")
        return

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("http://localhost:8001/health", timeout=5.0)
            r.raise_for_status()
            log.info(f"CONDUCTOR — Chat service healthy: {r.json()}")
    except Exception as e:
        log.error(f"CONDUCTOR — Chat service not responding: {e}")
        log.error("Start the chat service first: cd services/chat && python3 -m uvicorn app.main:app --port 8001")
        return

    # Phase 0.5: Download dataset if needed
    if not skip_download:
        training_file = DATA_DIR / "training_pairs.jsonl"
        if not training_file.exists():
            log.info("CONDUCTOR — Downloading test datasets...")
            subprocess.run(
                [sys.executable, str(Path(__file__).parent / "download_dataset.py")],
                check=True,
            )
        else:
            lines = sum(1 for _ in training_file.open())
            log.info(f"CONDUCTOR — Using existing dataset ({lines} training pairs)")

    # Get pre-test cache stats
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{BASE_URL}/v1/admin/metrics", timeout=10.0)
            pre_stats = r.json().get("cache", {})
            log.info(
                f"CONDUCTOR — Pre-test cache: {pre_stats.get('total_entries', 0)} entries, "
                f"{pre_stats.get('hit_rate', 0)}% hit rate, "
                f"{pre_stats.get('total_serves', 0)} serves"
            )
    except Exception:
        pre_stats = {}

    metrics.start_time = time.monotonic()
    stop_event = asyncio.Event()

    # Start background agents
    monitor_task = asyncio.create_task(monitor(stop_event))
    fixer_task = asyncio.create_task(fixer(stop_event))

    async with httpx.AsyncClient() as client:
        # Phase 1: Ingest training data
        log.info("\n" + "=" * 70)
        log.info("PHASE 1: Data Ingestion — Seeding the cache")
        log.info("=" * 70)
        await data_loader(client)

        # Phase 2: Query waves
        log.info("\n" + "=" * 70)
        log.info(f"PHASE 2: Query Waves — Concurrency={concurrency}")
        log.info("=" * 70)
        await query_runner(client, concurrency)

    # Stop background agents
    metrics.end_time = time.monotonic()
    stop_event.set()
    await asyncio.gather(monitor_task, fixer_task, return_exceptions=True)

    # Get post-test cache stats
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{BASE_URL}/v1/admin/metrics", timeout=10.0)
            post_stats = r.json().get("cache", {})
    except Exception:
        post_stats = {}

    # Phase 3: Final report
    log.info("\n" + "=" * 70)
    log.info("PHASE 3: Final Report")
    log.info("=" * 70)

    total_time = metrics.end_time - metrics.start_time
    report = {
        "test_metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "duration_s": round(total_time, 1),
            "concurrency": concurrency,
            "base_url": BASE_URL,
        },
        "ingestion": {
            "total": metrics.ingested + metrics.ingest_errors,
            "success": metrics.ingested,
            "errors": metrics.ingest_errors,
        },
        "queries": {
            "total_sent": metrics.queries_sent,
            "total_ok": metrics.queries_ok,
            "total_errors": metrics.queries_error,
            "cache_hits": metrics.cache_hits,
            "cache_misses": metrics.cache_misses,
            "overall_hit_rate": metrics.hit_rate(),
        },
        "latency": {
            "avg_ms": metrics.avg_latency(),
            "p50_ms": round(metrics.p50(), 1),
            "p95_ms": round(metrics.p95(), 1),
            "p99_ms": round(metrics.p99(), 1),
            "total_samples": len(metrics.latencies),
        },
        "throughput": {
            "queries_per_second": round(metrics.queries_ok / total_time, 2) if total_time > 0 else 0,
        },
        "wave_results": metrics.wave_results,
        "cache_before": {
            "entries": pre_stats.get("total_entries", 0),
            "hit_rate": pre_stats.get("hit_rate", 0),
            "serves": pre_stats.get("total_serves", 0),
        },
        "cache_after": {
            "entries": post_stats.get("total_entries", 0),
            "hit_rate": post_stats.get("hit_rate", 0),
            "serves": post_stats.get("total_serves", 0),
        },
        "layer_coverage": metrics.layer_hits,
        "reliability": {
            "service_restarts": metrics.restarts,
            "error_count": len(metrics.errors),
            "sample_errors": metrics.errors[:20],
        },
    }

    # Print report
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║" + "  BITMOD MEGA TEST — FINAL REPORT".center(68) + "║")
    print("╠" + "═" * 68 + "╣")
    print(f"║  Duration: {total_time:.0f}s ({total_time/60:.1f}min)".ljust(69) + "║")
    print(f"║  Concurrency: {concurrency}".ljust(69) + "║")
    print("╠" + "═" * 68 + "╣")
    print("║  INGESTION".ljust(69) + "║")
    print(f"║    Pairs ingested: {metrics.ingested}".ljust(69) + "║")
    print(f"║    Errors: {metrics.ingest_errors}".ljust(69) + "║")
    print("╠" + "═" * 68 + "╣")
    print("║  QUERIES".ljust(69) + "║")
    print(f"║    Total sent: {metrics.queries_sent}".ljust(69) + "║")
    print(f"║    Successful: {metrics.queries_ok}".ljust(69) + "║")
    print(f"║    Cache hits: {metrics.cache_hits}".ljust(69) + "║")
    print(f"║    Cache misses: {metrics.cache_misses}".ljust(69) + "║")
    print(f"║    Overall hit rate: {metrics.hit_rate()}%".ljust(69) + "║")
    print(f"║    Errors: {metrics.queries_error}".ljust(69) + "║")
    print("╠" + "═" * 68 + "╣")
    print("║  LATENCY".ljust(69) + "║")
    print(f"║    Avg: {metrics.avg_latency():.0f}ms".ljust(69) + "║")
    print(f"║    P50: {metrics.p50():.0f}ms  P95: {metrics.p95():.0f}ms  P99: {metrics.p99():.0f}ms".ljust(69) + "║")
    print(f"║    QPS: {metrics.queries_ok / total_time:.1f}".ljust(69) + "║")
    print("╠" + "═" * 68 + "╣")
    print("║  WAVE BREAKDOWN".ljust(69) + "║")
    for wave, wr in metrics.wave_results.items():
        line = f"    {wave}: {wr['total']} queries, {wr['hit_rate']}% hits, {wr['avg_latency_ms']:.0f}ms avg"
        print(f"║  {line}".ljust(69) + "║")
    print("╠" + "═" * 68 + "╣")
    print("║  9-LAYER PIPELINE COVERAGE".ljust(69) + "║")
    layer_names = {
        "exact_cache": "L1 Exact Cache",
        "double_verify": "L2 Double Verify",
        "semantic_cache": "L3 Semantic Cache",
        "fuzzy_match": "L4 Fuzzy Match",
        "composable_cache": "L5 Composable Cache",
        "skip_llm": "L6 Skip-LLM",
        "intent_detection": "L7 Intent Detection",
        "role_assignment": "L8 Role Assignment",
        "llm_generation": "L9 LLM Generation",
    }
    for key, label in layer_names.items():
        count = metrics.layer_hits.get(key, 0)
        status = "TESTED" if count > 0 else "NOT HIT"
        marker = "+" if count > 0 else "-"
        print(f"║    [{marker}] {label}: {count} hits ({status})".ljust(69) + "║")
    tested = sum(1 for v in metrics.layer_hits.values() if v > 0)
    print(f"║    Coverage: {tested}/9 layers tested".ljust(69) + "║")
    print("╠" + "═" * 68 + "╣")
    print("║  CACHE GROWTH".ljust(69) + "║")
    print(f"║    Before: {pre_stats.get('total_entries', '?')} entries".ljust(69) + "║")
    print(f"║    After:  {post_stats.get('total_entries', '?')} entries".ljust(69) + "║")
    print(f"║    Restarts: {metrics.restarts}".ljust(69) + "║")
    print("╚" + "═" * 68 + "╝")

    # Save report
    report_file = REPORT_DIR / f"mega_test_{time.strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nFull report saved to: {report_file}")

    return report

# ─── CLI ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="BitMod Mega Test")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrent queries per wave (default: 5)")
    parser.add_argument("--skip-download", action="store_true", help="Skip dataset download (use existing)")
    args = parser.parse_args()

    asyncio.run(run_test(concurrency=args.concurrency, skip_download=args.skip_download))

if __name__ == "__main__":
    main()
